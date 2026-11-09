"""검출기 공정 비교 (8단계 + B17).

규칙: 모든 검출기는 정상 학습 구간(14일)에서 오경보 사건 수를 같게 맞춘 뒤 임계값 여유(학습 통계 표준편차 × 1)를 더하고,
무작위 누수 시나리오 30개에서 탐지 지연을 비교한다. 오경보는 정상 3일 + 누수 시작 전 구간에서 센다.
ML 검출기(Isolation Forest, 오토인코더)는 과적합을 막으려고 학습 구간의 앞 70%로 학습하고 뒤 30%로 임계값을 맞춘다.

실행: python -m eval.tune_detectors [--no-ae] [--layouts S-A S-B]
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from core.detect import (
    count_alarm_episodes, cusum, ewma, first_alarm, recenter,
)
from core.ml_detectors import IForestDetector
from core.normalize import group_signals, groups_in
from eval.common import (
    EPISODE_GAP, MARGIN_SD, MIN_RUN, TARGET_FA_EPISODES_14D, calibrate_threshold, eval_names, event_group,
    fit_baseline, load_eval,
)
from sim.config import load_config
from sim.scenarios import DATA_DIR, load_scenario

LAMBDAS = [0.02, 0.05, 0.1, 0.2, 0.4]
CUSUM_KS = [0.25, 0.5, 1.0]
HOLDOUT_FRAC = 0.3


RAW_STAT: dict = {}     # 묶음별 (학습 구간 질량 불균형 평균, 표준편차): '운전점 보정 없음' 비교용


def base_signals(df, bl, g):
    """(재중심화한 z, 고정 임계값이 보는 부피유량 불균형, 운전점 보정 없이 학습 구간 통계로만 표준화한 z)"""
    z = recenter(bl.residuals(df, g)["z_imb_mass"].to_numpy())
    sig = group_signals(df, g)
    imb = sig["imb_vol"].to_numpy()
    if g not in RAW_STAT:
        raise KeyError(g)
    mu, sd = RAW_STAT[g]
    raw = recenter((sig["imb_mass"].to_numpy() - mu) / sd)
    return z, imb, raw


def _row(label, kind, params, stats, scen, cfg, mr, target):
    """stats: {'train': {g: arr}, 'normal': {g: arr}, 'ev': {name: {g: arr}}} — 이미 검출기 통계로 변환된 값."""
    gs = list(stats["train"])
    thr = {}
    for g in gs:
        st = stats["train"][g]
        thr[g] = calibrate_threshold(st, target, EPISODE_GAP, mr) + MARGIN_SD * float(np.std(st))
    fa_events = fa_samples = 0
    for g in gs:
        s = stats["normal"][g]
        fa_events += count_alarm_episodes(s, thr[g], EPISODE_GAP, mr)
        fa_samples += len(s)
    delays, leak_at, missed = [], [], 0
    for sc in scen:
        t0, g = event_group(cfg, sc.labels)
        s = stats["ev"][sc.name][g]
        # 오경보는 누수가 있는 묶음만이 아니라 모든 묶음의 누수 시작 전 구간에서 센다 (한 묶음만 세면 문제 있는 묶음이 가려진다)
        for gg in gs:
            fa_events += count_alarm_episodes(stats["ev"][sc.name][gg][: max(t0, 1)], thr[gg], EPISODE_GAP, mr)
            fa_samples += t0
        a = first_alarm(s, thr[g], t0, mr)
        if a is None:
            missed += 1
            continue
        delays.append(a - t0)
        segs = sc.labels["groups"][g - 1]
        leak_at.append(float(sc.truth_leak[a, [x - 1 for x in segs]].sum()))
    return {
        "label": label, "detector": kind, "params": params,
        "false_alarms_per_14d_per_group": round(fa_events / (fa_samples / (14 * 1440)), 3),
        "detected": len(delays), "missed": missed, "n": len(scen),
        "median_delay_min": None if not delays else float(np.median(delays)),
        "p90_delay_min": None if not delays else float(np.percentile(delays, 90)),
        "median_leak_lpm_at_detection": None if not leak_at else round(float(np.median(leak_at)), 2),
    }


def evaluate(layout: str = "S-A", with_ae: bool = True, target: int = TARGET_FA_EPISODES_14D) -> dict:
    cfg = load_config()
    bl, tr = fit_baseline(layout)
    gs = groups_in(tr)
    scen = [load_eval(n, layout) for n in eval_names()]
    normal_df, _ = load_scenario("normal_opchange", layout)
    for g in gs:
        v = group_signals(tr, g)["imb_mass"].to_numpy()
        RAW_STAT[g] = (float(v.mean()), float(v.std()))

    base = {
        "train": {g: base_signals(tr, bl, g) for g in gs},
        "normal": {g: base_signals(normal_df, bl, g) for g in gs},
        "ev": {s.name: {g: base_signals(s.df, bl, g) for g in gs} for s in scen},
    }

    def transform(fn):
        return {
            "train": {g: fn(*base["train"][g]) for g in gs},
            "normal": {g: fn(*base["normal"][g]) for g in gs},
            "ev": {n: {g: fn(*v) for g, v in d.items()} for n, d in base["ev"].items()},
        }

    rows = []
    for lam in LAMBDAS:
        rows.append(_row(f"EWMA λ={lam}", "ewma", {"lam": lam}, transform(lambda z, i, r, l=lam: ewma(z, l)), scen, cfg, MIN_RUN["ewma"], target))
    for k in CUSUM_KS:
        rows.append(_row(f"CUSUM k={k}", "cusum", {"k": k}, transform(lambda z, i, r, kk=k: cusum(z, kk)), scen, cfg, MIN_RUN["cusum"], target))
    rows.append(_row("고정 임계값(보정)", "fixed", {}, transform(lambda z, i, r: i), scen, cfg, MIN_RUN["fixed"], target))
    # 기여도 분해: 평균만 내는 방법(60분 이동평균)과 운전점 보정을 뺀 EWMA (같은 오경보 기준)
    ma60 = lambda z, i, r: pd.Series(z).rolling(60, min_periods=1).mean().to_numpy()
    rows.append(_row("60분 이동평균(보정 있음)", "ma60", {"window": 60}, transform(ma60), scen, cfg, MIN_RUN["ewma"], target))
    rows.append(_row("EWMA λ=0.1 (운전점 보정 없음)", "ewma_raw", {"lam": 0.1}, transform(lambda z, i, r: ewma(r, 0.1)), scen, cfg, MIN_RUN["ewma"], target))
    rows.append(_row("60분 이동평균(보정 없음)", "ma60_raw", {"window": 60}, transform(lambda z, i, r: pd.Series(r).rolling(60, min_periods=1).mean().to_numpy()), scen, cfg, MIN_RUN["ewma"], target))

    # ---- ML 검출기: 앞 70%로 학습, 뒤 30%로 임계값 보정 ----------------------
    cut = int(len(tr) * (1 - HOLDOUT_FRAC))
    tr_fit, tr_hold = tr.iloc[:cut].reset_index(drop=True), tr.iloc[cut:].reset_index(drop=True)
    ml = {
        "Isolation Forest (잔차)": ("iforest", {"input": "residual"}, IForestDetector("residual").fit(tr_fit, bl, gs), True),
        "Isolation Forest (원시+운전조건)": ("iforest", {"input": "raw"}, IForestDetector("raw").fit(tr_fit, bl, gs), True),
    }
    if with_ae:
        from core.autoencoder import AEDetector
        ml["오토인코더 (운전조건 포함)"] = ("autoencoder", {"conditions": True}, AEDetector(True).fit(tr_fit, gs), False)
        ml["오토인코더 (원시 센서만)"] = ("autoencoder", {"conditions": False}, AEDetector(False).fit(tr_fit, gs), False)
    for label, (kind, params, det, needs_bl) in ml.items():
        sc_fn = (lambda df, g, d=det: d.score(df, bl, g)) if needs_bl else (lambda df, g, d=det: d.score(df, g))
        stats = {
            "train": {g: sc_fn(tr_hold, g) for g in gs},
            "normal": {g: sc_fn(normal_df, g) for g in gs},
            "ev": {s.name: {g: sc_fn(s.df, g) for g in gs} for s in scen},
        }
        # 임계값을 뒤 30%(4.2일)로 맞추므로 목표 사건 수는 0건
        rows.append(_row(label, kind, params, stats, scen, cfg, 1, 0))
    return {"layout": layout, "target_fa_episodes_per_14d": target, "rows": rows}


def print_table(res: dict) -> None:
    print(f"\n=== {res['layout']} (그룹당 정상 14일 오경보 목표 ≤{res['target_fa_episodes_per_14d']}건, 임계값 여유 +{MARGIN_SD}σ) ===")
    print(f"{'검출기':28s} {'오경보/14일':>10s} {'탐지':>7s} {'중앙지연':>8s} {'p90':>7s} {'탐지시 누수량':>12s}")
    for r in res["rows"]:
        md = "-" if r["median_delay_min"] is None else f"{r['median_delay_min']:.0f}분"
        p90 = "-" if r["p90_delay_min"] is None else f"{r['p90_delay_min']:.0f}"
        lk = "-" if r["median_leak_lpm_at_detection"] is None else f"{r['median_leak_lpm_at_detection']} L/min"
        print(f"{r['label']:28s} {r['false_alarms_per_14d_per_group']:10.2f} {r['detected']:3d}/{r['n']:<3d} {md:>8s} {p90:>7s} {lk:>12s}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ae", action="store_true")
    ap.add_argument("--layouts", nargs="+", default=["S-A", "S-B"])
    args = ap.parse_args()
    out = {}
    for layout in args.layouts:
        res = evaluate(layout, with_ae=not args.no_ae)
        out[layout] = res
        print_table(res)
    (DATA_DIR / "detector_tuning.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
