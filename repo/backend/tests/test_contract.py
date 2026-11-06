"""API 계약·동작 점검: 모든 엔드포인트가 응답하고, 실제 계산 결과가 기대한 모양인지 확인."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from sim.config import load_config  # noqa: E402
from sim.scenarios import DATA_DIR  # noqa: E402

client = TestClient(app)
have_data = (DATA_DIR / "train_normal__S-A.csv.gz").exists()
needs_data = pytest.mark.skipif(not have_data, reason="python -m sim.generate 로 데이터를 먼저 만드세요")


def test_config_matches_plant_yaml():
    cfg = load_config()
    body = client.get("/api/config").json()
    assert body["n_segments"] == cfg.n_segments
    assert body["sensor_groups"] == cfg.sensor_groups


@needs_data
def test_all_get_endpoints_ok():
    for url in [
        "/api/scenarios", "/api/state?scenario_id=leak_ramp_s5&ts=2400", "/api/series?scenario_id=leak_ramp_s5&group=2&ts=2400",
        "/api/joints", "/api/handover", "/api/eval/detectors", "/api/eval/priors",
    ]:
        r = client.get(url)
        assert r.status_code == 200, url


@needs_data
def test_leak_scenario_flow():
    cfg = load_config()
    client.post("/api/scenarios/leak_ramp_s5/start")
    s0 = client.get("/api/state?scenario_id=leak_ramp_s5&ts=1500").json()
    assert s0["alert"]["level"] == "normal" and s0["segment_candidates"] == []
    assert len(s0["segments"]) == cfg.n_segments and len(s0["groups"]) == len(cfg.sensor_groups)
    assert "정상" in s0["summary"]["headline"]
    s1 = client.get("/api/state?scenario_id=leak_ramp_s5&ts=2400").json()
    # 시스템이 의심하는 단계는 '주의'(watch)이고, 사람이 확인하기 전에는 '경보'(alarm)가 아니다
    assert s1["alert"]["level"] == "watch" and s1["alert"]["cause"] == "leak"
    assert "누수가 의심" in s1["summary"]["headline"] and "확인했습니다" not in s1["summary"]["headline"]
    d = s1["alert"]["detectors"]
    assert d["ewma_alarm_ts"] is not None and d["cusum_alarm_ts"] is not None
    assert d["fixed_alarm_ts"] is None or d["fixed_alarm_ts"] > d["ewma_alarm_ts"]
    assert len(s1["segment_candidates"]) > 0 and s1["impact"] is not None
    assert sum(c["prob"] for c in s1["segment_candidates"]) <= 1.0001
    # 정답 세그먼트(5)가 속한 묶음(세그먼트 4~5)이 상위, 묶음 안은 구분되지 않음을 밝힌다
    assert {c["segment"] for c in s1["segment_candidates"][:2]} == {4, 5}
    assert s1["distinguishable"] is False and "구분되지 않습니다" in s1["candidate_note"]
    assert {r["cause"] for r in s1["cause_table"]} == {"leak", "clog", "pump"}


@needs_data
def test_normal_scenario_has_no_alarm():
    s = client.get("/api/state?scenario_id=normal_opchange&ts=3000").json()
    assert s["alert"]["level"] == "normal"


@needs_data
def test_other_causes_are_labeled_and_stay_watch():
    for sid, cause in [("clog_s7", "clog"), ("pump_degrade", "pump"), ("sensor_fault", "sensor")]:
        s = client.get(f"/api/state?scenario_id={sid}&ts=3000").json()
        assert s["alert"]["cause"] == cause, sid
        assert s["alert"]["level"] == "watch", sid           # 사람이 확인하는 점검 단계가 없는 원인은 적색으로 올리지 않는다
        assert s["segment_candidates"] == []                 # 누수가 아니면 위치 후보를 만들지 않는다


@needs_data
def test_inspection_flow_and_alarm_only_after_human_confirmation():
    sid = "leak_ramp_s5"
    client.post(f"/api/scenarios/{sid}/start")
    s = client.get(f"/api/state?scenario_id={sid}&ts=2400").json()
    first = s["segment_candidates"][0]
    r = client.post("/api/inspections", json={"scenario_id": sid, "candidate_id": f"S{first['segment']}", "result": "no_issue", "ts": 2400})
    assert r.status_code == 200 and len(r.json()["inspections"]) == 1
    s2 = client.get(f"/api/state?scenario_id={sid}&ts=2450").json()
    p_after = next(c["prob"] for c in s2["segment_candidates"] if c["segment"] == first["segment"])
    assert p_after < first["prob"]                            # '이상 없음' 점검 후 그 세그먼트 확률이 줄어든다
    assert s2["alert"]["level"] == "watch"
    nxt = s2["segment_candidates"][0]
    assert nxt["segment"] != first["segment"] and nxt["priority_rank"] == 1
    client.post("/api/inspections", json={"scenario_id": sid, "candidate_id": f"S{nxt['segment']}", "result": "leak_confirmed", "ts": 2460})
    s3 = client.get(f"/api/state?scenario_id={sid}&ts=2500").json()
    assert s3["alert"]["level"] == "alarm" and s3["confirmed_segment"] == nxt["segment"]
    assert "확인했습니다" in s3["summary"]["headline"] and s3["minutes_to_confirm"] is not None
    h = client.get(f"/api/handover?scenario_id={sid}&ts=2500").json()
    assert h["ready"] is True and any(sec["title"] == "점검 결과" for sec in h["sections"])
    # 잘못 입력한 결과를 지우면 다시 '주의'로 돌아간다
    for i in s3["inspections"]:
        client.delete(f"/api/inspections/{i['id']}?scenario_id={sid}")
    s4 = client.get(f"/api/state?scenario_id={sid}&ts=2500").json()
    assert s4["alert"]["level"] == "watch" and s4["inspections"] == []
    client.post(f"/api/scenarios/{sid}/start")


@needs_data
def test_series_channels_and_eval_summary():
    for ch in ("imb_mass", "m_in", "p_in", "p_out"):
        r = client.get(f"/api/series?scenario_id=leak_ramp_s5&group=2&ts=2400&channel={ch}")
        assert r.status_code == 200 and len(r.json()["points"]) > 100
    e = client.get("/api/eval/summary").json()
    assert e["headline"]["ours"] and e["headline"]["fixed"]


def test_bad_candidate_id_is_400():
    r = client.post("/api/inspections", json={"scenario_id": "leak_ramp_s5", "candidate_id": "X9", "result": "no_issue"})
    assert r.status_code == 400


def test_unknown_scenario_is_404():
    assert client.get("/api/state?scenario_id=nope").status_code == 404


def test_post_endpoints_ok():
    r = client.post("/api/agent/ask", json={"scenario_id": "leak_ramp_s5", "question": "왜 경보야?"})
    assert r.status_code == 200
    assert r.json()["disclaimer"]
