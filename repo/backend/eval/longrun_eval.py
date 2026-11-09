"""장기 오경보 시험: 정상 상태(누수 없음)를 30일 연속으로 돌려 경보가 몇 번 나는지 센다.

07 문서의 6번("오경보 없음은 3일만 시험한 결과")에 대한 답이다. 기존 평가의 오경보는 누수 시작 전 1~1.5일씩 30번(매번 처음 시작)과
정상 3일을 합친 것이어서, 한 번 시작해 오래 돌릴 때의 값이 아니었다. 여기서는 기준선·임계값을 정상 14일(학습)에서 맞춘 뒤
다른 시드의 정상 30일을 이어서 돌린다. 유량계 표류 크기를 0·현재·2배로 바꿔 범위로 본다(표류 크기는 현장에서 모르는 값).

실행: python -m eval.longrun_eval [--days 30] [--seeds 3]
"""
from __future__ import annotations

import argparse
import copy
import json

import numpy as np

from core.detect import count_alarm_episodes, ewma, recenter
from core.normalize import group_signals, groups_in
from eval.common import EPISODE_GAP, MARGIN_SD, MIN_RUN, TARGET_FA_EPISODES_14D, calibrate_threshold, fit_baseline
from eval.localize_eval import LAM
from sim.config import load_config
from sim.scenarios import DATA_DIR, DAY, ScenarioSpec, sensors_for, simulate_spec

DRIFT_SCALES = [(0.0, "표류 0 (유량계가 안 틀어짐)"), (1.0, "현재 설정"), (2.0, "표류 2배")]


def run(days: int, seeds: int, layout: str = "S-A") -> dict:
    base_cfg = load_config()
    bl, tr = fit_baseline(layout)
    gs = groups_in(tr)
    thr_e, thr_f = {}, {}
    for g in gs:
        st = ewma(recenter(bl.residuals(tr, g)["z_imb_mass"].to_numpy()), LAM)
        thr_e[g] = calibrate_threshold(st, TARGET_FA_EPISODES_14D, EPISODE_GAP, MIN_RUN["ewma"]) + MARGIN_SD * float(np.std(st))
        iv = group_signals(tr, g)["imb_vol"].to_numpy()
        thr_f[g] = calibrate_threshold(iv, TARGET_FA_EPISODES_14D, EPISODE_GAP, MIN_RUN["fixed"]) + MARGIN_SD * float(np.std(iv))

    rows = []
    for scale, label in DRIFT_SCALES:
        cfg = copy.deepcopy(base_cfg)
        cfg.sim["sensor"]["flow_drift_rel_per_sqrt_day"] *= scale
        ev = fx = 0
        per_group = {g: 0 for g in gs}
        for s in range(seeds):
            spec = ScenarioSpec(f"long_{s}", "정상 장기", days * DAY, 8000 + s, lambda c: [])
            truth, _ = simulate_spec(cfg, spec)
            df, _ = sensors_for(cfg, spec, truth, layout)
            for g in gs:
                z = ewma(recenter(bl.residuals(df, g)["z_imb_mass"].to_numpy()), LAM)
                n = count_alarm_episodes(z, thr_e[g], EPISODE_GAP, MIN_RUN["ewma"])
                ev += n
                per_group[g] += n
                fx += count_alarm_episodes(group_signals(df, g)["imb_vol"].to_numpy(), thr_f[g], EPISODE_GAP, MIN_RUN["fixed"])
        run_days = days * seeds
        row = {"drift_scale": scale, "label": label, "days_total": run_days,
               "ours_episodes": ev, "fixed_episodes": fx,
               "ours_per_30d_plant": round(ev / run_days * 30, 2), "fixed_per_30d_plant": round(fx / run_days * 30, 2),
               "ours_per_14d_per_group": round(ev / run_days * 14 / len(gs), 3), "per_group_episodes": per_group}
        rows.append(row)
        print(f"{label:28s} 총 {run_days}일: 우리 {ev}건(공장 전체 월 {row['ours_per_30d_plant']}건, 묶음당 14일 {row['ours_per_14d_per_group']}건) | 고정 임계값 {fx}건(월 {row['fixed_per_30d_plant']}건) | 묶음별 {per_group}", flush=True)
    return {"layout": layout, "days_per_run": days, "seeds": seeds, "rows": rows,
            "note": "기준선·임계값은 정상 14일(학습)에서 맞추고, 다른 시드의 정상 연속 운전에서 경보 사건 수를 센 값. 합성 데이터."}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seeds", type=int, default=3)
    a = ap.parse_args()
    out = run(a.days, a.seeds)
    (DATA_DIR / "longrun_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
