"""원인 구분(신호 방향 비교)·경보선 도달 예상 시각·추정 누수량 시험."""
import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.forecast import estimate_leak, forecast_line, forecast_text  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


def test_forecast_linear_ramp_hits_expected_time():
    t = np.arange(600)
    res = 0.00002 * t                                   # 분당 0.002%p 증가
    line, now = 0.02, float(res[-1])
    f = forecast_line(res, now, line, ts=599, t_start=0)
    assert f["available"] and not f["crossed"]
    expect_h = (line - now) / 0.00002 / 60
    assert abs(f["hours"] - expect_h) < 0.2
    assert "시간" in forecast_text(f)


def test_forecast_flat_series_gives_no_time():
    rng = np.random.default_rng(1)
    res = 0.001 + rng.normal(0, 0.0003, 600)
    f = forecast_line(res, 0.001, 0.02, ts=599, t_start=0)
    assert not f["available"] and "뚜렷하지" in f["reason"]


def test_forecast_already_crossed_and_decelerating():
    res = np.linspace(0, 0.03, 600)
    assert forecast_line(res, 0.03, 0.02, 599, 0)["crossed"]
    ramp_then_flat = np.concatenate([np.linspace(0, 0.01, 300), np.full(300, 0.01)])
    f = forecast_line(ramp_then_flat + np.random.default_rng(2).normal(0, 1e-5, 600), 0.01, 0.02, 599, 0)
    assert not f["available"]


def test_estimate_leak_is_nonnegative_with_range():
    e = estimate_leak(np.full(100, 0.01), np.full(100, 1000.0), 99, noise=0.0004)
    assert abs(e["lpm"] - 10.0) < 1e-6 and e["low_lpm"] < e["lpm"] < e["high_lpm"]
    assert estimate_leak(np.full(100, -0.01), np.full(100, 1000.0), 99, noise=0.0004)["lpm"] == 0.0


def test_leak_scenario_has_pattern_forecast_and_estimate():
    s = client.get("/api/state?scenario_id=leak_ramp_s5&ts=2400").json()
    assert s["alert"]["cause"] == "leak"
    assert s["pattern"]["ranking"][0]["cls"] == "leak" and not s["pattern"]["ambiguous"]
    assert len(s["pattern"]["signals"]) == 9
    assert s["leak_estimate"]["lpm"] > 0 and s["leak_estimate"]["conditional"] is False
    assert s["forecast"] is not None and s["forecast"]["text"]


def test_flow_meter_offset_is_called_sensor_not_leak():
    s = client.get("/api/state?scenario_id=flow_offset_s5&ts=2400").json()
    assert s["alert"]["cause"] == "sensor"
    assert "입구 유량계" in s["pattern"]["verdict"]
    assert s["segment_candidates"] == [] and s["leak_estimate"] is None


def test_indistinct_case_is_kept_as_ambiguous_without_candidates():
    s = client.get("/api/state?scenario_id=leak_small_s1&ts=3400").json()
    assert s["alert"]["cause"] == "ambiguous" and s["pattern"]["ambiguous"]
    assert s["segment_candidates"] == [] and s["forecast"] is None
    assert s["leak_estimate"]["conditional"] is True
    assert "구분되지 않습니다" in s["summary"]["headline"]


def test_normal_scenario_has_no_pattern():
    s = client.get("/api/state?scenario_id=normal_opchange&ts=3000").json()
    assert s["alert"]["level"] == "normal" and s["pattern"] is None and s["forecast"] is None
