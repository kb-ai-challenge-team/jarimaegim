import { z } from "zod";

export const caseInputSchema = z.object({
  industry: z.string().trim().min(1, "업종을 입력해 주세요."),
  district: z.string().trim().min(1, "서울 지역을 선택해 주세요."),
  budgetKrw: z.number().int().nonnegative("예산은 0원 이상이어야 합니다."),
  equityKrw: z.number().int().nonnegative("자기자본은 0원 이상이어야 합니다."),
  businessStage: z.enum(["PREPARING", "RELOCATING", "SECOND_STORE"]),
  startupType: z.enum(["INDEPENDENT", "FRANCHISE", "UNDECIDED"]),
  priority: z.enum(["STABILITY", "DEMAND", "COST", "GROWTH"]).default("STABILITY")
});

export type CaseInput = z.infer<typeof caseInputSchema>;

export type Provenance = {
  source?: string;
  source_as_of?: string;
  published_at?: string;
  collected_at?: string;
  verified_at?: string;
  industry_scope?: string;
  spatial_unit?: string;
  model_version?: string;
  rule_version?: string;
  source_year?: string | number;
  official_url?: string;
  official_urls?: string[];
  sample_n?: number | null;
  confidence?: "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT" | string;
  limitations?: string[];
  stale?: boolean;
};

export type Candidate = {
  id: string;
  name: string;
  district?: string;
  address?: string;
  latitude?: number;
  longitude?: number;
  display_label?: string;
  evidence_grade?: EvidenceGrade;
  confidence?: string;
  highlights?: string[];
  cautions?: string[];
  context_signals?: Array<{ name?: string; label?: string; direction?: string; description?: string }>;
  provenance?: Provenance;
};

const provenanceSchema = z.object({
  source: z.string().optional(), source_as_of: z.string().optional(), published_at: z.string().optional(),
  collected_at: z.string().optional(), verified_at: z.string().optional(), industry_scope: z.string().optional(),
  spatial_unit: z.string().optional(), model_version: z.string().optional(), rule_version: z.string().optional(),
  source_year: z.union([z.string(), z.number()]).optional(), official_url: z.string().optional(), official_urls: z.array(z.string()).optional(),
  sample_n: z.number().nullable().optional(),
  confidence: z.string().optional(), limitations: z.array(z.string()).optional(), stale: z.boolean().optional()
}).passthrough();

const baseAnalysis = z.object({
  analysis_id: z.string(),
  status: z.string(),
  confidence: z.string(),
  provenance: provenanceSchema,
  limitations: z.array(z.string()).default([]),
  axes: z.array(z.object({ name: z.string(), direction: z.string().optional(), description: z.string(), provenance: provenanceSchema.optional() })).optional()
});

const individualAnalysis = baseAnalysis.extend({
  evidence_grade: z.literal("A"), survival_grade: z.enum(["A", "B", "C", "D", "E"]),
  context_risk_grade: z.null(), probability_lower: z.number().min(0).max(100), probability_upper: z.number().min(0).max(100),
  probability_unit: z.literal("PERCENT_0_100"), horizon_months: z.number().int().positive(), sample_n: z.number().int().positive(),
  event_n: z.number().int().nonnegative(), context_signals: z.array(z.unknown()).nullable().optional(), blocked_reason: z.null().optional()
}).refine((value) => value.probability_lower <= value.probability_upper);

const aggregateAnalysis = baseAnalysis.extend({
  evidence_grade: z.literal("B"), survival_grade: z.null(), context_risk_grade: z.enum(["LOW", "MEDIUM", "HIGH"]),
  probability_lower: z.null(), probability_upper: z.null(), probability_unit: z.null(), horizon_months: z.null(),
  sample_n: z.number().int().positive(), event_n: z.number().int().nonnegative().nullable().optional(),
  context_signals: z.array(z.object({ name: z.string(), score_band: z.string().optional(), direction: z.string().optional(), description: z.string().optional() })), blocked_reason: z.null().optional()
});

const contextAnalysis = baseAnalysis.extend({
  evidence_grade: z.literal("C"), survival_grade: z.null(), context_risk_grade: z.null(), probability_lower: z.null(),
  probability_upper: z.null(), probability_unit: z.null(), horizon_months: z.null(), sample_n: z.number().int().positive().nullable().optional(),
  event_n: z.null(), context_signals: z.array(z.object({ name: z.string(), score_band: z.string().optional(), direction: z.string().optional(), description: z.string().optional() })), blocked_reason: z.null().optional()
});

const blockedAnalysis = baseAnalysis.extend({
  evidence_grade: z.literal("U"), survival_grade: z.null(), context_risk_grade: z.null(), probability_lower: z.null(),
  probability_upper: z.null(), probability_unit: z.null(), horizon_months: z.null(), sample_n: z.null(), event_n: z.null(),
  context_signals: z.null().optional(), blocked_reason: z.string(), required_actions: z.array(z.string()).min(1)
});

export const analysisSchema = z.discriminatedUnion("evidence_grade", [individualAnalysis, aggregateAnalysis, contextAnalysis, blockedAnalysis]);
export type AnalysisResult = z.infer<typeof analysisSchema>;
export type EvidenceGrade = AnalysisResult["evidence_grade"];

export const evidenceTitle: Record<EvidenceGrade, string> = {
  A: "개별 이력 기반 생존 진단", B: "상권 위험 진단", C: "입지 환경 신호", U: "현재 조건으로 분석 불가"
};

export const districtCodes = {
  "종로구":"11110", "중구":"11140", "용산구":"11170", "성동구":"11200", "광진구":"11215",
  "동대문구":"11230", "중랑구":"11260", "성북구":"11290", "강북구":"11305", "도봉구":"11320",
  "노원구":"11350", "은평구":"11380", "서대문구":"11410", "마포구":"11440", "양천구":"11470",
  "강서구":"11500", "구로구":"11530", "금천구":"11545", "영등포구":"11560", "동작구":"11590",
  "관악구":"11620", "서초구":"11650", "강남구":"11680", "송파구":"11710", "강동구":"11740"
} as const;
export const districtNames = Object.keys(districtCodes) as Array<keyof typeof districtCodes>;
export const districtNameByCode = Object.fromEntries(Object.entries(districtCodes).map(([name, code]) => [code, name])) as Record<string, string>;

export const stageLabels: Record<CaseInput["businessStage"], string> = { PREPARING: "예비 창업", RELOCATING: "운영 중 이전", SECOND_STORE: "2호점 준비" };
export const startupLabels: Record<CaseInput["startupType"], string> = { INDEPENDENT: "개인", FRANCHISE: "프랜차이즈", UNDECIDED: "미정" };
export const priorityLabels: Record<CaseInput["priority"], string> = { STABILITY: "안정성", DEMAND: "수요", COST: "비용", GROWTH: "성장" };

export function formatKrw(value: number) { return new Intl.NumberFormat("ko-KR", { style: "currency", currency: "KRW", maximumFractionDigits: 0 }).format(value); }
export function confidenceLabel(value?: string) { return ({ HIGH: "높음", MEDIUM: "보통", LOW: "낮음", INSUFFICIENT: "판단 자료 부족" } as Record<string,string>)[value ?? ""] ?? "확인 필요"; }
