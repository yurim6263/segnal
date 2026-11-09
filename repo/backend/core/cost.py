"""세그먼트 교체 비용 구조: 계획 교체 vs 비계획 교체, 그리고 조기 감지로 계획 교체로 바뀌는 건수.

이 모듈은 금액을 만들어 내지 않는다. 철강 연주기의 시간당 정지 비용·교체 소요 시간은 공개 근거가 없으므로
(docs 04 §5), 모든 금액·시간은 호출하는 쪽이 현장 값으로 넣는다. 값이 없으면 계산하지 않고 비어 있다고 알린다.

우리 가치 = (비계획 교체 비용 − 계획 교체 비용) × 조기 감지 덕분에 계획 교체로 바뀐 건수.
계획 교체로 바뀌려면 경보가 '다음 정비 창까지 기다릴 수 있는 시간' 이상으로 파손(강제 정지) 전에 와야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

REQUIRED = (
    "direct_planned", "direct_unplanned",
    "stop_hours_planned", "stop_hours_unplanned",
    "loss_per_hour",
)


@dataclass(frozen=True)
class CostBreakdown:
    direct: float          # 직접 정비비 (인건비 + 부품·리빌드 + 장비)
    stop_loss: float       # 정지 시간 × 시간당 생산 손실
    restart_loss: float    # 정지가 있었을 때 재가동 손실 (1회)
    collateral: float      # 부수 손실 (롤·베어링 추가 손상 등)
    total: float

    def as_dict(self) -> dict:
        return asdict(self)


def case_cost(direct: float, stop_hours: float, loss_per_hour: float,
              restart_loss: float = 0.0, collateral: float = 0.0) -> CostBreakdown:
    """교체 1건의 비용. 정지가 없으면(예비 세그먼트로 대체 등) 정지·재가동 손실은 0이다."""
    for name, v in (("direct", direct), ("stop_hours", stop_hours), ("loss_per_hour", loss_per_hour),
                    ("restart_loss", restart_loss), ("collateral", collateral)):
        if v < 0:
            raise ValueError(f"{name} 는 0 이상이어야 합니다")
    stop_loss = stop_hours * loss_per_hour
    restart = restart_loss if stop_hours > 0 else 0.0
    return CostBreakdown(direct, stop_loss, restart, collateral, direct + stop_loss + restart + collateral)


def missing_fields(values: dict) -> list[str]:
    return [k for k in REQUIRED if values.get(k) is None]


def compare(values: dict) -> dict:
    """계획 교체와 비계획 교체의 비용을 비교한다. 필수 입력이 비면 계산하지 않는다."""
    miss = missing_fields(values)
    if miss:
        return {"ready": False, "missing": miss}
    planned = case_cost(values["direct_planned"], values["stop_hours_planned"], values["loss_per_hour"],
                        values.get("restart_loss") or 0.0, 0.0)
    unplanned = case_cost(values["direct_unplanned"], values["stop_hours_unplanned"], values["loss_per_hour"],
                          values.get("restart_loss") or 0.0, values.get("collateral_unplanned") or 0.0)
    return {
        "ready": True, "missing": [],
        "planned": planned.as_dict(), "unplanned": unplanned.as_dict(),
        "saving_per_event": unplanned.total - planned.total,
        "collateral_included": (values.get("collateral_unplanned") or 0.0) > 0,
    }


def is_converted(detect_delay_min: Optional[float], failure_after_leak_min: float, wait_to_window_min: float) -> bool:
    """경보가 계획 정비 창까지 기다릴 만큼 파손보다 먼저 왔는가.

    detect_delay_min: 누수 시작부터 경보까지 걸린 시간. None이면 끝내 감지하지 못한 것.
    failure_after_leak_min: 누수 시작부터 강제 정지(파손)까지 걸리는 시간 — 현장에서 받거나 가정으로 둔다.
    wait_to_window_min: 경보 시점부터 다음 정비 창까지 기다려야 하는 시간.
    """
    if detect_delay_min is None:
        return False
    return (failure_after_leak_min - detect_delay_min) >= wait_to_window_min


def conversion(delay_ours: Optional[float], delay_fixed: Optional[float],
               failure_after_leak_min: float, wait_to_window_min: float) -> dict:
    """우리 방식과 고정 임계값 방식 중 어느 쪽이 비계획 교체를 계획 교체로 바꾸는가 (1건 기준)."""
    ours = is_converted(delay_ours, failure_after_leak_min, wait_to_window_min)
    fixed = is_converted(delay_fixed, failure_after_leak_min, wait_to_window_min)
    return {
        "converted_by_ours": ours,
        "converted_by_fixed": fixed,
        "incremental": ours and not fixed,     # 우리가 있어서 새로 계획 교체로 바뀌는 경우만 우리 몫
        "lead_ours_min": None if delay_ours is None else failure_after_leak_min - delay_ours,
        "lead_fixed_min": None if delay_fixed is None else failure_after_leak_min - delay_fixed,
    }
