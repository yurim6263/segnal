"""D 연구: 누수와 센서 오차(표류)·막힘·펌프 이상을 여러 신호의 '지문'으로 구분할 수 있는가.

운영 코드는 바꾸지 않는 연구용 스크립트다. 질문은 다섯 가지다.
 1) 고장마다 9개 신호(불균형, 입구·출구 질량유량, 공급·회수 압력, 온도차, 출구 온도, 다른 묶음의 입구 유량·공급 압력)의
    기준선 잔차가 어떤 방향으로 움직이는가(지문).
 2) 같은 크기(묶음 유량의 %)의 '유량계 오차'와 '누수'를 구분할 수 있는가. 어느 채널을 더하면 구분이 되는가(절제 실험).
 3) 구분하는 데 관측 시간이 얼마나 필요한가(창 길이 60·180·360분).
 4) 공급 유량이 밸브로 제어되는 회로(현장에서 가능한 구조)에서는 지문이 어떻게 바뀌는가.
 5) 구분 능력이 시뮬레이터의 펌프 곡선 가정(헤더 압력이 유량에 얼마나 민감한가)에 얼마나 기대는가.

측정: 고장을 묶음 하나에 주입(시각 T0, 계단형)하고, 발생 전(PRE)과 후(POST) 기준선 잔차 평균의 차이를 벡터로 만든다.
정상 시나리오에서 같은 방식으로 뽑은 벡터의 공분산으로 잡음을 정하고(백색화), 고장별 방향에 투영하는 방향 일치 분류기로 판정한다.
기존 규칙(입구 질량유량이 3σ 넘게 오르면 누수, 아니면 센서·기타)과 비교한다.

실행: python -m eval.discrimination_study [--reps 5]   결과: data/generated/discrimination_study.json
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import time
from itertools import combinations

import numpy as np

import core.baseline as B
from core.normalize import group_signals
from sim.circuit import Event, _first_order_lag, simulate_truth, water_density
from sim.config import load_config
from sim.scenarios import DATA_DIR, DAY, ScenarioSpec, _leak, sensors_for, simulate_spec

EXT = ["imb_mass", "m_in", "m_out", "p_in", "p_out", "dt", "t_out"]      # 기준선을 학습하는 채널
CH = EXT + ["oth_m_in", "oth_p_in"]                                      # 벡터 9차원(마지막 둘은 다른 묶음 평균)
B.CHANNELS = EXT            # 연구 전용: 기준선을 7개 채널로 학습한다(운영 코드의 채널 목록은 그대로)

T0 = DAY
PRE = (700, 1300)
POST_START = T0 + 180
N_SAMPLES = 3 * DAY
GROUPS = (3, 5)
WINDOWS = (60, 180, 360)

SUBSETS = {
    "A 불균형+입구유량(기존 규칙이 보는 것)": ["imb_mass", "m_in"],
    "B +출구유량": ["imb_mass", "m_in", "m_out"],
    "C +공급·회수 압력": ["imb_mass", "m_in", "m_out", "p_in", "p_out"],
    "D +온도(온도차·출구)": ["imb_mass", "m_in", "m_out", "dt", "t_out"],
    "E +다른 묶음(입구유량·공급압력)": ["imb_mass", "m_in", "m_out", "oth_m_in", "oth_p_in"],
    "F 전부": CH,
}
PCTS = [0.005, 0.01, 0.02]      # 묶음 유량 대비 비율(누수량과 유량계 오차 모두)


# ---- 공급 유량 제어 변형 ----------------------------------------------------
def controlled_truth(cfg, op, events):
    rng = np.random.default_rng(0)
    t_leak = simulate_truth(cfg, op, events, rng)
    t_nom = simulate_truth(cfg, op, [e for e in events if e.kind != "leak"], rng)
    sim = cfg.sim
    N = cfg.n_segments
    dt_min = sim["dt_s"] / 60.0
    q0 = np.array(sim["nominal_flow_lpm"], dtype=float)
    ql = t_leak.q_leak
    q_set = t_nom.q_in
    qb = np.maximum(q_set - ql, 0.0)
    slope = float(sim["heat_profile_slope"])
    w = 1.0 - slope * np.arange(N)
    dT_nom = float(sim["delta_t_nom_c"]) * w / w[0]
    gf = np.array([sim["grade_heat_factor"][g] for g in op.grade], dtype=float)
    heat_rel = (op.speed / float(sim["v_nom"])) ** float(sim["heat_speed_exponent"]) * gf
    flow_rel = np.maximum(qb / q0[None, :], 0.2)
    tau = float(sim["holdup_tau_min"]) / dt_min
    d_t = _first_order_lag(dT_nom[None, :] * heat_rel[:, None] / flow_rel, tau)
    t_out = op.t_in[:, None] + d_t
    q_out_equiv = _first_order_lag(qb, tau)
    q_out_vol = q_out_equiv * (water_density(op.t_in)[:, None] / water_density(t_out))
    return dataclasses.replace(t_leak, q_in=q_set, q_leak=ql, q_out_equiv=q_out_equiv, q_out_vol=q_out_vol,
                               p_header=t_nom.p_header, p_out_seg=t_nom.p_out_seg, t_out=t_out)


# ---- 고장 정의 ----------------------------------------------------------------
def group_flow(cfg, g):
    return float(sum(cfg.sim["nominal_flow_lpm"][s - 1] for s in cfg.sensor_groups[g - 1]))


def fault_events(cfg, group, label, size):
    """size: 유량 계열(누수·유량계)은 묶음 유량 대비 비율, 압력은 bar, 온도는 ℃, 막힘·펌프는 기존 배수."""
    segs = cfg.sensor_groups[group - 1]
    g0 = group - 1
    kind, _, sign = label.partition("|")
    s = -1.0 if sign == "-" else 1.0
    if kind == "leak":
        return [_leak(segs[0], 5, sign or "in", T0, size * group_flow(cfg, group), 0)]
    if kind == "clog":
        return [Event(kind="clog", start=T0, ramp=0, segment=segs[0], peak=size)]
    if kind == "pump":
        return [Event(kind="pump", start=T0, ramp=0, peak=size)]
    return [Event(kind="sensor", start=T0, sensor_group=g0, sensor_name=kind, sensor_mode="offset", sensor_value=s * size)]


LABELS_ALL = {
    "leak|in": PCTS, "leak|out": PCTS,
    "flow_in|+": PCTS, "flow_in|-": PCTS, "flow_out|+": PCTS, "flow_out|-": PCTS,
    "p_in|+": [0.1], "p_in|-": [0.1], "p_out|+": [0.1], "p_out|-": [0.1],
    "t_in|+": [0.5], "t_in|-": [0.5], "t_out|+": [0.5], "t_out|-": [0.5],
    "clog": [0.5, 1.0], "pump": [0.15, 0.3],
}
LABELS_FLOW = {k: v for k, v in LABELS_ALL.items() if k.startswith(("leak", "flow_"))}
IMB_CLASSES = ["leak", "flow_in|+", "flow_in|-", "flow_out|+", "flow_out|-"]


def merged(label):
    return "leak" if label.startswith("leak") else label


class Seeds:
    def __init__(self, base): self.n = base
    def next(self): self.n += 1; return self.n


def make_df(cfg, events_fn, seed, controlled, n=N_SAMPLES, layout="S-A"):
    spec = ScenarioSpec(f"disc_{seed}", "연구", n, seed, events_fn)
    truth, op = simulate_spec(cfg, spec)
    if controlled:
        truth = controlled_truth(cfg, op, spec.events(cfg))
    df, _ = sensors_for(cfg, spec, truth, layout)
    return df


def zmatrix(bl, df, g, all_groups):
    """(T, 9) 기준선 잔차 z. 마지막 둘은 다른 묶음의 입구 질량유량·공급 압력 평균."""
    r = bl.residuals(df, g)
    cols = [r[f"z_{c}"].to_numpy() for c in EXT]
    oth = [h for h in all_groups if h != g]
    om = np.mean([bl.residuals(df, h)["z_m_in"].to_numpy() for h in oth], axis=0)
    op_ = np.mean([bl.residuals(df, h)["z_p_in"].to_numpy() for h in oth], axis=0)
    return np.column_stack(cols + [om, op_])


def vec(Z, post):
    return Z[post[0]:post[1]].mean(axis=0) - Z[PRE[0]:PRE[1]].mean(axis=0)


def whitener(X, shrink=0.2):
    C = np.cov(X.T)
    C = (1 - shrink) * C + shrink * np.diag(np.diag(C))
    vals, vecs = np.linalg.eigh(C)
    return vecs @ np.diag(1.0 / np.sqrt(np.maximum(vals, 1e-12))) @ vecs.T, C


def fit_baseline_for(cfg, seed):
    df = make_df(cfg, lambda c: [], seed, False, n=10 * DAY)
    return B.Baseline().fit(df)


def run_variant(cfg, bl, groups_all, g, labels, reps, controlled, seeds, n_normal=20):
    """한 묶음에 대해 고장·정상 시나리오를 만들어 (T, 9) 잔차 행렬들을 모은다."""
    normal = [zmatrix(bl, make_df(cfg, lambda c: [], seeds.next(), controlled), g, groups_all) for _ in range(n_normal)]
    faults = {}
    for lab, sizes in labels.items():
        for size in sizes:
            for r in range(reps):
                ev = lambda c, lab=lab, size=size: fault_events(c, g, lab, size)
                faults.setdefault(lab, []).append((size, r, zmatrix(bl, make_df(cfg, ev, seeds.next(), controlled), g, groups_all)))
    return normal, faults


def noise_vecs(normal, W):
    out = []
    for Z in normal:
        for t in range(1500, 4000 - W, 300):
            out.append(vec(Z, (t, t + W)))
    return np.array(out)


def classify_eval(normal, faults, W, subset, classes, train_reps):
    idx = [CH.index(c) for c in subset]
    X0 = noise_vecs(normal, W)[:, idx]
    Wm, C = whitener(X0)
    sd = np.sqrt(np.diag(C))
    chi_thr = float(np.percentile(np.sum((X0 @ Wm) ** 2, axis=1), 99))
    post = (POST_START, POST_START + W)
    dirs = {}
    for cl in classes:
        vs = [Wm @ vec(Z, post)[idx] for lab, rows in faults.items() if merged(lab) == cl for (_, r, Z) in rows if r < train_reps]
        v = np.sum(vs, axis=0)
        dirs[cl] = v / (np.linalg.norm(v) + 1e-12)
    res = {}
    for lab, rows in faults.items():
        true = merged(lab)
        if true not in classes:
            continue
        for size, r, Z in rows:
            if r < train_reps:
                continue
            v = vec(Z, post)[idx]
            xw = Wm @ v
            scores = {cl: max(0.0, dirs[cl] @ xw) ** 2 for cl in classes}
            pred = max(scores, key=scores.get) if float(xw @ xw) > chi_thr else "none"
            # 기존 규칙 (A 부분집합 기준이 아니라 전체 채널의 입구유량·불균형으로 3σ 판정)
            res.setdefault(true, {}).setdefault(str(size), []).append(pred)
    return res, dirs, sd


def summarize(normal, faults, reps):
    train_reps = max(1, reps // 2 + reps % 2)    # 앞쪽 반복으로 방향을 정하고 나머지로 시험
    out = {"subsets": {}, "windows": {}}
    for name, sub in SUBSETS.items():
        res, _, _ = classify_eval(normal, faults, 360, sub, IMB_CLASSES, train_reps)
        out["subsets"][name] = {c: {s: _rates(p) for s, p in d.items()} for c, d in res.items()}
    for W in WINDOWS:
        res, _, _ = classify_eval(normal, faults, W, CH, IMB_CLASSES, train_reps)
        out["windows"][str(W)] = {c: {s: _rates(p) for s, p in d.items()} for c, d in res.items()}
    return out


def _rates(preds):
    n = len(preds)
    cnt = {}
    for p in preds:
        cnt[p] = cnt.get(p, 0) + 1
    return {k: round(v / n, 3) for k, v in cnt.items()} | {"n": n}


def signatures(normal, faults, W=360):
    sd = noise_vecs(normal, W).std(axis=0)
    sigs = {}
    for lab, rows in faults.items():
        mid = sorted({s for s, _, _ in rows})[len(sorted({s for s, _, _ in rows})) // 2]
        vs = [vec(Z, (POST_START, POST_START + W)) for s, _, Z in rows if s == mid]
        sigs[lab] = {"size": mid, "z": dict(zip(CH, map(float, np.mean(vs, axis=0))))}
    return {"noise_sd": dict(zip(CH, map(float, sd))), "signatures": sigs}


def angles(normal, faults, W=360):
    X0 = noise_vecs(normal, W)
    Wm, _ = whitener(X0)
    d = {}
    for lab, rows in faults.items():
        mid = sorted({s for s, _, _ in rows})[len(sorted({s for s, _, _ in rows})) // 2]
        v = np.mean([vec(Z, (POST_START, POST_START + W)) for s, _, Z in rows if s == mid], axis=0)
        w = Wm @ v
        d[lab] = w / (np.linalg.norm(w) + 1e-12)
    keys = sorted(d)
    return {f"{a} ~ {b}": round(float(np.degrees(np.arccos(np.clip(d[a] @ d[b], -1, 1)))), 1) for a, b in combinations(keys, 2)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--skip-variants", action="store_true")
    a = ap.parse_args()
    cfg = load_config()
    t_start = time.time()
    tr_df = make_df(cfg, lambda c: [], 1, False, n=14 * DAY)
    bl = B.Baseline().fit(tr_df)
    groups_all = sorted({int(c[1:].split("_")[0]) for c in tr_df.columns if c.startswith("g") and "_flow_in" in c})
    out = {"reps": a.reps, "note": "합성 데이터. 고장 크기는 묶음 유량 대비 %(유량계 오차·누수), 창 길이 360분(별도 표기 제외)."}

    for mode in ("uncontrolled", "controlled"):
        controlled = mode == "controlled"
        labels = LABELS_FLOW if controlled else LABELS_ALL
        out[mode] = {}
        for g in GROUPS:
            print(f"[{mode}] 묶음 {g} … {time.time() - t_start:.0f}s", flush=True)
            normal, faults = run_variant(cfg, bl, groups_all, g, labels, a.reps, controlled, Seeds(10000 * g + (500 if controlled else 0)))
            r = {"group": g, "group_flow_lpm": group_flow(cfg, g), **signatures(normal, faults), "angles_deg": angles(normal, faults)}
            r.update(summarize(normal, faults, a.reps))
            out[mode][str(g)] = r

    if not a.skip_variants:      # 펌프 곡선 기울기 변형: 헤더 압력이 유량에 얼마나 민감한가
        out["pump_variants"] = {}
        for p0 in (6.5, 8.0, 11.0):
            c2 = copy.deepcopy(cfg)
            c2.sim["pump"]["p0_bar"] = p0
            bl2 = fit_baseline_for(c2, 777 + int(p0 * 10))
            g = 3
            print(f"[펌프 p0={p0}] … {time.time() - t_start:.0f}s", flush=True)
            normal, faults = run_variant(c2, bl2, groups_all, g, LABELS_FLOW, a.reps, False, Seeds(int(p0 * 1000)))
            out["pump_variants"][str(p0)] = {
                "p0_bar": p0, "angles_deg": angles(normal, faults),
                "windows": summarize(normal, faults, a.reps)["windows"], "subsets": summarize(normal, faults, a.reps)["subsets"],
                **signatures(normal, faults),
            }
    (DATA_DIR / "discrimination_study.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"saved ({time.time() - t_start:.0f}s)")


if __name__ == "__main__":
    main()
