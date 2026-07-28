"""금융처방 팀에서 **모델이 남아 있는 두 축**.

  finance.kb_products  공시 문구를 읽고 상품 선별
  finance.subsidy      공고 본문 대조로 관련 공고 선별

밴드와 스트레스는 여기 없다 — 둘 다 커널로 내려가 모델이 낄 자리가 없어졌다. 그 계약은
`test_agent_finance_kernel.py` 가 더 강하게 고정한다: 술어는 코드가 전량 평가하고, 시나리오는
카탈로그 3종을 항상 전부 돌린다.

남은 둘은 공시의 한도·가입방법과 공고 본문이 **문장**이라 구조화 비교가 안 되는 경우다.
읽는 일은 모델이 하되 **id 만 고르고**, 결과로 나가는 행은 원천의 값 그대로다. 모델이
"이 상품 한도는 5억입니다" 같은 문장을 내도 그 문장이 들어갈 자리가 없다.
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


# ── finance.stress — 시나리오 카탈로그에서 고른다 ──────────────────────────


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


