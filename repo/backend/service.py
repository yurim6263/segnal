"""API가 쓰는 계산 계층. 시나리오 하나를 한 번 계산해 캐시하고, 시각(ts)별 상태는 그 결과를 잘라서 만든다.

EWMA·CUSUM·재중심화·진단은 모두 인과적이라 '전체를 한 번 계산한 뒤 ts까지 자르는 것'이 '그 시점까지의 데이터로 계산한 것'과 같다.
모든 데이터는 합성이고 기준값은 가설이다.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from core.baseline import Baseline
from core.classify import CHANNELS, Diagnosis, DiagnosisModel
from core.detect import cusum, ewma, first_alarm, recenter
from core.forecast import estimate_leak, forecast_line, forecast_text, leak_noise
from core.pattern import CH9, CH_LABEL, CLASS_LABEL, build_pattern_model
from core.impact import impact_range
from core.lifetime import WeibullFit, collect_lives, fit_weibull, prior_from_fit
from core.locate import WINDOW, apply_segment_inspection, priority_order, rank_candidates
from core.normalize import group_signals, groups_in
from core.signature import build_signatures
from db import init_db
from eval.common import EPISODE_GAP, MARGIN_SD, calibrate_threshold
from sim.config import load_config
from sim.scenarios import DATA_DIR, load_scenario

LAYOUT = "S-A"
UNEXPLAINED_HOURS = 24      # 원인을 못 가린 경보 기준 초과를 '주의'로 남기는 시간
EWMA_LAM = 0.1
CUSUM_K = 0.5
DIAG_DELAY = 60
TOP_N = 12

SCENARIO_NAMES = [
    "normal_opchange", "leak_ramp_s5", "leak_small_s9", "leak_abrupt_s2", "clog_s7", "pump_degrade", "sensor_fault",
    "flow_offset_s5", "leak_small_s1",
]

CAUSE_MESSAGE = {
    "leak": "공급-회수 불균형이 기준선 대비 커지는 추세 — 누수 후보",
    "clog": "회수 압력 상승과 유량 감소 — 막힘 후보",
    "pump": "여러 묶음에서 공급 압력과 유량이 함께 낮아짐 — 펌프 이상 후보",
    "sensor": "계측값 이상(고착 또는 계측기 오차) — 계측기 확인 필요",
    "ambiguous": "누수인지 계측기 오차인지 신호 방향으로 구분되지 않음 — 확인 필요",
    "unknown": "이상 징후가 있으나 원인 규칙에 맞지 않음",
}


@dataclass
class Static:
    cfg: object
    layout: str
    baseline: Baseline
    groups: list[int]
    model: DiagnosisModel
    sigs: object
    joints: pd.DataFrame
    fit: WeibullFit
    prior: np.ndarray                   # 서명 후보 순서에 맞춘 사전확률
    minutes: np.ndarray
    risk: np.ndarray
    thr_ewma: dict[int, float]
    thr_cusum: dict[int, float]
    thr_fixed: dict[int, float]
    seg_minutes: np.ndarray = None
    seg_risk: np.ndarray = None
    leak_noise: dict = None             # 묶음별: 정상 때 60분 평균 잔차가 흔들리는 폭(비율)
    line_leak: dict = None              # 묶음별: 기존 경보선(고정 임계값)에 해당하는 누수 크기(비율) = 임계값 − 정상 평균 불균형


@lru_cache(maxsize=1)
def static() -> Static:
    cfg = load_config()
    tr, _ = load_scenario("train_normal", LAYOUT)
    bl = Baseline().fit(tr)
    gs = groups_in(tr)
    model = DiagnosisModel(bl, build_pattern_model(cfg, bl, gs, LAYOUT)).fit(tr, gs)
    lnoise = {g: leak_noise(bl.residuals(tr, g)["res_imb_mass"].to_numpy()) for g in gs}
    sigs = build_signatures(cfg, bl, LAYOUT)
    joints = pd.read_csv(DATA_DIR / "joints.csv")
    log = pd.read_csv(DATA_DIR / "maintenance_log.csv")
    fit = fit_weibull(*collect_lives(joints, log))
    window = float(cfg.sim["maintenance"]["hazard_window_days"])
    pr = dict(zip(joints.joint_id, prior_from_fit(fit, joints, window)))
    prior = np.array([pr[j] for j in sigs.joint_ids]); prior /= prior.sum()
    jt = joints.set_index("joint_id")
    minutes = np.array([jt.loc[j, "inspect_minutes"] for j in sigs.joint_ids])
    risk = np.array([jt.loc[j, "access_risk"] for j in sigs.joint_ids])

    thr_e, thr_c, thr_f = {}, {}, {}
    for g in gs:
        z = recenter(bl.residuals(tr, g)["z_imb_mass"].to_numpy())
        se, sc = ewma(z, EWMA_LAM), cusum(z, CUSUM_K)
        imb = group_signals(tr, g)["imb_vol"].to_numpy()
        thr_e[g] = calibrate_threshold(se, 1, EPISODE_GAP, 1) + MARGIN_SD * float(np.std(se))
        thr_c[g] = calibrate_threshold(sc, 1, EPISODE_GAP, 1) + MARGIN_SD * float(np.std(sc))
        thr_f[g] = calibrate_threshold(imb, 1, EPISODE_GAP, 5) + MARGIN_SD * float(np.std(imb))
    line_leak = {g: thr_f[g] - float(np.mean(group_signals(tr, g)["imb_vol"].to_numpy())) for g in gs}
    init_db()
    seg_min = np.zeros(cfg.n_segments + 1)
    seg_rk = np.zeros(cfg.n_segments + 1)
    for sg in range(1, cfg.n_segments + 1):
        m = sigs.segments == sg
        seg_min[sg], seg_rk[sg] = minutes[m].mean(), risk[m].mean()     # 세그먼트 점검의 대표값(가상)
    return Static(cfg, LAYOUT, bl, gs, model, sigs, joints, fit, prior, minutes, risk, thr_e, thr_c, thr_f, seg_min, seg_rk, lnoise, line_leak)


@dataclass
class Runtime:
    name: str
    df: pd.DataFrame
    labels: dict
    zc: dict[int, dict[str, np.ndarray]]          # 재중심화한 z (묶음, 채널)
    ewma_imb: dict[int, np.ndarray]
    cusum_imb: dict[int, np.ndarray]
    pred_imb: dict[int, np.ndarray]
    res_imb: dict[int, np.ndarray]
    imb_mass: dict[int, np.ndarray]
    alarms: dict[str, dict[int, int | None]]       # 검출기별 묶음의 첫 경보 시각
    diagnosis: Diagnosis
    t_post: int | None
    E: dict = None


@lru_cache(maxsize=16)
def runtime(name: str) -> Runtime:
    st = static()
    df, labels = load_scenario(name, LAYOUT)
    zc, ew, cu, pred, res, imbm = {}, {}, {}, {}, {}, {}
    E = {}
    for g in st.groups:
        r = st.baseline.residuals(df, g)
        zc[g] = {ch: recenter(r[f"z_{ch}"].to_numpy()) for ch in CHANNELS}
        ew[g] = ewma(zc[g]["imb_mass"], EWMA_LAM)
        cu[g] = cusum(zc[g]["imb_mass"], CUSUM_K)
        pr = st.baseline.predict(df, g)
        pred[g] = pr["imb_mass"].to_numpy()
        res[g] = r["res_imb_mass"].to_numpy()
        imbm[g] = group_signals(df, g)["imb_mass"].to_numpy()
        E[g] = {ch: ewma(zc[g][ch], 0.1) for ch in CHANNELS}
    alarms = {"ewma": {}, "cusum": {}, "fixed": {}}
    for g in st.groups:
        alarms["ewma"][g] = first_alarm(ew[g], st.thr_ewma[g], 0)
        alarms["cusum"][g] = first_alarm(cu[g], st.thr_cusum[g], 0)
        alarms["fixed"][g] = first_alarm(group_signals(df, g)["imb_vol"].to_numpy(), st.thr_fixed[g], 0, 5)

    # 진단: 짧게 지나가는 이상이나 원인이 판정되지 않는 이상은 건너뛰고, 계속 이어지는 이상만 원인으로 확정한다
    d = st.model.diagnose_final(df, st.groups, E=E)
    # 경보 시각 보정: 앞선 짧은 오경보가 아니라, 확정된 원인의 증거 채널이 처음 지속적으로 임계값을 넘은 시점으로 한다
    if d.alarm_ts is not None:
        if d.cause == "leak" and d.group:
            ch, gl = "imb_mass", [d.group]
        elif d.cause == "clog" and d.group:
            ch, gl = "p_out", [d.group]
        elif d.cause == "pump":
            ch, gl = "p_in", st.groups
        else:
            ch, gl = None, []
        if ch:
            ts_ref = [first_alarm(np.abs(E[g][ch]), st.model.thr[(g, ch)], d.alarm_ts, 5) for g in gl]
            ts_ref = [t for t in ts_ref if t is not None]
            if ts_ref:
                d.alarm_ts = int(min(ts_ref))
    t_post = None
    if d.cause == "leak" and d.alarm_ts is not None:
        t_post = min(d.alarm_ts + DIAG_DELAY, len(df) - 1)
    return Runtime(name, df, labels, zc, ew, cu, pred, res, imbm, alarms, d, t_post, E)


# ---- 시각별 상태 ----------------------------------------------------------
def _db() -> sqlite3.Connection:
    return init_db()


def _observed(rt: Runtime, st: Static, t: int) -> np.ndarray:
    lo = max(t - WINDOW, 0)
    return np.array([rt.zc[g][ch][lo:t].mean() for g in st.groups for ch in CHANNELS])


def reset_inspections(scenario_id: str) -> None:
    c = _db()
    c.execute("DELETE FROM inspections WHERE scenario_id=?", (scenario_id,))
    c.commit()


def _seg_of(candidate_id: str) -> int:
    """'S5', 'S05', 'S05-R03-in' 어느 형식이든 세그먼트 번호를 꺼낸다."""
    m = re.match(r"S0*(\d+)", candidate_id)
    if not m:
        raise ValueError(f"bad candidate id: {candidate_id}")
    return int(m.group(1))


def add_inspection(scenario_id: str, candidate_id: str, result: str, sim_ts: int | None = None) -> int:
    c = _db()
    cur = c.execute(
        "INSERT INTO inspections (scenario_id, candidate_id, result, sim_ts) VALUES (?,?,?,?)",
        (scenario_id, f"S{_seg_of(candidate_id)}", result, sim_ts),
    )
    c.commit()
    return int(cur.lastrowid)


def delete_inspection(scenario_id: str, insp_id: int) -> None:
    c = _db()
    c.execute("DELETE FROM inspections WHERE scenario_id=? AND id=?", (scenario_id, insp_id))
    c.commit()


def inspections_at(scenario_id: str, ts: int | None = None) -> list[dict]:
    c = _db()
    rows = c.execute("SELECT id, candidate_id, result, sim_ts FROM inspections WHERE scenario_id=? ORDER BY id", (scenario_id,)).fetchall()
    out = []
    for r in rows:
        if ts is not None and r["sim_ts"] is not None and r["sim_ts"] > ts:
            continue
        out.append({"id": int(r["id"]), "segment": _seg_of(r["candidate_id"]), "result": r["result"], "sim_ts": r["sim_ts"]})
    return out


def _first_before(arr_by_group: dict[int, int | None], ts: int) -> int | None:
    vals = [v for v in arr_by_group.values() if v is not None and v <= ts]
    return min(vals) if vals else None


def _topic(n: int) -> str:
    """숫자 뒤 은/는 (마지막 자리 기준)."""
    return "은" if (n % 10) in (0, 1, 3, 6, 7, 8) else "는"


def _fmt_ts(ts: int | None) -> str:
    if ts is None:
        return "—"
    return f"{ts // 1440 + 1}일차 {(ts % 1440) // 60:02d}:{ts % 60:02d}"


def posterior_at(scenario_id: str, ts: int) -> dict | None:
    """누수로 진단된 시나리오의 위치 후보 사후확률 (점검 결과 반영). 없으면 None."""
    st, rt = static(), runtime(scenario_id)
    d = rt.diagnosis
    if d.cause != "leak" or d.alarm_ts is None or d.diag_ts is None or ts < d.diag_ts:
        return None
    t = min(max(ts, d.alarm_ts + 10), rt.t_post if rt.t_post is not None else ts)
    post = rank_candidates(st.sigs, _observed(rt, st, t), st.prior)
    prob = post.prob
    for insp in inspections_at(scenario_id, ts):
        prob = apply_segment_inspection(prob, st.sigs.segments, insp["segment"], insp["result"])
    seg_prob: dict[int, float] = {}
    seg_prior: dict[int, float] = {}
    for s_, p_, pr_ in zip(st.sigs.segments, prob, st.prior):
        seg_prob[int(s_)] = seg_prob.get(int(s_), 0.0) + float(p_)
        seg_prior[int(s_)] = seg_prior.get(int(s_), 0.0) + float(pr_)
    return {"t": t, "prob": prob, "seg_prob": seg_prob, "seg_prior": seg_prior, "post": post}


def candidates_at(scenario_id: str, ts: int) -> tuple[list[dict], np.ndarray | None]:
    """롤·조인트 단위 후보(참고용). 계측으로는 세그먼트 안 롤·조인트를 구분할 수 없어 사전확률이 순서를 정한다."""
    st, rt = static(), runtime(scenario_id)
    pa = posterior_at(scenario_id, ts)
    if pa is None:
        return [], None
    prob, t = pa["prob"], pa["t"]
    score, _ = priority_order(prob, st.minutes, st.risk)
    top = np.argsort(-prob)[:TOP_N]
    prio_rank = {int(i): k + 1 for k, i in enumerate(sorted(top, key=lambda i: -score[i]))}
    out = []
    for rank, i in enumerate(top, start=1):
        seg = int(st.sigs.segments[i])
        out.append({
            "id": st.sigs.joint_ids[i], "segment": seg, "roll": int(st.sigs.rolls[i]), "side": st.sigs.sides[i],
            "prob": round(float(prob[i]), 4), "prior": round(float(st.prior[i]), 5),
            "evidence": [f"조인트 수명 사전확률 {st.prior[i] * 100:.2f}% (신호로는 이 세그먼트 안에서 구분되지 않음)"],
            "rank": rank,
            "inspect_minutes": round(float(st.minutes[i]), 1), "access_risk": round(float(st.risk[i]), 2),
            "priority_score": round(float(score[i]), 5), "priority_rank": prio_rank[int(i)],
        })
    return out, prob


def _channel(rt: Runtime, st: Static, g: int, ch: str, ts: int) -> tuple[float, float]:
    return float(rt.E[g][ch][ts]), float(st.model.thr[(g, ch)])


def _cause_table(rt: Runtime, st: Static, ts: int, cause: str, group: int | None, pattern: dict | None = None) -> list[dict]:
    g = group or max(st.groups, key=lambda x: rt.ewma_imb[x][ts] / st.thr_ewma[x])
    imb, th_i = _channel(rt, st, g, "imb_mass", ts)
    m_in, _ = _channel(rt, st, g, "m_in", ts)
    p_out, th_po = _channel(rt, st, g, "p_out", ts)
    n_pump = sum(1 for x in st.groups if rt.E[x]["p_in"][ts] < -st.model.thr[(x, "p_in")] and rt.E[x]["m_in"][ts] < -st.model.thr[(x, "m_in")])
    alerted = cause in ("leak", "sensor", "ambiguous", "clog", "pump")
    ang = {r["cls"]: r["angle"] for r in pattern["ranking"]} if pattern else {}
    near_sensor = next((r for r in pattern["ranking"] if r["cls"] != "leak"), None) if pattern else None

    def verdict(c: str, label: str) -> str:
        if not alerted:
            return "해당 없음"
        if cause == "ambiguous" and c in ("leak", "sensor"):
            return "구분 불가"
        return f"{label} 후보" if cause == c else "해당 없음"
    leak_now = f"묶음 {g}: 불균형 {imb:+.1f}σ (한계 {th_i:.1f}σ), 입구 유량 {m_in:+.1f}σ" + (f", 누수 방향과 사이각 {ang['leak']:.0f}°" if "leak" in ang else "")
    sens_now = (f"가장 가까운 계측 이상: {near_sensor['label']} (사이각 {near_sensor['angle']:.0f}°)" if near_sensor else "불균형만 커지거나 값이 변하지 않는지 확인")
    return [
        {"cause": "leak", "label": "누수", "pattern": "공급-회수 불균형이 커지고, 여러 신호의 변화 방향이 누수 기준 방향과 가장 가깝다",
         "now": leak_now, "verdict": verdict("leak", "누수")},
        {"cause": "sensor", "label": "계측기 오차", "pattern": "불균형은 커졌지만 다른 신호의 움직임이 누수와 다르다(유량계·압력계·온도계 오차) 또는 값이 변하지 않는다(고착)",
         "now": sens_now, "verdict": verdict("sensor", "계측기 점검")},
        {"cause": "clog", "label": "막힘", "pattern": "회수 압력이 오르고 입구 유량이 줄어든다",
         "now": f"묶음 {g}: 회수 압력 {p_out:+.1f}σ (한계 {th_po:.1f}σ), 입구 유량 {m_in:+.1f}σ", "verdict": verdict("clog", "막힘")},
        {"cause": "pump", "label": "펌프 저하", "pattern": "여러 묶음에서 공급 압력과 입구 유량이 함께 내려간다",
         "now": f"공급 압력·입구 유량이 함께 낮아진 묶음 {n_pump}개 (판정 기준 3개 이상)", "verdict": verdict("pump", "펌프 저하")},
    ]


def _pattern_out(d: Diagnosis) -> dict | None:
    """원인 구분 결과와 근거를 화면용으로 정리한다."""
    p = d.pattern
    if p is None or len(p["ranking"]) < 2:
        return None
    top, second = p["ranking"][0], p["ranking"][1]
    if d.cause == "leak":
        verdict = f"누수 의심 (다음 후보: {second['label']}, 사이각 차이 {p['gap_deg']:.0f}°)"
        how = f"점검 순서대로 현장 확인. 다음 후보인 {second['label']}를 배제하려면 해당 유량계의 진단값과 교정 이력도 확인."
    elif d.cause == "ambiguous":
        verdict = f"구분 불가: '{top['label']}'와 '{second['label']}'의 모습이 비슷함 (사이각 차이 {p['gap_deg']:.0f}°)"
        how = "계측기 진단값·교정 이력과 현장(외부 배관) 점검을 함께 확인. 시간이 더 쌓이면 갈릴 수 있음."
    else:
        verdict = f"{top['label']} 의심 (사이각 {top['angle']:.0f}°)"
        how = "해당 계측기의 진단값과 교정 이력을 확인하고, 교정·교체 뒤에는 기준선을 다시 학습."
    return {
        "group": int(p["group"]), "window_min": int(p["window"]), "ambiguous": bool(p["ambiguous"]), "gap_deg": float(p["gap_deg"]),
        "ranking": [{"cls": r["cls"], "label": r["label"], "angle": float(r["angle"])} for r in p["ranking"]],
        "signals": [{"key": k, "label": CH_LABEL[k], "sigma": round(float(p["signals"][k]), 1)} for k in CH9],
        "verdict": verdict, "how_to_check": how,
    }


def _summary(level: str, cause: str, group_label: str, top_seg: int | None, indistinct: bool, fixed_alarm: int | None,
             confirmed_seg: int | None, n_insp: int, mins_to_confirm: int | None, changed: bool, inspected_clear: list[int],
             pat: dict | None = None, fc_text: str = "", est: dict | None = None) -> dict:
    est_txt = (f" 추정 누수량 약 {est['lpm']:.0f} L/min (범위 {est['low_lpm']:.0f}~{est['high_lpm']:.0f}){'은 누수라면의 값입니다' if est.get('conditional') else ''}."
               if est else "")
    if level == "normal":
        detail = ("주조 속도가 바뀌어 유량이 달라졌지만, 운전 조건을 보정한 기준선도 함께 움직였습니다."
                  if changed else "운전 조건을 보정한 기준선과의 차이가 모두 정상 범위입니다.")
        return {"headline": "정상입니다. 모든 계측 묶음이 기준선 범위 안에 있습니다.", "detail": detail}
    if level == "alarm" and confirmed_seg is not None:
        t = f"경보 뒤 {mins_to_confirm}분, 점검 {n_insp}회 만에 확인했습니다. " if mins_to_confirm is not None else ""
        return {"headline": f"세그먼트 {confirmed_seg}에서 누수를 확인했습니다.",
                "detail": t + (f"세그먼트 {', '.join(map(str, inspected_clear))}의 점검 결과는 이상 없음이었습니다. " if inspected_clear else "") + "조치는 담당자가 결정합니다.",
                "primary_label": "인수인계 노트 보기", "primary_tab": "handover"}
    if cause == "leak":
        where = f"세그먼트 {top_seg}부터 점검을 권고합니다." if top_seg else "점검을 권고합니다."
        fx = "고정 임계값은 아직 넘지 않았습니다." if fixed_alarm is None else "고정 임계값도 넘었지만 우리 방식이 먼저 알렸습니다."
        extra = " 묶음 안 세그먼트는 신호로 구분되지 않아 사전확률로 순서를 정했습니다." if indistinct else ""
        return {"headline": f"{group_label}에서 누수가 의심됩니다. {where}",
                "detail": f"공급-회수 불균형이 기준선보다 커지는 추세가 이어지고 있습니다. {fx}{extra}{est_txt}" + (f" {fc_text}" if fc_text else ""),
                "primary_label": "점검 시작", "primary_tab": "inspect", "secondary_label": "진단 보기", "secondary_tab": "diagnosis"}
    if cause == "clog":
        return {"headline": f"{group_label}에서 막힘이 의심됩니다.", "detail": "회수 압력이 오르고 입구 유량이 줄고 있습니다. 누수 후보 순위는 만들지 않습니다.",
                "secondary_label": "진단 보기", "secondary_tab": "diagnosis"}
    if cause == "pump":
        return {"headline": "펌프 저하가 의심됩니다.", "detail": "여러 묶음에서 공급 압력과 입구 유량이 함께 낮아졌습니다. 누수 후보 순위는 만들지 않습니다.",
                "secondary_label": "진단 보기", "secondary_tab": "diagnosis"}
    if cause == "sensor":
        if pat:
            return {"headline": f"{group_label}에서 {pat['verdict']}.", "detail": f"{pat['how_to_check']} 누수 후보 순위는 만들지 않습니다.",
                    "secondary_label": "진단 보기", "secondary_tab": "diagnosis"}
        return {"headline": f"{group_label}의 계측값 이상이 의심됩니다.", "detail": "값이 변하지 않거나 입구 유량 변화 없이 불균형만 커졌습니다. 계측기 확인을 권고합니다.",
                "secondary_label": "진단 보기", "secondary_tab": "diagnosis"}
    if cause == "ambiguous":
        return {"headline": f"{group_label}에서 이상이 있지만 누수인지 계측기 오차인지 구분되지 않습니다.",
                "detail": ((pat["verdict"] + ". " + pat["how_to_check"]) if pat else "신호 방향만으로는 구분되지 않습니다.") + est_txt + " 누수 후보 순위는 만들지 않습니다.",
                "secondary_label": "진단 보기", "secondary_tab": "diagnosis"}
    return {"headline": "이상 징후가 감지되었습니다. 원인을 확인하는 중입니다.", "detail": "패턴이 완성될 때까지 기다리는 중입니다."}


def state_at(scenario_id: str, ts: int | None) -> dict:
    st, rt = static(), runtime(scenario_id)
    T = len(rt.df)
    ts = T - 1 if ts is None else int(np.clip(ts, 0, T - 1))
    d = rt.diagnosis
    seg_to_group = {s: gi + 1 for gi, segs in enumerate(st.cfg.sensor_groups) for s in segs}
    insps = inspections_at(scenario_id, ts)
    latest_by_seg = {i["segment"]: i["result"] for i in insps}

    alerted = d.alarm_ts is not None and ts >= d.alarm_ts
    # 원인을 판정하지 못했어도 최근 24시간 안에 평활 불균형이 경보 기준을 넘은 묶음이 있으면 '정상'이라고 하지 않는다
    # (검출 한계 근처의 작은 누수는 기준을 잠깐 넘었다가 내려오기도 한다) → 주의, 원인 미판정
    unexplained = []
    if not alerted:
        unexplained = [g for g in st.groups if (rt.ewma_imb[g][max(ts - UNEXPLAINED_HOURS * 60, 0): ts + 1] > st.thr_ewma[g]).any()]
        alerted = bool(unexplained)
    confirmed = d.diag_ts is not None and ts >= d.diag_ts and d.cause != "unknown"
    cause = d.cause if confirmed else "unknown"
    conf_leaks = [i for i in insps if i["result"] == "leak_confirmed"]
    confirmed_seg = conf_leaks[-1]["segment"] if (conf_leaks and cause == "leak") else None

    # 상태: 시스템이 의심하는 단계는 '주의', 사람이 점검해서 누수를 확인한 뒤에만 '경보'
    level = "alarm" if confirmed_seg is not None else ("watch" if (confirmed or alerted) else "normal")

    ew_alarm = cu_alarm = fx_alarm = None
    t_start = None
    if confirmed and cause == "leak" and d.group is not None:
        g = d.group
        t_start = d.alarm_ts
        while t_start > 0 and rt.cusum_imb[g][t_start] > 0:
            t_start -= 1
        t_start = max(t_start, d.alarm_ts - 720)
        for key, arr in (("ewma", rt.ewma_imb[g]), ("cusum", rt.cusum_imb[g])):
            a = first_alarm(arr, st.thr_ewma[g] if key == "ewma" else st.thr_cusum[g], t_start)
            if a is not None and a <= ts:
                if key == "ewma":
                    ew_alarm = a
                else:
                    cu_alarm = a
        fx = first_alarm(group_signals(rt.df, g)["imb_vol"].to_numpy(), st.thr_fixed[g], t_start, 5)
        fx_alarm = fx if fx is not None and fx <= ts else None

    # 세그먼트 칸 상태
    seg_levels = []
    for s in range(1, st.cfg.n_segments + 1):
        g = seg_to_group[s]
        lv = "normal"
        if confirmed_seg == s:
            lv = "alarm"
        elif confirmed and (d.group is None or d.group == g):
            lv = "watch"
        elif alerted and (g in unexplained or rt.ewma_imb[g][ts] > 0.6 * st.thr_ewma[g]):
            lv = "watch"
        seg_levels.append({"segment": s, "level": lv, "group": g - 1, "inspected": latest_by_seg.get(s)})

    # 묶음 상태
    groups = []
    for gi, segs in enumerate(st.cfg.sensor_groups):
        g = gi + 1
        dev = float(rt.ewma_imb[g][ts] / st.thr_ewma[g])
        lv = "normal"
        if confirmed and (d.group is None or d.group == g):
            lv = "alarm" if confirmed_seg is not None and (confirmed_seg in segs) else "watch"
        elif alerted and (g in unexplained or abs(dev) > 0.6):
            lv = "watch"
        groups.append({"group": gi, "segments": segs, "level": lv, "deviation": round(dev, 2)})

    # 세그먼트 후보 (점검 단위)
    seg_cands, others, distinguishable, note = [], 0.0, True, ""
    cands: list[dict] = []
    impact = None
    pa = posterior_at(scenario_id, ts) if (confirmed and cause == "leak") else None
    if pa is not None:
        cands, _ = candidates_at(scenario_id, ts)
        seg_prob, seg_prior = pa["seg_prob"], pa["seg_prior"]
        seg_min = {s: float(st.seg_minutes[s]) for s in seg_prob}
        seg_risk = {s: float(st.seg_risk[s]) for s in seg_prob}
        score = {s: seg_prob[s] / (seg_min[s] + 20.0 * seg_risk[s]) for s in seg_prob}
        order = sorted(seg_prob, key=lambda s: -seg_prob[s])
        # 점검 순서(O1): 아직 이상 없음으로 점검하지 않은 세그먼트를 점수 순으로
        pending = [s for s in sorted(seg_prob, key=lambda s: -score[s]) if latest_by_seg.get(s) != "no_issue"]
        prio = {s: k + 1 for k, s in enumerate(pending)}
        g_ref = d.group or 1
        grp_segs = st.cfg.sensor_groups[g_ref - 1]
        z_imb = float(rt.zc[g_ref]["imb_mass"][max(pa["t"] - WINDOW, 0):pa["t"]].mean())
        z_min = float(rt.zc[g_ref]["m_in"][max(pa["t"] - WINDOW, 0):pa["t"]].mean())
        for rank, s in enumerate(order[:6], start=1):
            seg_cands.append({
                "segment": s, "prob": round(seg_prob[s], 4), "rank": rank, "inspected": latest_by_seg.get(s),
                "inspect_minutes": round(seg_min[s], 1), "access_risk": round(seg_risk[s], 2),
                "priority_score": round(score[s], 5), "priority_rank": prio.get(s, 0),
                "evidence": [f"묶음 {g_ref} 공급-회수 질량 불균형 잔차 {z_imb:+.1f}σ (최근 {WINDOW}분 평균)",
                             f"묶음 {g_ref} 입구 질량유량 잔차 {z_min:+.1f}σ",
                             f"조인트 수명 사전확률 합 {seg_prior[s] * 100:.1f}%"] if rank == 1 else [],
            })
        others = round(max(0.0, 1.0 - sum(c["prob"] for c in seg_cands[:3])), 4)
        # 같은 묶음 안 세그먼트는 신호로 구분되지 않는다 → 확률 차이가 작으면 '구분되지 않음'
        in_grp = sorted((seg_prob[s] for s in grp_segs if s in seg_prob), reverse=True)
        if len(grp_segs) > 1 and len(in_grp) > 1 and in_grp[0] < 1.5 * in_grp[1]:
            distinguishable = False
            note = f"묶음 {g_ref} 안의 세그먼트({', '.join(map(str, grp_segs))})는 신호로 구분되지 않습니다. 수명 사전확률과 점검 결과로 순서를 정했습니다."
        # O2 영향 구간
        if t_start is not None:
            speed = rt.df["cast_speed"].to_numpy()
            seg_i = confirmed_seg or (seg_cands[0]["segment"] if seg_cands else grp_segs[0])
            ir = impact_range(speed, seg_i, t_start, ts, dt_min=st.cfg.sim["dt_s"] / 60.0)
            impact = {"start_m": round(ir.start_m, 1), "end_m": round(ir.end_m, 1), "label": ir.label}

    # 경보 뒤 걸린 시간과 점검 횟수
    mins_since = (ts - d.alarm_ts) if alerted and d.alarm_ts is not None else None
    mins_to_confirm = None
    if confirmed_seg is not None and d.alarm_ts is not None:
        t_conf = next(i["sim_ts"] for i in conf_leaks if i["segment"] == confirmed_seg)
        if t_conf is not None:
            mins_to_confirm = int(t_conf - d.alarm_ts)

    changed = bool(ts >= 30 and abs(float(rt.df["cast_speed"].iloc[ts]) - float(rt.df["cast_speed"].iloc[ts - 30])) > 0.02)
    g_lab = f"묶음 {d.group}" if d.group else "일부 묶음"
    group_label = f"{g_lab}(세그먼트 {', '.join(map(str, st.cfg.sensor_groups[d.group - 1]))})" if d.group else g_lab
    # 원인 구분 근거, 경보선 도달 예상 시각, 추정 누수량
    pattern_out = _pattern_out(d) if (confirmed and cause in ("leak", "sensor", "ambiguous")) else None
    forecast_out = est_out = None
    if confirmed and cause in ("leak", "ambiguous") and d.group is not None:
        gg = d.group
        est_out = estimate_leak(rt.res_imb[gg], rt.df[f"g{gg}_flow_in"].to_numpy(), ts, st.leak_noise[gg])
        est_out["conditional"] = cause == "ambiguous"
    if confirmed and cause == "leak" and d.group is not None and t_start is not None:
        gg = d.group
        vol = group_signals(rt.df, gg)["imb_vol"].to_numpy()
        forecast_out = forecast_line(rt.res_imb[gg], float(np.mean(vol[max(ts - 29, 0): ts + 1])), float(st.thr_fixed[gg]), ts, t_start)
        if fx_alarm is not None:       # 기존 방식이 이미 울렸으면 '닿을 시각'이 아니라 '이미 넘음'
            forecast_out.update(available=False, crossed=True, hours=None, low_hours=None, high_hours=None, reason="이미 기존 경보선을 넘었습니다")
        forecast_out["text"] = forecast_text(forecast_out)
        forecast_out["line_leak_pct"] = round(st.line_leak[gg] * 100, 2)
        if est_out is not None and st.line_leak[gg] > 0:
            forecast_out["progress"] = round(est_out["pct"] / (st.line_leak[gg] * 100), 2)
    summary = _summary(level, cause if level != "normal" else "unknown", group_label,
                       seg_cands[0]["segment"] if seg_cands else None, not distinguishable, fx_alarm,
                       confirmed_seg, len(insps), mins_to_confirm, changed,
                       [i["segment"] for i in insps if i["result"] == "no_issue"],
                       pat=pattern_out, fc_text=(forecast_out or {}).get("text", ""), est=est_out)
    if level == "watch" and not confirmed:
        if unexplained:
            names = ", ".join(f"묶음 {g}(세그먼트 {', '.join(map(str, st.cfg.sensor_groups[g - 1]))})" for g in unexplained)
            summary = {"headline": f"{names}에서 경보 기준을 넘은 적이 있지만 원인을 가리지 못했습니다.",
                       "detail": "기준을 넘었다가 내려왔습니다. 작은 누수이거나 일시적인 변동일 수 있어 유량계 확인이나 점검을 권고합니다. 누수 후보 순위는 만들지 않습니다.",
                       "secondary_label": "진단 보기", "secondary_tab": "diagnosis"}
        else:
            summary = {"headline": "이상 징후가 감지되었습니다. 원인을 확인하는 중입니다.", "detail": "패턴이 완성될 때까지 기다리는 중입니다."}

    msg = CAUSE_MESSAGE.get(cause, "정상") if level != "normal" else "이상 징후 없음"
    if level == "watch" and not confirmed:
        msg = "이상 징후 감지 — 원인 확인 중"
    return {
        "scenario_id": scenario_id, "ts": ts,
        "cast_speed": round(float(rt.df["cast_speed"].iloc[ts]), 3), "steel_grade": str(rt.df["steel_grade"].iloc[ts]),
        "segments": seg_levels,
        "alert": {
            "level": level, "cause": cause if level != "normal" else "unknown",
            "since_ts": d.alarm_ts if alerted else None, "group": (d.group - 1) if (confirmed and d.group) else None,
            "message": msg,
            "detectors": {"fixed_alarm_ts": fx_alarm, "ewma_alarm_ts": ew_alarm, "cusum_alarm_ts": cu_alarm},
        },
        "candidates": cands, "impact": impact, "is_synthetic": True,
        "summary": summary, "groups": groups,
        "segment_candidates": seg_cands, "others_prob": others, "distinguishable": distinguishable, "candidate_note": note,
        "inspections": insps, "confirmed_segment": confirmed_seg,
        "minutes_since_alarm": mins_since, "minutes_to_confirm": mins_to_confirm,
        "cause_table": _cause_table(rt, st, ts, cause, d.group if confirmed else None, d.pattern if confirmed else None),
        "operating": {"cast_speed": round(float(rt.df["cast_speed"].iloc[ts]), 3), "steel_grade": str(rt.df["steel_grade"].iloc[ts]),
                      "t_in": round(float(rt.df["g1_t_in"].iloc[ts]), 1), "changed_recently": changed},
        "pattern": pattern_out, "forecast": forecast_out, "leak_estimate": est_out,
    }


def handover_at(scenario_id: str, ts: int | None) -> dict:
    """인수인계 노트 (템플릿). 수치는 계산 결과를 그대로 옮기고, 비어 있는 값은 문장을 만들지 않고 '값 없음'으로 둔다.
    17단계에서 LLM이 이 틀의 문장을 다듬도록 확장한다."""
    st, rt = static(), runtime(scenario_id)
    T = len(rt.df)
    ts = T - 1 if ts is None else int(np.clip(ts, 0, T - 1))
    state = state_at(scenario_id, ts)
    d = rt.diagnosis
    out: dict = {"title": "", "text": "", "generated_by": "template", "ready": False, "sections": [], "missing": [], "sources": []}
    if state["alert"]["level"] == "normal" or d.alarm_ts is None:
        out["missing"] = ["아직 경보가 없어 작성할 내용이 없습니다."]
        return out
    cause_label = {"leak": "누수", "clog": "막힘", "pump": "펌프 저하", "sensor": "계측기 이상", "ambiguous": "누수 또는 계측기 오차(구분 불가)"}.get(state["alert"]["cause"], "원인 확인 중")
    g = d.group
    secs, srcs = [], []
    # 경보
    v = [{"label": "경보 시각", "value": _fmt_ts(d.alarm_ts), "source": "변화 탐지(EWMA)"}]
    fx = state["alert"]["detectors"]["fixed_alarm_ts"]
    secs.append({"title": "경보", "text": f"{'묶음 ' + str(g) if g else '일부 묶음'}에서 {_fmt_ts(d.alarm_ts)}에 추세 감지 경보가 났습니다. "
                 + ("고정 임계값에는 도달하지 않았습니다." if fx is None else f"고정 임계값은 {_fmt_ts(fx)}에 도달했습니다."), "values": v})
    # 원인 후보
    ct = {r["cause"]: r for r in state["cause_table"]}
    row = ct.get(state["alert"]["cause"])
    secs.append({"title": "원인 후보", "text": f"{cause_label} 후보입니다. " + (row["pattern"] + "." if row else ""), "values": []})
    # 근거
    vals = []
    if g:
        imb = float(rt.E[g]["imb_mass"][ts]); mi = float(rt.E[g]["m_in"][ts])
        vals = [{"label": "공급-회수 불균형 잔차(평활)", "value": f"{imb:+.1f}σ", "source": "운전 조건 보정 모델 + EWMA"},
                {"label": "입구 질량유량 잔차(평활)", "value": f"{mi:+.1f}σ", "source": "운전 조건 보정 모델 + EWMA"}]
        secs.append({"title": "근거", "text": f"묶음 {g}의 공급-회수 불균형이 기준선보다 {imb:+.1f}σ 벌어졌고, 입구 유량 잔차는 {mi:+.1f}σ였습니다.", "values": vals})
    else:
        out["missing"].append("근거: 원인에 해당하는 묶음 정보가 없습니다.")
    # 점검 결과
    insps = state["inspections"]
    if insps:
        lines = [f"세그먼트 {i['segment']}{_topic(i['segment'])} {_fmt_ts(i['sim_ts'])}에 " + ("누수 확인" if i["result"] == "leak_confirmed" else "이상 없음") for i in insps]
        txt = "; ".join(lines) + "."
        if state["minutes_to_confirm"] is not None:
            txt += f" 경보부터 {state['minutes_to_confirm']}분, 점검 {len(insps)}회 만에 찾았습니다."
        secs.append({"title": "점검 결과", "text": txt,
                     "values": [{"label": "점검 횟수", "value": f"{len(insps)}회", "source": "점검 기록"}]})
    else:
        out["missing"].append("점검 결과: 아직 점검 기록이 없습니다.")
    secs.append({"title": "다음 할 일", "text": "조치는 담당자가 결정합니다.", "values": []})
    for sct in secs:
        srcs.extend(sct["values"])
    conf = state["confirmed_segment"]
    out["title"] = (f"묶음 {g} {cause_label}" + (f", 세그먼트 {conf}에서 확인" if conf else " 의심")) if g else f"{cause_label} 의심"
    out["sections"] = secs
    out["sources"] = srcs
    out["text"] = " ".join(s_["text"] for s_ in secs)
    out["ready"] = conf is not None
    return out


def series_at(scenario_id: str, group: int, ts: int | None, step: int = 5, channel: str = "imb_mass") -> dict:
    st, rt = static(), runtime(scenario_id)
    g = int(np.clip(group, 1, len(st.groups)))
    T = len(rt.df)
    ts = T - 1 if ts is None else int(np.clip(ts, 0, T - 1))
    idx = np.arange(0, ts + 1, step)
    if channel != "imb_mass":
        names = {"m_in": ("입구 질량유량", "kg/min"), "p_in": ("공급 압력", "bar"), "p_out": ("회수 압력", "bar")}
        nm, unit = names.get(channel, (channel, ""))
        sig = group_signals(rt.df, g)[channel].to_numpy()
        pred = st.baseline.predict(rt.df, g)[channel].to_numpy()
        pts = [{"ts": int(i), "value": round(float(sig[i]), 4), "baseline": round(float(pred[i]), 4),
                "residual": round(float(sig[i] - pred[i]), 4), "ewma": None, "cusum": None} for i in idx]
        return {"scenario_id": scenario_id, "group": g - 1, "name": f"묶음 {g} {nm}", "unit": unit, "points": pts,
                "ewma_limit": None, "cusum_limit": None, "fixed_limit": None}
    vol = group_signals(rt.df, g)["imb_vol"].to_numpy()
    pts = [{
        "ts": int(i), "value": round(float(rt.imb_mass[g][i] * 100), 4),
        "fixed_value": round(float(vol[i] * 100), 4),
        "baseline": round(float(rt.pred_imb[g][i] * 100), 4),
        "residual": round(float(rt.res_imb[g][i] * 100), 4),
        "ewma": round(float(rt.ewma_imb[g][i]), 4), "cusum": round(float(rt.cusum_imb[g][i]), 4),
    } for i in idx]
    return {
        "scenario_id": scenario_id, "group": g - 1, "name": f"묶음 {g} 공급-회수 질량 불균형", "unit": "%",
        "points": pts, "ewma_limit": round(float(st.thr_ewma[g]), 3), "cusum_limit": round(float(st.thr_cusum[g]), 3),
        "fixed_limit": round(float(st.thr_fixed[g]) * 100, 3),
    }


def scenario_infos() -> list[dict]:
    out = []
    for n in SCENARIO_NAMES:
        _, lab = load_scenario(n, LAYOUT)
        out.append({"id": n, "name": lab["description"].split(":")[0].split("(")[0].strip(), "description": lab["description"],
                    "n_samples": lab["n_samples"], "sensor_layout": LAYOUT})
    return out


def joint_risks() -> list[dict]:
    st = static()
    window = float(st.cfg.sim["maintenance"]["hazard_window_days"])
    h = st.fit.hazard(st.joints["age_days"].to_numpy(), window)
    out = []
    for r, hz in zip(st.joints.itertuples(), h):
        out.append({"joint_id": r.joint_id, "segment": int(r.segment), "roll": int(r.roll), "side": r.side,
                    "age_days": round(float(r.age_days), 1), "hazard": round(float(hz), 5),
                    "access_risk": round(float(r.access_risk), 2), "inspect_minutes": round(float(r.inspect_minutes), 1),
                    "replace_count": int(r.replace_count)})
    return out


def eval_detectors() -> list[dict]:
    p = DATA_DIR / "detector_tuning.json"
    if not p.exists():
        return []
    rows = json.loads(p.read_text(encoding="utf-8")).get(LAYOUT, {}).get("rows", [])
    keep = {"고정 임계값(보정)", "EWMA λ=0.1", "CUSUM k=0.5", "Isolation Forest (잔차)", "Isolation Forest (원시+운전조건)",
            "오토인코더 (운전조건 포함)", "오토인코더 (원시 센서만)"}
    return [{
        "detector": r["label"], "detection_delay_min": r["median_delay_min"],
        "false_alarms": r["false_alarms_per_14d_per_group"],
        "note": f"탐지 {r['detected']}/{r['n']}, 탐지 시점 누수량 {r['median_leak_lpm_at_detection']} L/min",
    } for r in rows if r["label"] in keep]


def eval_priors() -> list[dict]:
    p = DATA_DIR / "localize_eval.json"
    if not p.exists():
        return []
    d = json.loads(p.read_text(encoding="utf-8")).get(LAYOUT, {})
    w = d.get("evalp_w (진짜 Weibull)")
    l = d.get("evalp_l (진짜 lognormal, 모델은 Weibull)")
    if not w or not l:
        return []

    def row(name, x):
        return {"prior": name, "top1": x["joint_top1"], "top3": x["joint_top3"], "top10": x["joint_top10"], "mean_rank": x["mean_rank"]}
    return [row("none", w["none"]), row("uniform", w["none"]), row("weibull", w["weibull"]), row("mismatch", l["weibull"])]


def eval_summary() -> dict:
    """비교·지표 화면용: 저장된 평가 결과를 그대로 읽어 온다 (보고서·발표자료와 같은 값)."""
    out: dict = {"detectors": [], "inspection": None, "localize": None, "classify": None, "sensitivity": None, "longrun": None, "pattern": None}
    p = DATA_DIR / "detector_tuning.json"
    if p.exists():
        rows = json.loads(p.read_text(encoding="utf-8")).get(LAYOUT, {}).get("rows", [])
        by = {r["label"]: r for r in rows}
        out["detectors"] = rows
        out["headline"] = {
            "ours": by.get("EWMA λ=0.1"), "fixed": by.get("고정 임계값(보정)"),
        }
    p = DATA_DIR / "inspection_eval.json"
    if p.exists():
        out["inspection"] = json.loads(p.read_text(encoding="utf-8")).get(LAYOUT)
    p = DATA_DIR / "localize_eval.json"
    if p.exists():
        out["localize"] = json.loads(p.read_text(encoding="utf-8")).get(LAYOUT)
    p = DATA_DIR / "sensitivity_eval.json"
    if p.exists():
        out["sensitivity"] = json.loads(p.read_text(encoding="utf-8")).get(LAYOUT)
    p = DATA_DIR / "longrun_eval.json"
    if p.exists():
        out["longrun"] = json.loads(p.read_text(encoding="utf-8")).get(LAYOUT)
    p = DATA_DIR / "classify_eval.json"
    if p.exists():
        c = json.loads(p.read_text(encoding="utf-8"))
        out["classify"] = {"accuracy": c["accuracy"], "per_class": c["per_class"], "previous_rule": c.get("previous_rule"), "method": c.get("method")}
    pat: dict = {}
    for key, fname in (("normal", "pattern_eval.json"), ("calibration", "pattern_calibration.json"), ("forecast", "forecast_eval.json")):
        p = DATA_DIR / fname
        if p.exists():
            d_ = json.loads(p.read_text(encoding="utf-8"))
            if key == "forecast":              # 건별 행은 화면에 필요 없다
                d_.pop("rows", None)
                d_.pop("estimate_rows", None)
            pat[key] = d_
    out["pattern"] = pat or None
    return out
