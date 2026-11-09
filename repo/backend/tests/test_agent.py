"""17단계 에이전트 테스트. 실제 모델을 부르지 않고 가짜 클라이언트로 제어 흐름을 검증한다
(도구 호출 → 숫자 검증 → 재시도 → 양식 폴백, 사람 확인 대기, 캐시, 노트 다듬기 검증)."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import anthropic
import pytest

import service
from agent import cache, note, qa
from agent.verify import unmatched

SID, TS = "leak_ramp_s5", 2400


class FakeMessages:
    def __init__(self, script):
        self.script, self.calls = list(script), []

    def create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def tool_use(name, args=None, id_="tu1"):
    return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=id_, name=name, input=args or {})])


def text(t):
    return NS(stop_reason="end_turn", content=[NS(type="text", text=t)])


@pytest.fixture
def fake(monkeypatch):
    store = {}
    monkeypatch.setattr(cache, "get", lambda k: store.get(k))
    monkeypatch.setattr(cache, "put", lambda k, kind, p: store.__setitem__(k, p))
    monkeypatch.setattr(qa, "llm_available", lambda: True)
    monkeypatch.setattr(note, "llm_available", lambda: True)

    def install(script):
        msgs = FakeMessages(script)
        monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: NS(messages=msgs))
        return msgs
    install.store = store
    return install


def test_verify_accepts_rounded_and_rejects_invented():
    res = [{"p": 51.3, "r": 0.77, "m": 422, "t": "2일차 08:25"}]
    assert unmatched("가능성 51%, 오경보 0.77회, 약 7시간, 2일차 08:25", res) == []
    assert unmatched("가능성 83%이고 12.7 L/min", res) == ["83", "12.7"]


def test_no_key_uses_template(monkeypatch):
    monkeypatch.setattr(qa, "llm_available", lambda: False)
    r = qa.ask(SID, TS, qa.PRESETS[1])
    assert r["mode"] == "template" and "세그먼트 4" in r["answer"] and "API 키" in r["note"]


def test_llm_flow_with_tool_and_verified_numbers(fake):
    msgs = fake([tool_use("get_location_candidates"), text("묶음 3에서 누수가 의심됩니다. 세그먼트 4가 가능성 51%로 1순위입니다. 확정은 점검으로 합니다.")])
    r = qa.ask(SID, TS, "후보 알려줘")
    assert r["mode"] == "llm" and r["numbers_verified"] and "get_location_candidates" in r["tools_used"]
    # 도구 결과가 user 메시지로 되돌아갔다 (가짜 클라이언트는 같은 리스트를 참조하므로 전체에서 찾는다)
    sent = msgs.calls[1]["messages"]
    assert any(m["role"] == "user" and isinstance(m["content"], list) and m["content"][0]["type"] == "tool_result" for m in sent)
    assert "output_config" in msgs.calls[0] and "temperature" not in msgs.calls[0]
    # 같은 질문·같은 상태 → 캐시
    r2 = qa.ask(SID, TS, "후보 알려줘")
    assert r2["from_cache"] and r2["mode"] == "cache" and r2["answer"] == r["answer"]


def test_invented_number_retries_then_falls_back(fake):
    bad = "가능성 83%이고 누수량은 12.7 L/min입니다."
    msgs = fake([tool_use("get_location_candidates"), text(bad), text(bad)])
    r = qa.ask(SID, TS, "누수량은?")
    assert r["mode"] == "template" and "숫자" in r["note"]
    assert any("도구 결과에 없습니다" in str(m["content"]) for m in msgs.calls[-1]["messages"] if m["role"] == "user")


def test_retry_can_recover(fake):
    fake([tool_use("get_location_candidates"), text("가능성 83%입니다."), text("세그먼트 4의 가능성은 51%입니다.")])
    r = qa.ask(SID, TS, "가능성은?")
    assert r["mode"] == "llm" and r["numbers_verified"]


def test_api_error_falls_back(fake):
    fake([RuntimeError("network down")])
    r = qa.ask(SID, TS, qa.PRESETS[0])
    assert r["mode"] == "template" and "실패" in r["note"]


def test_refusal_falls_back(fake):
    fake([NS(stop_reason="refusal", content=[])])
    assert qa.ask(SID, TS, "질문")["mode"] == "template"


def test_write_tool_only_proposes_never_saves(fake):
    before = len(service.inspections_at(SID, TS))
    fake([tool_use("propose_inspection_record", {"segment": 4, "result": "no_issue", "reason": "4번 봤는데 이상 없음"}),
          text("세그먼트 4를 이상 없음으로 기록하려면 화면의 확인 버튼을 눌러 주세요.")])
    r = qa.ask(SID, TS, "4번 점검했는데 이상 없음")
    assert r["proposed_action"] == {"segment": 4, "result": "no_issue", "reason": "4번 봤는데 이상 없음"}
    assert len(service.inspections_at(SID, TS)) == before          # 사람이 확인하기 전에는 저장되지 않는다
    assert r["from_cache"] is False


def _ready_handover():
    service.reset_inspections(SID)
    service.add_inspection(SID, "S4", "no_issue", TS)
    service.add_inspection(SID, "S5", "leak_confirmed", TS)
    try:
        return service.handover_at(SID, TS)
    finally:
        service.reset_inspections(SID)


def test_note_polish_keeps_values_and_rejects_changed(fake):
    h = _ready_handover()
    assert h["ready"]
    good = [{"title": s["title"], "text": f"{s['text']} (정리)"} for s in h["sections"]]
    fake([NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps({"sections": good}, ensure_ascii=False))])])
    out = note.polish(h, SID, TS)
    assert out["generated_by"] == "llm" and out["text"] != h["text"]

    # 한 구역에서 값을 바꾸면 그 구역은 양식 문장으로 되돌아간다
    store = fake.store; store.clear()
    bad = [dict(g) for g in good]
    sec = next(s for s in h["sections"] if s["values"])
    for b in bad:
        if b["title"] == sec["title"]:
            b["text"] = b["text"].replace(sec["values"][0]["value"], "999")
    fake([NS(stop_reason="end_turn", content=[NS(type="text", text=json.dumps({"sections": bad}, ensure_ascii=False))])])
    out2 = note.polish(h, SID, TS)
    assert out2["generated_by"] == "template"
    assert next(s for s in out2["sections"] if s["title"] == sec["title"])["text"] == sec["text"]


def test_note_without_key_unchanged(monkeypatch):
    monkeypatch.setattr(note, "llm_available", lambda: False)
    h = _ready_handover()
    assert note.polish(h, SID, TS) == h
