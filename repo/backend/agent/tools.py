"""질의응답 에이전트의 도구. 읽기 전용 조회 도구 7개 + 쓰기 도구 1개(사람 확인 전에는 실행하지 않는다).

도구는 service.py의 계산 결과를 그대로 돌려준다. 모델이 숫자를 새로 만들지 못하도록, 답에 쓰일 값은 모두 여기서 나온다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import service

CHANNELS = {"imb_mass": "공급-회수 질량 불균형(%)", "m_in": "입구 질량유량(kg/min)", "p_in": "공급 압력(bar)", "p_out": "회수 압력(bar)"}


@dataclass
class Ctx:
    scenario_id: str
    ts: int
    proposed: dict | None = None                    # 쓰기 도구가 제안한 점검 기록 (사람이 확인해야 반영)
    used: list[str] = field(default_factory=list)


TOOLS = [
    {"name": "get_status",
     "description": "현재 시각의 전체 상태: 단계(정상/주의/경보), 한 줄 요약, 묶음별 상태와 편차, 운전 조건, 경보 시각, 두 방식(추세 감지·고정 임계값)의 경보 시점, 점검으로 확인된 세그먼트.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_cause_table",
     "description": "원인 분류표: 누수/계측기 오차/막힘/펌프 저하 각각의 판정 규칙, 지금 신호 값, 판정.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_diagnosis_detail",
     "description": "원인 구분 근거(누수와 계측기 오차 중 어느 쪽에 가까운지: 후보별 사이각, 신호별 변화량 σ, 구분 불가 여부, 확인 방법), 경보선(기존 방식의 고정 임계값) 도달 예상 시각과 범위, 추정 누수량(L/min과 범위). 없는 값은 null이다.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_location_candidates",
     "description": "점검할 세그먼트 후보: 확률(가능성), 순위, 점검 순서(점검 부담 반영), 이미 점검한 곳, 근거 문장. 후보는 세그먼트 단위이고 롤·조인트는 신호로 구분되지 않는다.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_signal",
     "description": "한 계측 묶음의 한 신호에 대한 최근 값 요약(실측, 기준선, 차이, 평활 값, 경보 한계)과 최근 6시간 동안의 변화.",
     "input_schema": {"type": "object", "properties": {
         "group": {"type": "integer", "description": "계측 묶음 번호(1부터)"},
         "channel": {"type": "string", "enum": list(CHANNELS), "description": "imb_mass|m_in|p_in|p_out"}},
         "required": ["group", "channel"], "additionalProperties": False}},
    {"name": "get_inspections",
     "description": "지금까지 기록된 점검 결과(세그먼트, 결과, 시각)와 경보 뒤 확인까지 걸린 시간.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_eval_results",
     "description": "합성 데이터로 잰 평가 결과: 추세 감지 vs 고정 임계값(탐지 지연·오경보·놓침), 원인 분류 정확도, 위치 후보 적중률, 점검 횟수 비교, 조건이 바뀔 때의 민감도.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "propose_inspection_record",
     "description": "사용자가 현장 점검 결과를 직접 말했을 때만 호출한다. 기록을 바로 저장하지 않고 '사람 확인 대기' 제안만 만든다. 사용자가 말하지 않은 결과를 추측해서 호출하지 않는다.",
     "input_schema": {"type": "object", "properties": {
         "segment": {"type": "integer", "description": "점검한 세그먼트 번호"},
         "result": {"type": "string", "enum": ["no_issue", "leak_confirmed"]},
         "reason": {"type": "string", "description": "사용자가 말한 내용 요약"}},
         "required": ["segment", "result"], "additionalProperties": False}},
]
READ_ONLY = {t["name"] for t in TOOLS} - {"propose_inspection_record"}


def _fmt_ts(ts: int | None) -> str | None:
    return None if ts is None else f"{ts // 1440 + 1}일차 {(ts % 1440) // 60:02d}:{ts % 60:02d}"


def run_tool(name: str, args: dict, ctx: Ctx) -> dict:
    ctx.used.append(name)
    sid, ts = ctx.scenario_id, ctx.ts
    if name == "get_status":
        s = service.state_at(sid, ts)
        a = s["alert"]
        return {
            "level": {"normal": "정상", "watch": "주의", "alarm": "경보"}[a["level"]],
            "headline": s["summary"]["headline"], "detail": s["summary"]["detail"],
            "groups": [{"group": g["group"] + 1, "segments": g["segments"], "level": {"normal": "정상", "watch": "주의", "alarm": "경보"}[g["level"]],
                        "deviation_vs_limit": g["deviation"]} for g in s["groups"]],
            "operating": s["operating"],
            "alarm_time": _fmt_ts(a["since_ts"]), "minutes_since_alarm": s["minutes_since_alarm"],
            "detector_alarm_time": {"추세 감지(EWMA)": _fmt_ts(a["detectors"]["ewma_alarm_ts"]), "CUSUM": _fmt_ts(a["detectors"]["cusum_alarm_ts"]),
                                    "고정 임계값": _fmt_ts(a["detectors"]["fixed_alarm_ts"])},
            "detector_alarm_minutes": {k: v for k, v in a["detectors"].items()},
            "confirmed_leak_segment_by_inspection": s["confirmed_segment"], "now": _fmt_ts(ts),
            "note": "경보(■)는 사람이 점검으로 누수를 확인한 뒤에만 켜진다. 주의(▲)는 시스템의 의심 단계다.",
        }
    if name == "get_cause_table":
        return {"rows": service.state_at(sid, ts)["cause_table"]}
    if name == "get_diagnosis_detail":
        s = service.state_at(sid, ts)
        p, f, e = s.get("pattern"), s.get("forecast"), s.get("leak_estimate")
        return {
            "cause": s["alert"]["cause"],
            "pattern": None if not p else {"verdict": p["verdict"], "how_to_check": p["how_to_check"], "ambiguous": p["ambiguous"],
                                          "gap_deg": p["gap_deg"], "observed_window_min": p["window_min"],
                                          "angle_by_candidate_deg": {r["label"]: r["angle"] for r in p["ranking"]},
                                          "signal_change_in_sigma": {x["label"]: x["sigma"] for x in p["signals"]}},
            "forecast_to_old_alarm_line": None if not f else {k: f.get(k) for k in ("text", "hours", "low_hours", "high_hours", "slope_pct_per_hour", "progress", "line_leak_pct", "reason", "crossed")},
            "leak_estimate": e,
            "note": "합성 데이터. 도달 시각은 누수가 일정 속도로 커진다는 직선 가정이며, 진행이 멈추면 닿지 않는다. 사이각이 작을수록 그 고장의 모습에 가깝다.",
        }
    if name == "get_location_candidates":
        s = service.state_at(sid, ts)
        return {
            "candidates": [{"segment": c["segment"], "probability_pct": round(c["prob"] * 100, 1), "rank": c["rank"],
                            "inspection_order": c["priority_rank"], "already_inspected": c["inspected"],
                            "inspect_minutes": c["inspect_minutes"], "access_risk": c["access_risk"], "evidence": c["evidence"]}
                           for c in s["segment_candidates"]],
            "others_probability_pct": round(s["others_prob"] * 100, 1), "distinguishable_within_group": s["distinguishable"],
            "note": s["candidate_note"], "empty_reason": None if s["segment_candidates"] else "누수로 판정되기 전이라 후보 순위가 없다",
        }
    if name == "get_signal":
        g, ch = int(args["group"]), args["channel"]
        if ch not in CHANNELS:
            return {"error": "알 수 없는 신호"}
        se = service.series_at(sid, g, ts, 5, ch)
        pts = se["points"]
        last = pts[-1]
        def at(back):
            tgt = last["ts"] - back
            return min(pts, key=lambda p: abs(p["ts"] - tgt))
        out = {"signal": CHANNELS[ch], "group": g, "unit": se["unit"], "time": _fmt_ts(last["ts"]),
               "actual": last["value"], "baseline": last["baseline"], "difference": last["residual"], "smoothed": last["ewma"],
               "ewma_limit": se["ewma_limit"]}
        if ch == "imb_mass":
            out["cusum_limit"] = se["cusum_limit"]
        out["difference_6h_ago"] = at(360)["residual"]
        out["difference_3h_ago"] = at(180)["residual"]
        out["difference_1h_ago"] = at(60)["residual"]
        return out
    if name == "get_inspections":
        s = service.state_at(sid, ts)
        return {"inspections": [{"segment": i["segment"], "result": "누수 확인" if i["result"] == "leak_confirmed" else "이상 없음",
                                 "time": _fmt_ts(i["sim_ts"])} for i in s["inspections"]],
                "minutes_to_confirm_after_alarm": s["minutes_to_confirm"]}
    if name == "get_eval_results":
        e = service.eval_summary()
        h = e.get("headline") or {}
        pick = lambda r: None if not r else {k: r[k] for k in ("label", "false_alarms_per_14d_per_group", "detected", "missed", "n", "median_delay_min", "p90_delay_min")}
        out = {"data": "합성 데이터, 임계값은 가설", "ours": pick(h.get("ours")), "fixed_threshold": pick(h.get("fixed"))}
        if e.get("classify"):
            out["classification_accuracy"] = e["classify"]["accuracy"]
        if e.get("inspection"):
            out["inspection_policies"] = e["inspection"]
        if e.get("localize"):
            first = next(iter(e["localize"].values()))
            out["localization_group_top1"] = first["weibull"]["group_top1"]
            out["localization_segment_top1"] = first["weibull"]["segment_top1"]
        if e.get("sensitivity"):
            out["sensitivity"] = [{k: r[k] for k in ("label", "median_delay_min", "missed", "n_leaks", "false_alarms_per_14d_per_group", "top3_hit", "mean_inspections")}
                                  for r in e["sensitivity"]["rows"]]
        return out
    if name == "propose_inspection_record":
        seg, res = int(args["segment"]), args["result"]
        ctx.proposed = {"segment": seg, "result": res, "reason": str(args.get("reason", ""))[:200]}
        return {"status": "pending_human_confirmation",
                "message": "아직 기록되지 않았다. 사용자가 화면의 '확인' 버튼을 눌러야 기록된다. 답에서 '기록했다'고 말하지 말고 '기록하려면 확인 버튼을 눌러 달라'고 안내한다."}
    return {"error": f"알 수 없는 도구: {name}"}
