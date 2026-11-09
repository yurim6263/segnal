// 오른쪽 아래 챗봇. 위험 모델 값과 이 역할이 열람할 수 있는 사내문서만 근거로 답한다 (backend/llm/gateway.py).
import { useEffect, useRef, useState } from "react";
import AnswerText from "./AnswerText";
import { ApiError, llm, type AskResult, type Role } from "../llmApi";

const TOOL_KO: Record<string, string> = { get_risk_board: "위험 순위", get_segment_risk: "세그먼트 위험", get_eval_results: "평가 결과" };
const PRESETS = ["가장 위험한 세그먼트와 이유는?", "다음 계획 정지 때 어떤 조치를 해야 해?", "장착 후 압력 시험은 어떻게 해?"];

type Msg = { id: number; asRole: Role; kind: "user" | "bot" | "info"; text: string; out?: AskResult };

export default function AskPanel({ role, user }: { role: Role; user: string }) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [modelOn, setModelOn] = useState<boolean | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const shown = msgs.filter((m) => m.asRole === role);     // 다른 역할의 권한으로 받은 답이 화면에 남지 않게 한다

  useEffect(() => { llm.roles().then((r) => setModelOn(r.llm_available)).catch(() => setModelOn(null)); }, []);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, open]);

  const send = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    const asRole = role;
    setInput("");
    setMsgs((m) => [...m, { id: ++seq.current, asRole, kind: "user", text: question }]);
    setBusy(true);
    try {
      const out = await llm.ask(asRole, user, question);
      setMsgs((m) => [...m, { id: ++seq.current, asRole, kind: "bot", text: out.answer, out }]);
    } catch (e) {
      setMsgs((m) => [...m, { id: ++seq.current, asRole, kind: "info", text: `답변을 가져오지 못했습니다: ${(e as ApiError).message}` }]);
    }
    setBusy(false);
  };

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
              {modelOn != null && <div className="card-sub">{modelOn ? "모델 연결됨 · 조회한 값만으로 답합니다" : "모델 미연결 · 정해진 양식으로 답합니다"}</div>}
            </div>
            <button className="btn" onClick={() => setOpen(false)}>닫기</button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto px-3 py-3">
            {shown.length === 0 && (
              <p className="muted text-[13.5px]">위험 모델 값과 '{role}' 역할이 열람할 수 있는 사내문서만 근거로 답합니다. 근거나 권한이 없으면 답하지 않습니다.</p>
            )}
            {shown.map((m) => m.kind === "user" ? (
              <div key={m.id} className="flex justify-end"><div className="max-w-[85%] rounded-lg px-3 py-2 text-[14px]" style={{ background: "var(--primary)", color: "var(--primary-fg)" }}>{m.text}</div></div>
            ) : m.kind === "info" ? (
              <p key={m.id} className="info-strip text-[13px]">{m.text}</p>
            ) : (
              <div key={m.id}>
                <div className="rounded-lg border px-3 py-2 text-[14px]" style={{ borderColor: "var(--line)", background: "var(--card2)" }}><AnswerText text={m.text} /></div>
                {m.out && (
                  <>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px]">
                      <span className={m.out.mode === "llm" ? "chip chip-blue" : "chip chip-dash"}>{m.out.mode === "llm" ? "모델 답변" : "정해진 양식"}</span>
                      {m.out.mode === "llm" && <span className={m.out.checks.numbers_ok ? "chip chip-ok" : "chip chip-watch"}>{m.out.checks.numbers_ok ? "숫자 일치 검사 통과" : "숫자 검사 실패"}</span>}
                      <span className="muted">조회: {m.out.tools_used.map((t) => TOOL_KO[t] ?? t).join(", ") || "없음"}</span>
                    </div>
                    {m.out.outcome === "answered" && m.out.citations.length > 0 && <p className="muted mt-1 text-[12px]">근거 조항: {m.out.citations.map((c) => c.ref).join(", ")}</p>}
                    <p className="muted mt-1 text-[11.5px]">{m.out.disclaimer}</p>
                  </>
                )}
              </div>
            ))}
            {busy && <p className="muted text-[13px]">값을 조회하는 중…</p>}
            <div ref={bottom} />
          </div>

          <div className="border-t px-3 py-2.5" style={{ borderColor: "var(--line)" }}>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {PRESETS.map((p) => <button key={p} className="chip" style={{ cursor: "pointer" }} disabled={busy} onClick={() => send(p)}>{p}</button>)}
            </div>
            <div className="flex gap-2">
              <input className="min-w-0 flex-1" style={{ background: "var(--card)", color: "var(--text)", border: "1px solid var(--line)", borderRadius: 6, padding: "7px 10px" }}
                value={input} placeholder="질문을 입력하세요" maxLength={300} aria-label="질문" onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.nativeEvent.isComposing) send(input); }} />
              <button className="btn btn-primary" disabled={busy || !input.trim()} onClick={() => send(input)}>보내기</button>
            </div>
          </div>
        </aside>
      )}
    </>
  );
}
