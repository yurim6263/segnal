"""시나리오 정의와 생성. 같은 진실 상태에서 S-A(묶음 계측)와 S-B(세그먼트별 계측)를 모두 만든다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from .circuit import Event, Operating, Truth, make_operating, simulate_truth
from .config import PlantConfig, load_config
from .sensors import build_sensors

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "generated"
DAY = 1440  # dt_s=60 기준 하루 샘플 수


@dataclass
class ScenarioSpec:
    name: str
    description: str
    n: int
    seed_offset: int
    events: Callable[[PlantConfig], list[Event]]
    op_changes: bool = True


def _leak(seg: int, roll: int, side: str, start: int, peak: float, ramp: int) -> Event:
    return Event(kind="leak", start=start, ramp=ramp, segment=seg, roll=roll, side=side, peak=peak)


def default_specs() -> list[ScenarioSpec]:
    return [
        ScenarioSpec("train_normal", "정상 14일 (기준선 학습용, 주조 속도·강종 변경 포함)", 14 * DAY, 1, lambda c: []),
        ScenarioSpec("normal_opchange", "정상 3일 + 주조 속도·강종 변경 (오경보 시험)", 3 * DAY, 2, lambda c: []),
        ScenarioSpec(
            "leak_ramp_s5", "서서히 커지는 미세 누수: 세그먼트 5, 롤 4, 입구 (6시간에 걸쳐 14 L/min)", 3 * DAY, 3,
            lambda c: [_leak(5, 4, "in", DAY + 6 * 60, 14.0, 6 * 60)],
        ),
        ScenarioSpec(
            "leak_small_s9", "아주 작은 누수: 세그먼트 9, 롤 7, 출구 (8시간에 걸쳐 9 L/min)", 3 * DAY, 4,
            lambda c: [_leak(9, 7, "out", DAY + 4 * 60, 9.0, 8 * 60)],
        ),
        ScenarioSpec(
            "leak_abrupt_s2", "급한 누수: 세그먼트 2, 롤 2, 입구 (25 L/min)", 3 * DAY, 5,
            lambda c: [_leak(2, 2, "in", DAY + 10 * 60, 25.0, 0)],
        ),
        ScenarioSpec(
            "clog_s7", "막힘: 세그먼트 7 출구쪽 저항 증가", 3 * DAY, 6,
            lambda c: [Event(kind="clog", start=DAY + 5 * 60, ramp=3 * 60, segment=7, peak=0.8)],
        ),
        ScenarioSpec(
            "pump_degrade", "펌프 성능 저하 (공급 압력·유량 감소)", 3 * DAY, 7,
            lambda c: [Event(kind="pump", start=DAY + 5 * 60, ramp=4 * 60, peak=0.25)],
        ),
        ScenarioSpec(
            "sensor_fault", "센서 고장: 묶음 3 회수 유량계 고착", 3 * DAY, 8,
            lambda c: [Event(kind="sensor", start=DAY + 8 * 60, sensor_group=2, sensor_name="flow_out", sensor_mode="stuck")],
        ),
    ]


def random_leak_spec(name: str, seed_offset: int, rng: np.random.Generator, cfg: PlantConfig) -> ScenarioSpec:
    """평가용 무작위 누수 시나리오 (위치·크기·진행 속도가 무작위)."""
    seg = int(rng.integers(1, cfg.n_segments + 1))
    roll = int(rng.integers(1, cfg.rolls_per_segment + 1))
    side = str(rng.choice(["in", "out"]))
    peak = float(rng.uniform(6.0, 30.0))
    ramp = int(rng.choice([0, 2 * 60, 6 * 60, 12 * 60]))
    start = int(DAY + rng.integers(2 * 60, 14 * 60))
    return ScenarioSpec(
        name, f"무작위 누수: 세그먼트 {seg}, 롤 {roll}, {side}, 최대 {peak:.1f} L/min, 램프 {ramp}분", 3 * DAY, seed_offset,
        lambda c, s=seg, r=roll, sd=side, st=start, pk=peak, rp=ramp: [_leak(s, r, sd, st, pk, rp)],
    )


def random_event_spec(kind: str, name: str, seed_offset: int, rng: np.random.Generator, cfg: PlantConfig) -> ScenarioSpec:
    """평가용 무작위 막힘·펌프 저하·센서 고장 시나리오 (원인 분류 평가용)."""
    start = int(DAY + rng.integers(2 * 60, 14 * 60))
    if kind == "clog":
        seg = int(rng.integers(1, cfg.n_segments + 1))
        peak = float(rng.uniform(0.5, 1.5))
        mk = lambda c, s=seg, st=start, pk=peak: [Event(kind="clog", start=st, ramp=3 * 60, segment=s, peak=pk)]
        desc = f"무작위 막힘: 세그먼트 {seg}, 저항 증가 {peak:.2f}배"
    elif kind == "pump":
        peak = float(rng.uniform(0.15, 0.4))
        mk = lambda c, st=start, pk=peak: [Event(kind="pump", start=st, ramp=4 * 60, peak=pk)]
        desc = f"무작위 펌프 저하: 계수 +{peak * 100:.0f}%"
    elif kind == "sensor":
        gi = int(rng.integers(0, len(cfg.sensor_groups)))
        name_s = str(rng.choice(["flow_in", "flow_out"]))
        mode = str(rng.choice(["stuck", "offset"]))
        val = float(rng.choice([-1, 1]) * rng.uniform(0.02, 0.05))
        mk = lambda c, g=gi, n=name_s, m=mode, v=val, st=start: [Event(kind="sensor", start=st, sensor_group=g, sensor_name=n, sensor_mode=m, sensor_value=v)]
        desc = f"무작위 센서 고장: 묶음 {gi + 1} {name_s} {mode}"
    else:
        raise ValueError(kind)
    return ScenarioSpec(name, desc, 3 * DAY, seed_offset, mk)


def hazard_leak_spec(name: str, seed_offset: int, rng: np.random.Generator, cfg: PlantConfig, joints, dist: str) -> ScenarioSpec:
    """누수 위치를 '진짜 수명 분포'의 고장 위험률에 따라 뽑는 평가용 시나리오 (사전확률 효과 평가용)."""
    from .maintenance import sample_leak_joints
    j = sample_leak_joints(cfg, joints, rng, 1, dist=dist).iloc[0]
    peak = float(rng.uniform(8.0, 30.0))
    ramp = int(rng.choice([0, 2 * 60, 6 * 60]))
    start = int(DAY + rng.integers(2 * 60, 14 * 60))
    seg, roll, side = int(j.segment), int(j.roll), str(j.side)
    return ScenarioSpec(
        name, f"위험률 기반 누수({dist}): {j.joint_id}, 최대 {peak:.1f} L/min, 램프 {ramp}분", 3 * DAY, seed_offset,
        lambda c, s=seg, r=roll, sd=side, st=start, pk=peak, rp=ramp: [_leak(s, r, sd, st, pk, rp)],
    )


def simulate_spec(cfg: PlantConfig, spec: ScenarioSpec) -> tuple[Truth, Operating]:
    rng = np.random.default_rng([int(cfg.sim["seed"]), spec.seed_offset])
    op = make_operating(cfg, spec.n, rng, op_changes=spec.op_changes)
    truth = simulate_truth(cfg, op, spec.events(cfg), rng)
    return truth, op


def sensors_for(cfg: PlantConfig, spec: ScenarioSpec, truth: Truth, layout: str) -> tuple[pd.DataFrame, list[list[int]]]:
    groups = cfg.sensor_groups if layout == "S-A" else cfg.per_segment_groups()
    rng = np.random.default_rng([int(cfg.sim["seed"]), spec.seed_offset, 99, 0 if layout == "S-A" else 1])
    df = build_sensors(cfg, truth, groups, layout, rng)
    return df, groups


def labels_for(cfg: PlantConfig, spec: ScenarioSpec, truth: Truth, layout: str, groups: list[list[int]]) -> dict:
    return {
        "scenario": spec.name, "layout": layout, "description": spec.description,
        "n_samples": spec.n, "dt_s": cfg.sim["dt_s"], "groups": groups,
        "events": [e.to_label() for e in truth.events],
    }


def write_scenario(cfg: PlantConfig, spec: ScenarioSpec, layouts=("S-A", "S-B"), out: Path = DATA_DIR) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    truth, _ = simulate_spec(cfg, spec)
    written = []
    for layout in layouts:
        df, groups = sensors_for(cfg, spec, truth, layout)
        base = out / f"{spec.name}__{layout}"
        df.to_csv(base.with_suffix(".csv.gz"), index=False, float_format="%.5g")
        base.with_suffix(".json").write_text(
            json.dumps(labels_for(cfg, spec, truth, layout, groups), ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(base.with_suffix(".csv.gz"))
    np.savez_compressed(
        out / f"{spec.name}__truth.npz",
        q_leak=truth.q_leak.astype(np.float32), speed=truth.speed.astype(np.float32),
        p_header=truth.p_header.astype(np.float32),
    )
    return written


def load_scenario(name: str, layout: str = "S-A", data_dir: Path = DATA_DIR) -> tuple[pd.DataFrame, dict]:
    df = pd.read_csv(data_dir / f"{name}__{layout}.csv.gz")
    labels = json.loads((data_dir / f"{name}__{layout}.json").read_text(encoding="utf-8"))
    return df, labels
