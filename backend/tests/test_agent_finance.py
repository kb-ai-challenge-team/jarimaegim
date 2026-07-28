"""얼마 — 금융처방 팀. 제안서 04장의 팀 계약을 고정한다.

  산출물   조달 밴드 3중선 · 손익분기선
  실패 시  후속 전체 중단 — 기준선 없이는 후보를 판정할 수 없다
"""
import pytest
from app.agents.contracts import AgentStatus
from app.agents.finance import FinanceTeam
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

# 지금 저장소의 실제 상태 — 4개 항목이 비어 있다.
PARTIAL = PolicyParams({
    "updated_at": "2026-07-27",
    "entries": {
        "loan.annual_rate_percent": {"value": 4.45, "source": "소진공"},
        "loan.term_months": {"value": None},
        "loan.guarantee_ceiling_krw": {"value": None},
        "loan.policy_fund_ceiling_krw": {"value": None},
        "stress.revenue_drop_ratio": {"value": 0.2, "source": "설계"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "source": "설계"},
        "working_capital.months": {"value": 3, "source": "설계"},
    },
    "industries": {},
})

CONDITIONS = dict(industry="카페", area_pyeong=15.0, deposit_krw=100_000_000,
                  monthly_rent_krw=2_500_000, monthly_maintenance_krw=300_000, key_money_krw=0,
                  fitout_krw=None, equity_krw=100_000_000, existing_debt_krw=0,
                  other_monthly_fixed_krw=1_000_000)


def team(params=FULL, *, kb_products=None, programs=None):
    return FinanceTeam(params, kb_products=kb_products or [], programs=programs or [])


def test_the_team_runs_all_four_of_its_sub_agents():
    report = team().run(CONDITIONS)
    assert [item.key for item in report.outcomes] == [
        "finance.band", "finance.stress", "finance.kb_products", "finance.subsidy"]


def test_the_band_agent_produces_the_three_lines_and_a_breakeven():
    report = team().run(CONDITIONS)
    band = next(item for item in report.outcomes if item.key == "finance.band")
    assert band.status is AgentStatus.OK
    assert [line["band"] for line in band.data["bands"]] == ["EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"]
    assert band.data["bands"][1]["target_monthly_revenue_krw"] > 0


def test_the_band_agent_reports_missing_parameters_instead_of_estimating():
    report = team(PARTIAL).run(CONDITIONS)
    band = next(item for item in report.outcomes if item.key == "finance.band")
    assert band.status is AgentStatus.INTEGRATION_PENDING
    assert "loan.term_months" in band.data["missing_params"]
    assert "industries.카페" in band.data["missing_params"]


def test_the_team_blocks_everything_downstream_when_the_band_cannot_be_drawn():
    # 제안서 04장 팀 계약 — 금융처방 실패는 후속 전체 중단이다.
    report = team(PARTIAL).run(CONDITIONS)
    assert report.blocking is True
    assert report.halted is True


def test_a_drawable_band_does_not_halt_the_run():
    report = team().run(CONDITIONS)
    assert report.blocking is True
    assert report.halted is False


def test_the_stress_agent_reuses_the_band_computation_rather_than_recomputing():
    # 가드 2 — 동일 조건에서 재실행하지 않는다. 권장 조달선은 스트레스를 통과하는 최대치이므로
    # 스트레스 결과는 밴드 산출물 안에 이미 있다.
    report = team().run(CONDITIONS)
    stress = next(item for item in report.outcomes if item.key == "finance.stress")
    assert stress.status is AgentStatus.OK
    assert stress.data["recommended_passes_stress"] is True
    assert stress.data["revenue_drop_ratio"] == 0.2


def test_the_stress_agent_is_pending_when_the_band_is():
    report = team(PARTIAL).run(CONDITIONS)
    stress = next(item for item in report.outcomes if item.key == "finance.stress")
    assert stress.status is AgentStatus.INTEGRATION_PENDING


def test_the_subsidy_agent_refuses_to_lift_the_ceiling_without_a_structured_amount():
    # 공고에는 지원 규모가 구조화 필드로 없다 (models 의 Program 에 금액 필드가 없다).
    # 금액을 본문에서 추측해 조달선을 올리면 그것이 곧 날조다.
    notices = [{"id": "p1", "title": "청년창업 지원", "organization": "서울시",
                "official_url": "https://example.kr/1"}]
    report = team(programs=notices).run(CONDITIONS)
    subsidy = next(item for item in report.outcomes if item.key == "finance.subsidy")
    assert subsidy.status is AgentStatus.INTEGRATION_PENDING
    assert subsidy.data["notice_count"] == 1
    assert subsidy.data["uplift_krw"] == 0


def test_the_subsidy_agent_never_changes_the_band_ceilings():
    notices = [{"id": "p1", "title": "청년창업 지원", "organization": "서울시",
                "official_url": "https://example.kr/1"}]
    with_notices = team(programs=notices).run(CONDITIONS)
    without = team().run(CONDITIONS)
    left = next(i for i in with_notices.outcomes if i.key == "finance.band").data["bands"]
    right = next(i for i in without.outcomes if i.key == "finance.band").data["bands"]
    assert left == right


def test_the_kb_products_agent_quotes_disclosed_rates_but_does_not_simulate_a_mix():
    products = [{"id": "kb1", "name": "KB소호대출", "category": "BUSINESS_LOAN",
                 "rate_min": 5.1, "rate_max": 7.4, "rate_avg": 6.2,
                 "loan_limit": "최대 5억원", "official_url": "https://example.kr/kb"}]
    report = team(kb_products=products).run(CONDITIONS)
    kb = next(item for item in report.outcomes if item.key == "finance.kb_products")
    assert kb.status is AgentStatus.OK
    assert kb.data["disclosed"][0]["rate_avg"] == 6.2
    # 밴드가 쓴 정책자금 금리와 나란히 놓기만 한다.
    assert kb.data["policy_rate_percent"] == 4.45
    assert kb.data["mix_simulated"] is False


def test_the_kb_products_agent_is_pending_with_an_empty_index():
    report = team(kb_products=[]).run(CONDITIONS)
    kb = next(item for item in report.outcomes if item.key == "finance.kb_products")
    assert kb.status is AgentStatus.INTEGRATION_PENDING


def test_business_loans_only_consumer_products_are_not_startup_funding():
    products = [{"id": "kb2", "name": "KB주택담보대출", "category": "MORTGAGE_LOAN",
                 "rate_min": 3.1, "rate_max": 4.4, "rate_avg": 3.8,
                 "official_url": "https://example.kr/kb2"}]
    report = team(kb_products=products).run(CONDITIONS)
    kb = next(item for item in report.outcomes if item.key == "finance.kb_products")
    assert kb.status is AgentStatus.INTEGRATION_PENDING


def test_an_impossible_industry_margin_is_withheld_not_crashed():
    broken = PolicyParams({
        "updated_at": "2026-07-27",
        "entries": FULL._entries,
        "industries": {"적자업종": {"cogs_ratio": 0.7, "labor_ratio": 0.4,
                                  "fitout_krw_per_pyeong": 1_000_000,
                                  "operating_days_per_month": 26}},
    })
    report = FinanceTeam(broken, kb_products=[], programs=[]).run({**CONDITIONS, "industry": "적자업종"})
    band = next(item for item in report.outcomes if item.key == "finance.band")
    assert band.status is AgentStatus.WITHHELD
    assert band.message
