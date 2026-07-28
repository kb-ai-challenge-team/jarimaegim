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


def test_assumed_is_empty_when_nothing_is_flagged():
    """basis 가 없는 항목은 가정값으로 보지 않는다 — 배포 설정은 별도 테스트가 명시를 강제한다."""
    assert PolicyParams(FULL).assumed("카페") == []


def test_assumed_lists_demo_entries():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.policy_fund_ceiling_krw"]["basis"] = "DEMO_ASSUMPTION"
    assert PolicyParams(raw).assumed("카페") == ["loan.policy_fund_ceiling_krw"]


def test_assumed_lists_a_demo_industry():
    raw = json.loads(json.dumps(FULL))
    raw["industries"]["카페"]["basis"] = "DEMO_ASSUMPTION"
    assert PolicyParams(raw).assumed("카페") == ["industries.카페"]


def test_assumed_ignores_industries_other_than_the_one_asked_for():
    raw = json.loads(json.dumps(FULL))
    raw["industries"]["분식점"] = {"cogs_ratio": 0.4, "labor_ratio": 0.2, "fitout_krw_per_pyeong": 1,
                                   "operating_days_per_month": 26, "basis": "DEMO_ASSUMPTION",
                                   "source": "테스트", "as_of": "2026-07-01"}
    assert PolicyParams(raw).assumed("카페") == []


def test_missing_of_reports_only_the_keys_asked_for():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.term_months"]["value"] = None
    params = PolicyParams(raw)
    assert params.missing_of(("loan.guarantee_ceiling_krw",)) == []
    assert params.missing_of(("loan.term_months",)) == ["loan.term_months"]


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


BASES = ("PUBLISHED", "DESIGN_DECISION", "DEMO_ASSUMPTION")


def test_shipped_entries_state_their_basis_explicitly():
    """basis 를 빼먹으면 시연용 가정값이 공시값으로 조용히 통과한다. 명시를 강제한다."""
    raw = _shipped_config()
    for key, entry in raw["entries"].items():
        assert entry.get("basis") in BASES, f"{key} 에 basis 가 없습니다"
    for name, profile in (raw.get("industries") or {}).items():
        assert profile.get("basis") in BASES, f"industries.{name} 에 basis 가 없습니다"


def test_shipped_demo_values_say_so_in_their_source():
    raw = _shipped_config()
    for key, entry in raw["entries"].items():
        if entry.get("verified") is False:
            assert "시연용" in (entry.get("source") or ""), f"{key} 출처가 시연용임을 밝히지 않습니다"


def test_shipped_industries_all_have_a_positive_contribution_margin():
    """공헌이익률이 0 이하면 compute_bands 가 ValueError 로 죽는다."""
    raw = _shipped_config()
    for name, profile in (raw.get("industries") or {}).items():
        margin = 1.0 - profile["cogs_ratio"] - profile["labor_ratio"]
        assert margin > 0, f"industries.{name} 의 공헌이익률이 {margin} 입니다"


def test_shipped_config_computes_bands_for_every_registered_industry():
    """등록해 놓고 계산이 안 되면 등록한 의미가 없다."""
    from app.funding import compute_bands
    params = PolicyParams(_shipped_config())
    for name in (_shipped_config().get("industries") or {}):
        assert params.missing(name) == []
        result = compute_bands(params, industry=name, area_pyeong=15.0, deposit_krw=50_000_000,
                               monthly_rent_krw=2_500_000, monthly_maintenance_krw=300_000,
                               key_money_krw=0, fitout_krw=None, equity_krw=100_000_000,
                               existing_debt_krw=0, other_monthly_fixed_krw=1_000_000)
        assert len(result["bands"]) == 3


def test_every_industry_the_extractor_can_emit_can_be_priced():
    """조건 추출이 내놓는 업종은 전부 밴드를 계산할 수 있어야 한다.

    추출은 됐는데 밴드가 막히는 조합이 생기면 사용자는 자기가 말한 업종이 왜 계산되지 않는지
    알 수 없다. 등록 여부를 이름으로 비교하지 않고 `missing()` 으로 묻는 이유는 배포 설정이
    업종 **코드**로 키를 잡기 때문이다 — 이름 비교로 바꾸면 코드 결합이 조용히 깨져도 통과한다.

    자유 입력과 NAMED_INDUSTRY 폴백은 어떤 명사든 낼 수 있으므로 미등록 업종 →
    integration_pending 경로는 등록을 아무리 늘려도 없어지지 않는 정상 상태다."""
    from app.condition_parse import INDUSTRY_HINTS

    params = PolicyParams(_shipped_config())
    unpriceable = [name for _, name in INDUSTRY_HINTS
                   if any(gap.startswith("industries.") for gap in params.missing(name))]
    assert unpriceable == []
