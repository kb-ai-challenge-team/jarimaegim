import pytest
from app.funding import compute_bands
from app.policy_params import PolicyParams

PARAMS = PolicyParams({
    "schema_version": 1,
    "entries": {
        "loan.annual_rate_percent": {"value": 4.5},
        "loan.term_months": {"value": 60},
        "loan.guarantee_ceiling_krw": {"value": 70_000_000},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000},
        "stress.revenue_drop_ratio": {"value": 0.2},
        "stress.repayment_burden_cap_ratio": {"value": 0.1},
        "working_capital.months": {"value": 3},
    },
    "industries": {
        "카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20, "fitout_krw_per_pyeong": 2_500_000,
                 "operating_days_per_month": 26, "source": "테스트", "as_of": "2026-07-01"}
    },
})

BASE = dict(industry="카페", area_pyeong=15.0, deposit_krw=100_000_000, monthly_rent_krw=2_500_000,
            monthly_maintenance_krw=300_000, key_money_krw=0, fitout_krw=None,
            equity_krw=100_000_000, existing_debt_krw=0, other_monthly_fixed_krw=1_000_000)


def test_required_capital_sums_deposit_fitout_and_working_capital():
    out = compute_bands(PARAMS, **BASE)
    # 보증금 1억 + 인테리어 15평×250만 = 3,750만 + 운전자금 (250+30+100)만 × 3개월 = 1,140만
    assert out["required_capital_krw"] == 100_000_000 + 37_500_000 + 11_400_000


def test_explicit_fitout_overrides_the_industry_estimate():
    out = compute_bands(PARAMS, **{**BASE, "fitout_krw": 20_000_000})
    assert out["required_capital_krw"] == 100_000_000 + 20_000_000 + 11_400_000
    assert out["fitout_is_estimate"] is False


def test_fitout_from_industry_table_is_marked_as_estimate():
    assert compute_bands(PARAMS, **BASE)["fitout_is_estimate"] is True


def test_three_bands_are_returned_in_ascending_order():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert [item["band"] for item in bands] == ["EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"]
    assert bands[0]["ceiling_krw"] <= bands[1]["ceiling_krw"] <= bands[2]["ceiling_krw"]


def test_equity_only_band_has_no_loan_and_no_repayment():
    band = compute_bands(PARAMS, **BASE)["bands"][0]
    assert band["loan_krw"] == 0
    assert band["monthly_repayment_krw"] == 0
    assert band["stress_pass"] is True


def test_maximum_band_is_capped_by_guarantee_plus_policy_fund_less_existing_debt():
    out = compute_bands(PARAMS, **{**BASE, "existing_debt_krw": 30_000_000})
    maximum = out["bands"][2]
    assert maximum["ceiling_krw"] == 100_000_000 + (70_000_000 + 20_000_000 - 30_000_000)


def test_maximum_band_is_always_flagged_as_estimate():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert bands[2]["is_estimate"] is True
    assert bands[0]["is_estimate"] is False


def test_recommended_band_satisfies_the_repayment_burden_cap():
    recommended = compute_bands(PARAMS, **BASE)["bands"][1]
    assert recommended["stress_pass"] is True
    assert recommended["repayment_burden_ratio"] <= 0.1 + 1e-9


def test_recommended_band_never_exceeds_maximum():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert bands[1]["ceiling_krw"] <= bands[2]["ceiling_krw"]


def test_tighter_burden_cap_lowers_the_recommended_ceiling():
    strict = PolicyParams({
        "entries": {**{k: dict(v) for k, v in PARAMS._entries.items()},
                    "stress.repayment_burden_cap_ratio": {"value": 0.02}},
        "industries": {"카페": PARAMS.industry("카페")},
    })
    loose = compute_bands(PARAMS, **BASE)["bands"][1]["ceiling_krw"]
    tight = compute_bands(strict, **BASE)["bands"][1]["ceiling_krw"]
    assert tight < loose


def test_break_even_target_rises_with_the_band():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert bands[2]["target_monthly_revenue_krw"] > bands[0]["target_monthly_revenue_krw"]


def test_daily_target_uses_the_industry_operating_days():
    band = compute_bands(PARAMS, **BASE)["bands"][0]
    assert band["target_daily_revenue_krw"] == band["target_monthly_revenue_krw"] // 26


def test_runway_is_none_when_the_band_cannot_cover_required_capital():
    # 자기자본 5천만, 필요자금 약 1.5억 → 자기자본선으로는 조달 불가
    out = compute_bands(PARAMS, **{**BASE, "equity_krw": 50_000_000})
    assert out["bands"][0]["runway_months"] is None


def test_required_capital_band_reports_where_the_need_falls():
    out = compute_bands(PARAMS, **BASE)
    assert out["required_capital_band"] in {"EQUITY_ONLY", "RECOMMENDED", "MAXIMUM", "OUT_OF_RANGE"}


def test_out_of_range_when_required_capital_exceeds_maximum():
    out = compute_bands(PARAMS, **{**BASE, "deposit_krw": 900_000_000})
    assert out["required_capital_band"] == "OUT_OF_RANGE"


def test_trade_area_count_is_none_because_rent_level_data_is_absent():
    for band in compute_bands(PARAMS, **BASE)["bands"]:
        assert band["trade_area_count"] is None


def test_impossible_margin_raises():
    broken = PolicyParams({
        "entries": {k: dict(v) for k, v in PARAMS._entries.items()},
        "industries": {"카페": {**PARAMS.industry("카페"), "cogs_ratio": 0.7, "labor_ratio": 0.4}},
    })
    with pytest.raises(ValueError):
        compute_bands(broken, **BASE)
