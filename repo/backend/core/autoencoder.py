"""B17 비교용 딥러닝 검출기: 작은 오토인코더 (PyTorch, CPU).

두 가지를 비교한다.
- with_conditions=True : 센서값 + 운전 조건(주조 속도, 강종)을 입력에 넣어 운전점 영향을 모델이 배우게 함
- with_conditions=False: 원시 센서값만 — 운전점이 바뀌면 정상값도 바뀌어 오경보가 생길 수 있음

GPU 없는 노트북에서 돌도록 입력 6~8차원, 은닉 16, 잠재 3의 작은 모델만 쓴다. 학습은 사전에 한다.
점수 = 재구성 오차(MSE)의 15분 이동평균.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .normalize import group_signals


def _features(df: pd.DataFrame, g: int, with_conditions: bool) -> np.ndarray:
    sig = group_signals(df, g)
    cols = [sig["imb_vol"], sig["m_in"], sig["p_in"], sig["p_out"], sig["dt"], sig["t_in"]]
    if with_conditions:
        cols += [df["cast_speed"], (df["steel_grade"] == "B").astype(float)]
    return np.column_stack([np.asarray(c, dtype=float) for c in cols])


class AEDetector:
    def __init__(self, with_conditions: bool, hidden: int = 16, latent: int = 3, epochs: int = 30,
                 smooth: int = 15, seed: int = 0) -> None:
        self.with_conditions = with_conditions
        self.hidden, self.latent, self.epochs = hidden, latent, epochs
        self.smooth, self.seed = smooth, seed
        self.models: dict[int, object] = {}
        self.norm: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def fit(self, df_train: pd.DataFrame, groups: list[int]) -> "AEDetector":
        import torch
        from torch import nn

        torch.manual_seed(self.seed)
        torch.set_num_threads(2)
        for g in groups:
            X = _features(df_train, g, self.with_conditions)
            mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-9
            Xn = torch.tensor((X - mu) / sd, dtype=torch.float32)
            d = Xn.shape[1]
            model = nn.Sequential(
                nn.Linear(d, self.hidden), nn.Tanh(),
                nn.Linear(self.hidden, self.latent), nn.Tanh(),
                nn.Linear(self.latent, self.hidden), nn.Tanh(),
                nn.Linear(self.hidden, d),
            )
            opt = torch.optim.Adam(model.parameters(), lr=3e-3)
            n = len(Xn)
            for _ in range(self.epochs):
                perm = torch.randperm(n)
                for i in range(0, n, 512):
                    b = Xn[perm[i:i + 512]]
                    loss = ((model(b) - b) ** 2).mean()
                    opt.zero_grad()
                    loss.backward()
                    opt.step()
            self.models[g] = model.eval()
            self.norm[g] = (mu, sd)
        return self

    def score(self, df: pd.DataFrame, g: int) -> np.ndarray:
        import torch

        mu, sd = self.norm[g]
        X = torch.tensor((_features(df, g, self.with_conditions) - mu) / sd, dtype=torch.float32)
        with torch.no_grad():
            err = ((self.models[g](X) - X) ** 2).mean(dim=1).numpy()
        k = self.smooth
        return np.convolve(np.concatenate([np.full(k - 1, err[0]), err]), np.ones(k) / k, mode="valid")
