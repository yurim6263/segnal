"""config/plant.yaml 로더. 세그먼트 수·계측 묶음을 코드에 쓰지 않고 이 파일에서만 읽는다."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "plant.yaml"


@dataclass
class PlantConfig:
    n_segments: int
    sensor_groups: list[list[int]]
    rolls_per_segment: int
    joints_per_roll: int
    sim: dict = field(default_factory=dict)

    # ---- 편의 함수 -------------------------------------------------
    def group_of_segment(self, segment: int) -> int:
        """세그먼트 번호(1부터) → 계측 묶음 번호(0부터)."""
        for gi, segs in enumerate(self.sensor_groups):
            if segment in segs:
                return gi
        raise ValueError(f"segment {segment} is not in any sensor group")

    def per_segment_groups(self) -> list[list[int]]:
        """S-B 계측: 세그먼트마다 하나의 묶음."""
        return [[s] for s in range(1, self.n_segments + 1)]

    def validate(self) -> None:
        covered = sorted(s for g in self.sensor_groups for s in g)
        if covered != list(range(1, self.n_segments + 1)):
            raise ValueError(
                "sensor_groups must cover every segment exactly once: "
                f"n_segments={self.n_segments}, covered={covered}"
            )
        nf = self.sim.get("nominal_flow_lpm", [])
        if len(nf) != self.n_segments:
            raise ValueError(
                f"sim.nominal_flow_lpm needs {self.n_segments} values, got {len(nf)}"
            )


def load_config(path: Path | str | None = None) -> PlantConfig:
    p = Path(path) if path else CONFIG_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    sim = dict(raw.get("sim", {}))
    if "maintenance" in raw:                      # 정비 이력(수명) 가정은 최상위 블록
        sim["maintenance"] = raw["maintenance"]
    cfg = PlantConfig(
        n_segments=int(raw["n_segments"]),
        sensor_groups=[[int(s) for s in g] for g in raw["sensor_groups"]],
        rolls_per_segment=int(raw["rolls_per_segment"]),
        joints_per_roll=int(raw.get("joints_per_roll", 2)),
        sim=sim,
    )
    cfg.validate()
    return cfg
