"""합성 정비 이력 생성 (조인트 수명). 실제 교체 이력이 없으므로 모든 파라미터는 가설이다.

- 시뮬레이터가 쓰는 '진짜' 수명 분포는 weibull 또는 lognormal(분포 불일치 시나리오).
- 모델(core/lifetime.py)은 항상 Weibull을 가정해 맞춘다. 두 분포가 다르면 사전확률 효과가
  설계상 좋게 나오는 순환 논리를 깨고 정직한 비교를 할 수 있다.
- 날짜 0 = 현재. 과거 이력은 음수 일(day)로 기록한다.
"""
from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
from scipy import stats

from .config import PlantConfig


def joint_id(seg: int, roll: int, side: str) -> str:
    return f"S{seg:02d}-R{roll:02d}-{side}"


def _scale_factor(cfg: PlantConfig, seg: int) -> float:
    g = float(cfg.sim["maintenance"]["seg_scale_gradient"])
    denom = max(cfg.n_segments - 1, 1)
    return 1.0 + g * (seg - 1) / denom


def true_life_dist(cfg: PlantConfig, seg: int, dist: str | None = None):
    """세그먼트별 '진짜' 수명 분포(scipy frozen). dist를 주면 설정값을 덮어쓴다."""
    m = cfg.sim["maintenance"]
    dist = dist or m["true_dist"]
    sc = _scale_factor(cfg, seg)
    if dist == "weibull":
        return stats.weibull_min(c=float(m["weibull_shape"]), scale=float(m["weibull_scale_days"]) * sc)
    if dist == "lognormal":
        k = float(m["weibull_shape"])
        eta = float(m["weibull_scale_days"]) * sc
        from math import gamma, log
        mean_w = eta * gamma(1 + 1 / k)
        sigma = float(m["lognormal_sigma"])
        mu = log(mean_w) - sigma**2 / 2
        return stats.lognorm(s=sigma, scale=np.exp(mu))
    raise ValueError(dist)


def conditional_failure_prob(dist, age: np.ndarray | float, window: float) -> np.ndarray | float:
    """이미 age일 살아남았을 때 다음 window일 안에 고장날 확률 = 1 − S(age+w)/S(age)."""
    s0 = dist.sf(age)
    s1 = dist.sf(np.asarray(age) + window)
    return np.where(s0 > 1e-12, 1.0 - s1 / np.maximum(s0, 1e-12), 1.0)


def generate_maintenance(cfg: PlantConfig, seed: int | None = None, dist: str | None = None):
    """(joints_df, log_df) 반환.

    joints_df 열: joint_id, segment, roll, side, install_day, replace_count, last_replace_day,
                  age_days, access_risk, inspect_minutes
    log_df 열: day, joint_id, action(replace/inspect/leak_repair), note
    """
    m = cfg.sim["maintenance"]
    base_seed = int(cfg.sim["seed"]) if seed is None else int(seed)
    rng = np.random.default_rng([base_seed, 424242])
    horizon = float(m["horizon_days"])
    N, R = cfg.n_segments, cfg.rolls_per_segment
    sides = ["in", "out"][: cfg.joints_per_roll]

    rows, logs = [], []
    for seg in range(1, N + 1):
        d = true_life_dist(cfg, seg, dist)
        # 접근 위험: 몰드에 가까운(번호 작은) 세그먼트일수록 높다 [가설]
        seg_risk = 0.25 + 0.55 * (1 - (seg - 1) / max(N - 1, 1))
        for roll in range(1, R + 1):
            for side in sides:
                jid = joint_id(seg, roll, side)
                # 과거 이력을 horizon 이전에 설치된 것으로 시작해서 현재까지 교체 반복
                t = -horizon - float(rng.uniform(0, 400))      # 최초 설치 시점
                replace_count = 0
                last_replace = np.nan
                first_install = t
                while True:
                    life = float(d.rvs(random_state=rng))
                    t_fail = t + life
                    if t_fail >= 0:
                        break                                   # 아직 고장 안 남 (검열)
                    action = "leak_repair" if rng.random() < 0.6 else "replace"
                    logs.append((t_fail, jid, action, "고장 후 교체" if action == "leak_repair" else "예방 교체"))
                    replace_count += 1
                    last_replace = t_fail
                    t = t_fail
                age = -t
                # 점검 기록 (무작위)
                for _ in range(rng.poisson(float(m["inspect_log_per_joint"]))):
                    day = float(rng.uniform(t, 0))
                    logs.append((day, jid, "inspect", "정기 점검"))
                rows.append({
                    "joint_id": jid, "segment": seg, "roll": roll, "side": side,
                    "install_day": first_install, "replace_count": replace_count,
                    "last_replace_day": last_replace if replace_count else np.nan,
                    "age_days": age,
                    "access_risk": float(np.clip(seg_risk + rng.normal(0, 0.12), 0.05, 0.98)),
                    "inspect_minutes": float(np.clip(rng.normal(25, 8) + (6 if side == "in" else 0), 8, 60)),
                })
    joints = pd.DataFrame(rows)
    log = pd.DataFrame(logs, columns=["day", "joint_id", "action", "note"]).sort_values("day").reset_index(drop=True)
    return joints, log


def sample_leak_joints(cfg: PlantConfig, joints: pd.DataFrame, rng: np.random.Generator, n: int = 1,
                       dist: str | None = None) -> pd.DataFrame:
    """진짜 수명 분포에 따라 '곧 샐 가능성'이 큰 조인트를 확률적으로 뽑는다 (평가용 정답 위치)."""
    window = float(cfg.sim["maintenance"]["hazard_window_days"])
    haz = np.empty(len(joints))
    for seg, idx in joints.groupby("segment").groups.items():
        d = true_life_dist(cfg, int(seg), dist)
        haz[joints.index.get_indexer(idx)] = conditional_failure_prob(d, joints.loc[idx, "age_days"].to_numpy(), window)
    p = haz / haz.sum()
    chosen = rng.choice(len(joints), size=n, replace=False, p=p)
    return joints.iloc[chosen]


def write_to_db(conn: sqlite3.Connection, joints: pd.DataFrame, log: pd.DataFrame) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM joints")
    cur.execute("DELETE FROM maintenance_log")
    cur.executemany(
        "INSERT INTO joints (joint_id, segment, roll, side, install_day, replace_count, last_replace_day, access_risk, inspect_minutes)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        [(r.joint_id, int(r.segment), int(r.roll), r.side, float(r.install_day), int(r.replace_count),
          None if np.isnan(r.last_replace_day) else float(r.last_replace_day),
          float(r.access_risk), float(r.inspect_minutes)) for r in joints.itertuples()],
    )
    cur.executemany(
        "INSERT INTO maintenance_log (day, joint_id, action, note) VALUES (?,?,?,?)",
        [(float(r.day), r.joint_id, r.action, r.note) for r in log.itertuples()],
    )
    conn.commit()
