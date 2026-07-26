from __future__ import annotations


def monthly_annuity_krw(principal_krw: int, annual_rate_percent: float, term_months: int) -> int:
    """원리금균등 월 상환액. 원 단위로 내림한다."""
    if term_months <= 0:
        raise ValueError("term_months must be positive")
    if principal_krw <= 0:
        return 0
    monthly_rate = float(annual_rate_percent) / 100.0 / 12.0
    if monthly_rate == 0:
        return int(principal_krw // term_months)
    factor = (1.0 + monthly_rate) ** term_months
    return int(principal_krw * monthly_rate * factor / (factor - 1.0))


def breakeven_monthly_revenue_krw(fixed_cost_krw: int, cogs_ratio: float, labor_ratio: float) -> int:
    """손익분기 월매출 = 고정비 / 공헌이익률. 공헌이익률이 0 이하면 성립하지 않는다."""
    contribution_margin = 1.0 - float(cogs_ratio) - float(labor_ratio)
    if contribution_margin <= 0:
        raise ValueError("contribution margin must be positive")
    if fixed_cost_krw <= 0:
        return 0
    return int(fixed_cost_krw / contribution_margin)


BAND_ORDER = ("EQUITY_ONLY", "RECOMMENDED", "MAXIMUM")


def _band_line(band: str, ceiling_krw: int, *, equity_krw: int, required_capital_krw: int,
               base_monthly_fixed_krw: int, rate: float, term: int, cogs: float, labor: float,
               drop: float, burden_cap: float, operating_days: int) -> dict:
    loan = max(0, ceiling_krw - equity_krw)
    repayment = monthly_annuity_krw(loan, rate, term)
    monthly_fixed_total = base_monthly_fixed_krw + repayment
    target_monthly = breakeven_monthly_revenue_krw(monthly_fixed_total, cogs, labor)
    stressed_monthly = target_monthly * (1.0 - drop)
    burden = (repayment / stressed_monthly) if stressed_monthly > 0 else 0.0
    surplus_cash = equity_krw + loan - required_capital_krw
    monthly_deficit = drop * monthly_fixed_total
    runway = int(surplus_cash // monthly_deficit) if surplus_cash >= 0 and monthly_deficit > 0 else None
    return {
        "band": band, "ceiling_krw": int(ceiling_krw), "loan_krw": int(loan),
        "monthly_repayment_krw": int(repayment),
        "monthly_fixed_cost_krw": int(monthly_fixed_total),
        "target_monthly_revenue_krw": int(target_monthly),
        "target_daily_revenue_krw": int(target_monthly // operating_days) if operating_days > 0 else 0,
        "runway_months": runway, "stress_pass": burden <= burden_cap + 1e-9,
        "repayment_burden_ratio": round(burden, 6), "subsidy_uplift_krw": 0,
        "is_estimate": band == "MAXIMUM", "trade_area_count": None,
    }


def compute_bands(params, *, industry: str, area_pyeong: float, deposit_krw: int, monthly_rent_krw: int,
                  monthly_maintenance_krw: int, key_money_krw: int, fitout_krw: int | None,
                  equity_krw: int, existing_debt_krw: int, other_monthly_fixed_krw: int) -> dict:
    """조달 밴드 3종과 밴드별 손익분기선을 산출한다. 파라미터가 없으면 호출 전에 걸러야 한다."""
    profile = params.industry(industry)
    cogs, labor = float(profile["cogs_ratio"]), float(profile["labor_ratio"])
    if 1.0 - cogs - labor <= 0:
        raise ValueError("contribution margin must be positive")
    operating_days = int(profile["operating_days_per_month"])
    rate, term = params.value("loan.annual_rate_percent"), int(params.value("loan.term_months"))
    drop = params.value("stress.revenue_drop_ratio")
    burden_cap = params.value("stress.repayment_burden_cap_ratio")

    fitout_is_estimate = fitout_krw is None
    fitout = int(area_pyeong * float(profile["fitout_krw_per_pyeong"])) if fitout_is_estimate else int(fitout_krw)
    base_monthly_fixed = int(monthly_rent_krw + monthly_maintenance_krw + other_monthly_fixed_krw)
    working_capital = int(base_monthly_fixed * params.value("working_capital.months"))
    required_capital = int(deposit_krw + key_money_krw + fitout + working_capital)

    borrow_ceiling = max(0, int(params.value("loan.guarantee_ceiling_krw")
                                + params.value("loan.policy_fund_ceiling_krw") - existing_debt_krw))
    maximum_ceiling = int(equity_krw + borrow_ceiling)

    common = dict(equity_krw=equity_krw, required_capital_krw=required_capital,
                  base_monthly_fixed_krw=base_monthly_fixed, rate=rate, term=term, cogs=cogs,
                  labor=labor, drop=drop, burden_cap=burden_cap, operating_days=operating_days)

    # 부담률은 차입액에 대해 단조증가하므로 이분 탐색으로 권장 조달선을 찾는다.
    low, high = equity_krw, maximum_ceiling
    if _band_line("RECOMMENDED", high, **common)["stress_pass"]:
        recommended_ceiling = high
    else:
        for _ in range(48):
            mid = (low + high) // 2
            if _band_line("RECOMMENDED", mid, **common)["stress_pass"]:
                low = mid
            else:
                high = mid
            if high - low <= 1:
                break
        recommended_ceiling = low

    bands = [_band_line("EQUITY_ONLY", equity_krw, **common),
             _band_line("RECOMMENDED", recommended_ceiling, **common),
             _band_line("MAXIMUM", maximum_ceiling, **common)]

    if required_capital > maximum_ceiling:
        required_capital_band = "OUT_OF_RANGE"
    else:
        required_capital_band = next(item["band"] for item in bands if required_capital <= item["ceiling_krw"])

    return {"required_capital_krw": required_capital, "required_capital_band": required_capital_band,
            "fitout_krw": fitout, "fitout_is_estimate": fitout_is_estimate,
            "base_monthly_fixed_krw": base_monthly_fixed, "working_capital_krw": working_capital,
            "contribution_margin_ratio": round(1.0 - cogs - labor, 6), "bands": bands}
