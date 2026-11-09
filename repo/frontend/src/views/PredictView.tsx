import { useEffect, useRef, useState } from "react";
import AnswerText from "../components/AnswerText";
import CasterArc from "../components/CasterArc";
import SegmentHistory, { HeroTrend } from "../components/SegmentHistory";
import { Bar, Card } from "../components/ui";
import { ApiError, llm, type Checks, type Role, type RiskBoard, type RiskSegment, type SegmentHistoryData, type WoRow, type WorkOrder } from "../llmApi";

const causeColor = (cause: string) => `var(--cause-${cause})`;
const CAUSE_NAME: Record<string, string> = { WEAR: "씰 정상 마모", HAMMER: "스팀 해머성 씰 파손", BEARING: "베어링 손상", THERMAL: "열 사이클 피로", WATER: "수질 손상", ASSEMBLY: "조립 불량", RANDOM: "우연형" };
const pct = (x: number, d = 1) => `${(x * 100).toFixed(d)}%`;

function Ok({ ok, label }: { ok: boolean | undefined; label: string }) {
  return <span className={`chip ${ok ? "chip-ok" : "chip-alarm"}`}>{ok ? "✓" : "✕"} {label}</span>;
}

function CheckRow({ c }: { c: Checks }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      <Ok ok={c.numbers_ok} label="숫자가 모델 값과 일치" />
      <Ok ok={c.required_ok} label="필수 항목 있음" />
      <Ok ok={c.actions_cited_ok} label="작업마다 조항 인용" />
      <Ok ok={c.citations_ok} label="인용 조항이 건네준 조항" />
      <Ok ok={c.pii_ok && c.no_forbidden_leak} label="개인정보·권한 밖 문구 없음" />
      <span className={`chip ${c.off_card ? "chip-watch" : ""}`}>카드 밖 제안 {c.off_card ?? 0}건</span>
    </div>
  );
}

export default function PredictView({ role, user, onPlan }: { role: Role; user: string; onPlan: () => void }) {
  const [board, setBoard] = useState<RiskBoard | null>(null);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [wo, setWo] = useState<WorkOrder | null>(null);
  const [orders, setOrders] = useState<WoRow[]>([]);
  const [edit, setEdit] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [hist, setHist] = useState<SegmentHistoryData | null>(null);
  const woRef = useRef<HTMLDivElement>(null);
  const [rGrade, setRGrade] = useState("2");
  const [rCause, setRCause] = useState("");
  const [rNote, setRNote] = useState("");
  const [rDone, setRDone] = useState<{ match: boolean; cause: string } | null>(null);

  const reload = () => llm.listWo().then(setOrders).catch(() => setOrders([]));
  useEffect(() => { llm.board().then((b) => { setBoard(b); setSel(b.segments[0]?.segment ?? ""); }).catch((e) => setErr(e.message)); reload(); }, []);
  useEffect(() => { if (sel) llm.history(sel).then(setHist).catch(() => setHist(null)); }, [sel]);
  useEffect(() => { if (wo) woRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [wo?.wo_id]);

  if (err) return <Card title="위험 예측"><p className="muted">{err}</p></Card>;
  if (!board) return <Card title="위험 예측"><p className="muted">모델을 맞추는 중…(처음 한 번 몇 초)</p></Card>;
  const seg: RiskSegment | undefined = board.segments.find((s) => s.segment === sel);
  const max = Math.max(...board.segments.map((s) => s.prob_next_stop));
  const pick = (segment: string) => { setSel(segment); setWo(null); setMsg(""); };
  const byTons = [...board.segments].sort((a, b) => b.joint_age_t - a.joint_age_t);
  const topCause = seg?.causes.find((c) => c.cause === seg.top_cause);

  const make = async () => {
    if (!seg) return;
    setBusy(true); setMsg(""); setWo(null); setEdit(null);
    try {
      const r = await llm.createWo(role, user, seg.segment);
      if (r.ok === false) setMsg(r.message ?? "생성할 수 없습니다.");
      else { setWo(r); reload(); }
    } catch (e) { setMsg((e as ApiError).message); }
    setBusy(false);
  };
  const approve = async () => {
    if (!wo) return;
    try { await llm.approveWo(wo.wo_id, role, user); setWo({ ...wo, status: "approved" }); setMsg(`${wo.wo_id} 승인됨 (승인자: ${user}, 역할: ${role})`); reload(); }
    catch (e) { setMsg(`승인 거부: ${(e as ApiError).message}`); }
  };
  const saveResult = async () => {
    if (!wo || !rCause) return;
    try {
      const r = await llm.recordResult(wo.wo_id, role, user, rGrade, rCause, rNote);
      setWo({ ...wo, status: "done" }); setRDone({ match: r.prediction_match, cause: rCause }); setMsg(`${wo.wo_id} 점검 결과를 기록했습니다.`); reload();
    } catch (e) { setMsg(`기록 거부: ${(e as ApiError).message}`); }
  };
  const saveEdit = async () => {
    if (!wo || edit === null) return;
    try { await llm.editWo(wo.wo_id, role, user, edit); setWo({ ...wo, draft_md: edit, checks: { ...wo.checks, numbers_ok: false } }); setEdit(null); setMsg("수정했습니다. 수정한 문서는 자동 숫자 검증을 다시 통과한 것이 아니므로 검증 표시를 껐습니다."); }
    catch (e) { setMsg((e as ApiError).message); }
  };

  return (
    <div>
      {seg && (
        <>
          <CasterArc cells={board.segments.map((s) => ({ position: s.position, bundle: s.bundle, serial: s.segment, prob: s.prob_next_stop, tone: s.rank === 1 ? "hot" : s.rank <= 3 ? "warm" : "plain" }))}
            focus={seg.position} focusLabel={`위험 ${seg.rank}위 · 묶음 ${seg.bundle}`} onSelect={(p) => pick(board.segments.find((s) => s.position === p)!.segment)}
            ariaLabel={`연주기 단면. 세그먼트 ${board.segments.length}개의 다음 정지 전 누수 확률. 선택: ${seg.segment} ${pct(seg.prob_next_stop)}`}>
            <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
              <div className="min-w-0 flex-[1_1_420px]">
                <div className="flex items-center gap-2 text-[14.5px] font-bold" style={{ color: "var(--watch-fg)" }}>
                  <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 15 14.5H1Z" style={{ fill: "var(--watch)" }} /></svg>
                  다음 계획 정지 {board.next_planned_stop} · 위험 {seg.rank}위 / {board.segments.length}개
                </div>
                <h1 className="mt-1 text-[28px] font-extrabold leading-tight">{seg.segment} 정지 전 누수 확률 <span className="mono">{pct(seg.prob_next_stop)}</span></h1>
                <p className="muted text-[14.5px]">유력 원인 {seg.top_cause_label}{topCause?.card ? ` (${topCause.card})` : ""} · {seg.position}번 자리, 묶음 {seg.bundle}</p>
              </div>
              <div className="flex gap-2">
                <button className="btn" onClick={onPlan}>휴지 교체 계획</button>
                <button className="btn btn-primary" disabled={busy} onClick={make}>{busy ? "작성 중…" : "작업지시서 만들기"}</button>
              </div>
            </div>
            {hist?.segment === seg.segment && <HeroTrend h={hist} cause={seg.top_cause} />}
          </CasterArc>

          <div className="mt-3 grid gap-px md:grid-cols-3" style={{ background: "var(--line)", border: "1px solid var(--line)" }}>
            <section className="px-[18px] py-3" style={{ background: "var(--card)" }}>
              <h2 className="muted text-[13.5px] font-medium">기존 톤수 순으로 고른다면</h2>
              <p className="mt-0.5 text-[15px]"><strong className="mono text-[22px]">{byTons[0].segment}</strong> 1순위 · 이 세그먼트는 {byTons.indexOf(seg) + 1}위</p>
            </section>
            <section className="px-[18px] py-3" style={{ background: "var(--card)" }}>
              <h2 className="muted text-[13.5px] font-medium">유력 원인 · 모델 추정</h2>
              <p className="mt-0.5 text-[15px]"><strong className="text-[18px]" style={{ color: "var(--watch-fg)" }}>{seg.top_cause_label}</strong> 기여도 {Math.round((topCause?.share ?? 0) * 100)}%</p>
            </section>
            <section className="px-[18px] py-3" style={{ background: "var(--card)" }}>
              <h2 className="muted text-[13.5px] font-medium">사용 이력</h2>
              <p className="mono mt-0.5 text-[17px]">{seg.joint_age_t.toLocaleString()} t · 장착 후 {seg.days_since_install}일</p>
            </section>
          </div>
          <p className="muted mt-2 text-[12.5px]">기준일 {board.as_of}. 원인별 위험률을 더한 생존 분석 모델의 합성 데이터 예측값입니다. {board.note} 표시 상한은 99%입니다.</p>
        </>
      )}

      <div className="mt-3 grid gap-3 lg:grid-cols-[1.25fr_1fr]">
        <Card title="위험도 순위판" sub="행을 누르면 상세가 바뀝니다">
          <table className="tbl">
            <thead><tr><th>순위</th><th>세그먼트</th><th>자리·묶음</th><th style={{ width: "34%" }}>정지 전 누수 확률</th><th>유력 원인</th></tr></thead>
            <tbody>
              {board.segments.map((s) => (
                <tr key={s.segment} onClick={() => pick(s.segment)} style={{ cursor: "pointer", background: s.segment === sel ? "var(--primary-soft)" : undefined }}>
                  <td className="font-bold">{s.rank}</td>
                  <td>{s.segment}</td>
                  <td className="muted">{s.position}번 · {s.bundle}</td>
                  <td><div className="flex items-center gap-2"><div className="flex-1"><Bar value={s.prob_next_stop / Math.max(max, 0.05)} /></div><b className="w-14 text-right">{pct(s.prob_next_stop)}</b></div></td>
                  <td className="text-[13px]">{s.top_cause_label}{s.top_cause === "ASSEMBLY" && <span className="chip chip-watch ml-1">미리 교체 금지</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        {seg && (
          <Card title={`${seg.segment} 상세`} sub={`${seg.position}번 자리 · 묶음 ${seg.bundle} · 위험 ${seg.rank}위`}>
            <div className="kpi mb-3"><span className="kpi-num">{pct(seg.prob_next_stop)}</span><span className="muted ml-2 text-[13px]">정지 전({seg.horizon_days}일) · 14일 {pct(seg.prob_14d, 0)}</span></div>
            <div className="mb-1 text-[13px] font-semibold">요인 기여도</div>
            <div className="flex h-4 overflow-hidden rounded" style={{ background: "var(--chart-grid)" }}>
              {seg.causes.map((c) => <div key={c.cause} title={`${c.label} ${Math.round(c.share * 100)}%`} style={{ width: `${c.share * 100}%`, background: causeColor(c.cause) }} />)}
            </div>
            <ul className="mt-1.5 space-y-0.5 text-[13.5px]">
              {seg.causes.map((c) => (
                <li key={c.cause} className="flex items-center gap-2"><span style={{ width: 10, height: 10, background: causeColor(c.cause), display: "inline-block" }} />{c.label}<b>{Math.round(c.share * 100)}%</b>{c.card && <span className="chip chip-blue">{c.card}</span>}</li>
              ))}
            </ul>
            <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[13.5px]">
              {"low_flow_index" in seg.signals && <><span className="muted">유량 저하 지수</span><b>{seg.signals.low_flow_index}</b></>}
              {"bearing_rise_c" in seg.signals && <><span className="muted">베어링 온도 상승</span><b>{seg.signals.bearing_rise_c}℃</b></>}
              {"vib_increase" in seg.signals && <><span className="muted">진동 증가율</span><b>{seg.signals.vib_increase}</b></>}
              <span className="muted">교체 후 누적</span><b>{seg.joint_age_t.toLocaleString()} t</b>
              <span className="muted">장착 후</span><b>{seg.days_since_install}일</b>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button className="btn btn-primary" disabled={busy} onClick={make}>{busy ? "작성 중… (최대 40초)" : "작업지시서 만들기"}</button>
              <span className="muted text-[12.5px]">역할: {role} · 권한 안의 조항만 AI에 전달</span>
            </div>
          </Card>
        )}
      </div>

      {seg && hist?.segment === seg.segment && <SegmentHistory h={hist} causeLabel={Object.fromEntries(seg.causes.map((c) => [c.cause, c.label]))} />}

      {msg && <p className="info-strip mt-3">{msg}</p>}

      <div ref={woRef} />
      {wo && (
        <Card className="mt-3" title={`작업지시서 ${wo.wo_id}`} sub={wo.status === "approved" ? "승인됨" : "초안 — 담당자 승인 전"}
          right={`${wo.mode === "llm" ? `Claude(${wo.model})가 작성` : "양식 모드(규칙 기반)"}${wo.retries ? ` · 검증 실패 후 재생성 ${wo.retries}회` : ""}`}>
          <div className="mb-3"><CheckRow c={wo.checks} /></div>
          {wo.checks.llm_error && <p className="muted mb-2 text-[12.5px]">모델 호출이 실패해 양식 모드로 대체됨: {wo.checks.llm_error}</p>}
          {edit === null ? <AnswerText text={wo.draft_md} /> : <textarea className="w-full text-[14px]" rows={16} value={edit} onChange={(e) => setEdit(e.target.value)} />}
          <p className="muted mt-2 text-[12.5px]">인용 조항: {wo.cited.join(", ")} · 개인정보 마스킹 {wo.masked_count}건</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {edit === null ? <button className="btn" disabled={wo.status !== "draft"} onClick={() => setEdit(wo.draft_md)}>수정</button> : <button className="btn" onClick={saveEdit}>수정 저장</button>}
            <button className="btn btn-primary" disabled={wo.status !== "draft" || edit !== null} onClick={approve}>승인</button>
            <span className="muted self-center text-[12.5px]">승인은 정비 계획 담당·관리자만 할 수 있습니다. 설비 제어나 자동 발행은 없습니다.</span>
          </div>
          {(wo.status === "approved" || wo.status === "done") && (
            <div className="mt-4 rounded-md border p-3" style={{ borderColor: "var(--line)" }}>
              <div className="mb-2 text-[14px] font-semibold">점검 결과 입력 (작업 후)</div>
              <div className="flex flex-wrap items-end gap-3 text-[13.5px]">
                <label className="flex flex-col gap-0.5">씰 마모 등급
                  <select value={rGrade} onChange={(e) => setRGrade(e.target.value)}><option value="1">1등급 (양호)</option><option value="2">2등급</option><option value="3">3등급 (심함)</option></select></label>
                <label className="flex flex-col gap-0.5">실제 원인
                  <select value={rCause} onChange={(e) => setRCause(e.target.value)}><option value="">선택</option>{Object.entries(CAUSE_NAME).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
                <label className="flex min-w-[220px] flex-1 flex-col gap-0.5">메모
                  <input className="rounded-md border px-2 py-1" style={{ borderColor: "var(--line)", background: "var(--card)", color: "var(--text)" }} value={rNote} onChange={(e) => setRNote(e.target.value)} placeholder="예: 씰 면 균열, B4 필터 막힘" /></label>
                <button className="btn" disabled={!rCause} onClick={saveResult}>결과 저장</button>
              </div>
              {rDone && <p className="mt-2 text-[13.5px]"><span className={`chip ${rDone.match ? "chip-ok" : "chip-watch"}`}>{rDone.match ? "예측한 원인과 일치" : "예측한 원인과 다름"}</span> 실제 원인: {CAUSE_NAME[rDone.cause]}. 기록만 쌓고 모델은 다시 학습하지 않습니다.</p>}
            </div>
          )}
        </Card>
      )}

      <Card className="mt-3" title="작업지시서 목록">
        {orders.length === 0 ? <p className="muted text-[14px]">아직 없습니다.</p> : (
          <table className="tbl"><thead><tr><th>번호</th><th>세그먼트</th><th>작업 시점</th><th>확률</th><th>숫자 검증</th><th>카드 밖</th><th>상태</th></tr></thead>
            <tbody>{orders.map((o) => (
              <tr key={o.wo_id}><td>{o.wo_id}</td><td>{o.segment_serial}</td><td>{o.planned_stop_date}</td><td>{pct(o.prob)}</td>
                <td>{o.numbers_ok ? "✓" : "—"}</td><td>{o.off_card}</td><td><span className={`chip ${o.status === "approved" ? "chip-ok" : "chip-watch"}`}>{o.status === "approved" ? `승인(${o.approver})` : "초안"}</span></td></tr>
            ))}</tbody></table>
        )}
      </Card>
    </div>
  );
}
