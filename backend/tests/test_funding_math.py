import pytest
from app.funding import breakeven_monthly_revenue_krw, compute_capacity, monthly_annuity_krw
from app.policy_params import PolicyParams


def test_annuity_is_zero_for_zero_principal():
    assert monthly_annuity_krw(0, 4.5, 60) == 0


def test_annuity_is_straight_division_at_zero_rate():
    assert monthly_annuity_krw(60_000_000, 0.0, 60) == 1_000_000


def test_annuity_matches_standard_formula():
    # 4.5% / 60개월 / 4,500만원 → 원리금균등 상환액
    assert monthly_annuity_krw(45_000_000, 4.5, 60) == 838_935


def test_annuity_grows_with_principal():
    small = monthly_annuity_krw(30_000_000, 4.5, 60)
    large = monthly_annuity_krw(60_000_000, 4.5, 60)
    assert large > small


def test_annuity_rejects_non_positive_term():
    with pytest.raises(ValueError):
        monthly_annuity_krw(10_000_000, 4.5, 0)


def test_breakeven_divides_fixed_cost_by_contribution_margin():
    # 고정비 380만, 원가율 0.35, 인건비율 0.20 → 공헌이익률 0.45
    assert breakeven_monthly_revenue_krw(3_800_000, 0.35, 0.20) == 8_444_444


def test_breakeven_rejects_non_positive_margin():
    with pytest.raises(ValueError):
        breakeven_monthly_revenue_krw(3_800_000, 0.6, 0.4)


def test_breakeven_is_zero_when_no_fixed_cost():
    assert breakeven_monthly_revenue_krw(0, 0.35, 0.20) == 0


CEILINGS = PolicyParams({"entries": {
    "loan.guarantee_ceiling_krw": {"value": 70_000_000},
    "loan.policy_fund_ceiling_krw": {"value": 20_000_000},
}})


def test_capacity_adds_both_ceilings_to_equity():
    result = compute_capacity(CEILINGS, equity_krw=50_000_000, existing_debt_krw=0)
    assert result == {"equity_line_krw": 50_000_000, "borrowing_headroom_krw": 90_000_000,
                      "maximum_line_krw": 140_000_000}


def test_existing_debt_eats_into_the_headroom():
    result = compute_capacity(CEILINGS, equity_krw=50_000_000, existing_debt_krw=30_000_000)
    assert result["borrowing_headroom_krw"] == 60_000_000
    assert result["maximum_line_krw"] == 110_000_000


def test_headroom_never_goes_negative():
    """기존부채가 한도를 넘겨도 음수 여력을 만들지 않는다 — 최대선이 자기자본선 아래로 내려갈 수 없다."""
    result = compute_capacity(CEILINGS, equity_krw=50_000_000, existing_debt_krw=200_000_000)
    assert result["borrowing_headroom_krw"] == 0
    assert result["maximum_line_krw"] == 50_000_000


def test_capacity_needs_no_industry_and_no_rent():
    """1단계가 2단계 입력 없이 성립한다는 사실 자체가 계약이다."""
    assert compute_capacity(CEILINGS, equity_krw=0, existing_debt_krw=0)["maximum_line_krw"] == 90_000_000


def test_capacity_raises_when_a_ceiling_is_unregistered():
    empty = PolicyParams({"entries": {"loan.guarantee_ceiling_krw": {"value": None},
                                      "loan.policy_fund_ceiling_krw": {"value": 20_000_000}}})
    with pytest.raises(KeyError):
        compute_capacity(empty, equity_krw=1, existing_debt_krw=0)
