from __future__ import annotations

from typing import Any


class ScenarioParams:
    """제도 파라미터 몇 개만 갈아 끼운 읽기 전용 겹침.

    스트레스 시나리오("매출 −30%이면?", "금리가 1%p 오르면?")를 계산하려면 같은 산식을 다른
    파라미터로 한 번 더 돌려야 한다. 그 산식을 에이전트 쪽에 복제하면 두 곳이 갈라지므로,
    파라미터만 덮고 `compute_bands` 를 그대로 다시 부른다. 원본은 건드리지 않는다 —
    같은 요청 안의 다른 밴드가 갈아 낀 값을 보게 되면 화면의 수치가 서로 어긋난다."""

    def __init__(self, base: Any, overrides: dict[str, float]):
        self._base, self._overrides = base, overrides

    @property
    def updated_at(self) -> Any:
        return self._base.updated_at

    def value(self, key: str) -> float:
        if key in self._overrides:
            return self._overrides[key]
        return self._base.value(key)

    def industry(self, name: str) -> dict[str, Any]:
        return self._base.industry(name)

    def missing(self, industry: str) -> list[str]:
        return self._base.missing(industry)

    def sources(self, industry: str) -> list[str]:
        return self._base.sources(industry)


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

# 여력 산출에만 필요한 키. 업종 파라미터도 임대조건도 요구하지 않는다.
CAPACITY_ENTRIES = ("loan.guarantee_ceiling_krw", "loan.policy_fund_ceiling_krw")


def compute_capacity(params, *, equity_krw: int, existing_debt_krw: int) -> dict:
    """자기자본선·차입 여력·최대 조달선. 금융 프로필만으로 나온다.

    권장 조달선은 스트레스 테스트(업종 원가율·인건비율 + 월 고정비)를 요구하므로 여기서 내지 않는다.
    그 경계가 1단계(자금)와 2단계(조건)를 가르는 근거다. 한도가 미등록이면 KeyError 를 던지고,
    호출부가 integration_pending 으로 바꾼다 — 추정으로 메우지 않는다."""
    headroom = max(0, int(params.value("loan.guarantee_ceiling_krw")
                          + params.value("loan.policy_fund_ceiling_krw") - existing_debt_krw))
    return {"equity_line_krw": int(equity_krw), "borrowing_headroom_krw": headroom,
            "maximum_line_krw": int(equity_krw) + headroom}


def _band_line(band: str, ceiling_krw: int, *, equity_krw: int, required_capital_krw: int | None,
               base_monthly_fixed_krw: int, rate: float, term: int, cogs: float, labor: float,
               drop: float, burden_cap: float, operating_days: int) -> dict:
    loan = max(0, ceiling_krw - equity_krw)
    repayment = monthly_annuity_krw(loan, rate, term)
    monthly_fixed_total = base_monthly_fixed_krw + repayment
    target_monthly = breakeven_monthly_revenue_krw(monthly_fixed_total, cogs, labor)
    stressed_monthly = target_monthly * (1.0 - drop)
    burden = (repayment / stressed_monthly) if stressed_monthly > 0 else 0.0
    # 필요자금을 모르면 잔여 현금을 알 수 없다. 0 으로 가정하면 낙관 방향으로 틀리므로 None 을 둔다.
    monthly_deficit = drop * monthly_fixed_total
    if required_capital_krw is None:
        runway = None
    else:
        surplus_cash = equity_krw + loan - required_capital_krw
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


def compute_bands(params, *, industry: str, area_pyeong: float | None, deposit_krw: int | None,
                  monthly_rent_krw: int, monthly_maintenance_krw: int, key_money_krw: int,
                  fitout_krw: int | None, equity_krw: int, existing_debt_krw: int,
                  other_monthly_fixed_krw: int) -> dict:
    """조달 밴드 3종과 밴드별 손익분기선을 산출한다. 제도 파라미터가 없으면 호출 전에 걸러야 한다.

    평수·보증금은 필요자금을 통해 현금소진에만 영향을 준다. 둘 중 하나라도 없으면
    required_capital_krw 와 runway_months 를 None 으로 두고 나머지는 그대로 계산한다."""
    profile = params.industry(industry)
    cogs, labor = float(profile["cogs_ratio"]), float(profile["labor_ratio"])
    if 1.0 - cogs - labor <= 0:
        raise ValueError("contribution margin must be positive")
    operating_days = int(profile["operating_days_per_month"])
    rate, term = params.value("loan.annual_rate_percent"), int(params.value("loan.term_months"))
    drop = params.value("stress.revenue_drop_ratio")
    burden_cap = params.value("stress.repayment_burden_cap_ratio")

    fitout_is_estimate = fitout_krw is None
    if fitout_is_estimate:
        fitout = int(area_pyeong * float(profile["fitout_krw_per_pyeong"])) if area_pyeong is not None else None
    else:
        fitout = int(fitout_krw)
    base_monthly_fixed = int(monthly_rent_krw + monthly_maintenance_krw + other_monthly_fixed_krw)
    working_capital = int(base_monthly_fixed * params.value("working_capital.months"))
    required_capital = None if (fitout is None or deposit_krw is None) else int(deposit_krw + key_money_krw + fitout + working_capital)

    # 여력과 밴드가 같은 산식을 쓰도록 한 곳에서만 계산한다. 두 화면이 다른 최대선을 말하면 안 된다.
    maximum_ceiling = compute_capacity(params, equity_krw=equity_krw,
                                       existing_debt_krw=existing_debt_krw)["maximum_line_krw"]

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

    if required_capital is None:
        required_capital_band = None
    elif required_capital > maximum_ceiling:
        required_capital_band = "OUT_OF_RANGE"
    else:
        required_capital_band = next(item["band"] for item in bands if required_capital <= item["ceiling_krw"])

    return {"required_capital_krw": required_capital, "required_capital_band": required_capital_band,
            "fitout_krw": fitout, "fitout_is_estimate": fitout_is_estimate,
            "base_monthly_fixed_krw": base_monthly_fixed, "working_capital_krw": working_capital,
            "contribution_margin_ratio": round(1.0 - cogs - labor, 6), "bands": bands}
