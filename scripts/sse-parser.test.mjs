import test from "node:test";
import assert from "node:assert/strict";
import { createSseParser } from "../lib/sse.ts";

test("한 프레임을 이벤트로 만든다", () => {
  const parser = createSseParser();
  const events = parser.push('event: delta\ndata: {"text":"안녕"}\n\n');
  assert.deepEqual(events, [{ event: "delta", data: { text: "안녕" } }]);
});

test("여러 프레임을 한 번에 처리한다", () => {
  const parser = createSseParser();
  const events = parser.push('event: turn_start\ndata: {}\n\nevent: done\ndata: {"message":"끝"}\n\n');
  assert.deepEqual(events.map(item => item.event), ["turn_start", "done"]);
});

test("경계에서 잘린 프레임을 이어붙인다", () => {
  const parser = createSseParser();
  assert.deepEqual(parser.push('event: delta\ndata: {"te'), []);
  assert.deepEqual(parser.push('xt":"안녕"}\n\n'), [{ event: "delta", data: { text: "안녕" } }]);
});

// A parser stubbed to always return [] would trivially satisfy "ignore a lone ping", so this
// also pushes a real frame afterward and checks it still comes through -- that second assertion
// is what actually fails if comment-skipping (or the parser generally) were gutted.
test("주석 프레임을 무시한다", () => {
  const parser = createSseParser();
  assert.deepEqual(parser.push(": ping\n\n"), []);
  assert.deepEqual(parser.push('event: done\ndata: {"message":"끝"}\n\n'), [{ event: "done", data: { message: "끝" } }]);
});

test("주석과 이벤트가 섞여도 이벤트만 낸다", () => {
  const parser = createSseParser();
  const events = parser.push(': ping\n\nevent: done\ndata: {"message":"끝"}\n\n');
  assert.deepEqual(events, [{ event: "done", data: { message: "끝" } }]);
});

test("깨진 JSON은 이벤트를 버리고 나머지를 계속 처리한다", () => {
  const parser = createSseParser();
  const events = parser.push('event: delta\ndata: {broken\n\nevent: done\ndata: {"message":"끝"}\n\n');
  assert.deepEqual(events, [{ event: "done", data: { message: "끝" } }]);
});

// Same rationale as the comment test above: an always-[] stub would also pass a bare
// "expect []" assertion, so this confirms the parser keeps working on a later, well-formed frame.
test("event 줄이 없으면 버린다", () => {
  const parser = createSseParser();
  assert.deepEqual(parser.push('data: {"text":"고아"}\n\n'), []);
  assert.deepEqual(parser.push('event: done\ndata: {"message":"끝"}\n\n'), [{ event: "done", data: { message: "끝" } }]);
});

test("CRLF 줄바꿈을 처리한다", () => {
  const parser = createSseParser();
  assert.deepEqual(parser.push('event: done\r\ndata: {"message":"끝"}\r\n\r\n'),
    [{ event: "done", data: { message: "끝" } }]);
});

// Pinned to the real backend format: backend/app/main.py's sse_frame() emits
// `event: {name}\ndata: {json.dumps(..., ensure_ascii=False)}\n\n`, and heartbeat_frames()
// interleaves bare `: ping\n\n` comment lines between real frames during a long tool-calling
// turn. This exercises Korean payload text and multiple full frames (including a ping in the
// middle) delivered in a single chunk, the shape a real fetch stream will actually produce.
test("백엔드 sse_frame/heartbeat_frames 출력 형태를 그대로 처리한다", () => {
  const parser = createSseParser();
  const chunk =
    'event: tool_start\ndata: {"call_id":"c1","tool":"lookup_seoul_presale","label":"청약홈 분양공고 조회 중"}\n\n' +
    ': ping\n\n' +
    'event: tool_end\ndata: {"call_id":"c1","ok":true}\n\n' +
    'event: done\ndata: {"message":"답변이 준비됐습니다."}\n\n';
  const events = parser.push(chunk);
  assert.deepEqual(events, [
    { event: "tool_start", data: { call_id: "c1", tool: "lookup_seoul_presale", label: "청약홈 분양공고 조회 중" } },
    { event: "tool_end", data: { call_id: "c1", ok: true } },
    { event: "done", data: { message: "답변이 준비됐습니다." } },
  ]);
});
