import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.baseline import Baseline  # noqa: E402
from core.detect import (  # noqa: E402
    count_alarm_episodes, cusum, ewma, ewma_limit, first_alarm, recenter,
)
from core.impact import impact_range  # noqa: E402
from core.lifetime import collect_lives, fit_weibull, prior_from_fit  # noqa: E402
from core.ml_detectors import IForestDetector  # noqa: E402
from core.normalize import group_signals, groups_in, mass_flow  # noqa: E402
from sim.config import load_config  # noqa: E402
from sim.maintenance import generate_maintenance  # noqa: E402
from sim.scenarios import DATA_DIR, load_scenario  # noqa: E402

cfg = load_config()
have_data = (DATA_DIR / "train_normal__S-A.csv.gz").exists()
needs_data = pytest.mark.skipif(not have_data, reason="python -m sim.generate 로 데이터를 먼저 만드세요")


# ---- B1 정규화 ---------------------------------------------------------
@needs_data
def test_mass_normalization_removes_density_bias():
    df, _ = load_scenario("train_normal", "S-A")
    means_vol, means_mass = [], []
    for g in groups_in(df):
        s = group_signals(df, g)
        # 질량유량으로 바꾸면 밀도 효과(약 1.2~2.6%)만큼 불균형이 올라간다
        diff = s["imb_mass"].mean() - s["imb_vol"].mean()
        assert 0.012 < diff < 0.026
        means_vol.append(s["imb_vol"].mean())
        means_mass.append(s["imb_mass"].mean())
    # 묶음 평균으로 보면 부피유량은 -1% 아래로 치우쳐 있고 질량유량은 0 근처(묶음별 차이는 계측 오프셋)
    assert np.mean(means_vol) < -0.010
    assert abs(np.mean(means_mass)) < 0.006


def test_mass_flow_units():
    assert abs(mass_flow(1000.0, 20.0) - 998.2) < 0.2   # kg/min


# ---- B2 기준선 ---------------------------------------------------------
@needs_data
def test_baseline_residuals_standardized_and_leak_visible():
    tr, _ = load_scenario("train_normal", "S-A")
    bl = Baseline().fit(tr)
    g = 3
    z = bl.residuals(tr, g)["z_imb_mass"]
    assert abs(z.mean()) < 0.05 and abs(z.std() - 1) < 0.05
    lk, lab = load_scenario("leak_abrupt_s2", "S-A")
    g2 = cfg.group_of_segment(2) + 1
    z2 = bl.residuals(lk, g2)["z_imb_mass"].to_numpy()
    t0 = lab["events"][0]["start_ts"]
    assert z2[t0 + 60 : t0 + 600].mean() > 3.0       # 25 L/min ≈ 4σ 이상의 이동
    assert abs(z2[200:t0 - 100].mean()) < 1.0


# ---- B3 변화 탐지 ------------------------------------------------------
def test_ewma_and_cusum_detect_small_shift():
    rng = np.random.default_rng(0)
    z = rng.normal(0, 1, 3000)
    z[1500:] += 0.8
    e = ewma(z, 0.1)
    c = cusum(z, 0.5)
    assert first_alarm(e, ewma_limit(0.1, 3.5), 0) is not None
    assert first_alarm(e, ewma_limit(0.1, 3.5), 0) > 1400   # 이동 전에는 경보 없음(보통)
    assert first_alarm(c, 8.0, 1500) is not None


def test_alarm_episode_counting():
    s = np.zeros(1000)
    s[100:110] = 5
    s[600:620] = 5
    assert count_alarm_episodes(s, 1.0, gap=30) == 2
    s[115:118] = 5          # 30분 안의 재발은 같은 사건
    assert count_alarm_episodes(s, 1.0, gap=30) == 2
    assert first_alarm(s, 1.0, 0, min_run=5) == 104


def test_recenter_removes_slow_drift_but_keeps_leak():
    rng = np.random.default_rng(1)
    n = 6000
    z = rng.normal(0, 1, n) + np.linspace(0, 1.0, n)       # 느린 표류
    zc = recenter(z)
    assert abs(zc[4000:].mean()) < abs(z[4000:].mean())
    z2 = rng.normal(0, 1, n)
    z2[3000:] += 2.0                                       # 갑작스러운 누수
    zc2 = recenter(z2)
    assert zc2[3100:3400].mean() > 1.5                     # 기준선이 누수를 바로 흡수하지 않는다


# ---- B17 Isolation Forest ----------------------------------------------
@needs_data
def test_iforest_score_rises_after_leak():
    tr, _ = load_scenario("train_normal", "S-A")
    bl = Baseline().fit(tr)
    g = cfg.group_of_segment(2) + 1
    det = IForestDetector("residual").fit(tr, bl, [g])
    lk, lab = load_scenario("leak_abrupt_s2", "S-A")
    sc = det.score(lk, bl, g)
    t0 = lab["events"][0]["start_ts"]
    assert sc[t0 + 60 : t0 + 600].mean() > sc[200 : t0 - 60].mean() + 0.02


# ---- B16 수명 모델 -----------------------------------------------------
def test_weibull_fit_recovers_parameters():
    joints, log = generate_maintenance(cfg)
    failures, censored = collect_lives(joints, log)
    fit = fit_weibull(failures, censored)
    assert fit.n_failures > 300 and fit.n_censored == len(joints)
    assert 1.7 < fit.shape < 2.8          # 진짜 2.2
    assert 500 < fit.scale < 1000         # 650 × (1.0~1.4)
    prior = prior_from_fit(fit, joints, 30.0)
    assert abs(prior.sum() - 1) < 1e-9
    # 나이가 많은 조인트의 사전확률이 더 크다
    assert prior[joints.age_days.idxmax()] > prior[joints.age_days.idxmin()]


# ---- O2 영향 구간 ------------------------------------------------------
def test_impact_range_geometry():
    speed = np.full(1000, 1.2)
    r = impact_range(speed, segment=5, t_start=100, t_now=160, slab_len_m=10.0)
    assert abs(r.exposed_length_m - 72.0) < 1e-9           # 60분 × 1.2 m/min
    assert r.start_m == pytest.approx(4 * 1.75)            # 세그먼트 5 입구
    assert r.end_m == pytest.approx(5 * 1.75 + 72.0)       # 세그먼트 5 출구 + 노출 길이
    assert r.slab_first <= r.slab_last
    assert "표면 검사 대상 후보" in r.label
