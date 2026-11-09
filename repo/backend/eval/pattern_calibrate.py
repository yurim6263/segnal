"""구분 불가 기준 각도(AMBIGUOUS_DEG) 보정: 평가 시나리오와 다른 시드의 홀드아웃 100건(누수 60, 유량계 오프셋 40)으로 각도별 결과를 센다.

평가용 66건으로 맞추면 자기 채점이 되므로 따로 만든 시나리오를 쓴다. 기준: 오답이 2% 이하가 되는 가장 작은 각도.
실행: python -m eval.pattern_calibrate   결과: data/generated/pattern_calibration.json
"""
from __future__ import annotations

import json

import numpy as np

import core.pattern as P
from core.classify import DiagnosisModel
from core.normalize import groups_in
from eval.common import fit_baseline
from sim.config import load_config
from sim.scenarios import DATA_DIR, random_event_spec, random_leak_spec, sensors_for, simulate_spec


def holdout(cfg, n_leak: int = 60, n_sensor: int = 40):
    rng = np.random.default_rng(424242)
    data = []
    for i in range(n_leak):
        spec = random_leak_spec(f"cal_leak_{i}", 91000 + i, rng, cfg)
        truth, _ = simulate_spec(cfg, spec)
        df, _ = sensors_for(cfg, spec, truth, "S-A")
        data.append(("leak", df, spec.events(cfg)[0].start))
    k = 0
    while sum(1 for d in data if d[0] == "sensor") < n_sensor:
        k += 1
        spec = random_event_spec("sensor", f"cal_sens_{k}", 92000 + k, rng, cfg)
        ev = spec.events(cfg)[0]
        if ev.sensor_mode != "offset":      # 고착은 규칙으로 걸러지므로 방향 비교 대상이 아니다
            continue
        truth, _ = simulate_spec(cfg, spec)
        df, _ = sensors_for(cfg, spec, truth, "S-A")
        data.append(("sensor", df, ev.start))
    return data


def main() -> None:
    cfg = load_config()
    bl, tr = fit_baseline("S-A")
    gs = groups_in(tr)
    model = DiagnosisModel(bl, P.build_pattern_model(cfg, bl, gs)).fit(tr, gs)
    data = holdout(cfg)
    rows = []
    keep = P.AMBIGUOUS_DEG
    for delta in (0, 1, 2, 3, 4, 5, 6, 8, 10):
        P.AMBIGUOUS_DEG = delta
        res: dict[str, list[str]] = {}
        for truth, df, t0 in data:
            res.setdefault(truth, []).append(model.diagnose(df, gs, start=int(t0)).cause)
        row = {"delta_deg": delta}
        for truth, c in res.items():
            n = len(c)
            ok, amb = c.count(truth), c.count("ambiguous")
            unk = c.count("unknown")
            row[truth] = {"n": n, "correct": ok, "ambiguous": amb, "unknown": unk, "wrong": n - ok - amb - unk}
        rows.append(row)
        print(row, flush=True)
    P.AMBIGUOUS_DEG = keep
    chosen = next((r["delta_deg"] for r in rows if (r["leak"]["wrong"] + r["sensor"]["wrong"]) / (r["leak"]["n"] + r["sensor"]["n"]) <= 0.02), None)
    out = {"rows": rows, "chosen_delta_deg": chosen, "rule": "오답이 전체의 2% 이하가 되는 가장 작은 각도",
           "holdout": "누수 60건 + 유량계 오프셋 40건 (평가용 66건과 다른 시드), 합성 데이터"}
    (DATA_DIR / "pattern_calibration.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("chosen", chosen)


if __name__ == "__main__":
    main()
