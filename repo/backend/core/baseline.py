"""B2. 운전점 보정 기준선.

묶음마다, 운전 조건(주조 속도, 강종, 공급 수온, 속도 변화의 지연 효과)에서 정상값을 예측하는
선형 회귀를 만들고 잔차(실측 − 예측)를 낸다. 설명 가능성이 우선이라 선형 회귀로 시작한다.

잔차는 정상 구간 잔차의 표준편차로 나눠 z 값으로도 제공한다 (변화 탐지기 입력).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .normalize import group_signals, groups_in

# 정상값을 예측해서 잔차를 내는 채널
CHANNELS = ["imb_mass", "m_in", "p_in", "p_out", "dt"]
SPEED_LAGS = (0, 1, 2, 3, 5, 8, 12, 20, 30)


def operating_features(df: pd.DataFrame, t_in: np.ndarray | None = None) -> np.ndarray:
    """운전 조건 특성 행렬. 속도의 지연값(FIR)으로 과도 응답을 근사한다."""
    v = df["cast_speed"].to_numpy(dtype=float)
    grade_b = (df["steel_grade"].to_numpy() == "B").astype(float)
    cols = []
    for k in SPEED_LAGS:
        cols.append(np.concatenate([np.full(k, v[0]), v[: len(v) - k]]) if k else v)
    cols.append(grade_b)
    cols.append(v * grade_b)
    if t_in is not None:
        cols.append(t_in)
    X = np.column_stack(cols)
    return X


@dataclass
class GroupBaseline:
    group: int
    coef: dict[str, np.ndarray] = field(default_factory=dict)
    mu: np.ndarray | None = None
    sd: np.ndarray | None = None
    res_sd: dict[str, float] = field(default_factory=dict)
    ar1: dict[str, float] = field(default_factory=dict)


class Baseline:
    def __init__(self) -> None:
        self.groups: dict[int, GroupBaseline] = {}

    # ---- 학습 ----------------------------------------------------------
    def fit(self, df: pd.DataFrame) -> "Baseline":
        for g in groups_in(df):
            sig = group_signals(df, g)
            X = operating_features(df, sig["t_in"].to_numpy())
            mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
            Z = np.column_stack([(X - mu) / sd, np.ones(len(X))])
            gb = GroupBaseline(group=g, mu=mu, sd=sd)
            for ch in CHANNELS:
                y = sig[ch].to_numpy()
                beta, *_ = np.linalg.lstsq(Z, y, rcond=None)
                res = y - Z @ beta
                gb.coef[ch] = beta
                gb.res_sd[ch] = float(res.std())
                gb.ar1[ch] = float(np.corrcoef(res[:-1], res[1:])[0, 1])
            self.groups[g] = gb
        return self

    # ---- 예측·잔차 -----------------------------------------------------
    def predict(self, df: pd.DataFrame, g: int) -> pd.DataFrame:
        gb = self.groups[g]
        sig = group_signals(df, g)
        X = operating_features(df, sig["t_in"].to_numpy())
        Z = np.column_stack([(X - gb.mu) / gb.sd, np.ones(len(X))])
        return pd.DataFrame({ch: Z @ gb.coef[ch] for ch in CHANNELS}, index=df.index)

    def residuals(self, df: pd.DataFrame, g: int) -> pd.DataFrame:
        """열: 채널별 잔차(res_*)와 정상 표준편차로 나눈 z(z_*)."""
        gb = self.groups[g]
        sig = group_signals(df, g)
        pred = self.predict(df, g)
        out = {}
        for ch in CHANNELS:
            r = sig[ch].to_numpy() - pred[ch].to_numpy()
            out[f"res_{ch}"] = r
            out[f"z_{ch}"] = r / gb.res_sd[ch]
        return pd.DataFrame(out, index=df.index)
