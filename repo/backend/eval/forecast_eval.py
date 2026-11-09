"""경보선 도달 예상 시각과 추정 누수량의 정확도. 누수 30건(평가용 무작위 시나리오).

도달 시각: "기존 방식의 경보선에 해당하는 누수 크기"에 실제 누수가 처음 닿은 시각(시뮬레이터 정답)과 비교한다.
경보선에 해당하는 누수 크기 = 고정 임계값 − 정상 학습 구간의 평균 불균형. 실제 누수가 끝내 닿지 않으면(진행이 멈추면) 채점하지 못하고 따로 센다.
예상은 누수로 판정된 시점(diag_ts)과 그 뒤 3·6시간에 낸 것을 본다.
실행: python -m eval.forecast_eval [--t-crit 2 --k 1 --window 360]   결과: data/generated/forecast_eval.json
"""
from __future__ import annotations

import argparse
import json

import numpy as np

import core.forecast as FC
from core.classify import DiagnosisModel
from core.detect import cusum, first_alarm, recenter
from core.forecast import estimate_leak, forecast_line, leak_noise
from core.normalize import group_signals, groups_in
from core.pattern import build_pattern_model
from eval.common import EPISODE_GAP, MARGIN_SD, calibrate_threshold, eval_names, fit_baseline, load_eval
from sim.config import load_config
from sim.scenarios import DATA_DIR

OFFSETS = (0, 180, 360)


def run(save: bool = True, verbose: bool = True) -> dict:
    cfg = load_config()
    bl, tr = fit_baseline("S-A")
    gs = groups_in(tr)
    model = DiagnosisModel(bl, build_pattern_model(cfg, bl, gs)).fit(tr, gs)
    thr_fixed, noise, line_leak = {}, {}, {}
    for g in gs:
        iv = group_signals(tr, g)["imb_vol"].to_numpy()
        thr_fixed[g] = calibrate_threshold(iv, 1, EPISODE_GAP, 5) + MARGIN_SD * float(np.std(iv))
        line_leak[g] = thr_fixed[g] - float(np.mean(iv))
        noise[g] = leak_noise(bl.residuals(tr, g)["res_imb_mass"].to_numpy())

    rows, est_rows = [], []
    skipped = {"원인이 누수가 아님": 0}
    for name in eval_names("eval_leak_"):
        sc = load_eval(name)
        df, T = sc.df, len(sc.df)
        d = model.diagnose_final(df, gs)
        if d.cause != "leak" or d.alarm_ts is None or d.diag_ts is None:
            skipped["원인이 누수가 아님"] += 1
            continue
        g = d.group
        vol = group_signals(df, g)["imb_vol"].to_numpy()
        res = bl.residuals(df, g)["res_imb_mass"].to_numpy()
        cu = cusum(recenter(bl.residuals(df, g)["z_imb_mass"].to_numpy()), 0.5)
        t_start = d.alarm_ts
        while t_start > 0 and cu[t_start] > 0:
            t_start -= 1
        t_start = max(t_start, d.alarm_ts - 720)
        t_fx = first_alarm(vol, thr_fixed[g], t_start, 5)
        segs = sc.labels["groups"][g - 1]
        flow_in = df[f"g{g}_flow_in"].to_numpy()
        q_series = sc.truth_leak[:, [s_ - 1 for s_ in segs]].sum(axis=1)
        frac_series = q_series / np.maximum(flow_in, 1.0)
        for off in OFFSETS:
            ts = d.diag_ts + off
            if ts >= T - 1:
                continue
            level = float(np.mean(vol[max(ts - 29, 0): ts + 1]))
            f = forecast_line(res, level, thr_fixed[g], ts, t_start)
            hit = np.flatnonzero(frac_series[ts + 1:] >= line_leak[g])
            row = {"scenario": name, "offset_min": off, "ts": ts, "available": f["available"], "crossed_already": f["crossed"],
                   "hours": f["hours"], "low": f["low_hours"], "high": f["high_hours"], "reason": f["reason"],
                   "fixed_alarm_ts": t_fx}
            if hit.size:
                row["actual_hours"] = round((hit[0] + 1) / 60, 1)
            rows.append(row)
            q_true = float(q_series[ts])
            e = estimate_leak(res, flow_in, ts, noise[g])
            est_rows.append({"scenario": name, "offset_min": off, "true_lpm": round(q_true, 1), **e,
                             "covered": e["low_lpm"] <= q_true <= e["high_lpm"], "abs_err": round(abs(e["lpm"] - q_true), 1)})

    def stat(sel):
        xs = [r for r in rows if sel(r)]
        avail = [r for r in xs if r["available"] and "actual_hours" in r]
        out = {"n_forecasts": len(xs), "n_available": sum(1 for r in xs if r["available"]), "n_scored": len(avail)}
        if avail:
            err = [abs(r["hours"] - r["actual_hours"]) for r in avail]
            out.update(median_abs_err_h=round(float(np.median(err)), 1),
                       median_rel_err=round(float(np.median([abs(r["hours"] - r["actual_hours"]) / max(r["actual_hours"], 0.5) for r in avail])), 2),
                       coverage=round(float(np.mean([r["low"] <= r["actual_hours"] and (r["high"] is None or r["actual_hours"] <= r["high"]) for r in avail])), 2))
        unscored = [r for r in xs if r["available"] and "actual_hours" not in r and not r["crossed_already"]]
        out["available_but_never_reached"] = len(unscored)
        return out

    res = {"params": {"t_crit": FC.T_CRIT, "k_range": FC.K_RANGE, "max_window_min": FC.MAX_WINDOW},
           "by_offset_min": {str(o): stat(lambda r, o=o: r["offset_min"] == o) for o in OFFSETS}, "skipped": skipped,
           "leak_estimate": {"n": len(est_rows), "median_abs_err_lpm": round(float(np.median([r["abs_err"] for r in est_rows])), 1),
                             "coverage": round(float(np.mean([r["covered"] for r in est_rows])), 2),
                             "median_true_lpm": round(float(np.median([r["true_lpm"] for r in est_rows])), 1)},
           "rows": rows, "estimate_rows": est_rows,
           "note": "합성 데이터. 도달 시각은 경보선에 해당하는 크기에 실제 누수가 처음 닿은 시각(시뮬레이터 정답)과 비교. 끝내 닿지 않은 누수는 채점하지 못함."}
    if verbose:
        print("params", res["params"])
        for o, s in res["by_offset_min"].items():
            print(f"+{o}분:", s)
        print("누수량:", res["leak_estimate"], "제외:", skipped)
    if save:
        (DATA_DIR / "forecast_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t-crit", type=float, default=FC.T_CRIT)
    ap.add_argument("--k", type=float, default=FC.K_RANGE)
    ap.add_argument("--window", type=int, default=FC.MAX_WINDOW)
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    if a.sweep:
        for tc in (2.0, 3.0):
            for k in (1.0, 2.0):
                for w in (180, 360):
                    FC.T_CRIT, FC.K_RANGE, FC.MAX_WINDOW = tc, k, w
                    r = run(save=False, verbose=False)
                    print(tc, k, w, {o: (s["n_available"], s["n_scored"], s.get("median_abs_err_h"), s.get("coverage"), s["available_but_never_reached"]) for o, s in r["by_offset_min"].items()}, flush=True)
        return
    FC.T_CRIT, FC.K_RANGE, FC.MAX_WINDOW = a.t_crit, a.k, a.window
    run()


if __name__ == "__main__":
    main()
