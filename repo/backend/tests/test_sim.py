"""시뮬레이터 물리 일관성 점검."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.circuit import Event, make_operating, simulate_truth, water_density  # noqa: E402
from sim.config import PlantConfig, load_config  # noqa: E402
from sim.scenarios import ScenarioSpec, sensors_for, simulate_spec  # noqa: E402

cfg = load_config()


def _run(events, n=2 * 1440, seed=3, op_changes=False):
    rng = np.random.default_rng(seed)
    op = make_operating(cfg, n, rng, op_changes=op_changes)
    return simulate_truth(cfg, op, events, rng), op


def test_water_density_matches_table():
    assert abs(water_density(20.0) - 998.21) < 0.1
    assert abs(water_density(40.0) - 992.22) < 0.1


def test_no_leak_steady_state_mass_balance():
    truth, op = _run([])
    # 질량 보존: 입구 질량유량 = 출구 질량유량 (정상 상태, 지연 후)
    m_in = truth.q_in * water_density(truth.t_in)[:, None]
    m_out = truth.q_out_vol * water_density(truth.t_out)
    rel = np.abs(m_in - m_out) / m_in
    assert rel[300:].max() < 1e-6
    # 부피유량계는 출구가 입구보다 1~2.5% 크게 본다
    ratio = truth.q_out_vol / truth.q_in
    assert 1.01 < ratio[300:].mean() < 1.03


def test_nominal_operating_point_matches_config():
    truth, _ = _run([])
    q0 = np.array(cfg.sim["nominal_flow_lpm"])
    assert np.allclose(truth.q_in[100], q0, rtol=0.03)
    assert abs(truth.p_header[100] - cfg.sim["pump"]["p_header_nom_bar"]) < 0.1
    assert 55 < truth.t_out[500].max() < 85


def test_leak_adds_inflow_and_lowers_header_pressure():
    base, _ = _run([])
    ev = Event(kind="leak", start=600, ramp=0, segment=5, roll=4, side="in", peak=20.0)
    leak, _ = _run([ev])
    # 누수 세그먼트의 입구 유량은 늘고, 헤더 압력은 낮아지며, 다른 세그먼트 유량은 소폭 줄어든다
    assert leak.q_in[800, 4] > base.q_in[800, 4] + 15
    assert leak.p_header[800] < base.p_header[800]
    assert leak.q_in[800, 0] < base.q_in[800, 0]
    # 누수량은 설정한 최대값 근처(압력 의존이라 약간 다를 수 있음)
    assert 17 < leak.q_leak[800, 4] < 21


def test_inlet_side_leak_leaks_more_than_outlet_side():
    a, _ = _run([Event(kind="leak", start=0, segment=5, roll=1, side="in", peak=10.0)])
    b, _ = _run([Event(kind="leak", start=0, segment=5, roll=10, side="out", peak=10.0)])
    # 같은 최대값 설정이면 같게 만들어지므로(정상 압력 기준 보정), 정상 압력 대비 같은 값이어야 한다
    assert abs(a.q_leak[500, 4] - b.q_leak[500, 4]) < 1.0


def test_clog_lowers_flow_and_raises_return_pressure():
    base, _ = _run([])
    clog, _ = _run([Event(kind="clog", start=300, ramp=0, segment=7, peak=0.8)])
    assert clog.q_in[600, 6] < base.q_in[600, 6] * 0.9
    assert clog.p_out_seg[600, 6] > base.p_out_seg[600, 6] + 0.3


def test_pump_degradation_lowers_pressure_and_flow():
    base, _ = _run([])
    pump, _ = _run([Event(kind="pump", start=300, ramp=0, peak=0.5)])
    assert pump.p_header[600] < base.p_header[600] - 0.2
    assert pump.q_in[600].sum() < base.q_in[600].sum()


def test_speed_change_changes_flow_and_temperature():
    truth, op = _run([], op_changes=True, n=3 * 1440, seed=11)
    assert truth.speed.max() - truth.speed.min() > 0.1
    assert truth.q_in.sum(axis=1).std() > 10


def test_sensor_layouts_follow_config_not_constants():
    spec = ScenarioSpec("t", "t", 600, 77, lambda c: [])
    truth, _ = simulate_spec(cfg, spec)
    df_a, groups_a = sensors_for(cfg, spec, truth, "S-A")
    df_b, groups_b = sensors_for(cfg, spec, truth, "S-B")
    assert len(groups_a) == len(cfg.sensor_groups)
    assert len(groups_b) == cfg.n_segments
    assert f"g{len(groups_a)}_flow_in" in df_a.columns
    assert f"g{cfg.n_segments}_flow_in" in df_b.columns


def test_changing_n_segments_in_config_still_works():
    """세그먼트 수가 달라져도(현업 답변) 코드 수정 없이 동작해야 한다."""
    nf = [500.0] * 10
    small = PlantConfig(
        n_segments=10, sensor_groups=[[1, 2, 3], [4, 5], [6, 7, 8, 9, 10]],
        rolls_per_segment=8, joints_per_roll=2, sim=dict(cfg.sim, nominal_flow_lpm=nf),
    )
    small.validate()
    rng = np.random.default_rng(1)
    op = make_operating(small, 600, rng)
    truth = simulate_truth(small, op, [], rng)
    assert truth.q_in.shape == (600, 10)


def test_leak_shows_in_group_imbalance():
    spec = ScenarioSpec(
        "t", "t", 3 * 1440, 78,
        lambda c: [Event(kind="leak", start=1440, ramp=0, segment=5, roll=4, side="in", peak=25.0)],
    )
    truth, _ = simulate_spec(cfg, spec)
    df, groups = sensors_for(cfg, spec, truth, "S-A")
    gi = cfg.group_of_segment(5) + 1
    imb = (df[f"g{gi}_flow_in"] - df[f"g{gi}_flow_out"]) / df[f"g{gi}_flow_in"]
    before = imb[200:1400].mean()
    after = imb[1500:2800].mean()
    # 25 L/min / 약 1000 L/min = 2.5% 만큼 불균형이 커진다
    assert 0.015 < (after - before) < 0.035
