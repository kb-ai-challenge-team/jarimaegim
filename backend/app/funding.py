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
