import { useEffect, useState } from "react";
import CasterArc from "../components/CasterArc";
import { Card } from "../components/ui";
import { ApiError, llm, type RiskBoard, type RiskSegment, type Role } from "../llmApi";

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
type Action = "replace" | "inspect" | "keep";
const ACTION: Record<Action, { label: string; cls: string }> = {
  replace: { label: "교체", cls: "chip-watch" }, inspect: { label: "점검 (미리 교체 금지)", cls: "chip-blue" }, keep: { label: "유지", cls: "" },
};

function PickList({ title, items }: { title: string; items: RiskSegment[] }) {
  return (
    <div className="min-w-0 p-3" style={{ background: "var(--card2)", border: "1px solid var(--chart-grid)" }}>
      <h2 className="muted text-[13.5px] font-medium">{title}</h2>
      <ul className="mt-1 space-y-1">
        {items.map((s) => (
          <li key={s.segment} className="flex flex-wrap items-baseline justify-between gap-x-3">
            <span><b className="mono text-[16px]">{s.segment}</b> <span className="muted text-[13px]">{s.position}번 · {s.bundle}</span></span>
            <span className="mono text-[13.5px]">{pct(s.prob_next_stop)} · {s.joint_age_t.toLocaleString()} t</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PlanView({ role, user, onOpenWo }: { role: Role; user: string; onOpenWo: (id: string) => void }) {
  const [board, setBoard] = useState<RiskBoard | null>(null);
  const [err, setErr] = useState("");
  const [capacity, setCapacity] = useState("2");
  const [cost, setCost] = useState("");
  const [loss, setLoss] = useState("");
  const [busy, setBusy] = useState("");
  const [results, setResults] = useState<{ segment: string; ok: boolean; text: string; woId?: string }[]>([]);

  useEffect(() => { llm.board().then(setBoard).catch((e) => setErr(e.message)); }, []);
  if (err) return <Card title="휴지 교체 계획"><p className="muted">{err}</p></Card>;
  if (!board) return <Card title="휴지 교체 계획"><p className="muted">모델을 맞추는 중…(처음 한 번 몇 초)</p></Card>;

  const segs = board.segments;
  const n = Math.max(0, Math.min(segs.length, Math.floor(Number(capacity) || 0)));
  // 기획서 4-5 (5) ②: 조립 불량형은 미리 바꾸면 손해라 교체 수에 넣지 않고 점검으로 뺀다
  const chosen = segs.filter((s) => s.top_cause !== "ASSEMBLY").slice(0, n);
  const cut = chosen.length ? chosen[chosen.length - 1].rank : 0;
  const actionOf = (s: RiskSegment): Action => (chosen.includes(s) ? "replace" : s.top_cause === "ASSEMBLY" && s.rank <= cut ? "inspect" : "keep");
  const byTons = [...segs].sort((a, b) => b.joint_age_t - a.joint_age_t).slice(0, n);
  const same = byTons.filter((s) => chosen.includes(s)).length;
  const targets = segs.filter((s) => actionOf(s) !== "keep");
  const threshold = Number(cost) > 0 && Number(loss) > 0 ? Number(cost) / Number(loss) : null;   // 금액은 현업이 정하는 값이라 기본값을 두지 않는다

  const makeAll = async () => {
    setResults([]);
    for (const s of targets) {     // Claude 호출이 길어 한 건씩 차례로 만들고 진행 상황을 보여 준다
      setBusy(s.segment);
      try {
        const r = await llm.createWo(role, user, s.segment);
        setResults((p) => [...p, r.ok === false ? { segment: s.segment, ok: false, text: r.message ?? "생성할 수 없습니다." } : { segment: s.segment, ok: true, woId: r.wo_id, text: `초안 · ${r.mode === "llm" ? "Claude 작성" : "양식 모드"}` }]);
      } catch (e) { setResults((p) => [...p, { segment: s.segment, ok: false, text: (e as ApiError).message }]); }
    }
    setBusy("");
  };

  return (
    <div>
      <CasterArc cells={segs.map((s) => ({ position: s.position, bundle: s.bundle, serial: s.segment, prob: s.prob_next_stop, tone: actionOf(s) === "replace" ? "hot" : actionOf(s) === "inspect" ? "warm" : "plain" }))}
        ariaLabel={`연주기 단면. 다음 계획 정지에 교체할 세그먼트 ${chosen.map((s) => s.segment).join(", ") || "없음"}`}>
        <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
          <div className="min-w-0 flex-[1_1_380px]">
            <div className="text-[14.5px] font-bold" style={{ color: "var(--watch-fg)" }}>다음 계획 정지(휴지) {board.next_planned_stop} · 장착 {segs.length}개</div>
            <h1 className="mt-1 text-[28px] font-extrabold leading-tight">{chosen.length ? <>{chosen.length}개 교체 추천</> : "교체 가능 수를 입력하세요"}</h1>
            <p className="muted text-[14.5px]">정지 시간과 예비품으로 정해지는 수만큼, 다음 정지 전 누수 확률이 높은 순서로 고릅니다.</p>
          </div>
          <div className="flex flex-wrap items-end gap-2">
            <label className="text-[13px]"><span className="muted mb-1 block">교체 가능 수</span>
              <input type="number" min={0} max={segs.length} value={capacity} onChange={(e) => setCapacity(e.target.value)} className="mono w-24 text-[16px]" style={{ minHeight: 44 }} />
            </label>
            <button className="btn btn-primary" disabled={!!busy || targets.length === 0} onClick={makeAll}>{busy ? `${busy} 작성 중…` : `작업지시서 ${targets.length}건 만들기`}</button>
          </div>
        </div>
        <div className="grid min-h-0 flex-1 gap-3 overflow-y-auto md:grid-cols-2">
          <PickList title="이 시스템 · 누수 확률 순" items={chosen} />
          <PickList title="기존 방식 · 누적 톤수 순" items={byTons} />
        </div>
        <p className="text-[14px]">기존 방식과 겹치는 세그먼트는 <b className="mono">{same}</b>개입니다{chosen.length - same > 0 ? ` · ${chosen.length - same}개가 달라집니다` : ""}.</p>
      </CasterArc>

      {results.length > 0 && (
        <Card className="mt-3" title="작업지시서 묶음" sub="번호를 누르면 작업지시서 탭에서 열립니다. 승인은 정비 계획 담당·관리자만 할 수 있습니다">
          <ul className="space-y-1 text-[14px]">{results.map((r) => <li key={r.segment} className="flex flex-wrap items-center gap-2"><span className={`chip ${r.ok ? "chip-ok" : "chip-alarm"}`}>{r.ok ? "✓" : "✕"}</span><b className="mono">{r.segment}</b>{r.woId && <button className="mono underline" style={{ color: "var(--primary)", cursor: "pointer" }} onClick={() => onOpenWo(r.woId!)}>{r.woId}</button>}<span className={r.ok ? "" : "muted"}>{r.text}</span></li>)}</ul>
        </Card>
      )}

      <Card className="mt-3" title="전체 목록">
        <div className="overflow-x-auto"><table className="tbl">
          <thead><tr><th>순위</th><th>세그먼트</th><th>자리·묶음</th><th>정지 전 누수 확률</th><th>유력 원인</th><th>교체 후 누적</th><th>추천</th>{threshold != null && <th>권고선</th>}</tr></thead>
          <tbody>{segs.map((s) => (
            <tr key={s.segment}>
              <td className="font-bold">{s.rank}</td><td className="mono">{s.segment}</td><td className="muted">{s.position}번 · {s.bundle}</td><td className="mono">{pct(s.prob_next_stop)}</td>
              <td className="text-[13px]">{s.top_cause_label}</td><td className="mono text-[13px]">{s.joint_age_t.toLocaleString()} t</td><td><span className={`chip ${ACTION[actionOf(s)].cls}`}>{ACTION[actionOf(s)].label}</span></td>
              {threshold != null && <td>{s.prob_next_stop > threshold ? "넘음" : "—"}</td>}
            </tr>
          ))}</tbody>
        </table></div>
      </Card>

      <Card className="mt-3" title="교체 권고선 [가정]" sub="확률 > 교체 비용 ÷ 누수 1건 손실 (기획서 4-5). 금액은 현업이 정하는 값이라 기본값이 없습니다">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-[13px]"><span className="muted mb-1 block">세그먼트 교체 비용</span><input type="number" min={0} value={cost} onChange={(e) => setCost(e.target.value)} className="mono w-40" /></label>
          <label className="text-[13px]"><span className="muted mb-1 block">누수 1건 손실 (같은 단위)</span><input type="number" min={0} value={loss} onChange={(e) => setLoss(e.target.value)} className="mono w-40" /></label>
          <p className="text-[14px]">{threshold != null ? <>권고선 <b className="mono">{pct(threshold)}</b> · 넘는 세그먼트 <b className="mono">{segs.filter((s) => s.prob_next_stop > threshold).length}</b>개</> : <span className="muted">두 값을 넣으면 계산합니다.</span>}</p>
        </div>
      </Card>
    </div>
  );
}
