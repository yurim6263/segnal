"""B17 비교용 ML 검출기: Isolation Forest.

두 가지 입력을 비교한다.
- residual: 운전점 보정 기준선의 잔차(z) 5개 채널
- raw     : 원시 센서값 + 운전 조건(주조 속도, 강종, 공급 수온) — 기준선 없이 모델이 운전점 영향을 스스로 배워야 함

점수는 15분 이동평균으로 매끄럽게 한 뒤, 다른 검출기와 같은 오경보율이 되도록 임계값을 맞춰서 비교한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .baseline import Baseline
from .normalize import group_signals


def _features(df: pd.DataFrame, bl: Baseline, g: int, kind: str) -> np.ndarray:
    if kind == "residual":
        r = bl.residuals(df, g)
        return r[[c for c in r.columns if c.startswith("z_")]].to_numpy()
    sig = group_signals(df, g)
    grade_b = (df["steel_grade"].to_numpy() == "B").astype(float)
    return np.column_stack([
        sig["imb_vol"], sig["m_in"], sig["p_in"], sig["p_out"], sig["dt"],
        df["cast_speed"].to_numpy(), grade_b, sig["t_in"],
    ])


class IForestDetector:
    def __init__(self, kind: str = "residual", n_estimators: int = 200, smooth: int = 15, seed: int = 0) -> None:
        assert kind in ("residual", "raw")
        self.kind, self.smooth = kind, smooth
        self.n_estimators, self.seed = n_estimators, seed
        self.models: dict[int, IsolationForest] = {}

    def fit(self, df_train: pd.DataFrame, bl: Baseline, groups: list[int]) -> "IForestDetector":
        for g in groups:
            X = _features(df_train, bl, g, self.kind)
            m = IsolationForest(n_estimators=self.n_estimators, contamination="auto", random_state=self.seed, n_jobs=1)
            m.fit(X[:: 2])                     # 14일 중 절반만 써도 충분
            self.models[g] = m
        return self

    def score(self, df: pd.DataFrame, bl: Baseline, g: int) -> np.ndarray:
        X = _features(df, bl, g, self.kind)
        raw = -self.models[g].score_samples(X)       # 클수록 이상
        k = self.smooth
        kernel = np.ones(k) / k
        sm = np.convolve(np.concatenate([np.full(k - 1, raw[0]), raw]), kernel, mode="valid")
        return sm
