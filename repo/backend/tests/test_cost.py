"""교체 비용 구조 점검. 아래 숫자는 계산식 확인용 임의 값이며 현장 값이 아니다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from core import cost  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)

FULL = dict(direct_planned=10, direct_unplanned=15, stop_hours_planned=0, stop_hours_unplanned=4,
            loss_per_hour=100, restart_loss=20, collateral_unplanned=30)


def test_no_stop_means_no_stop_or_restart_loss():
    c = cost.case_cost(direct=10, stop_hours=0, loss_per_hour=100, restart_loss=20)
    assert c.stop_loss == 0 and c.restart_loss == 0 and c.total == 10


def test_compare_planned_vs_unplanned():
    r = cost.compare(FULL)
    assert r["ready"] and r["planned"]["total"] == 10
    assert r["unplanned"]["total"] == 15 + 4 * 100 + 20 + 30
    assert r["saving_per_event"] == r["unplanned"]["total"] - r["planned"]["total"]
    assert r["collateral_included"] is True


def test_missing_inputs_are_reported_not_filled_in():
    r = cost.compare({"direct_planned": 10})
    assert r["ready"] is False
    assert set(r["missing"]) == {"direct_unplanned", "stop_hours_planned", "stop_hours_unplanned", "loss_per_hour"}


def test_negative_input_rejected():
    with pytest.raises(ValueError):
        cost.case_cost(direct=-1, stop_hours=0, loss_per_hour=0)


def test_conversion_needs_enough_lead_before_failure():
    # 파손까지 600분, 정비 창까지 120분 대기: 경보가 480분 안에 와야 한다
    assert cost.is_converted(60, 600, 120) is True
    assert cost.is_converted(480, 600, 120) is True
    assert cost.is_converted(481, 600, 120) is False
    assert cost.is_converted(None, 600, 120) is False        # 끝내 감지하지 못함


def test_incremental_only_when_ours_converts_and_fixed_does_not():
    r = cost.conversion(delay_ours=60, delay_fixed=455, failure_after_leak_min=480, wait_to_window_min=120)
    assert r["converted_by_ours"] and not r["converted_by_fixed"] and r["incremental"]
    both = cost.conversion(60, 100, 600, 120)
    assert both["converted_by_ours"] and both["converted_by_fixed"] and not both["incremental"]


def test_endpoint_without_inputs_returns_missing():
    r = client.post("/api/cost", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False and len(body["missing"]) == len(cost.REQUIRED)


def test_endpoint_with_inputs():
    r = client.post("/api/cost", json=FULL)
    assert r.status_code == 200 and r.json()["ready"] is True
    assert r.json()["saving_per_event"] > 0
    assert r.json()["conversion"] is None                    # 파손·정비 창 시간을 안 넣으면 건수 판단은 하지 않는다


def test_endpoint_rejects_negative():
    assert client.post("/api/cost", json={**FULL, "loss_per_hour": -1}).status_code == 422
