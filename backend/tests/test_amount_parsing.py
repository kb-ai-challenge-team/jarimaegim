"""금액 파서의 단일 계약.

두 경로(`agents/conditions.py` 의 Span 추출, `condition_parse.py` 의 규칙 추출)가 같은
문자열에 같은 답을 내야 한다. 예전에는 "월세 300" 이 한쪽에서 3,000,000원, 다른 쪽에서
300원이었고, 확인 화면이 먼저 값을 채워 넣는 덕에 그 차이가 가려져 있었다.
"""
import pytest

from app.agents.conditions import resolve_mention
from app.condition_parse import amount_from


@pytest.mark.parametrize("text,expected", [
    ("1억", 100_000_000),
    ("3천만원", 30_000_000),
    ("250만원", 2_500_000),
    ("2,500,000원", 2_500_000),
    ("보증금 5천만", 50_000_000),
    ("3000000", 3_000_000),
])
def test_a_single_component_is_read_the_same_either_way(text, expected):
    assert amount_from(text) == expected


def test_adjacent_components_are_summed():
    """"1억 5천만원" 은 두 성분이다. 첫 성분만 읽으면 5천만원이 조용히 사라진다."""
    assert amount_from("1억 5천만원") == 150_000_000
    assert amount_from("1억 5000") == 150_000_000


def test_components_separated_by_words_are_not_summed():
    """관리비까지 월세에 더하면 사용자가 말하지 않은 금액이 조건에 들어간다.
    공백 말고 다른 것이 사이에 있으면 거기서 멈춘다."""
    assert amount_from("300, 관리비 20") == 3_000_000
    assert amount_from("월세 300 정도이고 보증금은 5000") == 3_000_000


def test_a_bare_number_under_ten_thousand_uses_the_manwon_convention():
    """"월세 300" 이라고 쓴 사람은 300원을 뜻한 것이 아니다."""
    assert amount_from("300") == 3_000_000
    assert amount_from("1,200") == 12_000_000


def test_a_bare_number_at_or_above_ten_thousand_is_literal():
    """"3,000,000" 을 쓴 사람은 정확히 그 금액을 뜻한 것이지 300억을 뜻한 게 아니다."""
    assert amount_from("3,000,000원") == 3_000_000


def test_no_amount_yields_none_rather_than_zero():
    """0 을 돌려주면 "월세 0원" 이라는 조건이 조용히 만들어진다."""
    assert amount_from("적당한 가격이면 좋겠어요") is None
    assert amount_from("근거 없음") is None


def test_an_absurd_amount_is_refused_rather_than_capped():
    assert amount_from("9999억원") is None


def test_the_span_path_uses_the_same_function():
    """`resolve_mention` 이 자체 산술을 갖지 않아야 두 경로가 갈라지지 않는다."""
    assert resolve_mention("monthly_rent_krw", "월세 300") == 3_000_000
    assert resolve_mention("deposit_krw", "보증금 1억 5천만원") == 150_000_000
