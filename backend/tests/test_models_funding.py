import pytest
from pydantic import ValidationError
from app.models import BandLine, BreakEven, FundingBandResult, FundingCapacityResult

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


PARTIAL_LINE = {**LINE, "runway_months": None}


def test_partial_result_is_valid_without_required_capital():
    result = FundingBandResult(status="partial", required_capital_krw=None, required_capital_band=None,
                               bands=[BandLine(**PARTIAL_LINE)], break_even=BreakEven(**BREAK_EVEN),
                               missing_params=["희망 평수"], message="희망 평수를 입력하면 현금소진까지 계산합니다.")
    assert result.bands[0].ceiling_krw == 100_000_000
    assert result.bands[0].runway_months is None


def test_partial_result_requires_missing_params():
    with pytest.raises(ValidationError, match="partial"):
        FundingBandResult(status="partial", required_capital_krw=None, required_capital_band=None,
                          bands=[BandLine(**PARTIAL_LINE)], break_even=BreakEven(**BREAK_EVEN),
                          missing_params=[], message=None)


def test_partial_result_must_not_carry_required_capital():
    """필요자금을 냈다면 partial 이 아니다. 부분 산출이 완전 산출로 새는 것을 막는다."""
    with pytest.raises(ValidationError, match="partial"):
        FundingBandResult(status="partial", required_capital_krw=148_900_000,
                          required_capital_band="RECOMMENDED",
                          bands=[BandLine(**PARTIAL_LINE)], break_even=BreakEven(**BREAK_EVEN),
                          missing_params=["희망 평수"], message=None)


def test_partial_result_must_not_carry_a_runway():
    """현금소진은 필요자금에서만 나온다. 필요자금 없이 소진 개월이 붙으면 추정값이라는 뜻이다."""
    with pytest.raises(ValidationError, match="partial"):
        FundingBandResult(status="partial", required_capital_krw=None, required_capital_band=None,
                          bands=[BandLine(**LINE)], break_even=BreakEven(**BREAK_EVEN),
                          missing_params=["희망 평수"], message=None)


def test_partial_result_requires_bands():
    with pytest.raises(ValidationError, match="partial"):
        FundingBandResult(status="partial", required_capital_krw=None, required_capital_band=None,
                          bands=[], break_even=None, missing_params=["희망 평수"], message=None)


def test_break_even_rejects_non_positive_margin():
    with pytest.raises(ValidationError):
        BreakEven(**{**BREAK_EVEN, "contribution_margin_ratio": 0.0})


def test_break_even_requires_assumptions():
    with pytest.raises(ValidationError, match="assumptions"):
        BreakEven(**{**BREAK_EVEN, "assumptions": []})


PENDING_TEXT = "권장 조달선은 업종과 희망 월세를 받은 뒤 계산합니다."


def test_capacity_result_accepts_a_computed_shape():
    result = FundingCapacityResult(status="computed", equity_line_krw=50_000_000,
                                   borrowing_headroom_krw=90_000_000, maximum_line_krw=140_000_000,
                                   recommended_line_pending=PENDING_TEXT)
    assert result.parameter_status == "VERIFIED"
    assert result.unverified_params == []


def test_unverified_params_force_the_demo_label():
    """미검증 값으로 계산해 놓고 검증됐다고 표시하는 응답은 만들 수 없어야 한다."""
    with pytest.raises(ValidationError):
        FundingCapacityResult(status="computed", equity_line_krw=1, borrowing_headroom_krw=0,
                              maximum_line_krw=1, parameter_status="VERIFIED",
                              unverified_params=["loan.policy_fund_ceiling_krw"],
                              recommended_line_pending=PENDING_TEXT)


def test_demo_label_is_accepted_with_the_reason_listed():
    result = FundingCapacityResult(status="computed", equity_line_krw=1, borrowing_headroom_krw=0,
                                   maximum_line_krw=1, parameter_status="DEMO",
                                   unverified_params=["loan.policy_fund_ceiling_krw"],
                                   recommended_line_pending=PENDING_TEXT)
    assert result.parameter_status == "DEMO"


def test_maximum_line_cannot_fall_below_the_equity_line():
    with pytest.raises(ValidationError):
        FundingCapacityResult(status="computed", equity_line_krw=100, borrowing_headroom_krw=0,
                              maximum_line_krw=50, recommended_line_pending=PENDING_TEXT)


def test_pending_result_needs_no_numbers():
    result = FundingCapacityResult(status="integration_pending",
                                   missing_params=["loan.guarantee_ceiling_krw"],
                                   recommended_line_pending=PENDING_TEXT,
                                   message="한도 파라미터가 등록되지 않았습니다.")
    assert result.maximum_line_krw == 0
