"""메인 에이전트 — 제안서 04장의 실행 순서와 게이트를 고정한다.

  조건 확정 → 금융처방(후보 무관 1회) → 권장 밴드로 자동 진행 → 입지추천 → 축소 → 타이밍(잔존만)

게이트는 두 개다. 조건이 덜 차면 후보를 만들지 않고, 밴드를 못 그리면 후속 전체가 멈춘다.
메인 계약 — 수치 카드만 표시하고 설명문을 지어내지 않는다.
"""
from app.agents.conditions import ConditionLayer
from app.agents.contracts import AgentStatus
from app.agents.finance import FinanceTeam
from app.agents.location import LocationTeam
from app.agents.orchestrator import MainAgent
from app.agents.timing import TimingTeam
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

CONDITIONS = {"industry": "카페", "district": "강남구", "area_pyeong": 15.0,
              "deposit_krw": 100_000_000, "monthly_rent_krw": 2_500_000,
              "monthly_maintenance_krw": 300_000, "key_money_krw": 0, "fitout_krw": None,
              "equity_krw": 100_000_000, "existing_debt_krw": 0,
              "other_monthly_fixed_krw": 1_000_000}

CANDIDATES = [{"id": "l1", "name": "OO동 1층", "admin_dong": "역삼1동", "monthly_rent_krw": 2_500_000},
              {"id": "l2", "name": "△△동 2층", "admin_dong": "삼성2동", "monthly_rent_krw": 1_900_000}]


class CountingTiming(TimingTeam):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.saw = None

    def run(self, candidates, decision=None):
        self.calls += 1
        self.saw = [item["id"] for item in candidates]
        return super().run(candidates, decision)


def agent(params=FULL, *, timing=None, location=None):
    return MainAgent(conditions=ConditionLayer(),
                     finance=FinanceTeam(params, kb_products=[], programs=[]),
                     location=location or LocationTeam(),
                     timing=timing or TimingTeam())


async def test_a_complete_run_reports_every_team_in_order():
    result = await agent().run(CONDITIONS, CANDIDATES)
    assert [report.team for report in result.reports] == ["condition", "finance", "location", "timing", "main"]


async def test_unsettled_conditions_stop_before_the_finance_team_runs():
    result = await agent().run({**CONDITIONS, "industry": ""}, CANDIDATES)
    assert [report.team for report in result.reports] == ["condition", "main"]
    assert result.halted_at == "condition"
    assert result.questions
    assert result.surviving == []


async def test_a_missing_band_stops_before_the_location_team_runs():
    # 팀 계약 — 기준선 없이는 후보를 판정할 수 없으므로 후속 전체 중단.
    result = await agent(EMPTY).run(CONDITIONS, CANDIDATES)
    assert [report.team for report in result.reports] == ["condition", "finance", "main"]
    assert result.halted_at == "finance"
    assert result.surviving == []


async def test_the_timing_team_only_sees_surviving_candidates():
    timing = CountingTiming()
    dropping = LocationTeam(stress_check=lambda candidate: {"passes": candidate["id"] != "l1",
                                                            "runway_months": 6})
    result = await agent(timing=timing, location=dropping).run(CONDITIONS, CANDIDATES)
    assert timing.saw == ["l2"]
    assert [item["id"] for item in result.surviving] == ["l2"]
    assert result.dropped[0]["id"] == "l1"


async def test_the_finance_team_runs_once_regardless_of_candidate_count():
    result = await agent().run(CONDITIONS, CANDIDATES)
    finance = next(report for report in result.reports if report.team == "finance")
    assert len([item for item in finance.outcomes if item.key == "finance.band"]) == 1


async def test_the_run_reports_how_many_of_the_twelve_agents_are_active():
    result = await agent().run(CONDITIONS, CANDIDATES)
    assert result.activation["total"] == 12
    # 조건 2 + 밴드 + 스트레스 + 메인 통합 = 5. 상권·생존·타이밍·KB·지원금은 원천이 없다.
    assert result.activation["active"] == 5
    assert result.activation["by_key"]["location.demand"] == AgentStatus.INTEGRATION_PENDING


async def test_an_identical_run_is_served_from_the_previous_result():
    # 가드 2 — 동일 조건 재조회 시 재실행하지 않는다.
    timing = CountingTiming()
    main = agent(timing=timing)
    first = await main.run(CONDITIONS, CANDIDATES)
    second = await main.run(CONDITIONS, CANDIDATES)
    assert timing.calls == 1
    assert second.reused is True
    assert first.fingerprint == second.fingerprint


async def test_changed_conditions_force_a_rerun():
    timing = CountingTiming()
    main = agent(timing=timing)
    await main.run(CONDITIONS, CANDIDATES)
    await main.run({**CONDITIONS, "equity_krw": 200_000_000}, CANDIDATES)
    assert timing.calls == 2


async def test_the_summary_only_repeats_numbers_the_teams_produced():
    result = await agent().run(CONDITIONS, CANDIDATES)
    band = next(report for report in result.reports if report.team == "finance")
    lines = next(item for item in band.outcomes if item.key == "finance.band").data["bands"]
    assert result.summary["recommended_ceiling_krw"] == lines[1]["ceiling_krw"]
    assert result.summary["target_monthly_revenue_krw"] == lines[1]["target_monthly_revenue_krw"]


async def test_the_summary_is_empty_when_the_run_halted():
    result = await agent(EMPTY).run(CONDITIONS, CANDIDATES)
    assert result.summary == {}


async def test_the_main_agent_reports_its_own_integration_as_the_twelfth_outcome():
    # 메인도 일을 한다 — 팀 보고를 모아 수치 카드를 만든다. 그 결과를 스스로 내지 않으면
    # 화면에는 11개만 도착하고 12번째 칸이 영원히 비어 있게 된다.
    result = await agent().run(CONDITIONS, CANDIDATES)
    keys = [item.key for report in result.reports for item in report.outcomes]
    assert keys[-1] == "main.integrate"
    assert len(keys) == 12


async def test_the_main_agent_marks_itself_withheld_when_the_run_halted():
    result = await agent(EMPTY).run(CONDITIONS, CANDIDATES)
    main = [item for report in result.reports for item in report.outcomes if item.key == "main.integrate"]
    assert len(main) == 1
    assert main[0].status is AgentStatus.WITHHELD
    assert main[0].message


async def test_the_integration_outcome_carries_the_same_numbers_as_the_summary():
    result = await agent().run(CONDITIONS, CANDIDATES)
    main = next(item for report in result.reports for item in report.outcomes if item.key == "main.integrate")
    assert main.data["summary"] == result.summary
    assert main.data["surviving_count"] == len(result.surviving)
