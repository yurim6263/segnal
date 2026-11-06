"""연주기 기계 냉각수 회로의 '진실' 상태 계산 (센서 잡음 이전).

모델 요약 (모든 파라미터는 config/plant.yaml의 가설):
- 펌프 곡선: P_header = P0 − a·Q_total²
- 세그먼트 N개가 병렬 분기, 분기 저항 K_i (ΔP = K_i·Q²). 유량 설정(밸브)은 주조 속도에 따라 φ만큼 변한다.
- 누수: 분기 안의 위치(분기 길이 대비 비율 f)에서 압력 의존 싱크  Q_leak = C·sqrt(P_local)
  P_local = P_return + (1−f)·ΔP_branch  → 입구쪽 누수일수록 압력이 높아 더 많이 샌다.
- 막힘: 분기 출구쪽에 저항 추가 → 유량 감소, 회수쪽 압력 상승.
- 펌프 저하: 펌프 곡선의 계수가 커짐 → 공급 압력·유량 감소.
- 열: 출구 온도 = 입구 온도 + ΔT, ΔT ∝ (주조 속도)^지수 · 강종 계수 / (정상 유량 대비 유량)
- 입구-출구 유량은 1차 지연(보유량)을 두어 운전점 변경 직후 과도 불균형이 생긴다.
- 부피 유량계는 온도에 따라 밀도가 달라 출구 부피유량이 입구보다 약 1~2% 크게 보인다(질량은 보존).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

import numpy as np
from scipy.signal import lfilter

from .config import PlantConfig


def water_density(t_c: np.ndarray | float) -> np.ndarray | float:
    """물 밀도 (kg/m³). Kell(1975) 근사: 20℃ 998.2, 40℃ 992.2."""
    t = np.asarray(t_c, dtype=float)
    rho = (
        999.842594
        + 6.793952e-2 * t
        - 9.095290e-3 * t**2
        + 1.001685e-4 * t**3
        - 1.120083e-6 * t**4
        + 6.536332e-9 * t**5
    )
    return rho


@dataclass
class Event:
    kind: Literal["leak", "clog", "pump", "sensor"]
    start: int                       # 시작 샘플 인덱스 (1샘플 = dt_s)
    ramp: int = 0                    # 최대값까지 걸리는 샘플 수 (0이면 급작스러움)
    end: Optional[int] = None        # 끝 샘플 (None이면 계속)
    # 누수·막힘 위치
    segment: Optional[int] = None    # 1부터
    roll: Optional[int] = None       # 1부터
    side: Optional[Literal["in", "out"]] = None
    peak: float = 0.0                # 누수: L/min(정상 압력 기준), 막힘: 저항 증가 배수(K_c/K0), 펌프: 계수 증가 비율
    # 센서 고장
    sensor_group: Optional[int] = None   # 계측 묶음 번호(0부터)
    sensor_name: Optional[str] = None    # flow_in, flow_out, p_in, p_out, t_in, t_out
    sensor_mode: Optional[Literal["stuck", "offset"]] = None
    sensor_value: float = 0.0            # offset 크기(상대 또는 절대)

    def profile(self, n: int) -> np.ndarray:
        """0~1 사이의 시간 프로파일."""
        idx = np.arange(n)
        if self.ramp > 0:
            p = np.clip((idx - self.start) / self.ramp, 0.0, 1.0)
        else:
            p = (idx >= self.start).astype(float)
        if self.end is not None:
            p = np.where(idx >= self.end, 0.0, p)
        return p

    def to_label(self) -> dict:
        d = {
            "kind": self.kind, "start_ts": self.start, "ramp_min": self.ramp,
            "end_ts": self.end, "peak": self.peak,
        }
        if self.kind in ("leak", "clog"):
            d.update(segment=self.segment, roll=self.roll, side=self.side)
        if self.kind == "sensor":
            d.update(sensor_group=self.sensor_group, sensor_name=self.sensor_name,
                     sensor_mode=self.sensor_mode, sensor_value=self.sensor_value)
        return d


@dataclass
class Operating:
    speed: np.ndarray          # m/min
    grade: np.ndarray          # 'A'/'B'
    t_in: np.ndarray           # 공급 수온 ℃


@dataclass
class Truth:
    """세그먼트 단위 진실 상태. 형상은 (T, N) 또는 (T,)."""
    q_in: np.ndarray           # 입구 유량 (L/min, 입구 수온 기준 부피)
    q_leak: np.ndarray         # 누수량 (L/min)
    q_out_equiv: np.ndarray    # 출구 유량(입구 수온 기준 부피로 환산한 질량 등가), 지연 반영
    q_out_vol: np.ndarray      # 출구 온도에서의 부피유량 (유량계가 보는 값)
    p_header: np.ndarray       # (T,)
    p_out_seg: np.ndarray      # 세그먼트 출구 압력 (막힘 반영)
    t_out: np.ndarray          # 세그먼트 출구 온도
    t_in: np.ndarray           # (T,)
    speed: np.ndarray          # (T,)
    grade: np.ndarray          # (T,)
    events: list[Event] = field(default_factory=list)


def _first_order_lag(x: np.ndarray, tau_samples: float) -> np.ndarray:
    """열 방향(시간 축=0) 1차 지연. 초기값은 첫 샘플(정상 상태)."""
    if tau_samples <= 0:
        return x.copy()
    alpha = 1.0 - np.exp(-1.0 / tau_samples)
    b = [alpha]
    a = [1.0, -(1.0 - alpha)]
    zi = (1.0 - alpha) * x[0:1] if x.ndim == 1 else (1.0 - alpha) * x[0:1, :]
    # lfilter 초기 상태: y[-1] = x[0] 이 되도록
    y, _ = lfilter(b, a, x, axis=0, zi=zi)
    return y


def simulate_truth(cfg: PlantConfig, op: Operating, events: list[Event], rng: np.random.Generator) -> Truth:
    sim = cfg.sim
    N = cfg.n_segments
    T = len(op.speed)
    dt_min = sim["dt_s"] / 60.0

    q0 = np.array(sim["nominal_flow_lpm"], dtype=float)
    p_ret = float(sim["p_return_bar"])
    p_h_nom = float(sim["pump"]["p_header_nom_bar"])
    p0 = float(sim["pump"]["p0_bar"])
    dp0 = p_h_nom - p_ret
    K0 = dp0 / q0**2                                  # bar/(L/min)²
    a0 = (p0 - p_h_nom) / q0.sum() ** 2               # 펌프 곡선 계수

    v_nom = float(sim["v_nom"])
    phi = 1.0 + float(sim["valve_speed_gain"]) * (op.speed / v_nom - 1.0)   # (T,)

    # ---- 이벤트 프로파일 -------------------------------------------------
    leaks = [e for e in events if e.kind == "leak"]
    L = len(leaks)
    leak_seg = np.zeros(L, dtype=int)
    leak_f = np.zeros(L)
    leak_c = np.zeros((T, L))
    for li, e in enumerate(leaks):
        assert e.segment is not None and e.roll is not None and e.side is not None
        leak_seg[li] = e.segment - 1
        R = cfg.rolls_per_segment
        leak_f[li] = ((e.roll - 1) + (0 if e.side == "in" else 1)) / R   # 분기 길이 대비 위치 (0=입구, 1=출구)
        p_local_nom = p_ret + (1.0 - leak_f[li]) * dp0
        c_peak = e.peak / np.sqrt(p_local_nom)
        leak_c[:, li] = c_peak * e.profile(T)

    Kc_extra = np.zeros((T, N))                       # 출구쪽 추가 저항 (막힘)
    for e in events:
        if e.kind == "clog":
            assert e.segment is not None
            Kc_extra[:, e.segment - 1] += K0[e.segment - 1] * e.peak * e.profile(T)

    pump_a = np.full(T, a0)
    for e in events:
        if e.kind == "pump":
            pump_a = pump_a * (1.0 + e.peak * e.profile(T))

    # ---- 헤더 압력 고정점 반복 ----------------------------------------------
    p_h = np.full(T, p_h_nom)
    K_eff = (K0[None, :] + Kc_extra) / (phi[:, None] ** 2)
    qb = np.zeros((T, N))
    ql_seg = np.zeros((T, N))
    for _ in range(60):
        dp = np.maximum(p_h - p_ret, 1e-6)
        qb = np.sqrt(dp[:, None] / K_eff)
        ql_seg = np.zeros((T, N))
        for li in range(L):
            p_local = p_ret + (1.0 - leak_f[li]) * dp
            ql_seg[:, leak_seg[li]] += leak_c[:, li] * np.sqrt(np.maximum(p_local, 0.0))
        q_tot = (qb + ql_seg).sum(axis=1)
        p_h_new = p0 - pump_a * q_tot**2
        p_h = 0.5 * p_h + 0.5 * p_h_new

    q_in = qb + ql_seg
    # 막힘 세그먼트의 출구 압력(막힘 지점 상류) 상승
    p_out_seg = p_ret + (Kc_extra / (phi[:, None] ** 2)) * qb**2

    # ---- 열 ---------------------------------------------------------------
    slope = float(sim["heat_profile_slope"])
    w = 1.0 - slope * np.arange(N)
    dT_nom = float(sim["delta_t_nom_c"]) * w / w[0]
    gf = np.array([sim["grade_heat_factor"][g] for g in op.grade], dtype=float)
    heat_rel = (op.speed / v_nom) ** float(sim["heat_speed_exponent"]) * gf        # (T,)
    flow_rel = np.maximum(qb / q0[None, :], 0.2)
    d_t = dT_nom[None, :] * heat_rel[:, None] / flow_rel
    tau = float(sim["holdup_tau_min"]) / dt_min
    d_t = _first_order_lag(d_t, tau)
    t_out = op.t_in[:, None] + d_t

    # ---- 출구 유량: 입구 수온 기준 질량 등가 → 지연 → 출구 온도 부피로 환산 ----
    q_out_equiv = _first_order_lag(qb, tau)
    q_out_vol = q_out_equiv * (water_density(op.t_in)[:, None] / water_density(t_out))

    return Truth(
        q_in=q_in, q_leak=ql_seg, q_out_equiv=q_out_equiv, q_out_vol=q_out_vol,
        p_header=p_h, p_out_seg=p_out_seg, t_out=t_out, t_in=op.t_in.copy(),
        speed=op.speed.copy(), grade=op.grade.copy(), events=list(events),
    )


def make_operating(cfg: PlantConfig, n: int, rng: np.random.Generator, *, op_changes: bool = True) -> Operating:
    """주조 속도·강종·공급 수온 시계열. 속도는 6~14시간마다 10분 램프로 바뀐다."""
    sim = cfg.sim
    dt_min = sim["dt_s"] / 60.0
    v_nom = float(sim["v_nom"])
    speed = np.full(n, v_nom)
    grade = np.array(["A"] * n)
    if op_changes:
        # 속도 변경
        t = 0
        cur = v_nom
        pts = []
        while t < n:
            h_lo, h_hi = sim.get("op_hold_hours", (6, 14))           # 민감도 평가용으로 바꿀 수 있다(기본값은 기존과 동일)
            s_lo, s_hi = sim.get("op_step_range", (0.12, 0.30))
            hold = int(rng.uniform(h_lo, h_hi) * 60 / dt_min)
            nxt = float(np.clip(cur + rng.choice([-1, 1]) * rng.uniform(s_lo, s_hi), 1.0, float(sim.get("op_speed_max", 1.5))))
            pts.append((t, cur, nxt))
            t += hold
            cur = nxt
        speed = np.empty(n)
        for i, (t0, v_from, v_to) in enumerate(pts):
            t1 = pts[i + 1][0] if i + 1 < len(pts) else n
            ramp = int(10 / dt_min)
            seg = np.full(t1 - t0, v_to, dtype=float)
            r = min(ramp, t1 - t0)
            seg[:r] = np.linspace(v_from, v_to, r, endpoint=False)
            speed[t0:t1] = seg
        # 강종: 8~24시간마다 A/B 교대
        t = 0
        g = "A"
        while t < n:
            hold = int(rng.uniform(8, 24) * 60 / dt_min)
            grade[t:t + hold] = g
            g = "B" if g == "A" else "A"
            t += hold
    # 공급 수온: 일주기 + 느린 잡음
    mins = np.arange(n) * dt_min
    swing = float(sim["t_in_daily_swing_c"])
    t_in = float(sim["t_in_c"]) + swing * np.sin(2 * np.pi * mins / 1440.0 + rng.uniform(0, 2 * np.pi))
    noise = np.cumsum(rng.normal(0, 0.01, n))
    noise -= np.linspace(noise[0], noise[-1], n)       # 장기 표류 제거
    t_in = t_in + noise
    return Operating(speed=speed, grade=grade, t_in=t_in)
