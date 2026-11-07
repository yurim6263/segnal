"""모델 답변의 숫자 검증: 답에 나온 숫자는 도구가 돌려준 값(반올림 허용)과 일치해야 한다.

규칙
 - 답의 숫자를 쓰인 소수 자릿수로 반올림한 도구 값과 비교한다 (51.2 → '51', 3.84 → '3.8').
 - 비율(0.77)을 퍼센트(77)로, 분을 시간·일로 바꾼 표기는 허용한다.
 - 20 이하의 정수(세그먼트·묶음 번호, 순위, 횟수 등)는 검증하지 않는다. → 한계: 작은 정수가 틀려도 잡지 못한다.
"""
from __future__ import annotations

import re
from typing import Any

NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")
FREE_INT_MAX = 20


def numbers_in(obj: Any) -> list[float]:
    out: list[float] = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return [float(m) for m in NUM.findall(obj)]
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += numbers_in(v)
    return out


def _expand(vals: list[float]) -> list[float]:
    ex = set()
    for v in vals:
        a = abs(v)
        ex.update({a, a * 100, a / 60, a / 1440})
    return list(ex)


def unmatched(answer: str, tool_results: list[Any], extra_text: str = "") -> list[str]:
    allowed = _expand(numbers_in(tool_results) + [float(m) for m in NUM.findall(extra_text)])
    bad: list[str] = []
    for tok in NUM.findall(answer):
        d = len(tok.split(".")[1]) if "." in tok else 0
        x = abs(float(tok))
        if d == 0 and x <= FREE_INT_MAX:
            continue
        if any(round(v, d) == round(x, d) or abs(v - x) < 1e-9 for v in allowed):
            continue
        bad.append(tok)
    return bad
