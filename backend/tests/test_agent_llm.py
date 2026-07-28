"""서브에이전트가 LLM 을 부르는 유일한 통로. 제안서 06장 가드 1·2를 구조로 강제한다.

  가드 1  숫자는 도구·계산기 결과만. 그래서 이 통로의 선택 스키마에는 수치 타입이 없다.
          모델은 열거된 선택지를 고르거나(Pick), 원문의 한 조각을 가리키거나(Span),
          예/아니오(Flag)만 할 수 있다. 수치는 코드가 원문에서 다시 읽는다.
  가드 2  같은 조건이면 같은 답. temperature 0 으로 부르고, 모델이 무엇을 골랐는지를
          Decision 으로 남겨 감사 가능하게 한다.

모든 실패는 Decision 으로 봉쇄된다 — chat_tools.ChatToolset.run 과 같은 규칙이다.
단 CancelledError 는 통과시킨다.
"""
import asyncio

import pytest

from app.agents.llm import (AgentLLM, ChoiceSchema, Decision, Flag, Pick, Records, RunBudget,
                            Span)


class FakeResponder:
    """respond() 한 번에 무엇을 돌려줄지 대본으로 받는다. 네트워크를 타지 않는다."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls: list[dict] = []

    async def respond(self, messages, tools, **options):
        self.calls.append({"messages": messages, "tools": tools, "options": options})
        if not self.turns:
            return {"text": "", "tool_calls": []}
        turn = self.turns.pop(0)
        # BaseException 으로 받는다 — CancelledError 가 Exception 이 아니기 때문이고,
        # 통과 여부를 시험하려는 대상이 정확히 그 차이다.
        if isinstance(turn, BaseException):
            raise turn
        return turn


def call(name, arguments):
    return {"text": "", "tool_calls": [{"id": "c1", "name": name, "arguments": arguments}]}


SCENARIOS = ChoiceSchema(
    name="select_scenarios", description="이 케이스에 유의미한 시나리오를 고른다",
    fields={"scenarios": Pick(("REVENUE_DROP_20", "REVENUE_DROP_30", "RATE_PLUS_1PP"),
                              multi=True, max_items=2)})


def llm(responder, budget=None):
    return AgentLLM(responder, budget=budget or RunBudget())


# ── 스키마 자체가 가드 1이다 ────────────────────────────────────────────────

def test_no_choice_schema_can_declare_a_numeric_field():
    # 모델이 수치를 낼 문법 자체를 주지 않는다. 스키마에 number/integer 가 있으면 가드 1이 뚫린다.
    schema = ChoiceSchema(name="x", description="", fields={
        "pick": Pick(("A", "B")), "span": Span(), "flag": Flag(),
        "rows": Records(fields={"field": Pick(("a",)), "span": Span()})})
    rendered = repr(schema.json_schema())
    assert '"number"' not in rendered and "'number'" not in rendered
    assert '"integer"' not in rendered and "'integer'" not in rendered


def test_the_schema_is_rendered_as_a_single_tool_the_model_must_call():
    tool = SCENARIOS.tool()
    assert tool["name"] == "select_scenarios"
    assert tool["parameters"]["properties"]["scenarios"]["items"]["enum"] == [
        "REVENUE_DROP_20", "REVENUE_DROP_30", "RATE_PLUS_1PP"]


# ── Pick — 열거 밖의 값은 결과에 들어가지 못한다 ──────────────────────────────

async def test_a_pick_outside_the_offered_options_is_rejected_not_passed_through():
    responder = FakeResponder(call("select_scenarios", {"scenarios": ["REVENUE_DROP_20", "매출 반토막"]}))
    decision = await llm(responder).choose(agent_key="finance.stress", instruction="", context={},
                                           schema=SCENARIOS)
    assert decision.chosen["scenarios"] == ["REVENUE_DROP_20"]
    assert decision.rejected == [{"field": "scenarios", "value": "매출 반토막", "reason": "not_offered"}]


async def test_a_multi_pick_is_capped_at_the_declared_maximum():
    responder = FakeResponder(call("select_scenarios",
                                   {"scenarios": ["REVENUE_DROP_20", "REVENUE_DROP_30", "RATE_PLUS_1PP"]}))
    decision = await llm(responder).choose(agent_key="finance.stress", instruction="", context={},
                                           schema=SCENARIOS)
    assert decision.chosen["scenarios"] == ["REVENUE_DROP_20", "REVENUE_DROP_30"]


async def test_a_single_pick_returns_one_value_not_a_list():
    schema = ChoiceSchema(name="verdict", description="", fields={"verdict": Pick(("proceed", "withhold"))})
    responder = FakeResponder(call("verdict", {"verdict": "withhold"}))
    decision = await llm(responder).choose(agent_key="finance.band", instruction="", context={},
                                           schema=schema)
    assert decision.chosen["verdict"] == "withhold"


# ── Span — 원문에 없는 조각은 버린다 ────────────────────────────────────────

MENTIONS = ChoiceSchema(name="extract", description="", fields={
    "mentions": Records(fields={"field": Pick(("industry", "district")), "span": Span()})})


async def test_a_span_that_is_not_verbatim_in_the_source_text_is_rejected():
    # 모델이 원문에 없는 말을 가리키면 그것은 인용이 아니라 창작이다.
    responder = FakeResponder(call("extract", {"mentions": [
        {"field": "industry", "span": "카페"}, {"field": "district", "span": "서초구"}]}))
    decision = await llm(responder).choose(agent_key="condition.location", instruction="", context={},
                                           schema=MENTIONS, verify_against="강남구에서 카페 하려고요")
    assert decision.chosen["mentions"] == [{"field": "industry", "span": "카페"}]
    assert decision.rejected == [{"field": "mentions.span", "value": "서초구", "reason": "not_in_source"}]


async def test_a_span_matches_across_differing_whitespace():
    responder = FakeResponder(call("extract", {"mentions": [{"field": "industry", "span": "무인 카페"}]}))
    decision = await llm(responder).choose(agent_key="condition.location", instruction="", context={},
                                           schema=MENTIONS, verify_against="무인  카페를 열고 싶어요")
    assert decision.chosen["mentions"][0]["span"] == "무인 카페"


async def test_a_span_field_without_a_source_text_is_always_rejected():
    # 대조할 원문이 없으면 검증이 불가능하다. 통과시키면 검증 없는 인용이 된다.
    responder = FakeResponder(call("extract", {"mentions": [{"field": "industry", "span": "카페"}]}))
    decision = await llm(responder).choose(agent_key="condition.location", instruction="", context={},
                                           schema=MENTIONS)
    assert decision.chosen["mentions"] == []


# ── 봉쇄 — 어떤 실패도 예외로 새지 않는다 ────────────────────────────────────

async def test_without_a_responder_the_decision_says_so_instead_of_raising():
    decision = await AgentLLM(None, budget=RunBudget()).choose(
        agent_key="finance.stress", instruction="", context={}, schema=SCENARIOS)
    assert decision.source == "unavailable"
    assert decision.chosen == {}


async def test_an_upstream_failure_becomes_a_decision_not_an_exception():
    decision = await llm(FakeResponder(RuntimeError("boom"))).choose(
        agent_key="finance.stress", instruction="", context={}, schema=SCENARIOS)
    assert decision.source == "error"
    assert decision.chosen == {}


async def test_a_cancellation_still_propagates():
    # 클라이언트 연결이 끊긴 것을 "모델이 답을 못 냈다"로 바꿔 말하면 안 된다.
    with pytest.raises(asyncio.CancelledError):
        await llm(FakeResponder(asyncio.CancelledError())).choose(
            agent_key="finance.stress", instruction="", context={}, schema=SCENARIOS)


async def test_a_model_that_answers_in_prose_instead_of_choosing_yields_nothing():
    # 자유 텍스트는 폐기한다. 거기 적힌 수치가 결과로 새는 경로가 이것이다.
    responder = FakeResponder({"text": "매출 30% 감소가 좋겠습니다", "tool_calls": []})
    decision = await llm(responder).choose(agent_key="finance.stress", instruction="", context={},
                                           schema=SCENARIOS)
    assert decision.source == "empty"
    assert decision.chosen == {}


async def test_a_tool_call_with_another_name_is_not_accepted():
    responder = FakeResponder(call("something_else", {"scenarios": ["REVENUE_DROP_20"]}))
    decision = await llm(responder).choose(agent_key="finance.stress", instruction="", context={},
                                           schema=SCENARIOS)
    assert decision.chosen == {}


# ── 가드 2 — 재현성과 실행당 상한 ───────────────────────────────────────────

async def test_the_call_is_made_at_temperature_zero():
    responder = FakeResponder(call("select_scenarios", {"scenarios": []}))
    await llm(responder).choose(agent_key="finance.stress", instruction="", context={}, schema=SCENARIOS)
    assert responder.calls[0]["options"]["temperature"] == 0


async def test_the_run_budget_stops_further_calls_instead_of_failing_the_run():
    responder = FakeResponder(call("select_scenarios", {"scenarios": ["REVENUE_DROP_20"]}),
                              call("select_scenarios", {"scenarios": ["RATE_PLUS_1PP"]}))
    reasoner = llm(responder, budget=RunBudget(max_calls=1))
    first = await reasoner.choose(agent_key="a", instruction="", context={}, schema=SCENARIOS)
    second = await reasoner.choose(agent_key="b", instruction="", context={}, schema=SCENARIOS)
    assert first.source == "llm"
    assert second.source == "budget_exhausted"
    assert len(responder.calls) == 1


async def test_the_decision_records_the_agent_and_schema_that_produced_it():
    # 감사 가능성 — 어느 에이전트가 어느 선택지에서 무엇을 골랐는지가 결과와 함께 저장된다.
    responder = FakeResponder(call("select_scenarios", {"scenarios": ["REVENUE_DROP_30"]}))
    decision = await llm(responder).choose(agent_key="finance.stress", instruction="", context={},
                                           schema=SCENARIOS)
    assert decision.agent_key == "finance.stress"
    assert decision.schema == "select_scenarios"
    assert decision.as_data() == {"source": "llm", "schema": "select_scenarios",
                                  "chosen": {"scenarios": ["REVENUE_DROP_30"]}, "rejected": []}


def test_a_decision_can_be_built_without_a_model_for_the_deterministic_path():
    decision = Decision.deterministic("finance.stress")
    assert decision.source == "deterministic"
    assert decision.chosen == {}


# ── 설명문 — 메인 에이전트 하나만 쓰는 자유 텍스트 경로 ──────────────────────

async def test_narration_returns_the_text_the_model_wrote():
    responder = FakeResponder({"text": "권장 조달선 기준으로 후보를 좁혔습니다.", "tool_calls": []})
    narration = await llm(responder).narrate(agent_key="main.integrate", instruction="", context={})
    assert narration.text == "권장 조달선 기준으로 후보를 좁혔습니다."
    assert narration.source == "llm"


async def test_narration_is_offered_no_tools_because_it_is_not_choosing_anything():
    responder = FakeResponder({"text": "요약", "tool_calls": []})
    await llm(responder).narrate(agent_key="main.integrate", instruction="", context={})
    assert responder.calls[0]["tools"] == []


async def test_narration_failure_yields_empty_text_rather_than_raising():
    narration = await llm(FakeResponder(RuntimeError("boom"))).narrate(
        agent_key="main.integrate", instruction="", context={})
    assert narration.text == ""
    assert narration.source == "error"


async def test_narration_without_a_responder_says_so():
    narration = await AgentLLM(None, budget=RunBudget()).narrate(
        agent_key="main.integrate", instruction="", context={})
    assert narration.source == "unavailable"


async def test_narration_spends_the_same_run_budget_as_choosing():
    budget = RunBudget(max_calls=1)
    reasoner = llm(FakeResponder({"text": "요약", "tool_calls": []},
                                 {"text": "또 요약", "tool_calls": []}), budget=budget)
    await reasoner.narrate(agent_key="main.integrate", instruction="", context={})
    second = await reasoner.narrate(agent_key="main.integrate", instruction="", context={})
    assert second.source == "budget_exhausted"


def test_the_budget_is_reset_between_runs_not_carried_over():
    # 실행당 상한이므로 케이스가 두 번 돌면 두 번 다 쓸 수 있어야 한다.
    budget = RunBudget(max_calls=2)
    budget.take(); budget.take()
    assert budget.exhausted is True
    budget.reset()
    assert budget.exhausted is False
