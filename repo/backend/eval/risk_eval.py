"""위험 모델 백테스트 (기획서 5-3): 정지일마다 '그때까지의 데이터만'으로 모델을 다시 맞추고, 이후 14일의 매일 위험을 실제 누수와 비교한다.

  python -m eval.risk_eval          # 결과를 data/health/risk_eval.json 에 저장하고 요약을 출력
- 일 단위 평가: 세그먼트·일마다 '다음 하루 안에 누수가 날 확률'을 매기고 실제 누수 여부와 비교(AUC). 비교 대상은 현행 기준(교체 후 누적 톤수)이다.
- 매일 상위 3개 포착률: 그날 13개 세그먼트 중 모델 상위 3개 안에 실제 누수가 있었는지.
- 진동·베어링 온도 신호를 뺀 모델(use_vib=False)과 비교해 베어링 센서(온도·진동) 제거 민감도를 본다.
모든 수치는 합성 데이터 기준이며, 누수 건수가 적어(약 30건) 구간 추정이 넓다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from core import risk

HORIZON = 14
FIRST_FOLD_STOP = 12          # 처음 12번의 정지(약 170일)는 학습에만 쓴다
OUT = Path(__file__).resolve().parents[2] / "data" / "health" / "risk_eval.json"


def auc(score: np.ndarray, y: np.ndarray) -> float:
    pos, neg = score[y == 1], score[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    gt = (pos[:, None] > neg[None, :]).sum() + 0.5 * (pos[:, None] == neg[None, :]).sum()
    return float(gt / (len(pos) * len(neg)))


def _boot_diff(score_a, score_b, y, n=300, seed=1):
    rng = np.random.default_rng(seed)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    diffs = []
    for _ in range(n):
        ip, ineg = rng.choice(pos, len(pos)), rng.choice(neg, min(len(neg), 1500))
        idx = np.concatenate([ip, ineg])
        yy = y[idx]
        diffs.append(auc(score_a[idx], yy) - auc(score_b[idx], yy))
    return [round(float(np.percentile(diffs, 5)), 3), round(float(np.percentile(diffs, 95)), 3)]


def walk_forward(rows: pd.DataFrame, stops: list[int], n_days: int, use_vib: bool = True) -> pd.DataFrame:
    out = []
    for s in [x for x in stops if x + HORIZON <= n_days][FIRST_FOLD_STOP:]:
        m = risk.fit(rows[rows["day"] < s], use_vib=use_vib)
        te = rows[(rows["day"] >= s) & (rows["day"] < s + HORIZON)].copy()
        te = te.join(m.predict(te, 1.0, 7000.0))
        te["fold_stop"] = s
        out.append(te)
    t = pd.concat(out, ignore_index=True)
    t["y"] = (t["event"] != "").astype(int)
    t["rank_model"] = t.groupby("day")["prob"].rank(ascending=False, method="first")
    t["rank_tons"] = t.groupby("day")["t0"].rank(ascending=False, method="first")
    return t


def summarize(t: pd.DataFrame) -> dict:
    y = t["y"].to_numpy()
    n_ev = int(y.sum())
    res = {
        "rows": int(len(t)), "leaks": n_ev,
        "auc_model": round(auc(t["prob"].to_numpy(), y), 3), "auc_tons_order": round(auc(t["t0"].to_numpy(), y), 3),
        "auc_diff_90ci": _boot_diff(t["prob"].to_numpy(), t["t0"].to_numpy(), y),
        "top3_daily_capture_model": round(float(t[t["rank_model"] <= 3]["y"].sum() / max(n_ev, 1)), 3),
        "top3_daily_capture_tons": round(float(t[t["rank_tons"] <= 3]["y"].sum() / max(n_ev, 1)), 3),
        "top3_daily_capture_random": round(3 / 13, 3),
        "pred_total": round(float(t["prob"].sum()), 1),
    }
    q = pd.qcut(t["prob"].rank(method="first"), 5, labels=False)
    res["calibration"] = [{"bin": int(b), "pred_mean": round(float(g["prob"].mean()), 5), "obs_rate": round(float(g["y"].mean()), 5), "n": int(len(g)), "leaks": int(g["y"].sum())} for b, g in t.groupby(q)]
    per = []
    for c in risk.CAUSES:
        sub = t[(t["event"] == c) | (t["event"] == "")]
        k = int((sub["event"] == c).sum())
        if k:
            yy = (sub["event"] == c).astype(int).to_numpy()
            per.append({"cause": c, "n": k, "auc_model": round(auc(sub["prob"].to_numpy(), yy), 3), "auc_tons_order": round(auc(sub["t0"].to_numpy(), yy), 3)})
    res["per_cause_auc"] = per
    hit = t[t["y"] == 1]
    res["cause_top1_acc"] = round(float((hit["top_cause"] == hit["event"]).mean()), 3) if len(hit) else None
    res["cause_confusion"] = [{"true": a, "pred": b, "n": int(n)} for (a, b), n in hit.groupby(["event", "top_cause"]).size().items()]
    return res


def run() -> dict:
    data = risk.load()
    rows = risk.build_rows(data, future=False)
    res = {"with_vibration": summarize(walk_forward(rows, data.stops, data.n_days, True)),
           "no_bearing_sensor": summarize(walk_forward(rows, data.stops, data.n_days, False))}
    full = risk.fit(rows)
    res["coefficients"] = risk.describe(full)
    res["beta_by_cause"] = [{k: (float(v) if isinstance(v, (np.floating,)) else v) for k, v in risk.beta_by_cause(rows, c).items()} for c in ("WEAR", "ASSEMBLY", "RANDOM", "HAMMER")]
    res["note"] = ("합성 데이터. 누수 약 30건이라 구간 추정이 넓다. 일 단위 평가이며, 정지 때마다 그 시점까지의 데이터로 다시 맞춘 뒤 이후 14일을 평가했다. "
                   "와이블 β는 공변량 없이 교체 후 누적 톤수 기준.")
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    r = run()
    for k in ("with_vibration", "no_bearing_sensor"):
        v = r[k]
        print(f"[{k}] 행 {v['rows']}, 누수 {v['leaks']}건, 예측 합계 {v['pred_total']}")
        print(f"  AUC 모델 {v['auc_model']} / 톤수순 {v['auc_tons_order']} (차이 90% 범위 {v['auc_diff_90ci']})")
        print(f"  매일 상위3 포착 모델 {v['top3_daily_capture_model']} / 톤수순 {v['top3_daily_capture_tons']} / 무작위 {v['top3_daily_capture_random']}")
        print(f"  원인별 AUC {v['per_cause_auc']}")
        print(f"  원인 1순위 정확도 {v['cause_top1_acc']}")
    print("원인별 β", r["beta_by_cause"])
