// API 계약 — backend/schemas.py 와 같은 모양으로 유지한다.

export type Level = "normal" | "watch" | "alarm";
export type Cause = "leak" | "clog" | "pump" | "sensor" | "ambiguous" | "unknown";
export type Side = "in" | "out";

export interface PlantConfig {
  n_segments: number;
  sensor_groups: number[][];
  rolls_per_segment: number;
  joints_per_roll: number;
}

export interface ScenarioInfo {
  id: string;
  name: string;
  description: string;
  n_samples: number;
  sensor_layout: "S-A" | "S-B";
}

export type InspectResult = "no_issue" | "leak_confirmed";

export interface SegmentStatus {
  segment: number;
  level: Level;
  group: number;
  inspected?: InspectResult | null;
}

export interface GroupStatus {
  group: number;
  segments: number[];
  level: Level;
  deviation: number;
}

export interface SegmentCandidate {
  segment: number;
  prob: number;
  rank: number;
  inspected?: InspectResult | null;
  inspect_minutes: number;
  access_risk: number;
  priority_score: number;
  priority_rank: number;
  evidence: string[];
}

export interface InspectionRecord {
  id: number;
  segment: number;
  result: InspectResult;
  sim_ts: number | null;
}

export interface CauseRow {
  cause: Cause;
  label: string;
  pattern: string;
  now: string;
  verdict: string;
}

export interface OperatingInfo {
  cast_speed: number;
  steel_grade: string;
  t_in: number;
  changed_recently: boolean;
}

export interface Summary {
  headline: string;
  detail: string;
  primary_label?: string | null;
  primary_tab?: string | null;
  secondary_label?: string | null;
  secondary_tab?: string | null;
}

export interface DetectorState {
  fixed_alarm_ts: number | null;
  ewma_alarm_ts: number | null;
  cusum_alarm_ts: number | null;
}

export interface Candidate {
  id: string;
  segment: number;
  roll: number;
  side: Side;
  prob: number;
  prior: number;
  evidence: string[];
  rank: number;
  inspect_minutes: number;
  access_risk: number;
  priority_score: number;
  priority_rank: number;
}

export interface ImpactRange {
  start_m: number;
  end_m: number;
  label: string;
}

export interface Alert {
  level: Level;
  cause: Cause;
  since_ts: number | null;
  group: number | null;
  message: string;
  detectors: DetectorState;
}

export interface PatternRank { cls: string; label: string; angle: number }
export interface PatternSignal { key: string; label: string; sigma: number }
/** 원인 구분(신호 변화 방향 비교) 결과와 근거 */
export interface PatternInfo {
  group: number;
  window_min: number;
  ambiguous: boolean;
  gap_deg: number;
  ranking: PatternRank[];
  signals: PatternSignal[];
  verdict: string;
  how_to_check: string;
}
/** 교체 필요 크기까지의 추세 시간 (지금 속도가 이어진다는 직선 가정) */
export interface ForecastInfo {
  available: boolean;
  crossed: boolean;
  hours: number | null;
  low_hours: number | null;
  high_hours: number | null;
  slope_pct_per_hour: number | null;
  current_pct: number;
  limit_pct: number;
  basis_min: number;
  reason: string;
  text: string;
  limit_lpm?: number | null;
  progress?: number | null;
}
export type AdviceAction = "now" | "next_break" | "watch" | "verify";
export interface AdviceWindow { ts: number; label: string; in_hours: number }
/** 교체 시점 권고. 교체 필요 크기와 정비 창 일정은 가정 */
export interface AdviceInfo {
  action: AdviceAction;
  headline: string;
  reasons: string[];
  cases: { label: string; text: string }[];
  action_ts: number | null;
  next_break: AdviceWindow | null;
  planned_stop: AdviceWindow | null;
  limit_lpm: number;
  current_lpm: number | null;
  progress: number | null;
  assumptions: string[];
}
export interface LeakEstimate { lpm: number; low_lpm: number; high_lpm: number; pct: number; flow_lpm: number; conditional: boolean }

export interface State {
  scenario_id: string;
  ts: number;
  cast_speed: number;
  steel_grade: string;
  segments: SegmentStatus[];
  alert: Alert;
  candidates: Candidate[];
  impact: ImpactRange | null;
  is_synthetic: boolean;
  summary: Summary;
  groups: GroupStatus[];
  segment_candidates: SegmentCandidate[];
  others_prob: number;
  distinguishable: boolean;
  candidate_note: string;
  inspections: InspectionRecord[];
  confirmed_segment: number | null;
  minutes_since_alarm: number | null;
  minutes_to_confirm: number | null;
  cause_table: CauseRow[];
  operating: OperatingInfo | null;
  pattern?: PatternInfo | null;
  forecast?: ForecastInfo | null;
  leak_estimate?: LeakEstimate | null;
  advice?: AdviceInfo | null;
}

export interface SeriesPoint {
  ts: number;
  value: number;
  baseline: number | null;
  residual: number | null;
  ewma: number | null;
  cusum: number | null;
  fixed_value?: number | null;
}

export interface Series {
  scenario_id: string;
  group: number;
  name: string;
  unit: string;
  points: SeriesPoint[];
  ewma_limit: number | null;
  cusum_limit: number | null;
  fixed_limit: number | null;
}

export interface JointRisk {
  joint_id: string;
  segment: number;
  roll: number;
  side: Side;
  age_days: number;
  hazard: number;
  access_risk: number;
  inspect_minutes: number;
  replace_count: number;
}

export interface ProposedAction { segment: number; result: InspectResult; reason: string }
export interface AskOut {
  answer: string;
  tools_used: string[];
  numbers_verified: boolean;
  from_cache: boolean;
  disclaimer: string;
  mode: "llm" | "cache" | "template";
  proposed_action: ProposedAction | null;
  note: string;
}
export interface AgentStatus { llm_available: boolean; model_qa: string | null; model_note: string | null; presets: string[] }

export interface HandoverValue { label: string; value: string; source: string }
export interface HandoverSection { title: string; text: string; values: HandoverValue[] }
export interface Handover {
  text: string;
  title: string;
  generated_by: "llm" | "template";
  ready: boolean;
  sections: HandoverSection[];
  missing: string[];
  sources: HandoverValue[];
  fallback_reason?: string;
}

export interface DetectorRow {
  label: string;
  detector: string;
  false_alarms_per_14d_per_group: number;
  detected: number;
  missed: number;
  n: number;
  median_delay_min: number | null;
  p90_delay_min: number | null;
  median_leak_lpm_at_detection: number | null;
}
export interface InspectionPolicy { mean_inspections: number; mean_minutes: number; mean_exposure: number; success_rate: number }
export interface LocalizeRow { joint_top1: number; joint_top3: number; joint_top10: number; mean_rank: number; segment_top1: number; group_top1: number }
export interface SensitivityRow {
  key: string; label: string; n_cases: number; n_leaks: number; missed: number;
  median_delay_min: number | null; false_alarms_per_14d_per_group: number | null;
  top3_hit: number | null; mean_inspections: number | null; inspection_success: number | null;
}
export interface LongrunRow { drift_scale: number; label: string; days_total: number; ours_episodes: number; fixed_episodes: number; ours_per_30d_plant: number; fixed_per_30d_plant: number }
export interface ClassRow { n: number; correct: number; acc: number | null; ambiguous?: number; unknown?: number; wrong?: number }
export interface NormalRow { drift_scale: number; label: string; [method: string]: unknown }
export interface ForecastStat { n_forecasts: number; n_available: number; n_scored: number; median_abs_err_h?: number; median_rel_err?: number; coverage?: number; available_but_never_reached: number }
export type Verdicts = { 적절?: number; 조기?: number; 늦음?: number; 놓침?: number };
export interface AdviceEval {
  plan: Record<string, number | number[]>;
  n_leaks: number;
  skipped_not_leak: number;
  main: { n: number; by_action: Record<string, Verdicts>; policy_ours: Verdicts; policy_wait: Verdicts; policy_break: Verdicts };
  lead: { n_reach_limit: number; ours_median_min: number | null; ours_before_limit: number; fixed_detected: number; fixed_median_min: number | null; fixed_before_limit: number; fixed_never: number };
  sensitivity: { limit_lpm: number; break_every_min: number; n: number; ours: Verdicts; wait: Verdicts; break: Verdicts }[];
  note: string;
}
export interface PatternEval {
  normal?: { runs_per_setting: number; days_per_run: number; rows: { drift_scale: number; label: string; [m: string]: unknown }[] } | null;
  calibration?: { chosen_delta_deg: number | null; holdout: string; rule: string; rows: { delta_deg: number; leak: ClassRow & { wrong: number; ambiguous: number }; sensor: ClassRow & { wrong: number; ambiguous: number } }[] } | null;
  advice?: AdviceEval | null;
}
export interface EvalSummary {
  longrun?: { days_per_run: number; seeds: number; rows: LongrunRow[]; note: string } | null;
  detectors: DetectorRow[];
  headline?: { ours: DetectorRow | null; fixed: DetectorRow | null };
  inspection: Record<"random" | "prob" | "o1", InspectionPolicy> | null;
  localize: Record<string, { n: number; missed: number; none: LocalizeRow; weibull: LocalizeRow }> | null;
  classify: { accuracy: number; per_class: Record<string, ClassRow>; previous_rule?: { accuracy: number; per_class: Record<string, ClassRow> } | null; method?: string } | null;
  pattern?: PatternEval | null;
  sensitivity: { n_cases: number; note: string; rows: SensitivityRow[] } | null;
}

export interface DetectorEval {
  detector: string;
  detection_delay_min: number | null;
  false_alarms: number;
  note?: string;
}

export interface PriorEval {
  prior: "none" | "uniform" | "weibull" | "mismatch";
  top1: number;
  top3: number;
  top10?: number | null;
  mean_rank?: number | null;
}
