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

export interface ListingTerms {
  listing_kind: "DEMO_SYNTHETIC";
  deposit_krw: number;
  monthly_rent_krw: number;
  maintenance_fee_krw?: number | null;
  area_m2: number;
  floor: number;
}

/** One landing-map pin per covered district, shown before any condition is entered. */
export interface DistrictSummary {
  district: string;
  count: number;
  median_monthly_rent_krw: number;
  latitude: number;
  longitude: number;
}

export interface Candidate {
  id: string;
  name: string;
  address: string;
  road_address?: string;
  latitude: number;
  longitude: number;
  distance_m?: number;
  evidence_grade: EvidenceGrade;
  display_label: string;
  context_signals: ContextSignal[];
  provenance: Provenance;
  listing?: ListingTerms | null;
}

export interface ContextSignal {
  name: "demand" | "competition" | "cost" | "access" | "continuity" | string;
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
  per_session: number;
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

/** Mirrors chat_stream.py's `tool_start`/`tool_end` SSE payloads, merged by `call_id`.
 *
 * `tool_start` carries {call_id, tool, label} and no status -- the client synthesizes
 * `status: "running"` itself, which is why "running" is not in chat_tools.TOOL_STATUSES.
 * `tool_end` carries {call_id, tool, status, summary, citations} and no label -- callers must
 * look up the label from the matching `tool_start` entry by call_id; lib/api.ts's chatStream
 * cannot invent one that was never on the wire.
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

export type FundingBandKey = "EQUITY_ONLY" | "RECOMMENDED" | "MAXIMUM" | "OUT_OF_RANGE";

export interface FundingBandInput {
  industry: string;
  area_pyeong: number;
  deposit_krw: number;
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

export interface FundingBandResult {
  status: "computed" | "integration_pending";
  required_capital_krw: number | null;
  required_capital_band: FundingBandKey | null;
  bands: BandLine[];
  break_even: BreakEven | null;
  missing_params: string[];
  message: string | null;
  provenance: Provenance | null;
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
