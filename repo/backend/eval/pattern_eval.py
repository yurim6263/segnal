"""원인 구분(다신호 방향 비교) 평가: 정상 구간 오분류율과 유량계 표류의 영향. 옛 규칙과 나란히 비교한다.

정상 운전(누수 없음) 3일짜리 30회(서로 다른 시드)를 돌려, 서비스와 같은 방식(diagnose_final)으로 판정했을 때
"원인이 확정된" 비율과 종류를 센다. 유량계 표류 크기를 0·현재·2배로 바꿔 본다(표류 크기는 현장에서 모르는 값).
실행: python -m eval.pattern_eval [--runs 30]   결과: data/generated/pattern_eval.json
"""
from __future__ import annotations

import argparse
import copy
import json
from collections import Counter

from core.classify import DiagnosisModel
from core.normalize import groups_in
from core.pattern import build_pattern_model
from eval.common import fit_baseline
from sim.config import load_config
from sim.scenarios import DATA_DIR, DAY, ScenarioSpec, sensors_for, simulate_spec

DRIFT_SCALES = [(0.0, "표류 0"), (1.0, "현재 설정"), (2.0, "표류 2배")]


def normal_runs(cfg, n: int, seed0: int):
    for i in range(n):
        spec = ScenarioSpec(f"pe_norm_{i}", "정상", 3 * DAY, seed0 + i, lambda c: [])
        truth, _ = simulate_spec(cfg, spec)
        df, _ = sensors_for(cfg, spec, truth, "S-A")
        yield df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=30)
    a = ap.parse_args()
    base_cfg = load_config()
    bl, tr = fit_baseline("S-A")
    gs = groups_in(tr)
    models = {"옛 규칙": DiagnosisModel(bl).fit(tr, gs),
              "다신호 방향 비교": DiagnosisModel(bl, build_pattern_model(base_cfg, bl, gs)).fit(tr, gs)}
    out = {"runs_per_setting": a.runs, "days_per_run": 3, "rows": []}
    for scale, label in DRIFT_SCALES:
        cfg = copy.deepcopy(base_cfg)
        cfg.sim["sensor"]["flow_drift_rel_per_sqrt_day"] *= scale
        dfs = list(normal_runs(cfg, a.runs, 93000))
        row = {"drift_scale": scale, "label": label}
        for name, model in models.items():
            cnt: Counter = Counter()
            for df in dfs:
                d = model.diagnose_final(df, gs)
                cnt["none" if d.alarm_ts is None else d.cause] += 1
            confirmed = sum(v for k, v in cnt.items() if k not in ("none", "unknown"))
            row[name] = {"counts": dict(cnt), "confirmed_false_rate": round(confirmed / a.runs, 3)}
        out["rows"].append(row)
        print(label, {k: v for k, v in row.items() if k not in ("drift_scale", "label")}, flush=True)
    (DATA_DIR / "pattern_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
