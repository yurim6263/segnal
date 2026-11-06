"""B4. 원인 분류 (누수 / 막힘 / 펌프 / 센서). 규칙 기반이며 기준값은 모두 가설이다.

채널별(공급-회수 불균형, 입구 질량유량, 공급 압력, 회수 압력, 출구-입구 온도차) 잔차를 EWMA로 보고,
처음 이상이 잡힌 뒤 30분 시점의 패턴으로 원인을 구분한다.

규칙(현장 확인 전 가설):
- 센서 고착      : 한 계측값이 변하지 않음(표준편차 0)
- 펌프 이상      : 공급 압력이 낮아지고 입구 유량이 줄어드는 묶음이 3개 이상
- 막힘           : 회수 압력이 올라가고 그 묶음의 입구 유량이 줄어듦
- 누수           : 공급-회수 불균형이 커지고 입구 유량은 줄지 않음
- 센서 오프셋 의심: 불균형은 커졌는데 입구 유량 변화가 없음 (유량계 문제 가능)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .baseline import Baseline
from .detect import ewma, recenter

CHANNELS = ["imb_mass", "m_in", "p_in", "p_out", "dt"]
LAM = 0.1
CONFIRM_DELAY = 30       # 처음 이상이 잡힌 뒤 원인을 판단하기까지 기다리는 시간(분)


@dataclass
class Diagnosis:
    cause: str                      # leak / clog / pump / sensor / unknown
    group: int | None
    alarm_ts: int | None
    diag_ts: int | None
    evidence: list[str] = field(default_factory=list)


class DiagnosisModel:
    def __init__(self, baseline: Baseline) -> None:
        self.bl = baseline
        self.thr: dict[tuple[int, str], float] = {}

    def series(self, df: pd.DataFrame, g: int) -> dict[str, np.ndarray]:
        r = self.bl.residuals(df, g)
        return {ch: ewma(recenter(r[f"z_{ch}"].to_numpy()), LAM) for ch in CHANNELS}

    def fit(self, df_train: pd.DataFrame, groups: list[int], margin_sd: float = 1.0) -> "DiagnosisModel":
        from eval.common import calibrate_threshold   # 같은 보정 규칙을 쓴다
        for g in groups:
            for ch, e in self.series(df_train, g).items():
                a = np.abs(e)
                self.thr[(g, ch)] = calibrate_threshold(a, 1, 30, 1) + margin_sd * float(np.std(a))
        return self

    # ---- 진단 ---------------------------------------------------------
    def diagnose(self, df: pd.DataFrame, groups: list[int], start: int = 0, E: dict | None = None) -> Diagnosis:
        if E is None:
            E = {g: self.series(df, g) for g in groups}
        T = len(df)
        # 처음 이상이 잡힌 시각: 어느 채널이든 임계값을 5분 연속 넘는 첫 시점
        t_alarm, g_first, ch_first = None, None, None
        for g in groups:
            for ch in CHANNELS:
                over = np.abs(E[g][ch][start:]) > self.thr[(g, ch)]
                run = np.convolve(over.astype(int), np.ones(5, dtype=int), mode="valid")
                idx = np.flatnonzero(run >= 5)
                if idx.size:
                    t = int(idx[0] + start + 4)
                    if t_alarm is None or t < t_alarm:
                        t_alarm, g_first, ch_first = t, g, ch
        if t_alarm is None:
            return Diagnosis("unknown", None, None, None, ["이상 징후 없음"])
        # 서서히 진행되는 이상은 패턴이 늦게 완성되므로, 원인이 가려질 때까지 30분씩 늘려 가며 다시 본다 (최대 8시간)
        last = None
        for t_d in range(min(t_alarm + CONFIRM_DELAY, T - 1), min(t_alarm + 480, T - 1) + 1, 30):
            last = self._classify_at(df, groups, E, t_d, t_alarm)
            if last.cause != "unknown":
                return last
        return last if last is not None else Diagnosis("unknown", g_first, t_alarm, None, [f"묶음 {g_first}의 {ch_first} 이상"])

    def _classify_at(self, df, groups, E, t_d, t_alarm) -> Diagnosis:
        def sig(g, ch):                      # 부호 있는 상태: +1 임계 초과, −1 임계 미만, 0 정상
            v, th = E[g][ch][t_d], self.thr[(g, ch)]
            return 1 if v > th else (-1 if v < -th else 0)

        # 1) 센서 고착
        for g in groups:
            for col in (f"g{g}_flow_in", f"g{g}_flow_out", f"g{g}_p_in", f"g{g}_p_out"):
                w = df[col].to_numpy()[max(t_d - 60, 0): t_d + 1]
                if len(w) > 30 and np.ptp(w) < 1e-9:
                    return Diagnosis("sensor", g, t_alarm, t_d, [f"묶음 {g}의 {col.split('_', 1)[1]} 값이 변하지 않음(고착)"])
        # 2) 펌프 이상: 여러 묶음에서 공급 압력↓·입구 유량↓
        pump_groups = [g for g in groups if sig(g, "p_in") < 0 and sig(g, "m_in") < 0]
        if len(pump_groups) >= 3:
            return Diagnosis("pump", None, t_alarm, t_d, [f"{len(pump_groups)}개 묶음에서 공급 압력과 입구 유량이 함께 낮아짐"])
        # 3) 막힘: 회수 압력↑ + 입구 유량↓
        for g in groups:
            if sig(g, "p_out") > 0 and sig(g, "m_in") <= 0:
                return Diagnosis("clog", g, t_alarm, t_d, [f"묶음 {g}의 회수 압력이 올라가고 입구 유량이 줄어듦"])
        # 4) 누수 / 센서 오프셋
        best = None
        for g in groups:
            if sig(g, "imb_mass") > 0:
                v = E[g]["imb_mass"][t_d] / self.thr[(g, "imb_mass")]
                if best is None or v > best[1]:
                    best = (g, v)
        if best is not None:
            g = best[0]
            if sig(g, "m_in") >= 0 and E[g]["m_in"][t_d] > 0.5 * self.thr[(g, "m_in")]:
                return Diagnosis("leak", g, t_alarm, t_d, [f"묶음 {g}에서 공급-회수 불균형이 커지고 입구 유량이 늘어남"])
            return Diagnosis("sensor", g, t_alarm, t_d, [f"묶음 {g}의 불균형만 커지고 입구 유량 변화가 없음(유량계 확인 필요)"])
        return Diagnosis("unknown", None, t_alarm, t_d, ["원인 규칙에 맞지 않는 이상"])
