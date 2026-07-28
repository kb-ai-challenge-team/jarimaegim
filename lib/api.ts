import type { AnalysisResult, Candidate, CaseInput, CaseRecord, ChatStreamHandlers, ChatToolActivity, Citation, CostPlan, DistrictSummary, DocumentRecord, FundingBandInput, FundingBandResult, KbProduct, Program, RetrievalResponse, StatusResponse } from "./types";
import { createSseParser, type SseEvent } from "./sse";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "/api/v1";

// Explicit fields, not TS constructor-parameter-property shorthand: Node's built-in type-stripping
// (used by `node --test` against these .ts files directly, see scripts/*.test.mjs) only erases
// type syntax, it does not transform non-erasable constructs like parameter properties into real
// field assignments -- importing a class written that way throws ERR_UNSUPPORTED_TYPESCRIPT_SYNTAX
// the moment a test imports this module. Same runtime shape, just spelled so `node --test` can
// load it without a build step.
export class ApiError extends Error {
  code: string;
  status: number;
  retryable: boolean;
  constructor(code: string, message: string, status: number, retryable = false) {
    super(message);
    this.code = code;
    this.status = status;
    this.retryable = retryable;
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

// ---- chat stream: frame data off the wire is `unknown` at the type level and untrusted at the
// trust level (a malformed frame or a compromised/misbehaving upstream), so every field is
// validated here rather than cast. A missing/wrong-typed field degrades to a safe default instead
// of propagating `undefined`/garbage into a component that assumes the ChatToolActivity/Citation
// shape is real.
function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map(item => ({ title: asString(item.title), official_url: asString(item.official_url), source_name: asString(item.source_name), collected_at: asString(item.collected_at), tool: asString(item.tool) }));
}

const TOOL_ACTIVITY_STATUSES = new Set<ChatToolActivity["status"]>(["ok", "empty", "error", "out_of_scope", "invalid_place_ref", "not_found", "unknown_tool", "not_implemented"]);

// An unrecognized status (a future backend value this client doesn't know yet, or a hostile frame)
// folds to "error" rather than being cast through -- "error" is the one status that already tells
// a caller not to trust the result, which is the safe default for "we don't know what this means."
function toToolStatus(value: unknown): ChatToolActivity["status"] {
  return typeof value === "string" && TOOL_ACTIVITY_STATUSES.has(value as ChatToolActivity["status"]) ? (value as ChatToolActivity["status"]) : "error";
}

/** Pure, network-free interpretation of one already-parsed SSE frame. Exported so
 * scripts/chat-stream-dispatch.test.mjs can exercise every branch -- including malformed frames --
 * without a real fetch/ReadableStream. Returns true once the turn is over (a `done` frame reached);
 * `chatStream` uses that to stop reading. An `error` frame is terminal by throwing ApiError
 * directly, matching chat_stream.py: both `done` and `error` are always the last event of a turn,
 * so abandoning any further frames already parsed from the same chunk (see the loop in
 * `chatStream`) never drops something the backend would still send. */
export function applyChatStreamFrame(frame: SseEvent, handlers: ChatStreamHandlers): boolean {
  if (frame.event === "tool_start") {
    handlers.onToolStart({ call_id: asString(frame.data.call_id), tool: asString(frame.data.tool), label: asString(frame.data.label, "공식 원천 조회 중"), status: "running" });
    return false;
  }
  if (frame.event === "tool_end") {
    // No `label` on the wire for tool_end (see ChatToolActivity's doc comment) -- callers merge
    // this by call_id with the label captured from that call's earlier tool_start.
    const activity: ChatToolActivity = { call_id: asString(frame.data.call_id), tool: asString(frame.data.tool), label: "", status: toToolStatus(frame.data.status) };
    if (typeof frame.data.summary === "string") activity.summary = frame.data.summary;
    handlers.onToolEnd(activity);
    return false;
  }
  if (frame.event === "delta") {
    handlers.onDelta(asString(frame.data.text));
    return false;
  }
  if (frame.event === "done") {
    handlers.onDone({ message: asString(frame.data.message, "응답을 확인하지 못했습니다."), citations: asCitations(frame.data.citations), integration_status: asString(frame.data.integration_status, "unknown") });
    return true;
  }
  if (frame.event === "error") {
    throw new ApiError(asString(frame.data.code, "UPSTREAM_UNAVAILABLE"), asString(frame.data.message, "AI 응답을 받지 못했습니다."), 502, Boolean(frame.data.retryable));
  }
  return false; // unknown event name: forward-compatible no-op, not a crash
}

async function chatStream(caseId: string, content: string, handlers: ChatStreamHandlers, signal?: AbortSignal): Promise<void> {
  const response = await fetch(`${API_BASE}/cases/${caseId}/messages/stream`, {
    method: "POST", credentials: "include", signal,
    headers: { "Content-Type": "application/json", "Accept": "text/event-stream", "Idempotency-Key": requestId() },
    // base_case_version is hardcoded like the non-streaming `chat` below: models.py only checks
    // `gt=0` on it, and neither create_message nor create_message_stream in main.py reads
    // payload.base_case_version at all today, so this is a currently-inert placeholder, not a
    // functioning staleness check -- matching `chat`'s existing value keeps the two endpoints
    // consistent rather than inventing a different placeholder for no reason. If the backend ever
    // starts enforcing this field, both call sites need the real case version plumbed in, not just
    // this one.
    body: JSON.stringify({ client_message_id: requestId(), content, base_case_version: 1, confirmed_case_patch: [], locale: "ko-KR" }),
  });
  if (!response.ok) throw await responseError(response);
  if (!response.body) throw new ApiError("UPSTREAM_UNAVAILABLE", "AI 응답 스트림을 열지 못했습니다.", 502, true);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = createSseParser();
  let settled = false;
  try {
    while (!settled) {
      const { done, value } = await reader.read();
      if (done) break;
      // { stream: true } is required, not cosmetic: a chunk boundary can legitimately land inside
      // a multi-byte Korean UTF-8 sequence, and decoding each chunk independently would hand the
      // parser a stray U+FFFD in place of the split character (see lib/sse.ts's header comment).
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
        if (applyChatStreamFrame(frame, handlers)) { settled = true; break; }
      }
    }
    if (!settled) {
      // Defensive no-op, not a recovery path. The loop reached here because the connection closed
      // without a `done`/`error` event. `{stream: true}` already reassembles multi-byte characters
      // split across ordinary chunk boundaries, so the only way bytes remain buffered here is a
      // connection severed mid-character -- which necessarily also severed the frame's trailing
      // "\n\n". Flushing replaces the dangling bytes with U+FFFD rather than recovering them, and
      // without a terminator the parser still cannot complete a frame. What actually reports this
      // case is the `!settled` throw below. Kept so a stray complete frame is not silently dropped.
      const trailing = decoder.decode();
      if (trailing) {
        for (const frame of parser.push(trailing)) {
          if (applyChatStreamFrame(frame, handlers)) { settled = true; break; }
        }
      }
    }
  } finally {
    // Release the connection whether we finished cleanly, threw (an `error` SSE event, or a
    // network error), or were cancelled via `signal`: cancel() must run before releaseLock() --
    // once released, the reader is no longer attached to the stream and cancel() would throw.
    // Calling cancel() when the stream already closed normally is a documented no-op, so this is
    // safe on every exit path, not just the early ones.
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
  // A stream that ends without ever producing `done` or `error` is a dropped connection, not a
  // silent success -- product rule 1 (never fabricate data) means this must surface as an error
  // rather than letting the caller believe the turn simply produced no answer.
  if (!settled) throw new ApiError("UPSTREAM_UNAVAILABLE", "AI 응답이 도중에 끊겼습니다. 다시 시도해 주세요.", 502, true);
}

export const api = {
  status: () => request<StatusResponse>("/status"),
  createAnonymousSession: () => request<{ session_id: string; expires_at: string }>("/sessions/anonymous", { method: "POST", body: JSON.stringify({ retention_notice_accepted: true }) }),
  createCase: (inputs: CaseInput, title: string) => request<CaseRecord>("/cases", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ title, inputs }) }),
  getCase: (id: string) => request<CaseRecord>(`/cases/${id}`),
  updateCase: (id: string, version: number, inputs: Partial<CaseInput>) => request<CaseRecord>(`/cases/${id}`, { method: "PATCH", headers: { "If-Match": String(version), "Idempotency-Key": requestId() }, body: JSON.stringify({ inputs }) }),
  searchLocations: (caseId: string, inputs: CaseInput) => request<{ candidates: Candidate[]; status: "success" | "empty" | "integration_pending"; message?: string }>("/locations/search", { method: "POST", body: JSON.stringify({ case_id: caseId, industry: inputs.industry, district: inputs.district, limit: 4 }) }),
  // Landing map. Public on purpose — browsing must not mint an anonymous session cookie.
  getListingSummary: () => request<{ districts: DistrictSummary[] }>("/listings/summary"),
  getListings: (district: string, limit = 15) => request<{ candidates: Candidate[]; status: "success" | "empty"; message?: string }>(`/listings?district=${encodeURIComponent(district)}&limit=${limit}`),
  createAnalysis: (caseId: string, candidateId: string) => request<AnalysisResult>("/analyses", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, candidate_id: candidateId, requested_as_of: null }) }),
  getPrograms: (caseId: string) => request<{ items: Program[]; status: string; message?: string }>(`/programs?case_id=${encodeURIComponent(caseId)}`),
  getProducts: (caseId: string) => request<{ items: Program[]; status: string }>(`/products?case_id=${encodeURIComponent(caseId)}`),
  getProgramCatalog: () => request<{ items: Program[]; status: string; message?: string }>("/programs/catalog"),
  getKbProducts: () => request<{ items: KbProduct[]; status: string; message?: string }>("/products/kb"),
  // 질의 1회당 임베딩 호출 1회다. 호출부는 입력마다가 아니라 제출에서만 부른다.
  searchPrograms: (query: string, district?: string, limit = 8) => request<RetrievalResponse>(`/knowledge/search?q=${encodeURIComponent(query)}&kind=PROGRAM${district ? `&district=${encodeURIComponent(district)}` : ""}&limit=${limit}`),
  createCostPlan: (caseId: string, items: { key: string; label: string; min_krw: number | null; max_krw: number | null; source_type: string }[]) => request<CostPlan>("/cost-plans", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, items }) }),
  fundingBands: (caseId: string, inputs: FundingBandInput) => request<FundingBandResult>("/funding-bands", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, ...inputs }) }),
  // Non-streaming, no tools. `AIService.explain` always returns `citations: []` -- the Citation[]
  // type is what the envelope permits, not what this endpoint delivers. Use chatStream for sourced
  // answers.
  chat: (caseId: string, content: string) => request<{ message: string; citations: Citation[]; integration_status: string }>(`/cases/${caseId}/messages`, { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ client_message_id: requestId(), content, base_case_version: 1, confirmed_case_patch: [], locale: "ko-KR" }) }),
  chatStream: (caseId: string, content: string, handlers: ChatStreamHandlers, signal?: AbortSignal) => chatStream(caseId, content, handlers, signal),
  createDocument: (caseId: string, template: string) => request<DocumentRecord>("/documents", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, template, confirmed: true }) }),
  getDocument: (documentId: string) => request<DocumentRecord>(`/documents/${documentId}`),
  downloadDocument: async (documentId: string) => { const response = await fetch(`${API_BASE}/documents/${documentId}/download`, { credentials: "include", headers: requestHeaders() }); if (!response.ok) throw await responseError(response); return response.blob(); },
  createPrivacyRequest: (requestType: string) => request<{ request_id: string; status: string }>("/privacy/requests", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ request_type: requestType, verification_method: "ANON_COOKIE" }) })
};
