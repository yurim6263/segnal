import { useEffect, useState } from "react";
import { Card, PageHead } from "../components/ui";
import { ApiError, llm, type AuditRow, type PolicyRole, type Redteam, type RedteamMode, type Role } from "../llmApi";

const FLOW = ["① 역할 확인", "② 입력 검사(주입·제어·개인정보 요구)", "③ 권한 필터 → 검색(RAG)·모델 값 조회", "④ 문서 속 지시문 제거", "⑤ 개인정보 마스킹", "⑥ LLM 호출(교체 가능한 어댑터)", "⑦ 출력 검사(숫자·인용·유출)", "⑧ 감사 기록"];
const TIER_NAME = ["일반", "내부", "제한"];

function RtBlock({ title, m }: { title: string; m: RedteamMode }) {
  return (
    <div className="kpi">
      <div className="muted text-[12.5px]">{title}</div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <span><span className="kpi-num">{Math.round(m.defense_rate * 100)}</span><span className="kpi-unit">% 방어</span> <span className="muted text-[12.5px]">({m.attack_cases}문항)</span></span>
        <span><b>{Math.round(m.normal_pass_rate * 100)}%</b> <span className="muted text-[12.5px]">정상 질문 통과({m.normal_cases})</span></span>
        <span><b>{m.restricted_leaks}건</b> <span className="muted text-[12.5px]">제한 정보 유출</span></span>
        <span><b>{Math.round(m.heldout_defense_rate * 100)}%</b> <span className="muted text-[12.5px]">조정 후 새 문항({m.heldout_cases})</span></span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">{Object.entries(m.by_category).map(([k, v]) => <span key={k} className="chip">{k} {v.pass}/{v.n}</span>)}</div>
      {m.failures.length > 0 && <p className="muted mt-1 text-[12.5px]">놓친 문항: {m.failures.map((f) => `「${f.q}」(${f.outcome})`).join(", ")}</p>}
    </div>
  );
}

export default function SecurityView({ role }: { role: Role }) {
  const [pol, setPol] = useState<PolicyRole[]>([]);
  const [rt, setRt] = useState<Redteam | null>(null);
  const [audit, setAudit] = useState<AuditRow[] | null>(null);
  const [auditErr, setAuditErr] = useState("");

  useEffect(() => { llm.policy().then((p) => setPol(p.roles)).catch(() => setPol([])); llm.redteam().then(setRt).catch(() => setRt(null)); }, []);
  const loadAudit = () => llm.audit(role).then((r) => { setAudit(r); setAuditErr(""); }).catch((e: ApiError) => { setAudit(null); setAuditErr(e.status === 403 ? `'${role}' 역할은 감사 로그를 볼 수 없습니다. 관리자만 열람합니다.` : e.message); });
  useEffect(() => { loadAudit(); }, [role]);

  return (
    <div>
      <PageHead title="AI 보안·감사" sub="AI가 무엇을 읽을 수 있고, 어떻게 답하고, 그 기록을 어떻게 남기는가. 통제는 모델 밖(게이트웨이)에서 하고, 모델은 교체할 수 있는 부품입니다." />

      <Card title="모든 AI 호출이 거치는 길">
        <ol className="flex flex-wrap gap-1.5 text-[13.5px]">{FLOW.map((f) => <li key={f} className="chip chip-blue">{f}</li>)}</ol>
        <p className="muted mt-2 text-[13px]">AI는 도구를 스스로 고르지 않습니다. 게이트웨이가 권한 범위 안의 읽기 전용 값과 문서 조항만 골라 건넵니다. 설비 제어 기능은 없고, 작업지시서는 사람이 승인하기 전까지 초안입니다.</p>
      </Card>

      <Card className="mt-3" title="역할별 열람 범위" sub="같은 질문도 역할에 따라 AI가 받는 근거가 다릅니다">
        <table className="tbl">
          <thead><tr><th>역할</th><th>열람 등급</th><th>문서 조항</th><th>문서</th><th>모델 값 도구</th></tr></thead>
          <tbody>{pol.map((p) => (
            <tr key={p.role} style={{ background: p.role === role ? "var(--primary-soft)" : undefined }}>
              <td><b>{p.role}</b><div className="muted text-[12.5px]">{p.desc}</div></td>
              <td>{TIER_NAME.slice(0, p.max_tier + 1).join("·")}</td>
              <td><b>{p.clauses}</b> / {p.total_clauses}</td>
              <td className="text-[12.5px]">{p.docs.map((d) => `${d.doc_id}(${d.clauses})`).join(" ")}</td>
              <td className="text-[12.5px]">{p.tools.join(", ")}</td>
            </tr>))}</tbody>
        </table>
      </Card>

      <Card className="mt-3" title="공격 시험 결과" sub="범위 밖 질문 · 프롬프트 주입 · 문서 속 주입 · 개인정보 · 권한 상승 · 설비 제어">
        {rt ? (
          <div className="grid gap-3 md:grid-cols-2">
            <RtBlock title="규칙 모드(모델 없이 게이트웨이 규칙만)" m={rt.rules} />
            {rt.claude && <RtBlock title="Claude 모드(실제 모델 + 게이트웨이)" m={rt.claude} />}
          </div>
        ) : <p className="muted text-[14px]">결과 파일이 없습니다. <code>python -m eval.redteam_eval</code></p>}
        {rt && <p className="muted mt-2 text-[12.5px]">{rt.note} 일부 규칙은 시험 중 실패한 문항을 보고 보정했으므로, 보정 이후 새로 쓴 문항의 방어율을 따로 표시했습니다.</p>}
      </Card>

      <Card className="mt-3" title="감사 로그" sub="누가·언제·무엇을 물었고 어떤 조항을 AI에 넘겼는지" right={<button className="btn btn-sm" onClick={loadAudit}>새로고침</button>}>
        {auditErr ? <p className="info-strip text-[14px]">{auditErr}</p> : !audit ? <p className="muted">불러오는 중…</p> : audit.length === 0 ? <p className="muted text-[14px]">기록이 없습니다.</p> : (
          <div className="overflow-x-auto"><table className="tbl">
            <thead><tr><th>시각</th><th>사용자(역할)</th><th>종류</th><th>질문(마스킹됨)</th><th>넘긴 조항</th><th>결과</th></tr></thead>
            <tbody>{audit.map((a) => (
              <tr key={a.id}><td className="whitespace-nowrap text-[12.5px]">{new Date(a.ts * 1000).toLocaleTimeString("ko-KR")}</td><td>{a.user}({a.role})</td><td>{a.kind}</td><td className="max-w-[300px] text-[13px]">{a.question}</td>
                <td className="text-[12.5px]">{a.refs.slice(0, 4).join(", ")}{a.refs.length > 4 ? ` 외 ${a.refs.length - 4}` : ""}</td>
                <td><span className={`chip ${a.outcome === "answered" || a.outcome === "approved" ? "chip-ok" : "chip-watch"}`}>{a.outcome}{a.reason ? `·${a.reason}` : ""}</span></td></tr>))}</tbody>
          </table></div>
        )}
      </Card>
    </div>
  );
}
