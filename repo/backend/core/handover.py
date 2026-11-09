"""인수인계 노트 문장 정리 (LLM 옵션).

템플릿 노트(service.handover_at)의 '경보·원인 후보·근거' 문장만 Claude가 다듬는다. 수치와 판단은 바꿀 수 없다.
결과가 검사를 하나라도 통과하지 못하거나 호출이 실패하면 템플릿을 그대로 돌려주고 fallback_reason에 이유를 적는다.
'점검 결과'(사람의 기록)와 '다음 할 일'(고정 문구)은 모델에 보내지 않는다.
"""
from __future__ import annotations

import json
import re
from collections import Counter

MODEL = "claude-opus-5-5"
TIMEOUT_S = 20.0
REWRITABLE = ("경보", "원인 후보", "근거")

NUMBER = re.compile(r"[+\-−]?\d+(?:[.:]\d+)*")
NUMBER_WORD = re.compile(r"(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s?(?:번|배|차례|개|곳|회|분|시간)")
NEGATION = re.compile(r"않|없|못")
# 템플릿에 없는데 결과에 나타나면 안 되는 말: 단정, 조치 지시, 다른 원인, 어림 표현, 묶음 계측으로 말할 수 없는 위치
FORBIDDEN = (
    "확정", "확인", "판명", "틀림없", "확실", "분명", "반드시", "즉시", "당장", "긴급", "위험", "폭발",
    "정지", "중단", "교체", "수리", "조치", "권고", "필요",
    "누수", "막힘", "펌프", "센서",
    "약 ", "정도", "가량",
    "세그먼트", "조인트",
)
REQUIRED = ("후보", "의심")

SYSTEM = """당신은 제철소 연주기 설비 담당자의 교대 인수인계 노트를 다듬는 편집자입니다.
입력의 각 문단을 다음 교대자가 읽기 좋은 자연스러운 한국어 보고체 문장으로 고칩니다.

- 문단의 제목과 순서는 그대로 둡니다.
- 숫자, 부호, 시각, 단위는 입력에 적힌 표기 그대로 쓰고, 숫자를 더하거나 빼거나 합치지 않습니다.
- keep_verbatim의 값은 글자 하나 바꾸지 않고 포함합니다.
- '않았습니다', '없습니다' 같은 부정 표현의 뜻과 개수를 유지합니다.
- '후보', '의심'은 그대로 둡니다. 추정을 확정처럼 쓰지 않습니다.
- 입력에 없는 사실, 원인, 위치, 조치, 권고, 어림 표현을 더하지 않습니다.
- 문장 길이는 입력과 비슷하게 유지합니다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "text": {"type": "string"}},
                "required": ["title", "text"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sections"],
    "additionalProperties": False,
}

_cache: dict[str, list[dict]] = {}          # 검사를 통과한 결과만 저장한다. 같은 노트를 다시 눌러도 같은 문장이 나온다.


class ModelOutputError(Exception):
    """모델이 쓸 수 있는 답을 돌려주지 않았다. 메시지는 화면에 그대로 표시한다."""


def _request(payload: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=0)
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=4096,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        messages=[{"role": "user", "content": payload}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if resp.stop_reason != "end_turn":
        raise ModelOutputError(f"언어 모델이 답을 끝내지 못했습니다({resp.stop_reason}).")
    try:
        return json.loads(next(b.text for b in resp.content if b.type == "text"))["sections"]
    except (StopIteration, ValueError, KeyError) as e:
        raise ModelOutputError("언어 모델의 응답 형식이 올바르지 않습니다.") from e


def check_rewrite(sources: list[dict], rewritten: list[dict]) -> str:
    """통과하면 빈 문자열, 아니면 화면에 표시할 탈락 이유를 돌려준다."""
    if [s["title"] for s in sources] != [r["title"] for r in rewritten]:
        return "문단 구성이 원문과 달라졌습니다."
    for src, out in zip(sources, rewritten):
        title, a, b = src["title"], src["text"], out["text"]
        if not b.strip() or len(b) > len(a) * 1.6 + 20:
            return f"'{title}' 문단의 길이가 허용 범위를 벗어났습니다."
        if Counter(NUMBER.findall(a)) != Counter(NUMBER.findall(b)) or NUMBER_WORD.search(b):
            return f"'{title}' 문단의 숫자가 계산 결과와 달라졌습니다."
        if any(v["value"] not in b for v in src["values"]):
            return f"'{title}' 문단에서 계산 값의 표기가 달라졌습니다."
        if len(NEGATION.findall(a)) != len(NEGATION.findall(b)):
            return f"'{title}' 문단의 부정 표현이 달라졌습니다."
        if any(w in a and w not in b for w in REQUIRED):
            return f"'{title}' 문단에서 추정 표현이 빠졌습니다."
        added = [w for w in FORBIDDEN if w in b and w not in a]
        if added:
            return f"'{title}' 문단에 원문에 없는 표현이 들어갔습니다({added[0].strip()})."
    return ""


def _failure_reason(e: Exception) -> str:
    if isinstance(e, ImportError):
        return "anthropic 패키지가 설치되어 있지 않습니다."
    if isinstance(e, ModelOutputError):
        return str(e)
    import anthropic

    if isinstance(e, anthropic.APITimeoutError):
        return f"언어 모델이 {TIMEOUT_S:.0f}초 안에 답하지 않았습니다."
    if isinstance(e, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return "API 키를 사용할 수 없습니다."
    if isinstance(e, anthropic.RateLimitError):
        return "API 호출 한도를 넘었습니다."
    if isinstance(e, anthropic.APIConnectionError):
        return "언어 모델 서버에 연결하지 못했습니다."
    if isinstance(e, anthropic.APIStatusError):
        return f"언어 모델 서버 오류입니다({e.status_code})."
    return "언어 모델을 호출하지 못했습니다. API 키 설정을 확인하세요."


def polish_note(note: dict) -> dict:
    """템플릿 노트를 받아 문장을 다듬은 노트를 돌려준다. 실패하면 템플릿 그대로다."""
    def keep_template(reason: str) -> dict:
        return {**note, "generated_by": "template", "fallback_reason": reason}

    targets = [s for s in note["sections"] if s["title"] in REWRITABLE]
    if not targets:
        return keep_template("다듬을 문장이 없습니다.")
    payload = json.dumps(
        {"sections": [{"title": s["title"], "text": s["text"], "keep_verbatim": [v["value"] for v in s["values"]]} for s in targets]},
        ensure_ascii=False,
    )
    try:
        rewritten = _cache[payload] if payload in _cache else _request(payload)
    except Exception as e:                       # 시연 중 어떤 호출 실패도 노트 화면을 막지 않는다
        print("[warn] handover polish failed:", type(e).__name__)
        return keep_template(_failure_reason(e))
    reason = check_rewrite(targets, rewritten)
    if reason:
        return keep_template(reason)
    _cache[payload] = rewritten
    by_title = {r["title"]: r["text"] for r in rewritten}
    sections = [{**s, "text": by_title.get(s["title"], s["text"])} for s in note["sections"]]
    return {**note, "sections": sections, "text": " ".join(s["text"] for s in sections), "generated_by": "llm", "fallback_reason": ""}
