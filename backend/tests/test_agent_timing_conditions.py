"""언제 — 타이밍 팀, 그리고 조건 확정 레이어.

타이밍 계약 (제안서 04장)
  산출물   계약 시점 권고 또는 판단 유보
  실패 시  "일정 확인 전 판단 유보"를 반환 — 후보는 그대로 유지

조건 계약 (제안서 03장)
  최소 조건 미충족 시 후보를 생성하지 않고 질문한다. 최대 3개, 답이 후보를 바꾸는 항목만.
"""
from app.agents.orchestrator import conditions_unsettled
from app.agents.conditions import ConditionLayer
from app.agents.contracts import AgentStatus
from app.agents.timing import TimingTeam

CANDIDATES = [{"id": "l1", "name": "OO동 1층"}, {"id": "l2", "name": "△△동 2층"}]

COMPLETE = {"industry": "카페", "district": "강남구", "area_pyeong": 15.0,
            "operating_style": "홀+테이크아웃", "monthly_rent_krw": 2_500_000,
            "deposit_krw": 100_000_000, "equity_krw": 100_000_000,
            "existing_debt_krw": 0, "other_monthly_fixed_krw": 1_000_000}


# ── 언제 · 타이밍 팀 ────────────────────────────────────────────────

def test_the_timing_team_runs_its_single_sub_agent():
    report = TimingTeam().run(CANDIDATES)
    assert [item.key for item in report.outcomes] == ["timing.policy"]


def test_timing_withholds_instead_of_recommending_a_date():
    report = TimingTeam().run(CANDIDATES)
    assert report.outcomes[0].status is AgentStatus.INTEGRATION_PENDING
    assert "판단 유보" in (report.outcomes[0].message or "")


def test_timing_keeps_every_candidate():
    report = TimingTeam().run(CANDIDATES)
    assert [item["id"] for item in report.surviving] == ["l1", "l2"]


def test_timing_never_reduces_the_candidate_set():
    """판정하지 못한 축이 후보를 줄이면 안 된다. 타이밍은 원천이 없어 언제나 유보다."""
    report = TimingTeam().run(CANDIDATES)
    assert len(report.surviving) == len(CANDIDATES)


# ── 조건 확정 레이어 ────────────────────────────────────────────────

def test_the_layer_runs_both_of_its_agents():
    report = ConditionLayer().run(COMPLETE)
    assert [item.key for item in report.outcomes] == ["condition.location", "condition.finance"]


def test_complete_conditions_are_settled():
    report = ConditionLayer().run(COMPLETE)
    assert all(item.status is AgentStatus.OK for item in report.outcomes)
    assert report.questions == []
    assert report.settled is True


def test_a_missing_minimum_condition_produces_a_question_not_a_guess():
    report = ConditionLayer().run({**COMPLETE, "industry": ""})
    location = next(item for item in report.outcomes if item.key == "condition.location")
    assert location.status is AgentStatus.WITHHELD
    assert report.settled is False
    assert any("업종" in question["label"] for question in report.questions)


def test_questions_are_capped_at_three():
    report = ConditionLayer().run({})
    assert 0 < len(report.questions) <= 3


def test_an_unsettled_layer_blocks_candidate_generation():
    # 제안서 03장 — 미충족 시 후보를 생성하지 않는다.
    assert conditions_unsettled(ConditionLayer().run({})) is True


def test_mydata_is_declared_off_and_manual_entry_satisfies_the_same_schema():
    report = ConditionLayer().run(COMPLETE)
    finance = next(item for item in report.outcomes if item.key == "condition.finance")
    assert finance.data["source"] == "MANUAL"
    assert finance.data["mydata_enabled"] is False


def test_optional_fields_do_not_hold_the_run():
    # 평수·운영형태·보증금에 더해 희망 월세까지 — 없어도 후보는 나온다.
    # 없으면 손익분기만 못 내고, 그 사실은 `deferred` 로 밝힌다.
    report = ConditionLayer().run({**COMPLETE, "area_pyeong": None, "operating_style": "",
                                   "monthly_rent_krw": None, "deposit_krw": None})
    assert report.settled is True
    assert conditions_unsettled(report) is False
    assert report.questions == []
    assert set(report.deferred) >= {"monthly_rent_krw", "area_pyeong", "deposit_krw"}
