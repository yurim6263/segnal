import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.baseline import Baseline  # noqa: E402
from core.classify import DiagnosisModel  # noqa: E402
from core.locate import apply_inspection, priority_order, rank_candidates  # noqa: E402
from core.normalize import groups_in  # noqa: E402
from core.signature import build_signatures, separability_report  # noqa: E402
from sim.config import load_config  # noqa: E402
from sim.scenarios import DATA_DIR, load_scenario  # noqa: E402

cfg = load_config()
have_data = (DATA_DIR / "train_normal__S-A.csv.gz").exists()
needs_data = pytest.mark.skipif(not have_data, reason="python -m sim.generate 로 데이터를 먼저 만드세요")


@pytest.fixture(scope="module")
def sa():
    tr, _ = load_scenario("train_normal", "S-A")
    bl = Baseline().fit(tr)
    return bl, tr, build_signatures(cfg, bl, "S-A")


@pytest.fixture(scope="module")
def sb():
    tr, _ = load_scenario("train_normal", "S-B")
    bl = Baseline().fit(tr)
    return bl, tr, build_signatures(cfg, bl, "S-B")


@needs_data
def test_signature_count_and_ids_follow_config(sa):
    _, _, sigs = sa
    assert len(sigs.joint_ids) == cfg.n_segments * cfg.rolls_per_segment * cfg.joints_per_roll
    assert sigs.matrix.shape == (len(sigs.joint_ids), len(cfg.sensor_groups) * 5)


@needs_data
def test_separability_gate_matches_expectation(sa, sb):
    ra, rb = separability_report(sa[2]), separability_report(sb[2])
    # 롤·입구/출구는 어느 계측에서도 구분되지 않는다 (게이트 결과: 세그먼트/묶음 단위까지만)
    assert ra["frac_same_segment_pairs_indistinguishable"] > 0.95
    assert rb["frac_same_segment_pairs_indistinguishable"] > 0.95
    # 세그먼트별 계측(S-B)은 세그먼트를 구분하고, 묶음 계측(S-A)은 구분이 훨씬 약하다
    assert rb["frac_candidates_segment_distinguishable"] > 0.95
    assert ra["frac_candidates_segment_distinguishable"] < 0.5


@needs_data
def test_rank_candidates_finds_right_segment_from_own_signature(sb):
    _, _, sigs = sb
    i = 100                                   # 임의의 후보
    r = sigs.matrix[i] * 0.8                  # 기준 누수량의 0.8배 누수가 났을 때의 이상적 관측
    post = rank_candidates(sigs, r)
    assert abs(post.prob.sum() - 1) < 1e-9
    assert post.segments[post.top(1)[0]] == sigs.segments[i]
    assert 10 < post.amplitude_lpm[post.top(1)[0]] < 14      # 15 × 0.8 = 12 L/min


@needs_data
def test_prior_breaks_ties_within_segment(sb):
    _, _, sigs = sb
    i = 100
    prior = np.ones(len(sigs.joint_ids))
    seg_members = np.flatnonzero(sigs.segments == sigs.segments[i])
    target = seg_members[3]
    prior[target] = 50.0                       # 사전확률이 큰 조인트
    post = rank_candidates(sigs, sigs.matrix[i] * 0.8, prior)
    assert post.top(1)[0] == target


def test_apply_inspection_updates_probabilities():
    p = np.array([0.5, 0.3, 0.2])
    q = apply_inspection(p, 0, "no_issue", 0.9)
    assert abs(q.sum() - 1) < 1e-12
    assert q[0] < p[0] and q[1] > p[1]
    c = apply_inspection(p, 2, "leak_confirmed", 0.9)
    assert c.argmax() == 2


def test_priority_prefers_cheap_and_safe_candidates():
    p = np.array([0.4, 0.4, 0.2])
    minutes = np.array([40.0, 15.0, 15.0])
    risk = np.array([0.9, 0.2, 0.1])
    score, order = priority_order(p, minutes, risk, lam=20.0)
    assert order[0] == 1 and score[1] > score[0]


@needs_data
def test_classifier_on_generated_events(sa):
    bl, tr, _ = sa
    gs = groups_in(tr)
    model = DiagnosisModel(bl).fit(tr, gs)
    for name, expect in [("clog_s7", "clog"), ("pump_degrade", "pump"), ("leak_abrupt_s2", "leak"), ("sensor_fault", "sensor")]:
        df, lab = load_scenario(name, "S-A")
        d = model.diagnose(df, gs, start=int(lab["events"][0]["start_ts"]))
        assert d.cause == expect, (name, d)
