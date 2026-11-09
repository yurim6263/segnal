"""경보선 도달 예상 시각과 추정 누수량.

누수로 가려진 뒤, 기준선 보정 불균형(누수 비율에 해당)의 최근 추세를 직선으로 이어
"이 추세면 기존 방식 경보선(고정 임계값)에 언제 닿는가"를 계산한다.

- 추세는 30분 평균 블록에 직선을 맞춰 구하고(최대 6시간), 기울기의 표준오차로 범위를 낸다.
- 기울기가 표준오차의 2배에 못 미치면(추세가 뚜렷하지 않으면) 시각을 내지 않는다.
- 누수가 일정한 속도로 커진다는 가정이다. 중간에 멈추거나 급변하면 틀린다.
모든 데이터는 합성이다.
"""
from __future__ import annotations

import numpy as np

BLOCK = 30          # 분
MAX_WINDOW = 360    # 분
MIN_BLOCKS = 4
T_CRIT = 2.0        # 기울기 / 표준오차가 이보다 작으면 추세가 뚜렷하지 않다고 본다
K_RANGE = 1.0       # 범위: 기울기 ± K × 표준오차
RECENT_BLOCKS = 4   # 최근 2시간의 기울기가 전체 기울기의 절반 아래로 꺾이면 둔화 중으로 본다
DECEL = 0.5


def block_means(x: np.ndarray, end: int, window: int, block: int = BLOCK) -> tuple[np.ndarray, np.ndarray]:
    """end(포함) 이전 window분을 block분씩 묶은 평균과 각 블록 중심 시각."""
    n = max(window // block, 0)
    if n == 0:
        return np.array([]), np.array([])
    lo = end + 1 - n * block
    if lo < 0:
        n = (end + 1) // block
        lo = end + 1 - n * block
    if n <= 0:
        return np.array([]), np.array([])
    seg = np.asarray(x[lo: end + 1], dtype=float).reshape(n, block)
    return seg.mean(axis=1), lo + block * (np.arange(n) + 0.5) - 0.5


def forecast_line(res: np.ndarray, level_now: float, line: float, ts: int, t_start: int) -> dict:
    """res: 기준선 보정 불균형 잔차(비율), level_now: 지금 기존 방식이 보는 불균형(비율, 평활), line: 기존 방식 경보선(비율)."""
    out = {"available": False, "reason": "", "crossed": False, "hours": None, "low_hours": None, "high_hours": None,
           "slope_pct_per_hour": None, "current_pct": round(level_now * 100, 3), "line_pct": round(line * 100, 3), "basis_min": 0}
    if level_now >= line:
        out.update(crossed=True, reason="이미 기존 경보선을 넘었습니다")
        return out
    window = int(min(MAX_WINDOW, ts - t_start + 1))
    y, t = block_means(res, ts, window)
    out["basis_min"] = int(len(y) * BLOCK)
    if len(y) < MIN_BLOCKS:
        out["reason"] = "추세를 읽을 만큼 시간이 쌓이지 않았습니다"
        return out
    tm = t - t.mean()
    sxx = float(tm @ tm)
    b = float(tm @ (y - y.mean()) / sxx)                     # 비율 / 분
    sse = float(np.sum((y - y.mean() - b * tm) ** 2))
    se = (sse / (len(y) - 2) / sxx) ** 0.5
    out["slope_pct_per_hour"] = round(b * 60 * 100, 3)
    if b <= 0 or b < T_CRIT * se:
        out["reason"] = "증가 추세가 뚜렷하지 않아 도달 시각을 내지 않습니다"
        return out
    if len(y) >= 2 * RECENT_BLOCKS:                           # 둔화 확인: 최근 구간 기울기
        tr_, yr = t[-RECENT_BLOCKS:], y[-RECENT_BLOCKS:]
        br = float((tr_ - tr_.mean()) @ (yr - yr.mean()) / ((tr_ - tr_.mean()) @ (tr_ - tr_.mean())))
        if br < DECEL * b:
            out["reason"] = "증가가 둔화되고 있어 도달 시각을 내지 않습니다"
            return out
    dist = line - level_now
    hi = b - K_RANGE * se
    out.update(available=True, hours=round(dist / b / 60, 1), low_hours=round(dist / (b + K_RANGE * se) / 60, 1),
               high_hours=round(dist / hi / 60, 1) if hi > 0 else None)
    return out


def forecast_text(f: dict) -> str:
    if f["crossed"]:
        return "이미 기존 경보선을 넘었습니다."
    if not f["available"]:
        return f["reason"] + "."
    if f["hours"] < 1:
        return "이 추세면 기존 경보선에 1시간 안에 닿습니다."
    if f["high_hours"] is None:
        return f"이 추세면 기존 경보선에 약 {f['hours']:.0f}시간 뒤(빠르면 {f['low_hours']:.0f}시간)."
    return f"이 추세면 기존 경보선에 약 {f['hours']:.0f}시간 뒤(범위 {f['low_hours']:.0f}~{f['high_hours']:.0f}시간)."


def estimate_leak(res: np.ndarray, flow_in: np.ndarray, ts: int, noise: float, window: int = 60) -> dict:
    """추정 누수량(L/min): 최근 window분 평균 잔차 × 입구 유량. 범위는 정상 때 같은 평균이 흔들리는 폭의 2배."""
    lo = max(ts + 1 - window, 0)
    frac = float(np.mean(res[lo: ts + 1]))
    flow = float(np.mean(flow_in[lo: ts + 1]))
    est, half = max(frac, 0.0) * flow, 2.0 * noise * flow
    return {"lpm": round(est, 1), "low_lpm": round(max(est - half, 0.0), 1), "high_lpm": round(est + half, 1),
            "pct": round(max(frac, 0.0) * 100, 2), "flow_lpm": round(flow, 0)}


def leak_noise(res_train: np.ndarray, window: int = 60) -> float:
    """정상 학습 구간에서 window분 평균 잔차가 흔들리는 폭(표준편차, 비율)."""
    k = np.ones(window) / window
    m = np.convolve(np.asarray(res_train, dtype=float), k, mode="valid")
    return float(np.std(m))
