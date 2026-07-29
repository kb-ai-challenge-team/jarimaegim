"""조달 밴드와 스트레스는 커널이다 — 모델이 끼지 않는다.

예전에는 모델이 이상치를 **지목**하고 코드가 그 지목만 술어로 확인했다. 그 구조에서 모델이
고르지 않은 이상치는 술어가 참이어도 아무 데도 기록되지 않았다. 즉 그 호출은 재현율을
떨어뜨리는 필터로만 작동했고, 놓친 이상치는 화면에도 감사 기록에도 남지 않았다.

지금은 코드가 5종을 **전량 평가**한다. 모델이 무엇을 고르든 관계없고, 애초에 이 축에서는
모델을 부르지 않는다. 시나리오도 마찬가지다 — 3종을 항상 전부 돌린다. 무엇을 확인할
가치가 있는지는 케이스마다 달라지는 판단이 아니라 제품이 약속한 목록이다.

유보(WITHHELD)는 이상치로 일어나지 않는다. 보증금이 자기자본을 넘는 것은 정상 상황이고
(보증금을 조달하려고 대출을 받는다), 그것으로 실행을 멈추면 흔한 입력에서 아무 표도 못 본 채
멈춘다. 이상치는 전부 화면이 그리도록 표시로만 내보낸다.
"""
from app.agents.contracts import AgentStatus
from app.agents.finance import ANOMALY_PREDICATES, FinanceTeam, STRESS_SCENARIOS, WITHHOLDABLE
from app.agents.orchestrator import capacity_failed
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

CONDITIONS = dict(industry="카페", area_pyeong=15.0, deposit_krw=100_000_000,
                  monthly_rent_krw=2_500_000, monthly_maintenance_krw=300_000, key_money_krw=0,
                  fitout_krw=None, equity_krw=100_000_000, existing_debt_krw=0,
                  other_monthly_fixed_krw=1_000_000)


class CountingResponder:
    """무엇을 몇 번 불렀는지만 센다. 아무것도 고르지 않은 것으로 답한다."""

    def __init__(self):
        self.calls = []

    async def respond(self, messages, tools, **options):
        self.calls.append(tools[0]["name"])
        return {"text": "", "tool_calls": []}


def team(params=FULL, *, kb_products=None, programs=None, responder=None):
    llm = AgentLLM(responder, budget=RunBudget()) if responder is not None else None
    return FinanceTeam(params, kb_products=kb_products or [], programs=programs or [], llm=llm)


def outcome(report, key):
    return next(item for item in report.outcomes if item.key == key)


# ── 이상치는 코드가 전량 평가한다 ─────────────────────────────────────────

async def test_a_true_predicate_is_recorded_even_though_no_model_selected_it():
    """이것이 M2 의 핵심이다. 예전 구조에서는 모델이 지목하지 않은 이상치가 술어가 참이어도
    사라졌다 — 놓친 이상치가 화면에도 감사 기록에도 남지 않는 것이 그 호출의 실제 효과였다."""
    responder = CountingResponder()  # 아무것도 고르지 않는다
    conditions = {**CONDITIONS, "deposit_krw": 200_000_000, "equity_krw": 100_000_000}
    report = await team(responder=responder).arun(conditions)
    assert "DEPOSIT_EXCEEDS_EQUITY" in outcome(report, "finance.band").data["anomalies"]


async def test_every_predicate_is_evaluated_not_just_the_observed_ones():
    """관찰 여부와 무관하게 5종 전부에 대한 판정이 남는다. 평가하지 않은 것과 거짓인 것은
    다른 말이고, 감사에서 그 둘을 구분할 수 없으면 기록이 아니다."""
    report = await team(responder=CountingResponder()).arun(CONDITIONS)
    evaluated = outcome(report, "finance.band").data["anomaly_checks"]
    assert set(evaluated) == set(ANOMALY_PREDICATES)
    assert all(isinstance(value, bool) for value in evaluated.values())


def test_the_deterministic_path_evaluates_the_predicates_too():
    """모델이 아예 없을 때도 같은 판정이 나온다 — 이 축에는 모델 경로가 없기 때문이다."""
    conditions = {**CONDITIONS, "deposit_krw": 200_000_000, "equity_krw": 100_000_000}
    data = outcome(team().run(conditions), "finance.band").data
    assert "DEPOSIT_EXCEEDS_EQUITY" in data["anomalies"]


def test_a_false_predicate_never_becomes_an_anomaly():
    data = outcome(team().run(CONDITIONS), "finance.band").data
    assert "DEPOSIT_EXCEEDS_EQUITY" not in data["anomalies"]


# ── 이상치는 실행을 멈추지 않는다 ─────────────────────────────────────────

def test_nothing_is_withholdable_any_more():
    """보증금이 자기자본을 넘는 것은 정상이다 — 보증금을 조달하려고 대출을 받는다.
    그것으로 유보하면 흔한 입력에서 사용자가 아무 표도 못 본 채 멈춘다."""
    assert WITHHOLDABLE == frozenset()


def test_an_input_contradiction_is_reported_but_the_band_is_still_drawn():
    conditions = {**CONDITIONS, "deposit_krw": 200_000_000, "equity_krw": 100_000_000}
    band = outcome(team().run(conditions), "finance.band")
    assert band.status is AgentStatus.OK
    assert band.data["bands"], "이상치가 밴드 표를 지우면 안 된다"


def test_an_input_contradiction_never_halts_the_run():
    conditions = {**CONDITIONS, "deposit_krw": 200_000_000, "equity_krw": 100_000_000}
    assert capacity_failed(team().run(conditions)) is False


def test_an_anomaly_carries_the_sentence_the_code_owns():
    """유보 사유 문장은 코드가 가진 고정 문장이다. 모델 문장을 실으면 그 문장이 곧 근거가 된다."""
    conditions = {**CONDITIONS, "deposit_krw": 200_000_000, "equity_krw": 100_000_000}
    notes = outcome(team().run(conditions), "finance.band").data["anomaly_notes"]
    assert "DEPOSIT_EXCEEDS_EQUITY" in notes
    assert "보증금" in notes["DEPOSIT_EXCEEDS_EQUITY"]


# ── 시나리오는 3종을 항상 전부 돌린다 ────────────────────────────────────

def test_all_three_scenarios_always_run():
    rows = outcome(team().run(CONDITIONS), "finance.stress").data["scenarios"]
    assert {row["key"] for row in rows} == set(STRESS_SCENARIOS)


async def test_the_scenarios_do_not_depend_on_what_a_model_picks():
    responder = CountingResponder()  # 아무 시나리오도 고르지 않는다
    rows = outcome(await team(responder=responder).arun(CONDITIONS), "finance.stress").data["scenarios"]
    assert {row["key"] for row in rows} == set(STRESS_SCENARIOS)


def test_a_harsher_scenario_is_never_easier_to_pass():
    rows = {row["key"]: row for row in
            outcome(team().run(CONDITIONS), "finance.stress").data["scenarios"]}
    assert rows["REVENUE_DROP_30"]["recommended_ceiling_krw"] <= rows["REVENUE_DROP_20"]["recommended_ceiling_krw"]


# ── 모델 호출 예산 ───────────────────────────────────────────────────────

async def test_the_band_and_stress_axes_never_call_a_model():
    responder = CountingResponder()
    await team(responder=responder).arun(CONDITIONS)
    assert "review_band_inputs" not in responder.calls
    assert "select_stress_scenarios" not in responder.calls


async def test_only_the_lookup_axes_may_call_a_model():
    """조회 결과를 읽는 두 축만 남는다 — 공시 한도와 공고 본문은 문장이라 구조화 비교가 안 된다."""
    responder = CountingResponder()
    await team(responder=responder,
               kb_products=[{"id": "p1", "name": "사업자대출", "category": "BUSINESS_LOAN"}],
               programs=[{"id": "n1", "title": "창업지원"}]).arun(CONDITIONS)
    assert sorted(responder.calls) == ["select_kb_products", "select_subsidy_notices"]


async def test_with_no_lookup_rows_the_team_calls_no_model_at_all():
    responder = CountingResponder()
    await team(responder=responder).arun(CONDITIONS)
    assert responder.calls == []


# ── 산출은 한 번만 계산된다 ──────────────────────────────────────────────

def test_the_band_is_computed_once_per_run(monkeypatch):
    """모델이 본 산출과 최종 산출이 같은 객체여야 한다는 요구가 사라진 자리에, 같은 값을 두 번
    계산하지 않는다는 요구가 남는다. 기준 밴드는 실행당 한 번이다(시나리오 3회는 별도 산식)."""
    from app.agents import finance as module
    calls = []
    real = module.compute_bands

    def counting(params, **kwargs):
        calls.append(kwargs.get("industry"))
        return real(params, **kwargs)

    monkeypatch.setattr(module, "compute_bands", counting)
    team().run(CONDITIONS)
    # 기준 1회 + 시나리오 3회. 예전에는 리뷰용 1회가 더 있었다.
    assert len(calls) == 1 + len(STRESS_SCENARIOS)
