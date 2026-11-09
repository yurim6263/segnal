import { useEffect, useRef, useState } from "react";
import AnswerText from "../components/AnswerText";
import { Card } from "../components/ui";
import { ApiError, llm, type Checks, type Role, type WoRow, type WorkOrder } from "../llmApi";

const pct = (x: number) => `${(x * 100).toFixed(1)}%`;
const APPROVERS: Role[] = ["정비계획", "관리자"];     // 화면 표시용. 실제 권한 검사는 backend/llm/workorder.py의 APPROVE_ROLES

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

export default function WorkOrderView({ role, user, openWoId }: { role: Role; user: string; openWoId?: string | null }) {
  const [wo, setWo] = useState<WorkOrder | null>(null);
  const [orders, setOrders] = useState<WoRow[] | null>(null);
  const [edit, setEdit] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const topRef = useRef<HTMLDivElement>(null);

  const reload = () => llm.listWo().then(setOrders).catch((e: ApiError) => { setOrders([]); setMsg(e.message); });
  const open = async (id: string) => {
    setMsg(""); setEdit(null);
    try {
      const r = await llm.getWo(id, role);
      const checks: Checks = { ...JSON.parse(r.checks), numbers_ok: !!r.numbers_ok };   // 수정된 문서는 DB의 numbers_ok만 꺼지고 checks 원문은 그대로다
      setWo({ ok: true, wo_id: r.wo_id, status: r.status, mode: r.mode, model: "", retries: 0, draft_md: r.draft_md, checks, cited: JSON.parse(r.docs_cited), approver: r.approver });
      topRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) { setMsg((e as Error).message); }
  };
  useEffect(() => { reload(); }, []);
  useEffect(() => { if (openWoId) open(openWoId); }, [openWoId]);
  useEffect(() => { if (role === "수처리담당") setWo(null); }, [role]);     // 열람 권한이 없는 역할로 바뀌면 열린 카드를 닫는다

  const approve = async () => {
    if (!wo) return;
    try { await llm.approveWo(wo.wo_id, role, user); setWo({ ...wo, status: "approved", approver: user }); setMsg(`${wo.wo_id} 승인됨 (승인자: ${user}, 역할: ${role})`); reload(); }
    catch (e) { setMsg(`승인 거부: ${(e as ApiError).message}`); }
  };
  const saveEdit = async () => {
    if (!wo || edit === null) return;
    try { await llm.editWo(wo.wo_id, role, user, edit); setWo({ ...wo, draft_md: edit, mode: `${wo.mode}+edited`, checks: { ...wo.checks, numbers_ok: false } }); setEdit(null); setMsg("수정했습니다. 수정한 문서는 자동 숫자 검증을 다시 통과한 것이 아니므로 검증 표시를 껐습니다."); reload(); }
    catch (e) { setMsg((e as ApiError).message); }
  };

  return (
    <div className="space-y-3">
      <div ref={topRef} />
      {msg && <p className="info-strip">{msg}</p>}

      {wo && (
        <Card title={`작업지시서 ${wo.wo_id}`} sub={wo.status === "approved" ? `승인됨${wo.approver ? ` (${wo.approver})` : ""}` : "초안 — 담당자 승인 전"}
          right={`${wo.mode.startsWith("llm") ? "Claude가 작성" : "양식 모드(규칙 기반)"}${wo.mode.endsWith("+edited") ? " · 담당자 수정" : ""}`}>
          <div className="mb-3"><CheckRow c={wo.checks} /></div>
          {wo.checks.llm_error && <p className="muted mb-2 text-[12.5px]">모델 호출이 실패해 양식 모드로 대체됨: {wo.checks.llm_error}</p>}
          {edit === null ? <AnswerText text={wo.draft_md} /> : <textarea className="w-full text-[14px]" rows={16} value={edit} onChange={(e) => setEdit(e.target.value)} />}
          <p className="muted mt-2 text-[12.5px]">인용 조항: {wo.cited.join(", ")}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {edit === null ? <button className="btn" disabled={wo.status !== "draft"} onClick={() => setEdit(wo.draft_md)}>수정</button> : <button className="btn" onClick={saveEdit}>수정 저장</button>}
            <button className="btn btn-primary" disabled={wo.status !== "draft" || edit !== null || !APPROVERS.includes(role)} onClick={approve}>승인</button>
            <span className="muted self-center text-[12.5px]">승인은 정비 계획 담당·관리자만 할 수 있습니다. 설비 제어나 자동 발행은 없습니다.</span>
          </div>
        </Card>
      )}

      <Card title="작업지시서 목록" sub="행을 누르면 내용을 열어 검토·승인합니다">
        {orders === null ? <p className="muted text-[14px]">불러오는 중…</p> : orders.length === 0 ? <p className="muted text-[14px]">아직 없습니다. 위험 예측이나 휴지 교체 계획 탭에서 만들 수 있습니다.</p> : (
          <div className="overflow-x-auto"><table className="tbl"><thead><tr><th>번호</th><th>세그먼트</th><th>작업 시점</th><th>확률</th><th>숫자 검증</th><th>카드 밖</th><th>상태</th><th></th></tr></thead>
            <tbody>{orders.map((o) => (
              <tr key={o.wo_id} onClick={() => open(o.wo_id)} style={{ cursor: "pointer", background: o.wo_id === wo?.wo_id ? "var(--primary-soft)" : undefined }}><td className="whitespace-nowrap">{o.wo_id}</td><td>{o.segment_serial}</td><td className="whitespace-nowrap">{o.planned_stop_date}</td><td>{pct(o.prob)}</td>
                <td>{o.numbers_ok ? "✓" : "—"}</td><td>{o.off_card}</td><td><span className={`chip ${o.status === "approved" ? "chip-ok" : "chip-watch"}`}>{o.status === "approved" ? `승인(${o.approver})` : "초안"}</span></td>
                <td><button className="chip" style={{ cursor: "pointer" }} onClick={(e) => { e.stopPropagation(); open(o.wo_id); }}>보기</button></td></tr>
            ))}</tbody></table></div>
        )}
      </Card>
    </div>
  );
}
