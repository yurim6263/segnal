"""조치 카드 AC-01~06과 사례집 HIST-01을 만든다. 숫자는 위험 모델·합성 데이터와 같은 출처다.

  python -m llm.build_docs         # docs/corp/AC-0x.md, HIST-01.md 생성 (HIST-01은 data/health 이력에서 추출)
HIST-01은 합성 이력에서 뽑으므로 데이터와 문서가 어긋나지 않는다. 담당자 이름·사번·내선은 합성 값이다.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DOCS = Path(__file__).resolve().parents[2] / "docs" / "corp"
DATA = Path(__file__).resolve().parents[2] / "data" / "health"
ALL = "정비담당,정비계획,수처리담당,관리자"
MAINT = "정비담당,정비계획,관리자"

CARDS = {
    "AC-01": dict(cause="WEAR", title="씰 정상 마모", roles=MAINT,
        signal="교체 후 누적 톤수가 늘어 위험률이 커진다(마모형). 다른 신호의 기여는 작다.",
        run="감시. 누수 징후(유량 수지 편차)가 보이면 계획 정지 전이라도 점검 요청.",
        stop="씰·로터리 조인트를 교체하고 교체 후 누적 톤수를 0으로 초기화한다. (SOP-01 3)",
        root="실측 수명으로 교체 주기를 다시 정한다.", parts="씰 키트, O링, 로터리 조인트(필요 시)", time="세그먼트당 약 1시간 [가정]",
        warn="마모 등급(1~3등급)을 반드시 기록한다. 기록이 쌓여야 교체 주기를 정할 수 있다."),
    "AC-02": dict(cause="HAMMER", title="스팀 해머성 씰 파손", roles=ALL,
        signal="묶음 유량이 정상의 90% 미만인 시간이 늘고 공급 압력이 떨어진다.",
        run="유량·공급 압력을 확인하고 해당 묶음 필터 차압·밸브를 점검한다.",
        stop="해당 묶음의 씰을 우선 교체하고 공급 호스·커플링을 육안 점검, 필터를 교체한다. (SOP-01 3, SOP-01 6)",
        root="유량·압력 하한 관리 기준을 정하고 필터 막힘·밸브 원인을 제거한다.", parts="씰 키트, 필터 엘리먼트, 호스·커플링", time="묶음당 약 2시간 [가정]",
        warn="유량 저하가 이어지는 묶음의 다른 세그먼트도 함께 점검한다."),
    "AC-03": dict(cause="BEARING", title="베어링 손상 → 씰 하중", roles=MAINT,
        signal="베어링 온도가 평소보다 올라 이어지고 진동이 늘어난다.",
        run="윤활 상태를 확인하고 온도 추세를 감시한다.",
        stop="베어링·하우징 씰을 교체하고 정렬을 확인한다. (SOP-01 3, SOP-01 4)",
        root="상태 기준으로 베어링을 교체하고 윤활을 관리한다.", parts="베어링, 하우징 씰, 윤활제", time="세그먼트당 약 2시간 [가정]",
        warn="온도 상승이 빠르면(수일 내 3℃ 이상) 계획 정지를 기다리지 말고 담당 관리자에게 보고한다."),
    "AC-04": dict(cause="THERMAL", title="열 사이클 피로", roles=MAINT,
        signal="주조 시작·정지 횟수(열 사이클)가 많은 기간에 위험률이 커진다.",
        run="없음.", stop="씰을 우선 교체한다. (SOP-01 3)",
        root="불필요한 정지·재가동을 줄이도록 조업 계획에 반영한다.", parts="씰 키트", time="세그먼트당 약 1시간 [가정]",
        warn="조업 조건은 정비 담당이 바꿀 수 없다. 조업 부서에 근거를 전달한다."),
    "AC-05": dict(cause="WATER", title="이물질·스케일에 의한 씰 손상", roles=ALL,
        signal="수질(탁도·경도)이 관리 상한을 넘고 필터 차압이 오른다.",
        run="필터를 점검한다.", stop="분해 시 씰 면 긁힘을 확인하고 씰을 교체한다. (SOP-01 6)",
        root="여과·수처리를 강화하고 수질 상한 관리를 강화한다.", parts="필터 엘리먼트, 씰 키트", time="묶음당 약 1.5시간 [가정]",
        warn="수질 조치는 수처리 담당과 협의한다."),
    "AC-06": dict(cause="ASSEMBLY", title="조립 불량(O링·체결)", roles=MAINT,
        signal="장착 직후(초기)에 누수 위험이 높고 압력 시험을 거치지 않았다.",
        run="장착 직후 감시를 강화한다.", stop="미리 교체하지 않는다. 체결 상태를 점검하고 장착 후 압력 시험을 한다. (SOP-01 5)",
        root="조립 절차·토크를 관리하고 모든 장착에 압력 시험을 한다.", parts="O링, 토크 렌치", time="세그먼트당 약 40분 [가정]",
        warn="초기 불량형은 미리 교체하면 오히려 손해다. 교체 대신 점검한다."),
}


def card_md(cid: str, c: dict) -> str:
    return f"""---
doc_id: {cid}
title: 조치 카드 {cid} {c['title']}
cause: {c['cause']}
---
> **가상 문서**: 실제 포스코 문서가 아닙니다. 기준 숫자는 모두 [가정]입니다.

## 1 판단 신호 {{tier=내부 roles={c['roles']} causes={c['cause']}}}
{c['signal']}

## 2 운전 중 조치 {{tier=내부 roles={c['roles']} causes={c['cause']}}}
{c['run']}

## 3 계획 정지 때 조치 {{tier=내부 roles={c['roles']} causes={c['cause']}}}
{c['stop']}

## 4 근본 예방 {{tier=내부 roles={c['roles']} causes={c['cause']}}}
{c['root']}

## 5 필요 부품·공구 {{tier=내부 roles={c['roles']} causes={c['cause']}}}
{c['parts']}

## 6 예상 작업 시간 {{tier=내부 roles={c['roles']} causes={c['cause']}}}
{c['time']}

## 7 주의 사항 {{tier=내부 roles={c['roles']} causes={c['cause']}}}
{c['warn']}
"""


NAMES = ["김정비", "박설비", "이점검", "최수리", "정윤활", "한배관", "오계측", "서조립"]
FOUND = {"flow_balance": "유량 수지 편차", "inspection": "정기 점검", "operator": "운전원 발견", "planned_check": "계획 정지 점검"}


def hist_md(max_cases: int = 14) -> str:
    leaks = pd.read_csv(DATA / "leaks.csv", parse_dates=["ts"]).sort_values("ts")
    rec = leaks.tail(max_cases)
    lab = {"WEAR": "씰 정상 마모", "HAMMER": "스팀 해머성 씰 파손", "BEARING": "베어링 손상", "THERMAL": "열 사이클 피로", "WATER": "수질 손상", "ASSEMBLY": "조립 불량", "RANDOM": "우연형"}
    card = {"WEAR": "AC-01", "HAMMER": "AC-02", "BEARING": "AC-03", "THERMAL": "AC-04", "WATER": "AC-05", "ASSEMBLY": "AC-06", "RANDOM": "조치 카드 없음"}
    out = ["---", "doc_id: HIST-01", "title: 과거 이상 조치·정비 사례집", "---",
           "> **가상 문서**: 합성 데이터(data/health)의 누수 이력에서 자동 추출했습니다. 담당자 이름·사번·내선은 합성 값입니다.", ""]
    for i, r in enumerate(rec.itertuples(), 1):
        name = NAMES[i % len(NAMES)]
        sab = f"P{10300 + i * 7}"
        ext = 4300 + i * 11
        out += [f"## {i} 사례 {r.ts:%Y-%m-%d} {r.segment_serial} {{tier=내부 roles={MAINT} causes={r.cause_code}}}",
                f"일시 {r.ts:%Y-%m-%d %H:%M}, 세그먼트 {r.segment_serial}({r.position}번 자리, 묶음 {r.bundle_id}), 부위 {r.part}. 확인 원인: {lab[r.cause_code]}. 누수량 {r.leak_lpm:.1f} L/min. 발견 경로: {r.found_by}. 적용 카드: {card[r.cause_code]}. 담당: {name}(사번 {sab}, 내선 {ext}).", ""]
    return "\n".join(out)


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for cid, c in CARDS.items():
        (DOCS / f"{cid}.md").write_text(card_md(cid, c), encoding="utf-8")
    (DOCS / "HIST-01.md").write_text(hist_md(), encoding="utf-8")
    print("wrote", sorted(p.name for p in DOCS.glob("*.md")))


if __name__ == "__main__":
    main()
