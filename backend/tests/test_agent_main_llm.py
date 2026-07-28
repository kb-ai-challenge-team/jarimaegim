"""타이밍 팀과 메인 에이전트의 추론.

  timing.policy   일정 문서의 후보 관련성 판단. 원천 확보 전까지 상태는 integration_pending 유지
  main.integrate  팀 보고 → 설명문. **수치는 인용만**

메인은 12개 중 유일하게 자유 문장을 낸다. 그래서 가드 1이 여기서는 문법이 아니라 후처리로
구현된다 — 제안서 06장의 "근거 표시가 없는데 숫자를 포함한 문장은 후처리로 제거". 팀이 산출한
수치에 없는 숫자가 든 문장은 통째로 버린다. 문장을 버리는 쪽이 틀린 숫자를 남기는 쪽보다 낫다.
"""
from app.agents.contracts import AgentStatus
from app.agents.llm import AgentLLM, RunBudget
from app.agents.orchestrator import quoted_numbers, strip_unsourced_numbers
from app.agents.timing import TimingTeam

CANDIDATES = [{"id": "l1", "name": "OO동 1층"}, {"id": "l2", "name": "△△동 2층"}]

DOCUMENTS = [{"id": "d1", "title": "역삼동 재개발 정비구역 지정 고시"},
             {"id": "d2", "title": "부산 교통망 확충 계획"}]


class ScriptedResponder:
    def __init__(self, **by_schema):
        self.by_schema, self.calls = by_schema, []

    async def respond(self, messages, tools, **options):
        name = tools[0]["name"] if tools else "__text__"
        self.calls.append(name)
        answer = self.by_schema.get(name)
        if answer is None:
            return {"text": "", "tool_calls": []}
        if isinstance(answer, str):
            return {"text": answer, "tool_calls": []}
        return {"text": "", "tool_calls": [{"id": "c", "name": name, "arguments": answer}]}


def llm(responder):
    return AgentLLM(responder, budget=RunBudget())


# ── 수치 인용 후처리 — 순수 함수부터 고정한다 ───────────────────────────────

def test_a_sentence_whose_numbers_all_come_from_the_teams_survives():
    kept, dropped = strip_unsourced_numbers("권장 조달선은 145000000원입니다.", {"145000000"})
    assert kept == "권장 조달선은 145000000원입니다."
    assert dropped == []


def test_a_sentence_carrying_a_number_no_team_produced_is_removed_whole():
    text = "권장 조달선은 145000000원입니다. 이 상권의 폐업률은 12%입니다."
    kept, dropped = strip_unsourced_numbers(text, {"145000000"})
    assert kept == "권장 조달선은 145000000원입니다."
    assert dropped == ["이 상권의 폐업률은 12%입니다."]


def test_thousand_separators_do_not_smuggle_a_number_past_the_filter():
    kept, dropped = strip_unsourced_numbers("월 상환은 1,234,567원입니다.", {"999"})
    assert kept == ""
    assert dropped


def test_a_sentence_without_any_number_is_never_touched():
    kept, _ = strip_unsourced_numbers("조달 상한 안에서만 후보를 제시했습니다.", set())
    assert kept == "조달 상한 안에서만 후보를 제시했습니다."


def test_ratios_may_be_quoted_as_percentages():
    # 팀이 0.2 로 낸 값을 사람이 읽는 문장에서 20% 로 쓰는 것은 인용이지 창작이 아니다.
    assert "20" in quoted_numbers({"revenue_drop_ratio": 0.2})


def test_quoted_numbers_reaches_into_nested_team_data():
    numbers = quoted_numbers({"bands": [{"ceiling_krw": 145_000_000}], "count": 2})
    assert {"145000000", "2"} <= numbers


def test_quoted_numbers_ignores_booleans():
    # True 는 파이썬에서 1 이다. 숫자로 세면 "1"이 근거 없이 허용된다.
    assert quoted_numbers({"stress_pass": True}) == set()


# ── timing.policy ────────────────────────────────────────────────────────

async def test_timing_still_withholds_even_when_documents_are_supplied():
    responder = ScriptedResponder(select_schedule_documents={"relevant": ["d1"]})
    report = await TimingTeam(llm=llm(responder), documents=DOCUMENTS).arun(CANDIDATES)
    outcome = report.outcomes[0]
    assert outcome.status is AgentStatus.INTEGRATION_PENDING
    assert "판단 유보" in (outcome.message or "")
    assert [item["id"] for item in outcome.data["documents"] if item["relevant"]] == ["d1"]


async def test_timing_keeps_every_candidate_whatever_the_model_says():
    responder = ScriptedResponder(select_schedule_documents={"relevant": []})
    report = await TimingTeam(llm=llm(responder), documents=DOCUMENTS).arun(CANDIDATES)
    assert [item["id"] for item in report.surviving] == ["l1", "l2"]


async def test_without_schedule_documents_the_model_is_not_called():
    responder = ScriptedResponder()
    await TimingTeam(llm=llm(responder)).arun(CANDIDATES)
    assert responder.calls == []


def test_the_synchronous_timing_path_is_unchanged():
    report = TimingTeam().run(CANDIDATES)
    assert report.outcomes[0].status is AgentStatus.INTEGRATION_PENDING
    assert [item["id"] for item in report.surviving] == ["l1", "l2"]


# ── main.integrate — 팀 보고를 설명문으로 옮긴다 ────────────────────────────

from app.agents.conditions import ConditionLayer          # noqa: E402
from app.agents.finance import FinanceTeam                # noqa: E402
from app.agents.location import LocationTeam              # noqa: E402
from app.agents.orchestrator import MainAgent             # noqa: E402
from app.policy_params import PolicyParams                # noqa: E402

FULL = PolicyParams({
    "updated_at": "2026-07-27",
    "entries": {
        "loan.annual_rate_percent": {"value": 4.45, "source": "소진공"},
        "loan.term_months": {"value": 60, "source": "소진공"},
        "loan.guarantee_ceiling_krw": {"value": 70_000_000, "source": "테스트"},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000, "source": "테스트"},
        "stress.revenue_drop_ratio": {"value": 0.2, "source": "설계"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "source": "설계"},
        "working_capital.months": {"value": 3, "source": "설계"},
    },
    "industries": {"카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20,
                           "fitout_krw_per_pyeong": 2_500_000, "operating_days_per_month": 26,
                           "source": "테스트"}},
})
EMPTY = PolicyParams({"updated_at": "2026-07-27", "entries": {}, "industries": {}})

CONDITIONS = {"industry": "카페", "district": "강남구", "area_pyeong": 15.0,
              "deposit_krw": 100_000_000, "monthly_rent_krw": 2_500_000,
              "monthly_maintenance_krw": 300_000, "key_money_krw": 0, "fitout_krw": None,
              "equity_krw": 100_000_000, "existing_debt_krw": 0,
              "other_monthly_fixed_krw": 1_000_000}
LISTINGS = [{"id": "l1", "name": "OO동 1층", "admin_dong": "역삼1동", "monthly_rent_krw": 2_500_000}]


def main_agent(responder, params=FULL):
    reasoner = llm(responder)
    return MainAgent(conditions=ConditionLayer(llm=reasoner),
                     finance=FinanceTeam(params, kb_products=[], programs=[], llm=reasoner),
                     location=LocationTeam(llm=reasoner), timing=TimingTeam(llm=reasoner),
                     llm=reasoner, budget=reasoner.budget)


def integration(result):
    return next(item for report in result.reports for item in report.outcomes
                if item.key == "main.integrate")


async def test_the_narrative_keeps_sentences_that_quote_the_teams_numbers():
    result = await main_agent(ScriptedResponder()).run(CONDITIONS, LISTINGS)
    ceiling = result.summary["recommended_ceiling_krw"]
    text = f"권장 조달선은 {ceiling}원입니다."
    responder = ScriptedResponder(__text__=text)
    fresh = await main_agent(responder).run(CONDITIONS, LISTINGS)
    assert integration(fresh).data["narrative"] == text


async def test_a_narrative_number_no_team_produced_is_dropped_from_the_answer():
    responder = ScriptedResponder(__text__="후보를 좁혔습니다. 이 자리의 생존 확률은 61%입니다.")
    result = await main_agent(responder).run(CONDITIONS, LISTINGS)
    integrated = integration(result)
    assert integrated.data["narrative"] == "후보를 좁혔습니다."
    assert integrated.data["narrative_dropped"] == ["이 자리의 생존 확률은 61%입니다."]


async def test_a_halted_run_writes_no_narrative_at_all():
    responder = ScriptedResponder(__text__="설명을 써 보겠습니다.")
    result = await main_agent(responder, EMPTY).run(CONDITIONS, LISTINGS)
    integrated = integration(result)
    assert integrated.status is AgentStatus.WITHHELD
    assert "narrative" not in integrated.data


async def test_a_run_without_a_model_still_reports_the_twelfth_agent():
    plain = MainAgent(conditions=ConditionLayer(),
                      finance=FinanceTeam(FULL, kb_products=[], programs=[]),
                      location=LocationTeam(), timing=TimingTeam())
    result = await plain.run(CONDITIONS, LISTINGS)
    integrated = integration(result)
    assert integrated.status is AgentStatus.OK
    assert integrated.data["summary"]["recommended_ceiling_krw"] > 0
    assert "narrative" not in integrated.data


async def test_a_repeat_of_the_same_conditions_calls_no_model_at_all():
    # 가드 2 — 같은 조건이면 저장분을 돌려준다. 모델을 다시 부르면 답이 달라질 수 있다.
    responder = ScriptedResponder(__text__="요약")
    agent = main_agent(responder)
    await agent.run(CONDITIONS, LISTINGS)
    spent = len(responder.calls)
    second = await agent.run(CONDITIONS, LISTINGS)
    assert second.reused is True
    assert len(responder.calls) == spent


#: 상한을 실제로 넘겨 보려면 부를 축이 있어야 한다. 밴드·스트레스가 커널로 내려간 뒤로는
#: 조회 축(공시·공고)만 모델을 부르므로, 예산 시험은 그 둘을 실제로 채워 놓고 한다.
LOOKUPS = dict(kb_products=[{"id": "p1", "name": "사업자대출", "category": "BUSINESS_LOAN"}],
               programs=[{"id": "n1", "title": "창업지원"}])


def budgeted_agent(responder, max_calls):
    reasoner = AgentLLM(responder, budget=RunBudget(max_calls=max_calls))
    return MainAgent(conditions=ConditionLayer(llm=reasoner),
                     finance=FinanceTeam(FULL, llm=reasoner, **LOOKUPS),
                     location=LocationTeam(llm=reasoner), timing=TimingTeam(llm=reasoner),
                     llm=reasoner, budget=reasoner.budget)


async def test_one_run_never_exceeds_the_call_budget():
    responder = ScriptedResponder(__text__="요약")
    # 부르려는 축은 셋(공시·공고·설명문)인데 상한은 둘이다.
    agent = budgeted_agent(responder, max_calls=2)
    result = await agent.run(CONDITIONS, LISTINGS)
    assert len(responder.calls) == 2
    # 상한을 넘긴 것은 에러가 아니라 부분 결과다 — 실행은 끝까지 가고 12개가 모두 보고한다.
    assert len([item for report in result.reports for item in report.outcomes]) == 12


async def test_the_budget_starts_over_when_the_conditions_change():
    responder = ScriptedResponder(__text__="요약")
    agent = budgeted_agent(responder, max_calls=2)
    await agent.run(CONDITIONS, LISTINGS)
    await agent.run({**CONDITIONS, "equity_krw": 200_000_000}, LISTINGS)
    # 상한은 케이스 평생이 아니라 실행 한 번의 것이다.
    assert len(responder.calls) == 4
