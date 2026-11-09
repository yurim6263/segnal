"""작업지시서 자동 검증 통과율 측정 (기획서 5-3 '작업지시서 숫자 일치율').

  python -m eval.workorder_eval [N]     # 위험 순위 상위 N개 세그먼트(기본 7)마다 작업지시서를 만들어 검사 결과를 집계
Claude가 쓴 초안이 검사를 통과한 비율, 재생성 횟수, 양식 모드로 떨어진 건수를 센다. 키가 없으면 전부 양식 모드다.
저장: data/health/workorder_eval.json. 임시 DB를 써서 실제 작업지시서 목록을 어지럽히지 않는다.
"""
from __future__ import annotations

import json
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llm import policy, workorder
from llm.gateway import Gateway

OUT = Path(__file__).resolve().parents[2] / "data" / "health" / "workorder_eval.json"


def run(n: int = 7) -> dict:
    tmp = Path(tempfile.mkdtemp())
    gw = Gateway(audit_path=tmp / "a.db")
    segs = [s["segment"] for s in gw.board()["segments"][:n]]
    subj = policy.Subject("정비계획", "eval")

    def one(serial: str) -> dict:
        r = workorder.generate(gw, subj, serial, tmp / f"{serial}.db")
        c = r["checks"]
        return {"segment": serial, "mode": r["mode"], "retries": r.get("retries", 0), "numbers_ok": bool(c.get("numbers_ok")), "required_ok": bool(c.get("required_ok")),
                "citations_ok": bool(c.get("citations_ok")), "actions_cited_ok": bool(c.get("actions_cited_ok")), "off_card": c.get("off_card", 0),
                "numbers_in_doc": c.get("numbers_total"), "llm_error": c.get("llm_error"), "chars": len(r["draft_md"])}

    with ThreadPoolExecutor(3) as ex:
        rows = list(ex.map(one, segs))
    llm = [r for r in rows if r["mode"] == "llm"]
    res = {"n": len(rows), "llm_generated": len(llm), "fell_back_to_template": len(rows) - len(llm),
           "llm_first_try_pass": sum(1 for r in llm if r["retries"] == 0), "llm_regenerated_pass": sum(1 for r in llm if r["retries"] > 0),
           "llm_pass_rate": round(len(llm) / len(rows), 3), "numbers_ok_all": all(r["numbers_ok"] for r in rows),
           "total_retries": sum(r["retries"] for r in rows), "off_card_total": sum(r["off_card"] for r in rows), "rows": rows,
           "note": "통과 = 숫자 일치·필수 항목·작업 줄마다 조항 인용·허용 조항만 인용·개인정보 없음. 실패하면 한 번 다시 쓰게 하고, 그래도 실패하면 양식 모드. 같은 합성 데이터의 상위 세그먼트라 서로 비슷한 문서가 나온다."}
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


if __name__ == "__main__":
    r = run(int(sys.argv[1]) if len(sys.argv) > 1 else 7)
    print({k: v for k, v in r.items() if k not in ("rows", "note")})
    for x in r["rows"]:
        print(x)
