"""SQLite 연결과 스키마. 파일은 data/caster.db 에 만들어진다."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "caster.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS joints (
    joint_id        TEXT PRIMARY KEY,      -- 예: S05-R03-in
    segment         INTEGER NOT NULL,
    roll            INTEGER NOT NULL,
    side            TEXT NOT NULL,         -- in / out
    install_day     REAL NOT NULL,         -- 기준일(0) 대비 설치 시점(일, 음수 = 과거)
    replace_count   INTEGER NOT NULL DEFAULT 0,
    last_replace_day REAL,
    access_risk     REAL NOT NULL,         -- 0~1 가상값 (O1)
    inspect_minutes REAL NOT NULL          -- 가상값 (O1)
);
CREATE TABLE IF NOT EXISTS maintenance_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    day       REAL NOT NULL,
    joint_id  TEXT NOT NULL,
    action    TEXT NOT NULL,               -- replace / inspect / leak_repair
    note      TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scenarios (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    layout      TEXT NOT NULL,             -- S-A / S-B
    labels_json TEXT NOT NULL              -- 정답 라벨(이벤트 목록)
);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    level       TEXT NOT NULL,
    cause       TEXT NOT NULL,
    candidates_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS inspections (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id  TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    result       TEXT NOT NULL,            -- leak_confirmed / no_issue
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    sim_ts       INTEGER                   -- 시뮬레이션 시각(분)
);
CREATE TABLE IF NOT EXISTS agent_cache (
    question    TEXT PRIMARY KEY,
    answer      TEXT NOT NULL,
    tools_json  TEXT NOT NULL DEFAULT '[]'
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path | str | None = None) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
    try:                                   # 예전 DB 파일에 sim_ts가 없으면 추가
        conn.execute("ALTER TABLE inspections ADD COLUMN sim_ts INTEGER")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return conn
