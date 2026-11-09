"""11단계: 원인 분류 정확도 (누수·막힘·펌프·센서). 실행: python -m eval.classify_eval"""
from __future__ import annotations

import json
from collections import Counter

from core.classify import DiagnosisModel
from core.normalize import groups_in
from core.pattern import build_pattern_model
from sim.config import load_config
from eval.common import fit_baseline
from sim.scenarios import DATA_DIR, load_scenario

TRUTH = {"eval_leak_": "leak", "eval_clog_": "clog", "eval_pump_": "pump", "eval_sensor_": "sensor"}


def names(prefix):
    return sorted(p.name.split("__")[0] for p in DATA_DIR.glob(f"{prefix}*__S-A.json"))


def evaluate(layout: str = "S-A", use_pattern: bool = True) -> dict:
    bl, tr = fit_baseline(layout)
    gs = groups_in(tr)
    model = DiagnosisModel(bl, build_pattern_model(load_config(), bl, gs, layout) if use_pattern else None).fit(tr, gs)
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
    classes = ["leak", "clog", "pump", "sensor", "ambiguous", "unknown"]
    per_class = {}
    for c in classes[:4]:
        tot = sum(conf[(c, p)] for p in classes)
        amb, unk = conf[(c, "ambiguous")], conf[(c, "unknown")]
        per_class[c] = {"n": tot, "correct": conf[(c, c)], "ambiguous": amb, "unknown": unk,
                        "wrong": tot - conf[(c, c)] - amb - unk,
                        "acc": round(conf[(c, c)] / tot, 3) if tot else None}
    total = sum(v["n"] for v in per_class.values())
    acc = sum(v["correct"] for v in per_class.values()) / total
    return {
        "layout": layout, "method": "pattern" if use_pattern else "rule", "accuracy": round(acc, 3), "per_class": per_class,
        "confusion": {f"{t}->{p}": conf[(t, p)] for t in classes[:4] for p in classes if conf[(t, p)]},
        "normal_scenario_alarm": d_norm.cause != "unknown" or d_norm.alarm_ts is not None,
        "rows": rows,
    }


def main() -> None:
    import sys
    old = evaluate("S-A", use_pattern=False)
    print(f"[옛 규칙] 정확도 {old['accuracy']*100:.1f}%  혼동 {old['confusion']}")
    res = evaluate("S-A", use_pattern=True)
    res["previous_rule"] = {"accuracy": old["accuracy"], "per_class": old["per_class"], "confusion": old["confusion"]}
    print(f"원인 분류 정확도(S-A): {res['accuracy']*100:.1f}%")
    for c, v in res["per_class"].items():
        print(f"  {c:7s} 정답 {v['correct']}/{v['n']}  구분불가 {v['ambiguous']}  미상 {v['unknown']}  오답 {v['wrong']}")
    print("혼동:", res["confusion"])
    print("정상 3일에 경보:", res["normal_scenario_alarm"])
    (DATA_DIR / "classify_eval.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
