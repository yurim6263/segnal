import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db import init_db  # noqa: E402
from sim.config import load_config  # noqa: E402
from sim.maintenance import (  # noqa: E402
    conditional_failure_prob, generate_maintenance, sample_leak_joints, true_life_dist, write_to_db,
)

cfg = load_config()


def test_joint_count_follows_config():
    joints, log = generate_maintenance(cfg)
    assert len(joints) == cfg.n_segments * cfg.rolls_per_segment * cfg.joints_per_roll
    assert joints.joint_id.is_unique
    assert (joints.age_days > 0).all()
    assert joints.access_risk.between(0, 1).all()
    assert set(log.action) >= {"replace", "leak_repair", "inspect"}


def test_history_is_reproducible():
    a, _ = generate_maintenance(cfg)
    b, _ = generate_maintenance(cfg)
    assert np.allclose(a.age_days, b.age_days)


def test_conditional_failure_prob_increases_with_age_for_weibull():
    d = true_life_dist(cfg, 1, "weibull")
    p = conditional_failure_prob(d, np.array([50.0, 300.0, 900.0]), 30.0)
    assert p[0] < p[1] < p[2]


def test_lognormal_differs_from_weibull():
    w = true_life_dist(cfg, 1, "weibull")
    l = true_life_dist(cfg, 1, "lognormal")
    # 평균 수명은 비슷해야 하고 위험률 모양은 달라야 한다
    assert abs(w.mean() - l.mean()) / w.mean() < 0.05
    ages = np.array([100.0, 600.0, 1500.0])
    assert not np.allclose(conditional_failure_prob(w, ages, 30), conditional_failure_prob(l, ages, 30), rtol=0.2)


def test_sampled_leak_joints_prefer_older_ones():
    joints, _ = generate_maintenance(cfg)
    rng = np.random.default_rng(0)
    picked = [sample_leak_joints(cfg, joints, rng, 1).iloc[0].age_days for _ in range(300)]
    assert np.mean(picked) > joints.age_days.mean()


def test_write_to_db(tmp_path):
    joints, log = generate_maintenance(cfg)
    conn = init_db(tmp_path / "t.db")
    write_to_db(conn, joints, log)
    n = conn.execute("SELECT COUNT(*) FROM joints").fetchone()[0]
    assert n == len(joints)
