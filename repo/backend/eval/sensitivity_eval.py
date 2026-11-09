"""16단계: 조건이 바뀔 때의 민감도 평가 (B12).

기준 시스템(정상 14일로 기준선을 만들고 임계값을 맞춘 것)은 그대로 두고, 평가 시나리오의 조건만 바꿔서 같은 지표를 다시 잡는다.
따라서 '조건이 바뀌었는데 다시 맞추지 않은' 경우의 강건성이다. 같은 시드의 누수(위치·시작 시각)를 쓰므로 조건끼리 짝지어 비교된다.

지표
 - 감지까지 걸린 시간: 누수 시작 → 우리 방식(EWMA λ=0.1) 경보, 중앙값(놓친 건수는 따로)
 - 오경보: 누수 시작 전 구간에서 경보 사건 수 (14일·묶음당)
 - 상위 3개 적중률: 경보 60분 뒤 시점의 세그먼트 후보 상위 3개에 정답 세그먼트가 있는 비율
 - 점검 횟수: 후보 확률 순서 + 점검 결과 반영(세그먼트 단위, UI와 같음)으로 누수를 찾을 때까지의 평균 점검 수
   (점검이 누수를 찾아낼 확률 90%, 누수 아닌 곳을 '누수'로 잘못 볼 확률 2% 가정)

조건: 기준 / 누수 작게·크게 / 센서 잡음 ×2·×4 / 유량계 오프셋 ×3 / 센서 드리프트 ×6 / 센서 고장 동시 발생 /
       운전 조건 변동 크게 / 누수 두 곳 / 점검 결과를 잘못 입력(10%·25%)

실행: python -m eval.sensitivity_eval [--n 20]
"""
from __future__ import annotations

import argparse
import copy
import json
import zlib

import numpy as np
import pandas as pd

from core.detect import count_alarm_episodes, ewma, first_alarm, recenter
from core.lifetime import collect_lives, fit_weibull, prior_from_fit
from core.locate import WINDOW, apply_segment_inspection, observed_vector, rank_candidates
from core.normalize import groups_in
from core.signature import build_signatures
from eval.common import EPISODE_GAP, MARGIN_SD, calibrate_threshold, fit_baseline
from eval.localize_eval import DIAG_DELAY, LAM
from sim.config import load_config
from sim.scenarios import DATA_DIR, DAY, ScenarioSpec, _leak, labels_for, sensors_for, simulate_spec
from sim.circuit import Event

SENS, FALSE_POS, ACC = 0.9, 0.02, 0.9


def leak_params(rng, cfg, peak_range):
    seg = int(rng.integers(1, cfg.n_segments + 1))
    roll = int(rng.integers(1, cfg.rolls_per_segment + 1))
    side = str(rng.choice(["in", "out"]))
    peak = float(rng.uniform(*peak_range))
    ramp = int(rng.choice([0, 2 * 60, 6 * 60, 12 * 60]))
    start = int(DAY + rng.integers(2 * 60, 14 * 60))
    return seg, roll, side, peak, ramp, start


def make_case(cfg, i: int, cond: dict, seed_base: int = 9000):
    """같은 i에서는 조건이 달라도 누수 위치·시작 시각이 같다(짝지은 비교)."""
    rng = np.random.default_rng([int(cfg.sim["seed"]), seed_base, i])
    seg, roll, side, peak, ramp, start = leak_params(rng, cfg, cond.get("peak_range", (6.0, 30.0)))
    leaks = [(seg, roll, side, peak, ramp, start)]
    if cond.get("two_leaks"):
        # 정답이 둘이 되도록 다른 계측 묶음에 두 번째 누수 (1~2시간 뒤 시작)
        groups = cfg.sensor_groups
        g0 = next(k for k, g in enumerate(groups) if seg in g)
        others = [s for k, g in enumerate(groups) if k != g0 for s in g]
        s2 = int(rng.choice(others))
        leaks.append((s2, int(rng.integers(1, cfg.rolls_per_segment + 1)), str(rng.choice(["in", "out"])),
                      float(rng.uniform(6.0, 30.0)), ramp, start + int(rng.integers(60, 120))))
    extra = []
    if cond.get("sensor_fault"):
        g0 = next(k for k, g in enumerate(cfg.sensor_groups) if seg in g)
        gi = int(rng.choice([k for k in range(len(cfg.sensor_groups)) if k != g0]))
        extra.append(Event(kind="sensor", start=DAY, sensor_group=gi, sensor_name=str(rng.choice(["flow_in", "flow_out"])),
                           sensor_mode="offset", sensor_value=float(rng.choice([-1, 1]) * rng.uniform(0.02, 0.05))))
    spec = ScenarioSpec(
        f"sens_{i:02d}", "민감도 평가", 3 * DAY, 9000 + i,
        lambda c, L=tuple(leaks), E=tuple(extra): [_leak(l[0], l[1], l[2], l[5], l[3], l[4]) for l in L] + list(E),
    )
    return spec, leaks


def variant_cfg(base, cond: dict):
    cfg = copy.deepcopy(base)
    sp = cfg.sim["sensor"]
    for k, m in cond.get("sensor_scale", {}).items():
        sp[k] = sp[k] * m
    for k, v in cond.get("sim_set", {}).items():
        cfg.sim[k] = v
    return cfg


CONDITIONS = [
    ("base", "기준 (조건 변경 없음)", {}),
    ("small", "누수 작게 (3~6 L/min)", {"peak_range": (3.0, 6.0)}),
    ("large", "누수 크게 (30~60 L/min)", {"peak_range": (30.0, 60.0)}),
    ("noise2", "센서 잡음 ×2", {"sensor_scale": {"flow_noise_rel": 2, "pressure_noise_bar": 2, "temp_noise_c": 2}}),
    ("noise4", "센서 잡음 ×4", {"sensor_scale": {"flow_noise_rel": 4, "pressure_noise_bar": 4, "temp_noise_c": 4}}),
    ("offset3", "유량계 오프셋 ×3", {"sensor_scale": {"flow_offset_rel": 3}}),
    ("drift6", "센서 드리프트 ×6", {"sensor_scale": {"flow_drift_rel_per_sqrt_day": 6}}),
    ("fault", "다른 묶음 센서 고장이 동시에 있음", {"sensor_fault": True}),
    ("opvar", "운전 조건 변동 크게 (속도 3~6시간마다 ±0.25~0.5)",
     {"sim_set": {"op_hold_hours": (3, 6), "op_step_range": (0.25, 0.5), "op_speed_max": 1.8}}),
    ("two", "누수가 두 곳", {"two_leaks": True}),
    ("wrong10", "점검 결과를 잘못 입력 (10%)", {"wrong_input": 0.10}),
    ("wrong25", "점검 결과를 잘못 입력 (25%)", {"wrong_input": 0.25}),
]


def inspect_count(prob0, segments, truth_segs, n_seg, rng, wrong=0.0):
    """세그먼트 단위 점검: 확률 순서, 점검 결과 반영, 이미 본 곳은 다시 보지 않는다. (횟수, 찾았는가)"""
    p = prob0.copy()
    seen = set()
    for step in range(n_seg):
        sp = {}
        for s, q in zip(segments, p):
            sp[int(s)] = sp.get(int(s), 0.0) + float(q)
        cand = [s for s in sp if s not in seen]
        if not cand:
            break
        s = max(cand, key=lambda x: sp[x])
        seen.add(s)
        is_leak = s in truth_segs
        saw_leak = (rng.random() < SENS) if is_leak else (rng.random() < FALSE_POS)
        if rng.random() < wrong:       # 사람이 결과를 반대로 입력
            saw_leak = not saw_leak
        if saw_leak:
            return step + 1, bool(is_leak)
        p = apply_segment_inspection(p, segments, s, "no_issue", ACC)
    return n_seg, False


def evaluate(n: int, layout: str = "S-A") -> dict:
    base_cfg = load_config()
    bl, tr = fit_baseline(layout)
    gs = groups_in(tr)
    sigs = build_signatures(base_cfg, bl, layout)
    jw = pd.read_csv(DATA_DIR / "joints.csv"); lw = pd.read_csv(DATA_DIR / "maintenance_log.csv")
    fit = fit_weibull(*collect_lives(jw, lw))
    pr = prior_from_fit(fit, jw, float(base_cfg.sim["maintenance"]["hazard_window_days"]))
    by_id = dict(zip(jw.joint_id, pr))
    prior = np.array([by_id[j] for j in sigs.joint_ids]); prior /= prior.sum()

    thr = {}
    for g in gs:
        st = ewma(recenter(bl.residuals(tr, g)["z_imb_mass"].to_numpy()), LAM)
        thr[g] = calibrate_threshold(st, 1, EPISODE_GAP, 1) + MARGIN_SD * float(np.std(st))

    rows = []
    for key, label, cond in CONDITIONS:
        cfg = variant_cfg(base_cfg, cond)
        rng_i = np.random.default_rng([7, zlib.crc32(key.encode()) % 1000])
        delays, missed, fa_events, fa_samples, hits, insp_n, insp_ok = [], 0, 0, 0, [], [], []
        for i in range(n):
            spec, leaks = make_case(base_cfg, i, cond)       # 누수 위치·크기는 기준 설정으로 뽑아 조건끼리 같게 한다
            truth, _ = simulate_spec(cfg, spec)
            df, groups = sensors_for(cfg, spec, truth, layout)
            stats = {g: ewma(recenter(bl.residuals(df, g)["z_imb_mass"].to_numpy()), LAM) for g in gs}
            t0 = min(l[5] for l in leaks)
            for g in gs:
                fa_events += count_alarm_episodes(stats[g][: max(t0, 1)], thr[g], EPISODE_GAP, 1)
                fa_samples += t0
            true_segs = {l[0] for l in leaks}
            alarms = []
            for (seg, _r, _s, _p, _rp, st0) in leaks:
                g = next(k for k, gr in enumerate(groups) if seg in gr) + 1
                a = first_alarm(stats[g], thr[g], st0)
                if a is None:
                    missed += 1
                else:
                    delays.append(a - st0)
                    alarms.append(a)
            if not alarms:
                continue
            t_d = min(min(alarms) + DIAG_DELAY, len(df) - 1)
            post = rank_candidates(sigs, observed_vector(df, bl, gs, t_d, WINDOW), prior)
            sp = post.segment_prob()
            top3 = sorted(sp, key=sp.get, reverse=True)[:3]
            hits.append(bool(true_segs & set(top3)))
            for _ in range(10):
                c, ok = inspect_count(post.prob, post.segments, true_segs, base_cfg.n_segments, rng_i, cond.get("wrong_input", 0.0))
                insp_n.append(c); insp_ok.append(ok)
        n_leaks = len(delays) + missed
        rows.append({
            "key": key, "label": label, "n_cases": n, "n_leaks": n_leaks, "missed": missed,
            "median_delay_min": None if not delays else float(np.median(delays)),
            "false_alarms_per_14d_per_group": round(fa_events / (fa_samples / (14 * 1440)), 2) if fa_samples else None,
            "top3_hit": None if not hits else round(float(np.mean(hits)), 3),
            "mean_inspections": None if not insp_n else round(float(np.mean(insp_n)), 2),
            "inspection_success": None if not insp_ok else round(float(np.mean(insp_ok)), 3),
        })
        r = rows[-1]
        print(f"{label:34s} 지연 {r['median_delay_min']!s:>6}분 놓침 {r['missed']:2d}/{r['n_leaks']:<2d} 오경보 {r['false_alarms_per_14d_per_group']!s:>5} "
              f"top3 {r['top3_hit']!s:>5} 점검 {r['mean_inspections']!s:>5}회 성공 {r['inspection_success']!s:>5}", flush=True)
    return {"layout": layout, "n_cases": n, "rows": rows,
            "note": "기준 시스템은 그대로 두고(재보정 없음) 조건만 바꿔 측정. 합성 데이터, 임계값은 가설."}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--layouts", nargs="+", default=["S-A"])
    ap.add_argument("--only", nargs="+", default=None, help="조건 키만 실행")
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()
    if args.only:
        CONDITIONS[:] = [c for c in CONDITIONS if c[0] in args.only]
    out = {}
    for layout in args.layouts:
        print(f"\n=== {layout} (n={args.n}) ===")
        out[layout] = evaluate(args.n, layout)
    if not args.no_save:
        (DATA_DIR / "sensitivity_eval.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
