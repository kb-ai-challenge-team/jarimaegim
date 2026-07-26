import pytest
from app.funding import breakeven_monthly_revenue_krw, monthly_annuity_krw


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
