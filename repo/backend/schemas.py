"""API 계약(응답 형식). 프론트엔드의 frontend/src/types.ts와 같은 모양으로 유지한다.

모든 값은 합성 데이터이며 기준값은 가설이다.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Level = Literal["normal", "watch", "alarm"]
Cause = Literal["leak", "clog", "pump", "sensor", "ambiguous", "unknown"]
Side = Literal["in", "out"]


class PlantConfigOut(BaseModel):
    n_segments: int
    sensor_groups: list[list[int]]
    rolls_per_segment: int
    joints_per_roll: int


class ScenarioInfo(BaseModel):
    id: str
    name: str
    description: str
    n_samples: int
    sensor_layout: Literal["S-A", "S-B"]


class SegmentStatus(BaseModel):
    segment: int
    level: Level
    group: int = Field(description="이 세그먼트가 속한 계측 묶음 번호(0부터)")
    inspected: Optional[Literal["no_issue", "leak_confirmed"]] = None


class DetectorState(BaseModel):
    """검출기별 경보 시각(분 단위 샘플 인덱스). None이면 아직 경보 없음."""
    fixed_alarm_ts: Optional[int] = None
    ewma_alarm_ts: Optional[int] = None
    cusum_alarm_ts: Optional[int] = None


class Candidate(BaseModel):
    id: str = Field(description="예: S5-R3-in")
    segment: int
    roll: int
    side: Side
    prob: float = Field(description="후보 사후확률")
    prior: float = Field(description="수명 모델 사전확률")
    evidence: list[str] = []
    rank: int
    # O1 점검 순서
    inspect_minutes: float = 0.0
    access_risk: float = 0.0
    priority_score: float = 0.0
    priority_rank: int = 0


class ImpactRange(BaseModel):
    """O2: 영향을 받은 슬래브 구간 (몰드 출구로부터의 길이, m)."""
    start_m: float
    end_m: float
    label: str


class AlertOut(BaseModel):
    level: Level
    cause: Cause = "unknown"
    since_ts: Optional[int] = None
    group: Optional[int] = None
    message: str = ""
    detectors: DetectorState = DetectorState()


class GroupStatus(BaseModel):
    group: int                              # 0부터
    segments: list[int]
    level: Level
    deviation: float = Field(description="기준선 대비 편차 / 경보 한계 (1이면 한계). 부호 있음")


class SegmentCandidate(BaseModel):
    segment: int
    prob: float
    rank: int
    inspected: Optional[Literal["no_issue", "leak_confirmed"]] = None
    inspect_minutes: float = 0.0
    access_risk: float = 0.0
    priority_score: float = 0.0
    priority_rank: int = 0
    evidence: list[str] = []


class InspectionRecord(BaseModel):
    id: int
    segment: int
    result: Literal["leak_confirmed", "no_issue"]
    sim_ts: Optional[int] = None


class CauseRow(BaseModel):
    cause: Cause
    label: str
    pattern: str
    now: str
    verdict: str


class OperatingInfo(BaseModel):
    cast_speed: float
    steel_grade: str
    t_in: float
    changed_recently: bool = False


class Summary(BaseModel):
    headline: str
    detail: str
    primary_label: Optional[str] = None
    primary_tab: Optional[str] = None
    secondary_label: Optional[str] = None
    secondary_tab: Optional[str] = None


class PatternRank(BaseModel):
    cls: str
    label: str
    angle: float = Field(description="관측한 변화 방향과 이 고장의 기준 방향 사이각(도). 작을수록 가깝다")


class PatternSignal(BaseModel):
    key: str
    label: str
    sigma: float = Field(description="평소 흔들림 폭(σ)의 몇 배 움직였나. 부호 있음")


class PatternOut(BaseModel):
    """원인 구분(신호 변화 방향 비교) 결과와 근거."""
    group: int                                  # 1부터
    window_min: int
    ambiguous: bool
    gap_deg: float = Field(description="1위와 2위 사이각 차이(도). 작으면 구분 불가")
    ranking: list[PatternRank] = []
    signals: list[PatternSignal] = []
    verdict: str = ""
    how_to_check: str = ""


class ForecastOut(BaseModel):
    """교체 필요 크기까지의 추세 시간 (지금 속도가 이어진다고 가정한 직선 추세)."""
    available: bool
    crossed: bool = False
    hours: Optional[float] = None
    low_hours: Optional[float] = None
    high_hours: Optional[float] = None
    slope_pct_per_hour: Optional[float] = None
    current_pct: float = 0.0
    limit_pct: float = 0.0
    basis_min: int = 0
    reason: str = ""
    text: str = ""
    limit_lpm: Optional[float] = None
    progress: Optional[float] = Field(default=None, description="지금 추정 누수량 / 교체 필요 크기. 1이면 도달")


class AdviceCase(BaseModel):
    label: str
    text: str


class WindowOut(BaseModel):
    ts: int
    label: str
    in_hours: float


class AdviceOut(BaseModel):
    """교체 시점 권고. 교체 필요 크기와 정비 창 일정은 가정이다."""
    action: Literal["now", "next_break", "watch", "verify"]
    headline: str
    reasons: list[str] = []
    cases: list[AdviceCase] = []
    action_ts: Optional[int] = None
    next_break: Optional[WindowOut] = None
    planned_stop: Optional[WindowOut] = None
    limit_lpm: float
    current_lpm: Optional[float] = None
    progress: Optional[float] = None
    assumptions: list[str] = []


class LeakEstimateOut(BaseModel):
    lpm: float
    low_lpm: float
    high_lpm: float
    pct: float
    flow_lpm: float
    conditional: bool = Field(default=False, description="True면 원인이 구분 불가라 '누수라면'의 값")


class StateOut(BaseModel):
    scenario_id: str
    ts: int
    cast_speed: float
    steel_grade: str
    segments: list[SegmentStatus]
    alert: AlertOut
    candidates: list[Candidate] = []
    impact: Optional[ImpactRange] = None
    is_synthetic: bool = True
    summary: Summary = Summary(headline="", detail="")
    groups: list[GroupStatus] = []
    segment_candidates: list[SegmentCandidate] = []
    others_prob: float = 0.0
    distinguishable: bool = True
    candidate_note: str = ""
    inspections: list[InspectionRecord] = []
    confirmed_segment: Optional[int] = None
    minutes_since_alarm: Optional[int] = None
    minutes_to_confirm: Optional[int] = None
    cause_table: list[CauseRow] = []
    operating: Optional[OperatingInfo] = None
    pattern: Optional[PatternOut] = None
    forecast: Optional[ForecastOut] = None
    leak_estimate: Optional[LeakEstimateOut] = None
    advice: Optional[AdviceOut] = None


class SeriesPoint(BaseModel):
    ts: int
    value: float
    baseline: Optional[float] = None
    residual: Optional[float] = None
    ewma: Optional[float] = None
    cusum: Optional[float] = None
    fixed_value: Optional[float] = None


class SeriesOut(BaseModel):
    scenario_id: str
    group: int
    name: str
    unit: str
    points: list[SeriesPoint]
    ewma_limit: Optional[float] = None
    cusum_limit: Optional[float] = None
    fixed_limit: Optional[float] = None


class JointRisk(BaseModel):
    joint_id: str
    segment: int
    roll: int
    side: Side
    age_days: float
    hazard: float = Field(description="다음 구간의 조건부 고장 확률")
    access_risk: float
    inspect_minutes: float
    replace_count: int


class InspectionIn(BaseModel):
    scenario_id: str
    candidate_id: str
    result: Literal["leak_confirmed", "no_issue"]
    ts: Optional[int] = None


class InspectionOut(BaseModel):
    ok: bool
    candidates: list[Candidate] = []
    inspections: list[InspectionRecord] = []


class AskIn(BaseModel):
    scenario_id: str
    question: str
    ts: Optional[int] = None


class ProposedAction(BaseModel):
    segment: int
    result: str
    reason: str = ""


class AskOut(BaseModel):
    answer: str
    tools_used: list[str] = []
    numbers_verified: bool = True
    from_cache: bool = False
    disclaimer: str = "AI가 작성한 내용이며 사람의 확인이 필요합니다."
    mode: str = "template"                       # llm | cache | template
    proposed_action: Optional[ProposedAction] = None
    note: str = ""


class HandoverValue(BaseModel):
    label: str
    value: str
    source: str


class HandoverSection(BaseModel):
    title: str
    text: str
    values: list[HandoverValue] = []


class HandoverOut(BaseModel):
    text: str = ""
    title: str = ""
    generated_by: Literal["llm", "template"] = "template"
    ready: bool = False
    sections: list[HandoverSection] = []
    missing: list[str] = []
    sources: list[HandoverValue] = []
    fallback_reason: str = ""


class HandoverPolishIn(BaseModel):
    scenario_id: str
    ts: Optional[int] = None


class CostIn(BaseModel):
    """세그먼트 교체 비용 입력. 모두 현장 값을 넣는다 (금액 단위는 호출자가 통일, 시간은 시간(h)·분(min)).
    비워 두면 계산하지 않고 missing 으로 알려 준다. 기본 금액은 없다."""
    direct_planned: Optional[float] = Field(None, ge=0, description="계획 교체 직접 정비비")
    direct_unplanned: Optional[float] = Field(None, ge=0, description="비계획 교체 직접 정비비")
    stop_hours_planned: Optional[float] = Field(None, ge=0, description="계획 교체로 늘어나는 정지 시간(h). 정기 정지에 편승하면 0")
    stop_hours_unplanned: Optional[float] = Field(None, ge=0, description="비계획 교체 정지 시간(h)")
    loss_per_hour: Optional[float] = Field(None, ge=0, description="시간당 생산 손실")
    restart_loss: Optional[float] = Field(None, ge=0, description="재가동 손실(정지 1회당). 생략하면 0")
    collateral_unplanned: Optional[float] = Field(None, ge=0, description="비계획 시 부수 손실. 생략하면 0(보수적)")
    failure_after_leak_min: Optional[float] = Field(None, ge=0, description="누수 시작부터 강제 정지까지(분)")
    wait_to_window_min: Optional[float] = Field(None, ge=0, description="경보부터 다음 정비 창까지(분)")


class CostOut(BaseModel):
    ready: bool
    missing: list[str] = []
    planned: Optional[dict] = None
    unplanned: Optional[dict] = None
    saving_per_event: Optional[float] = None
    collateral_included: bool = False
    conversion: Optional[dict] = None
    detector_delay_min: Optional[dict] = None
    note: str = ""


class DetectorEval(BaseModel):
    detector: str
    detection_delay_min: Optional[float]
    false_alarms: float = Field(description="정상 14일·계측 묶음 하나당 오경보 사건 수(평균)")
    note: str = ""


class PriorEval(BaseModel):
    prior: Literal["none", "uniform", "weibull", "mismatch"]
    top1: float
    top3: float
    top10: Optional[float] = None
    mean_rank: Optional[float] = None


class SegmentOut(BaseModel):
    segment_serial: str
    commission_date: str
    position: Optional[int] = None          # 예비품은 None
    bundle_id: Optional[str] = None
    install_ts: Optional[str] = None
    last_seal: Optional[str] = None
    last_rotary_joint: Optional[str] = None
    last_bearing: Optional[str] = None
    is_synthetic: bool = True


class SegmentDetail(SegmentOut):
    installs: list[dict] = []
    maintenance: list[dict] = []
    leaks: list[dict] = []


class ReplacementPlanIn(BaseModel):
    capacity: int = Field(2, ge=0, description="이번 계획 정지에서 교체 가능한 세그먼트 수 [가정]")


class ReplacementItem(BaseModel):
    rank: int
    segment: str
    position: int
    bundle: str
    prob_next_stop: float
    top_cause: str
    top_cause_label: str
    action: Literal["replace", "inspect"]


class ReplacementPlanOut(BaseModel):
    as_of: str
    next_planned_stop: str
    capacity: int
    items: list[ReplacementItem]
    is_synthetic: bool = True
