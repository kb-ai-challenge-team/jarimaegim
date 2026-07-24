from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, HttpUrl, model_validator


class BusinessStage(StrEnum):
    PRE_OPEN = "PRE_OPEN"
    RELOCATING = "RELOCATING"
    SECOND_STORE = "SECOND_STORE"


class StartupType(StrEnum):
    INDEPENDENT = "INDEPENDENT"
    FRANCHISE = "FRANCHISE"
    UNDECIDED = "UNDECIDED"


class CaseInput(BaseModel):
    industry: str = Field(min_length=1, max_length=120)
    district: str = Field(min_length=1, max_length=20)
    budget_krw: int = Field(gt=0, le=100_000_000_000)
    equity_krw: int = Field(ge=0, le=100_000_000_000)
    business_stage: BusinessStage
    startup_type: StartupType
    priority: Literal["STABILITY", "DEMAND", "COST", "GROWTH"] = "STABILITY"


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    inputs: CaseInput


class CasePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    inputs: dict[str, Any] = Field(default_factory=dict)


class CaseRecord(BaseModel):
    id: UUID
    title: str
    version: int
    status: str
    inputs: CaseInput
    created_at: datetime
    updated_at: datetime


class SessionCreate(BaseModel):
    retention_notice_accepted: bool


class LocationSearch(BaseModel):
    case_id: UUID
    industry: str = Field(min_length=1, max_length=120)
    district: str = Field(min_length=1, max_length=20)
    limit: int = Field(default=12, ge=1, le=15)


class ContextSignal(BaseModel):
    name: str
    label: str
    score_band: Literal["FAVORABLE", "NEUTRAL", "CAUTION", "UNKNOWN"]
    direction: Literal["POSITIVE", "NEUTRAL", "RISK", "UNKNOWN"]
    explanation: str


class Provenance(BaseModel):
    source_name: str
    official_url: str | None = None
    source_as_of: str | None = None
    published_at: str | None = None
    collected_at: str | None = None
    verified_at: str | None = None
    industry_scope: str
    spatial_unit: str
    model_version: str | None = None
    sample_n: int | None = None
    confidence: Literal["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"]
    limitations: list[str]


class Candidate(BaseModel):
    id: str
    name: str
    address: str
    road_address: str | None = None
    latitude: float
    longitude: float
    distance_m: int | None = None
    evidence_grade: Literal["A", "B", "C", "U"]
    display_label: str
    context_signals: list[ContextSignal]
    provenance: Provenance


class AnalysisCreate(BaseModel):
    case_id: UUID
    candidate_id: str
    requested_as_of: date | None = None


class AnalysisResult(BaseModel):
    analysis_id: UUID
    status: Literal["completed", "blocked"]
    evidence_grade: Literal["A", "B", "C", "U"]
    display_label: str
    survival_grade: Literal["A", "B", "C", "D", "E"] | None = None
    context_risk_grade: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    probability_lower: float | None = None
    probability_upper: float | None = None
    probability_unit: Literal["PERCENT_0_100"] | None = None
    horizon_months: int | None = None
    confidence: Literal["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"]
    sample_n: int | None = None
    event_n: int | None = None
    context_signals: list[ContextSignal] = Field(default_factory=list)
    blocked_reason: str | None = None
    required_actions: list[str] = Field(default_factory=list)
    provenance: Provenance
    limitations: list[str]

    @model_validator(mode="after")
    def evidence_contract(self):
        probability_values = (self.probability_lower, self.probability_upper, self.probability_unit, self.horizon_months)
        if self.evidence_grade == "A":
            if self.survival_grade is None or any(value is None for value in probability_values) or not self.sample_n or self.event_n is None:
                raise ValueError("A evidence requires complete individual cohort output")
            if not 0 <= float(self.probability_lower) <= float(self.probability_upper) <= 100:
                raise ValueError("probability bounds are invalid")
            if self.context_risk_grade is not None or self.blocked_reason is not None:
                raise ValueError("A evidence contains incompatible fields")
        elif self.evidence_grade == "B":
            if self.context_risk_grade is None or self.sample_n is None:
                raise ValueError("B evidence requires aggregate risk and sample")
            if self.survival_grade is not None or any(value is not None for value in probability_values):
                raise ValueError("B evidence must not contain individual output")
        elif self.evidence_grade == "C":
            if self.survival_grade is not None or self.context_risk_grade is not None or any(value is not None for value in probability_values) or self.event_n is not None:
                raise ValueError("C evidence must contain context only")
        elif self.evidence_grade == "U":
            if not self.blocked_reason or self.sample_n is not None or self.event_n is not None or self.survival_grade is not None or self.context_risk_grade is not None or any(value is not None for value in probability_values):
                raise ValueError("U evidence must contain only a blocked reason")
        return self


class CostItem(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=100)
    min_krw: int | None = Field(default=None, ge=0)
    max_krw: int | None = Field(default=None, ge=0)
    source_type: Literal["USER", "OFFICIAL", "ESTIMATE", "UNAVAILABLE"]
    note: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def range_contract(self):
        if self.source_type == "UNAVAILABLE":
            self.min_krw = None
            self.max_krw = None
        elif self.min_krw is None or self.max_krw is None:
            raise ValueError("available amount requires min and max")
        elif self.max_krw < self.min_krw:
            raise ValueError("max must be greater than or equal to min")
        return self


class CostPlanCreate(BaseModel):
    case_id: UUID
    items: list[CostItem]


class MessageCreate(BaseModel):
    client_message_id: UUID
    content: str = Field(min_length=1, max_length=4000)
    base_case_version: int = Field(gt=0)
    confirmed_case_patch: list[dict[str, Any]] = Field(default_factory=list)
    locale: str = "ko-KR"


class DocumentCreate(BaseModel):
    case_id: UUID
    template: Literal["location", "cost", "funding", "business", "checklist"]
    confirmed: bool


class PrivacyRequestCreate(BaseModel):
    request_type: Literal["ACCESS", "RECTIFY", "ERASE", "RESTRICT", "WITHDRAW_CONSENT"]
    verification_method: Literal["ACCOUNT_REAUTH", "ANON_COOKIE", "EMAIL_CHALLENGE"]
