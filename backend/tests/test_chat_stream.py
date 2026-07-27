import asyncio
import json
import pytest
from app.chat_stream import ChatStreamer, StreamLimits, _summarize
from app.config import Settings
from app.services import AIService, OpenAIResponder


class FakeToolset:
    def __init__(self, results=None):
        self.results = results or {}
        self.calls = []

    def schemas(self):
        return [{"name": "resolve_seoul_place", "description": "d",
                 "parameters": {"type": "object", "properties": {}, "required": []}}]

    async def run(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.get(name, {"status": "ok", "citations": []})


class FakeLLM:
    """Replays scripted turns. Each turn is either tool calls or a final text."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.prompts = []

    async def respond(self, messages, tools):
        self.prompts.append((messages, tools))
        return self.turns.pop(0) if self.turns else {"text": "더 이상 할 말이 없습니다.", "tool_calls": []}


async def collect(streamer, text="강남구 분양 알려줘"):
    return [event async for event in streamer.run(text, "케이스 요약")]


def kinds(events):
    return [event["event"] for event in events]


async def test_a_turn_without_tools_emits_start_delta_and_done():
    streamer = ChatStreamer(FakeLLM([{"text": "안녕하세요.", "tool_calls": []}]), FakeToolset(), StreamLimits())
    events = await collect(streamer)
    assert kinds(events) == ["turn_start", "delta", "done"]
    assert events[-1]["data"]["message"] == "안녕하세요."


async def test_tool_calls_emit_start_and_end_events():
    llm = FakeLLM([{"text": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {"query": "강남구"}}]},
                   {"text": "강남구를 확인했습니다.", "tool_calls": []}])
    events = await collect(ChatStreamer(llm, FakeToolset(), StreamLimits()))
    assert kinds(events) == ["turn_start", "tool_start", "tool_end", "delta", "done"]
    assert events[1]["data"]["tool"] == "resolve_seoul_place"
    assert events[2]["data"]["status"] == "ok"


async def test_citations_from_tools_reach_the_done_event():
    tools = FakeToolset({"resolve_seoul_place": {"status": "ok", "citations": [
        {"title": "카카오 로컬", "official_url": "https://map.kakao.com/", "source_name": "카카오 로컬",
         "collected_at": "2026-07-27T00:00:00+00:00", "tool": "resolve_seoul_place"}]}})
    llm = FakeLLM([{"text": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {}}]},
                   {"text": "확인했습니다.", "tool_calls": []}])
    events = await collect(ChatStreamer(llm, tools, StreamLimits()))
    assert events[-1]["data"]["citations"][0]["source_name"] == "카카오 로컬"


async def test_duplicate_citations_are_collapsed():
    same = {"title": "카카오 로컬", "official_url": "https://map.kakao.com/", "source_name": "카카오 로컬",
            "collected_at": "2026-07-27T00:00:00+00:00", "tool": "resolve_seoul_place"}
    tools = FakeToolset({"resolve_seoul_place": {"status": "ok", "citations": [same, dict(same)]}})
    llm = FakeLLM([{"text": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {}}]},
                   {"text": "확인했습니다.", "tool_calls": []}])
    events = await collect(ChatStreamer(llm, tools, StreamLimits()))
    assert len(events[-1]["data"]["citations"]) == 1


async def test_the_loop_stops_at_the_round_limit_and_says_so():
    forever = [{"text": "", "tool_calls": [{"id": f"c{i}", "name": "resolve_seoul_place", "arguments": {}}]}
               for i in range(10)]
    events = await collect(ChatStreamer(FakeLLM(forever), FakeToolset(), StreamLimits(max_rounds=2)))
    done = events[-1]["data"]
    assert events[-1]["event"] == "done"
    assert "길어져" in done["message"]
    assert kinds(events).count("tool_start") == 2


async def test_the_loop_stops_at_the_raw_call_limit():
    many = [{"text": "", "tool_calls": [{"id": f"c{i}-{j}", "name": "resolve_seoul_place", "arguments": {}}
                                        for j in range(4)]} for i in range(10)]
    events = await collect(ChatStreamer(FakeLLM(many), FakeToolset(), StreamLimits(max_rounds=10, max_tool_calls=5)))
    assert kinds(events).count("tool_start") == 5
    assert events[-1]["event"] == "done"


def _declared_and_fulfilled_tool_call_ids(messages):
    """Every tool_call id an assistant message declares vs. every id a role:tool message answers.
    `messages` is the same list object ChatStreamer mutates in place and hands to `llm.respond`
    each round, so inspecting any captured reference after the run finishes sees the final state
    -- including the truncated round's synthetic skipped-result entries, even though that round's
    own `respond()` call happened before they were appended."""
    declared = {call["id"] for message in messages if message["role"] == "assistant"
                for call in message.get("tool_calls", [])}
    fulfilled = {message["tool_call_id"] for message in messages if message["role"] == "tool"}
    return declared, fulfilled


async def test_a_truncated_round_still_pairs_every_declared_tool_call_with_a_tool_result():
    """Regression test for the carried-over Task 7 bug: when the raw call-budget runs out mid
    round, ChatStreamer used to append an assistant message declaring all of that round's
    tool_calls while only appending role:tool results for the executed subset. Reverting the
    chat_stream.py fix (dropping the synthetic skipped-result loop) makes `declared` a strict
    superset of `fulfilled` here, so this assertion fails without the fix."""
    calls = [{"id": f"c{i}", "name": "resolve_seoul_place", "arguments": {}} for i in range(5)]
    llm = FakeLLM([{"text": "", "tool_calls": calls}])
    streamer = ChatStreamer(llm, FakeToolset(), StreamLimits(max_rounds=1, max_tool_calls=2))
    await collect(streamer)
    declared, fulfilled = _declared_and_fulfilled_tool_call_ids(llm.prompts[0][0])
    assert declared == {"c0", "c1", "c2", "c3", "c4"}
    assert declared == fulfilled


async def test_an_untruncated_multi_round_conversation_pairs_every_declared_tool_call_with_a_tool_result():
    llm = FakeLLM([{"text": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {}}]},
                   {"text": "", "tool_calls": [{"id": "c2", "name": "resolve_seoul_place", "arguments": {}}]},
                   {"text": "다 됐습니다.", "tool_calls": []}])
    streamer = ChatStreamer(llm, FakeToolset(), StreamLimits())
    await collect(streamer)
    declared, fulfilled = _declared_and_fulfilled_tool_call_ids(llm.prompts[-1][0])
    assert declared == {"c1", "c2"}
    assert declared == fulfilled


async def test_a_failing_tool_does_not_end_the_turn():
    tools = FakeToolset({"resolve_seoul_place": {"status": "error", "message": "조회에 실패했습니다."}})
    llm = FakeLLM([{"text": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {}}]},
                   {"text": "조회하지 못했습니다.", "tool_calls": []}])
    events = await collect(ChatStreamer(llm, tools, StreamLimits()))
    assert events[2]["event"] == "tool_end" and events[2]["data"]["status"] == "error"
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["message"] == "조회하지 못했습니다."


async def test_tools_unavailable_reports_not_configured_and_skips_the_tool_list():
    streamer = ChatStreamer(FakeLLM([{"text": "키가 없습니다.", "tool_calls": []}]), None, StreamLimits())
    events = await collect(streamer)
    assert events[0]["data"]["tools_available"] is False
    assert events[-1]["data"]["integration_status"] == "not_configured"


async def test_no_toolset_but_the_model_calls_a_tool_anyway_does_not_crash():
    """Defensive case not in the original test set: tools_available is False (toolset=None) so
    the model is handed an empty schema list, but a misbehaving/fake LLM could still emit a
    tool_call. Without a guard, ChatStreamer would call `None.run(...)` and crash the whole
    turn -- deleting the guard reproduces exactly that AttributeError."""
    llm = FakeLLM([{"text": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {}}]},
                   {"text": "도구 없이 답합니다.", "tool_calls": []}])
    events = await collect(ChatStreamer(llm, None, StreamLimits()))
    assert kinds(events) == ["turn_start", "tool_start", "tool_end", "delta", "done"]
    assert events[2]["data"]["status"] == "error"


async def test_an_empty_final_text_is_reported_as_incomplete():
    events = await collect(ChatStreamer(FakeLLM([{"text": "", "tool_calls": []}]), FakeToolset(), StreamLimits()))
    assert events[-1]["data"]["integration_status"] == "incomplete"
    assert events[-1]["data"]["message"]


async def test_an_llm_failure_emits_an_error_event():
    class BrokenLLM:
        async def respond(self, messages, tools):
            raise RuntimeError("upstream down")

    events = await collect(ChatStreamer(BrokenLLM(), FakeToolset(), StreamLimits()))
    assert events[-1]["event"] == "error"
    assert events[-1]["data"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert events[-1]["data"]["retryable"] is True


async def test_a_cancellation_during_the_model_call_is_not_reported_as_an_error_event():
    """asyncio.CancelledError subclasses BaseException, not Exception (verified on this repo's
    Python 3.12), so `except Exception` around llm.respond must let it through untouched --
    exactly the property mcp_client.MCPSession relies on for the same reason. If the `except`
    clause were ever widened to `except BaseException`, this test would fail because the
    cancellation would be swallowed and reported as an ordinary 'error' event instead of
    propagating."""
    class CancellingLLM:
        async def respond(self, messages, tools):
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await collect(ChatStreamer(CancellingLLM(), FakeToolset(), StreamLimits()))


async def test_the_system_prompt_carries_the_calculation_and_injection_rules():
    """Asserts only that the instructions reach the model. It does NOT prove the model obeys
    them -- nothing at this layer can. The guardrail that actually holds is that the tools
    return raw upstream values and compute nothing (Tasks 5-6)."""
    llm = FakeLLM([{"text": "안녕하세요.", "tool_calls": []}])
    await collect(ChatStreamer(llm, FakeToolset(), StreamLimits()))
    system = llm.prompts[0][0][0]["content"]
    assert "계산" in system
    assert "지시문" in system


async def test_tool_results_are_wrapped_in_a_delimiter():
    llm = FakeLLM([{"text": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {}}]},
                   {"text": "확인.", "tool_calls": []}])
    await collect(ChatStreamer(llm, FakeToolset(), StreamLimits()))
    second_turn_messages = llm.prompts[1][0]
    tool_message = [item for item in second_turn_messages if item["role"] == "tool"][0]
    assert tool_message["content"].startswith("<<<TOOL_RESULT")
    assert tool_message["content"].rstrip().endswith("TOOL_RESULT>>>")


# --- _summarize: exercised directly, since scan_nearby_facilities's split-bucket shape and the
# hidden-failure risk it creates are properties of this function, not of the tool loop around it.

def test_summarize_counts_both_category_and_keyword_buckets_not_just_one():
    """The real bug this guards against: an earlier draft of _summarize checked `by_keyword`
    before `by_category` and returned on the first dict it found -- so a category-only search
    (by_keyword left as {}) always reported '0건' no matter how many category hits came back.
    Deleting the fix (i.e. summing only one bucket) makes this fail."""
    result = {"status": "ok", "by_category": {"SW8": [{"id": 1}, {"id": 2}]}, "by_keyword": {}}
    assert _summarize(result) == "2건"


def test_summarize_folds_in_the_failure_note_even_when_some_targets_succeeded():
    """scan_nearby_facilities stays status=ok when at least one target succeeded, even if others
    failed -- failure_note is the only place that fact lives. Summarizing to a bare count would
    make a partial failure look like a clean, complete answer."""
    result = {"status": "ok", "by_category": {"SW8": [{"id": 1}]}, "by_keyword": {},
              "failed_targets": ["학교"], "failure_note": "다음 대상은 조회에 실패해 결과에서 빠졌습니다: 학교"}
    summary = _summarize(result)
    assert "1건" in summary
    assert "학교" in summary


def test_summarize_reports_the_message_for_non_countable_statuses():
    """not_found/error/out_of_scope/etc. carry a human message and no meaningful item list --
    summarizing them as a count (e.g. '0건') would hide *why* nothing came back."""
    assert _summarize({"status": "not_found", "message": "단지를 찾지 못했습니다."}) == "단지를 찾지 못했습니다."
    assert _summarize({"status": "error", "message": "조회에 실패했습니다."}) == "조회에 실패했습니다."


# --- OpenAIResponder: the {text, tool_calls} adapter over the Responses API ---

def ai_service(**overrides):
    base = dict(openai_api_key="sk-test", ai_chat_model="gpt-5", ai_explanation_enabled=True)
    base.update(overrides)
    return AIService(Settings(**base))


def test_responder_is_none_without_a_key():
    assert ai_service(openai_api_key="").responder() is None


def test_responder_is_none_when_explanation_is_disabled():
    assert ai_service(ai_explanation_enabled=False).responder() is None


def test_responder_exists_when_configured():
    assert isinstance(ai_service().responder(), OpenAIResponder)


def test_responder_flattens_openai_tool_calls():
    class FakeResponse:
        output_text = "확인했습니다."
        output = [type("Call", (), {"type": "function_call", "call_id": "c1", "name": "resolve_seoul_place",
                                    "arguments": '{"query": "강남구"}'})()]

    parsed = OpenAIResponder._parse(FakeResponse())
    assert parsed["text"] == "확인했습니다."
    assert parsed["tool_calls"] == [{"id": "c1", "name": "resolve_seoul_place", "arguments": {"query": "강남구"}}]


def test_responder_survives_unparseable_tool_arguments():
    class FakeResponse:
        output_text = ""
        output = [type("Call", (), {"type": "function_call", "call_id": "c1", "name": "resolve_seoul_place",
                                    "arguments": "not json"})()]

    assert OpenAIResponder._parse(FakeResponse())["tool_calls"][0]["arguments"] == {}


def test_responder_ignores_non_function_output_items():
    class FakeResponse:
        output_text = "안녕하세요."
        output = [type("Reasoning", (), {"type": "reasoning"})()]

    assert OpenAIResponder._parse(FakeResponse())["tool_calls"] == []


# The Responses API's `input` array does not accept ChatStreamer's Chat-Completions-shaped
# messages (assistant messages carrying a nested `tool_calls` list; tool results carrying
# `tool_call_id`) -- function calls and their outputs are each a distinct top-level item there
# (`function_call` / `function_call_output`), never a field nested inside a role:assistant or
# role:tool message. These tests pin down `_translate`, the layer that bridges the two shapes;
# deleting it (passing `messages` straight through as `input`) would make every one of them fail,
# either on the assertion shape or because the OpenAI SDK's TypedDicts don't match at all.

def test_translate_turns_plain_messages_into_responses_message_items():
    items = OpenAIResponder._translate([{"role": "system", "content": "시스템"}, {"role": "user", "content": "질문"}])
    assert items == [{"type": "message", "role": "system", "content": "시스템"},
                     {"type": "message", "role": "user", "content": "질문"}]


def test_translate_turns_an_assistant_tool_call_into_a_standalone_function_call_item():
    items = OpenAIResponder._translate(
        [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "name": "resolve_seoul_place",
                                                              "arguments": {"query": "강남구"}}]}])
    assert items == [{"type": "function_call", "call_id": "c1", "name": "resolve_seoul_place",
                      "arguments": json.dumps({"query": "강남구"}, ensure_ascii=False)}]


def test_translate_turns_a_tool_result_into_a_function_call_output_item():
    """The Responses API's FunctionCallOutput item takes the result text under `output`, keyed to
    the call by `call_id` -- not `content`/`tool_call_id`, which is Chat-Completions vocabulary."""
    items = OpenAIResponder._translate([{"role": "tool", "tool_call_id": "c1", "content": "<<<TOOL_RESULT\n{}\nTOOL_RESULT>>>"}])
    assert items == [{"type": "function_call_output", "call_id": "c1", "output": "<<<TOOL_RESULT\n{}\nTOOL_RESULT>>>"}]


def test_translate_keeps_an_assistant_message_with_both_text_and_tool_calls_as_two_items():
    """A round can, in principle, carry commentary text alongside its tool_calls (ChatStreamer
    stores whatever `turn.get('text')` was, unconditionally). Both must survive translation: the
    text as a message item, the call as its own function_call item -- not one item with both,
    since the Responses API has no such combined shape."""
    items = OpenAIResponder._translate(
        [{"role": "assistant", "content": "확인 중입니다.",
          "tool_calls": [{"id": "c1", "name": "resolve_seoul_place", "arguments": {}}]}])
    assert {"type": "message", "role": "assistant", "content": "확인 중입니다."} in items
    assert any(item.get("type") == "function_call" and item.get("call_id") == "c1" for item in items)
    assert len(items) == 2


class FakeResponsesAPI:
    """Records every kwargs dict `.create()` was called with; replays `error` on the first call
    only (mirroring a transient reasoning-parameter rejection that succeeds on retry), else
    returns `response`."""

    def __init__(self, response, error=None):
        self.response, self.error, self.calls = response, error, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None and len(self.calls) == 1:
            raise self.error
        return self.response


class FakeOpenAIClient:
    def __init__(self, response, error=None):
        self.responses = FakeResponsesAPI(response, error)


def _fake_response(text="", tool_calls=()):
    return type("FakeResponse", (), {"output_text": text, "output": list(tool_calls)})()


async def test_respond_sends_translated_input_and_low_reasoning_effort_by_default():
    client = FakeOpenAIClient(_fake_response(text="ok"))
    responder = OpenAIResponder(client, "gpt-5")
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]
    tools = [{"name": "resolve_seoul_place", "description": "d",
             "parameters": {"type": "object", "properties": {}, "required": []}}]
    result = await responder.respond(messages, tools)
    assert result["text"] == "ok"
    kwargs = client.responses.calls[0]
    assert kwargs["model"] == "gpt-5"
    assert kwargs["input"] == OpenAIResponder._translate(messages)
    assert kwargs["reasoning"] == {"effort": "low"}
    assert kwargs["store"] is False
    # `strict` is Required[Optional[bool]] on FunctionToolParam -- the key has to be there.
    assert kwargs["tools"] == [{"type": "function", "name": "resolve_seoul_place", "description": "d",
                               "parameters": {"type": "object", "properties": {}, "required": []},
                               "strict": False}]


async def test_respond_omits_the_tools_key_when_no_tools_are_available():
    client = FakeOpenAIClient(_fake_response(text="ok"))
    responder = OpenAIResponder(client, "gpt-5")
    await responder.respond([{"role": "user", "content": "hi"}], [])
    assert "tools" not in client.responses.calls[0]


async def test_respond_retries_without_reasoning_when_the_installed_sdk_rejects_the_kwarg():
    """Mirrors AIService._respond's own compatibility fallback: some installed SDK builds raise
    TypeError for an unrecognized `reasoning` kwarg before any network call happens."""
    client = FakeOpenAIClient(_fake_response(text="ok"), error=TypeError("unexpected keyword argument 'reasoning'"))
    responder = OpenAIResponder(client, "gpt-5")
    result = await responder.respond([{"role": "user", "content": "hi"}], [])
    assert result["text"] == "ok"
    assert len(client.responses.calls) == 2
    assert "reasoning" not in client.responses.calls[1]


async def test_respond_retries_without_reasoning_when_the_configured_model_rejects_the_parameter():
    """A non-reasoning model can reject `reasoning` server-side instead of at the SDK layer -- an
    ordinary Exception whose message names the parameter, not a TypeError."""
    client = FakeOpenAIClient(_fake_response(text="ok"), error=Exception("Unsupported parameter: 'reasoning'"))
    responder = OpenAIResponder(client, "gpt-5")
    result = await responder.respond([{"role": "user", "content": "hi"}], [])
    assert result["text"] == "ok"
    assert len(client.responses.calls) == 2


async def test_respond_propagates_errors_unrelated_to_reasoning():
    """An error that has nothing to do with the reasoning kwarg (auth failure, rate limit, ...)
    must not be silently retried and swallowed -- ChatStreamer's own `except Exception` around
    `respond()` is what turns this into an UPSTREAM_UNAVAILABLE event; if this method swallowed it
    instead, the loop would treat a real outage as if the model had simply answered nothing."""
    client = FakeOpenAIClient(_fake_response(), error=RuntimeError("rate limited"))
    responder = OpenAIResponder(client, "gpt-5")
    with pytest.raises(RuntimeError):
        await responder.respond([{"role": "user", "content": "hi"}], [])
    assert len(client.responses.calls) == 1
