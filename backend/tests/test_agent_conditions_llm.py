"""조건 확정 레이어의 추론.

  condition.location  자유 문장 → 업종·자치구·평수·운영형태·희망 임대조건 추출
  condition.finance   누락 항목 중 무엇을 물을지 선택 (최대 3개, 답이 후보를 바꾸는 항목만)

가장 중요한 성질은 **모델이 수치를 만들지 못한다**는 것이다. 모델은 원문의 조각을 가리키기만
하고, 그 조각이 원문에 그대로 있는지 확인한 다음 금액·평수를 **코드가 다시 읽는다**. 발화에
없는 금액이 조건에 들어오는 경로를 이 방식으로 없앤다.
"""
import pytest

from app.agents.conditions import ConditionLayer, resolve_mention
from app.agents.contracts import AgentStatus
from app.agents.llm import AgentLLM, RunBudget

COMPLETE = {"industry": "카페", "district": "강남구", "area_pyeong": 15.0,
            "operating_style": "홀+테이크아웃", "monthly_rent_krw": 2_500_000,
            "deposit_krw": 100_000_000, "equity_krw": 100_000_000}


class ScriptedResponder:
    def __init__(self, *turns):
        self.turns, self.calls = list(turns), []

    async def respond(self, messages, tools, **options):
        self.calls.append(tools[0]["name"])
        return self.turns.pop(0) if self.turns else {"text": "", "tool_calls": []}


def mentions(*rows):
    return {"text": "", "tool_calls": [{"id": "c1", "name": "extract_conditions",
                                        "arguments": {"mentions": list(rows)}}]}


def asks(*fields):
    return {"text": "", "tool_calls": [{"id": "c2", "name": "select_questions",
                                        "arguments": {"ask": list(fields)}}]}


def layer(responder, **kwargs):
    return ConditionLayer(llm=AgentLLM(responder, budget=RunBudget()), **kwargs)


# ── 코드가 값을 읽는다 — 순수 함수부터 고정한다 ─────────────────────────────

# 금액 파싱 자체의 계약은 `test_amount_parsing.py` 가 두 경로에 걸쳐 고정한다.
# 여기서 다시 단언하면 같은 것을 두 곳에서 정의하게 되고, 한쪽만 고쳐도 통과하게 된다.


def test_a_district_is_resolved_only_to_one_of_the_twenty_five():
    assert resolve_mention("district", "강남구에서") == "강남구"
    assert resolve_mention("district", "분당구") is None


def test_an_area_is_read_in_pyeong_from_the_span():
    assert resolve_mention("area_pyeong", "15평 정도") == 15.0


def test_an_industry_span_keeps_its_own_words_with_the_particle_dropped():
    # 업종은 열거가 불가능하므로 원문 그대로 쓴다. 유사 매칭은 industry 코드 단계의 몫이고,
    # 여기서 "커피-음료" 같은 상위 분류로 바꾸면 그 순간 유사 매칭이 된다.
    assert resolve_mention("industry", "무인 카페를") == "무인 카페"


# ── condition.location ───────────────────────────────────────────────────

async def test_the_model_fills_only_the_conditions_that_were_missing():
    responder = ScriptedResponder(mentions({"field": "area_pyeong", "span": "20평"},
                                           {"field": "industry", "span": "베이커리"}))
    conditions = {**COMPLETE, "area_pyeong": None, "utterance": "강남구에 20평 베이커리 자리 찾아요"}
    report = await layer(responder).arun(conditions)
    location = next(item for item in report.outcomes if item.key == "condition.location")
    assert location.data["extracted"] == {"area_pyeong": 20.0}
    # 이미 확정된 업종은 모델이 무엇을 가리키든 바뀌지 않는다.
    assert location.data["settled"]["industry"] == "카페"


async def test_a_span_that_is_not_in_the_utterance_never_becomes_a_condition():
    responder = ScriptedResponder(mentions({"field": "monthly_rent_krw", "span": "월세 400만원"}))
    conditions = {"district": "강남구", "industry": "카페", "equity_krw": 100_000_000,
                  "utterance": "강남구에 카페 자리 찾아요"}
    report = await layer(responder).arun(conditions)
    location = next(item for item in report.outcomes if item.key == "condition.location")
    assert location.data["extracted"] == {}
    assert location.data["decision"]["rejected"][0]["reason"] == "not_in_source"


async def test_a_verified_span_becomes_a_condition_the_code_parsed():
    responder = ScriptedResponder(mentions({"field": "monthly_rent_krw", "span": "300만원"}))
    conditions = {"district": "강남구", "industry": "카페", "equity_krw": 100_000_000,
                  "utterance": "강남구 카페, 월세는 300만원까지 봅니다"}
    report = await layer(responder).arun(conditions)
    location = next(item for item in report.outcomes if item.key == "condition.location")
    assert location.data["extracted"] == {"monthly_rent_krw": 3_000_000}
    assert report.settled is True


async def test_extraction_can_settle_a_condition_that_was_blocking_the_run():
    responder = ScriptedResponder(mentions({"field": "district", "span": "마포구"}))
    conditions = {"industry": "카페", "district": "", "equity_krw": 100_000_000,
                  "monthly_rent_krw": 2_000_000, "utterance": "마포구 쪽으로 보고 있어요"}
    report = await layer(responder).arun(conditions)
    assert report.settled is True
    assert report.questions == []


async def test_without_an_utterance_the_model_is_not_called_at_all():
    # 대조할 원문이 없으면 검증이 불가능하다. 검증할 수 없는 추출은 하지 않는다.
    responder = ScriptedResponder(mentions({"field": "district", "span": "마포구"}))
    report = await layer(responder).arun(COMPLETE)
    assert responder.calls == ["select_questions"] or responder.calls == []
    location = next(item for item in report.outcomes if item.key == "condition.location")
    assert location.data["decision"]["source"] == "deterministic"


async def test_without_an_llm_the_layer_behaves_exactly_as_before():
    report = await ConditionLayer().arun({**COMPLETE, "utterance": "강남구 카페"})
    assert report.settled is True
    location = next(item for item in report.outcomes if item.key == "condition.location")
    assert location.data["extracted"] == {}


# ── condition.finance ────────────────────────────────────────────────────

async def test_the_model_chooses_which_gaps_to_ask_about():
    responder = ScriptedResponder(mentions(), asks("equity_krw"))
    conditions = {"industry": "카페", "district": "강남구", "utterance": "강남구 카페"}
    report = await layer(responder).arun(conditions)
    assert [question["field"] for question in report.questions] == ["equity_krw"]


async def test_the_model_cannot_ask_about_a_deferrable_gap():
    """희망 월세는 비어 있어도 되묻기 목록에 오르지 않는다 — 모델이 골라도 마찬가지다.
    유보 항목을 되물으면 되묻기가 다시 늘어나고 자동 진행이 그만큼 막힌다."""
    responder = ScriptedResponder(mentions(), asks("monthly_rent_krw"))
    conditions = {"industry": "카페", "district": "강남구", "equity_krw": 50_000_000,
                  "utterance": "강남구 카페"}
    report = await layer(responder).arun(conditions)
    assert report.questions == []
    assert "monthly_rent_krw" in report.deferred


async def test_a_question_about_something_that_is_not_missing_is_discarded():
    # 이미 답이 있는 항목을 되물으면 "답이 후보를 바꾸는 항목만"이라는 계약이 깨진다.
    responder = ScriptedResponder(mentions(), asks("area_pyeong", "equity_krw"))
    conditions = {"industry": "카페", "district": "강남구", "monthly_rent_krw": 2_000_000,
                  "area_pyeong": 15.0, "utterance": "강남구 카페"}
    report = await layer(responder).arun(conditions)
    assert [question["field"] for question in report.questions] == ["equity_krw"]


async def test_the_question_limit_survives_the_model():
    responder = ScriptedResponder(mentions(), asks("equity_krw", "monthly_rent_krw", "industry", "district"))
    report = await layer(responder).arun({"utterance": "가게 하나 하려고요"})
    assert len(report.questions) <= 3


async def test_a_model_that_picks_nothing_falls_back_to_the_declared_order():
    responder = ScriptedResponder(mentions(), asks())
    report = await layer(responder).arun({"industry": "카페", "utterance": "카페 하려고요"})
    # 선언 순서는 BLOCKING 의 순서다. 희망 월세는 유보 항목이라 여기 오지 않는다.
    assert [question["field"] for question in report.questions] == ["district", "equity_krw"]


async def test_the_finance_agent_records_what_the_model_chose():
    responder = ScriptedResponder(mentions(), asks("equity_krw"))
    report = await layer(responder).arun({"industry": "카페", "district": "강남구",
                                          "monthly_rent_krw": 2_000_000, "utterance": "강남구 카페"})
    finance = next(item for item in report.outcomes if item.key == "condition.finance")
    assert finance.data["decision"]["chosen"] == {"ask": ["equity_krw"]}
    assert finance.status is AgentStatus.WITHHELD


# ── 기존 동기 경로는 그대로 남는다 ────────────────────────────────────────

def test_the_synchronous_path_still_works_without_any_model():
    report = ConditionLayer().run(COMPLETE)
    assert report.settled is True
