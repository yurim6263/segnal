"""B1. 질량유량 환산·정규화.

부피유량계는 위치(온도)마다 밀도가 달라, 출구가 더 뜨거우면 부피유량을 그대로 비교할 때
약 1~2.5%의 가짜 불균형이 생긴다 (물 밀도 20℃ 998.2 → 40℃ 992.2 kg/m³, 70℃ 977.8).
질량유량으로 환산한 뒤 공급-회수를 비교한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from sim.circuit import water_density


def mass_flow(vol_lpm, t_c):
    """부피유량(L/min) → 질량유량(kg/min)."""
    return np.asarray(vol_lpm) * water_density(t_c) / 1000.0


def groups_in(df: pd.DataFrame) -> list[int]:
    """데이터프레임에 들어 있는 계측 묶음 번호(1부터)."""
    ks = sorted({int(c[1:].split("_")[0]) for c in df.columns if c.startswith("g") and "_flow_in" in c})
    return ks


def group_signals(df: pd.DataFrame, g: int) -> pd.DataFrame:
    """묶음 g의 정규화된 신호.

    imb_vol : (부피유량 입구 − 출구) / 입구      (고정 임계값 방식이 보는 값)
    imb_mass: (질량유량 입구 − 출구) / 입구      (온도 보정 후, 누수만 남음)
    m_in    : 입구 질량유량 (kg/min)
    """
    fi, fo = df[f"g{g}_flow_in"].to_numpy(), df[f"g{g}_flow_out"].to_numpy()
    ti, to = df[f"g{g}_t_in"].to_numpy(), df[f"g{g}_t_out"].to_numpy()
    m_in, m_out = mass_flow(fi, ti), mass_flow(fo, to)
    out = pd.DataFrame({
        "imb_vol": (fi - fo) / fi,
        "imb_mass": (m_in - m_out) / m_in,
        "m_in": m_in,
        "m_out": m_out,
        "p_in": df[f"g{g}_p_in"].to_numpy(),
        "p_out": df[f"g{g}_p_out"].to_numpy(),
        "t_in": ti,
        "t_out": to,
        "dt": to - ti,
    }, index=df.index)
    return out
