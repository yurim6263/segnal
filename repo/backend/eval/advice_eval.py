"""교체 시점 권고 평가: 누수 30건(평가용 무작위 시나리오)에서 권고가 맞았는지, 기존 방식보다 여유를 얼마나 확보하는지, 가정이 바뀌면 어떻게 달라지는지.

정답(시뮬레이터): 실제 누수량이 교체 필요 크기에 처음 닿은 시각 t_L (끝내 닿지 않으면 없음).
 - "필요했다" = 계획 정지 전에 t_L이 옴 (그 전에 교체해야 했음)
 - 권고별 판정
     지금 점검(now)      : t_L이 다음 휴지보다 앞이면 적절, 아니면 조기
     다음 휴지에 교체    : 필요했고 t_L이 그 휴지 뒤면 적절, 필요했는데 t_L이 휴지 앞이면 늦음(놓침), 필요 없었으면 조기
     계획 정지까지 감시  : 필요 없었으면 적절, 필요했으면 놓침
 - 비교 정책: A) 항상 계획 정지까지 기다림, B) 항상 다음 휴지에 교체
정비 창 일정과 교체 필요 크기는 [가정]이라 값을 바꿔 가며 같은 평가를 되풀이한다.
실행: python -m eval.advice_eval   결과: data/generated/advice_eval.json
"""
from __future__ import annotations

import copy
import json

import numpy as np

from core.advice import advise, next_windows
from core.classify import DiagnosisModel
from core.detect import cusum, first_alarm, recenter
from core.forecast import estimate_leak, forecast_line, leak_noise
from core.normalize import group_signals, groups_in
from core.pattern import build_pattern_model
from eval.common import EPISODE_GAP, MARGIN_SD, calibrate_threshold, eval_names, fit_baseline, load_eval
from sim.config import load_config
from sim.scenarios import DATA_DIR

OFFSETS = (0, 180, 360)


def prepare(cfg, bl, tr, gs, model):
    """누수로 판정된 시나리오마다 시점별 추정 누수량·추세와 정답을 모은다."""
    thr_fixed, noise = {}, {}
    for g in gs:
        iv = group_signals(tr, g)["imb_vol"].to_numpy()
        thr_fixed[g] = calibrate_threshold(iv, 1, EPISODE_GAP, 5) + MARGIN_SD * float(np.std(iv))
        noise[g] = leak_noise(bl.residuals(tr, g)["res_imb_mass"].to_numpy())
    out, skipped = [], 0
    for name in eval_names("eval_leak_"):
        sc = load_eval(name)
        df, T = sc.df, len(sc.df)
        d = model.diagnose_final(df, gs)
        if d.cause != "leak" or d.alarm_ts is None or d.diag_ts is None:
            skipped += 1
            continue
        g = d.group
        res = bl.residuals(df, g)["res_imb_mass"].to_numpy()
        cu = cusum(recenter(bl.residuals(df, g)["z_imb_mass"].to_numpy()), 0.5)
        t_start = d.alarm_ts
        while t_start > 0 and cu[t_start] > 0:
            t_start -= 1
        t_start = max(t_start, d.alarm_ts - 720)
        segs = sc.labels["groups"][g - 1]
        flow_in = df[f"g{g}_flow_in"].to_numpy()
        q_series = sc.truth_leak[:, [s - 1 for s in segs]].sum(axis=1)
        vol = group_signals(df, g)["imb_vol"].to_numpy()
        out.append({"name": name, "T": T, "g": g, "alarm_ts": d.alarm_ts, "diag_ts": d.diag_ts, "t_start": t_start, "res": res,
                    "flow_in": flow_in, "q": q_series, "noise": noise[g], "fixed_alarm": first_alarm(vol, thr_fixed[g], t_start, 5)})
    return out, skipped


def judge(action: str, t_L: int | None, ts: int, t_break: int, t_stop: int | None) -> str:
    needed = t_L is not None and (t_stop is None or t_L < t_stop)
    if action == "now":
        return "적절" if (t_L is not None and t_L < t_break) else "조기"
    if action == "next_break":
        if not needed:
            return "조기"
        return "늦음" if t_L < t_break else "적절"
    if action == "watch":
        return "놓침" if needed else "적절"
    return "해당 없음"


def evaluate(items, plan, offsets=OFFSETS) -> dict:
    L = float(plan["replace_limit_lpm"])
    res = {"by_action": {}, "policy_ours": {"적절": 0, "조기": 0, "늦음": 0, "놓침": 0}, "policy_wait": {"적절": 0, "놓침": 0}, "policy_break": {"적절": 0, "조기": 0, "늦음": 0}, "n": 0}
    for it in items:
        for off in offsets:
            ts = it["diag_ts"] + off
            if ts >= it["T"] - 1:
                continue
            t_break, t_stop = next_windows(ts, plan)
            if t_stop is None:                  # 계획 정지가 지난 뒤는 평가하지 않는다
                continue
            est = estimate_leak(it["res"], it["flow_in"], ts, it["noise"])
            flow = max(est["flow_lpm"], 1.0)
            f = forecast_line(it["res"], est["lpm"] / flow, L / flow, ts, it["t_start"])
            adv = advise("leak", est, f, ts, plan)
            hit = np.flatnonzero(it["q"][ts:] >= L)
            t_L = int(ts + hit[0]) if hit.size else None
            verdict = judge(adv["action"], t_L, ts, t_break, t_stop)
            res["n"] += 1
            res["by_action"].setdefault(adv["action"], {"적절": 0, "조기": 0, "늦음": 0, "놓침": 0})[verdict] += 1
            res["policy_ours"][verdict] += 1
            needed = t_L is not None and t_L < t_stop
            res["policy_wait"]["놓침" if needed else "적절"] += 1
            if not needed:
                res["policy_break"]["조기"] += 1
            else:
                res["policy_break"]["늦음" if t_L < t_break else "적절"] += 1
    return res


def lead_times(items, L: float) -> dict:
    """한계(교체 필요 크기)에 닿은 누수에서, 한계 도달 전에 알게 된 시간(분)을 우리 방식과 고정 임계값으로 비교."""
    ours, fixed = [], []
    for it in items:
        hit = np.flatnonzero(it["q"] >= L)
        if not hit.size:
            continue
        t_L = int(hit[0])
        ours.append(t_L - it["alarm_ts"])
        if it["fixed_alarm"] is not None:
            fixed.append(t_L - it["fixed_alarm"])
        else:
            fixed.append(None)
    f_ok = [x for x in fixed if x is not None]
    return {"n_reach_limit": len(ours), "ours_median_min": float(np.median(ours)) if ours else None,
            "ours_before_limit": int(sum(1 for x in ours if x > 0)),
            "fixed_detected": len(f_ok), "fixed_median_min": float(np.median(f_ok)) if f_ok else None,
            "fixed_before_limit": int(sum(1 for x in f_ok if x > 0)),
            "fixed_never": int(sum(1 for x in fixed if x is None))}


def estimate_stats(items, offsets=OFFSETS) -> dict:
    """추정 누수량이 실제 누수량과 얼마나 맞는지(오차 중앙값, 범위 안에 든 비율)."""
    errs, cov, true_q = [], [], []
    for it in items:
        for off in offsets:
            ts = it["diag_ts"] + off
            if ts >= it["T"] - 1:
                continue
            e = estimate_leak(it["res"], it["flow_in"], ts, it["noise"])
            q = float(it["q"][ts])
            errs.append(abs(e["lpm"] - q))
            cov.append(e["low_lpm"] <= q <= e["high_lpm"])
            true_q.append(q)
    return {"n": len(errs), "median_abs_err_lpm": round(float(np.median(errs)), 1), "coverage": round(float(np.mean(cov)), 2),
            "median_true_lpm": round(float(np.median(true_q)), 1)}


def main() -> None:
    cfg = load_config()
    bl, tr = fit_baseline("S-A")
    gs = groups_in(tr)
    model = DiagnosisModel(bl, build_pattern_model(cfg, bl, gs)).fit(tr, gs)
    items, skipped = prepare(cfg, bl, tr, gs, model)
    base = dict(cfg.plan)
    out = {"plan": base, "n_leaks": len(items), "skipped_not_leak": skipped, "main": evaluate(items, base), "lead": lead_times(items, float(base["replace_limit_lpm"])),
           "estimate": estimate_stats(items), "sensitivity": [], "note": "합성 데이터. 교체 필요 크기와 정비 창 일정은 가정이다. 판정 시점은 누수로 판정된 직후와 3시간·6시간 뒤."}
    for L in (10.0, 15.0, 20.0, 30.0):
        for every in (180, 360, 720):
            p = copy.deepcopy(base)
            p["replace_limit_lpm"], p["sequence_break_every_min"] = L, every
            r = evaluate(items, p, offsets=(0,))
            out["sensitivity"].append({"limit_lpm": L, "break_every_min": every, "n": r["n"], "ours": r["policy_ours"], "wait": r["policy_wait"], "break": r["policy_break"]})
    m = out["main"]
    print("권고별:", m["by_action"])
    print("우리:", m["policy_ours"], "| 항상 기다림:", m["policy_wait"], "| 항상 다음 휴지:", m["policy_break"], "| n", m["n"])
    print("여유:", out["lead"])
    print("추정 누수량:", out["estimate"])
    for s in out["sensitivity"]:
        print(s["limit_lpm"], s["break_every_min"], "n", s["n"], "우리", s["ours"], "기다림", s["wait"], "휴지", s["break"])
    (DATA_DIR / "advice_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
