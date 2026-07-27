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

export interface StatusResponse {
  mode: string;
  integrations: IntegrationStatus;
  feature_flags: FeatureFlags;
  axes: Record<string, AnalysisAxis>;
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
