// API 호출. 백엔드(8000)에 연결되지 않으면 mock JSON으로 대신한다 (병렬 개발용).
import type {
  AskOut, DetectorEval, EvalSummary, Handover, InspectionRecord, JointRisk, PlantConfig, PriorEval,
  ScenarioInfo, Series, State,
} from "./types";
import mockConfig from "./mock/config.json";
import mockScenarios from "./mock/scenarios.json";
import mockState from "./mock/state.json";
import mockSeries from "./mock/series.json";
import mockJoints from "./mock/joints.json";
import mockAsk from "./mock/ask.json";
import mockHandover from "./mock/handover.json";
import mockDetectors from "./mock/eval_detectors.json";
import mockPriors from "./mock/eval_priors.json";

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
export const USE_MOCK = (import.meta.env.VITE_USE_MOCK ?? "auto") === "true";

export let backendOnline = false; // 마지막 요청이 실제 백엔드에서 왔는지 (화면 표시용)

async function get<T>(path: string, fallback: unknown): Promise<T> {
  if (USE_MOCK) return fallback as T;
  try {
    const r = await fetch(`${BASE}${path}`);
    if (!r.ok) throw new Error(String(r.status));
    backendOnline = true;
    return (await r.json()) as T;
  } catch {
    backendOnline = false;
    return fallback as T; // 백엔드가 꺼져 있으면 mock 사용
  }
}

async function post<T>(path: string, body: unknown, fallback: unknown): Promise<T> {
  if (USE_MOCK) return fallback as T;
  try {
    const r = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(String(r.status));
    backendOnline = true;
    return (await r.json()) as T;
  } catch {
    backendOnline = false;
    return fallback as T;
  }
}

export const api = {
  config: () => get<PlantConfig>("/api/config", mockConfig),
  scenarios: () => get<ScenarioInfo[]>("/api/scenarios", mockScenarios),
  start: (scenarioId: string) => post<{ ok: boolean }>(`/api/scenarios/${scenarioId}/start`, {}, { ok: true }),
  state: (scenarioId: string, ts: number) =>
    get<State>(`/api/state?scenario_id=${scenarioId}&ts=${ts}`, mockState),
  series: (scenarioId: string, group: number, ts: number, channel = "imb_mass") =>
    get<Series>(`/api/series?scenario_id=${scenarioId}&group=${group}&ts=${ts}&channel=${channel}`, mockSeries),
  joints: () => get<JointRisk[]>("/api/joints", mockJoints),
  handover: (scenarioId: string, ts: number) => get<Handover>(`/api/handover?scenario_id=${scenarioId}&ts=${ts}`, mockHandover as unknown as Handover),
  evalSummary: () => get<EvalSummary | null>("/api/eval/summary", null),
  detectors: () => get<DetectorEval[]>("/api/eval/detectors", mockDetectors),
  priors: () => get<PriorEval[]>("/api/eval/priors", mockPriors),
  inspect: (scenario_id: string, segment: number, result: "leak_confirmed" | "no_issue", ts: number) =>
    post<{ ok: boolean; inspections: InspectionRecord[] }>(
      "/api/inspections", { scenario_id, candidate_id: `S${segment}`, result, ts },
      { ok: false, inspections: [] },
    ),
  deleteInspection: async (scenario_id: string, id: number) => {
    try { await fetch(`${BASE}/api/inspections/${id}?scenario_id=${scenario_id}`, { method: "DELETE" }); } catch { /* 백엔드 꺼짐 */ }
  },
  ask: (scenario_id: string, question: string) =>
    post<AskOut>("/api/agent/ask", { scenario_id, question }, mockAsk),
};
