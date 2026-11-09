"""교체 시점 권고: 누수가 "이번 시퀀스 휴지에 교체할지, 다음 계획 정지까지 둘지, 지금 점검할지"를 정한다.

입력: 추정 누수량, 교체 필요 크기까지의 추세(core.forecast), 정비 창(시퀀스 휴지·계획 정지)과 준비 시간.
교체 필요 크기와 정비 창 일정은 모두 [가정]이다(config/plant.yaml의 plan 블록). 현업 답변이 오면 그 값만 바꾼다.

규칙(설명 가능한 순서):
 1) 추정 누수량이 교체 필요 크기 이상 → 지금 점검, 교체 준비
 2) 지금 속도가 이어질 때(보수적으로 빠른 쪽) 다음 시퀀스 휴지보다 먼저 한계에 닿음 → 지금 점검, 휴지 앞당김 협의
 3) 한계가 다음 계획 정지보다 먼저 올 수 있거나, 추세가 불분명해도 한계의 watch_ratio 이상 → 다음 시퀀스 휴지에 교체
 4) 그 밖 → 다음 계획 정지까지 감시 유지 (조건 만족 시 재판단)
증가가 멈추면 한계에 닿지 않을 수 있다는 점도 두 경우를 나란히 보여 준다. 모든 데이터는 합성이다.
"""
from __future__ import annotations

import math


def fmt_ts(ts: int) -> str:
    return f"{ts // 1440 + 1}일차 {(ts % 1440) // 60:02d}:{ts % 60:02d}"


def next_windows(ts: int, plan: dict) -> tuple[int, int | None]:
    """준비 시간을 뺀 뒤 처음 오는 시퀀스 휴지 시각과 계획 정지 시각."""
    earliest = ts + int(plan["prep_minutes"])
    every, off = int(plan["sequence_break_every_min"]), int(plan["sequence_break_offset_min"])
    k = max(0, math.ceil((earliest - off) / every))
    t_break = off + k * every
    stops = [int(s) for s in plan.get("planned_stop_min", []) if int(s) >= earliest]
    return t_break, (min(stops) if stops else None)


def assumptions(plan: dict) -> list[str]:
    stops = ", ".join(fmt_ts(int(s)) for s in plan.get("planned_stop_min", [])) or "없음"
    return [f"교체 필요 크기 {plan['replace_limit_lpm']:.0f} L/min (가정, 현업 질문 5)",
            f"시퀀스 휴지 {int(plan['sequence_break_every_min']) // 60}시간마다 (가정)",
            f"계획 정지 {stops} (가정)", f"예비품·인력 준비 {int(plan['prep_minutes'])}분 (가정)"]


def advise(cause: str, est: dict | None, f: dict | None, ts: int, plan: dict) -> dict | None:
    """cause: 확정된 원인. est: 추정 누수량(lpm, high_lpm), f: 교체 필요 크기까지의 추세(core.forecast.forecast_line)."""
    base = {"assumptions": assumptions(plan)}
    if cause == "ambiguous":
        return {**base, "action": "verify", "headline": "교체 판단보다 원인 확인이 먼저입니다. 누수인지 계측기 오차인지 구분되지 않았습니다.",
                "reasons": ["계측기 진단값·교정 이력과 현장(외부 배관) 점검을 함께 확인하세요.", "누수로 확인되면 그때 교체 시점을 권고합니다."], "cases": [],
                "action_ts": None, "next_break": None, "planned_stop": None, "limit_lpm": float(plan["replace_limit_lpm"]), "current_lpm": est["lpm"] if est else None, "progress": None}
    if cause == "sensor":
        return {**base, "action": "verify", "headline": "누수가 아니라 계측기 오차가 의심됩니다. 해당 계측기를 먼저 점검하세요.",
                "reasons": ["교체 권고는 누수로 판정된 경우에만 냅니다."], "cases": [], "action_ts": None, "next_break": None, "planned_stop": None,
                "limit_lpm": float(plan["replace_limit_lpm"]), "current_lpm": None, "progress": None}
    if cause != "leak" or est is None or f is None:
        return None
    L, q, hi = float(plan["replace_limit_lpm"]), float(est["lpm"]), float(est["high_lpm"])
    t_break, t_stop = next_windows(ts, plan)
    to_break, to_stop = (t_break - ts) / 60.0, (None if t_stop is None else (t_stop - ts) / 60.0)
    low_h = f.get("low_hours") if f.get("available") else None
    watch = float(plan["watch_ratio"])
    brk = {"ts": t_break, "label": fmt_ts(t_break), "in_hours": round(to_break, 1)}
    stp = None if t_stop is None else {"ts": t_stop, "label": fmt_ts(t_stop), "in_hours": round(to_stop, 1)}

    reasons: list[str] = []
    if q >= L:
        action, action_ts = "now", ts
        head = f"지금 점검하고 교체를 준비하세요. 추정 누수량({q:.0f} L/min)이 교체 필요 크기({L:.0f} L/min)에 도달했습니다."
        reasons.append("교체 필요 크기를 넘었으므로 다음 정비 창까지 기다리지 않는 쪽을 권고합니다.")
    elif low_h is not None and low_h < to_break:
        action, action_ts = "now", ts
        head = f"지금 점검하세요. 지금 속도가 이어지면 다음 시퀀스 휴지({brk['label']})보다 빨리 교체 필요 크기에 닿을 수 있습니다."
        reasons.append(f"빠른 쪽 추정으로 약 {low_h:.0f}시간 뒤 한계, 다음 휴지는 {to_break:.0f}시간 뒤입니다. 휴지를 앞당길 수 있는지 협의하세요.")
    elif (low_h is not None and (to_stop is None or low_h < to_stop)) or q >= watch * L or hi >= L:
        action, action_ts = "next_break", t_break
        head = f"다음 시퀀스 휴지({brk['label']}, 약 {to_break:.0f}시간 뒤)에 교체하세요. 예비 세그먼트·인력 준비를 지금 시작하세요."
        if low_h is not None:
            reasons.append(f"지금 속도가 이어지면 약 {f['hours']:.0f}시간 뒤(빠르면 {low_h:.0f}시간) 교체 필요 크기에 닿아 계획 정지까지 두기 어렵습니다.")
        if q >= watch * L:
            reasons.append(f"추정 누수량이 교체 필요 크기의 {q / L * 100:.0f}%로, 증가 추세가 불분명해도 한계의 {watch * 100:.0f}%를 넘었습니다.")
        if hi >= L and q < L:
            reasons.append(f"추정 범위 상한({hi:.0f} L/min)이 교체 필요 크기 이상입니다.")
    else:
        action, action_ts = "watch", t_stop
        when = f"다음 계획 정지({stp['label']}, 약 {to_stop:.0f}시간 뒤)" if stp else "다음 정비 창"
        head = f"{when}까지 감시를 유지해도 됩니다. 단 추정 누수량이 {watch * L:.0f} L/min를 넘거나 증가 추세가 뚜렷해지면 다시 판단하세요."
        reasons.append(f"추정 누수량은 교체 필요 크기의 {q / L * 100:.0f}%이고, " + (f"증가 추세로 계산한 한계 도달도 계획 정지보다 늦습니다." if low_h is not None else "증가 추세가 뚜렷하지 않거나 둔화되고 있습니다."))

    cases = []
    if f.get("crossed"):
        cases.append({"label": "증가가 이어지면", "text": "이미 교체 필요 크기를 넘었습니다."})
    elif f.get("available"):
        hi_txt = f"빠르면 {f['low_hours']:.0f}시간" + (f", 늦으면 {f['high_hours']:.0f}시간" if f.get("high_hours") is not None else "")
        cases.append({"label": "지금 속도가 이어지면", "text": f"약 {f['hours']:.0f}시간 뒤 교체 필요 크기에 닿습니다({hi_txt})."})
    else:
        cases.append({"label": "지금 속도가 이어지면", "text": f["reason"] + "."})
    cases.append({"label": "증가가 멈추면", "text": (f"지금 {q:.0f} L/min에 머물러 교체 필요 크기({L:.0f} L/min)에 닿지 않습니다. 감시를 유지하면서 계획 정지에 맞춥니다." if q < L else "이미 넘었으므로 해당 없음.")})
    return {**base, "action": action, "headline": head, "reasons": reasons, "cases": cases, "action_ts": action_ts, "next_break": brk, "planned_stop": stp,
            "limit_lpm": L, "current_lpm": round(q, 1), "progress": round(q / L, 2)}
