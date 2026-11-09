"""FastAPI 앱. 시나리오·상태·후보는 service.py의 실제 계산 결과이고, 질의응답·인수인계는 17단계 전까지 mock이다.

/docs 에서 API 문서를 볼 수 있다. 데이터를 아직 만들지 않았다면 python -m sim.generate 를 먼저 실행한다.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import service
from core import cost as cost_core
from schemas import (
    AskIn, AskOut, CostIn, CostOut, DetectorEval, HandoverOut, InspectionIn, InspectionOut,
    JointRisk, PlantConfigOut, PriorEval, ScenarioInfo, SeriesOut, StateOut,
)
from sim.config import load_config

MOCK_DIR = Path(__file__).resolve().parents[1] / "frontend" / "src" / "mock"


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:                       # 첫 요청이 느리지 않게 미리 계산해 둔다 (약 10초)
        service.static()
        service.runtime("leak_ramp_s5")
    except Exception as e:     # 데이터가 없으면 mock으로만 동작
        print("[warn] service warm-up failed:", e)
    yield


app = FastAPI(title="연주기 냉각수 누수 조기 감지 API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
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


@app.post("/api/agent/ask", response_model=AskOut)
def ask(body: AskIn):
    return _mock("ask")                           # 17단계에서 실제 에이전트로 교체


@app.get("/api/handover", response_model=HandoverOut)
def handover(scenario_id: str = "leak_ramp_s5", ts: int | None = None):
    _check(scenario_id)
    return service.handover_at(scenario_id, ts)    # 템플릿 노트 (17단계에서 LLM 문장 다듬기 추가)


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


@app.get("/api/eval/detectors", response_model=list[DetectorEval])
def eval_detectors():
    return service.eval_detectors() or _mock("eval_detectors")


@app.get("/api/eval/priors", response_model=list[PriorEval])
def eval_priors():
    return service.eval_priors() or _mock("eval_priors")


@app.get("/api/eval/summary")
def eval_summary():
    return service.eval_summary()
