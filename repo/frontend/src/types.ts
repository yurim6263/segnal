// API 계약 — backend/schemas.py 와 같은 모양으로 유지한다.

export type Level = "normal" | "watch" | "alarm";
export type Cause = "leak" | "clog" | "pump" | "sensor" | "unknown";
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
export interface EvalSummary {
  longrun?: { days_per_run: number; seeds: number; rows: LongrunRow[]; note: string } | null;
  detectors: DetectorRow[];
  headline?: { ours: DetectorRow | null; fixed: DetectorRow | null };
  inspection: Record<"random" | "prob" | "o1", InspectionPolicy> | null;
  localize: Record<string, { n: number; missed: number; none: LocalizeRow; weibull: LocalizeRow }> | null;
  classify: { accuracy: number; per_class: Record<string, { n: number; correct: number; acc: number | null }> } | null;
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
