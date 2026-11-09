// 위험 예측·보안 LLM API (기획서 4-6). mock으로 대체하지 않는다: 실제 계산·권한 결과만 보여 준다.
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

export interface SegmentHistoryData {
  segment: string;
  days: Array<Record<string, number | string | null>>;       // 신호 열과 같은 날 장착 평균 fleet_ 열
  maintenance: { date: string; part: string; type: string; finding_grade: number | null; found_cause: string | null; wo_id: string | null }[];
}

export interface Checks {
  numbers_ok?: boolean; citations_ok?: boolean; pii_ok?: boolean; no_forbidden_leak?: boolean; control_ok?: boolean; fallback?: boolean;
  required_ok?: boolean; actions_cited_ok?: boolean; off_card?: number; bad_numbers?: string[]; missing_sections?: string[]; llm_error?: string | null;
}
export interface WorkOrder {
  ok: boolean; outcome?: string; message?: string; wo_id: string; status: string; mode: string; model: string; retries: number;
  draft_md: string; checks: Checks; cited: string[]; masked_count: number;
}
export interface WoRow { wo_id: string; segment_serial: string; position: number; planned_stop_date: string; prob: number; rank: number; top_cause: string; status: string; numbers_ok: number; off_card: number; approver: string | null; mode: string; draft_md?: string }

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
  createWo: (role: Role, user: string, segment: string) => call<WorkOrder>("POST", "/api/llm/workorders", { role, user, segment }),
  listWo: () => call<WoRow[]>("GET", "/api/llm/workorders"),
  editWo: (id: string, role: Role, user: string, draft_md: string) => call<WoRow & { draft_md: string }>("PUT", `/api/llm/workorders/${id}`, { role, user, draft_md }),
  approveWo: (id: string, role: Role, user: string) => call<WoRow>("POST", `/api/llm/workorders/${id}/approve`, { role, user }),
  roles: () => call<{ llm_available: boolean }>("GET", "/api/llm/roles"),
  history:(segment: string) => call<SegmentHistoryData>("GET", `/api/risk/segments/${segment}/history`),
};
