// Pure Server-Sent-Events frame parser for the browser chat stream client.
//
// EventSource can't be used against POST /api/v1/cases/{id}/messages/stream (no POST body, no
// custom headers), so the caller reads `response.body.getReader()` and feeds decoded chunks in
// here instead. This module has no fetch/DOM/network of its own -- Task 13's chatStream() owns
// the transport, this only turns decoded text into events.
//
// Multi-byte UTF-8 split across chunk boundaries is the CALLER's problem, not this parser's: the
// payload is Korean text serialized with `ensure_ascii=False` (see backend/app/main.py's
// sse_frame()), so a chunk boundary can legitimately land in the middle of a multi-byte
// character. This parser only ever receives already-decoded `string`s -- it has no access to the
// raw bytes needed to fix that. The caller MUST decode with
// `decoder.decode(value, { stream: true })` (a `TextDecoder` built once per response and reused
// across chunks); passing per-chunk decode with the default (non-streaming) options will
// occasionally hand this parser a stray U+FFFD replacement character instead.
//
// This parser is intentionally NOT a general SSE-spec implementation -- it matches exactly what
// backend/app/main.py's sse_frame() and heartbeat_frames() emit, and no more:
//   - `sse_frame()` always writes "event: {name}\n" with exactly one space after the colon, never
//     the spec-legal "event:{name}" (no space) or "event:  {name}" (n spaces). We match the one
//     format our own server produces rather than hardening for spec-legal variants nothing here
//     will ever send.
//   - `sse_frame()` always writes a single "data: {json}\n" line per frame, and json.dumps with
//     ensure_ascii=False never emits a raw newline inside a JSON string, so a frame's payload is
//     guaranteed single-line. The SSE spec's rule for joining multiple `data:` lines with "\n" is
//     therefore not implemented; if the server ever changed to emit multi-line data, this would
//     silently concatenate the lines with no separator and corrupt the payload. Acceptable only
///    because that never happens today.
// If this module is ever pointed at a third-party SSE source, both of the above need revisiting.
//
// `buffer` growing without bound if a stream never produces a "\n\n" terminator is not guarded
// here: the only source is our own backend, which always terminates every frame (including
// heartbeats) with a blank line, so an unterminated stream would mean the backend itself is
// broken -- not something this parser can recover from by capping a buffer.
//
// A frame with an `event:` line but no `data:` line parses to `{}` rather than being dropped.
// sse_frame() always writes both, so this never fires today; permissive was chosen over strict
// because an empty payload is a plausible future frame shape and dropping it would lose the event.
//
// One real hazard, currently unreachable: a ": ping" arriving BETWEEN two chunks of a single
// half-written frame would contribute its own "\n\n", creating a false frame boundary that splits
// the real frame in two -- both halves then fail to parse and the payload is silently lost. That
// cannot happen against this backend because heartbeat_frames() pumps whole, already-terminated
// sse_frame() strings and only emits a ping when the queue times out waiting for the NEXT item,
// never mid-write of the current one; ASGI writes are sequential per yield, so a ping's bytes can
// never interleave with an item already being written. Revisit if that yield discipline changes.

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

export interface SseParser {
  /** Feed one decoded chunk; returns zero or more complete events found in it (plus anything carried over from a prior partial frame). */
  push(chunk: string): SseEvent[];
}

export function createSseParser(): SseParser {
  let buffer = "";
  return {
    push(chunk: string): SseEvent[] {
      // Normalize over the whole buffer (not just the new chunk) so a CRLF split across two
      // pushes -- chunk 1 ending in a bare "\r", chunk 2 starting with "\n" -- still collapses.
      buffer = (buffer + chunk).replace(/\r\n/g, "\n");
      const events: SseEvent[] = [];
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseFrame(frame);
        if (parsed) events.push(parsed);
        boundary = buffer.indexOf("\n\n");
      }
      return events;
    },
  };
}

function parseFrame(frame: string): SseEvent | null {
  let event = "";
  let payload = "";
  for (const line of frame.split("\n")) {
    // Belt-and-braces only: ":"-prefixed comment lines are prefix-disjoint from "event: " and
    // "data: ", so they'd fall through both branches below and be ignored anyway. No input can
    // distinguish this guard's presence from its absence -- it documents intent, it does not
    // implement it. Don't take the "주석 무시" tests as coverage of this line.
    if (line.startsWith(":")) continue;
    if (line.startsWith("event: ")) event = line.slice(7);
    else if (line.startsWith("data: ")) payload += line.slice(6);
  }
  if (!event) return null; // no event line: not a frame our server would send, drop it
  try {
    return { event, data: JSON.parse(payload || "{}") as Record<string, unknown> };
  } catch {
    return null; // malformed JSON: drop just this frame, keep processing the rest of the stream
  }
}
