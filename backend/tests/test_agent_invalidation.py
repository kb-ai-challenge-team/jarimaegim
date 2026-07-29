"""조건이 바뀌면 무엇이 다시 도는가.

가드 2("같은 조건이면 다시 돌리지 않는다")를 실행 전체가 아니라 축 단위로 건다. 통짜로 걸면
조건 한 칸만 고쳐도 열세 축이 전부 다시 돌고, 반대로 느슨하게 걸면 낡은 판정이 새 조건 옆에
남는다. 후자가 훨씬 나쁘므로, 모르는 입력은 **전부 무효화**하는 쪽이 기본값이다.
"""
from app.agents.invalidation import (ALWAYS, KERNEL_UNITS, LOOKUP_UNITS, WHERE_UNITS,
                                     condition_digests, invalidated)

BASE = {"industry": "카페", "district": "마포구", "equity_krw": 50_000_000,
        "monthly_rent_krw": 2_500_000, "priority": "STABILITY"}


def stale(before, after, candidates_changed=False):
    return invalidated(condition_digests(before), condition_digests(after), candidates_changed)


def test_nothing_changes_so_only_the_always_units_rerun():
    """조건 수립과 메인 종합은 언제나 돈다 — 전자는 입력 그 자체이고 후자는 나머지를 읽는다."""
    assert stale(BASE, BASE) == set(ALWAYS)


def test_changing_the_district_invalidates_only_the_where_axes():
    """자치구는 탐색 공간이다. 공시 금리와 공고 목록은 자치구로 달라지지 않는다."""
    result = stale(BASE, {**BASE, "district": "강남구"})
    assert set(WHERE_UNITS) <= result
    assert not (set(LOOKUP_UNITS) & result)
    assert not (set(KERNEL_UNITS) & result)


def test_changing_the_equity_invalidates_only_the_kernel():
    """입지 축은 금액을 읽지 않는다. 자기자본을 고쳤다고 상권을 다시 조회할 이유가 없다."""
    result = stale(BASE, {**BASE, "equity_krw": 80_000_000})
    assert set(KERNEL_UNITS) <= result
    assert not (set(WHERE_UNITS) & result)


def test_changing_the_debt_invalidates_only_the_kernel():
    result = stale(BASE, {**BASE, "existing_debt_krw": 10_000_000})
    assert set(KERNEL_UNITS) <= result
    assert not (set(WHERE_UNITS) & result)


def test_changing_the_industry_invalidates_everything():
    """상권 조회 코드도, 손익분기의 원가 구조도, 공고 대조도 업종에서 갈린다."""
    result = stale(BASE, {**BASE, "industry": "치킨"})
    assert set(WHERE_UNITS) <= result
    assert set(KERNEL_UNITS) <= result
    assert set(LOOKUP_UNITS) <= result


def test_changing_the_rent_invalidates_the_kernel_but_not_the_where_axes():
    """희망 월세는 손익분기만 움직인다 — 이 자리에 손님이 있는지와는 무관하다."""
    result = stale(BASE, {**BASE, "monthly_rent_krw": 3_000_000})
    assert set(KERNEL_UNITS) <= result
    assert not (set(WHERE_UNITS) & result)


def test_a_presentation_only_field_invalidates_nothing_extra():
    """우선순위는 정렬과 문구에만 쓰인다. 축의 판정을 바꾸지 않는다."""
    assert stale(BASE, {**BASE, "priority": "COST"}) == set(ALWAYS)


def test_a_new_candidate_set_invalidates_the_per_candidate_axes():
    """후보마다 판정하는 축은 후보가 바뀌면 무효다."""
    result = stale(BASE, BASE, candidates_changed=True)
    assert set(WHERE_UNITS) <= result


def test_a_new_candidate_set_leaves_the_kernel_valid():
    """커널은 후보를 읽지 않는다 — 조건만으로 계산한다."""
    result = stale(BASE, BASE, candidates_changed=True)
    assert not (set(KERNEL_UNITS) & result)


def test_an_unknown_condition_key_invalidates_everything():
    """표에 없는 입력이 조용히 아무 영향도 없는 것으로 취급되면, 새 조건을 추가하고 표를 고치는
    것을 잊었을 때 낡은 판정이 살아남는다. 안전한 기본값은 '다시 돈다' 다."""
    result = stale(BASE, {**BASE, "some_new_condition": 1})
    assert set(WHERE_UNITS) <= result
    assert set(KERNEL_UNITS) <= result
    assert set(LOOKUP_UNITS) <= result


def test_removing_a_condition_counts_as_a_change():
    without = {key: value for key, value in BASE.items() if key != "district"}
    assert set(WHERE_UNITS) <= stale(BASE, without)


def test_a_new_candidate_set_leaves_the_lookup_axes_valid():
    """공시·공고는 후보를 읽지 않는다 — 조건과 조회 인덱스만 본다.

    자치구를 바꾸면 후보도 함께 바뀌므로, 후보 변경이 조회 축까지 무효화하면
    "자치구만 고쳤는데 공시를 다시 조회한다"가 되어 부분 무효화가 노리던 경우에서 무력해진다."""
    result = stale(BASE, BASE, candidates_changed=True)
    assert "finance.kb_products" not in result
    assert "finance.subsidy" not in result


def test_a_new_candidate_set_invalidates_timing_because_it_reads_survivors():
    """시점 축은 잔존 후보를 본다. 후보가 바뀌면 무효다."""
    assert "timing.policy" in stale(BASE, BASE, candidates_changed=True)


def test_changing_the_district_leaves_the_lookup_axes_valid_even_with_new_candidates():
    """M5 의 대표 사례 — 자치구를 고치면 어디 축만 다시 돌고 얼마 축은 앞 판정을 쓴다."""
    result = stale(BASE, {**BASE, "district": "성동구"}, candidates_changed=True)
    assert set(WHERE_UNITS) <= result
    assert "finance.kb_products" not in result
    assert "finance.subsidy" not in result
