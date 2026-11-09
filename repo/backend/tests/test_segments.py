import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import queries  # noqa: E402
from db import init_db  # noqa: E402
from tools.load_db import load  # noqa: E402


def test_ledger_hides_answer_columns(tmp_path):
    db = tmp_path / "t.db"
    conn = init_db(db)
    load(conn)
    conn.close()
    rows = queries.list_segments(db)
    assert len(rows) == 20 and sum(r["position"] is not None for r in rows) == 13
    assert all("assembly_flag" not in r for r in rows)
    detail = queries.get_segment("S-0012", db)
    assert detail["installs"] and all("cause_code" not in x for x in detail["leaks"])
    assert queries.get_segment("없음", db) is None


def _seg(rank, cause):
    return {"rank": rank, "segment": f"S-{rank:04d}", "position": rank, "bundle": "B1",
            "prob_next_stop": 0.5 / rank, "top_cause": cause, "top_cause_label": cause}


def test_replacement_plan_keeps_capacity_for_replacements():
    board = {"as_of": "2026-11-09", "next_planned_stop": "2026-11-12",
             "segments": [_seg(1, "HAMMER"), _seg(2, "ASSEMBLY"), _seg(3, "WEAR"), _seg(4, "BEARING")]}
    plan = queries.replacement_plan(board, 2)
    assert [(i["segment"], i["action"]) for i in plan["items"]] == [
        ("S-0001", "replace"), ("S-0002", "inspect"), ("S-0003", "replace")]
    assert queries.replacement_plan(board, 0)["items"] == []
