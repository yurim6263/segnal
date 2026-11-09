import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AgentStatus, AskOut, ProposedAction } from "../types";
import { josa } from "./ui";
import AnswerText from "./AnswerText";

const TOOL_KO: Record<string, string> = {
  get_status: "현재 상태", get_cause_table: "원인 분류표", get_diagnosis_detail: "원인 구분 근거", get_replacement_advice: "교체 시점 권고", get_location_candidates: "위치 후보", get_signal: "신호 값",
  get_inspections: "점검 기록", get_eval_results: "평가 결과", propose_inspection_record: "점검 기록 제안", "(정해진 양식)": "정해진 양식",
};
const FALLBACK_PRESETS = ["왜 주의(경보)가 떴어?", "누수 후보 순위와 근거를 알려줘", "지금 무엇을 하면 돼?", "언제까지 교체해야 해?"];

type Msg = { id: number; role: "user" | "bot" | "info"; text: string; out?: AskOut; action?: ProposedAction | null; actionState?: "wait" | "done" | "cancel" };

export default function AskPanel({ scenarioId, ts, onRecord }: {
  scenarioId: string; ts: number;
  onRecord: (segment: number, result: "leak_confirmed" | "no_issue") => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<AgentStatus | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const seq = useRef(0);

  useEffect(() => { api.agentStatus().then(setStatus); }, []);
  useEffect(() => { setMsgs([]); }, [scenarioId]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, open]);

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    setInput("");
    setMsgs((m) => [...m, { id: ++seq.current, role: "user", text: question }]);
    setBusy(true);
    const out = await api.ask(scenarioId, question, ts);
    setBusy(false);
    setMsgs((m) => [...m, { id: ++seq.current, role: "bot", text: out.answer, out, action: out.proposed_action, actionState: out.proposed_action ? "wait" : undefined }]);
  };
  const decide = async (id: number, a: ProposedAction, ok: boolean) => {
    if (ok) await onRecord(a.segment, a.result);
    setMsgs((m) => m.map((x): Msg => (x.id === id ? { ...x, actionState: ok ? "done" : "cancel" } : x))
      .concat(ok ? [{ id: ++seq.current, role: "info" as const, text: `세그먼트 ${a.segment}${josa(a.segment, "을", "를")} ${a.result === "leak_confirmed" ? "누수 확인" : "이상 없음"}으로 기록했습니다. 점검 화면에서 고칠 수 있습니다.` }] : []));
  };

  const presets = status?.presets?.length ? status.presets : FALLBACK_PRESETS;
  const modeChip = (o: AskOut) =>
    o.mode === "cache" ? <span className="chip">저장된 답변</span> : o.mode === "llm" ? <span className="chip chip-blue">모델 답변</span> : <span className="chip chip-dash">정해진 양식</span>;

  return (
    <>
      {!open && (
        <button className="btn btn-primary" style={{ position: "fixed", right: 18, bottom: 18, zIndex: 40, boxShadow: "0 2px 10px rgba(0,0,0,.25)", borderRadius: 999, padding: "10px 20px" }}
          onClick={() => setOpen(true)} aria-label="질문창 열기">물어보기</button>
      )}
      {open && (
        <aside role="dialog" aria-label="질문창" className="card flex flex-col"
          style={{ position: "fixed", right: 14, bottom: 14, top: 64, width: 400, maxWidth: "calc(100vw - 28px)", zIndex: 50, padding: 0, boxShadow: "0 4px 24px rgba(0,0,0,.3)" }}>
          <div className="flex items-center justify-between gap-2 border-b px-3 py-2.5" style={{ borderColor: "var(--line)" }}>
            <div>
              <b>물어보기</b>
              <div className="card-sub">{status?.llm_available ? "모델 연결됨 · 조회한 값만으로 답합니다" : "모델 미연결 · 정해진 양식으로 답합니다"}</div>
            </div>
            <button className="btn btn-sm" onClick={() => setOpen(false)}>닫기</button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
            {msgs.length === 0 && (
              <p className="muted text-[13.5px]">현재 화면 기준으로 물어보세요. 값은 시스템이 계산한 것만 사용합니다. 점검 결과를 말하면 기록 제안이 만들어지고, 사람이 확인해야 반영됩니다.</p>
            )}
            {msgs.map((m) => m.role === "user" ? (
              <div key={m.id} className="flex justify-end"><div className="max-w-[85%] rounded-lg px-3 py-2 text-[14px]" style={{ background: "var(--primary)", color: "var(--primary-fg)" }}>{m.text}</div></div>
            ) : m.role === "info" ? (
              <p key={m.id} className="info-strip text-[13px]">{m.text}</p>
            ) : (
              <div key={m.id}>
                <div className="rounded-lg border px-3 py-2 text-[14px]" style={{ borderColor: "var(--line)", background: "var(--card2)" }}><AnswerText text={m.text} /></div>
                {m.out && (
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px]">
                    {modeChip(m.out)}
                    {m.out.mode !== "template" && <span className={m.out.numbers_verified ? "chip chip-ok" : "chip chip-watch"}>{m.out.numbers_verified ? "숫자 일치 검사 통과" : "숫자 검사 실패"}</span>}
                    <span className="muted">조회: {m.out.tools_used.map((t) => TOOL_KO[t] ?? t).join(", ") || "없음"}</span>
                  </div>
                )}
                {m.out?.note && <p className="muted mt-1 text-[12px]">{m.out.note}</p>}
                {m.action && (
                  <div className="info-strip mt-2 text-[13.5px]">
                    <b>세그먼트 {m.action.segment}{josa(m.action.segment, "을", "를")} {m.action.result === "leak_confirmed" ? "누수 확인" : "이상 없음"}으로 기록할까요?</b>
                    {m.actionState === "wait" ? (
                      <div className="mt-2 flex gap-2">
                        <button className="btn btn-primary btn-sm" onClick={() => decide(m.id, m.action!, true)}>확인, 기록하기</button>
                        <button className="btn btn-sm" onClick={() => decide(m.id, m.action!, false)}>취소</button>
                      </div>
                    ) : <div className="muted mt-1 text-[12.5px]">{m.actionState === "done" ? "기록했습니다." : "취소했습니다."}</div>}
                  </div>
                )}
                {m.out && <p className="muted mt-1 text-[11.5px]">{m.out.disclaimer}</p>}
              </div>
            ))}
            {busy && <p className="muted text-[13px]">값을 조회하는 중…</p>}
            <div ref={bottom} />
          </div>

          <div className="border-t px-3 py-2.5" style={{ borderColor: "var(--line)" }}>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {presets.map((p) => <button key={p} className="chip" style={{ cursor: "pointer" }} disabled={busy} onClick={() => send(p)}>{p}</button>)}
            </div>
            <div className="flex gap-2">
              <input className="min-w-0 flex-1" style={{ background: "var(--card)", color: "var(--text)", border: "1px solid var(--line)", borderRadius: 6, padding: "7px 10px" }}
                value={input} placeholder="질문을 입력하세요" maxLength={300} onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) send(input); }} />
              <button className="btn btn-primary" disabled={busy || !input.trim()} onClick={() => send(input)}>보내기</button>
            </div>
          </div>
        </aside>
      )}
    </>
  );
}
