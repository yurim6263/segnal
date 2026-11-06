"""합성 데이터 생성 CLI.  python -m sim.generate [--layouts S-A S-B] [--eval-n 30]"""
from __future__ import annotations

import argparse
import time

import numpy as np

from .config import load_config
from .scenarios import default_specs, random_leak_spec, write_scenario


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layouts", nargs="+", default=["S-A", "S-B"])
    ap.add_argument("--eval-n", type=int, default=0, help="평가용 무작위 누수 시나리오 개수")
    ap.add_argument("--eval-events", type=int, default=0, help="평가용 막힘·펌프·센서 시나리오 종류별 개수")
    ap.add_argument("--eval-prior", type=int, default=0, help="사전확률 평가용 위험률 기반 누수 시나리오 개수(분포별)")
    args = ap.parse_args()

    cfg = load_config()
    t0 = time.time()
    for spec in default_specs():
        write_scenario(cfg, spec, tuple(args.layouts))
        print(f"  {spec.name}: {spec.n} samples")
    if args.eval_n:
        rng = np.random.default_rng([int(cfg.sim["seed"]), 12345])
        for i in range(args.eval_n):
            spec = random_leak_spec(f"eval_leak_{i:02d}", 100 + i, rng, cfg)
            write_scenario(cfg, spec, tuple(args.layouts))
        print(f"  eval_leak_00..{args.eval_n - 1:02d}")
    if args.eval_events:
        from .scenarios import random_event_spec
        rng = np.random.default_rng([int(cfg.sim["seed"]), 54321])
        for kind in ("clog", "pump", "sensor"):
            for i in range(args.eval_events):
                spec = random_event_spec(kind, f"eval_{kind}_{i:02d}", 300 + 100 * ("clog pump sensor".split().index(kind)) + i, rng, cfg)
                write_scenario(cfg, spec, tuple(args.layouts))
        print(f"  eval_clog/pump/sensor x{args.eval_events}")
    if args.eval_prior:
        import pandas as pd
        from .maintenance import generate_maintenance
        from .scenarios import DATA_DIR as _D, hazard_leak_spec
        rng = np.random.default_rng([int(cfg.sim["seed"]), 777])
        for tag, dist in (("w", "weibull"), ("l", "lognormal")):
            joints, _log = generate_maintenance(cfg, dist=None if dist == "weibull" else "lognormal")
            for i in range(args.eval_prior):
                spec = hazard_leak_spec(f"evalp_{tag}_{i:02d}", 600 + (0 if tag == "w" else 100) + i, rng, cfg, joints, dist)
                write_scenario(cfg, spec, tuple(args.layouts))
        print(f"  evalp_w/l x{args.eval_prior}")

    # 합성 정비 이력 (조인트 수명): CSV + SQLite
    from db import init_db
    from .maintenance import generate_maintenance, write_to_db
    from .scenarios import DATA_DIR

    for dist in (None, "lognormal"):
        joints, log = generate_maintenance(cfg, dist=dist)
        tag = "" if dist is None else f"_{dist}"
        joints.to_csv(DATA_DIR / f"joints{tag}.csv", index=False, float_format="%.5g")
        log.to_csv(DATA_DIR / f"maintenance_log{tag}.csv", index=False, float_format="%.5g")
        if dist is None:
            write_to_db(init_db(), joints, log)
    print(f"  joints: {len(joints)}, maintenance_log: {len(log)} (+ lognormal 변형)")
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
