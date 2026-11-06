"""평가 공통 도구: 시나리오 묶음 불러오기, 묶음별 통계 계산, 임계값 보정."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from core.baseline import Baseline
from core.detect import count_alarm_episodes
from core.normalize import group_signals
from sim.config import PlantConfig, load_config
from sim.scenarios import DATA_DIR, load_scenario

TARGET_FA_EPISODES_14D = 1       # 정상 14일(학습 구간)에서 허용하는 오경보 사건 수 (그룹당)
MARGIN_SD = 1.0                  # 임계값 여유: 학습 구간 통계의 표준편차 × 1.0 (계측 표류 대비)
EPISODE_GAP = 30                 # 분: 이 시간 안에 다시 넘으면 같은 사건
MIN_RUN = {"fixed": 5, "ewma": 1, "cusum": 1}   # 경보 지연(on-delay): 고정 임계값은 5분 연속 넘어야 경보


@dataclass
class EvalScenario:
    name: str
    df: pd.DataFrame
    labels: dict
    truth_leak: np.ndarray            # (T, N) 누수량 L/min
    speed: np.ndarray


def eval_names(prefix: str = "eval_leak_") -> list[str]:
    return sorted(p.name.split("__")[0] for p in DATA_DIR.glob(f"{prefix}*__S-A.json"))


def load_eval(name: str, layout: str = "S-A") -> EvalScenario:
    df, labels = load_scenario(name, layout)
    z = np.load(DATA_DIR / f"{name}__truth.npz")
    return EvalScenario(name, df, labels, z["q_leak"], z["speed"])


def event_group(cfg: PlantConfig, labels: dict) -> tuple[int, int]:
    """(이벤트 시작 샘플, 이벤트 세그먼트가 속한 묶음 번호(1부터))."""
    ev = labels["events"][0]
    groups = labels["groups"]
    seg = ev["segment"]
    gi = next(i for i, g in enumerate(groups) if seg in g)
    return int(ev["start_ts"]), gi + 1


def calibrate_threshold(stat: np.ndarray, target_episodes: int, gap: int = EPISODE_GAP, min_run: int = 1) -> float:
    """정상 구간에서 오경보 사건이 target_episodes 이하가 되는 가장 작은 임계값(이분 탐색)."""
    def ok(thr: float) -> bool:
        # 오경보 사건 수가 목표 이하이고, 경보가 켜져 있는 시간 비율도 1% 이하여야 한다
        # (깜빡이는 경보가 '하나의 사건'으로 합쳐져 통과하는 것을 막는다)
        return count_alarm_episodes(stat, thr, gap, min_run) <= target_episodes and float(np.mean(stat > thr)) <= 0.01

    lo, hi = float(np.nanmedian(stat)), float(np.nanmax(stat))
    if ok(lo):
        return lo
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi


def fit_baseline(layout: str = "S-A") -> tuple[Baseline, pd.DataFrame]:
    tr, _ = load_scenario("train_normal", layout)
    return Baseline().fit(tr), tr
