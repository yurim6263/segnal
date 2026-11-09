"""세그먼트 누수 위험 모델 (기획서 4-5): 원인별 위험률을 더해 "다음 계획 정지 전 누수 확률"과 유력 원인을 구한다.

  세그먼트 위험 = Σ_c (원인 c의 기본 위험률 × exp(계수 · 그 원인의 전조 신호))
  다음 정지 전 누수 확률 = 1 − exp(−Σ_c ΔH_c)      유력 원인 = 가장 큰 ΔH_c      요인 기여도 = ΔH_c / ΣΔH

원인별 형태(계수는 우리가 정하지 않고 이력에서 최대우도로 추정한다):
  마모형  WEAR      와이블 기본 위험률(씰·조인트 교체 후 누적 톤수), 전조 신호 없음
  초기불량형 ASSEMBLY  와이블 기본 위험률(장착 후 경과일) × exp(c · 장착 후 압력 시험)
  스트레스형 HAMMER·THERMAL·WATER·BEARING  기본 위험률 상수 × exp(b · 전조 신호)
        (유량 저하 시간, 열 사이클, 수질 초과량, 베어링 온도 상승·진동)
  우연형  RANDOM    일정 비율
전조 신호는 모두 전날까지의 값으로 만든다(예측 시점에 알 수 있는 값만 쓴다).
누수 건수가 적으므로 계수에 약한 사전분포(릿지)를 걸고, 와이블 모양 값 β는 불확실성 범위(90%)와 함께 낸다.
새 라이브러리 없이 numpy·scipy·pandas·statsmodels(수치 헤시안)만 쓴다. 모든 데이터는 합성이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

CAUSES = ["WEAR", "HAMMER", "BEARING", "THERMAL", "WATER", "ASSEMBLY", "RANDOM"]
CAUSE_LABEL = {"WEAR": "씰 정상 마모", "HAMMER": "스팀 해머성 씰 파손", "BEARING": "베어링 손상 → 씰 하중", "THERMAL": "열 사이클 피로",
               "WATER": "이물질·스케일(수질)", "ASSEMBLY": "조립 불량", "RANDOM": "우연형"}
CARD = {"WEAR": "AC-01", "HAMMER": "AC-02", "BEARING": "AC-03", "THERMAL": "AC-04", "WATER": "AC-05", "ASSEMBLY": "AC-06", "RANDOM": None}
# 원인별 전조 신호 (특징 열 이름, 사람이 읽는 이름)
COVS = {
    "HAMMER": [("x_low", "냉각 유량 저하 시간(분/일)")],
    "THERMAL": [("x_cyc", "열 사이클(주조 시작·정지 횟수/일)")],
    "WATER": [("x_exc", "수질 관리 상한 초과량")],
    "BEARING": [("x_brise", "베어링 온도 상승(℃)"), ("x_vib", "진동 증가율")],
    "ASSEMBLY": [("pt", "장착 후 압력 시험")],
}
TON = 1e5          # 톤수 단위(10만 t)


# ---- 데이터 -----------------------------------------------------------------
@dataclass
class Data:
    daily: pd.DataFrame
    installs: pd.DataFrame
    leaks: pd.DataFrame
    water: pd.DataFrame
    stops: list[int]               # 계획 정지일(day 번호)
    next_stop_day: int
    n_days: int
    start_date: pd.Timestamp


def load(dir_: Path | str | None = None) -> Data:
    import json
    d = Path(dir_ or Path(__file__).resolve().parents[2] / "data" / "health")
    daily = pd.read_csv(d / "segment_daily.csv", parse_dates=["date"])
    installs = pd.read_csv(d / "installs.csv", parse_dates=["install_ts", "remove_ts"])
    leaks = pd.read_csv(d / "leaks.csv", parse_dates=["ts"])
    water = pd.read_csv(d / "water_quality.csv", parse_dates=["date"])
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    return from_frames(daily, installs, leaks, water, meta)


def from_frames(daily, installs, leaks, water, meta) -> Data:
    start = pd.Timestamp(meta["start_date"])
    day_of = lambda s: int((pd.Timestamp(s) - start).days)
    daily = daily.assign(day=(daily["date"] - start).dt.days.astype(int))
    stops = [day_of(s) for s in meta["planned_stops"]]
    return Data(daily, installs, leaks, water, stops, day_of(meta["next_planned_stop"]), int(daily["day"].max()) + 1, start)


# ---- 특징 (전날까지의 값만 사용) ---------------------------------------------
def build_rows(data: Data, future: bool = True) -> pd.DataFrame:
    """세그먼트·일 단위 행. 열: t0/t1(누적 톤수, 10만 t), s0/s1(장착 후 경과일), 전조 특징, event(원인 코드 또는 빈칸).
    future=True면 마지막 날 다음 날(예측 기준일) 행을 장착 중인 세그먼트마다 하나 더 만든다(event 없음)."""
    df = data.daily.sort_values(["segment_serial", "day"]).copy()
    last_day = int(df["day"].max())
    df["spell"] = (df.groupby("segment_serial")["days_since_install"].diff().fillna(0) < 0).groupby(df["segment_serial"]).cumsum()
    if future:
        cur = df[df["day"] == last_day].copy()
        cur["day"] = last_day + 1
        cur["date"] = cur["date"] + pd.Timedelta(days=1)
        cur["joint_age_t"] = cur["joint_age_t"] + cur["tons"]
        cur["days_since_install"] = cur["days_since_install"] + 1
        for c in ("low_flow_min", "thermal_cycles", "bearing_t_avg_c", "vib_rms_mm_s", "pressure_events"):
            cur[c] = np.nan
        cur["tons"] = df[df["day"] > last_day - 7]["tons"].mean()
        df = pd.concat([df, cur], ignore_index=True).sort_values(["segment_serial", "day"])
    df["t0"] = df["joint_age_t"] / TON
    df["t1"] = (df["joint_age_t"] + df["tons"]) / TON
    df["s0"] = df["days_since_install"].astype(float)
    df["s1"] = df["s0"] + 1.0
    # 묶음·플랜트 수준 이동 평균(전날까지 3일)
    b = data.daily.groupby(["day", "bundle_id"])["low_flow_min"].first().unstack()
    lf = b.rolling(3, min_periods=1).mean().shift(1).stack().rename("x_low").reset_index()
    lf["x_low"] /= 100.0
    p = data.daily.groupby("day")["thermal_cycles"].first()
    cy = p.rolling(3, min_periods=1).mean().shift(1).rename("x_cyc").reset_index()
    df = df.merge(lf, on=["day", "bundle_id"], how="left").merge(cy, on="day", how="left")
    df["x_low"] = df["x_low"].fillna(0.0)        # 첫날은 전날 값이 없으므로 0
    df["x_cyc"] = df["x_cyc"].fillna(df["x_cyc"].median())
    # 마지막 날 다음 날 행은 마지막 값으로 채운다
    fut = df["day"] > last_day
    if fut.any():
        lf_last = b.iloc[-3:].mean() / 100.0
        df.loc[fut, "x_low"] = df.loc[fut, "bundle_id"].map(lf_last)
        df.loc[fut, "x_cyc"] = p.iloc[-3:].mean()
    # 수질: 전날까지 가장 최근 주간 표본
    w = data.water.sort_values("date").copy()
    w["x_exc"] = np.maximum(0, (w["turbidity_ntu"] - 5) / 5) + np.maximum(0, (w["hardness_mg_l"] - 200) / 100)
    df["_asof"] = df["date"] - pd.Timedelta(days=1)
    df = pd.merge_asof(df.sort_values("_asof"), w[["date", "x_exc"]].rename(columns={"date": "_wd"}), left_on="_asof", right_on="_wd", direction="backward")
    df["x_exc"] = df["x_exc"].fillna(0.0)
    df = df.sort_values(["segment_serial", "day"]).reset_index(drop=True)
    # 베어링: 같은 장착 기간 안에서 최근 3일 평균 − 기준(2주 전 3일 평균, 짧으면 장착 직후 3일 평균)
    br, vr = np.zeros(len(df)), np.zeros(len(df))
    for _, idx in df.groupby(["segment_serial", "spell"]).indices.items():
        g = df.iloc[idx]
        bt, vb = g["bearing_t_avg_c"].to_numpy(), g["vib_rms_mm_s"].to_numpy()
        n = len(g)
        for k in range(n):
            if k < 5:
                continue
            cur_b, cur_v = np.nanmean(bt[max(0, k - 3):k]), np.nanmean(vb[max(0, k - 3):k])
            if k >= 17:
                base_b, base_v = np.nanmean(bt[k - 17:k - 14]), np.nanmean(vb[k - 17:k - 14])
            else:
                base_b, base_v = np.nanmean(bt[0:3]), np.nanmean(vb[0:3])
            br[idx[k]], vr[idx[k]] = cur_b - base_b, cur_v / base_v - 1.0
    df["x_brise"], df["x_vib"] = br, vr
    # 장착 후 압력 시험(정답이 아니라 장착 기록)
    ins = data.installs.sort_values("install_ts")[["segment_serial", "install_ts", "pressure_test"]].rename(columns={"pressure_test": "pt"})
    df = pd.merge_asof(df.sort_values("date"), ins, left_on="date", right_on="install_ts", by="segment_serial", direction="backward").sort_values(["segment_serial", "day"])
    df["pt"] = df["pt"].fillna(0).astype(float)
    # 사건
    lk = data.leaks.assign(day=((data.leaks["ts"].dt.normalize() - data.start_date).dt.days).astype(int))[["segment_serial", "day", "cause_code"]]
    df = df.merge(lk, on=["segment_serial", "day"], how="left").rename(columns={"cause_code": "event"})
    df["event"] = df["event"].fillna("")
    return df.reset_index(drop=True)


# ---- 원인별 모형 ----------------------------------------------------------------
@dataclass
class CauseModel:
    cause: str
    form: str                                  # weibull_tons | weibull_days | exp
    cov: list[str]
    theta: np.ndarray = field(default_factory=lambda: np.zeros(1))
    se: np.ndarray = field(default_factory=lambda: np.zeros(1))
    n_events: int = 0

    @property
    def beta(self) -> float | None:
        return float(np.exp(self.theta[0])) if self.form.startswith("weibull") else None

    def _lin(self, X: np.ndarray, theta: np.ndarray) -> np.ndarray:
        k = 2 if self.form.startswith("weibull") else 1
        return X @ theta[k:] if X.shape[1] else np.zeros(len(X))

    def cumhaz(self, t0, t1, X, theta=None) -> np.ndarray:
        th = self.theta if theta is None else theta
        lin = self._lin(X, th)
        if self.form == "exp":
            return np.exp(th[0] + lin) * (t1 - t0)
        beta, eta = np.exp(th[0]), np.exp(th[1])
        return ((np.maximum(t1, 1e-9) / eta) ** beta - (np.maximum(t0, 1e-9) / eta) ** beta) * np.exp(lin)


def _nll(theta, m: CauseModel, t0, t1, X, ev, ridge=1.0):
    lin = m._lin(X, theta)
    ch = m.cumhaz(t0, t1, X, theta)
    tm = np.maximum((t0 + t1) / 2, 1e-6)
    if m.form == "exp":
        ll = float((theta[0] + lin[ev]).sum())
        pen = 0.5 * ridge * float(np.sum((theta[1:] / 3.0) ** 2)) + 0.5 * ((theta[0] + 6.0) / 4.0) ** 2
    else:
        beta, eta = np.exp(theta[0]), np.exp(theta[1])
        ll = float((np.log(beta) - np.log(eta) + (beta - 1) * (np.log(tm[ev]) - np.log(eta)) + lin[ev]).sum())
        pen = 0.5 * ridge * float(np.sum((theta[2:] / 3.0) ** 2)) + 0.5 * (theta[0] / 1.5) ** 2 + 0.5 * ((theta[1] - np.log(15.0 if m.form == "weibull_tons" else 100.0)) / 2.0) ** 2
    return -(ll - float(ch.sum())) + pen


def fit_cause(rows: pd.DataFrame, cause: str, form: str, cov: list[str], use_vib: bool = True) -> CauseModel:
    cov = [c for c in cov if use_vib or c not in ("x_vib", "x_brise")]   # use_vib=False: 베어링 온도·진동 센서가 없는 설비
    m = CauseModel(cause, form, cov)
    t0, t1 = (rows["t0"].to_numpy(), rows["t1"].to_numpy()) if form == "weibull_tons" else (rows["s0"].to_numpy(), rows["s1"].to_numpy())
    if form == "weibull_days":
        t0, t1 = t0 / 100.0, t1 / 100.0
    X = rows[cov].to_numpy(float) if cov else np.zeros((len(rows), 0))
    ev = (rows["event"] == cause).to_numpy()
    m.n_events = int(ev.sum())
    k = (2 if form.startswith("weibull") else 1) + X.shape[1]
    x0 = np.zeros(k)
    if form == "exp":
        x0[0] = np.log(max(m.n_events, 0.5) / max(len(rows), 1))
    else:
        x0[1] = np.log(15.0 if form == "weibull_tons" else 100.0)
    bounds = ([(np.log(0.2), np.log(6.0)), (-3, 8)] if form.startswith("weibull") else [(-16, 0)]) + [(-8, 8)] * X.shape[1]
    r = minimize(_nll, x0, args=(m, t0, t1, X, ev), method="L-BFGS-B", bounds=bounds)
    m.theta = r.x
    try:
        from statsmodels.tools.numdiff import approx_hess
        H = approx_hess(r.x, lambda th: _nll(th, m, t0, t1, X, ev))
        m.se = np.sqrt(np.clip(np.diag(np.linalg.pinv(H)), 0, None))
    except Exception:
        m.se = np.full(k, np.nan)
    return m


def beta_by_cause(rows: pd.DataFrame, cause: str) -> dict:
    """원인별 와이블 모양 값 β(공변량 없이, 교체 후 누적 톤수 기준)와 90% 범위. 다른 원인의 누수는 관측 중단으로 본다."""
    m = fit_cause(rows, cause, "weibull_tons", [])
    se = float(m.se[0]) if len(m.se) and np.isfinite(m.se[0]) else float("nan")
    b = float(np.exp(m.theta[0]))
    lo, hi = (b * np.exp(-1.645 * se), b * np.exp(1.645 * se)) if np.isfinite(se) else (float("nan"), float("nan"))
    return {"cause": cause, "n_events": m.n_events, "beta": round(b, 2), "beta_lo": round(lo, 2), "beta_hi": round(hi, 2), "type": beta_type(b)}


def beta_type(b: float) -> str:
    """기획서 4-5 (5): β > 1.2 마모형, 0.8~1.2 우연형, < 0.8 초기 불량형 [가정]."""
    return "마모형" if b > 1.2 else ("우연형" if b >= 0.8 else "초기불량형")


# ---- 전체 모델 ----------------------------------------------------------------------
@dataclass
class RiskModel:
    models: dict[str, CauseModel]
    use_vib: bool = True

    def delta_h(self, row: pd.Series | pd.DataFrame, days: float, tons_per_day: float) -> dict[str, np.ndarray]:
        """다음 `days`일 동안의 원인별 누적 위험 증가량. 전조 신호는 그 날의 특징을 그대로 이어 간다고 본다."""
        df = row.to_frame().T if isinstance(row, pd.Series) else row
        out = {}
        for c, m in self.models.items():
            X = df[m.cov].to_numpy(float) if m.cov else np.zeros((len(df), 0))
            if m.form == "exp":
                out[c] = m.cumhaz(np.zeros(len(df)), np.full(len(df), days), X)
            elif m.form == "weibull_tons":
                a0 = df["t0"].to_numpy(float)
                out[c] = m.cumhaz(a0, a0 + days * tons_per_day / TON, X)
            else:
                s0 = df["s0"].to_numpy(float) / 100.0
                out[c] = m.cumhaz(s0, s0 + days / 100.0, X)
        return out

    def predict(self, rows: pd.DataFrame, days: float, tons_per_day: float = 7000.0) -> pd.DataFrame:
        dh = self.delta_h(rows, days, tons_per_day)
        tot = sum(dh.values())
        res = pd.DataFrame({"prob": 1 - np.exp(-tot)}, index=rows.index)
        for c in CAUSES:
            res[f"share_{c}"] = dh[c] / np.maximum(tot, 1e-12)
        res["top_cause"] = res[[f"share_{c}" for c in CAUSES]].idxmax(axis=1).str.replace("share_", "")
        return res


SPEC = {"WEAR": ("weibull_tons", []), "ASSEMBLY": ("weibull_days", ["pt"]), "RANDOM": ("exp", []), "HAMMER": ("exp", ["x_low"]),
        "THERMAL": ("exp", ["x_cyc"]), "WATER": ("exp", ["x_exc"]), "BEARING": ("exp", ["x_brise", "x_vib"])}


def fit(rows: pd.DataFrame, use_vib: bool = True) -> RiskModel:
    ms = {}
    for c in CAUSES:
        form, cov = SPEC[c]
        ms[c] = fit_cause(rows, c, form, cov, use_vib=use_vib)
    return RiskModel(ms, use_vib)


def describe(model: RiskModel) -> list[dict]:
    """추정한 계수를 읽기 쉬운 표로. exp(계수)는 신호가 1 단위 늘 때 위험이 몇 배가 되는가."""
    out = []
    for c, m in model.models.items():
        k = 2 if m.form.startswith("weibull") else 1
        row = {"cause": c, "label": CAUSE_LABEL[c], "form": m.form, "n_events": m.n_events, "beta": None if m.beta is None else round(m.beta, 2), "effects": []}
        for i, name in enumerate(m.cov):
            lab = dict(COVS[c])[name]
            out_i = k + i
            row["effects"].append({"signal": lab, "hazard_ratio": round(float(np.exp(m.theta[out_i])), 2), "se": round(float(m.se[out_i]), 2) if len(m.se) > out_i else None})
        out.append(row)
    return out


# ---- 현재 상태 → 위험 순위판 ------------------------------------------------------
def snapshot(model: RiskModel, rows: pd.DataFrame, data: Data, horizon_days: float | None = None) -> list[dict]:
    """마지막 날 다음 날(예측 기준일) 장착 세그먼트별 위험. 기본 기간은 다음 계획 정지까지(정지 당일 포함)."""
    last = int(rows["day"].max())
    cur = rows[rows["day"] == last].copy()
    h = float(horizon_days if horizon_days is not None else max(1, data.next_stop_day - last + 1))
    tpd = float(data.daily[data.daily["day"] > data.daily["day"].max() - 7]["tons"].mean())
    pr = model.predict(cur, h, tpd)
    pr14 = model.predict(cur, 14.0, tpd)
    dh = model.delta_h(cur, h, tpd)
    out = []
    for i, (idx, r) in enumerate(cur.iterrows()):
        shares = {c: float(pr.loc[idx, f"share_{c}"]) for c in CAUSES}
        top = sorted(shares.items(), key=lambda kv: -kv[1])[:3]
        out.append({
            "segment": r["segment_serial"], "position": int(r["position"]), "bundle": r["bundle_id"],
            "prob_next_stop": round(min(float(pr.loc[idx, "prob"]), 0.99), 4), "prob_14d": round(min(float(pr14.loc[idx, "prob"]), 0.99), 4),   # 표시 상한 99%: 학습 범위 밖 외삽 방지
            "horizon_days": h, "joint_age_t": int(r["t0"] * TON), "days_since_install": int(r["s0"]),
            "top_cause": pr.loc[idx, "top_cause"], "top_cause_label": CAUSE_LABEL[pr.loc[idx, "top_cause"]],
            "causes": [{"cause": c, "label": CAUSE_LABEL[c], "share": round(s, 3), "card": CARD[c]} for c, s in top],
            "signals": {"low_flow_index": round(float(r["x_low"]) * 100, 0), "bearing_rise_c": round(float(r["x_brise"]), 2),
                        "vib_increase": round(float(r["x_vib"]), 3), "pressure_test": int(r["pt"])},
        })
    out.sort(key=lambda d: -d["prob_next_stop"])
    for k, d in enumerate(out, 1):
        d["rank"] = k
    return out


def age_rank(rows: pd.DataFrame) -> pd.Series:
    """현행 기준(교체 후 누적 톤수가 큰 순서)의 순위. 1이 가장 위험."""
    return rows["t0"].rank(ascending=False, method="first")
