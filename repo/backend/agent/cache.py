"""질의응답·노트 답변 캐시 (SQLite). 키는 질문 + 화면 상태 지문이라, 상태가 같으면 모델을 부르지 않고 같은 답을 즉시 낸다."""
from __future__ import annotations

import hashlib
import json

from db import init_db

_DDL = "CREATE TABLE IF NOT EXISTS agent_cache2 (key TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL)"


def _conn():
    c = init_db()
    c.execute(_DDL)
    return c


def make_key(kind: str, *parts) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return f"{kind}:" + hashlib.sha1(raw.encode("utf-8")).hexdigest()


def get(key: str) -> dict | None:
    row = _conn().execute("SELECT payload FROM agent_cache2 WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def put(key: str, kind: str, payload: dict) -> None:
    c = _conn()
    c.execute("INSERT OR REPLACE INTO agent_cache2 (key, kind, payload) VALUES (?,?,?)", (key, kind, json.dumps(payload, ensure_ascii=False)))
    c.commit()
