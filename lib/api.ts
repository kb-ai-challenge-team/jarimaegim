import type { AnalysisResult, Candidate, CaseInput, CaseRecord, CostPlan, DocumentRecord, Program, StatusResponse } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number, public retryable = false) {
    super(message);
    this.name = "ApiError";
  }
}

function requestId() {
  if (typeof globalThis.crypto?.randomUUID === "function") return globalThis.crypto.randomUUID();
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40; bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

function requestHeaders(init?: RequestInit) {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  return headers;
}

async function responseError(response: Response) {
  const body = await response.json().catch(() => null);
  const error = body?.error;
  return new ApiError(error?.code || "UPSTREAM_UNAVAILABLE", error?.message || "요청을 처리하지 못했습니다.", response.status, Boolean(error?.retryable));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include", ...init, headers: requestHeaders(init) });
  if (!response.ok) throw await responseError(response);
  return await response.json() as T;
}

export const api = {
  status: () => request<StatusResponse>("/status"),
  createAnonymousSession: () => request<{ session_id: string; expires_at: string }>("/sessions/anonymous", { method: "POST", body: JSON.stringify({ retention_notice_accepted: true }) }),
  createCase: (inputs: CaseInput, title: string) => request<CaseRecord>("/cases", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ title, inputs }) }),
  getCase: (id: string) => request<CaseRecord>(`/cases/${id}`),
  updateCase: (id: string, version: number, inputs: Partial<CaseInput>) => request<CaseRecord>(`/cases/${id}`, { method: "PATCH", headers: { "If-Match": String(version), "Idempotency-Key": requestId() }, body: JSON.stringify({ inputs }) }),
  searchLocations: (caseId: string, inputs: CaseInput) => request<{ candidates: Candidate[]; status: "success" | "empty" | "integration_pending"; message?: string }>("/locations/search", { method: "POST", body: JSON.stringify({ case_id: caseId, industry: inputs.industry, district: inputs.district, limit: 12 }) }),
  createAnalysis: (caseId: string, candidateId: string) => request<AnalysisResult>("/analyses", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, candidate_id: candidateId, requested_as_of: null }) }),
  getPrograms: (caseId: string) => request<{ items: Program[]; status: string; message?: string }>(`/programs?case_id=${encodeURIComponent(caseId)}`),
  getProducts: (caseId: string) => request<{ items: Program[]; status: string }>(`/products?case_id=${encodeURIComponent(caseId)}`),
  createCostPlan: (caseId: string, items: { key: string; label: string; min_krw: number | null; max_krw: number | null; source_type: string }[]) => request<CostPlan>("/cost-plans", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, items }) }),
  chat: (caseId: string, content: string) => request<{ message: string; citations: { title: string; official_url: string }[]; integration_status: string }>(`/cases/${caseId}/messages`, { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ client_message_id: requestId(), content, base_case_version: 1, confirmed_case_patch: [], locale: "ko-KR" }) }),
  createDocument: (caseId: string, template: string) => request<DocumentRecord>("/documents", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, template, confirmed: true }) }),
  getDocument: (documentId: string) => request<DocumentRecord>(`/documents/${documentId}`),
  downloadDocument: async (documentId: string) => { const response = await fetch(`${API_BASE}/documents/${documentId}/download`, { credentials: "include", headers: requestHeaders() }); if (!response.ok) throw await responseError(response); return response.blob(); },
  createPrivacyRequest: (requestType: string) => request<{ request_id: string; status: string }>("/privacy/requests", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ request_type: requestType, verification_method: "ANON_COOKIE" }) })
};
