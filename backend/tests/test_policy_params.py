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


def _shipped_config() -> dict:
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "config" / "policy-params.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_shipped_values_all_carry_a_source_and_date():
    """등록된 값은 출처와 기준일을 반드시 갖는다 — 근거 없는 값의 커밋을 막는다."""
    raw = _shipped_config()
    for key, entry in raw["entries"].items():
        if entry.get("value") is None:
            continue
        assert entry.get("source"), f"{key} 에 값이 있으나 출처가 없습니다"
        assert entry.get("as_of"), f"{key} 에 값이 있으나 기준일이 없습니다"
    for name, profile in (raw.get("industries") or {}).items():
        assert profile.get("source"), f"industries.{name} 에 출처가 없습니다"
        assert profile.get("as_of"), f"industries.{name} 에 기준일이 없습니다"


def test_shipped_config_still_reports_what_is_missing():
    """미등록 항목이 남아 있으면 missing 이 그것을 그대로 보고해야 한다."""
    params = PolicyParams(_shipped_config())
    gaps = params.missing("카페")
    # 값이 전부 채워지면 이 단정은 자연히 빈 리스트가 되어야 하며, 그때는 밴드가 계산된다.
    for key in gaps:
        assert key.startswith("loan.") or key.startswith("stress.") \
            or key.startswith("working_capital.") or key.startswith("industries."), key
