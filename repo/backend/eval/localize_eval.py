"""12·14·16단계: 위치 후보 순위 평가와 사전확률(수명 모델) 효과 비교.

- eval_leak_*  : 누수 위치가 균일 무작위
- evalp_w_*    : 누수 위치를 '진짜 Weibull 위험률'로 뽑음  → 모델(Weibull)과 일치
- evalp_l_*    : 누수 위치를 '진짜 lognormal 위험률'로 뽑음 → 모델(Weibull)과 불일치 (순환 논리 방지용)

사전확률: none(균일) / weibull(정비 이력에 Weibull을 맞춰 얻은 조건부 고장 확률)
지표: 조인트 단위 top-1/top-3/top-10 적중률, 정답 조인트의 평균 순위, 세그먼트 단위 top-1, 계측 묶음 단위 top-1

실행: python -m eval.localize_eval
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.detect import ewma, first_alarm, recenter
from core.lifetime import collect_lives, fit_weibull, prior_from_fit
from core.locate import WINDOW, observed_vector, rank_candidates
from core.normalize import groups_in
from core.signature import build_signatures
from eval.common import EPISODE_GAP, MARGIN_SD, calibrate_threshold, fit_baseline
from sim.config import load_config
from sim.maintenance import joint_id
from sim.scenarios import DATA_DIR, load_scenario

LAM = 0.1
DIAG_DELAY = 60          # 경보 후 60분 뒤 시점의 잔차로 위치 후보를 낸다


def scenario_names(prefix: str) -> list[str]:
    return sorted(p.name.split("__")[0] for p in DATA_DIR.glob(f"{prefix}*__S-A.json"))


def _prior_vector(sigs, fit, joints: pd.DataFrame, window_days: float) -> np.ndarray:
    pr = prior_from_fit(fit, joints, window_days)
    by_id = dict(zip(joints.joint_id, pr))
    v = np.array([by_id[j] for j in sigs.joint_ids])
    return v / v.sum()


def evaluate_set(layout: str, prefix: str, joints: pd.DataFrame, log: pd.DataFrame, bl, tr, sigs, cfg) -> dict:
    gs = groups_in(tr)
    fit = fit_weibull(*collect_lives(joints, log))
    window_days = float(cfg.sim["maintenance"]["hazard_window_days"])
    priors = {"none": None, "weibull": _prior_vector(sigs, fit, joints, window_days)}

    # 임계값: 정상 학습 구간에서 보정 (그룹별)
    thr = {}
    for g in gs:
        st = ewma(recenter(bl.residuals(tr, g)["z_imb_mass"].to_numpy()), LAM)
        thr[g] = calibrate_threshold(st, 1, EPISODE_GAP, 1) + MARGIN_SD * float(np.std(st))

    id_index = {j: i for i, j in enumerate(sigs.joint_ids)}
    res = {k: {"ranks": [], "seg_top1": [], "grp_top1": []} for k in priors}
    missed = 0
    for name in scenario_names(prefix):
        df, lab = load_scenario(name, layout)
        ev = lab["events"][0]
        t0 = int(ev["start_ts"])
        truth_id = joint_id(ev["segment"], ev["roll"], ev["side"])
        groups = lab["groups"]
        true_group = next(i for i, g in enumerate(groups) if ev["segment"] in g) + 1
        # 어느 묶음이든 먼저 경보가 난 시점
        alarms = []
        for g in gs:
            e = ewma(recenter(bl.residuals(df, g)["z_imb_mass"].to_numpy()), LAM)
            a = first_alarm(e, thr[g], t0)
            if a is not None:
                alarms.append(a)
        if not alarms:
            missed += 1
            continue
        t_d = min(min(alarms) + DIAG_DELAY, len(df) - 1)
        r = observed_vector(df, bl, gs, t_d, WINDOW)
        for k, pr in priors.items():
            post = rank_candidates(sigs, r, pr)
            order = post.order()
            rank = int(np.flatnonzero(order == id_index[truth_id])[0]) + 1
            res[k]["ranks"].append(rank)
            sp = post.segment_prob()
            res[k]["seg_top1"].append(max(sp, key=sp.get) == ev["segment"])
            gp = {}
            for s, p in sp.items():
                gi = next(i for i, g in enumerate(groups) if s in g) + 1
                gp[gi] = gp.get(gi, 0.0) + p
            res[k]["grp_top1"].append(max(gp, key=gp.get) == true_group)
    out = {"n": len(scenario_names(prefix)), "missed": missed, "weibull_fit": {"shape": round(fit.shape, 2), "scale": round(fit.scale, 1)}}
    for k, v in res.items():
        ranks = np.array(v["ranks"])
        out[k] = {
            "n": int(len(ranks)),
            "joint_top1": round(float((ranks <= 1).mean()), 3),
            "joint_top3": round(float((ranks <= 3).mean()), 3),
            "joint_top10": round(float((ranks <= 10).mean()), 3),
            "mean_rank": round(float(ranks.mean()), 1),
            "segment_top1": round(float(np.mean(v["seg_top1"])), 3),
            "group_top1": round(float(np.mean(v["grp_top1"])), 3),
        }
    return out


def main() -> None:
    cfg = load_config()
    jw = pd.read_csv(DATA_DIR / "joints.csv"); lw = pd.read_csv(DATA_DIR / "maintenance_log.csv")
    jl = pd.read_csv(DATA_DIR / "joints_lognormal.csv"); ll = pd.read_csv(DATA_DIR / "maintenance_log_lognormal.csv")
    results = {}
    for layout in ("S-A", "S-B"):
        bl, tr = fit_baseline(layout)
        sigs = build_signatures(cfg, bl, layout)
        results[layout] = {
            "eval_leak (위치 균일)": evaluate_set(layout, "eval_leak_", jw, lw, bl, tr, sigs, cfg),
            "evalp_w (진짜 Weibull)": evaluate_set(layout, "evalp_w_", jw, lw, bl, tr, sigs, cfg),
            "evalp_l (진짜 lognormal, 모델은 Weibull)": evaluate_set(layout, "evalp_l_", jl, ll, bl, tr, sigs, cfg),
        }
    for layout, sets in results.items():
        print(f"\n===== {layout} =====")
        for sname, r in sets.items():
            print(f"[{sname}] 시나리오 {r['n']}개(미탐지 {r['missed']}), Weibull 적합 shape={r['weibull_fit']['shape']} scale={r['weibull_fit']['scale']}")
            for k in ("none", "weibull"):
                v = r[k]
                print(f"   사전확률 {k:8s} 조인트 top1 {v['joint_top1']*100:5.1f}%  top3 {v['joint_top3']*100:5.1f}%  top10 {v['joint_top10']*100:5.1f}%  평균순위 {v['mean_rank']:6.1f}  | 세그먼트 top1 {v['segment_top1']*100:5.1f}%  묶음 top1 {v['group_top1']*100:5.1f}%")
    (DATA_DIR / "localize_eval.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
