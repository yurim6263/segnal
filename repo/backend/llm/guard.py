"""입력·출력 검사. 모델 앞뒤에서 규칙으로 막는다(모델의 "착함"에 기대지 않는다).

입력: 프롬프트 주입 문구, 시스템 지시 요구, 설비 제어 요구, 개인정보 요구
문서: 검색된 조항 안의 지시문(주입) 제거
출력: 숫자 대조, 인용 조항이 넘겨 준 조항인지, 개인정보 패턴, 열람 권한 없는 조항 문구 유출, 제어·실행 표현
"""
from __future__ import annotations

import re

from agent.verify import unmatched

# 모델에 "지시"를 걸려는 문구
_INJECT = [r"이전\s*(의\s*)?(지시|명령|규칙).{0,8}(무시|잊)", r"위의?\s*(지시|규칙).{0,6}(무시|잊)", r"시스템\s*(프롬프트|지시|메시지)", r"(규칙|제한|권한)\s*(을|를)?\s*(무시|해제|풀)",
           r"ignore\s+(all\s+|the\s+)?(previous|above)", r"system\s*prompt", r"jailbreak|DAN\s*모드", r"관리자\s*(모드|권한)\s*(으?로|를)?\s*(전환|켜|부여)", r"개발자\s*모드",
           r"너는\s*이제", r"역할을\s*(바꿔|변경)", r"you\s+are\s+now"]
_CONTROL = [r"(밸브|펌프|유량|압력|설비).{0,10}(제어|조작|열어|닫아|꺼|켜|변경해)", r"(자동으로|바로)\s*(발행|승인|실행)", r"작업지시서.{0,10}(승인\s*처리|발행해)"]
_PII_ASK = [r"(사번|내선|연락처|전화번호|휴대폰|핸드폰|이메일|주민|담당자\s*(이름|명단))", r"누가\s*(담당|작업|처리)했"]
_INJECT_RE = [re.compile(p, re.I) for p in _INJECT]
_CONTROL_RE = [re.compile(p) for p in _CONTROL]
_PII_ASK_RE = [re.compile(p) for p in _PII_ASK]
_PII_OUT = [re.compile(p) for p in (r"사번\s*[A-Z]?\d{4,8}", r"내선\s*\d{3,4}", r"01[016789]-?\d{3,4}-?\d{4}", r"[\w.+-]+@[\w-]+\.[\w.]+")]
_CITE = re.compile(r"\[([A-Z]+-\d{2})\s+([0-9][0-9.]*)\]")
_CTRL_OUT = [re.compile(p) for p in (r"(제가|내가|시스템이)\s*(밸브|펌프|설비).{0,8}(조작|제어|닫|열)", r"자동으로\s*(승인|발행|실행)했")]


def check_question(q: str) -> tuple[str | None, str]:
    """(차단 이유 코드, 사용자에게 보여 줄 문구). 통과하면 (None, "")."""
    for r in _INJECT_RE:
        if r.search(q):
            return "injection", "규칙이나 권한을 바꾸라는 요청은 처리하지 않습니다. 업무 질문(세그먼트 위험, 원인, 조치, 절차)을 해 주세요."
    for r in _CONTROL_RE:
        if r.search(q):
            return "control", "이 시스템은 설비를 제어하거나 문서를 자동 발행하지 않습니다. 조치는 담당자가 결정하고 승인합니다."
    for r in _PII_ASK_RE:
        if r.search(q):
            return "pii", "개인 식별 정보(이름·사번·연락처)는 제공하지 않습니다."
    return None, ""


_DOC_INJECT = [re.compile(p, re.I) for p in (r"(이 문서|이 조항|아래|위).{0,12}(지시|명령).{0,6}(따르|무시|수행)", r"이전\s*지시.{0,6}무시", r"ignore\s+(all\s+)?previous", r"시스템\s*프롬프트.{0,10}(출력|공개|보여)",
                                             r"(비밀|전체).{0,6}(출력|공개)해", r"관리자\s*권한.{0,8}(부여|전환)")]


def doc_has_injection(text: str) -> bool:
    return any(r.search(text) for r in _DOC_INJECT)


def _shingles(text: str, n: int = 12) -> set[str]:
    t = re.sub(r"\s+", "", text)
    return {t[i:i + n] for i in range(0, max(0, len(t) - n + 1))}


def check_answer(answer: str, *, model_values: list, clause_text: str, question: str, allowed_refs: set[str], forbidden_texts: list[str]) -> dict:
    """출력 검사 결과: 각 항목 True면 통과."""
    bad_nums = unmatched(answer, model_values, clause_text + " " + question)
    cited = {f"{d} {c.rstrip('.')}" for d, c in _CITE.findall(answer)}
    bad_cites = sorted(cited - allowed_refs)
    pii = any(r.search(answer) for r in _PII_OUT)
    ctrl = any(r.search(answer) for r in _CTRL_OUT)
    ans_sh = _shingles(answer)
    leak = any(ans_sh & _shingles(t) for t in forbidden_texts if len(t) > 20)
    return {"numbers_ok": not bad_nums, "bad_numbers": bad_nums, "citations_ok": not bad_cites, "bad_citations": bad_cites,
            "pii_ok": not pii, "control_ok": not ctrl, "no_forbidden_leak": not leak, "cited": sorted(cited)}


def passed(checks: dict) -> bool:
    return all(checks[k] for k in ("numbers_ok", "citations_ok", "pii_ok", "control_ok", "no_forbidden_leak"))
