"""차단 항목과 유보 항목의 경계.

되묻는 기준은 "답이 후보를 바꾸는가" 가 아니라 **"없으면 계산 자체가 불가능한가"** 다.
업종이 없으면 `compute_bands` 가 업종 파라미터를 못 찾고, 자기자본이 없으면 `compute_capacity`
가 여력을 못 내고, 자치구가 없으면 탐색 공간을 못 자른다. 희망 월세는 손익분기만 못 내므로
입지 축은 전부 그대로 돈다 — 그래서 되묻지 않고 그 수치만 유보한다.
"""
from app.agents.conditions import BLOCKING, DEFERRABLE, ConditionLayer

FULL = {"industry": "카페", "district": "마포구", "equity_krw": 50_000_000,
        "monthly_rent_krw": 2_500_000}


def layer():
    return ConditionLayer()


def test_the_blocking_set_is_exactly_the_three_that_stop_a_calculation():
    assert [key for key, _ in BLOCKING] == ["industry", "district", "equity_krw"]


def test_the_rent_is_deferrable_not_blocking():
    assert "monthly_rent_krw" in [key for key, _ in DEFERRABLE]
    assert "monthly_rent_krw" not in [key for key, _ in BLOCKING]


def test_complete_conditions_settle_and_do_not_halt():
    report = layer().run(FULL)
    assert report.settled is True
    assert report.halted is False
    assert report.questions == []


def test_a_missing_rent_does_not_halt_the_run():
    """M0 의 핵심 — 손익분기만 못 내는 항목이 입지 판단을 인질로 잡지 않는다."""
    report = layer().run({**FULL, "monthly_rent_krw": None})
    assert report.halted is False
    assert report.questions == []
    assert "monthly_rent_krw" in report.deferred


def test_a_missing_area_or_deposit_does_not_halt_the_run():
    report = layer().run({**FULL, "area_pyeong": None, "deposit_krw": None})
    assert report.halted is False
    assert report.questions == []


def test_a_missing_industry_halts_and_asks_for_exactly_that():
    report = layer().run({**FULL, "industry": None})
    assert report.halted is True
    assert [item["field"] for item in report.questions] == ["industry"]


def test_a_missing_equity_halts_and_asks_for_exactly_that():
    report = layer().run({**FULL, "equity_krw": None})
    assert report.halted is True
    assert [item["field"] for item in report.questions] == ["equity_krw"]


def test_a_deferred_gap_never_becomes_a_question_even_alongside_a_blocking_one():
    """되묻기는 차단 항목만이다. 유보 항목을 같이 물으면 질문 수가 다시 늘어난다."""
    report = layer().run({"district": "마포구", "equity_krw": 50_000_000})
    assert [item["field"] for item in report.questions] == ["industry"]


def test_questions_are_still_capped_at_three():
    report = layer().run({})
    assert len(report.questions) <= 3


def test_a_zero_equity_counts_as_missing_rather_than_as_an_answer():
    """0 원을 확정된 자기자본으로 읽으면 여력 커널이 0 을 진짜 답으로 낸다."""
    report = layer().run({**FULL, "equity_krw": 0})
    assert report.halted is True
