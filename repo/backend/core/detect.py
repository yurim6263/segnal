"""B3. 조기 감지: 잔차의 EWMA / CUSUM, 그리고 비교용 고정 임계값.

- EWMA : EWMA_t = λ·z_t + (1−λ)·EWMA_(t−1), 한계 = k·sqrt(λ/(2−λ))  (z는 표준화된 잔차, 한쪽 방향)
- CUSUM: S_t = max(0, S_(t−1) + z_t − k),  경보 = S_t > h
- 자기상관이 있으면 AR(1) 사전백색화(z_t − φ·z_(t−1))를 옵션으로 쓴다.
- 고정 임계값: 원 신호의 상대 편차가 정해진 값(SAIL 특허 예시: 입출구 유량 차이 20%)을 넘으면 경보.

파라미터는 근거 없이 정하지 않는다: eval/tune_detectors.py가 정상 데이터의 오경보율을 맞춘 뒤 탐지 지연을 본다.
"""
from __future__ import annotations

import numpy as np


def prewhiten(z: np.ndarray, phi: float) -> np.ndarray:
    """AR(1) 사전백색화. 분산이 1에 가깝도록 sqrt(1−φ²)로 보정."""
    e = np.empty_like(z)
    e[0] = z[0]
    e[1:] = (z[1:] - phi * z[:-1]) / np.sqrt(max(1.0 - phi**2, 1e-6))
    return e


def recenter(z: np.ndarray, tau: float = 1440.0, gate_sigma: float = 3.0, fast_lam: float = 0.05, warmup: int = 360) -> np.ndarray:
    """느린 계측 표류를 따라가는 적응형 기준선 보정 (인과적).

    유량계의 느린 표류로 잔차의 평균이 서서히 어긋나면 기준선을 주기적으로 다시 맞춰야 한다.
    중심값 c를 시정수 tau(샘플)로 천천히 갱신하되, 빠른 EWMA가 정상 범위(gate_sigma·σ_ewma)를 벗어난 동안(= 이상 의심)에는
    갱신을 멈춰서 진행 중인 누수를 기준선이 흡수하지 않게 한다.

    warmup > 0이면 처음 warmup 샘플 동안은 이상 여부와 상관없이 누적 평균으로 중심을 맞춘다(시작 시 기준선 어긋남을 빨리 흡수).
    대신 그 구간에 시작한 누수는 흡수될 수 있다(시작 직후 구간은 이상 감지를 하지 않는 셈).
    """
    out = np.empty_like(z, dtype=float)
    c, fast = 0.0, 0.0
    a_slow = 1.0 / tau
    gate = gate_sigma * np.sqrt(fast_lam / (2.0 - fast_lam))
    for i, x in enumerate(z):
        d = x - c
        out[i] = d
        fast = fast_lam * d + (1.0 - fast_lam) * fast
        if i < warmup:
            c += (x - c) / (i + 1)
        elif abs(fast) < gate:
            c += a_slow * d
    return out


def ewma(z: np.ndarray, lam: float) -> np.ndarray:
    out = np.empty_like(z, dtype=float)
    acc = 0.0
    for i, x in enumerate(z):
        acc = lam * x + (1.0 - lam) * acc
        out[i] = acc
    return out


def ewma_limit(lam: float, k: float) -> float:
    return k * np.sqrt(lam / (2.0 - lam))


def cusum(z: np.ndarray, k: float) -> np.ndarray:
    """위쪽(+) CUSUM. 누수는 불균형 잔차가 커지는 방향이라 +쪽만 본다."""
    out = np.empty_like(z, dtype=float)
    s = 0.0
    for i, x in enumerate(z):
        s = max(0.0, s + x - k)
        out[i] = s
    return out


def first_alarm(stat: np.ndarray, limit: float, start: int = 0, min_run: int = 1) -> int | None:
    """stat이 limit을 min_run 샘플 연속 넘는 첫 시각(샘플 인덱스). 없으면 None."""
    over = stat[start:] > limit
    if min_run <= 1:
        idx = np.flatnonzero(over)
        return int(idx[0] + start) if idx.size else None
    run = np.convolve(over.astype(int), np.ones(min_run, dtype=int), mode="valid")
    idx = np.flatnonzero(run >= min_run)
    return int(idx[0] + start + min_run - 1) if idx.size else None


def count_alarm_episodes(stat: np.ndarray, limit: float, gap: int = 60, min_run: int = 1) -> int:
    """오경보 '사건' 수: limit을 넘는 구간들을 gap 샘플 이내면 하나로 센다."""
    over = stat > limit
    if min_run > 1:
        run = np.convolve(over.astype(int), np.ones(min_run, dtype=int), mode="full")[: len(over)]
        over = run >= min_run
    idx = np.flatnonzero(over)
    if idx.size == 0:
        return 0
    return int(1 + np.sum(np.diff(idx) > gap))


def fixed_threshold_stat(imb: np.ndarray) -> np.ndarray:
    """고정 임계값 방식이 보는 값: 입출구 유량 상대 편차의 절댓값."""
    return np.abs(imb)
