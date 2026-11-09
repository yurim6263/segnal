"""세그먼트 수명·누수 원인 데이터 생성 CLI.  python -m sim.health_generate [--seed N] [--no-minute]

결과: data/health/*.csv (segments, installs, maintenance, leaks, segment_daily, water_quality, ops_events, sensor_1min, work_orders)
"""
from __future__ import annotations

import argparse
import json
import time

from . import health as H


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-minute", action="store_true", help="1분 센서 시계열을 만들지 않는다")
    a = ap.parse_args()
    t = time.time()
    out = H.simulate(seed=a.seed, with_minute=not a.no_minute)
    d = H.write(out)
    print(f"저장: {d} ({time.time() - t:.1f}s)")
    print(json.dumps(H.validate(out), ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
