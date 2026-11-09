// 위험 예측·보안 LLM API (기획서 4-6). 기존 api.ts와 달리 mock으로 대체하지 않는다: 실제 계산·권한 결과만 보여 준다.
const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Role = "정비담당" | "정비계획" | "수처리담당" | "관리자";
export const ROLES: Role[] = ["정비담당", "정비계획", "수처리담당", "관리자"];

export interface RiskCause { cause: string; label: string; share: number; card: string | null }
export interface RiskSegment {
  segment: string; position: number; bundle: string; rank: number; prob_next_stop: number; prob_14d: number; horizon_days: number;
  joint_age_t: number; days_since_install: number; top_cause: string; top_cause_label: string; causes: RiskCause[];
  signals: { low_flow_index: number; bearing_rise_c: number; vib_increase: number; pressure_test: number };
}
export interface RiskBoard { as_of: string; next_planned_stop: string; segments: RiskSegment[]; note: string; coefficients: unknown[] }

export interface Checks {
  numbers_ok?: boolean; citations_ok?: boolean; pii_ok?: boolean; no_forbidden_leak?: boolean; control_ok?: boolean; fallback?: boolean;
  required_ok?: boolean; actions_cited_ok?: boolean; off_card?: number; bad_numbers?: string[]; missing_sections?: string[]; llm_error?: string | null;
}
export interface AskResult {
  answer: string; outcome: "answered" | "blocked" | "denied" | "refused"; reason: string; mode: string; model: string; role: string;
  citations: { ref: string; title: string; tier: string }[]; tools_used: string[]; checks: Checks; masked_count: number;
  dropped_injection: string[]; audit_id: number; disclaimer: string;
}
export interface WorkOrder {
  ok: boolean; outcome?: string; message?: string; wo_id: string; status: string; mode: string; model: string; retries: number;
  draft_md: string; checks: Checks; cited: string[]; masked_count: number;
}
export interface WoRow { wo_id: string; segment_serial: string; position: number; planned_stop_date: string; prob: number; rank: number; top_cause: string; status: string; numbers_ok: number; off_card: number; approver: string | null; mode: string; draft_md?: string }
export interface PolicyRole { role: string; desc: string; max_tier: number; clauses: number; total_clauses: number; tools: string[]; docs: { doc_id: string; title: string; clauses: number; tiers: string[] }[] }
export interface AuditRow { id: number; ts: number; user: string; role: string; kind: string; question: string; refs: string[]; tools: string[]; masked: number; outcome: string; reason: string; answer: string; mode: string; model: string }
export interface RedteamMode { defense_rate: number; attack_cases: number; normal_pass_rate: number; normal_cases: number; restricted_leaks: number; heldout_defense_rate: number; heldout_cases: number;
  by_category: Record<string, { n: number; pass: number; rate: number }>; failures: { cat: string; role: string; q: string; outcome: string }[] }
export interface Redteam { rules: RedteamMode; claude?: RedteamMode; note: string }

export class ApiError extends Error { constructor(public status: number, msg: string) { super(msg); } }

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${BASE}${path}`, { method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  } catch { throw new ApiError(0, "백엔드에 연결하지 못했습니다."); }
  if (!r.ok) {
    let msg = String(r.status);
    try { const j = await r.json(); msg = j.detail ?? msg; } catch { /* 본문 없음 */ }
    throw new ApiError(r.status, msg);
  }
  return (await r.json()) as T;
}

export const llm = {
  board: () => call<RiskBoard>("GET", "/api/risk/board"),
  ask: (role: Role, user: string, question: string) => call<AskResult>("POST", "/api/llm/ask", { role, user, question }),
  createWo: (role: Role, user: string, segment: string) => call<WorkOrder>("POST", "/api/llm/workorders", { role, user, segment }),
  listWo: () => call<WoRow[]>("GET", "/api/llm/workorders"),
  getWo: (id: string) => call<WoRow & { draft_md: string; checks: string }>("GET", `/api/llm/workorders/${id}`),
  editWo: (id: string, role: Role, user: string, draft_md: string) => call<WoRow & { draft_md: string }>("PUT", `/api/llm/workorders/${id}`, { role, user, draft_md }),
  approveWo: (id: string, role: Role, user: string) => call<WoRow>("POST", `/api/llm/workorders/${id}/approve`, { role, user }),
  recordResult: (id: string, role: Role, user: string, grade: string, cause: string, note: string) =>
    call<WoRow & { prediction_match: boolean }>("POST", `/api/llm/workorders/${id}/result`, { role, user, grade, cause, note }),
  policy: () => call<{ roles: PolicyRole[] }>("GET", "/api/llm/policy"),
  audit: (role: Role) => call<AuditRow[]>("GET", `/api/llm/audit?role=${encodeURIComponent(role)}&limit=40`),
  redteam: () => call<Redteam>("GET", "/api/llm/redteam"),
  riskEval: () => call<Record<string, unknown>>("GET", "/api/risk/eval"),
};
