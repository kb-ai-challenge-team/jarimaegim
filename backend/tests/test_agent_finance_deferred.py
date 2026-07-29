"""희망 월세가 없을 때 금융 축이 무엇을 내는가.

여력(자기자본선·차입 여력·최대 조달선)은 금융 프로필만으로 나온다 — `compute_capacity` 가
업종도 월세도 읽지 않기 때문이다. 권장 조달선과 손익분기만 월세를 요구한다. 그래서 월세가
없으면 밴드를 통째로 유보하는 대신 여력만 싣고 무엇을 못 냈는지 밝힌다.

유보(`WITHHELD`)로 반환하면 여력 커널 실패로 읽혀 실행 전체가 멈추고, 그러면
"이 자리에 손님이 있나" 까지 월세 입력을 기다리게 된다. 그것이 M0 가 없애려는 상태다.
"""
from app.agents.contracts import AgentStatus
from app.agents.finance import FinanceTeam
from app.agents.orchestrator import capacity_failed
from app.policy_params import PolicyParams

# `test_agent_finance.py` 와 같은 인라인 파라미터를 쓴다 — 저장소의 실제 파일을 읽으면
# 시연용 가정값이 바뀔 때마다 이 테스트가 같이 흔들린다.
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

BASE = {"industry": "카페", "district": "마포구", "equity_krw": 50_000_000,
        "existing_debt_krw": 0, "other_monthly_fixed_krw": 0,
        "monthly_maintenance_krw": 0, "key_money_krw": 0,
        "area_pyeong": None, "deposit_krw": None, "fitout_krw": None}


def team(params=FULL):
    return FinanceTeam(params, kb_products=[], programs=[])


def band_of(report):
    return next(item for item in report.outcomes if item.key == "finance.band")


def test_without_a_rent_the_band_agent_still_reports_ok():
    outcome = band_of(team().run({**BASE, "monthly_rent_krw": None}))
    assert outcome.status is AgentStatus.OK


def test_without_a_rent_the_run_is_not_halted():
    """이것이 M0 의 핵심 단언이다."""
    assert capacity_failed(team().run({**BASE, "monthly_rent_krw": None})) is False


def test_without_a_rent_the_capacity_lines_are_still_produced():
    data = band_of(team().run({**BASE, "monthly_rent_krw": None})).data
    assert data["capacity"]["equity_line_krw"] == 50_000_000
    assert data["capacity"]["maximum_line_krw"] >= 50_000_000


def test_without_a_rent_no_recommended_ceiling_is_invented():
    """월세 0 으로 계산하면 손익분기가 과소 산출되고 목표매출이 낮게 나온다."""
    data = band_of(team().run({**BASE, "monthly_rent_krw": None})).data
    assert data["bands"] == []
    assert data["deferred"] == ["monthly_rent_krw"]


def test_the_deferred_reason_is_stated_rather_than_left_blank():
    outcome = band_of(team().run({**BASE, "monthly_rent_krw": None}))
    assert "희망 월세" in outcome.message


def test_with_a_rent_the_bands_come_back_exactly_as_before():
    data = band_of(team().run({**BASE, "monthly_rent_krw": 2_500_000})).data
    assert data["deferred"] == []
    assert {line["band"] for line in data["bands"]} == {"EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"}


def test_the_capacity_is_carried_even_when_the_bands_are_computed():
    """화면이 여력과 밴드를 한 곳에서 읽도록 두 경우 모두 같은 키를 싣는다."""
    data = band_of(team().run({**BASE, "monthly_rent_krw": 2_500_000})).data
    assert data["capacity"]["maximum_line_krw"] == data["bands"][-1]["ceiling_krw"]


def test_the_stress_axis_withholds_rather_than_reading_an_absent_band():
    """스트레스는 밴드 산출물을 읽는 축이다. 읽을 것이 없으면 유보다."""
    report = team().run({**BASE, "monthly_rent_krw": None})
    stress = next(item for item in report.outcomes if item.key == "finance.stress")
    assert stress.status is AgentStatus.WITHHELD


def test_unregistered_parameters_still_win_over_a_deferred_rent():
    """원천이 없으면 여력조차 낼 수 없다. 유보보다 연동 대기가 먼저다."""
    outcome = band_of(team(EMPTY).run({**BASE, "monthly_rent_krw": None}))
    assert outcome.status is AgentStatus.INTEGRATION_PENDING
