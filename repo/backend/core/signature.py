"""B5. 서명 행렬: 후보 위치마다 가상 누수를 하나씩 넣었을 때 센서 잔차가 어떻게 달라지는지의 패턴.

후보 = (세그먼트, 롤, 입구/출구) 전체. 시뮬레이터로 기준 운전점에서 기준 크기(REF_LPM)의 누수를 넣고,
누수가 없을 때와의 차이를 기준선의 정상 표준편차로 나눈 z 단위로 저장한다 (묶음 × 채널 벡터).

주의: 서명을 만드는 모델이 데이터를 만든 시뮬레이터와 같은 물리라서 '이상적' 서명이다. 실제 설비에서는
모델 오차 때문에 더 흐려진다 (민감도 분석에서 서명 모델의 저항·누수 계수를 흔들어 확인한다).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sim.circuit import Event, make_operating, simulate_truth
from sim.config import PlantConfig
from sim.sensors import build_sensors
from sim.maintenance import joint_id

from .baseline import Baseline
from .classify import CHANNELS
from .normalize import group_signals

REF_LPM = 15.0


@dataclass
class SignatureSet:
    layout: str
    groups: list[int]                       # 계측 묶음 번호(1부터)
    joint_ids: list[str]
    segments: np.ndarray                    # 후보별 세그먼트
    rolls: np.ndarray
    sides: list[str]
    matrix: np.ndarray                      # (후보 수, 묶음 수 × 채널 수), 기준 누수량 REF_LPM일 때의 z 변화량

    def vector_dim(self) -> int:
        return self.matrix.shape[1]


def _signal_vector(df: pd.DataFrame, groups: list[int], res_sd_by_group: dict[int, dict[str, float]], idx: slice) -> np.ndarray:
    parts = []
    for g in groups:
        sig = group_signals(df, g)
        for ch in CHANNELS:
            parts.append(sig[ch].to_numpy()[idx].mean() / res_sd_by_group[g][ch])
    return np.array(parts)


def build_signatures(cfg: PlantConfig, bl: Baseline, layout: str = "S-A", ref_lpm: float = REF_LPM,
                     param_scale: dict | None = None) -> SignatureSet:
    """param_scale: 서명 모델의 물리 파라미터를 일부러 틀리게 하는 민감도 분석용 (예: {'flow_scale': 1.1})."""
    sim_cfg = cfg
    if param_scale:
        import copy
        sim_cfg = copy.deepcopy(cfg)
        sc = param_scale.get("flow_scale", 1.0)
        sim_cfg.sim["nominal_flow_lpm"] = [q * sc for q in cfg.sim["nominal_flow_lpm"]]
        sim_cfg.sim["pump"]["p0_bar"] = cfg.sim["pump"]["p0_bar"] * param_scale.get("pump_scale", 1.0)
    groups_idx = cfg.sensor_groups if layout == "S-A" else cfg.per_segment_groups()
    groups = list(range(1, len(groups_idx) + 1))
    res_sd = {g: bl.groups[g].res_sd for g in groups}

    T = 200
    rng = np.random.default_rng(0)
    op = make_operating(sim_cfg, T, rng, op_changes=False)
    base_truth = simulate_truth(sim_cfg, op, [], rng)
    base_df = build_sensors(sim_cfg, base_truth, groups_idx, layout, rng, noiseless=True)
    sl = slice(100, T)

    # 기준선(회귀)은 정상 운전에서의 보정값을 이미 포함하므로, 누수 유무의 차이만 쓴다
    base_vec = _signal_vector(base_df, groups, res_sd, sl)
    ids, segs, rolls, sides, rows = [], [], [], [], []
    for seg in range(1, cfg.n_segments + 1):
        for roll in range(1, cfg.rolls_per_segment + 1):
            for side in ["in", "out"][: cfg.joints_per_roll]:
                ev = Event(kind="leak", start=0, ramp=0, segment=seg, roll=roll, side=side, peak=ref_lpm)
                tr = simulate_truth(sim_cfg, op, [ev], rng)
                df = build_sensors(sim_cfg, tr, groups_idx, layout, rng, noiseless=True)
                rows.append(_signal_vector(df, groups, res_sd, sl) - base_vec)
                ids.append(joint_id(seg, roll, side))
                segs.append(seg)
                rolls.append(roll)
                sides.append(side)
    return SignatureSet(layout, groups, ids, np.array(segs), np.array(rolls), sides, np.array(rows))


def separability_report(sigs: SignatureSet, cos_thr: float = 0.98) -> dict:
    """분리도 게이트: 서로 다른 후보의 서명이 얼마나 비슷한가 (코사인 유사도)."""
    M = sigs.matrix
    U = M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-12)
    C = U @ U.T
    n = len(M)
    same_seg = sigs.segments[:, None] == sigs.segments[None, :]
    eye = np.eye(n, dtype=bool)
    diff_seg = ~same_seg
    same_seg_pairs = same_seg & ~eye
    return {
        "n_candidates": n,
        "frac_diff_segment_pairs_indistinguishable": float((C[diff_seg] > cos_thr).mean()),
        "frac_same_segment_pairs_indistinguishable": float((C[same_seg_pairs] > cos_thr).mean()),
        "median_cos_diff_segment": float(np.median(C[diff_seg])),
        # 각 후보에서 '다른 세그먼트 중 가장 비슷한 후보'와의 유사도 → 세그먼트 단위 분리 가능한 후보의 비율
        "frac_candidates_segment_distinguishable": float(
            np.mean([C[i][diff_seg[i]].max() < cos_thr for i in range(n)])
        ),
        "mean_nearest_other_segment_cos": float(np.mean([C[i][diff_seg[i]].max() for i in range(n)])),
    }

