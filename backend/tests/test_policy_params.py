import json
import pytest
from app.policy_params import PolicyParams

FULL = {
    "schema_version": 1,
    "entries": {
        "loan.annual_rate_percent": {"value": 4.5, "unit": "PERCENT", "source": "테스트", "as_of": "2026-07-01"},
        "loan.term_months": {"value": 60, "unit": "MONTHS", "source": "테스트", "as_of": "2026-07-01"},
        "loan.guarantee_ceiling_krw": {"value": 70000000, "unit": "KRW", "source": "테스트", "as_of": "2026-07-01"},
        "loan.policy_fund_ceiling_krw": {"value": 20000000, "unit": "KRW", "source": "테스트", "as_of": "2026-07-01"},
        "stress.revenue_drop_ratio": {"value": 0.2, "unit": "RATIO", "source": "테스트", "as_of": "2026-07-01"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "unit": "RATIO", "source": "테스트", "as_of": "2026-07-01"},
        "working_capital.months": {"value": 3, "unit": "MONTHS", "source": "테스트", "as_of": "2026-07-01"},
    },
    "industries": {
        "카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20, "fitout_krw_per_pyeong": 2500000,
                 "operating_days_per_month": 26, "source": "테스트", "as_of": "2026-07-01"}
    },
}


def test_missing_is_empty_when_everything_registered():
    params = PolicyParams(FULL)
    assert params.missing("카페") == []


def test_missing_lists_null_entries():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.annual_rate_percent"]["value"] = None
    params = PolicyParams(raw)
    assert params.missing("카페") == ["loan.annual_rate_percent"]


def test_missing_lists_unregistered_industry():
    params = PolicyParams(FULL)
    assert params.missing("치킨집") == ["industries.치킨집"]


def test_missing_lists_partial_industry_fields():
    raw = json.loads(json.dumps(FULL))
    del raw["industries"]["카페"]["labor_ratio"]
    params = PolicyParams(raw)
    assert params.missing("카페") == ["industries.카페.labor_ratio"]


def test_value_returns_registered_number():
    assert PolicyParams(FULL).value("loan.term_months") == 60


def test_value_raises_on_missing():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.term_months"]["value"] = None
    with pytest.raises(KeyError):
        PolicyParams(raw).value("loan.term_months")


def test_industry_returns_field_map():
    assert PolicyParams(FULL).industry("카페")["cogs_ratio"] == 0.35


def test_shipped_config_has_no_registered_values():
    """커밋된 설정은 값이 비어 있어야 한다 — 임의 값 커밋 방지."""
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "config" / "policy-params.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    params = PolicyParams(raw)
    assert params.missing("카페") != []
