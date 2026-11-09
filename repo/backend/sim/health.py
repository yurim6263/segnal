"""세그먼트 수명·누수 원인 시뮬레이터 (기획서 5-1).

2년(730일) 일별 이력(자산·장착·정비·누수·일별 열화 신호·수질·조업 이벤트)과 최근 14일 1분 센서 시계열을 만든다.
모든 값은 [가정]이고 config/plant.yaml의 `health` 블록에 둔다. 난수 시드를 고정해 누가 돌려도 같은 데이터가 나온다.

누수는 원인별로 따로 생성한다(일별 위험 증가량 ΔH, 같은 날 하나라도 일어나면 누수):
  WEAR     씰 정상 마모: 와이블 β=2.5, 씰·조인트 교체 후 누적 톤수 기준
  HAMMER   스팀 해머성 씰 파손: 냉각 유량이 정상의 90% 미만이었던 시간에 비례
  BEARING  베어링 손상 → 씰 하중: 열화가 2~6주에 걸쳐 오르다 끝 무렵 위험 급증, 베어링 온도·진동이 오름
  THERMAL  열 사이클 피로: 주조 시작·정지 횟수에 비례
  WATER    이물질·스케일: 탁도·경도가 관리 상한을 넘은 정도에 비례
  ASSEMBLY 조립 불량: 와이블 β=0.6, 장착 후 경과일 기준, 장착 후 압력 시험을 하면 위험 절반
  RANDOM   우연형: 일정 비율
숨은 요인: 세그먼트 10%는 예측 모델이 읽지 않는 조립 불량 플래그(위험 2배).
정답 전용 필드: segments.assembly_flag, leaks.cause_code (예측 모델은 읽지 않는다).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from .config import CONFIG_PATH

OUT_DIR = Path(__file__).resolve().parents[2] / "data" / "health"
CAUSES = ["WEAR", "HAMMER", "BEARING", "THERMAL", "WATER", "ASSEMBLY", "RANDOM"]
CAUSE_PART = {"WEAR": ["rotary_joint", "seal"], "HAMMER": ["seal"], "BEARING": ["bearing_housing"], "THERMAL": ["seal"],
              "WATER": ["seal"], "ASSEMBLY": ["oring", "hose"], "RANDOM": ["hose", "rotary_joint"]}
BUNDLES = {"B1": [1], "B2": [2, 3], "B3": [4, 5], "B4": [6, 7], "B5": [8, 9, 10, 11, 12, 13]}
BUNDLE_OF = {p: b for b, ps in BUNDLES.items() for p in ps}
BUNDLE_IDX = {b: i for i, b in enumerate(BUNDLES)}

DEFAULTS = {
    "seed": 20261110, "days": 730, "n_serials": 20, "n_positions": 13, "end_date": "2026-11-09", "demo_days": 14,
    "planned_stop_every_days": 14, "planned_stop_hours": 8, "next_stop_in_days": 3, "replace_top_n": 2, "refurb_days": 10,
    "assembly_hidden_share": 0.10, "assembly_hidden_multiplier": 2.0, "pressure_test_share": 0.5,
    "tons_per_cast_hour": 340.0, "unplanned_pull_lpm": 12.0,
    "wear": {"beta": 2.5, "eta_tons": 1670000.0},
    "hammer": {"k_per_low_flow_min": 0.0000185},
    "bearing": {"episode_rate_per_day": 0.00056, "k_peak": 0.25},
    "thermal": {"k_per_cycle": 0.00017},
    "water": {"k_per_excess": 0.0025},
    "assembly": {"beta": 0.6, "eta_days": 8800.0, "pressure_test_factor": 0.5},
    "random": {"rate_per_day": 0.00039},
    "demo": {"serial": "S-0012", "position": 7, "bundle": "B4", "low_flow_days": 18, "low_flow_min": 380, "bearing_rise_c": 6.0},
}


def load_params(path: Path | str | None = None) -> dict:
    raw = yaml.safe_load(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    out = json.loads(json.dumps(DEFAULTS))
    for k, v in (raw.get("health") or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


@dataclass
class Seg:
    sid: int                       # 내부 번호 (최종 표기는 S-xxxx)
    assembly_flag: int
    joint_age: float = 0.0
    pos: int | None = None
    install_day: int = 0
    pressure_test: int = 0
    status: str = "spare"          # installed / refurb / spare
    ready_day: int = 0
    pull_day: int | None = None
    pull_cause: str | None = None
    protected: bool = False
    ep: dict | None = None         # 베어링 열화 에피소드
    bearing_base: float = 60.0
    vib_base: float = 1.6
    degraded: bool = False


def _ar1(rng, n, mu, sd, rho):
    x = np.empty(n)
    x[0] = mu
    for i in range(1, n):
        x[i] = mu + rho * (x[i - 1] - mu) + rng.normal(0, sd * np.sqrt(1 - rho ** 2))
    return x


def _episodes(rng, n, rate_per_year, dur, hi, lo, base_hi=None):
    """연속 구간(에피소드)의 일별 강도 배열. rate: 연간 발생 건수."""
    arr = np.zeros(n)
    k = rng.poisson(rate_per_year * n / 365.0)
    for _ in range(k):
        s = int(rng.integers(0, n))
        d = int(rng.integers(dur[0], dur[1] + 1))
        arr[s:s + d] = np.maximum(arr[s:s + d], rng.uniform(lo, hi))
    return arr


def simulate(params: dict | None = None, seed: int | None = None, with_minute: bool = True) -> dict[str, pd.DataFrame]:
    P = params or load_params()
    rng = np.random.default_rng(P["seed"] if seed is None else seed)
    N, NP = int(P["days"]), int(P["n_positions"])
    end = date.fromisoformat(P["end_date"])
    d0 = end - timedelta(days=N - 1)
    day_date = lambda d: d0 + timedelta(days=int(d))
    demo_start = N - int(P["demo_days"])
    stop_every = int(P["planned_stop_every_days"])
    next_stop = N - 1 + int(P["next_stop_in_days"])
    stops = sorted({next_stop - stop_every * k for k in range(1, N // stop_every + 2) if 0 < next_stop - stop_every * k < N})
    stop_set = set(stops)
    dm = P["demo"]
    demo_stop_day = max(s for s in stops if s < N)          # 시연 세그먼트가 장착되는 정지일

    # ---- 플랜트 공통 일별 값 -------------------------------------------------
    speed = np.clip(_ar1(rng, N, 1.3, 0.1, 0.9), 1.0, 1.6)
    freq_stop = _episodes(rng, N, 3, (3, 10), 12, 6)                    # 정지·재가동이 잦은 기간(하루 6~12회)
    cycles = np.where(freq_stop > 0, np.round(freq_stop).astype(int), rng.integers(2, 5, size=N))
    cast_h = np.clip(rng.normal(21.0, 1.2, N), 18.0, 23.0)
    for s in stops:
        cast_h[s] = rng.uniform(12.0, 15.0)                             # 계획 정지 8시간
        cycles[s] += 1
    # ---- 묶음별 일별 값 ------------------------------------------------------
    nb = len(BUNDLES)
    low_flow = np.zeros((N, nb))
    pres_ev = np.zeros((N, nb))
    for b, bi in BUNDLE_IDX.items():
        base = np.minimum(rng.exponential(18, N), 60)
        ep = _episodes(rng, N, 5, (4, 15), 450, 150)
        low_flow[:, bi] = np.where(ep > 0, ep + rng.normal(0, 30, N), base)
        pe = _episodes(rng, N, 3, (3, 10), 12, 4)
        pres_ev[:, bi] = np.where(pe > 0, np.round(pe), np.minimum(rng.poisson(0.8, N), 3))
    bi4 = BUNDLE_IDX[dm["bundle"]]
    low_flow[N - int(dm["low_flow_days"]):, bi4] = np.clip(rng.normal(dm["low_flow_min"], 50, int(dm["low_flow_days"])), 250, 520)
    low_flow = np.clip(np.round(low_flow), 0, None)
    heat_base = np.array([14.0, 13.0, 12.0, 11.0, 9.5])
    # ---- 수질(주 1회) --------------------------------------------------------
    nw = N // 7 + 1
    turb = np.clip(rng.normal(3.0, 0.8, nw), 1, None)
    hard = np.clip(rng.normal(120, 25, nw), 40, None)
    for _ in range(3):
        s, ln = int(rng.integers(0, nw - 6)), int(rng.integers(3, 7))
        turb[s:s + ln] = rng.uniform(6.5, 10.0, ln)
        hard[s:s + ln] = rng.uniform(220, 290, ln)
    cond = np.clip(rng.normal(1100, 120, nw), 600, None)
    ph = np.clip(rng.normal(8.0, 0.15, nw), 7.0, None)
    lf_week = np.array([low_flow[w * 7:(w + 1) * 7].max() if w * 7 < N else 0 for w in range(nw)])
    fdp = np.clip(rng.uniform(0.2, 0.5, nw) + np.where(lf_week > 200, rng.uniform(0.2, 0.4, nw), 0), 0.1, None)
    wq = pd.DataFrame({"date": [day_date(w * 7) for w in range(nw)], "turbidity_ntu": turb.round(2), "hardness_mg_l": hard.round(0),
                       "conductivity_us_cm": cond.round(0), "ph": ph.round(2), "filter_dp_bar": fdp.round(2)})

    ops: list = []
    sched = _casting_schedule(rng, N, cast_h, cycles, stop_set, int(P["planned_stop_hours"]), day_date, ops)
    cycles = np.array([len(sched[d]["blocks"]) for d in range(N)])
    cast_h = np.array([sched[d]["minutes"] / 60.0 for d in range(N)])

    # ---- 세그먼트 초기화 -----------------------------------------------------
    nser = int(P["n_serials"])
    segs = [Seg(i, int(rng.random() < P["assembly_hidden_share"]), bearing_base=float(rng.uniform(55, 65)), vib_base=float(rng.uniform(1.2, 2.2)))
            for i in range(nser)]
    pos_seg: dict[int, Seg] = {}
    for p in range(1, NP + 1):
        s = segs[p - 1]
        s.status, s.pos, s.joint_age = "installed", p, float(rng.uniform(0, 520000))
        s.install_day, s.pressure_test = -int(rng.integers(20, 120)), int(rng.random() < P["pressure_test_share"])
        pos_seg[p] = s
    commission = {s.sid: day_date(-int(rng.integers(300, 2200))) for s in segs}

    installs, maint, leaks, daily = [], [], [], []
    for s in pos_seg.values():
        installs.append({"sid": s.sid, "position": s.pos, "install_ts": day_date(s.install_day), "remove_ts": None, "pressure_test": s.pressure_test, "_open": True})
    mid = [0]

    def log_m(d, s, part, typ, **kw):
        mid[0] += 1
        maint.append({"mnt_id": mid[0], "sid": s.sid, "date": day_date(d), "part": part, "type": typ, "resets_joint_age": kw.get("reset", 0),
                      "pressure_test": kw.get("pt", ""), "finding_grade": kw.get("grade", ""), "found_cause": kw.get("cause", ""), "wo_id": ""})

    def close_install(s, d):
        for r in reversed(installs):
            if r["sid"] == s.sid and r["_open"]:
                r["remove_ts"], r["_open"] = day_date(d), False
                break

    def remove(s, d, cause=None):
        grade = int(np.clip(round(s.joint_age / 650000 * 2.2 + rng.normal(0, 0.5) + (1.0 if cause in ("WEAR", "HAMMER") else 0)), 0, 3))
        if cause == "ASSEMBLY":
            grade = int(min(grade, 1))
        log_m(d, s, "seal", "inspect", grade=grade, cause=cause or "")
        close_install(s, d)
        pos = s.pos
        pos_seg.pop(pos, None)
        s.status, s.pos, s.ready_day, s.pull_day, s.pull_cause = "refurb", None, d + int(P["refurb_days"]) + (4 if cause else 0), None, None
        s.degraded = bool(s.ep)
        s.ep = None
        return pos

    def install(spare, pos, d):
        spare.status, spare.pos, spare.install_day = "installed", pos, d
        spare.pressure_test = int(rng.random() < P["pressure_test_share"])
        spare.ep, spare.protected = None, False
        pos_seg[pos] = spare
        installs.append({"sid": spare.sid, "position": pos, "install_ts": day_date(d), "remove_ts": None, "pressure_test": spare.pressure_test, "_open": True})
        log_m(d, spare, "oring", "inspect", pt=spare.pressure_test)

    def ready_spares(d, prefer=None):
        c = [s for s in segs if s.status == "spare" and s.ready_day <= d]
        return sorted(c, key=lambda s: s.sid)

    W, Hm, Bg, Th, Wa, As, Ra = P["wear"], P["hammer"], P["bearing"], P["thermal"], P["water"], P["assembly"], P["random"]
    demo_sid = None
    demo_pos = int(dm["position"])

    for d in range(N):
        # 1) 정비공장에서 돌아온 세그먼트: 씰·조인트·O링(필요시 베어링) 교체
        for s in segs:
            if s.status == "refurb" and s.ready_day <= d:
                s.status, s.joint_age = "spare", 0.0
                for part in ("seal", "rotary_joint", "oring"):
                    log_m(d, s, part, "replace", reset=1 if part != "oring" else 0)
                if s.degraded or rng.random() < 0.1:
                    log_m(d, s, "bearing", "replace")
                    s.bearing_base, s.vib_base = float(rng.uniform(55, 65)), float(rng.uniform(1.2, 2.2))
                if rng.random() < 0.5:
                    log_m(d, s, "hose", "replace")
        # 2) 누수로 비계획 철거 예정일
        for s in list(pos_seg.values()):
            if s.pull_day == d and s.pull_cause:
                sp = ready_spares(d)
                if sp:
                    pos = remove(s, d, s.pull_cause)
                    install(sp[0], pos, d)
                    log_m(d, s, "seal", "leak_repair", cause=s.pull_cause)
                else:
                    s.pull_day = d + 1
        # 3) 계획 정지: 기존 방식 = 씰·조인트 사용 톤수가 가장 많은 세그먼트 N개 교체 (누수 난 것 우선)
        if d in stop_set:
            ops.append({"ts": datetime.combine(day_date(d), datetime.min.time()) + timedelta(hours=2), "event_type": "planned_stop_start", "bundle_id": "", "note": f"{P['planned_stop_hours']}h"})
            ops.append({"ts": datetime.combine(day_date(d), datetime.min.time()) + timedelta(hours=2 + int(P["planned_stop_hours"])), "event_type": "planned_stop_end", "bundle_id": "", "note": ""})
            pending = [s for s in pos_seg.values() if s.pull_cause]
            order = sorted([s for s in pos_seg.values() if not s.pull_cause and not s.protected], key=lambda s: -s.joint_age)
            targets = pending + order[:max(0, int(P["replace_top_n"]) - len(pending))]
            if d == demo_stop_day:
                forced = pos_seg[demo_pos]
                targets = [forced] + [t for t in targets if t is not forced][:max(0, int(P["replace_top_n"]) - 1)]
            for s in targets:
                sp = ready_spares(d)
                if not sp:
                    break
                cause = s.pull_cause
                pos = remove(s, d, cause)
                new = sp[0]
                install(new, pos, d)
                if cause:
                    log_m(d, s, "seal", "leak_repair", cause=cause)
                if d == demo_stop_day and pos == demo_pos:
                    new.protected, demo_sid = True, new.sid
                    new.ep = {"t0": d, "D": int(P["demo_days"]) , "sev": float(dm["bearing_rise_c"]) / ((N - 1 - d) / float(P["demo_days"])), "vf": 2.2, "demo": True}
        # 4) 일별 신호·위험·누수
        day_ts0 = datetime.combine(day_date(d), datetime.min.time())
        tons = float(np.clip(cast_h[d] * P["tons_per_cast_hour"] * (speed[d] / 1.3), 4000, 8400))
        wk = min(d // 7, nw - 1)
        excess = max(0.0, (turb[wk] - 5) / 5) + max(0.0, (hard[wk] - 200) / 100)
        for p in range(1, NP + 1):
            s = pos_seg[p]
            b = BUNDLE_OF[p]
            bi = BUNDLE_IDX[b]
            # 베어링 열화 에피소드
            if s.ep is None and not s.protected and rng.random() < Bg["episode_rate_per_day"]:
                s.ep = {"t0": d, "D": int(rng.integers(14, 43)), "sev": float(rng.uniform(3, 10)), "vf": float(rng.uniform(1.5, 3.0))}
            prog = 0.0
            if s.ep:
                prog = min(1.0, max(0.0, (d - s.ep["t0"]) / s.ep["D"]))
            bear = s.bearing_base + 0.04 * (speed[d] - 1.3) * 10 + (s.ep["sev"] * prog if s.ep else 0.0) + rng.normal(0, 0.8)
            vib = (s.vib_base + rng.normal(0, 0.08)) * (1 + (s.ep["vf"] - 1) * prog if s.ep else 1.0)
            lf = float(low_flow[d, bi])
            dT = heat_base[bi] * (speed[d] / 1.3) ** 0.8 * (1 + 0.25 * min(lf, 600) / 600) + rng.normal(0, 0.3)
            t_out = 32.0 + dT
            age = s.joint_age
            dsi = d - s.install_day
            # 원인별 위험 증가량
            h = {}
            h["WEAR"] = ((age + tons) / W["eta_tons"]) ** W["beta"] - (age / W["eta_tons"]) ** W["beta"]
            h["HAMMER"] = Hm["k_per_low_flow_min"] * lf * (0.5 + age / 1e6)
            h["BEARING"] = Bg["k_peak"] * prog ** 4 if s.ep else 0.0
            h["THERMAL"] = Th["k_per_cycle"] * cycles[d] * (0.2 + age / 1e6)
            h["WATER"] = Wa["k_per_excess"] * excess
            h["ASSEMBLY"] = (((dsi + 1) / As["eta_days"]) ** As["beta"] - (max(dsi, 0) / As["eta_days"]) ** As["beta"]) * (As["pressure_test_factor"] if s.pressure_test else 1.0)
            h["RANDOM"] = Ra["rate_per_day"]
            mult = P["assembly_hidden_multiplier"] if s.assembly_flag else 1.0
            tot = sum(h.values()) * mult
            daily.append({"day": d, "date": day_date(d), "sid": s.sid, "position": p, "bundle_id": b, "tons": round(tons), "cast_hours": None,
                          "cast_speed_avg": round(float(speed[d]), 3), "thermal_cycles": int(cycles[d]), "low_flow_min": int(lf),
                          "pressure_events": int(pres_ev[d, bi]), "t_out_avg_c": None, "bearing_t_avg_c": round(float(bear), 2),
                          "vib_rms_mm_s": round(float(vib), 3), "joint_age_t": round(age), "days_since_install": int(dsi),
                          "_dT": float(dT), "_t_out": float(t_out)})
            if not s.protected and s.pull_cause is None and rng.random() < 1 - np.exp(-tot):
                w = np.array([h[c] for c in CAUSES])
                cause = CAUSES[int(rng.choice(len(CAUSES), p=w / w.sum()))]
                lpm = float(np.clip(rng.lognormal(np.log(8.0), 0.7), 1.5, 60.0))
                found = "sensor" if (lpm >= 10 and rng.random() < 0.7) else str(rng.choice(["patrol", "stop_check", "sensor"], p=[0.45, 0.4, 0.15]))
                if lpm >= 10 and found != "sensor":
                    found = "patrol"
                ts = day_ts0 + timedelta(minutes=int(rng.integers(0, 1440)))
                leaks.append({"ts": ts, "sid": s.sid, "position": p, "bundle_id": b, "part": str(rng.choice(CAUSE_PART[cause])), "cause_code": cause,
                              "leak_lpm": round(lpm, 1), "found_by": found})
                s.pull_cause = cause
                s.pull_day = d + 1 if lpm >= P["unplanned_pull_lpm"] else None
            s.joint_age += tons
    # ---- 정리 ----------------------------------------------------------------
    label = {s.sid: f"S-{s.sid + 1:04d}" for s in segs}
    if demo_sid is not None:
        want = int(dm["serial"].split("-")[1]) - 1
        other = want
        label[demo_sid], label[other] = label[other], label[demo_sid]
    fix = lambda df, col="sid": df.assign(segment_serial=df[col].map(label)).drop(columns=[col])
    # 일별 이력 (캐스팅 시간 등은 조업 일정에서)
    daily_df = pd.DataFrame(daily)
    daily_df["cast_hours"] = daily_df["day"].map(lambda x: round(sched[x]["minutes"] / 60.0, 3))
    daily_df["thermal_cycles"] = daily_df["day"].map(lambda x: len(sched[x]["blocks"]))
    daily_df["tons"] = daily_df.apply(lambda r: int(np.clip(r["cast_hours"] * P["tons_per_cast_hour"] * (r["cast_speed_avg"] / 1.3), 4000, 8400)), axis=1)
    mean_tin = {d: 32.0 + 1.5 * np.sin(2 * np.pi * d / 365.0) for d in range(N)}
    daily_df["t_out_avg_c"] = (daily_df["day"].map(mean_tin) + daily_df["_dT"]).round(2)
    daily_df = fix(daily_df).drop(columns=["_dT", "_t_out"])
    cols = ["date", "segment_serial", "position", "bundle_id", "tons", "cast_hours", "cast_speed_avg", "thermal_cycles", "low_flow_min",
            "pressure_events", "t_out_avg_c", "bearing_t_avg_c", "vib_rms_mm_s", "joint_age_t", "days_since_install"]
    daily_df = daily_df[cols + ["day"]]
    segments_df = pd.DataFrame([{"segment_serial": label[s.sid], "commission_date": commission[s.sid], "assembly_flag": s.assembly_flag} for s in segs]).sort_values("segment_serial")
    installs_df = fix(pd.DataFrame(installs).drop(columns=["_open"]))[["segment_serial", "position", "install_ts", "remove_ts", "pressure_test"]]
    installs_df["bundle_id"] = installs_df["position"].map(BUNDLE_OF)
    maint_df = fix(pd.DataFrame(maint))[["mnt_id", "segment_serial", "date", "part", "type", "resets_joint_age", "pressure_test", "finding_grade", "found_cause", "wo_id"]]
    leaks_df = pd.DataFrame(leaks)
    if len(leaks_df):
        leaks_df = fix(leaks_df)
        leaks_df.insert(0, "leak_id", [f"L-{i + 1:04d}" for i in range(len(leaks_df))])
        leaks_df = leaks_df[["leak_id", "ts", "segment_serial", "position", "bundle_id", "part", "cause_code", "leak_lpm", "found_by"]]
    ops_df = pd.DataFrame(ops).sort_values("ts").reset_index(drop=True)
    out = {"segments": segments_df, "installs": installs_df.sort_values(["install_ts", "position"]).reset_index(drop=True), "maintenance": maint_df,
           "leaks": leaks_df, "segment_daily": daily_df, "water_quality": wq, "ops_events": ops_df,
           "work_orders": pd.DataFrame(columns=["wo_id", "created_ts", "segment_serial", "position", "planned_stop_date", "prob", "prob_avg", "rank", "top_cause",
                                                "contributions", "cards_used", "docs_cited", "draft_md", "numbers_ok", "off_card", "approver", "approved_ts",
                                                "status", "result_grade", "result_cause", "result_note"])}
    if with_minute:
        out["sensor_1min"] = _minute_series(rng, P, N, demo_start, daily_df, sched, speed, day_date)
    out["_meta"] = {"params": P, "start_date": str(d0), "end_date": str(end), "planned_stops": [str(day_date(s)) for s in stops],
                    "next_planned_stop": str(day_date(next_stop)), "demo_serial": dm["serial"], "demo_stop_day": str(day_date(demo_stop_day))}
    return out


def _casting_schedule(rng, N, cast_h, cycles, stop_set, stop_hours, day_date, ops):
    """일별 주조 구간(분 단위 블록). 정지·재가동 횟수 = 블록 수. 계획 정지일은 앞쪽 8시간+2시간 대기를 비워 둔다."""
    sched = {}
    for d in range(N):
        total = int(round(cast_h[d] * 60))
        n = int(cycles[d])
        free_lo = 2 * 60 + stop_hours * 60 if d in stop_set else 0       # 계획 정지일: 정지가 끝난 뒤에 주조
        avail = 1440 - free_lo
        total = min(total, avail - 5 * n)
        lens = np.maximum(10, np.round(rng.dirichlet(np.ones(n)) * total)).astype(int)
        total = int(lens.sum())
        gaps = rng.dirichlet(np.ones(n + 1)) * (avail - total)
        gaps = np.floor(gaps).astype(int)
        gaps[1:n] = np.maximum(gaps[1:n], 2)                      # 블록 사이는 최소 2분 비워 정지·재가동이 합쳐지지 않게 한다
        t, blocks = free_lo + int(gaps[0]), []
        for i in range(n):
            blocks.append((t, t + int(lens[i])))
            t += int(lens[i]) + int(gaps[i + 1])
        blocks = [(a, min(b, 1440)) for a, b in blocks if a < 1440]
        sched[d] = {"blocks": blocks, "minutes": sum(b - a for a, b in blocks)}
        base = datetime.combine(day_date(d), datetime.min.time())
        for a, b in blocks:
            ops.append({"ts": base + timedelta(minutes=a), "event_type": "cast_start", "bundle_id": "", "note": ""})
            ops.append({"ts": base + timedelta(minutes=b), "event_type": "cast_stop", "bundle_id": "", "note": ""})
        if d % 3 == 1:
            ops.append({"ts": base + timedelta(minutes=int(rng.integers(0, 1440))), "event_type": "grade_change", "bundle_id": "", "note": rng.choice(["A", "B"])})
    return sched


def _minute_series(rng, P, N, demo_start, daily_df, sched, speed, day_date) -> pd.DataFrame:
    """최근 14일 묶음별 1분 시계열. 1분 값을 하루로 모으면 segment_daily와 같은 값이 되게 만든다."""
    rows = []
    q_seg = 30.0
    nom_flow = {b: q_seg * len(ps) for b, ps in BUNDLES.items()}
    for d in range(demo_start, N):
        day = daily_df[daily_df["day"] == d]
        base = datetime.combine(day_date(d), datetime.min.time())
        mask = np.zeros(1440, dtype=bool)
        for a, b in sched[d]["blocks"]:
            mask[a:b] = True
        cm = int(mask.sum())
        cast_idx = np.flatnonzero(mask)
        t_in = 32.0 + 1.5 * np.sin(2 * np.pi * d / 365.0) + 1.2 * np.sin(2 * np.pi * (np.arange(1440) - 300) / 1440.0)
        for b, ps in BUNDLES.items():
            dd = day[day["bundle_id"] == b]
            lf, pe = int(dd["low_flow_min"].iloc[0]), int(dd["pressure_events"].iloc[0])
            t_out_d, bear_d, vib_d = float(dd["t_out_avg_c"].mean()), float(dd["bearing_t_avg_c"].mean()), float(dd["vib_rms_mm_s"].mean())
            v = np.zeros(1440)
            v[cast_idx] = np.clip(speed[d] + rng.normal(0, 0.03, cm), 1.0, 1.6)
            if cm:
                v[cast_idx] += float(speed[d]) - v[cast_idx].mean()
            phi = np.where(mask, 1 + 0.5 * (v / 1.3 - 1), 0.35)
            q_nom = nom_flow[b] * phi
            q_in = q_nom * (1 + rng.normal(0, 0.0025, 1440))
            lf = min(lf, cm)
            if lf and cm:
                k = int(rng.integers(1, 4))
                cuts = np.sort(rng.choice(np.arange(1, lf), size=min(k - 1, lf - 1), replace=False)) if lf > 1 and k > 1 else np.array([], dtype=int)
                parts = np.diff(np.concatenate([[0], cuts, [lf]]))
                pool = cast_idx.copy()
                picked = []
                for ln in parts:
                    st = int(rng.integers(0, max(1, len(pool) - ln)))
                    picked.extend(pool[st:st + ln])
                    pool = np.delete(pool, np.arange(st, min(st + ln, len(pool))))
                picked = np.array(picked[:lf])
                q_in[picked] = q_nom[picked] * rng.uniform(0.78, 0.87, len(picked))
            q_out = q_in * (1 - 0.0015) * (1 + rng.normal(0, 0.0025, 1440))
            t_out = np.where(mask, t_in + 10.0, t_in + 2.0) + rng.normal(0, 0.15, 1440)
            if cm:
                t_out[mask] += t_out_d - t_out[mask].mean()
            p_in = 8.0 + rng.normal(0, 0.02, 1440) - 0.15 * (q_nom < 0.5 * nom_flow[b])
            p_out = 2.0 + rng.normal(0, 0.02, 1440)
            if pe:
                starts = np.sort(rng.choice(np.arange(5, 1430, 7), size=min(pe, 200), replace=False))
                for st in starts:
                    sgn = rng.choice([-1, 1])
                    for j, amp in enumerate((0.7, 0.4, 0.15)):
                        p_in[st + j] += sgn * amp
            bear = bear_d + rng.normal(0, 0.3, 1440)
            bear += bear_d - bear.mean()
            vib = np.clip(vib_d + rng.normal(0, 0.05, 1440), 0.1, None)
            ts = [base + timedelta(minutes=i) for i in range(1440)]
            rows.append(pd.DataFrame({"ts": ts, "bundle_id": b, "q_in_m3h": q_in.round(3), "q_out_m3h": q_out.round(3), "t_in_c": t_in.round(2),
                                      "t_out_c": t_out.round(2), "p_in_bar": p_in.round(3), "p_out_bar": p_out.round(3), "cast_speed_mpm": v.round(3),
                                      "casting": mask.astype(int), "bearing_t_c": bear.round(2), "vib_rms_mm_s": vib.round(3)}))
    return pd.concat(rows, ignore_index=True)


def write(out: dict, dir_: Path = OUT_DIR) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    for name, df in out.items():
        if name.startswith("_"):
            continue
        df.drop(columns=["day"], errors="ignore").to_csv(dir_ / f"{name}.csv", index=False, encoding="utf-8")
    (dir_ / "meta.json").write_text(json.dumps(out["_meta"], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return dir_


def summary(out: dict) -> dict:
    lk = out["leaks"]
    return {"leaks": len(lk), "by_cause": lk["cause_code"].value_counts().to_dict() if len(lk) else {},
            "segment_daily_rows": len(out["segment_daily"]), "installs": len(out["installs"]), "maintenance": len(out["maintenance"])}


def validate(out: dict) -> dict:
    """생성한 데이터가 명세(5-1)와 맞는지 검사한다."""
    sd, mn, lk = out["segment_daily"], out.get("sensor_1min"), out["leaks"]
    res: dict = {"leaks_total": len(lk), "leaks_by_cause": lk["cause_code"].value_counts().to_dict(), "leaks_per_month": round(len(lk) / (len(sd["day"].unique()) / 30.4), 2)}
    res["tons_range"] = [int(sd["tons"].min()), int(sd["tons"].max())]
    res["cast_hours_range"] = [round(float(sd["cast_hours"].min()), 1), round(float(sd["cast_hours"].max()), 1)]
    res["bearing_range"] = [round(float(sd["bearing_t_avg_c"].min()), 1), round(float(sd["bearing_t_avg_c"].max()), 1)]
    res["serials_installed_per_day"] = sd.groupby("day")["segment_serial"].nunique().unique().tolist()
    res["maintenance_parts"] = out["maintenance"]["part"].value_counts().to_dict()
    if mn is not None:
        mn = mn.copy()
        mn["date"] = pd.to_datetime(mn["ts"]).dt.date
        d = sd[sd["day"] >= sd["day"].max() - 13]
        bad = {"low_flow_min": 0, "pressure_events": 0, "bearing": 0, "t_out": 0, "cast_hours": 0, "thermal_cycles": 0}
        n = 0
        for (date_, b), g in mn.groupby(["date", "bundle_id"]):
            dd = d[(d["date"] == date_) & (d["bundle_id"] == b)]
            n += 1
            nom = g["q_in_m3h"] / np.where(g["casting"] == 1, 1, 1)
            # 정상 유량(잡음 없는 설정값) 대비 90% 미만 분: 같은 날 같은 묶음 중앙값 기준
            q_cast = g.loc[g["casting"] == 1, "q_in_m3h"]
            med = float(q_cast.median()) if len(q_cast) else 0.0
            lf = int((g.loc[g["casting"] == 1, "q_in_m3h"] < 0.9 * med * (g.loc[g["casting"] == 1, "cast_speed_mpm"] * 0 + 1)).sum())
            pe = int((g["p_in_bar"].diff().abs() >= 0.5).sum())
            bad["pressure_events"] += int(pe != int(dd["pressure_events"].iloc[0]))
            bad["bearing"] += int(abs(g["bearing_t_c"].mean() - dd["bearing_t_avg_c"].mean()) > 0.05)
            cm = g["casting"].sum()
            bad["t_out"] += int(abs(g.loc[g["casting"] == 1, "t_out_c"].mean() - dd["t_out_avg_c"].mean()) > 0.05) if cm else 0
            bad["cast_hours"] += int(abs(cm / 60.0 - float(dd["cast_hours"].iloc[0])) > 0.02)
            bad["thermal_cycles"] += int(int((g["casting"].diff().fillna(g["casting"].iloc[0]) == 1).sum()) != int(dd["thermal_cycles"].iloc[0]))
            bad["low_flow_min"] += int(abs(lf - int(dd["low_flow_min"].iloc[0])) > max(8, 0.25 * int(dd["low_flow_min"].iloc[0])))
        res["minute_vs_daily_mismatch"] = {"bundle_days": n, **bad}
    return res
