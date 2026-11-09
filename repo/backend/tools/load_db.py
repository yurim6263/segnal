"""data/health/*.csv를 data/caster.db에 적재한다. E1 테이블은 건드리지 않는다.
실행: python -m tools.load_db [--if-empty]   (backend 폴더에서)
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

from db import init_db

CSV_DIR = Path(__file__).resolve().parents[2] / "data" / "health"
# 외래키 순서
TABLES = ("segments", "installs", "maintenance", "leaks", "segment_daily", "water_quality", "ops_events")


def load(conn: sqlite3.Connection, csv_dir: Path = CSV_DIR) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn:                              # 전체가 한 트랜잭션. 실패하면 이전 데이터가 남는다
        for table in reversed(TABLES):
            conn.execute(f"DELETE FROM {table}")
        for table in TABLES:
            with (csv_dir / f"{table}.csv").open(encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f)
                head = next(reader)
                rows = [[v if v != "" else None for v in r] for r in reader]   # 빈칸은 NULL
            marks = ",".join("?" * len(head))
            conn.executemany(f"INSERT INTO {table} ({','.join(head)}) VALUES ({marks})", rows)
            counts[table] = len(rows)
    return counts


def main() -> None:
    conn = init_db()
    try:
        if "--if-empty" in sys.argv and conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]:
            print("already loaded")
            return
        print(load(conn))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
