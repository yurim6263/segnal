"""B6·B10. 위치 후보 순위 (서명 매칭 + 사전확률) 와 점검 결과 피드백(베이지안 갱신).

관측: 이상이 잡힌 시점 직전 W분의 잔차 z 평균 벡터 r (묶음 × 채널).
후보 c의 서명 s_c(기준 누수량일 때의 z 변화)에 대해, 누수량(진폭) a_c ≥ 0을 최소제곱으로 맞추고
오차 e_c = ‖r − a_c·s_c‖² 로 가능도 ∝ exp(−W_eff·e_c/2) 를 계산한다 (W_eff = W / temper).
사후확률 ∝ 사전확률 × 가능도. 단일 누수를 가정한다.

피드백(B10): 후보 k를 점검해 '이상 없음'이면 그 후보의 확률을 (1−정확도)배로 줄이고 정규화,
'누수 확인'이면 점검 정확도만큼 확률을 몰아준다. 점검 오입력 가능성은 정확도 파라미터(기본 90%)로 반영한다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .baseline import Baseline
from .classify import CHANNELS
from .detect import recenter
from .signature import REF_LPM, SignatureSet

WINDOW = 60
TEMPER = 2.0            # 잔차의 자기상관·모델 오차를 감안해 유효 표본 수를 W/2로 줄임
MAX_LEAK_LPM = 60.0


def observed_vector(df: pd.DataFrame, bl: Baseline, groups: list[int], t: int, window: int = WINDOW) -> np.ndarray:
    """t 직전 window분의 재중심화 잔차 z 평균 (묶음 × 채널 순서는 서명과 같다)."""
    parts = []
    lo = max(t - window, 0)
    for g in groups:
        r = bl.residuals(df, g)
        for ch in CHANNELS:
            z = recenter(r[f"z_{ch}"].to_numpy())
            parts.append(z[lo:t].mean())
    return np.array(parts)


@dataclass
class Posterior:
    joint_ids: list[str]
    segments: np.ndarray
    rolls: np.ndarray
    sides: list[str]
    prob: np.ndarray               # 사후확률
    prior: np.ndarray
    amplitude_lpm: np.ndarray      # 후보별 추정 누수량
    loglik: np.ndarray

    def order(self) -> np.ndarray:
        return np.argsort(-self.prob)

    def top(self, k: int) -> list[int]:
        return list(self.order()[:k])

    def segment_prob(self) -> dict[int, float]:
        out: dict[int, float] = {}
        for s, p in zip(self.segments, self.prob):
            out[int(s)] = out.get(int(s), 0.0) + float(p)
        return out


def rank_candidates(sigs: SignatureSet, r: np.ndarray, prior: np.ndarray | None = None,
                    window: int = WINDOW, temper: float = TEMPER) -> Posterior:
    S = sigs.matrix                                   # (C, D)
    ss = (S * S).sum(axis=1) + 1e-12
    a = np.clip((S @ r) / ss, 0.0, MAX_LEAK_LPM / REF_LPM)       # 기준 누수량 대비 배수
    resid = r[None, :] - a[:, None] * S
    err = (resid * resid).sum(axis=1)
    loglik = -(window / temper) * err / 2.0
    n = len(S)
    pr = np.full(n, 1.0 / n) if prior is None else np.asarray(prior, dtype=float) / np.sum(prior)
    logp = np.log(pr + 1e-300) + loglik
    logp -= logp.max()
    p = np.exp(logp)
    p /= p.sum()
    return Posterior(sigs.joint_ids, sigs.segments, sigs.rolls, sigs.sides, p, pr, a * REF_LPM, loglik)


def apply_inspection(prob: np.ndarray, idx: int, result: str, accuracy: float = 0.9) -> np.ndarray:
    """점검 결과 반영 (베이지안). idx = 점검한 후보의 위치."""
    p = prob.copy()
    if result == "no_issue":
        # P(점검 '이상 없음' | 실제 그 후보가 누수) = 1−accuracy, 아니면 = accuracy
        like = np.full_like(p, accuracy)
        like[idx] = 1.0 - accuracy
    elif result == "leak_confirmed":
        like = np.full_like(p, 1.0 - accuracy)
        like[idx] = accuracy
    else:
        raise ValueError(result)
    p = p * like
    return p / p.sum()


def priority_order(prob: np.ndarray, inspect_minutes: np.ndarray, access_risk: np.ndarray, lam: float = 20.0) -> tuple[np.ndarray, np.ndarray]:
    """O1: score = p / (점검 시간 + λ·접근 위험). 큰 순서가 점검 순서. (score, 점검 순서 인덱스) 반환."""
    score = prob / (inspect_minutes + lam * access_risk)
    return score, np.argsort(-score)


def apply_segment_inspection(prob: np.ndarray, segments: np.ndarray, segment: int, result: str, accuracy: float = 0.9) -> np.ndarray:
    """세그먼트 단위 점검 결과 반영. 그 세그먼트에 속한 모든 후보(롤·조인트)에 같은 가능도를 곱한다."""
    in_seg = np.asarray(segments) == segment
    if result == "no_issue":
        like = np.where(in_seg, 1.0 - accuracy, accuracy)
    elif result == "leak_confirmed":
        like = np.where(in_seg, accuracy, 1.0 - accuracy)
    else:
        raise ValueError(result)
    p = prob * like
    return p / p.sum()
