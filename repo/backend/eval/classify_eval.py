"""11단계: 원인 분류 정확도 (누수·막힘·펌프·센서). 실행: python -m eval.classify_eval"""
from __future__ import annotations

import json
from collections import Counter

from core.classify import DiagnosisModel
from core.normalize import groups_in
from eval.common import fit_baseline
from sim.scenarios import DATA_DIR, load_scenario

TRUTH = {"eval_leak_": "leak", "eval_clog_": "clog", "eval_pump_": "pump", "eval_sensor_": "sensor"}


def names(prefix):
    return sorted(p.name.split("__")[0] for p in DATA_DIR.glob(f"{prefix}*__S-A.json"))


def evaluate(layout: str = "S-A") -> dict:
    bl, tr = fit_baseline(layout)
    gs = groups_in(tr)
    model = DiagnosisModel(bl).fit(tr, gs)
    conf: Counter = Counter()
    rows = []
    for prefix, truth in TRUTH.items():
        for n in names(prefix):
            df, labels = load_scenario(n, layout)
            t0 = int(labels["events"][0]["start_ts"])
            d = model.diagnose(df, gs, start=t0)
            pred = d.cause
            conf[(truth, pred)] += 1
            rows.append({"scenario": n, "truth": truth, "pred": pred, "alarm_delay_min": None if d.alarm_ts is None else d.alarm_ts - t0})
    # 정상 시나리오 오경보
    nop, _ = load_scenario("normal_opchange", layout)
    d_norm = model.diagnose(nop, gs)
    classes = ["leak", "clog", "pump", "sensor", "unknown"]
    per_class = {}
    for c in classes[:4]:
        tot = sum(conf[(c, p)] for p in classes)
        per_class[c] = {"n": tot, "correct": conf[(c, c)], "acc": round(conf[(c, c)] / tot, 3) if tot else None}
    total = sum(v["n"] for v in per_class.values())
    acc = sum(v["correct"] for v in per_class.values()) / total
    return {
        "layout": layout, "accuracy": round(acc, 3), "per_class": per_class,
        "confusion": {f"{t}->{p}": conf[(t, p)] for t in classes[:4] for p in classes if conf[(t, p)]},
        "normal_scenario_alarm": d_norm.cause != "unknown" or d_norm.alarm_ts is not None,
        "rows": rows,
    }


def main() -> None:
    res = evaluate("S-A")
    print(f"원인 분류 정확도(S-A): {res['accuracy']*100:.1f}%")
    for c, v in res["per_class"].items():
        print(f"  {c:7s} {v['correct']}/{v['n']}  ({v['acc']})")
    print("혼동:", res["confusion"])
    print("정상 3일에 경보:", res["normal_scenario_alarm"])
    (DATA_DIR / "classify_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
