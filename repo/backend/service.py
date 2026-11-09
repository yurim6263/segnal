"""API가 쓰는 위험 예측 계산 계층(기획서 4-5): 세그먼트 수명·누수 원인 모델.

모든 데이터는 합성이고 기준값은 가정이다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

_RISK: dict = {}


def risk_board() -> dict:
    """다음 계획 정지 전 누수 위험 순위판. 데이터는 합성이며 첫 호출 때 한 번 맞춘 뒤 메모리에 둔다."""
    if "board" not in _RISK:
        from core import risk
        data = risk.load()
        rows = risk.build_rows(data)
        model = risk.fit(rows[rows["day"] < rows["day"].max()])
        snap = risk.snapshot(model, rows, data)
        _RISK["board"] = {
            "as_of": str((data.start_date + pd.Timedelta(days=int(rows["day"].max()))).date()),
            "next_planned_stop": str((data.start_date + pd.Timedelta(days=data.next_stop_day)).date()),
            "segments": snap, "coefficients": risk.describe(model),
            "note": "합성 데이터. 누수 이력이 적어 계수 추정 폭이 넓고, 신호가 학습 범위를 넘으면 확률이 과대할 수 있다.",
        }
    return _RISK["board"]


_HISTORY_COLS = ["bearing_t_avg_c", "vib_rms_mm_s", "low_flow_min", "pressure_events", "t_out_avg_c", "joint_age_t"]


def risk_history(serial: str, days: int = 30) -> dict:
    """세그먼트의 최근 일별 신호와 정비 이력(합성 데이터). 같은 날 장착 세그먼트 평균을 fleet_ 열로 함께 준다."""
    if "daily" not in _RISK:
        d = Path(__file__).resolve().parents[1] / "data" / "health"
        _RISK["daily"] = pd.read_csv(d / "segment_daily.csv")
        _RISK["maintenance"] = pd.read_csv(d / "maintenance.csv")
    daily, mnt = _RISK["daily"], _RISK["maintenance"]
    if serial not in set(daily["segment_serial"]):
        raise KeyError(serial)
    recent = daily[daily["date"].isin(sorted(daily["date"].unique())[-days:])]
    fleet = recent.groupby("date")[_HISTORY_COLS].mean().round(3).add_prefix("fleet_")
    mine = recent[recent["segment_serial"] == serial].set_index("date")[_HISTORY_COLS]
    table = fleet.join(mine).reset_index()         # 탈거 기간은 신호가 빈칸으로 남는다
    rows = mnt[mnt["segment_serial"] == serial].sort_values("date", ascending=False).head(10)
    rows = rows[["date", "part", "type", "finding_grade", "found_cause", "wo_id"]]
    clean = lambda df: df.astype(object).where(df.notna(), None).to_dict("records")
    return {"segment": serial, "days": clean(table), "maintenance": clean(rows)}


def risk_eval() -> dict:
    p = Path(__file__).resolve().parents[1] / "data" / "health" / "risk_eval.json"
    if not p.exists():
        raise FileNotFoundError("risk_eval.json 없음: python -m eval.risk_eval 을 먼저 실행")
    return json.loads(p.read_text(encoding="utf-8"))
