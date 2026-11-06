"""14단계: 점검 피드백과 점검 순서(O1) 평가.

같은 사후확률에서 출발해 세 가지 점검 정책을 비교한다 (누수 확정까지 걸리는 점검 횟수, 점검 시간, 누적 위험 노출).
 - random : 무작위 순서 (피드백 없음)
 - prob   : 확률이 가장 큰 후보부터, 점검 결과로 매번 갱신
 - o1     : 확률 ÷ (점검 시간 + λ·접근 위험) 이 가장 큰 후보부터, 점검 결과로 매번 갱신
점검은 누수를 90% 확률로 찾아내고(놓칠 확률 10%), 누수가 아닌 곳에서 잘못 '누수'라고 할 확률은 2%라고 가정한다(오입력·오판 포함). '누수 확인'이 나오면 점검을 멈춘다.
순위 갱신에는 보수적으로 정확도 90%를 쓴다.
위험 노출 = Σ(점검 시간 × 접근 위험)  ← 접근 위험·점검 시간은 모두 가상값이다.

실행: python -m eval.inspection_eval
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from core.detect import ewma, first_alarm, recenter
from core.lifetime import collect_lives, fit_weibull, prior_from_fit
from core.locate import WINDOW, apply_inspection, observed_vector, priority_order, rank_candidates
from core.normalize import groups_in
from core.signature import build_signatures
from eval.common import EPISODE_GAP, MARGIN_SD, calibrate_threshold, fit_baseline
from eval.localize_eval import DIAG_DELAY, LAM, scenario_names
from sim.config import load_config
from sim.maintenance import joint_id
from sim.scenarios import DATA_DIR, load_scenario

ACC = 0.9               # 순위 갱신에 쓰는 점검 정확도
SENS = 0.9              # 누수를 실제로 찾아낼 확률
FALSE_POS = 0.02        # 누수가 아닌 곳에서 '누수'라고 잘못 입력할 확률
MAX_STEPS = 60


def run_policy(policy, p0, truth_idx, minutes, risk, rng, lam=20.0):
    p = p0.copy()
    inspected = np.zeros(len(p), dtype=bool)
    n_insp, t_min, expo = 0, 0.0, 0.0
    order_rand = rng.permutation(len(p))
    for step in range(MAX_STEPS):
        if policy == "random":
            idx = int(order_rand[step])
        elif policy == "prob":
            q = np.where(inspected, -1, p)
            idx = int(np.argmax(q))
        else:
            score, _ = priority_order(p, minutes, risk, lam)
            idx = int(np.argmax(np.where(inspected, -1, score)))
        inspected[idx] = True
        n_insp += 1
        t_min += minutes[idx]
        expo += minutes[idx] * risk[idx]
        is_leak = idx == truth_idx
        says_leak = (rng.random() < SENS) if is_leak else (rng.random() < FALSE_POS)
        if says_leak:
            return {"n": n_insp, "minutes": t_min, "exposure": expo, "correct": bool(is_leak)}
        if policy != "random":
            p = apply_inspection(p, idx, "no_issue", ACC)
            p[inspected] = np.maximum(p[inspected], 1e-12)
    return {"n": MAX_STEPS, "minutes": t_min, "exposure": expo, "correct": False}


def evaluate(layout: str, prefix: str, joints: pd.DataFrame, log: pd.DataFrame, bl, tr, sigs, cfg, reps: int = 20) -> dict:
    gs = groups_in(tr)
    fit = fit_weibull(*collect_lives(joints, log))
    pr = prior_from_fit(fit, joints, float(cfg.sim["maintenance"]["hazard_window_days"]))
    by_id = dict(zip(joints.joint_id, pr))
    prior = np.array([by_id[j] for j in sigs.joint_ids]); prior /= prior.sum()
    jt = joints.set_index("joint_id")
    minutes = np.array([jt.loc[j, "inspect_minutes"] for j in sigs.joint_ids])
    risk = np.array([jt.loc[j, "access_risk"] for j in sigs.joint_ids])
    thr = {}
    for g in gs:
        st = ewma(recenter(bl.residuals(tr, g)["z_imb_mass"].to_numpy()), LAM)
        thr[g] = calibrate_threshold(st, 1, EPISODE_GAP, 1) + MARGIN_SD * float(np.std(st))
    idx_of = {j: i for i, j in enumerate(sigs.joint_ids)}
    rng = np.random.default_rng(5)
    acc = {k: [] for k in ("random", "prob", "o1")}
    for name in scenario_names(prefix):
        df, lab = load_scenario(name, layout)
        ev = lab["events"][0]
        t0 = int(ev["start_ts"])
        truth_idx = idx_of[joint_id(ev["segment"], ev["roll"], ev["side"])]
        alarms = [a for g in gs if (a := first_alarm(ewma(recenter(bl.residuals(df, g)["z_imb_mass"].to_numpy()), LAM), thr[g], t0)) is not None]
        if not alarms:
            continue
        t_d = min(min(alarms) + DIAG_DELAY, len(df) - 1)
        post = rank_candidates(sigs, observed_vector(df, bl, gs, t_d, WINDOW), prior)
        for _ in range(reps):
            for pol in acc:
                acc[pol].append(run_policy(pol, post.prob, truth_idx, minutes, risk, rng))
    out = {}
    for pol, rows in acc.items():
        out[pol] = {
            "mean_inspections": round(float(np.mean([r["n"] for r in rows])), 2),
            "mean_minutes": round(float(np.mean([r["minutes"] for r in rows])), 1),
            "mean_exposure": round(float(np.mean([r["exposure"] for r in rows])), 1),
            "success_rate": round(float(np.mean([r["correct"] for r in rows])), 3),
        }
    return out


def main() -> None:
    cfg = load_config()
    jw = pd.read_csv(DATA_DIR / "joints.csv"); lw = pd.read_csv(DATA_DIR / "maintenance_log.csv")
    res = {}
    for layout in ("S-A", "S-B"):
        bl, tr = fit_baseline(layout)
        sigs = build_signatures(cfg, bl, layout)
        res[layout] = evaluate(layout, "evalp_w_", jw, lw, bl, tr, sigs, cfg)
        print(f"\n[{layout}] 누수 확정까지 (정확도 {ACC*100:.0f}% 점검, 가상 위험·시간)")
        for pol, v in res[layout].items():
            print(f"  {pol:6s} 점검 {v['mean_inspections']:5.2f}회  시간 {v['mean_minutes']:6.1f}분  위험노출 {v['mean_exposure']:7.1f}  성공 {v['success_rate']*100:5.1f}%")
    (DATA_DIR / "inspection_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
