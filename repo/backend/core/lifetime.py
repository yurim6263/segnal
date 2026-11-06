"""B16. 조인트 수명 모델 (Weibull 생존분석, 검열 반영).

정비 이력에서 완료된 수명(교체 사이 간격)과 검열된 수명(현재까지 살아남은 나이)을 모아
Weibull을 최대우도로 맞추고, 조인트별로 '다음 window일 안에 고장날 조건부 확률'을 사전확률로 쓴다.

모델은 항상 Weibull을 가정한다. 시뮬레이터의 진짜 분포가 lognormal이면 '분포 불일치' 시나리오가 된다.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import optimize, stats


@dataclass
class WeibullFit:
    shape: float
    scale: float
    n_failures: int
    n_censored: int

    def dist(self):
        return stats.weibull_min(c=self.shape, scale=self.scale)

    def hazard(self, age: np.ndarray | float, window: float) -> np.ndarray | float:
        d = self.dist()
        s0 = d.sf(age)
        s1 = d.sf(np.asarray(age) + window)
        return np.where(s0 > 1e-12, 1.0 - s1 / np.maximum(s0, 1e-12), 1.0)


def collect_lives(joints: pd.DataFrame, log: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """(완료 수명 배열, 검열 수명 배열) — 일 단위."""
    events = log[log.action.isin(["replace", "leak_repair"])]
    by_joint = {k: np.sort(v.day.to_numpy()) for k, v in events.groupby("joint_id")}
    done, cens = [], []
    for r in joints.itertuples():
        times = by_joint.get(r.joint_id, np.array([]))
        start = r.install_day
        for t in times:
            done.append(t - start)
            start = t
        cens.append(0.0 - start)          # 현재(0)까지 살아남은 나이
    return np.array(done, dtype=float), np.array(cens, dtype=float)


def fit_weibull(failures: np.ndarray, censored: np.ndarray) -> WeibullFit:
    """검열을 반영한 Weibull 최대우도 적합."""
    f = failures[failures > 0]
    c = censored[censored > 0]

    def nll(params):
        k, lam = np.exp(params)
        ll = np.sum(stats.weibull_min.logpdf(f, c=k, scale=lam)) + np.sum(stats.weibull_min.logsf(c, c=k, scale=lam))
        return -ll

    x0 = np.log([2.0, max(np.mean(np.concatenate([f, c])), 1.0)])
    res = optimize.minimize(nll, x0, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 2000})
    k, lam = np.exp(res.x)
    return WeibullFit(shape=float(k), scale=float(lam), n_failures=len(f), n_censored=len(c))


def prior_from_fit(fit: WeibullFit, joints: pd.DataFrame, window: float) -> np.ndarray:
    """조인트별 사전확률(합이 1)."""
    h = fit.hazard(joints["age_days"].to_numpy(), window)
    return h / h.sum()
