"""금융처방 팀의 추론.

  finance.band         적용할 제도 파라미터 확인 · 입력 이상치 감지 시 유보 판단
  finance.stress       이 케이스에 유의미한 시나리오 선택
  finance.kb_products  공시 문구를 읽고 상품 선별
  finance.subsidy      공고 본문 대조로 관련 공고 선별

산술은 전부 `funding.compute_bands` 가 한다. 모델은 **무엇을 적용할지**만 고르고, 골라도
코드가 다시 검증한다 — 이상치는 코드가 술어로 확인하고, 상품·공고는 실제로 존재하는 id 만
통과한다. 모델이 "이 상권 폐업률은 12%입니다" 같은 문장을 내도 그 문장이 들어갈 자리가 없다.
"""
from app.agents.contracts import AgentStatus
from app.agents.finance import ANOMALY_MESSAGES, FinanceTeam, STRESS_SCENARIOS
from app.agents.llm import AgentLLM, RunBudget
from app.policy_params import PolicyParams

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

CONDITIONS = dict(industry="카페", area_pyeong=15.0, deposit_krw=100_000_000,
                  monthly_rent_krw=2_500_000, monthly_maintenance_krw=300_000, key_money_krw=0,
                  fitout_krw=None, equity_krw=100_000_000, existing_debt_krw=0,
                  other_monthly_fixed_krw=1_000_000)


class ScriptedResponder:
    """도구 이름별로 무엇을 돌려줄지 정해 둔다. 없으면 아무것도 고르지 않은 것으로 답한다."""

    def __init__(self, **by_schema):
        self.by_schema, self.calls = by_schema, []

    async def respond(self, messages, tools, **options):
        name = tools[0]["name"]
        self.calls.append(name)
        arguments = self.by_schema.get(name)
        if arguments is None:
            return {"text": "", "tool_calls": []}
        return {"text": "", "tool_calls": [{"id": "c", "name": name, "arguments": arguments}]}


def team(params=FULL, *, kb_products=None, programs=None, responder=None):
    llm = AgentLLM(responder, budget=RunBudget()) if responder is not None else None
    return FinanceTeam(params, kb_products=kb_products or [], programs=programs or [], llm=llm)


def outcome(report, key):
    return next(item for item in report.outcomes if item.key == key)


# ── finance.band — 이상치는 모델이 말하고 코드가 확인한다 ──────────────────

async def test_an_anomaly_the_code_cannot_confirm_is_discarded():
    # 모델이 "보증금이 자기자본을 넘는다"고 해도 실제로 넘지 않으면 유보 근거가 되지 못한다.
    responder = ScriptedResponder(review_band_inputs={"verdict": "withhold",
                                                      "anomalies": ["DEPOSIT_EXCEEDS_EQUITY"]})
    report = await team(responder=responder).arun(CONDITIONS)
    band = outcome(report, "finance.band")
    assert band.status is AgentStatus.OK
    assert band.data["decision"]["rejected"] == [
        {"field": "anomalies", "value": "DEPOSIT_EXCEEDS_EQUITY", "reason": "predicate_false"}]


async def test_a_confirmed_anomaly_with_a_withhold_verdict_stops_the_run():
    conditions = {**CONDITIONS, "deposit_krw": 300_000_000}
    responder = ScriptedResponder(review_band_inputs={"verdict": "withhold",
                                                      "anomalies": ["DEPOSIT_EXCEEDS_EQUITY"]})
    report = await team(responder=responder).arun(conditions)
    band = outcome(report, "finance.band")
    assert band.status is AgentStatus.WITHHELD
    assert band.message == ANOMALY_MESSAGES["DEPOSIT_EXCEEDS_EQUITY"]
    assert report.halted is True


async def test_a_confirmed_anomaly_without_a_withhold_verdict_is_reported_but_does_not_stop():
    # 이상치가 있다는 사실과 판정을 멈춘다는 결정은 다르다. 자동으로 멈추면 축이 늘수록 탈락이 는다.
    conditions = {**CONDITIONS, "deposit_krw": 300_000_000}
    responder = ScriptedResponder(review_band_inputs={"verdict": "proceed",
                                                      "anomalies": ["DEPOSIT_EXCEEDS_EQUITY"]})
    report = await team(responder=responder).arun(conditions)
    band = outcome(report, "finance.band")
    assert band.status is AgentStatus.OK
    assert band.data["anomalies"] == ["DEPOSIT_EXCEEDS_EQUITY"]
    assert band.data["bands"][1]["ceiling_krw"] > 0


async def test_withholding_never_invents_its_own_sentence():
    # 유보 사유는 코드가 가진 고정 문장이다. 모델 문장을 그대로 실으면 그 문장이 근거가 된다.
    conditions = {**CONDITIONS, "deposit_krw": 300_000_000}
    responder = ScriptedResponder(review_band_inputs={"verdict": "withhold",
                                                      "anomalies": ["DEPOSIT_EXCEEDS_EQUITY"]})
    report = await team(responder=responder).arun(conditions)
    assert outcome(report, "finance.band").message in ANOMALY_MESSAGES.values()


async def test_missing_parameters_are_still_decided_before_any_model_call():
    # 가드 3 — 원천(제도 파라미터)이 없으면 판정 자체를 하지 않는다. 모델을 부를 일도 없다.
    responder = ScriptedResponder(review_band_inputs={"verdict": "proceed", "anomalies": []})
    report = await team(EMPTY, responder=responder).arun(CONDITIONS)
    assert outcome(report, "finance.band").status is AgentStatus.INTEGRATION_PENDING
    assert "review_band_inputs" not in responder.calls


async def test_the_band_numbers_are_identical_with_and_without_the_model():
    # 모델은 무엇을 적용할지만 고른다. 같은 조건이면 같은 수치가 나와야 한다.
    responder = ScriptedResponder(review_band_inputs={"verdict": "proceed", "anomalies": []})
    with_model = await team(responder=responder).arun(CONDITIONS)
    without = team().run(CONDITIONS)
    assert outcome(with_model, "finance.band").data["bands"] == outcome(without, "finance.band").data["bands"]


# ── finance.stress — 시나리오 카탈로그에서 고른다 ──────────────────────────

async def test_the_model_selects_scenarios_and_the_code_computes_them():
    responder = ScriptedResponder(select_stress_scenarios={"scenarios": ["REVENUE_DROP_30"]})
    report = await team(responder=responder).arun(CONDITIONS)
    stress = outcome(report, "finance.stress")
    assert [item["key"] for item in stress.data["scenarios"]] == ["REVENUE_DROP_30"]
    assert stress.data["scenarios"][0]["label"] == STRESS_SCENARIOS["REVENUE_DROP_30"]["label"]
    assert isinstance(stress.data["scenarios"][0]["recommended_passes_stress"], bool)


async def test_a_scenario_outside_the_catalogue_never_runs():
    responder = ScriptedResponder(select_stress_scenarios={"scenarios": ["매출 반토막"]})
    report = await team(responder=responder).arun(CONDITIONS)
    stress = outcome(report, "finance.stress")
    assert stress.data["scenarios"] == []
    assert stress.data["decision"]["rejected"][0]["reason"] == "not_offered"


async def test_the_baseline_stress_result_survives_whatever_the_model_picks():
    # 권장 조달선의 정의 자체가 기준 시나리오 통과다. 모델 선택이 그것을 지우면 안 된다.
    responder = ScriptedResponder(select_stress_scenarios={"scenarios": ["RATE_PLUS_1PP"]})
    report = await team(responder=responder).arun(CONDITIONS)
    stress = outcome(report, "finance.stress")
    assert stress.data["recommended_passes_stress"] is True
    assert stress.data["revenue_drop_ratio"] == 0.2


async def test_a_harsher_scenario_is_never_easier_to_pass():
    responder = ScriptedResponder(select_stress_scenarios={"scenarios": ["REVENUE_DROP_20", "REVENUE_DROP_30"]})
    report = await team(responder=responder).arun(CONDITIONS)
    rows = {item["key"]: item for item in outcome(report, "finance.stress").data["scenarios"]}
    assert rows["REVENUE_DROP_30"]["recommended_ceiling_krw"] <= rows["REVENUE_DROP_20"]["recommended_ceiling_krw"]


# ── finance.kb_products · finance.subsidy — id 로만 고른다 ────────────────

PRODUCTS = [{"id": "kb1", "name": "KB소호대출", "category": "BUSINESS_LOAN", "rate_avg": 6.2,
             "loan_limit": "최대 5억원", "join_way": "영업점", "official_url": "https://example.kr/1"},
            {"id": "kb2", "name": "KB사업자우대", "category": "BUSINESS_LOAN", "rate_avg": 5.4,
             "loan_limit": "신용등급별 차등", "join_way": "인터넷", "official_url": "https://example.kr/2"}]

NOTICES = [{"id": "p1", "title": "청년창업 지원", "organization": "서울시", "regions": None,
            "match_text": "서울특별시 소재 청년 소상공인 대상", "official_url": "https://example.kr/p1"},
           {"id": "p2", "title": "농어촌 정착 지원", "organization": "농림부", "regions": None,
            "match_text": "농어촌 지역 귀농인 대상", "official_url": "https://example.kr/p2"}]


async def test_the_model_narrows_disclosed_products_but_the_rows_stay_verbatim():
    responder = ScriptedResponder(select_kb_products={"selected": ["kb2"]})
    report = await team(kb_products=PRODUCTS, responder=responder).arun(CONDITIONS)
    kb = outcome(report, "finance.kb_products")
    assert [item["id"] for item in kb.data["disclosed"]] == ["kb2"]
    assert kb.data["disclosed"][0]["rate_avg"] == 5.4
    assert kb.data["mix_simulated"] is False


async def test_a_product_id_that_does_not_exist_is_ignored_rather_than_created():
    responder = ScriptedResponder(select_kb_products={"selected": ["kb9"]})
    report = await team(kb_products=PRODUCTS, responder=responder).arun(CONDITIONS)
    kb = outcome(report, "finance.kb_products")
    assert [item["id"] for item in kb.data["disclosed"]] == ["kb1", "kb2"]


async def test_the_model_marks_which_notices_matched_the_body_text():
    responder = ScriptedResponder(select_subsidy_notices={"relevant": ["p1"]})
    report = await team(programs=NOTICES, responder=responder).arun(CONDITIONS)
    subsidy = outcome(report, "finance.subsidy")
    assert [item["id"] for item in subsidy.data["notices"] if item["relevant"]] == ["p1"]


async def test_selecting_notices_still_lifts_the_ceiling_by_nothing():
    # 공고 본문에 지원 규모가 구조화 필드로 없다는 사실은 모델이 붙어도 그대로다.
    responder = ScriptedResponder(select_subsidy_notices={"relevant": ["p1", "p2"]})
    report = await team(programs=NOTICES, responder=responder).arun(CONDITIONS)
    subsidy = outcome(report, "finance.subsidy")
    assert subsidy.status is AgentStatus.INTEGRATION_PENDING
    assert subsidy.data["uplift_krw"] == 0


async def test_an_empty_notice_index_does_not_call_the_model():
    responder = ScriptedResponder()
    await team(responder=responder).arun(CONDITIONS)
    assert "select_subsidy_notices" not in responder.calls
    assert "select_kb_products" not in responder.calls


# ── 결정론 경로는 그대로 ──────────────────────────────────────────────────

def test_the_synchronous_path_needs_no_model():
    report = team(kb_products=PRODUCTS, programs=NOTICES).run(CONDITIONS)
    assert outcome(report, "finance.band").status is AgentStatus.OK
    assert [item["id"] for item in outcome(report, "finance.kb_products").data["disclosed"]] == ["kb1", "kb2"]


# ── 유보할 수 있는 이상치와, 보여 주기만 하는 이상치 ─────────────────────────
# 화면이 그리도록 설계된 상태(최대 조달선의 스트레스 실패, 필요자금 초과)는 이상치로 표시는
# 하되 판정을 멈출 근거가 되지 못한다. 그것을 멈춤으로 바꾸면 제품이 보여 주기로 한 것을
# 모델의 그날 판단이 덮어쓰게 된다.

async def test_a_displayed_state_is_reported_but_can_never_halt_the_run():
    # 최대 조달선이 스트레스를 통과하지 못하는 것은 정상이고, 밴드 표가 그대로 보여 주는 값이다.
    conditions = {**CONDITIONS, "equity_krw": 20_000_000, "monthly_rent_krw": 6_000_000}
    responder = ScriptedResponder(review_band_inputs={"verdict": "withhold",
                                                      "anomalies": ["MAXIMUM_FAILS_STRESS"]})
    report = await team(responder=responder).arun(conditions)
    band = outcome(report, "finance.band")
    assert band.status is AgentStatus.OK
    assert band.data["anomalies"] == ["MAXIMUM_FAILS_STRESS"]
    assert report.halted is False


async def test_an_input_contradiction_can_still_halt_the_run():
    # 보증금이 자기자본을 넘는 것은 화면이 그리기로 한 상태가 아니라 입력이 어긋난 것이다.
    conditions = {**CONDITIONS, "deposit_krw": 300_000_000}
    responder = ScriptedResponder(review_band_inputs={"verdict": "withhold",
                                                      "anomalies": ["DEPOSIT_EXCEEDS_EQUITY"]})
    report = await team(responder=responder).arun(conditions)
    assert outcome(report, "finance.band").status is AgentStatus.WITHHELD


async def test_a_withholdable_anomaly_mixed_with_a_displayed_one_still_withholds():
    conditions = {**CONDITIONS, "deposit_krw": 300_000_000, "equity_krw": 20_000_000}
    responder = ScriptedResponder(review_band_inputs={
        "verdict": "withhold", "anomalies": ["MAXIMUM_FAILS_STRESS", "DEPOSIT_EXCEEDS_EQUITY"]})
    report = await team(responder=responder).arun(conditions)
    band = outcome(report, "finance.band")
    assert band.status is AgentStatus.WITHHELD
    # 유보 사유는 유보 가능한 이상치에서 나와야 한다. 보여 주기용 상태를 사유로 적으면 안 된다.
    assert band.message == ANOMALY_MESSAGES["DEPOSIT_EXCEEDS_EQUITY"]
