"""FastAPI 앱. 위험 예측·작업지시서·보안 질의응답과 E1 조기 감지 API를 함께 제공한다.

/docs 에서 API 문서를 볼 수 있다. 데이터 준비는 README의 실행 순서를 따른다.
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.envfile import load_env, llm_available, MODEL_QA, MODEL_NOTE
from agent import qa as agent_qa, note as agent_note
from db import init_db
import queries
import service
from core import cost as cost_core
from core.handover import polish_note
from schemas import (
    AskIn, AskOut, CostIn, CostOut, DetectorEval, HandoverOut, HandoverPolishIn, InspectionIn, InspectionOut,
    JointRisk, PlantConfigOut, PriorEval, ReplacementPlanIn, ReplacementPlanOut, ScenarioInfo, SegmentDetail,
    SegmentOut, SeriesOut, StateOut,
)
from sim.config import load_config

load_env()                    # backend/.env 의 ANTHROPIC_API_KEY (없으면 정해진 양식으로 동작)
MOCK_DIR = Path(__file__).resolve().parents[1] / "frontend" / "src" / "mock"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:                       # 첫 요청이 느리지 않게 미리 계산해 둔다 (약 10초)
        service.static()
        service.runtime("leak_ramp_s5")
        import anthropic  # noqa: F401  첫 '문장 다듬기'가 패키지 로딩을 기다리지 않게 한다
    except Exception as e:     # 데이터가 없으면 mock으로만 동작
        print("[warn] service warm-up failed:", e)
    try:
        init_db().close()
    except Exception as e:
        print("[warn] db init failed:", e)
    yield


app = FastAPI(title="세그먼트 냉각수 누수 예측·예방 API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *[o for o in os.environ.get("CORS_EXTRA", "").split(",") if o]],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _mock(name: str):
    return json.loads((MOCK_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _check(scenario_id: str) -> None:
    if scenario_id not in service.SCENARIO_NAMES:
        raise HTTPException(404, f"unknown scenario: {scenario_id}")


@app.get("/api/config", response_model=PlantConfigOut)
def get_config() -> PlantConfigOut:
    cfg = load_config()  # config/plant.yaml (값을 바꾸면 즉시 반영)
    return PlantConfigOut(
        n_segments=cfg.n_segments,
        sensor_groups=cfg.sensor_groups,
        rolls_per_segment=cfg.rolls_per_segment,
        joints_per_roll=cfg.joints_per_roll,
    )


@app.get("/api/scenarios", response_model=list[ScenarioInfo])
def list_scenarios():
    return service.scenario_infos()


@app.post("/api/scenarios/{scenario_id}/start")
def start_scenario(scenario_id: str):
    _check(scenario_id)
    service.reset_inspections(scenario_id)       # 점검 입력 기록 초기화
    return {"ok": True, "scenario_id": scenario_id}


@app.get("/api/state", response_model=StateOut)
def get_state(scenario_id: str = "leak_ramp_s5", ts: int | None = None):
    _check(scenario_id)
    return service.state_at(scenario_id, ts)


@app.get("/api/series", response_model=SeriesOut)
def get_series(scenario_id: str = "leak_ramp_s5", group: int = 2, ts: int | None = None, channel: str = "imb_mass"):
    _check(scenario_id)
    return service.series_at(scenario_id, group + 1, ts, channel=channel)   # group은 0부터


@app.post("/api/inspections", response_model=InspectionOut)
def post_inspection(body: InspectionIn):
    _check(body.scenario_id)
    try:
        service.add_inspection(body.scenario_id, body.candidate_id, body.result, body.ts)
    except ValueError as e:
        raise HTTPException(400, str(e))
    cands, _ = service.candidates_at(body.scenario_id, body.ts if body.ts is not None else 10**9)
    return {"ok": True, "candidates": cands, "inspections": service.inspections_at(body.scenario_id, body.ts)}


@app.delete("/api/inspections/{insp_id}")
def delete_inspection(insp_id: int, scenario_id: str):
    """잘못 입력한 점검 결과를 지운다 (지운 뒤 상태를 다시 요청하면 순위가 다시 계산된다)."""
    _check(scenario_id)
    service.delete_inspection(scenario_id, insp_id)
    return {"ok": True}


@app.get("/api/joints", response_model=list[JointRisk])
def get_joints():
    return service.joint_risks()


@app.get("/api/agent/status")
def agent_status():
    """질의응답이 모델을 쓰는지(키 있음) 정해진 양식으로 동작하는지 화면에 알려 준다. 키 값은 돌려주지 않는다."""
    return {"llm_available": llm_available(), "model_qa": MODEL_QA() if llm_available() else None,
            "model_note": MODEL_NOTE() if llm_available() else None, "presets": agent_qa.PRESETS}


@app.post("/api/agent/ask", response_model=AskOut)
def ask(body: AskIn):
    _check(body.scenario_id)
    T = len(service.runtime(body.scenario_id).df)
    ts = T - 1 if body.ts is None else max(0, min(int(body.ts), T - 1))
    return agent_qa.ask(body.scenario_id, ts, body.question)


@app.get("/api/handover", response_model=HandoverOut)
def handover(scenario_id: str = "leak_ramp_s5", ts: int | None = None):
    _check(scenario_id)
    h = service.handover_at(scenario_id, ts)       # 양식 노트(계산값)
    return agent_note.polish(h, scenario_id, -1 if ts is None else ts)   # 키가 있으면 문장만 다듬는다(값은 검증, 실패 시 양식 그대로)


@app.post("/api/handover/polish", response_model=HandoverOut)
def polish_handover(body: HandoverPolishIn):
    """사람이 '문장 다듬기'를 눌렀을 때만 LLM을 호출한다. 실패하면 템플릿 노트와 이유를 돌려준다."""
    _check(body.scenario_id)
    return polish_note(service.handover_at(body.scenario_id, body.ts))


@app.post("/api/cost", response_model=CostOut)
def cost(body: CostIn) -> CostOut:
    """계획 교체와 비계획 교체의 비용 비교. 금액·시간은 모두 입력값이며 이 서버가 만들지 않는다."""
    values = body.model_dump()
    res = cost_core.compare(values)
    out = CostOut(**res)
    out.note = "입력값 기준 계산입니다. 기본 금액은 없으며 현장 값 확인 전입니다."
    if not res["ready"]:
        return out
    if body.failure_after_leak_min is not None and body.wait_to_window_min is not None:
        head = service.eval_summary().get("headline") or {}
        d_ours = (head.get("ours") or {}).get("median_delay_min")
        d_fixed = (head.get("fixed") or {}).get("median_delay_min")
        out.detector_delay_min = {"ours": d_ours, "fixed": d_fixed}
        out.conversion = cost_core.conversion(d_ours, d_fixed, body.failure_after_leak_min, body.wait_to_window_min)
    return out


@app.get("/api/risk/board")
def risk_board():
    return service.risk_board()


@app.get("/api/risk/segments/{serial}/history")
def risk_history(serial: str, days: int = 30):
    if not 1 <= days <= 730:
        raise HTTPException(422, "days 는 1~730 이어야 합니다")
    try:
        return service.risk_history(serial, days)
    except KeyError:
        raise HTTPException(404, f"세그먼트 없음: {serial}")


@app.get("/api/risk/eval")
def risk_eval():
    try:
        return service.risk_eval()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.get("/api/segments", response_model=list[SegmentOut])
def get_segments():
    return queries.list_segments()


@app.get("/api/segments/{serial}", response_model=SegmentDetail)
def get_segment(serial: str):
    row = queries.get_segment(serial)
    if row is None:
        raise HTTPException(404, "세그먼트 없음")
    return row


@app.post("/api/replacement-plan", response_model=ReplacementPlanOut)
def replacement_plan(body: ReplacementPlanIn):
    return queries.replacement_plan(service.risk_board(), body.capacity)


@app.get("/api/eval/detectors", response_model=list[DetectorEval])
def eval_detectors():
    return service.eval_detectors() or _mock("eval_detectors")


@app.get("/api/eval/priors", response_model=list[PriorEval])
def eval_priors():
    return service.eval_priors() or _mock("eval_priors")


@app.get("/api/eval/summary")
def eval_summary():
    return service.eval_summary()

# ---- 보안 LLM (기획서 4-6): 질의응답·작업지시서·감사 로그. 역할은 데모용으로 요청에 담아 보낸다(실서비스는 사내 인증 연동) ----
from pydantic import BaseModel
from llm import policy as llm_policy, workorder as llm_wo
from llm.gateway import Gateway as _Gateway

_gw: _Gateway | None = None


def _gateway() -> _Gateway:
    global _gw
    if _gw is None:
        _gw = _Gateway()
    return _gw


def _subj(role: str, user: str = "demo") -> llm_policy.Subject:
    try:
        return llm_policy.Subject(role, user or "demo")
    except ValueError as e:
        raise HTTPException(400, str(e))


class LlmAskIn(BaseModel):
    role: str
    user: str = "demo"
    question: str


class WoCreateIn(BaseModel):
    role: str
    user: str = "demo"
    segment: str


class WoEditIn(BaseModel):
    role: str
    user: str = "demo"
    draft_md: str


class WoApproveIn(BaseModel):
    role: str
    user: str = "demo"


@app.get("/api/llm/roles")
def llm_roles():
    return {"roles": [{"role": r, "max_tier": v["max_tier"], "desc": v["desc"]} for r, v in llm_policy.ROLES.items()],
            "adapter": _gateway().adapter.name, "llm_available": _gateway().adapter.available()}


@app.post("/api/llm/ask")
def llm_ask(body: LlmAskIn):
    return _gateway().ask(_subj(body.role, body.user), body.question)


@app.post("/api/llm/workorders")
def llm_wo_create(body: WoCreateIn):
    try:
        return llm_wo.generate(_gateway(), _subj(body.role, body.user), body.segment)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/llm/workorders")
def llm_wo_list():
    return llm_wo.list_orders()


@app.get("/api/llm/workorders/{wo_id}")
def llm_wo_get(wo_id: str):
    wo = llm_wo.get(wo_id)
    if not wo:
        raise HTTPException(404, "작업지시서 없음")
    return wo


@app.put("/api/llm/workorders/{wo_id}")
def llm_wo_edit(wo_id: str, body: WoEditIn):
    try:
        return llm_wo.edit(_subj(body.role, body.user), wo_id, body.draft_md)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.post("/api/llm/workorders/{wo_id}/approve")
def llm_wo_approve(wo_id: str, body: WoApproveIn):
    try:
        return llm_wo.approve(_subj(body.role, body.user), wo_id)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/api/llm/audit")
def llm_audit(role: str, limit: int = 50):
    try:
        return _gateway().audit_log(_subj(role), limit)
    except PermissionError as e:
        raise HTTPException(403, str(e))


@app.get("/api/llm/redteam")
def llm_redteam():
    p = Path(__file__).resolve().parents[1] / "data" / "health" / "redteam.json"
    if not p.exists():
        raise HTTPException(404, "redteam.json 없음: python -m eval.redteam_eval 을 먼저 실행")
    d = json.loads(p.read_text(encoding="utf-8"))
    for k in ("rules", "claude"):
        if k in d:
            d[k].pop("rows", None)
    return d


@app.get("/api/llm/policy")
def llm_policy_matrix():
    """역할별로 AI가 읽을 수 있는 문서 조항 수와 도구. 조항 본문은 돌려주지 않는다."""
    gw = _gateway()
    out = []
    for role, v in llm_policy.ROLES.items():
        idx = gw.index.allowed(role)
        docs: dict = {}
        for i in idx:
            c = gw.index.chunks[i]
            d = docs.setdefault(c.doc_id, {"doc_id": c.doc_id, "title": c.doc_title, "clauses": 0, "tiers": set()})
            d["clauses"] += 1
            d["tiers"].add(c.tier)
        out.append({"role": role, "desc": v["desc"], "max_tier": v["max_tier"], "clauses": len(idx), "total_clauses": len(gw.index.chunks),
                    "docs": [{**d, "tiers": sorted(d["tiers"])} for d in docs.values()],
                    "tools": [t for t, rs in llm_policy.TOOL_ROLES.items() if role in rs]})
    return {"roles": out, "tiers": llm_policy.TIERS}


class WoResultIn(BaseModel):
    role: str
    user: str = "demo"
    grade: str
    cause: str
    note: str = ""


@app.post("/api/llm/workorders/{wo_id}/result")
def llm_wo_result(wo_id: str, body: WoResultIn):
    try:
        return llm_wo.record_result(_subj(body.role, body.user), wo_id, body.grade, body.cause, body.note)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
