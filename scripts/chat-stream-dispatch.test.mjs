import test from "node:test";
import assert from "node:assert/strict";
import { applyChatStreamFrame, ApiError } from "../lib/api.ts";

// Minimal ChatStreamHandlers double: records every call it receives instead of asserting inline,
// so each test can pick which calls matter to it.
function recorder() {
  const calls = { toolStart: [], toolEnd: [], delta: [], done: [] };
  return {
    calls,
    onToolStart: activity => calls.toolStart.push(activity),
    onToolEnd: activity => calls.toolEnd.push(activity),
    onDelta: text => calls.delta.push(text),
    onDone: result => calls.done.push(result),
  };
}

test("tool_start always reports status running, even if the frame carries its own status field", () => {
  const handlers = recorder();
  // A well-behaved backend never sends `status` on tool_start (see chat_stream.py's _event call),
  // but this frame includes one anyway to prove the client ignores it rather than trusting the
  // wire -- "running" is a client-side-only state chat_tools.TOOL_STATUSES doesn't even define.
  const settled = applyChatStreamFrame({ event: "tool_start", data: { call_id: "c1", tool: "resolve_seoul_place", label: "공식 주소와 좌표 확인 중", status: "ok" } }, handlers);
  assert.equal(settled, false);
  assert.deepEqual(handlers.calls.toolStart, [{ call_id: "c1", tool: "resolve_seoul_place", label: "공식 주소와 좌표 확인 중", status: "running" }]);
});

test("tool_start with a missing label falls back rather than surfacing undefined", () => {
  const handlers = recorder();
  applyChatStreamFrame({ event: "tool_start", data: { call_id: "c1", tool: "resolve_seoul_place" } }, handlers);
  assert.equal(handlers.calls.toolStart[0].label, "공식 원천 조회 중");
});

test("tool_end passes through a real TOOL_STATUSES value and an optional summary", () => {
  const handlers = recorder();
  applyChatStreamFrame({ event: "tool_end", data: { call_id: "c1", tool: "scan_nearby_facilities", status: "empty", summary: "0건" } }, handlers);
  assert.deepEqual(handlers.calls.toolEnd, [{ call_id: "c1", tool: "scan_nearby_facilities", label: "", status: "empty", summary: "0건" }]);
});

test("tool_end omits summary entirely when the frame has none, rather than setting it to undefined", () => {
  const handlers = recorder();
  applyChatStreamFrame({ event: "tool_end", data: { call_id: "c1", tool: "resolve_seoul_place", status: "ok" } }, handlers);
  assert.equal("summary" in handlers.calls.toolEnd[0], false);
});

// This is the case a blind `as never` cast cannot survive: a status this client's union doesn't
// recognize (a typo, a future backend value, or a hostile frame) must degrade to "error" instead
// of being asserted through as if it were a valid ChatToolActivity["status"]. Deleting
// `toToolStatus`'s validation and reverting to a bare cast would make this assertion fail (the
// unrecognized string would flow through unchanged instead of becoming "error").
test("tool_end with an unrecognized status folds to error instead of passing the raw value through", () => {
  const handlers = recorder();
  applyChatStreamFrame({ event: "tool_end", data: { call_id: "c1", tool: "x", status: "totally_made_up" } }, handlers);
  assert.equal(handlers.calls.toolEnd[0].status, "error");
});

test("tool_end with a missing status also folds to error", () => {
  const handlers = recorder();
  applyChatStreamFrame({ event: "tool_end", data: { call_id: "c1", tool: "x" } }, handlers);
  assert.equal(handlers.calls.toolEnd[0].status, "error");
});

test("delta forwards the text field as-is", () => {
  const handlers = recorder();
  const settled = applyChatStreamFrame({ event: "delta", data: { text: "안녕하세요" } }, handlers);
  assert.equal(settled, false);
  assert.deepEqual(handlers.calls.delta, ["안녕하세요"]);
});

test("delta with a non-string text falls back to an empty string rather than throwing", () => {
  const handlers = recorder();
  applyChatStreamFrame({ event: "delta", data: { text: 42 } }, handlers);
  assert.deepEqual(handlers.calls.delta, [""]);
});

test("done reports settled=true and sanitizes citations", () => {
  const handlers = recorder();
  const settled = applyChatStreamFrame({
    event: "done",
    data: {
      message: "답변입니다",
      integration_status: "connected",
      citations: [
        { title: "국토교통부 실거래가", official_url: "https://rt.molit.go.kr/", source_name: "국토교통부 실거래가", collected_at: "2026-07-27T00:00:00Z", tool: "lookup_complex_trades" },
        "not-an-object", // malformed entry: must be dropped, not crash the whole array
      ],
    },
  }, handlers);
  assert.equal(settled, true);
  assert.equal(handlers.calls.done.length, 1);
  assert.equal(handlers.calls.done[0].message, "답변입니다");
  assert.equal(handlers.calls.done[0].citations.length, 1);
  assert.equal(handlers.calls.done[0].citations[0].source_name, "국토교통부 실거래가");
});

test("done with a non-array citations field yields an empty list instead of throwing", () => {
  const handlers = recorder();
  applyChatStreamFrame({ event: "done", data: { message: "끝", citations: "oops", integration_status: "connected" } }, handlers);
  assert.deepEqual(handlers.calls.done[0].citations, []);
});

// The one path that must become an ApiError rather than a silently-ignored frame: a dropped
// stream must surface as an error (product rule 1), never as a quiet non-event.
test("error frame throws an ApiError built from its code/message/retryable fields", () => {
  const handlers = recorder();
  assert.throws(
    () => applyChatStreamFrame({ event: "error", data: { code: "RATE_LIMITED", message: "오늘 대화 횟수를 모두 사용했습니다.", retryable: false } }, handlers),
    error => error instanceof ApiError && error.code === "RATE_LIMITED" && error.message === "오늘 대화 횟수를 모두 사용했습니다." && error.retryable === false,
  );
});

test("error frame with no fields at all still throws a well-formed ApiError, never a silent pass-through", () => {
  const handlers = recorder();
  assert.throws(
    () => applyChatStreamFrame({ event: "error", data: {} }, handlers),
    error => error instanceof ApiError && error.code === "UPSTREAM_UNAVAILABLE" && typeof error.message === "string" && error.message.length > 0,
  );
});

test("an unknown event name is ignored rather than crashing or calling any handler", () => {
  const handlers = recorder();
  const settled = applyChatStreamFrame({ event: "future_event_type", data: { anything: true } }, handlers);
  assert.equal(settled, false);
  assert.deepEqual(handlers.calls, { toolStart: [], toolEnd: [], delta: [], done: [] });
});
