"""인수인계 노트 문장 다듬기 (17단계).

service.handover_at()의 양식 노트에서 '문장'만 Claude가 읽기 좋게 다듬는다. 숫자·시각 값은 계산값 그대로여야 한다.
검증: ① 구역 제목이 같을 것 ② 구역의 값(values)이 문장에 그대로 들어 있을 것 ③ 새 숫자가 생기지 않을 것.
하나라도 어긋난 구역은 양식 문장을 그대로 쓴다. 키가 없거나 호출이 실패하면 양식 노트를 그대로 낸다.
"""
from __future__ import annotations

import json

import service
from agent import cache
from agent.envfile import MODEL_NOTE, llm_available
from agent.verify import unmatched

SYSTEM = """당신은 제철소 연주기 교대 인수인계 노트의 문장을 다듬는 편집자다. 입력은 구역별 양식 문장과 '고정 값' 목록이다.

규칙
1. 구역(title)은 바꾸지 않고, 각 구역의 text만 자연스러운 한국어 1~2문장으로 다듬는다.
2. 각 구역의 '고정 값'은 한 글자도 바꾸지 말고 그대로 문장에 넣는다(시각, 숫자, 단위 포함).
3. 입력에 없는 사실, 숫자, 원인, 조치를 추가하지 않는다. 의미를 바꾸지 않는다. 숫자를 합치거나 계산하지 않는다.
4. 말투는 단정하지 않는다: "의심됩니다", "후보입니다". 점검으로 누수가 확인되었다는 표현은 입력에 있을 때만 쓴다.
5. "조치는 담당자가 결정합니다" 같은 책임 문구는 그대로 유지한다.
6. 서식·제목·목록 없이 문장만 쓴다."""

SCHEMA = {
    "type": "object",
    "properties": {"sections": {"type": "array", "items": {
        "type": "object", "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
        "required": ["title", "text"], "additionalProperties": False}}},
    "required": ["sections"], "additionalProperties": False,
}


def polish(h: dict, scenario_id: str, ts: int) -> dict:
    """h: service.handover_at() 결과. 다듬은 노트(또는 그대로)를 돌려준다."""
    if not h.get("ready") or not llm_available() or not h.get("sections"):
        return h
    key = cache.make_key("note", scenario_id, ts, [(s["title"], s["text"]) for s in h["sections"]], MODEL_NOTE())
    hit = cache.get(key)
    if hit:
        return _apply(h, hit["texts"], hit["ok"])
    try:
        import anthropic
        client = anthropic.Anthropic(timeout=40.0, max_retries=1)
        payload = [{"title": s["title"], "text": s["text"], "고정_값": [v["value"] for v in s["values"]]} for s in h["sections"]]
        resp = client.messages.create(
            model=MODEL_NOTE(), max_tokens=3000, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        )
        if resp.stop_reason in ("refusal", "max_tokens"):
            return h
        data = json.loads(next(b.text for b in resp.content if b.type == "text"))
        by_title = {s["title"]: s["text"] for s in data["sections"]}
    except Exception:
        return h
    texts, ok = {}, {}
    for s in h["sections"]:
        new = by_title.get(s["title"])
        vals = [v["value"] for v in s["values"]]
        good = bool(new) and all(v in new for v in vals) and not unmatched(new, [], s["text"] + " " + " ".join(vals))
        texts[s["title"]], ok[s["title"]] = (new if good else s["text"]), good
    cache.put(key, "note", {"texts": texts, "ok": ok})
    return _apply(h, texts, ok)


def _apply(h: dict, texts: dict, ok: dict) -> dict:
    out = dict(h)
    out["sections"] = [dict(s, text=texts.get(s["title"], s["text"])) for s in h["sections"]]
    out["text"] = " ".join(s["text"] for s in out["sections"])
    out["generated_by"] = "llm" if ok and all(ok.values()) else "template"
    return out
