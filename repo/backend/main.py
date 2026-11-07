"""FastAPI 앱. 시나리오·상태·후보는 service.py의 실제 계산 결과이고, 질의응답·인수인계는 17단계 전까지 mock이다.

/docs 에서 API 문서를 볼 수 있다. 데이터를 아직 만들지 않았다면 python -m sim.generate 를 먼저 실행한다.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.envfile import load_env, llm_available, MODEL_QA, MODEL_NOTE
from agent import qa as agent_qa, note as agent_note
import service
from schemas import (
    AskIn, AskOut, DetectorEval, HandoverOut, InspectionIn, InspectionOut,
    JointRisk, PlantConfigOut, PriorEval, ScenarioInfo, SeriesOut, StateOut,
)
from sim.config import load_config

load_env()                    # backend/.env 의 ANTHROPIC_API_KEY (없으면 정해진 양식으로 동작)
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


@app.get("/api/eval/detectors", response_model=list[DetectorEval])
def eval_detectors():
    return service.eval_detectors() or _mock("eval_detectors")


@app.get("/api/eval/priors", response_model=list[PriorEval])
def eval_priors():
    return service.eval_priors() or _mock("eval_priors")


@app.get("/api/eval/summary")
def eval_summary():
    return service.eval_summary()
