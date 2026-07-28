"""권리금이 필요자금을 거쳐 조달 판정까지 닿는지 확인한다.

권리금은 매물의 **가정값**이다(`pipeline/lib/attribute-constants.mjs`). 실측이 아니지만
필요자금에는 실제로 합산되므로, 그 경로가 살아 있는지는 코드로 고정해 둔다. 값이 조용히
버려지면 화면의 조달 금액이 매물 조건과 어긋나는데, 눈으로는 알아채기 어렵다.

이 테스트는 제도 파라미터를 직접 주입한다. `config/policy-params.json` 은 대출 한도 3종과
업종 프로파일이 비어 있어 API 경로가 integration_pending 을 반환하기 때문이다. 그 공백은
의도된 것이고(부록 A 불변조건 1), 여기서 검증하려는 것은 산식이지 그 공백이 아니다.
"""

import pytest

from app.funding import compute_bands


class StubParams:
    """제도 파라미터 스텁. 실제 공고값이 아니라 산식 검증용 고정값이다."""

    _VALUES = {
        "loan.annual_rate_percent": 4.45, "loan.term_months": 60,
        "loan.guarantee_ceiling_krw": 100_000_000, "loan.policy_fund_ceiling_krw": 70_000_000,
        "stress.revenue_drop_ratio": 0.2, "stress.repayment_burden_cap_ratio": 0.1,
        "working_capital.months": 3,
    }

    def value(self, key: str) -> float:
        return self._VALUES[key]

    def industry(self, name: str) -> dict:
        return {"cogs_ratio": 0.35, "labor_ratio": 0.20,
                "fitout_krw_per_pyeong": 2_000_000, "operating_days_per_month": 26}


def bands(**overrides):
    args = dict(industry="카페", area_pyeong=17.5, deposit_krw=51_000_000,
                monthly_rent_krw=3_090_000, monthly_maintenance_krw=250_000,
                key_money_krw=0, fitout_krw=None, equity_krw=80_000_000,
                existing_debt_krw=0, other_monthly_fixed_krw=0)
    args.update(overrides)
    return compute_bands(StubParams(), **args)


def test_key_money_is_added_to_the_required_capital():
    without = bands(key_money_krw=0)["required_capital_krw"]
    with_key = bands(key_money_krw=48_000_000)["required_capital_krw"]
    assert with_key - without == 48_000_000


def test_zero_key_money_leaves_the_required_capital_untouched():
    """무권리 매물이 실제로 236건 있다. 그 경우 필요자금이 부풀지 않아야 한다."""
    assert bands(key_money_krw=0)["required_capital_krw"] == bands()["required_capital_krw"]


def test_key_money_shortens_the_runway():
    """필요자금이 늘면 같은 조달선에서 현금소진이 빨라진다.

    자기자본을 넉넉히 둔다 — 잔여 현금이 음수면 runway 가 None 이 되어(설계상 낙관
    방향으로 틀리지 않기 위한 처리) 두 값을 비교할 수 없다."""
    rich = {"equity_krw": 300_000_000}
    calm = next(b for b in bands(key_money_krw=0, **rich)["bands"] if b["band"] == "RECOMMENDED")
    heavy = next(b for b in bands(key_money_krw=48_000_000, **rich)["bands"] if b["band"] == "RECOMMENDED")
    assert calm["runway_months"] is not None and heavy["runway_months"] is not None
    assert heavy["runway_months"] < calm["runway_months"]


def test_key_money_does_not_move_the_monthly_fixed_cost():
    """권리금은 일시금이지 월 고정지출이 아니다. 월 고정비가 움직이면 산식이 틀린 것이다.

    월 고정비가 그대로면 손익분기 목표매출도 그대로다 — 목표매출은 고정비에서만 나온다."""
    calm = bands(key_money_krw=0)
    heavy = bands(key_money_krw=48_000_000)
    assert calm["base_monthly_fixed_krw"] == heavy["base_monthly_fixed_krw"]
    calm_line = next(b for b in calm["bands"] if b["band"] == "RECOMMENDED")
    heavy_line = next(b for b in heavy["bands"] if b["band"] == "RECOMMENDED")
    assert calm_line["target_daily_revenue_krw"] == heavy_line["target_daily_revenue_krw"]


def test_key_money_does_not_move_the_borrowing_ceiling():
    """조달 상한은 자기자본과 보증·정책자금 한도에서 나온다. 매물 권리금이 한도를 넓히지 않는다."""
    calm = {b["band"]: b["ceiling_krw"] for b in bands(key_money_krw=0)["bands"]}
    heavy = {b["band"]: b["ceiling_krw"] for b in bands(key_money_krw=48_000_000)["bands"]}
    assert calm == heavy


@pytest.mark.parametrize("key_money", [0, 1_000_000, 225_000_000])
def test_required_capital_band_stays_consistent(key_money):
    result = bands(key_money_krw=key_money)
    assert result["required_capital_krw"] > 0
    assert result["required_capital_band"] is not None
