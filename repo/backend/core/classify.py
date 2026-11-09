"""B4. 원인 분류 (누수 / 막힘 / 펌프 / 센서). 규칙 기반이며 기준값은 모두 가설이다.

채널별(공급-회수 불균형, 입구 질량유량, 공급 압력, 회수 압력, 출구-입구 온도차) 잔차를 EWMA로 보고,
처음 이상이 잡힌 뒤 30분 시점의 패턴으로 원인을 구분한다.

규칙(현장 확인 전 가설):
- 센서 고착      : 한 계측값이 변하지 않음(표준편차 0)
- 펌프 이상      : 공급 압력이 낮아지고 입구 유량이 줄어드는 묶음이 3개 이상
- 막힘           : 회수 압력이 올라가고 그 묶음의 입구 유량이 줄어듦
- 누수 / 계측 이상: 패턴 모델(core.pattern)이 있으면 9개 신호의 변화 방향을 고장별 기준 방향과 비교해 가른다.
                    1위와 2위의 각도 차이가 작으면 '구분 불가(ambiguous)'. 모델이 없으면 아래 옛 규칙을 쓴다.
  (옛 규칙) 불균형이 커지고 입구 유량이 늘면 누수, 늘지 않으면 유량계 의심
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
MAX_WAIT = 720           # 원인이 가려지지 않을 때 더 기다려 보는 최대 시간(분)


@dataclass
class Diagnosis:
    cause: str                      # leak / clog / pump / sensor / ambiguous / unknown
    group: int | None
    alarm_ts: int | None
    diag_ts: int | None
    evidence: list[str] = field(default_factory=list)
    pattern: dict | None = None     # core.pattern 판정 결과(근거 표시용)


class DiagnosisModel:
    def __init__(self, baseline: Baseline, pattern=None) -> None:
        self.bl = baseline
        self.thr: dict[tuple[int, str], float] = {}
        self.pattern = pattern          # core.pattern.PatternModel | None
        self._zdf = None
        self._zm: dict = {}

    def zmats(self, df, groups):
        """df별 (T, 9) 잔차 행렬 캐시."""
        if self._zdf is not df:
            from .pattern import zmatrix
            self._zdf, self._zm = df, {g: zmatrix(self.bl, df, g, groups) for g in groups}
        return self._zm

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
        last, amb = None, None
        for t_d in range(min(t_alarm + CONFIRM_DELAY, T - 1), min(t_alarm + MAX_WAIT, T - 1) + 1, 30):
            last = self._classify_at(df, groups, E, t_d, t_alarm)
            if last.cause == "ambiguous":          # 구분 불가는 시간이 더 쌓이면 갈릴 수 있으니 끝까지 기다려 본다
                amb = last
                continue
            if last.cause != "unknown":
                return last
        if amb is not None:
            return amb
        return last if last is not None else Diagnosis("unknown", g_first, t_alarm, None, [f"묶음 {g_first}의 {ch_first} 이상"])

    def diagnose_final(self, df, groups, E: dict | None = None) -> Diagnosis:
        """짧게 지나가는 이상(오경보)이나 원인이 판정되지 않는 이상은 건너뛰고, 계속 이어지는 이상만 원인으로 확정한다.
        (서비스와 평가가 같은 방식으로 쓴다.)"""
        if E is None:
            E = {g: self.series(df, g) for g in groups}
        T = len(df)

        def persistent(dg: Diagnosis) -> bool:
            for dt in (60, 120):
                t = (dg.diag_ts or 0) + dt
                if t >= T:
                    return True
                if self._classify_at(df, groups, E, t, dg.alarm_ts).cause != dg.cause:
                    return False
            return True

        start = 0
        d = self.diagnose(df, groups, start=start, E=E)
        while d.alarm_ts is not None:
            if d.cause != "unknown" and persistent(d):
                break
            start = d.alarm_ts + 60
            if start >= T - 1:
                return Diagnosis("unknown", None, None, None, ["이상 징후 없음"])
            d = self.diagnose(df, groups, start=start, E=E)
        return d

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
        # 4) 누수 / 계측 이상
        if self.pattern is not None:
            return self._pattern_step(df, groups, E, t_d, t_alarm)
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

    # ---- 패턴(방향 매칭) ----------------------------------------------------
    def _pattern_step(self, df, groups, E, t_d, t_alarm) -> Diagnosis:
        # 가장 크게 벗어난 묶음
        g = max(groups, key=lambda x: max(abs(E[x][ch][t_d]) / self.thr[(x, ch)] for ch in CHANNELS))
        e = E[g]["imb_mass"]
        s0 = np.sign(e[t_alarm]) if abs(e[t_alarm]) > 0 else 1.0
        onset = t_alarm
        while onset > 0 and t_alarm - onset < 720 and e[onset - 1] * s0 > 0:
            onset -= 1
        res = self.pattern.classify(self.zmats(df, groups)[g], g, t_d, onset)
        if res is None:
            return Diagnosis("unknown", g, t_alarm, t_d, [f"묶음 {g}: 패턴을 읽을 만큼 신호가 쌓이는 중"])
        pd_ = res.to_dict()
        if res.label is None:
            return Diagnosis("unknown", g, t_alarm, t_d, [f"묶음 {g}: 변화가 정상 잡음 수준이라 원인을 가리지 않음"], pd_)
        top, second = res.ranking[0], res.ranking[1]
        if res.ambiguous:
            return Diagnosis("ambiguous", g, t_alarm, t_d,
                             [f"묶음 {g}: '{top['label']}'({top['angle']:.0f}°)와 '{second['label']}'({second['angle']:.0f}°)의 모습이 비슷해 구분되지 않음"], pd_)
        if res.label == "leak":
            return Diagnosis("leak", g, t_alarm, t_d, [f"묶음 {g}: 신호 변화 방향이 누수와 가장 가까움({top['angle']:.0f}°, 다음 후보 '{second['label']}' {second['angle']:.0f}°)"], pd_)
        return Diagnosis("sensor", g, t_alarm, t_d, [f"묶음 {g}: 신호 변화 방향이 '{top['label']}'와 가장 가까움({top['angle']:.0f}°). 계측기 확인 필요"], pd_)
