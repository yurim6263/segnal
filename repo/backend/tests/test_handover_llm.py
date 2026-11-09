"""인수인계 노트 LLM 문장 정리: 모델 응답을 가짜로 넣어 검사와 템플릿 폴백을 확인한다 (API 호출 없음)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from core import handover  # noqa: E402
from main import app  # noqa: E402
from sim.scenarios import DATA_DIR  # noqa: E402

client = TestClient(app)
needs_data = pytest.mark.skipif(not (DATA_DIR / "train_normal__S-A.csv.gz").exists(), reason="python -m sim.generate 로 데이터를 먼저 만드세요")

ALARM = "묶음 3에서 1일차 18:44에 추세 감지 경보가 났습니다. 고정 임계값에는 도달하지 않았습니다."
CAUSE = "누수 후보입니다. 공급-회수 불균형이 커지고 입구 유량은 줄지 않는다."
BASIS = "묶음 3의 공급-회수 불균형이 기준선보다 +3.2σ 벌어졌고, 입구 유량 잔차는 -0.4σ였습니다."
GOOD = [
    {"title": "경보", "text": "1일차 18:44에 묶음 3에서 추세 감지 경보가 발생했습니다. 고정 임계값에는 도달하지 않았습니다."},
    {"title": "원인 후보", "text": "누수 후보입니다. 공급-회수 불균형은 커지는데 입구 유량은 줄지 않고 있습니다."},
    {"title": "근거", "text": "묶음 3의 공급-회수 불균형은 기준선보다 +3.2σ 벌어졌으며, 입구 유량 잔차는 -0.4σ입니다."},
]


@pytest.fixture
def note():
    secs = [
        {"title": "경보", "text": ALARM, "values": [{"label": "경보 시각", "value": "1일차 18:44", "source": "EWMA"}]},
        {"title": "원인 후보", "text": CAUSE, "values": []},
        {"title": "근거", "text": BASIS, "values": [{"label": "불균형", "value": "+3.2σ", "source": "EWMA"}, {"label": "유량", "value": "-0.4σ", "source": "EWMA"}]},
        {"title": "점검 결과", "text": "세그먼트 5는 1일차 20:00에 누수 확인.", "values": []},
        {"title": "다음 할 일", "text": "조치는 담당자가 결정합니다.", "values": []},
    ]
    return {"title": "묶음 3 누수 의심", "text": "원문", "generated_by": "template", "ready": True, "sections": secs, "missing": [], "sources": []}


@pytest.fixture(autouse=True)
def clear_cache():
    handover._cache.clear()


def fake_model(monkeypatch, sections):
    sent = []

    def request(payload):
        sent.append(payload)
        return sections
    monkeypatch.setattr(handover, "_request", request)
    return sent


def with_text(title, text):
    return [{"title": s["title"], "text": text if s["title"] == title else s["text"]} for s in GOOD]


def test_good_rewrite_is_used_and_human_sections_stay(monkeypatch, note):
    sent = fake_model(monkeypatch, GOOD)
    out = handover.polish_note(note)
    assert out["generated_by"] == "llm" and out["fallback_reason"] == ""
    assert out["sections"][0]["text"] == GOOD[0]["text"]
    assert out["sections"][3]["text"] == note["sections"][3]["text"] and out["sections"][4]["text"] == note["sections"][4]["text"]
    assert GOOD[2]["text"] in out["text"] and "조치는 담당자" in out["text"]
    assert "점검 결과" not in sent[0] and "세그먼트" not in sent[0]        # 사람의 기록은 모델에 보내지 않는다


@pytest.mark.parametrize("bad, reason", [
    (with_text("근거", GOOD[2]["text"].replace("+3.2σ", "+3.5σ")), "숫자"),
    (with_text("근거", GOOD[2]["text"].replace("+3.2σ", "3.2σ")), "숫자"),
    (with_text("근거", GOOD[2]["text"] + " 변화는 2시간째입니다."), "숫자"),
    (with_text("경보", GOOD[0]["text"] + " 두 번 울렸습니다."), "숫자"),
    (with_text("경보", GOOD[0]["text"].replace("도달하지 않았습니다", "도달했습니다")), "부정"),
    (with_text("원인 후보", "누수입니다. 공급-회수 불균형이 커지고 입구 유량은 줄지 않습니다."), "추정"),
    (with_text("원인 후보", GOOD[1]["text"] + " 확정입니다."), "없는 표현"),
    (with_text("원인 후보", GOOD[1]["text"].replace("누수 후보", "막힘 후보")), "없는 표현"),
    (with_text("근거", GOOD[2]["text"] + " 세그먼트 점검이 필요합니다."), "없는 표현"),
    (with_text("근거", GOOD[2]["text"].replace("+3.2σ", "약 +3.2σ")), "없는 표현"),
    (with_text("경보", ""), "길이"),
    (GOOD[:2], "문단 구성"),
])
def test_bad_rewrite_falls_back_to_template(monkeypatch, note, bad, reason):
    fake_model(monkeypatch, bad)
    out = handover.polish_note(note)
    assert out["generated_by"] == "template" and reason in out["fallback_reason"]
    assert out["sections"] == note["sections"] and out["text"] == note["text"]


def test_api_failure_falls_back_to_template(monkeypatch, note):
    def boom(payload):
        raise RuntimeError("down")
    monkeypatch.setattr(handover, "_request", boom)
    out = handover.polish_note(note)
    assert out["generated_by"] == "template" and out["fallback_reason"] and out["sections"] == note["sections"]


def test_only_validated_result_is_cached(monkeypatch, note):
    sent = fake_model(monkeypatch, GOOD)
    handover.polish_note(note)
    handover.polish_note(note)
    assert len(sent) == 1
    handover._cache.clear()
    sent = fake_model(monkeypatch, with_text("근거", "틀린 문장 +9.9σ"))
    handover.polish_note(note)
    handover.polish_note(note)
    assert len(sent) == 2


def test_empty_note_does_not_call_model(monkeypatch):
    sent = fake_model(monkeypatch, GOOD)
    out = handover.polish_note({"sections": [], "text": ""})
    assert out["generated_by"] == "template" and out["fallback_reason"] and sent == []


def test_unknown_scenario_is_404():
    assert client.post("/api/handover/polish", json={"scenario_id": "nope"}).status_code == 404


@needs_data
def test_endpoint_with_real_template(monkeypatch):
    sid = "leak_ramp_s5"
    client.post(f"/api/scenarios/{sid}/start")
    template = client.get(f"/api/handover?scenario_id={sid}&ts=2400").json()
    assert template["generated_by"] == "template" and template["sections"]
    echo = [{"title": s["title"], "text": s["text"]} for s in template["sections"] if s["title"] in handover.REWRITABLE]
    fake_model(monkeypatch, echo)
    out = client.post("/api/handover/polish", json={"scenario_id": sid, "ts": 2400}).json()
    assert out["generated_by"] == "llm" and out["text"] == template["text"]
