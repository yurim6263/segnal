"""발표 전에 사전 질문 3개의 답을 미리 저장해 둔다(모델을 한 번 부르고 이후엔 즉시 응답).
시연 흐름(leak_ramp_s5, 2400분)의 세 단계 상태에서 각각 묻는다: 점검 전 → 세그먼트 4 이상 없음 → 세그먼트 5 누수 확인.
키가 없으면 아무것도 저장하지 않는다. 실행: python -m agent.warm   (점검 기록은 끝나면 지운다)
"""
from __future__ import annotations

import service
from agent import qa
from agent.envfile import llm_available, load_env

SID, TS = "leak_ramp_s5", 2400


def main() -> None:
    load_env()
    if not llm_available():
        print("ANTHROPIC_API_KEY가 없어 건너뜁니다 (backend/.env 에 키를 넣으세요).")
        return
    service.reset_inspections(SID)
    steps = [("점검 전", None), ("세그먼트 4 이상 없음", ("S4", "no_issue")), ("세그먼트 5 누수 확인", ("S5", "leak_confirmed"))]
    try:
        for label, rec in steps:
            if rec:
                service.add_inspection(SID, rec[0], rec[1], TS)
            for q in qa.PRESETS:
                r = qa.ask(SID, TS, q)
                print(f"[{label}] {q} -> {r['mode']} 검증={r['numbers_verified']} {('· ' + r['note']) if r['note'] else ''}")
    finally:
        service.reset_inspections(SID)


if __name__ == "__main__":
    main()
