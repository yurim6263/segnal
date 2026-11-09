"""보안 정책: 데이터 등급, 역할별 열람 범위, 도구 권한, 마스킹. 통제는 모델 밖에서 하고, 모델은 허용된 것만 받는다.

등급: 일반(0) < 내부(1) < 제한(2). 문서 조항은 등급과 열람 가능 역할을 함께 가지며 둘 다 맞아야 열람할 수 있다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

TIERS = {"일반": 0, "내부": 1, "제한": 2}
ROLES = {
    "정비담당": {"max_tier": 1, "desc": "현장 정비 담당: 정비 표준·조치 카드·안전 절차, 세그먼트 위험과 신호"},
    "정비계획": {"max_tier": 2, "desc": "정비 계획 담당: 위 범위 + 예비품·비용, 평가 결과"},
    "수처리담당": {"max_tier": 1, "desc": "수처리 담당: 수질·유량 관련 문서와 신호만"},
    "관리자": {"max_tier": 2, "desc": "설비 관리자: 전체 + 감사 로그"},
}
# 도구 이름 -> 사용 가능 역할
TOOL_ROLES = {
    "get_risk_board": ["정비담당", "정비계획", "수처리담당", "관리자"],
    "get_segment_risk": ["정비담당", "정비계획", "수처리담당", "관리자"],
    "get_eval_results": ["정비계획", "관리자"],
}
# 수처리 담당에게 보여 주는 원인·신호
WATER_CAUSES = {"HAMMER", "WATER"}
WATER_SIGNALS = {"low_flow_index"}


@dataclass(frozen=True)
class Subject:
    role: str
    user: str = "demo"

    def __post_init__(self):
        if self.role not in ROLES:
            raise ValueError(f"알 수 없는 역할: {self.role}")


def can_read_chunk(role: str, tier: str, roles: list[str]) -> bool:
    return role in roles and TIERS[tier] <= ROLES[role]["max_tier"]


def can_use_tool(role: str, tool: str) -> bool:
    return role in TOOL_ROLES.get(tool, [])


def redact_segment(role: str, seg: dict) -> dict:
    """역할별로 세그먼트 위험 값에서 볼 수 없는 필드를 뺀다."""
    if role != "수처리담당":
        return seg
    s = dict(seg)
    s["signals"] = {k: v for k, v in seg.get("signals", {}).items() if k in WATER_SIGNALS}
    s["causes"] = [c for c in seg.get("causes", []) if c["cause"] in WATER_CAUSES]
    if s.get("top_cause") not in WATER_CAUSES:
        s["top_cause"], s["top_cause_label"] = None, "수처리 담당 열람 범위 밖"
    return s


# ---- 마스킹: 모델에 보내기 전에 개인 식별 정보를 지운다 -------------------------------------
_PATTERNS = [
    (re.compile(r"[가-힣]{2,4}(?=\(사번)"), "[이름]"),
    (re.compile(r"사번\s*[A-Z]?\d{4,8}"), "사번 [사번]"),
    (re.compile(r"내선\s*\d{3,4}"), "내선 [내선]"),
    (re.compile(r"01[016789]-?\d{3,4}-?\d{4}"), "[전화]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[이메일]"),
]


def mask(text: str) -> tuple[str, int]:
    n = 0
    for pat, rep in _PATTERNS:
        text, k = pat.subn(rep, text)
        n += k
    return text, n
