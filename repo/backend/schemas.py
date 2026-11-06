"""API 계약(응답 형식). 프론트엔드의 frontend/src/types.ts와 같은 모양으로 유지한다.

모든 값은 합성 데이터이며 기준값은 가설이다.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Level = Literal["normal", "watch", "alarm"]
Cause = Literal["leak", "clog", "pump", "sensor", "unknown"]
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


class AskOut(BaseModel):
    answer: str
    tools_used: list[str] = []
    numbers_verified: bool = True
    from_cache: bool = False
    disclaimer: str = "AI가 작성한 내용이며 사람의 확인이 필요합니다."


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
