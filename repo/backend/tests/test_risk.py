import numpy as np
import pytest

from core import risk


@pytest.fixture(scope="module")
def setup():
    d = risk.load()
    rows = risk.build_rows(d)
    m = risk.fit(rows[rows["day"] < rows["day"].max()])
    return d, rows, m


def test_features_use_only_past_and_hide_answer_fields(setup):
    d, rows, _ = setup
    assert "assembly_flag" not in rows.columns                    # 정답 전용 값은 모델에 안 들어간다
    last = rows["day"].max()
    fut = rows[rows["day"] == last]
    assert len(fut) == 13 and (fut["event"] == "").all()          # 예측 기준일 행: 장착 13개, 결과 없음
    # 전날까지의 값만 쓴다: 어느 날의 유량 저하 시간을 바꿔도 그 날의 특징은 변하지 않는다
    d2 = risk.load()
    day = 400
    d2.daily.loc[d2.daily["day"] == day, "low_flow_min"] += 500
    r2 = risk.build_rows(d2)
    a = rows[rows["day"] == day].sort_values("segment_serial")["x_low"].to_numpy()
    b = r2[r2["day"] == day].sort_values("segment_serial")["x_low"].to_numpy()
    assert np.allclose(a, b)


def test_coefficients_are_sensible(setup):
    _, _, m = setup
    assert 1.0 < m.models["WEAR"].beta < 3.5                       # 마모형
    for c in ("HAMMER", "WATER", "BEARING"):
        assert m.models[c].theta[1] > 0                            # 신호가 늘면 위험이 는다
    assert m.models["ASSEMBLY"].beta < 1.2                         # 초기 불량은 마모형이 아니다


def test_snapshot_demo_segment_ranks_first(setup):
    d, rows, m = setup
    snap = risk.snapshot(m, rows, d)
    assert len(snap) == 13 and snap[0]["rank"] == 1
    top = snap[0]
    assert top["segment"] == "S-0012" and top["position"] == 7 and top["top_cause"] == "BEARING"
    assert top["prob_next_stop"] > 3 * snap[1]["prob_next_stop"]
    for s in snap:
        assert 0 <= s["prob_next_stop"] <= s["prob_14d"] <= 1
        assert abs(sum(c["share"] for c in s["causes"]) - 1.0) < 0.5   # 상위 3개 비중
    assert top["horizon_days"] == 3                                 # 다음 계획 정지(11/12)까지


def test_beta_type_rule():
    assert risk.beta_type(1.5) == "마모형" and risk.beta_type(1.0) == "우연형" and risk.beta_type(0.6) == "초기불량형"


def test_service_board():
    import service
    b = service.risk_board()
    assert b["next_planned_stop"] == "2026-11-12" and len(b["segments"]) == 13
    assert b["segments"][0]["segment"] == "S-0012"
