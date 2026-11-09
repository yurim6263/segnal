"""세그먼트 자산 대장 조회(F1)와 교체 추천 목록(F5). 정답 컬럼이 나가지 않도록 segments·leaks 원본 대신 뷰를 읽는다."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path

from db import connect


def _last(part: str) -> str:
    return (f"(SELECT MAX(m.date) FROM maintenance m WHERE m.segment_serial = s.segment_serial "
            f"AND m.part = '{part}' AND m.type = 'replace') AS last_{part}")


_BASE = f"""
SELECT s.segment_serial, s.commission_date, i.position, i.bundle_id, i.install_ts,
       {_last('seal')}, {_last('rotary_joint')}, {_last('bearing')}
FROM v_segments s
LEFT JOIN installs i ON i.segment_serial = s.segment_serial AND i.remove_ts IS NULL
"""


def list_segments(path: Path | str | None = None) -> list[dict]:
    sql = _BASE + " ORDER BY i.position IS NULL, i.position, s.segment_serial"
    with closing(connect(path)) as c:
        return [dict(r) for r in c.execute(sql)]


def get_segment(serial: str, path: Path | str | None = None) -> dict | None:
    with closing(connect(path)) as c:
        row = c.execute(_BASE + " WHERE s.segment_serial = ?", (serial,)).fetchone()
        if row is None:
            return None
        out = dict(row)
        for key, table, order in (("installs", "installs", "install_ts"),
                                  ("maintenance", "maintenance", "date"),
                                  ("leaks", "v_leaks", "ts")):
            out[key] = [dict(r) for r in c.execute(
                f"SELECT * FROM {table} WHERE segment_serial = ? ORDER BY {order} DESC", (serial,))]
        return out


def replacement_plan(board: dict, capacity: int) -> dict:
    """F5 교체 추천: 확률 순으로 교체 가능 수만큼 고른다. 조립 불량이 유력하면 교체 칸을 쓰지 않고 점검으로 둔다."""
    items, left = [], capacity
    for seg in board["segments"]:               # risk_board()가 이미 확률 순으로 정렬해 돌려준다
        if left == 0:
            break
        if seg["top_cause"] == "ASSEMBLY":
            action = "inspect"
        else:
            action, left = "replace", left - 1
        items.append({k: seg[k] for k in ("rank", "segment", "position", "bundle", "prob_next_stop",
                                          "top_cause", "top_cause_label")} | {"action": action})
    return {"as_of": board["as_of"], "next_planned_stop": board["next_planned_stop"],
            "capacity": capacity, "items": items, "is_synthetic": True}
