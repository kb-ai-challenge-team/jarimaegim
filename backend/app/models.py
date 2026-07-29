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
    committed_listing_id: str | None = Field(default=None, max_length=64)


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


class ListingTerms(BaseModel):
    """Demo listing terms. The label is a required Literal so an unlabelled listing cannot be constructed.

    두 종류가 한 객체에 섞여 있다. 면적과 월세는 서울교통공사 지하상가 임대정보의 실측
    분포에서 나왔고, 나머지는 전부 **가정값**이다 (`pipeline/lib/attribute-constants.mjs`).
    가정값은 매물 카드와 필요자금 계산에만 쓰이며 근거등급을 올리지 않는다 — 등급 B는
    서울시 상권분석서비스의 실측 집계에서만 나온다.

    부가 속성은 전부 선택이다. 이 열이 없는 저장소(마이그레이션 이전 Supabase)에서 읽어도
    매물 자체는 그대로 뜨고, 값이 없는 항목만 화면에서 빠진다.
    """
    listing_kind: Literal["DEMO_SYNTHETIC"]
    deposit_krw: int = Field(ge=0)
    monthly_rent_krw: int = Field(gt=0)
    maintenance_fee_krw: int | None = Field(default=None, ge=0)
    area_m2: float = Field(gt=0)
    floor: int
    # ── 아래부터 가정값 ──
    key_money_krw: int | None = Field(default=None, ge=0)
    exclusive_area_m2: float | None = Field(default=None, gt=0)
    built_year: int | None = Field(default=None, ge=1900, le=2100)
    parking_slots: int | None = Field(default=None, ge=0)
    corner: bool | None = None
    elevator: bool | None = None
    floors_total: int | None = Field(default=None, ge=1)
    frontage_m: float | None = Field(default=None, gt=0)
    available_from: date | None = None

    @model_validator(mode="after")
    def area_contract(self):
        # 전용면적이 계약면적보다 클 수는 없다. 생성기 버그를 여기서 잡는다.
        if self.exclusive_area_m2 is not None and self.exclusive_area_m2 > self.area_m2:
            raise ValueError("exclusive area cannot exceed contract area")
        if self.floors_total is not None and self.floor > self.floors_total:
            raise ValueError("floor cannot exceed the building's total floors")
        return self


class DistrictSummary(BaseModel):
    """One map pin per covered district, shown before the user enters any condition."""
    district: str
    count: int = Field(ge=0)
    median_monthly_rent_krw: int = Field(ge=0)
    latitude: float
    longitude: float


class TradeAreaFit(BaseModel):
    """후보가 왜 이 순위인지. 점수는 정렬 규칙의 산출물이며 확률도 매출 예측도 아니다."""

    status: Literal["judged", "unavailable"]
    # 0~1. 판정된 축만으로 낸 가중 평균이라 축 개수가 다른 후보끼리도 같은 척도에 놓인다.
    score: float | None = Field(default=None, ge=0, le=1)
    judged_axes: list[str] = Field(default_factory=list)
    unjudged_axes: list[str] = Field(default_factory=list)
    store_count: int | None = Field(default=None, ge=0)
    trade_area_count: int | None = Field(default=None, ge=0)
    reason: str | None = None

    @model_validator(mode="after")
    def fit_contract(self):
        if self.status == "judged":
            if self.score is None or not self.judged_axes:
                raise ValueError("judged fit requires a score and at least one judged axis")
        elif self.score is not None or self.judged_axes:
            raise ValueError("unavailable fit must not carry a score")
        elif not self.reason:
            raise ValueError("unavailable fit requires a reason")
        return self


class Candidate(BaseModel):
    id: str
    name: str
    address: str
    road_address: str | None = None
    latitude: float
    longitude: float
    distance_m: int | None = None
    admin_dong: str | None = None
    admin_dong_code: str | None = Field(default=None, max_length=16)
    evidence_grade: Literal["A", "B", "C", "U"]
    display_label: str
    context_signals: list[ContextSignal]
    provenance: Provenance
    listing: ListingTerms | None = None
    trade_area_fit: TradeAreaFit | None = None


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
    # 선택은 id 로만 받는다. 이름·금리·URL 은 서버가 카탈로그에서 되찾는다 — 클라이언트가 보낸
    # 문자열을 그대로 인쇄하면 조작된 상품명과 금리가 KB 문서 모양으로 찍힌다.
    selected_product_ids: list[str] = Field(default_factory=list, max_length=10)
    selected_program_ids: list[str] = Field(default_factory=list, max_length=10)
    funding_input: "FundingFacts | None" = None


class PrivacyRequestCreate(BaseModel):
    request_type: Literal["ACCESS", "RECTIFY", "ERASE", "RESTRICT", "WITHDRAW_CONSENT"]
    verification_method: Literal["ACCOUNT_REAUTH", "ANON_COOKIE", "EMAIL_CHALLENGE"]


class FundingBand(StrEnum):
    EQUITY_ONLY = "EQUITY_ONLY"
    RECOMMENDED = "RECOMMENDED"
    MAXIMUM = "MAXIMUM"
    OUT_OF_RANGE = "OUT_OF_RANGE"


class PrescribeRequest(BaseModel):
    """메인 에이전트 1회 실행의 입력.

    업종·자치구는 케이스에서 읽는다 — 대화나 요청 본문이 확정된 조건을 바꿀 수 없다는 규칙이
    이 엔드포인트에도 그대로 적용된다. `confirmed_case_patch` 가 오면 422 다."""

    area_pyeong: float | None = Field(default=None, gt=0, le=500)
    deposit_krw: int | None = Field(default=None, ge=0, le=100_000_000_000)
    monthly_rent_krw: int = Field(ge=0, le=1_000_000_000)
    monthly_maintenance_krw: int = Field(default=0, ge=0, le=1_000_000_000)
    key_money_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    fitout_krw: int | None = Field(default=None, ge=0, le=100_000_000_000)
    existing_debt_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    other_monthly_fixed_krw: int = Field(default=0, ge=0, le=1_000_000_000)
    operating_style: str = Field(default="", max_length=60)
    #: 조건을 만든 발화. condition.location 이 아직 비어 있는 항목을 여기서 읽는다. 이미 확정된
    #: 값은 덮어쓰지 않으므로, 이 필드가 케이스 조건을 바꾸는 경로가 되지는 않는다.
    utterance: str = Field(default="", max_length=1000)
    confirmed_case_patch: list[dict[str, Any]] = Field(default_factory=list)


class ConditionInterpret(BaseModel):
    """자유 문장 한 개를 조건으로 읽는 요청. 케이스를 만들기 전에 쓰인다."""

    utterance: str = Field(min_length=1, max_length=1000)
    #: 이미 확정된 값. 채워져 있는 항목은 덮어쓰지 않는다.
    known: dict[str, Any] = Field(default_factory=dict)


class FundingFacts(BaseModel):
    """밴드 산출에 필요한 사실만. 케이스 식별자는 담지 않는다 — 문서 요청처럼 바깥에 이미
    case_id 가 있는 곳에서 두 번 싣지 않기 위해서다.

    평수·보증금은 필요자금(→현금소진)에만 쓰이므로 없어도 밴드 상한과 손익분기는 계산된다."""

    industry: str = Field(min_length=1, max_length=120)
    area_pyeong: float | None = Field(default=None, gt=0, le=500)
    deposit_krw: int | None = Field(default=None, ge=0, le=100_000_000_000)
    monthly_rent_krw: int = Field(ge=0, le=1_000_000_000)
    monthly_maintenance_krw: int = Field(default=0, ge=0, le=1_000_000_000)
    key_money_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    fitout_krw: int | None = Field(default=None, ge=0, le=100_000_000_000)
    equity_krw: int = Field(ge=0, le=100_000_000_000)
    existing_debt_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    other_monthly_fixed_krw: int = Field(default=0, ge=0, le=1_000_000_000)


class FundingBandInput(FundingFacts):
    case_id: UUID


DocumentCreate.model_rebuild()


class BandLine(BaseModel):
    band: FundingBand
    ceiling_krw: int = Field(ge=0)
    loan_krw: int = Field(ge=0)
    monthly_repayment_krw: int = Field(ge=0)
    monthly_fixed_cost_krw: int = Field(ge=0)
    target_monthly_revenue_krw: int = Field(ge=0)
    target_daily_revenue_krw: int = Field(ge=0)
    runway_months: int | None = None
    stress_pass: bool
    repayment_burden_ratio: float = Field(ge=0)
    subsidy_uplift_krw: int = Field(default=0, ge=0)
    is_estimate: bool
    trade_area_count: int | None = None

    @model_validator(mode="after")
    def band_contract(self):
        if self.band == FundingBand.MAXIMUM and not self.is_estimate:
            raise ValueError("MAXIMUM band is a pre-screening estimate and must set is_estimate")
        if self.loan_krw > 0 and self.monthly_repayment_krw <= 0:
            raise ValueError("a loan requires a positive monthly repayment")
        if self.loan_krw == 0 and self.monthly_repayment_krw != 0:
            raise ValueError("no loan must not carry a repayment")
        return self


class BreakEven(BaseModel):
    monthly_fixed_cost_krw: int = Field(ge=0)
    target_monthly_revenue_krw: int = Field(ge=0)
    target_daily_revenue_krw: int = Field(ge=0)
    contribution_margin_ratio: float = Field(gt=0, lt=1)
    assumptions: list[str] = Field(min_length=1)


class FundingCapacityInput(BaseModel):
    """조달 여력은 금융 프로필만 요구한다. 업종·임대조건은 2단계에서 받는다."""

    equity_krw: int = Field(ge=0, le=100_000_000_000)
    existing_debt_krw: int = Field(default=0, ge=0, le=100_000_000_000)


class FundingCapacityResult(BaseModel):
    """1단계의 완결 결과. 권장 조달선은 여기서 내지 않고 왜 아직 없는지를 문장으로 말한다."""

    status: Literal["computed", "integration_pending"]
    equity_line_krw: int = Field(default=0, ge=0)
    borrowing_headroom_krw: int = Field(default=0, ge=0)
    maximum_line_krw: int = Field(default=0, ge=0)
    parameter_status: Literal["VERIFIED", "DEMO"] = "VERIFIED"
    unverified_params: list[str] = Field(default_factory=list)
    recommended_line_pending: str = Field(min_length=1)
    missing_params: list[str] = Field(default_factory=list)
    message: str | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def capacity_contract(self):
        if self.unverified_params and self.parameter_status != "DEMO":
            raise ValueError("unverified parameters must mark the result as DEMO")
        if self.status == "computed" and self.maximum_line_krw < self.equity_line_krw:
            raise ValueError("maximum line cannot fall below the equity line")
        if self.status == "integration_pending":
            if not self.missing_params:
                raise ValueError("integration_pending result requires missing_params")
            if self.equity_line_krw or self.borrowing_headroom_krw or self.maximum_line_krw:
                raise ValueError("integration_pending result must not carry computed lines")
        return self


class FundingBandResult(BaseModel):
    """partial 은 밴드 상한과 손익분기는 냈으나 필요자금·현금소진을 낼 입력이 없는 상태다.
    빠진 입력을 추정으로 메우지 않고, 낼 수 있는 값까지만 내고 나머지는 None 으로 둔다."""

    status: Literal["computed", "partial", "integration_pending"]
    required_capital_krw: int | None = None
    required_capital_band: FundingBand | None = None
    bands: list[BandLine] = Field(default_factory=list)
    break_even: BreakEven | None = None
    parameter_status: Literal["VERIFIED", "DEMO"] = "VERIFIED"
    unverified_params: list[str] = Field(default_factory=list)
    missing_params: list[str] = Field(default_factory=list)
    message: str | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def result_contract(self):
        if self.unverified_params and self.parameter_status != "DEMO":
            raise ValueError("unverified parameters must mark the result as DEMO")
        if self.status == "computed":
            if not self.bands or self.break_even is None or self.required_capital_krw is None:
                raise ValueError("computed result requires bands, break_even and required capital")
            if self.missing_params:
                raise ValueError("computed result must not report missing params")
        elif self.status == "partial":
            if not self.bands or self.break_even is None:
                raise ValueError("partial result requires bands and break_even")
            if self.required_capital_krw is not None or self.required_capital_band is not None:
                raise ValueError("partial result must not carry required capital")
            if not self.missing_params:
                raise ValueError("partial result requires missing_params")
            if any(band.runway_months is not None for band in self.bands):
                raise ValueError("partial result must not carry a runway")
        else:
            if not self.missing_params:
                raise ValueError("integration_pending result requires missing_params")
            if self.bands or self.break_even is not None:
                raise ValueError("integration_pending result must not contain computed values")
        return self


class RetrievedDocument(BaseModel):
    id: str
    kind: Literal["PROGRAM", "KB_PRODUCT"]
    title: str
    organization: str
    official_url: str
    provider: str
    category: str
    excerpt: str
    similarity: float
    source_as_of: str | None = None
    collected_at: str | None = None
    application_start: str | None = None
    application_end: str | None = None
    # 코드가 구조화 필드를 비교한 결과만 들어간다. 유사도는 여기 오지 않는다.
    matched_conditions: list[str] = Field(default_factory=list)
    unknown_conditions: list[str] = Field(default_factory=list)
    # 불변조건 3. 모든 데이터 표면은 출처를 달고 나간다. ProvenanceBar가 그대로 렌더한다.
    provenance: Provenance


class RetrievalResponse(BaseModel):
    items: list[RetrievedDocument] = Field(default_factory=list)
    status: Literal["success", "integration_pending", "unavailable"]
    message: str | None = None
    evidence_grade: Literal["C"] = "C"


class ConditionField(BaseModel):
    """추출된 값 하나와 그 근거. evidence 는 사용자 원문의 부분문자열이며 서버가 검증한 뒤에만 채워진다."""

    value: str | int | None = None
    evidence: str | None = None


class ConditionInterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ConditionInterpretResult(BaseModel):
    """조건 제안. 케이스를 만들지 않으며, 사용자가 확인 화면에서 승인해야 조건이 된다.
    equity_krw·budget_krw 는 의도적으로 없다 — 1단계 금융 프로필이 소유하는 값이다."""

    source: Literal["AI", "RULE"]
    fields: dict[Literal["industry", "district", "monthly_rent_krw",
                         "business_stage", "startup_type", "priority"], ConditionField]
    unresolved: list[str] = Field(default_factory=list)
    message: str
