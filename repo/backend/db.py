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
CREATE TABLE IF NOT EXISTS segments (
    segment_serial  TEXT PRIMARY KEY,
    commission_date TEXT NOT NULL,
    assembly_flag   INTEGER NOT NULL          -- 정답: v_segments에서 제외
);
CREATE TABLE IF NOT EXISTS installs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    segment_serial TEXT NOT NULL REFERENCES segments(segment_serial),
    position       INTEGER NOT NULL,
    install_ts     TEXT NOT NULL,
    remove_ts      TEXT,                      -- 장착 중이면 NULL
    pressure_test  INTEGER,
    bundle_id      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_installs_position ON installs(position) WHERE remove_ts IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_installs_serial ON installs(segment_serial) WHERE remove_ts IS NULL;
CREATE TABLE IF NOT EXISTS maintenance (
    mnt_id           INTEGER PRIMARY KEY,
    segment_serial   TEXT NOT NULL REFERENCES segments(segment_serial),
    date             TEXT NOT NULL,
    part             TEXT NOT NULL,
    type             TEXT NOT NULL,
    resets_joint_age INTEGER,
    pressure_test    INTEGER,
    finding_grade    INTEGER,
    found_cause      TEXT,
    wo_id            TEXT                     -- 작업지시서는 workorders.db에 있어 외래키 없음
);
CREATE TABLE IF NOT EXISTS leaks (
    leak_id        TEXT PRIMARY KEY,
    ts             TEXT NOT NULL,
    segment_serial TEXT NOT NULL REFERENCES segments(segment_serial),
    position       INTEGER NOT NULL,
    bundle_id      TEXT NOT NULL,
    part           TEXT NOT NULL,
    cause_code     TEXT NOT NULL,             -- 정답: v_leaks에서 제외
    leak_lpm       REAL,
    found_by       TEXT
);
CREATE TABLE IF NOT EXISTS segment_daily (
    date TEXT NOT NULL,
    segment_serial TEXT NOT NULL REFERENCES segments(segment_serial),
    position INTEGER NOT NULL, bundle_id TEXT NOT NULL,
    tons REAL, cast_hours REAL, cast_speed_avg REAL, thermal_cycles INTEGER,
    low_flow_min REAL, pressure_events INTEGER, t_out_avg_c REAL,
    bearing_t_avg_c REAL, vib_rms_mm_s REAL, joint_age_t REAL, days_since_install REAL,
    PRIMARY KEY (date, segment_serial)
);
CREATE TABLE IF NOT EXISTS water_quality (
    date TEXT PRIMARY KEY, turbidity_ntu REAL, hardness_mg_l REAL,
    conductivity_us_cm REAL, ph REAL, filter_dp_bar REAL
);
CREATE TABLE IF NOT EXISTS ops_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL, event_type TEXT NOT NULL, bundle_id TEXT, note TEXT
);
CREATE VIEW IF NOT EXISTS v_segments AS
    SELECT segment_serial, commission_date FROM segments;
CREATE VIEW IF NOT EXISTS v_leaks AS
    SELECT leak_id, ts, segment_serial, position, bundle_id, part, leak_lpm, found_by FROM leaks;
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
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
