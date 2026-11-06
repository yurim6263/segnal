"""O2. 영향 슬래브 구간 표시 (품질 축).

누수로 냉각이 불균형해진 시간 구간 × 주조 속도로, 그 구간에 해당 세그먼트를 지나간 주편의 길이를 계산해
'표면 검사 대상 후보' 구간으로 표시한다. 불량을 예측하지는 않는다 (냉각 이상과 표면 결함의 정량 관계는 모른다).

기하(가설): 세그먼트 i는 몰드 출구로부터 [i0, i1] m 구간을 차지한다 (세그먼트 길이 일정).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ImpactResult:
    start_m: float          # 영향 구간 시작(몰드 출구로부터 m) — 현재 세그먼트 안에 있는 주편
    end_m: float            # 영향 구간 끝 — 이미 세그먼트를 지나간 주편의 현재 위치
    exposed_length_m: float
    slab_first: int
    slab_last: int
    label: str


def segment_span_m(segment: int, segment_len_m: float = 1.75, mold_to_seg1_m: float = 0.0) -> tuple[float, float]:
    i0 = mold_to_seg1_m + (segment - 1) * segment_len_m
    return i0, i0 + segment_len_m


def exposed_length_m(speed_m_per_min: np.ndarray, t_start: int, t_end: int, dt_min: float = 1.0) -> float:
    """[t_start, t_end) 동안 지나간 주편 길이 = ∫ v dt."""
    return float(np.sum(speed_m_per_min[t_start:t_end]) * dt_min)


def impact_range(
    speed_m_per_min: np.ndarray,
    segment: int,
    t_start: int,
    t_now: int,
    *,
    dt_min: float = 1.0,
    segment_len_m: float = 1.75,
    slab_len_m: float = 10.0,
) -> ImpactResult:
    entry, exit_ = segment_span_m(segment, segment_len_m)
    E = exposed_length_m(speed_m_per_min, t_start, t_now, dt_min)
    start_m, end_m = entry, exit_ + E

    # 슬래브 번호: 주조 시작(ts 0)부터 누적 주조 길이 D(t). 위치 x의 주편은 D(τ) = D(t_now) − x 인 τ에 메니스커스를 지났다.
    cum = np.concatenate([[0.0], np.cumsum(speed_m_per_min * dt_min)])
    d_now = cum[min(t_now, len(cum) - 1)]
    cast_at_end = max(d_now - end_m, 0.0)       # 가장 먼저 노출된 주편이 메니스커스를 지난 누적 길이
    cast_at_start = max(d_now - start_m, 0.0)
    first = int(cast_at_end // slab_len_m) + 1
    last = int(cast_at_start // slab_len_m) + 1
    label = (f"슬래브 No.{first}~{last}: 몰드 출구로부터 {start_m:.1f}~{end_m:.1f} m 구간, "
             f"노출 길이 {E:.1f} m → 표면 검사 대상 후보")
    return ImpactResult(start_m, end_m, E, first, last, label)
