"""감사 로그: 누가, 언제, 무엇을 물었고 어떤 조항·값을 AI에 넘겼으며 어떻게 답했고 검증이 어땠는지 남긴다.
질문·답변은 개인정보 마스킹을 거친 뒤 저장한다. 열람은 관리자만 한다(gateway.audit_log)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "audit.db"
_SCHEMA = """CREATE TABLE IF NOT EXISTS llm_audit(
 id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, user TEXT, role TEXT, kind TEXT, question TEXT,
 refs TEXT, tools TEXT, masked INTEGER, outcome TEXT, reason TEXT, answer TEXT, checks TEXT, mode TEXT, model TEXT)"""


def _con(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p)
    c.execute(_SCHEMA)
    return c


def log(path: Path | None, *, user: str, role: str, kind: str, question: str, refs: list[str], tools: list[str], masked: int,
        outcome: str, reason: str, answer: str, checks: dict, mode: str, model: str) -> int:
    with _con(path) as c:
        cur = c.execute("INSERT INTO llm_audit(ts,user,role,kind,question,refs,tools,masked,outcome,reason,answer,checks,mode,model) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (time.time(), user, role, kind, question[:500], json.dumps(refs, ensure_ascii=False), json.dumps(tools, ensure_ascii=False), masked,
                         outcome, reason, answer[:4000], json.dumps(checks, ensure_ascii=False), mode, model))
        return int(cur.lastrowid)


def recent(path: Path | None = None, limit: int = 50) -> list[dict]:
    with _con(path) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM llm_audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("refs", "tools", "checks"):
            d[k] = json.loads(d[k] or "null")
        out.append(d)
    return out
