import test from "node:test";
import assert from "node:assert/strict";
import { applyPrescribeFrame, ApiError } from "../lib/api.ts";

function recorder() {
  const calls = { runStart: [], teamStart: [], agentEnd: [], done: [] };
  return { calls,
    onRunStart: info => calls.runStart.push(info),
    onTeamStart: team => calls.teamStart.push(team),
    onAgentEnd: agent => calls.agentEnd.push(agent),
    onDone: result => calls.done.push(result) };
}

test("run_start reports how many agents the run will cover", () => {
  const handlers = recorder();
  assert.equal(applyPrescribeFrame({ event: "run_start", data: { total_agents: 12, fingerprint: "abc" } }, handlers), false);
  assert.deepEqual(handlers.calls.runStart, [{ total_agents: 12, fingerprint: "abc" }]);
});

test("team_start carries the team's Korean name and its agent count", () => {
  const handlers = recorder();
  applyPrescribeFrame({ event: "team_start", data: { team: "finance", name: "금융처방 팀", agent_count: 4 } }, handlers);
  assert.deepEqual(handlers.calls.teamStart, [{ team: "finance", name: "금융처방 팀", agent_count: 4 }]);
});

test("agent_end keeps the backend status verbatim so the UI never re-judges it", () => {
  const handlers = recorder();
  applyPrescribeFrame({ event: "agent_end", data: { team: "location", key: "location.survival", name: "생존시기", status: "integration_pending", message: "인허가 코호트 미구축" } }, handlers);
  assert.deepEqual(handlers.calls.agentEnd, [{ team: "location", key: "location.survival", name: "생존시기", status: "integration_pending", message: "인허가 코호트 미구축" }]);
});

test("an unknown status passes through rather than folding to a failure", () => {
  // 판정에 성공한 축을 고장난 것처럼 보이게 만드는 방향으로 반올림하지 않는다.
  const handlers = recorder();
  applyPrescribeFrame({ event: "agent_end", data: { key: "finance.band", name: "조달 밴드 산출", status: "some_future_status" } }, handlers);
  assert.equal(handlers.calls.agentEnd[0].status, "some_future_status");
});

test("a malformed agent_end falls back to safe defaults rather than rendering undefined", () => {
  const handlers = recorder();
  applyPrescribeFrame({ event: "agent_end", data: {} }, handlers);
  assert.equal(handlers.calls.agentEnd[0].status, "unknown");
  assert.equal(typeof handlers.calls.agentEnd[0].name, "string");
});

test("done settles the run and carries activation, summary and the drop list", () => {
  const handlers = recorder();
  const settled = applyPrescribeFrame({ event: "done", data: {
    halted_at: null, reused: false, activation: { total: 12, active: 5, by_key: {} },
    summary: { recommended_ceiling_krw: 145000000 }, surviving: [{ id: "l1" }],
    dropped: [{ id: "l2", reason: "분기점 미달" }], questions: [] } }, handlers);
  assert.equal(settled, true);
  assert.equal(handlers.calls.done[0].activation.active, 5);
  assert.equal(handlers.calls.done[0].dropped[0].reason, "분기점 미달");
});

test("a halted run still settles and names where it stopped", () => {
  const handlers = recorder();
  assert.equal(applyPrescribeFrame({ event: "done", data: { halted_at: "finance", activation: { total: 12, active: 3, by_key: {} }, summary: {} } }, handlers), true);
  assert.equal(handlers.calls.done[0].halted_at, "finance");
  assert.deepEqual(handlers.calls.done[0].summary, {});
});

test("a run halted at the condition layer forwards its questions", () => {
  const handlers = recorder();
  applyPrescribeFrame({ event: "done", data: { halted_at: "condition", questions: [{ field: "industry", label: "업종" }] } }, handlers);
  // 서버가 안 보낸 키는 빈 값으로 채운다. 되묻기 항목의 모양이 두 가지면 화면이 매번 어느
  // 쪽인지 확인해야 하고, 한쪽에만 있는 키를 읽다 조용히 undefined 가 된다.
  assert.deepEqual(handlers.calls.done[0].questions,
    [{ field: "industry", label: "업종", reason: "MISSING", message: "", options: [] }]);
});

test("an unmappable industry forwards its recovery reason and candidates", () => {
  const handlers = recorder();
  applyPrescribeFrame({ event: "done", data: { halted_at: "condition", questions: [{
    field: "industry", label: "업종", reason: "UNMAPPED_INDUSTRY",
    message: "'스터디카페' 은(는) 상권 통계의 업종 코드로 이어지지 않아 입지 판단을 할 수 없습니다. 가까운 업종을 골라 주세요.",
    options: ["카페", "학원"]
  }] } }, handlers);
  const question = handlers.calls.done[0].questions[0];
  assert.equal(question.reason, "UNMAPPED_INDUSTRY");
  assert.deepEqual(question.options, ["카페", "학원"]);
});

test("an unknown question reason degrades to MISSING rather than passing through", () => {
  const handlers = recorder();
  applyPrescribeFrame({ event: "done", data: { questions: [{ field: "industry", label: "업종", reason: "SOMETHING_ELSE" }] } }, handlers);
  assert.equal(handlers.calls.done[0].questions[0].reason, "MISSING");
});

test("team_end is accepted and ignored, not treated as the end of the run", () => {
  const handlers = recorder();
  assert.equal(applyPrescribeFrame({ event: "team_end", data: { team: "finance", active: 1 } }, handlers), false);
  assert.deepEqual(handlers.calls.done, []);
});

test("an error frame throws ApiError so the caller cannot mistake it for a finished run", () => {
  const handlers = recorder();
  assert.throws(() => applyPrescribeFrame({ event: "error", data: { code: "PRESCRIBE_FAILED", message: "분석을 완료하지 못했습니다.", retryable: true } }, handlers),
    error => error instanceof ApiError && error.code === "PRESCRIBE_FAILED" && error.retryable === true);
  assert.deepEqual(handlers.calls.done, []);
});

test("an unknown event name is a forward-compatible no-op, not a crash", () => {
  const handlers = recorder();
  assert.equal(applyPrescribeFrame({ event: "something_new", data: {} }, handlers), false);
  assert.deepEqual(handlers.calls, { runStart: [], teamStart: [], agentEnd: [], done: [] });
});

test("agent_end forwards the agent's own numbers so a settled row can quote them", () => {
  // 조달 밴드 줄은 "완료"만 적기에는 아까운 줄이다 — 백엔드가 이미 낸 수치를 그대로 인용한다.
  // 인용이 성립하려면 그 수치가 이벤트에 실려 와야 하고, 화면이 다시 계산해서는 안 된다.
  const handlers = recorder();
  applyPrescribeFrame({ event: "agent_end", data: {
    team: "finance", key: "finance.band", name: "조달 밴드 산출", status: "ok",
    data: { bands: [{ band: "RECOMMENDED", ceiling_krw: 145000000, target_daily_revenue_krw: 320000 }] },
  } }, handlers);
  const recommended = handlers.calls.agentEnd[0].data.bands.find((line) => line.band === "RECOMMENDED");
  assert.equal(recommended.ceiling_krw, 145000000);
});

test("an agent_end without data leaves the field absent rather than inventing an empty shape", () => {
  const handlers = recorder();
  applyPrescribeFrame({ event: "agent_end", data: { key: "timing.policy", status: "integration_pending" } }, handlers);
  assert.equal(handlers.calls.agentEnd[0].data, undefined);
});
