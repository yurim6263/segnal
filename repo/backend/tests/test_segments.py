"""세그먼트 조회 API (기획서 4-4 위험도 순위판·세그먼트 상세). 화면이 쓰는 응답 형식을 HTTP 계층에서 확인한다."""
import pytest
from fastapi.testclient import TestClient

import main

SEGMENT_FIELDS = {"segment", "position", "bundle", "rank", "prob_next_stop", "prob_14d", "horizon_days", "joint_age_t",
                  "days_since_install", "top_cause", "top_cause_label", "causes", "signals"}   # frontend/src/llmApi.ts의 RiskSegment
SIGNAL_COLS = ("bearing_t_avg_c", "vib_rms_mm_s", "low_flow_min", "pressure_events", "t_out_avg_c", "joint_age_t")


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


def test_board_ranks_installed_segments(client):
    r = client.get("/api/risk/board")
    assert r.status_code == 200
    b = r.json()
    assert b["as_of"] and b["next_planned_stop"] == "2026-11-12"
    segs = b["segments"]
    assert sorted(s["position"] for s in segs) == list(range(1, 14))                          # 13개 자리에 하나씩 장착
    assert [s["rank"] for s in segs] == list(range(1, 14))
    probs = [s["prob_next_stop"] for s in segs]
    assert probs == sorted(probs, reverse=True) and all(0 <= p <= 0.99 for p in probs)        # 확률 순, 표시 상한 99%
    for s in segs:
        assert SEGMENT_FIELDS <= set(s)
        assert s["top_cause"] == s["causes"][0]["cause"]                                       # 유력 원인 = 기여도 1위


def test_board_does_not_expose_answer_fields(client):
    assert "assembly_flag" not in client.get("/api/risk/board").text                          # 숨은 조립 불량 플래그는 정답 전용


def test_history_returns_signals_and_maintenance(client):
    r = client.get("/api/risk/segments/S-0012/history", params={"days": 14})
    assert r.status_code == 200
    h = r.json()
    assert h["segment"] == "S-0012" and len(h["days"]) == 14
    last = h["days"][-1]
    for c in SIGNAL_COLS:
        assert last[c] is not None and last[f"fleet_{c}"] is not None                         # 최근 신호와 같은 날 장착 평균
    dates = [m["date"] for m in h["maintenance"]]
    assert 0 < len(dates) <= 10 and dates == sorted(dates, reverse=True)                      # 최근 정비 이력부터


def test_history_rejects_unknown_serial_and_bad_days(client):
    assert client.get("/api/risk/segments/S-9999/history").status_code == 404
    for days in (0, 731):
        assert client.get("/api/risk/segments/S-0012/history", params={"days": days}).status_code == 422
