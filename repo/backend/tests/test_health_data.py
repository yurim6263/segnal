"""세그먼트 수명·누수 원인 데이터(기획서 5-1) 생성 시험."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim import health as H  # noqa: E402


@pytest.fixture(scope="module")
def out():
    return H.simulate()


def test_same_seed_same_data(out):
    again = H.simulate(with_minute=False)
    assert out["leaks"].equals(again["leaks"])
    assert out["segment_daily"].drop(columns=["day"]).equals(again["segment_daily"].drop(columns=["day"]))


def test_schema_and_shape(out):
    assert set(out["leaks"].columns) >= {"leak_id", "ts", "segment_serial", "position", "bundle_id", "part", "cause_code", "leak_lpm", "found_by"}
    assert set(out["maintenance"].columns) >= {"segment_serial", "part", "type", "resets_joint_age", "pressure_test", "finding_grade", "found_cause"}
    sd = out["segment_daily"]
    assert sd["day"].nunique() == 730 and sd.groupby("day")["segment_serial"].nunique().eq(13).all()
    assert sd["segment_serial"].nunique() <= 20 and sd["position"].between(1, 13).all()
    assert len(out["segments"]) == 20


def test_leak_frequency_and_causes(out):
    lk = out["leaks"]
    assert 25 <= len(lk) <= 60                                    # 월 1~2건 안팎(2년 약 35~40건)
    assert set(lk["cause_code"]) <= set(H.CAUSES) and lk["cause_code"].nunique() >= 5
    assert lk["leak_lpm"].between(1.5, 60).all()


def test_hidden_fields_exist_but_are_answer_only(out):
    assert "assembly_flag" in out["segments"].columns and "cause_code" in out["leaks"].columns
    assert "assembly_flag" not in out["segment_daily"].columns and "cause_code" not in out["segment_daily"].columns


def test_demo_case_is_fixed(out):
    sd = out["segment_daily"]
    last = sd[sd["day"] == sd["day"].max()]
    demo = last[last["segment_serial"] == "S-0012"].iloc[0]
    assert demo["position"] == 7 and demo["bundle_id"] == "B4"
    others = last[(last["bundle_id"] != "B4")]["low_flow_min"].max()
    assert demo["low_flow_min"] > 250 and demo["low_flow_min"] > 5 * others           # B4 필터 막힘 기간
    first = sd[(sd["segment_serial"] == "S-0012") & (sd["days_since_install"] == 0)].iloc[-1]       # 마지막(시연) 장착
    assert demo["bearing_t_avg_c"] - first["bearing_t_avg_c"] > 3.0                   # 베어링 온도 상승
    import pandas as pd
    assert not (out["leaks"]["segment_serial"].eq("S-0012") & (out["leaks"]["ts"] >= pd.Timestamp(first["date"]))).any()


def test_minute_series_matches_daily(out):
    v = H.validate(out)["minute_vs_daily_mismatch"]
    assert v["bundle_days"] == 70
    assert v["pressure_events"] == 0 and v["bearing"] == 0 and v["t_out"] == 0 and v["cast_hours"] == 0 and v["thermal_cycles"] == 0
    assert v["low_flow_min"] <= 3


def test_planned_stops_and_joint_age_reset(out):
    m = out["maintenance"]
    reset = m[m["resets_joint_age"] == 1]
    assert len(reset) > 0 and set(reset["part"]) <= {"seal", "rotary_joint"}
    assert out["_meta"]["next_planned_stop"] == "2026-11-12"
    sd = out["segment_daily"]
    assert (sd["joint_age_t"] >= 0).all() and sd["tons"].between(4000, 8400).all()
