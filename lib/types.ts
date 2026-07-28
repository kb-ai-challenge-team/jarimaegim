export type EvidenceGrade = "A" | "B" | "C" | "U";
export type Confidence = "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT";
export type BusinessStage = "PRE_OPEN" | "RELOCATING" | "SECOND_STORE";
export type StartupType = "INDEPENDENT" | "FRANCHISE" | "UNDECIDED";

export interface CaseInput {
  industry: string;
  district: string;
  budget_krw: number;
  equity_krw: number;
  business_stage: BusinessStage;
  startup_type: StartupType;
  priority: "STABILITY" | "DEMAND" | "COST" | "GROWTH";
  committed_listing_id?: string | null;
}

export interface CaseRecord {
  id: string;
  title: string;
  version: number;
  status: string;
  inputs: CaseInput;
  created_at: string;
  updated_at: string;
}

export interface Provenance {
  source_name: string;
  official_url?: string;
  source_as_of?: string;
  published_at?: string;
  collected_at?: string;
  verified_at?: string;
  industry_scope: string;
  spatial_unit: string;
  model_version?: string;
  sample_n?: number | null;
  confidence: Confidence;
  limitations: string[];
}

/** 면적·월세는 서울교통공사 실측 분포에서, 나머지는 전부 가정값이다.
 *  가정값은 매물 카드와 필요자금 계산에만 쓰이며 근거등급을 올리지 않는다 —
 *  등급 B는 서울시 상권분석서비스의 실측 집계에서만 나온다.
 *  backend/app/models.py 의 ListingTerms 와 필드 단위로 일치해야 한다. */
export interface ListingTerms {
  listing_kind: "DEMO_SYNTHETIC";
  deposit_krw: number;
  monthly_rent_krw: number;
  maintenance_fee_krw?: number | null;
  area_m2: number;
  floor: number;
  // ── 아래부터 가정값. 전부 선택이며, 없으면 화면에서 해당 항목만 빠진다 ──
  key_money_krw?: number | null;
  exclusive_area_m2?: number | null;
  built_year?: number | null;
  parking_slots?: number | null;
  corner?: boolean | null;
  elevator?: boolean | null;
  floors_total?: number | null;
  frontage_m?: number | null;
  /** ISO date (YYYY-MM-DD) */
  available_from?: string | null;
}

/** One landing-map pin per covered district, shown before any condition is entered. */
export interface DistrictSummary {
  district: string;
  count: number;
  median_monthly_rent_krw: number;
  latitude: number;
  longitude: number;
}

/** 상권 판정 축. backend/app/ranking.py 의 PRIORITY_WEIGHTS 키와 같아야 한다. */
export type TradeAreaAxis = "demand" | "competition" | "turnover" | "sales" | "cost";

/** 후보가 왜 이 순위인지. score 는 정렬 규칙의 산출물이며 확률도 매출 예측도 아니다. */
export type TradeAreaFit =
  | {
      status: "judged";
      score: number;
      judged_axes: TradeAreaAxis[];
      unjudged_axes: TradeAreaAxis[];
      store_count?: number | null;
      trade_area_count?: number | null;
      reason?: string | null;
    }
  | {
      status: "unavailable";
      score: null;
      judged_axes: [];
      unjudged_axes: TradeAreaAxis[];
      store_count?: number | null;
      trade_area_count?: number | null;
      reason: string;
    };

export interface Candidate {
  id: string;
  name: string;
  address: string;
  road_address?: string;
  latitude: number;
  longitude: number;
  distance_m?: number;
  admin_dong?: string | null;
  admin_dong_code?: string | null;
  evidence_grade: EvidenceGrade;
  display_label: string;
  context_signals: ContextSignal[];
  provenance: Provenance;
  listing?: ListingTerms | null;
  trade_area_fit?: TradeAreaFit | null;
}

export interface ContextSignal {
  name: TradeAreaAxis | "access" | "continuity" | string;
  label: string;
  score_band: "FAVORABLE" | "NEUTRAL" | "CAUTION" | "UNKNOWN";
  direction: "POSITIVE" | "NEUTRAL" | "RISK" | "UNKNOWN";
  explanation: string;
}

interface AnalysisBase {
  analysis_id: string;
  status: "completed" | "blocked";
  evidence_grade: EvidenceGrade;
  display_label: string;
  confidence: Confidence;
  context_signals: ContextSignal[];
  provenance: Provenance;
  limitations: string[];
}

export interface AnalysisA extends AnalysisBase {
  evidence_grade: "A";
  survival_grade: "A" | "B" | "C" | "D" | "E";
  context_risk_grade: null;
  probability_lower: number;
  probability_upper: number;
  probability_unit: "PERCENT_0_100";
  horizon_months: number;
  sample_n: number;
  event_n: number;
}

export interface AnalysisB extends AnalysisBase {
  evidence_grade: "B";
  survival_grade: null;
  context_risk_grade: "LOW" | "MEDIUM" | "HIGH";
  probability_lower: null;
  probability_upper: null;
  probability_unit: null;
  horizon_months: null;
  sample_n: number;
  event_n: number | null;
}

export interface AnalysisC extends AnalysisBase {
  evidence_grade: "C";
  survival_grade: null;
  context_risk_grade: null;
  probability_lower: null;
  probability_upper: null;
  probability_unit: null;
  horizon_months: null;
  sample_n: number | null;
  event_n: null;
}

export interface AnalysisU extends AnalysisBase {
  evidence_grade: "U";
  survival_grade: null;
  context_risk_grade: null;
  probability_lower: null;
  probability_upper: null;
  probability_unit: null;
  horizon_months: null;
  sample_n: null;
  event_n: null;
  blocked_reason: string;
  required_actions: string[];
}

export type AnalysisResult = AnalysisA | AnalysisB | AnalysisC | AnalysisU;

export interface Program {
  id: string;
  category: "GOVERNMENT" | "POLICY_FUND" | "GUARANTEE" | "PRIVATE";
  title: string;
  organization: string;
  status: "ELIGIBLE_PRECHECK" | "CONDITIONAL" | "MANUAL_CHECK" | "CLOSED" | "UNKNOWN";
  application_period?: string;
  matched_conditions: string[];
  unknown_conditions: string[];
  official_url: string;
  source_as_of?: string;
  /** 임베딩에 들어간 공고 본문. 관련도 대조에만 쓰고 화면에 그대로 뿌리지 않는다. */
  match_text?: string;
  /** 원천이 준 지원지역. 주지 않으면 null 이고, 그때는 본문 대조로 떨어진다. */
  regions?: string[] | null;
}

/** KB국민은행 개인사업자대출 공시 (FSS 금융상품 한눈에). Rates are disclosure-month averages, not offers. */
export interface KbProduct {
  id: string;
  name: string;
  category: "BUSINESS_LOAN" | "CREDIT_LOAN" | "MORTGAGE_LOAN" | "RENT_LOAN" | "DEPOSIT" | "SAVING";
  category_label: string;
  rate_kind: string;
  organization: string;
  product_type?: string | null;
  rate_min: number | null;
  rate_max: number | null;
  rate_avg: number | null;
  rate_type?: string | null;
  loan_limit?: string | null;
  join_way?: string | null;
  repay_type?: string | null;
  source_as_of?: string | null;
  official_url: string;
  unknown_conditions: string[];
}

export interface CostItem {
  key: string;
  label: string;
  min_krw: number | null;
  max_krw: number | null;
  source_type: "USER" | "OFFICIAL" | "ESTIMATE" | "UNAVAILABLE";
  note?: string;
}

export interface CostPlan {
  items: CostItem[];
  total_min_krw: number;
  total_max_krw: number;
  equity_krw: number;
  gap_min_krw: number;
  gap_max_krw: number;
}

export interface DocumentRecord {
  document_id: string;
  case_id: string;
  template: string;
  status: "queued" | "processing" | "ready" | "failed";
  message: string;
  created_at?: string;
  updated_at?: string;
}

export interface IntegrationStatus {
  supabase: boolean;
  kakao_map: boolean;
  kakao_local: boolean;
  openai: boolean;
  seoul_data: boolean;
  bizinfo: boolean;
  kstartup: boolean;
  finlife: boolean;
  ipzitalk: boolean;
}

export interface FeatureFlags {
  financial_application: boolean;
  consultation_transfer: boolean;
  mydata: boolean;
}

export interface AnalysisAxis {
  enabled: boolean;
  disabled_reason: string | null;
  note: string | null;
}

/** backend/app/main.py's integration_status(): chat_daily_turns is a process-local (not
 * cross-worker/cross-restart) counter -- `note` says so plainly, surface it rather than implying
 * a durable quota. */
export interface ChatDailyTurnsLimit {
  /** false 면 한도를 세지 않는다. 그때 per_session 은 null 이며 숫자를 표시하면 안 된다. */
  enabled: boolean;
  /** null 이면 한도 없음. 음수 설정값을 그대로 내보내면 한도로 오해되므로 서버가 null 로 바꿔 보낸다. */
  per_session: number | null;
  scope: string;
  note: string;
}

export interface StatusLimits {
  chat_daily_turns: ChatDailyTurnsLimit;
}

export interface StatusResponse {
  mode: string;
  integrations: IntegrationStatus;
  feature_flags: FeatureFlags;
  axes: Record<string, AnalysisAxis>;
  limits: StatusLimits;
}

/** backend/app/chat_tools.py's `citation()` -- carried per tool_end event and deduped into the
 * `done` event's final list. */
export interface Citation {
  title: string;
  official_url: string;
  source_name: string;
  collected_at: string;
  tool: string;
}

/** The browser-only payload chat_stream.py's `_for_browser()` extracts alongside `tool_end` --
 * exactly the fields `_for_model()` withholds from the model because they're too large to re-send
 * every round (today: get_location_map_image's base64 `image_url`). Every field is optional
 * because different tools populate different ones; `image_url` is the only one lib/api.ts
 * currently recognizes and validates (see `asImageDataUri`) -- an unrecognized key or a value that
 * fails validation is dropped rather than passed through. */
export interface ChatToolDisplay {
  image_url?: string;
}

/** Mirrors chat_stream.py's `tool_start`/`tool_end` SSE payloads, merged by `call_id`.
 *
 * `tool_start` carries {call_id, tool, label} and no status -- the client synthesizes
 * `status: "running"` itself, which is why "running" is not in chat_tools.TOOL_STATUSES.
 * `tool_end` carries {call_id, tool, status, summary, citations} and no label -- callers must
 * look up the label from the matching `tool_start` entry by call_id; lib/api.ts's chatStream
 * cannot invent one that was never on the wire. `tool_end` also *optionally* carries `display`
 * (see ChatToolDisplay) -- absent entirely for the common case of a tool whose result has nothing
 * oversized to show.
 *
 * The eight non-"running" values are exactly chat_tools.TOOL_STATUSES (backend/app/chat_tools.py).
 * "not_implemented" is included for that reason even though no handler currently returns it (see
 * that file's comment: it was a Task 5-6 stub-only value) -- keeping this union in lockstep with
 * the backend's authoritative status set means a status the backend is *allowed* to emit never
 * fails to type here, even if nothing on today's code path exercises it. */
export interface ChatToolActivity {
  call_id: string;
  tool: string;
  label: string;
  status: "running" | "ok" | "empty" | "error" | "out_of_scope" | "invalid_place_ref" | "not_found" | "unknown_tool" | "not_implemented";
  summary?: string;
  display?: ChatToolDisplay;
}

/** Handlers for api.chatStream(). Read this before wiring up a message panel (Task 14):
 *
 * chat_stream.py emits exactly one `delta` event immediately before `done`, and that delta's
 * `text` is the SAME full answer as `done`'s `message` (see ChatStreamer.run(): both the
 * no-tool-calls branch and the round-limit branch send identical text through both events).
 * Calling BOTH onDelta (to append/render streaming text) AND rendering onDone's `message` will
 * show the answer twice. Pick one path: either render incrementally from onDelta and ignore
 * `result.message` in onDone (use it only to know the turn is over), or ignore onDelta entirely
 * and render `result.message` once onDone fires. Do not do both. */
export interface ChatStreamHandlers {
  onToolStart(activity: ChatToolActivity): void;
  onToolEnd(activity: ChatToolActivity): void;
  onDelta(text: string): void;
  onDone(result: { message: string; citations: Citation[]; integration_status: string }): void;
}

/** 화면이 축을 묶어 보여주는 세 갈래. **실행 단위가 아니다** — 실행 그래프의 단위는 축
 *  하나이고, 이 값은 그 축들을 화면에서 어떻게 모아 보여줄지만 정한다. 둘을 겹쳐 놓으면
 *  "같이 보여주는 것"이 "같이 실행되는 것"이 된다. */
export type DisplayGroup = "어디" | "얼마" | "언제";

/** 에이전트 선언. `GET /api/v1/agents` 가 주는 모양.
 *  판단 축은 `display_group` 을 가진 것이 전부다 — 개수를 문자열로 적지 않는다. */
export interface AgentSpec {
  key: string;
  team: "main" | "condition" | "kernel" | "finance" | "location" | "timing";
  name: string;
  source_name: string;
  produces: string;
  evidence_grade: EvidenceGrade | null;
  /** 판단 축만 갖는다. 메인(종합)과 조건(수립)은 판단 축이 아니므로 null 이다. */
  display_group: DisplayGroup | null;
}

/** 백엔드 `AgentStatus` 와 짝을 이룬다. 유니온을 열어 두는 이유는, 백엔드가 어휘를 넓혔을 때
 * 모르는 값을 실패로 접으면 판정에 성공한 축을 고장난 것처럼 보이게 만들기 때문이다. */
export type AgentRunStatus = "ok" | "integration_pending" | "withheld" | "failed" | (string & {});

/** `data` 는 그 에이전트가 실제로 산출한 값이다. 화면은 인용만 하고 다시 계산하지 않는다 —
 *  형태는 에이전트마다 다르므로 읽는 쪽이 필요한 필드만 좁혀서 꺼내 쓴다. */
export interface AgentProgress { team: string; key: string; name: string; status: AgentRunStatus; message?: string; data?: Record<string, unknown> }

/** 되묻기 항목.
 *
 *  `MISSING` 은 값이 비어 계산이 성립하지 않는 것이고, `UNMAPPED_INDUSTRY` 는 값은 있지만
 *  상권 통계의 업종 코드로 이어지지 않는 것이다 — 후자는 확인 절차가 아니라 실패 복구이며,
 *  `options` 는 **표시용** 후보일 뿐 코드가 자동으로 붙이지 않는다(유사 매칭 금지). */
export interface ConditionQuestion {
  field: string;
  label: string;
  reason: "MISSING" | "UNMAPPED_INDUSTRY";
  message: string;
  options: string[];
}

/** 발화가 이미 확정된 값과 어긋나 올라온 변경 제안. 적용되지 않은 상태로 온다 —
 *  조건 변경은 재실행을 유발하므로 사용자가 모르는 사이에 일어나면 안 된다. */
export interface ConditionProposal { field: string; current: string | number | null; proposed: string | number; span: string }

/** `orchestrator._summary` 를 그대로 미러링한다. 여력 세 줄은 금융 프로필만으로 나오므로
 *  언제나 있고, 권장 조달선 이하는 희망 월세가 있어야 나온다. */
export interface PrescribeSummary {
  equity_line_krw?: number | null;
  borrowing_headroom_krw?: number | null;
  maximum_line_krw?: number | null;
  /** 이 실행에서 값이 없어 내지 못한 조건 항목. */
  deferred?: string[];
  recommended_ceiling_krw?: number | null;
  monthly_repayment_krw?: number | null;
  target_monthly_revenue_krw?: number | null;
  target_daily_revenue_krw?: number | null;
  runway_months?: number | null;
  required_capital_krw?: number | null;
}

export interface PrescribeResult {
  fingerprint?: string;
  reused: boolean;
  halted_at: string | null;
  questions: ConditionQuestion[];
  /** 없어서 그 수치만 내지 못한 조건 항목. 되묻지 않고 진행했다는 사실을 화면이 말한다. */
  deferred: string[];
  proposals: ConditionProposal[];
  activation: { total: number; active: number; by_key: Record<string, AgentRunStatus | null> };
  summary: PrescribeSummary;
  surviving: Record<string, unknown>[];
  dropped: (Record<string, unknown> & { reason?: string })[];
}

/** `done` 은 언제나 마지막 프레임이고 `error` 는 던져진다 — chat 스트림과 같은 규칙이다. */
export interface PrescribeStreamHandlers {
  onRunStart(info: { total_agents: number; fingerprint: string }): void;
  /** 축 하나가 시작했다. 팀 경계는 더 이상 이벤트에 없다 — 화면의 묶음은
   *  `AgentSpec.display_group` 이 정하고, 그것은 표시일 뿐 실행 단위가 아니다. */
  onAxisStart(axis: { key: string; name: string }): void;
  onAgentEnd(agent: AgentProgress): void;
  onDone(result: PrescribeResult): void;
}

export type FundingBandKey = "EQUITY_ONLY" | "RECOMMENDED" | "MAXIMUM" | "OUT_OF_RANGE";

/** 평수·보증금은 필요자금(→현금소진)에만 쓰이므로 없어도 밴드 상한과 손익분기는 계산된다. */
export interface FundingBandInput {
  industry: string;
  area_pyeong: number | null;
  deposit_krw: number | null;
  monthly_rent_krw: number;
  monthly_maintenance_krw: number;
  key_money_krw: number;
  fitout_krw: number | null;
  equity_krw: number;
  existing_debt_krw: number;
  other_monthly_fixed_krw: number;
}

export interface BandLine {
  band: FundingBandKey;
  ceiling_krw: number;
  loan_krw: number;
  monthly_repayment_krw: number;
  monthly_fixed_cost_krw: number;
  target_monthly_revenue_krw: number;
  target_daily_revenue_krw: number;
  runway_months: number | null;
  stress_pass: boolean;
  repayment_burden_ratio: number;
  subsidy_uplift_krw: number;
  is_estimate: boolean;
  trade_area_count: number | null;
}

export interface BreakEven {
  monthly_fixed_cost_krw: number;
  target_monthly_revenue_krw: number;
  target_daily_revenue_krw: number;
  contribution_margin_ratio: number;
  assumptions: string[];
}

/** partial 은 밴드 상한과 손익분기는 냈으나 필요자금·현금소진을 낼 입력이 없는 상태다. */
export interface FundingBandResult {
  status: "computed" | "partial" | "integration_pending";
  required_capital_krw: number | null;
  required_capital_band: FundingBandKey | null;
  bands: BandLine[];
  break_even: BreakEven | null;
  parameter_status: "VERIFIED" | "DEMO";
  unverified_params: string[];
  missing_params: string[];
  message: string | null;
  provenance: Provenance | null;
}

/** 1단계의 완결 결과. 권장 조달선은 여기 없고, 왜 아직 없는지를 문장으로 말한다. */
export interface FundingCapacityResult {
  status: "computed" | "integration_pending";
  equity_line_krw: number;
  borrowing_headroom_krw: number;
  maximum_line_krw: number;
  parameter_status: "VERIFIED" | "DEMO";
  unverified_params: string[];
  recommended_line_pending: string;
  missing_params: string[];
  message: string | null;
  provenance: Provenance | null;
}

export type ConditionKey = "industry" | "district" | "monthly_rent_krw" | "business_stage" | "startup_type" | "priority";

/** evidence 는 사용자 원문의 부분문자열이며, 서버 검증을 통과한 값만 채워져 온다. */
export interface ConditionField { value: string | number | null; evidence: string | null }

/** 조건 제안. 케이스가 아니며 확인 화면의 승인이 있어야 조건이 된다.
 *  equity_krw·budget_krw 는 의도적으로 없다 — 1단계 금융 프로필이 소유한다. */
export interface ConditionInterpretResult {
  source: "AI" | "RULE";
  fields: Record<ConditionKey, ConditionField>;
  unresolved: string[];
  message: string;
}

/** 의미 검색 결과 한 건. backend/app/models.py의 RetrievedDocument와 필드 대 필드로 맞춘다. */
export interface RetrievedDocument {
  id: string;
  kind: "PROGRAM" | "KB_PRODUCT";
  title: string;
  organization: string;
  official_url: string;
  provider: string;
  category: string;
  excerpt: string;
  /** 결과 순서에만 관여한다. 자격 판정에 쓰지 않는다. */
  similarity: number;
  source_as_of: string | null;
  collected_at: string | null;
  application_start: string | null;
  application_end: string | null;
  /** 코드가 구조화 필드를 비교한 결과만 들어 있다. */
  matched_conditions: string[];
  unknown_conditions: string[];
  provenance: Provenance;
}

export interface RetrievalResponse {
  items: RetrievedDocument[];
  status: "success" | "integration_pending" | "unavailable";
  message: string | null;
  evidence_grade: "C";
}
