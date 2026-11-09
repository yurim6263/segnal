import { useEffect, useState } from "react";
import AnswerText from "../components/AnswerText";
import { Bar, Card, PageHead } from "../components/ui";
import { ApiError, llm, type Checks, type Role, type RiskBoard, type RiskSegment, type WoRow, type WorkOrder } from "../llmApi";

const CAUSE_COLOR: Record<string, string> = { WEAR: "#6b7fb3", HAMMER: "#d98e04", BEARING: "#c62828", THERMAL: "#8e5bb5", WATER: "#2a9d9d", ASSEMBLY: "#8a6d3b", RANDOM: "#9aa5b5" };
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

export default function PredictView({ role, user }: { role: Role; user: string }) {
  const [board, setBoard] = useState<RiskBoard | null>(null);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [wo, setWo] = useState<WorkOrder | null>(null);
  const [orders, setOrders] = useState<WoRow[]>([]);
  const [edit, setEdit] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [capacity, setCapacity] = useState(2);
  const [rGrade, setRGrade] = useState("2");
  const [rCause, setRCause] = useState("");
  const [rNote, setRNote] = useState("");
  const [rDone, setRDone] = useState<{ match: boolean; cause: string } | null>(null);

  const reload = () => llm.listWo().then(setOrders).catch(() => setOrders([]));
  useEffect(() => { llm.board().then((b) => { setBoard(b); setSel(b.segments[0]?.segment ?? ""); }).catch((e) => setErr(e.message)); reload(); }, []);

  if (err) return <Card title="위험 예측"><p className="muted">{err}</p></Card>;
  if (!board) return <Card title="위험 예측"><p className="muted">모델을 맞추는 중…(처음 한 번 몇 초)</p></Card>;
  const seg: RiskSegment | undefined = board.segments.find((s) => s.segment === sel);
  const max = Math.max(...board.segments.map((s) => s.prob_next_stop));
  // 교체 추천(기획서 4-5 (5)): 확률 순으로 교체 가능 수만큼 고르되, 조립 불량형은 교체 대신 점검한다(미리 교체하면 손해).
  const action: Record<string, "replace" | "check"> = {};
  let left = capacity;
  for (const s of board.segments) {
    if (s.top_cause === "ASSEMBLY") action[s.segment] = "check";
    else if (left > 0) { action[s.segment] = "replace"; left -= 1; }
  }
  const replaceList = board.segments.filter((s) => action[s.segment] === "replace");
  const checkList = board.segments.filter((s) => action[s.segment] === "check");

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
      <PageHead title="누수 위험 예측" sub={`기준일 ${board.as_of} · 다음 계획 정지 ${board.next_planned_stop} 전 누수 확률. 원인별 위험률을 더한 생존 분석 모델이며 확률은 합성 데이터 기반 예측값입니다.`} />
      <Card className="mb-3" title="다음 정지 교체 추천" sub={`${board.next_planned_stop} 계획 정지`}
        right={<label className="flex items-center gap-1.5 text-[13px]">교체 가능 수
          <input type="number" min={0} max={6} value={capacity} onChange={(e) => setCapacity(Math.max(0, Math.min(6, Number(e.target.value) || 0)))} style={{ width: 54 }} className="rounded-md border px-1.5 py-0.5" aria-label="교체 가능 수" /></label>}>
        <div className="flex flex-wrap items-center gap-2 text-[14px]">
          <b>교체 추천</b>
          {replaceList.length ? replaceList.map((s) => <span key={s.segment} className="chip chip-alarm">{s.segment} · {s.position}번 · {pct(s.prob_next_stop)}</span>) : <span className="muted">없음</span>}
        </div>
        {checkList.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[14px]">
            <b>점검만 (미리 교체 금지)</b>
            {checkList.map((s) => <span key={s.segment} className="chip chip-watch">{s.segment} · 조립 불량형</span>)}
            <span className="muted text-[12.5px]">장착 직후 위험이 큰 유형이라 새 부품으로 갈면 오히려 손해입니다. 체결 상태와 압력 시험을 점검합니다 (AC-06).</span>
          </div>
        )}
        <p className="muted mt-2 text-[12.5px]">교체 가능 수는 휴지 시간과 예비품에 따라 현업이 정합니다(기본 2개는 가정). 교체 권고선(확률 &gt; 교체 비용 ÷ 누수 1건 손실)은 현업이 비용을 정해야 계산할 수 있어 아직 표시하지 않습니다.</p>
      </Card>
      <div className="grid gap-3 lg:grid-cols-[1.25fr_1fr]">
        <Card title="위험도 순위판" sub="행을 누르면 상세가 바뀝니다">
          <table className="tbl">
            <thead><tr><th>순위</th><th>세그먼트</th><th>자리·묶음</th><th style={{ width: "30%" }}>정지 전 누수 확률</th><th>유력 원인</th><th>조치</th></tr></thead>
            <tbody>
              {board.segments.map((s) => (
                <tr key={s.segment} onClick={() => { setSel(s.segment); setWo(null); setMsg(""); }} style={{ cursor: "pointer", background: s.segment === sel ? "var(--primary-soft)" : undefined }}>
                  <td className="font-bold">{s.rank}</td>
                  <td>{s.segment}</td>
                  <td className="muted">{s.position}번 · {s.bundle}</td>
                  <td><div className="flex items-center gap-2"><div className="flex-1"><Bar value={s.prob_next_stop / Math.max(max, 0.05)} /></div><b className="w-14 text-right">{pct(s.prob_next_stop)}</b></div></td>
                  <td className="text-[13px]">{s.top_cause_label}</td>
                  <td>{action[s.segment] === "replace" ? <span className="chip chip-alarm">교체 추천</span> : action[s.segment] === "check" ? <span className="chip chip-watch">점검</span> : <span className="muted text-[12.5px]">감시</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted mt-2 text-[12.5px]">{board.note} 표시 상한은 99%입니다.</p>
        </Card>

        {seg && (
          <Card title={`${seg.segment} 상세`} sub={`${seg.position}번 자리 · 묶음 ${seg.bundle} · 위험 ${seg.rank}위`}>
            <div className="kpi mb-3"><span className="kpi-num">{pct(seg.prob_next_stop)}</span><span className="muted ml-2 text-[13px]">정지 전({seg.horizon_days}일) · 14일 {pct(seg.prob_14d, 0)}</span></div>
            <div className="mb-1 text-[13px] font-semibold">요인 기여도</div>
            <div className="flex h-4 overflow-hidden rounded" style={{ background: "var(--chart-grid)" }}>
              {seg.causes.map((c) => <div key={c.cause} title={`${c.label} ${Math.round(c.share * 100)}%`} style={{ width: `${c.share * 100}%`, background: CAUSE_COLOR[c.cause] }} />)}
            </div>
            <ul className="mt-1.5 space-y-0.5 text-[13.5px]">
              {seg.causes.map((c) => (
                <li key={c.cause} className="flex items-center gap-2"><span style={{ width: 10, height: 10, background: CAUSE_COLOR[c.cause], display: "inline-block", borderRadius: 2 }} />{c.label}<b>{Math.round(c.share * 100)}%</b>{c.card && <span className="chip chip-blue">{c.card}</span>}</li>
              ))}
            </ul>
            <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[13.5px]">
              {"low_flow_index" in seg.signals && <><span className="muted">유량 저하 지수</span><b>{seg.signals.low_flow_index}</b></>}
              {"bearing_rise_c" in seg.signals && <><span className="muted">베어링 온도 상승</span><b>{seg.signals.bearing_rise_c}℃</b></>}
              {"vib_increase" in seg.signals && <><span className="muted">진동 증가율</span><b>{seg.signals.vib_increase}</b></>}
              <span className="muted">교체 후 누적</span><b>{seg.joint_age_t.toLocaleString()} t</b>
              <span className="muted">장착 후</span><b>{seg.days_since_install}일</b>
            </div>
            {seg.top_cause === "ASSEMBLY" && <p className="info-strip mt-3 text-[13.5px]">조립 불량형입니다. 미리 교체하지 않고 체결 상태와 장착 후 압력 시험을 점검합니다 (AC-06).</p>}
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button className="btn btn-primary" disabled={busy} onClick={make}>{busy ? "작성 중… (최대 40초)" : "작업지시서 만들기"}</button>
              <span className="muted text-[12.5px]">역할: {role} · 권한 안의 조항만 AI에 전달</span>
            </div>
          </Card>
        )}
      </div>

      {msg && <p className="info-strip mt-3">{msg}</p>}

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
