"""진실 상태(Truth) → 계측 묶음별 센서값 (잡음·고정 오프셋·표류·고장 포함).

계측 묶음은 config/plant.yaml의 sensor_groups(S-A) 또는 세그먼트마다 하나(S-B)로 만든다.
유량계의 고정 오프셋은 같은 센서라면 시나리오가 달라도 같다 (레이아웃·묶음 번호로 시드를 정함).
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from .circuit import Event, Truth
from .config import PlantConfig

SENSOR_NAMES = ["flow_in", "flow_out", "p_in", "p_out", "t_in", "t_out"]


def _fixed_rng(cfg: PlantConfig, layout: str, group: int, name: str) -> np.random.Generator:
    key = zlib.crc32(f"{layout}|{group}|{name}".encode("utf-8"))
    return np.random.default_rng([int(cfg.sim["seed"]), key])


def build_sensors(
    cfg: PlantConfig,
    truth: Truth,
    groups: list[list[int]],
    layout: str,
    rng: np.random.Generator,
    noiseless: bool = False,
) -> pd.DataFrame:
    sim = cfg.sim
    sp = sim["sensor"]
    T = len(truth.speed)
    spd = 86400 / float(sim["dt_s"])      # 하루 샘플 수
    cols: dict[str, np.ndarray] = {}

    for gi, segs in enumerate(groups):
        idx = [s - 1 for s in segs]
        flow_in = truth.q_in[:, idx].sum(axis=1)
        flow_out = truth.q_out_vol[:, idx].sum(axis=1)
        w = truth.q_out_equiv[:, idx]
        t_out = (truth.t_out[:, idx] * w).sum(axis=1) / w.sum(axis=1)
        p_out = (truth.p_out_seg[:, idx] * w).sum(axis=1) / w.sum(axis=1)
        # 공급 헤더에서 이 묶음까지의 배관 압력 손실 (묶음 위치에 따라 고정)
        header_loss = 0.015 * (min(segs) - 1) / max(cfg.n_segments - 1, 1) * 10
        p_in = truth.p_header - header_loss * (flow_in / max(flow_in.mean(), 1e-9))

        true_vals = {
            "flow_in": flow_in, "flow_out": flow_out,
            "p_in": p_in, "p_out": p_out,
            "t_in": truth.t_in.copy(), "t_out": t_out,
        }
        for name, val in true_vals.items():
            if noiseless:                       # 서명(누수 패턴) 계산용: 잡음·오프셋·표류 없음
                cols[f"g{gi + 1}_{name}"] = np.asarray(val, dtype=float)
                continue
            off_rng = _fixed_rng(cfg, layout, gi, name)
            if name.startswith("flow"):
                offset = off_rng.normal(0.0, sp["flow_offset_rel"])
                drift = np.cumsum(rng.normal(0.0, sp["flow_drift_rel_per_sqrt_day"] / np.sqrt(spd), T))
                noise = rng.normal(0.0, sp["flow_noise_rel"], T)
                meas = val * (1.0 + offset + drift + noise)
            elif name.startswith("p"):
                offset = off_rng.normal(0.0, 0.03)
                meas = val + offset + rng.normal(0.0, sp["pressure_noise_bar"], T)
            else:
                offset = off_rng.normal(0.0, 0.15)
                meas = val + offset + rng.normal(0.0, sp["temp_noise_c"], T)
            cols[f"g{gi + 1}_{name}"] = meas

    # 센서 고장 이벤트 적용
    for e in truth.events:
        if e.kind != "sensor" or noiseless:
            continue
        assert e.sensor_group is not None and e.sensor_name is not None
        key = f"g{e.sensor_group + 1}_{e.sensor_name}"
        if key not in cols:
            continue
        prof = e.profile(T)
        x = cols[key]
        if e.sensor_mode == "stuck":
            held = x[max(e.start - 1, 0)]
            x = np.where(prof > 0, held, x)
        elif e.sensor_mode == "offset":
            if e.sensor_name.startswith("flow"):
                x = x * (1.0 + e.sensor_value * prof)
            else:
                x = x + e.sensor_value * prof
        cols[key] = x

    df = pd.DataFrame(cols)
    df.insert(0, "steel_grade", truth.grade)
    df.insert(0, "cast_speed", np.round(truth.speed, 4))
    df.insert(0, "ts", np.arange(T))
    return df
