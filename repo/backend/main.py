"""FastAPI 앱. 화면이 쓰는 위험 예측·작업지시서 API를 제공한다.

/docs 에서 API 문서를 볼 수 있다. 데이터 준비는 README의 실행 순서를 따른다.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.envfile import load_env
import service

load_env()                   # backend/.env 의 ANTHROPIC_API_KEY (없으면 정해진 양식으로 동작)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        import anthropic  # noqa: F401  첫 LLM 호출이 패키지 로딩을 기다리지 않게 한다
    except Exception as e:
        print("[warn] anthropic import failed:", e)
    yield


app = FastAPI(title="세그먼트 냉각수 누수 예측·예방 API", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *[o for o in os.environ.get("CORS_EXTRA", "").split(",") if o]],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# ---- 보안 LLM (기획서 4-6): 작업지시서. 역할은 데모용으로 요청에 담아 보낸다(실서비스는 사내 인증 연동) ----
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


@app.post("/api/llm/workorders")
def llm_wo_create(body: WoCreateIn):
    try:
        return llm_wo.generate(_gateway(), _subj(body.role, body.user), body.segment)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/llm/workorders")
def llm_wo_list():
    return llm_wo.list_orders()


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
