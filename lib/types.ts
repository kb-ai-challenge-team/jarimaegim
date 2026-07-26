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

export interface StatusResponse {
  mode: string;
  integrations: IntegrationStatus;
  feature_flags: FeatureFlags;
}
