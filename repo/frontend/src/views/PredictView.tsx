import { useEffect, useState } from "react";
import CasterArc from "../components/CasterArc";
import SegmentHistory, { HeroTrend } from "../components/SegmentHistory";
import { Bar, Card } from "../components/ui";
import { ApiError, llm, type Role, type RiskBoard, type RiskSegment, type SegmentHistoryData } from "../llmApi";

const causeColor = (cause: string) => `var(--cause-${cause})`;
const pct =(x: number, d = 1) => `${(x * 100).toFixed(d)}%`;

export default function PredictView({ role, user, onPlan, onOpenWo }: { role: Role; user: string; onPlan: () => void; onOpenWo: (id: string) => void }) {
  const [board, setBoard] = useState<RiskBoard | null>(null);
  const [err, setErr] = useState("");
  const [sel, setSel] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [hist, setHist] = useState<SegmentHistoryData | null>(null);

  useEffect(() => { llm.board().then((b) => { setBoard(b); setSel(b.segments[0]?.segment ?? ""); }).catch((e) => setErr(e.message)); }, []);
  useEffect(() => { if (sel) llm.history(sel).then(setHist).catch(() => setHist(null)); }, [sel]);

  if (err) return <Card title="위험 예측"><p className="muted">{err}</p></Card>;
  if (!board) return <Card title="위험 예측"><p className="muted">모델을 맞추는 중…(처음 한 번 몇 초)</p></Card>;
  const seg: RiskSegment | undefined = board.segments.find((s) => s.segment === sel);
  const max = Math.max(...board.segments.map((s) => s.prob_next_stop));
  const pick = (segment: string) => { setSel(segment); setMsg(""); };
  const byTons = [...board.segments].sort((a, b) => b.joint_age_t - a.joint_age_t);
  const topCause = seg?.causes.find((c) => c.cause === seg.top_cause);

  const make = async () => {
    if (!seg) return;
    setBusy(true); setMsg("");
    try {
      const r = await llm.createWo(role, user, seg.segment);
      if (r.ok === false) setMsg(r.message ?? "생성할 수 없습니다.");
      else onOpenWo(r.wo_id);
    } catch (e) { setMsg((e as ApiError).message); }
    setBusy(false);
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
    </div>
  );
}
