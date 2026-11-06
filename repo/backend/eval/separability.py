"""12단계 분리도 검증 게이트: 서명이 후보를 실제로 구분하는가?  실행: python -m eval.separability

판정 기준(제안): 다른 세그먼트 후보 쌍 중 코사인 유사도 > 0.98(구분 불가)인 비율, 그리고
'다른 세그먼트 중 가장 비슷한 후보'와도 구분되는 후보의 비율.
"""
from __future__ import annotations

import json

from core.signature import build_signatures, separability_report
from eval.common import fit_baseline
from sim.config import load_config
from sim.scenarios import DATA_DIR


def main() -> None:
    cfg = load_config()
    out = {}
    for layout in ("S-A", "S-B"):
        bl, _ = fit_baseline(layout)
        sigs = build_signatures(cfg, bl, layout)
        rep = separability_report(sigs)
        out[layout] = rep
        print(f"\n[{layout}] 후보 {rep['n_candidates']}개")
        print(f"  같은 세그먼트 안(롤·입구/출구) 구분 불가 쌍 비율: {rep['frac_same_segment_pairs_indistinguishable']*100:.1f}%")
        print(f"  다른 세그먼트 쌍 중 구분 불가 비율        : {rep['frac_diff_segment_pairs_indistinguishable']*100:.1f}%")
        print(f"  세그먼트 단위로 구분 가능한 후보 비율     : {rep['frac_candidates_segment_distinguishable']*100:.1f}%")
        print(f"  가장 비슷한 다른 세그먼트와의 평균 유사도 : {rep['mean_nearest_other_segment_cos']:.3f}")
    (DATA_DIR / "separability.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
