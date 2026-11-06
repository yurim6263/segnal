"""API 계약의 예시(mock) JSON을 frontend/src/mock/ 에 만든다.

프론트엔드는 백엔드가 준비되기 전까지 이 mock으로 화면을 만든다. (실제 값이 아닌 합성 예시)
실행: python -m tools.make_mock   (backend 폴더에서)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from sim.config import load_config

OUT = Path(__file__).resolve().parents[2] / "frontend" / "src" / "mock"


def dump(name: str, obj) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(
        json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> None:
    cfg = load_config()
    rng = np.random.default_rng(1)

    dump("config", {
        "n_segments": cfg.n_segments,
        "sensor_groups": cfg.sensor_groups,
        "rolls_per_segment": cfg.rolls_per_segment,
        "joints_per_roll": cfg.joints_per_roll,
    })

    dump("scenarios", [
        {"id": "normal_opchange", "name": "정상 + 주조 속도 변경",
         "description": "누수 없음. 주조 속도와 강종이 바뀌어도 오경보가 없어야 한다.",
         "n_samples": 2880, "sensor_layout": "S-A"},
        {"id": "leak_ramp_s5", "name": "서서히 커지는 누수 (세그먼트 5)",
         "description": "6시간에 걸쳐 커지는 미세 누수. 고정 임계값은 늦게 감지한다.",
         "n_samples": 2880, "sensor_layout": "S-A"},
    ])

    gmap = {s: gi for gi, g in enumerate(cfg.sensor_groups) for s in g}
    leak_seg, leak_roll = 5, 4
    levels = []
    for s in range(1, cfg.n_segments + 1):
        lv = "alarm" if gmap[s] == gmap[leak_seg] else "normal"
        levels.append({"segment": s, "level": lv, "group": gmap[s]})

    cands = []
    raw = []
    for s in cfg.sensor_groups[gmap[leak_seg]]:
        for r in range(1, cfg.rolls_per_segment + 1):
            for side in ("in", "out"):
                raw.append((s, r, side, float(rng.gamma(2.0, 1.0))))
    tot = sum(x[3] for x in raw)
    raw.sort(key=lambda x: -x[3])
    for rank, (s, r, side, w) in enumerate(raw[:12], start=1):
        prob = w / tot
        insp = float(round(rng.uniform(10, 45), 1))
        risk = float(round(rng.uniform(0.1, 0.9), 2))
        cands.append({
            "id": f"S{s}-R{r}-{side}", "segment": s, "roll": r, "side": side,
            "prob": round(prob, 4), "prior": round(prob * 0.9, 4),
            "evidence": [f"묶음 {gmap[s]+1} 회수 유량 잔차 감소", "공급 헤더 압력 소폭 저하"],
            "rank": rank, "inspect_minutes": insp, "access_risk": risk,
            "priority_score": round(prob / (insp + 20 * risk), 5), "priority_rank": 0,
        })
    for pr, c in enumerate(sorted(cands, key=lambda c: -c["priority_score"]), start=1):
        c["priority_rank"] = pr

    dump("state", {
        "scenario_id": "leak_ramp_s5", "ts": 1620, "cast_speed": 1.25, "steel_grade": "A",
        "segments": levels,
        "alert": {
            "level": "alarm", "cause": "leak", "since_ts": 1510, "group": gmap[leak_seg],
            "message": "묶음 3의 회수 유량이 기준선보다 낮아지는 추세 (누수 후보)",
            "detectors": {"fixed_alarm_ts": None, "ewma_alarm_ts": 1510, "cusum_alarm_ts": 1498},
        },
        "candidates": cands,
        "impact": {"start_m": 3.1, "end_m": 5.6, "label": "슬래브 No.318 몰드 출구로부터 3.1~5.6 m 표면 검사 대상 후보"},
        "is_synthetic": True,
    })

    t = np.arange(0, 480)
    base = 1000 + 20 * np.sin(t / 80)
    leak = np.clip((t - 260) / 200, 0, None) * 12
    val = base - leak + rng.normal(0, 3, t.size)
    resid = val - base
    ewma = np.zeros_like(resid)
    cusum = np.zeros_like(resid)
    for i, x in enumerate(resid):
        ewma[i] = (0.25 * x + 0.75 * ewma[i - 1]) if i else 0.25 * x
        cusum[i] = max(0.0, (cusum[i - 1] if i else 0.0) - x - 1.5)
    dump("series", {
        "scenario_id": "leak_ramp_s5", "group": 2, "name": "묶음 3 회수 유량", "unit": "L/min",
        "points": [
            {"ts": int(ti), "value": round(float(v), 2), "baseline": round(float(b), 2),
             "residual": round(float(r), 2), "ewma": round(float(e), 3), "cusum": round(float(c), 3)}
            for ti, v, b, r, e, c in zip(t, val, base, resid, ewma, cusum)
        ],
        "ewma_limit": -4.5, "cusum_limit": 12.0, "fixed_limit": -200.0,
    })

    joints = []
    for s in range(1, cfg.n_segments + 1):
        for r in range(1, cfg.rolls_per_segment + 1):
            for side in ("in", "out"):
                age = float(rng.uniform(20, 400))
                joints.append({
                    "joint_id": f"S{s:02d}-R{r:02d}-{side}", "segment": s, "roll": r, "side": side,
                    "age_days": round(age, 1), "hazard": round(float(1 - np.exp(-(age / 500) ** 1.6 * 0.05)), 5),
                    "access_risk": round(float(rng.uniform(0.1, 0.9)), 2),
                    "inspect_minutes": round(float(rng.uniform(10, 45)), 1),
                    "replace_count": int(rng.integers(0, 3)),
                })
    dump("joints", joints)

    dump("eval_detectors", [
        {"detector": "고정 임계값(SAIL 예시)", "detection_delay_min": None, "false_alarms": 4, "note": "20% 편차 기준은 작은 누수를 못 잡음"},
        {"detector": "EWMA", "detection_delay_min": 112, "false_alarms": 1},
        {"detector": "CUSUM", "detection_delay_min": 98, "false_alarms": 1},
        {"detector": "Isolation Forest", "detection_delay_min": 140, "false_alarms": 1},
    ])
    dump("eval_priors", [
        {"prior": "none", "top1": 0.12, "top3": 0.31},
        {"prior": "uniform", "top1": 0.12, "top3": 0.31},
        {"prior": "weibull", "top1": 0.26, "top3": 0.52},
        {"prior": "mismatch", "top1": 0.19, "top3": 0.41},
    ])
    dump("handover", {"text": "(예시) 묶음 3에서 회수 유량이 기준선보다 낮아지는 추세가 감지되었습니다. 점검 순서는 후보 목록을 따르세요.", "generated_by": "template"})
    dump("ask", {"answer": "(예시) 묶음 3의 회수 유량 잔차가 기준선보다 낮아져 EWMA가 경보를 냈습니다.", "tools_used": ["get_status", "get_residual_trend"], "numbers_verified": True, "from_cache": True,
                 "disclaimer": "AI가 작성한 내용이며 사람의 확인이 필요합니다."})
    print("mock written to", OUT)


if __name__ == "__main__":
    main()
