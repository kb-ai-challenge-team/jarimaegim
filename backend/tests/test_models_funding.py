import pytest
from pydantic import ValidationError
from app.models import BandLine, BreakEven, FundingBandResult

LINE = dict(band="EQUITY_ONLY", ceiling_krw=100_000_000, loan_krw=0, monthly_repayment_krw=0,
            monthly_fixed_cost_krw=3_800_000, target_monthly_revenue_krw=8_444_444,
            target_daily_revenue_krw=324_786, runway_months=14, stress_pass=True,
            repayment_burden_ratio=0.0, subsidy_uplift_krw=0, is_estimate=False, trade_area_count=None)

BREAK_EVEN = dict(monthly_fixed_cost_krw=3_800_000, target_monthly_revenue_krw=8_444_444,
                  target_daily_revenue_krw=324_786, contribution_margin_ratio=0.45,
                  assumptions=["원가율 0.35 · 인건비율 0.20 (출처: 테스트, 기준일 2026-07-01)"])


def test_band_line_accepts_a_valid_row():
    assert BandLine(**LINE).band == "EQUITY_ONLY"


def test_maximum_band_must_be_flagged_as_estimate():
    with pytest.raises(ValidationError, match="MAXIMUM"):
        BandLine(**{**LINE, "band": "MAXIMUM", "is_estimate": False})


def test_maximum_band_passes_when_flagged():
    assert BandLine(**{**LINE, "band": "MAXIMUM", "is_estimate": True}).is_estimate is True


def test_band_line_rejects_a_loan_without_repayment():
    with pytest.raises(ValidationError, match="repayment"):
        BandLine(**{**LINE, "loan_krw": 50_000_000, "monthly_repayment_krw": 0})


def test_computed_result_requires_bands_and_break_even():
    with pytest.raises(ValidationError, match="computed"):
        FundingBandResult(status="computed", required_capital_krw=None, required_capital_band=None,
                          bands=[], break_even=None, missing_params=[], message=None)


def test_pending_result_requires_missing_params_and_no_bands():
    with pytest.raises(ValidationError, match="integration_pending"):
        FundingBandResult(status="integration_pending", required_capital_krw=None,
                          required_capital_band=None, bands=[], break_even=None,
                          missing_params=[], message="x")


def test_pending_result_is_valid_with_missing_params():
    result = FundingBandResult(status="integration_pending", required_capital_krw=None,
                               required_capital_band=None, bands=[], break_even=None,
                               missing_params=["loan.term_months"], message="등록 대기")
    assert result.bands == []


def test_computed_result_is_valid():
    result = FundingBandResult(status="computed", required_capital_krw=148_900_000,
                               required_capital_band="RECOMMENDED",
                               bands=[BandLine(**LINE)], break_even=BreakEven(**BREAK_EVEN),
                               missing_params=[], message=None)
    assert result.break_even.contribution_margin_ratio == 0.45


def test_break_even_rejects_non_positive_margin():
    with pytest.raises(ValidationError):
        BreakEven(**{**BREAK_EVEN, "contribution_margin_ratio": 0.0})


def test_break_even_requires_assumptions():
    with pytest.raises(ValidationError, match="assumptions"):
        BreakEven(**{**BREAK_EVEN, "assumptions": []})
