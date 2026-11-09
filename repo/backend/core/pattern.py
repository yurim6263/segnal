"""D안: 여러 신호의 '움직임 방향'으로 누수와 계측 이상(유량계·압력계·온도계 오차)을 가른다.

경보가 오른 뒤 쌓인 구간의 평균 잔차를 9개 신호 벡터로 만든다.
  [공급-회수 불균형, 입구 유량, 출구 유량, 공급 압력, 회수 압력, 온도차, 출구 온도, 다른 묶음 입구 유량, 다른 묶음 공급 압력]
정상 때 같이 흔들리는 부분을 공분산으로 빼 주고(백색화), 고장별 기준 방향과의 각도가 가장 작은 쪽을 고른다.
1위와 2위의 각도 차이가 작으면 '구분 불가'로 남긴다.

기준 방향은 시뮬레이터에 고장을 주입해 얻는다(현장 정비 이력이 생기면 그 사건으로 바꾼다).
이 방향은 시뮬레이터의 펌프 곡선(비제어 공급) 가정에 기댄다. 유량조절밸브가 입구 유량을 고정하는 구조라면
누수의 방향이 달라지므로 현업 확인이 필요하다(eval/discrimination_study.py의 제어 변형 참고).
모든 데이터는 합성이다.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field

import numpy as np

from sim.circuit import Event
from sim.scenarios import DATA_DIR, DAY, ScenarioSpec, _leak, sensors_for, simulate_spec

EXT = ["imb_mass", "m_in", "m_out", "p_in", "p_out", "dt", "t_out"]      # 기준선을 학습하는 채널(core.baseline.CHANNELS와 같다)
CH9 = EXT + ["oth_m_in", "oth_p_in"]
CH_LABEL = {
    "imb_mass": "공급-회수 불균형", "m_in": "입구 유량", "m_out": "출구 유량", "p_in": "공급 압력", "p_out": "회수 압력",
    "dt": "온도차", "t_out": "출구 온도", "oth_m_in": "다른 묶음 입구 유량", "oth_p_in": "다른 묶음 공급 압력",
}
WINDOWS = (120, 240, 360)          # 분. 경보 이후 이만큼 쌓여야 판정한다
SIZES = (0.005, 0.01, 0.02)        # 묶음 유량 대비 비율(누수량·유량계 오차)
SHRINK = 0.2
AMBIGUOUS_DEG = 3.0                # 1위와 2위 각도 차이가 이보다 작으면 구분 불가 (홀드아웃 100건에서 오답 2% 이하가 되는 가장 작은 값, eval/pattern_calibrate.py)
REPS = 2
LIB_VERSION = 3

CLASS_LABEL = {
    "leak": "누수", "flow_in|+": "입구 유량계 +오차", "flow_in|-": "입구 유량계 −오차",
    "flow_out|+": "출구 유량계 +오차", "flow_out|-": "출구 유량계 −오차",
    "p_in|+": "공급 압력계 +오차", "p_in|-": "공급 압력계 −오차", "p_out|+": "회수 압력계 +오차", "p_out|-": "회수 압력계 −오차",
    "t_in|+": "입구 온도계 +오차", "t_in|-": "입구 온도계 −오차", "t_out|+": "출구 온도계 +오차", "t_out|-": "출구 온도계 −오차",
}
CLASSES = list(CLASS_LABEL)
# 라벨별 (주입 크기들): 유량 계열은 묶음 유량 대비 비율, 압력은 bar, 온도는 ℃
LABELS = {
    "leak|in": SIZES, "leak|out": SIZES,
    "flow_in|+": SIZES, "flow_in|-": SIZES, "flow_out|+": SIZES, "flow_out|-": SIZES,
    "p_in|+": (0.1,), "p_in|-": (0.1,), "p_out|+": (0.1,), "p_out|-": (0.1,),
    "t_in|+": (0.5,), "t_in|-": (0.5,), "t_out|+": (0.5,), "t_out|-": (0.5,),
}


def merged(label: str) -> str:
    return "leak" if label.startswith("leak") else label


def zmatrix(bl, df, g: int, groups: list[int]) -> np.ndarray:
    """(T, 9) 기준선 잔차 z. 마지막 둘은 다른 묶음의 입구 질량유량·공급 압력 평균."""
    r = bl.residuals(df, g)
    cols = [r[f"z_{c}"].to_numpy() for c in EXT]
    oth = [h for h in groups if h != g]
    om = np.mean([bl.residuals(df, h)["z_m_in"].to_numpy() for h in oth], axis=0)
    op = np.mean([bl.residuals(df, h)["z_p_in"].to_numpy() for h in oth], axis=0)
    return np.column_stack(cols + [om, op])


def window_vector(Z: np.ndarray, t_end: int, W: int, ref: tuple[int, int]) -> np.ndarray:
    lo = max(t_end - W + 1, 0)
    return Z[lo: t_end + 1].mean(axis=0) - Z[ref[0]: ref[1]].mean(axis=0)


def reference_window(onset: int) -> tuple[int, int]:
    """이상이 시작되기 전의 기준 구간(분). 시작이 너무 이르면 맨 앞부터 쓴다."""
    hi = max(onset - 60, 120)
    return max(hi - 540, 0), hi


def _whitener(X: np.ndarray, shrink: float = SHRINK):
    C = np.cov(X.T)
    C = (1 - shrink) * C + shrink * np.diag(np.diag(C))
    vals, vecs = np.linalg.eigh(C)
    return vecs @ np.diag(1.0 / np.sqrt(np.maximum(vals, 1e-12))) @ vecs.T, C


def group_flow(cfg, g: int) -> float:
    return float(sum(cfg.sim["nominal_flow_lpm"][s - 1] for s in cfg.sensor_groups[g - 1]))


def fault_events(cfg, group: int, label: str, size: float, t0: int = DAY):
    segs = cfg.sensor_groups[group - 1]
    kind, _, sign = label.partition("|")
    s = -1.0 if sign == "-" else 1.0
    if kind == "leak":
        return [_leak(segs[0], 5, sign or "in", t0, size * group_flow(cfg, group), 0)]
    return [Event(kind="sensor", start=t0, sensor_group=group - 1, sensor_name=kind, sensor_mode="offset", sensor_value=s * size)]


@dataclass
class PatternResult:
    group: int
    window: int
    onset: int
    t_end: int
    label: str | None                 # 가장 가까운 고장 (None이면 정상 잡음 수준)
    ambiguous: bool
    gap_deg: float                    # 1위와 2위 사이각 차이
    ranking: list[dict] = field(default_factory=list)       # [{cls,label,angle}] 각도 오름차순
    signals: dict[str, float] = field(default_factory=dict)  # 신호별 변화량(정상 흔들림의 몇 배)
    norm2: float = 0.0
    chi_thr: float = 0.0

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


@dataclass
class PatternModel:
    groups: list[int]
    # [g][W] = {"Wm": (9,9), "sd": (9,), "chi": float, "dirs": {cls: (9,)}}
    lib: dict = field(default_factory=dict)

    # ---- 판정 -----------------------------------------------------------
    def classify(self, Z: np.ndarray, g: int, t_end: int, onset: int) -> PatternResult | None:
        avail = t_end - onset
        if avail < WINDOWS[0]:
            return None
        W = max(w for w in WINDOWS if w <= avail)
        L = self.lib[g][W]
        v = window_vector(Z, t_end, W, reference_window(onset))
        xw = L["Wm"] @ v
        norm2 = float(xw @ xw)
        sig = {c: float(x) for c, x in zip(CH9, v / L["sd"])}
        angles = {}
        for cl, d in L["dirs"].items():
            cos = float(d @ xw) / (np.linalg.norm(xw) + 1e-12)
            angles[cl] = float(np.degrees(np.arccos(np.clip(cos, -1, 1))))
        order = sorted(angles, key=angles.get)
        ranking = [{"cls": c, "label": CLASS_LABEL[c], "angle": round(angles[c], 1)} for c in order[:4]]
        gap = angles[order[1]] - angles[order[0]]
        noise = norm2 <= L["chi"]
        # 1위가 누수·계측 이상 어느 쪽이든, 2위가 다른 종류이고 각도 차이가 작으면 구분 불가
        ambiguous = (not noise) and gap < AMBIGUOUS_DEG
        return PatternResult(g, W, onset, t_end, None if noise else order[0], ambiguous, round(gap, 1), ranking, sig, norm2, L["chi"])

    # ---- 저장·불러오기 ----------------------------------------------------
    def to_json(self) -> dict:
        return {str(g): {str(W): {"Wm": L["Wm"].tolist(), "sd": L["sd"].tolist(), "chi": L["chi"],
                                  "dirs": {c: d.tolist() for c, d in L["dirs"].items()}} for W, L in per.items()}
                for g, per in self.lib.items()}

    @staticmethod
    def from_json(groups: list[int], d: dict) -> "PatternModel":
        lib = {int(g): {int(W): {"Wm": np.array(L["Wm"]), "sd": np.array(L["sd"]), "chi": float(L["chi"]),
                                 "dirs": {c: np.array(v) for c, v in L["dirs"].items()}} for W, L in per.items()}
               for g, per in d.items()}
        return PatternModel(groups, lib)


def _key(cfg, bl) -> str:
    h = hashlib.md5()
    h.update(str(cfg.sim["seed"]).encode())
    h.update(json.dumps(cfg.sim, sort_keys=True, default=str).encode())
    for g in sorted(bl.groups):
        for ch in sorted(bl.groups[g].coef):
            h.update(np.round(bl.groups[g].coef[ch], 8).tobytes())
    h.update(f"{LIB_VERSION}-{REPS}-{SIZES}".encode())
    return h.hexdigest()


def build_pattern_model(cfg, bl, groups: list[int], layout: str = "S-A", use_cache: bool = True,
                        reps: int = REPS, n_normal: int = 16, seed0: int = 71000) -> PatternModel:
    cache = DATA_DIR / "pattern_library.json"
    key = _key(cfg, bl)
    if use_cache and cache.exists():
        try:
            d = json.loads(cache.read_text(encoding="utf-8"))
            if d.get("key") == key:
                return PatternModel.from_json(groups, d["lib"])
        except Exception:
            pass

    counter = [seed0]

    def make_df(events_fn, n=3 * DAY):
        counter[0] += 1
        spec = ScenarioSpec(f"pat_{counter[0]}", "패턴 라이브러리", n, counter[0], events_fn)
        truth, _ = simulate_spec(cfg, spec)
        df, _ = sensors_for(cfg, spec, truth, layout)
        return df

    # 정상 구간: 창 평균 벡터의 공분산 → 백색화
    normal = [{g: zmatrix(bl, df, g, groups) for g in groups} for df in (make_df(lambda c: []) for _ in range(n_normal))]
    pre = (700, 1300)
    post0 = DAY + 180
    model = PatternModel(groups, {})
    for g in groups:
        per = {}
        wm_for, chi_for, sd_for = {}, {}, {}
        for W in WINDOWS:
            X0 = np.array([window_vector(Zs[g], t + W - 1, W, pre) for Zs in normal for t in range(1500, 4000 - W, 300)])
            Wm, C = _whitener(X0)
            wm_for[W] = Wm
            sd_for[W] = np.sqrt(np.diag(C))
            chi_for[W] = float(np.percentile(np.sum((X0 @ Wm) ** 2, axis=1), 99))
        acc = {W: {} for W in WINDOWS}
        for lab, sizes in LABELS.items():
            for size in sizes:
                for _ in range(reps):
                    df = make_df(lambda c, lab=lab, size=size: fault_events(c, g, lab, size))
                    Z = zmatrix(bl, df, g, groups)
                    for W in WINDOWS:
                        x = wm_for[W] @ window_vector(Z, post0 + W - 1, W, pre)
                        acc[W].setdefault(merged(lab), []).append(x / (np.linalg.norm(x) + 1e-12))
        for W in WINDOWS:
            dirs = {}
            for cl, vs in acc[W].items():
                v = np.sum(vs, axis=0)
                dirs[cl] = v / (np.linalg.norm(v) + 1e-12)
            per[W] = {"Wm": wm_for[W], "sd": sd_for[W], "chi": chi_for[W], "dirs": dirs}
        model.lib[g] = per
    if use_cache:
        try:
            cache.write_text(json.dumps({"key": key, "lib": model.to_json()}), encoding="utf-8")
        except OSError:
            pass
    return model
