"""제도 파라미터의 성격(basis)이 계산 결과까지 따라가는지 확인한다.

값이 등록돼 있다는 것과 근거가 있다는 것은 다르다. 지금 등록된 대출 만기·보증한도·
정책자금 한도와 업종 원가 구조는 **시연용 가정값**이고, 그 위에서 나온 조달선과 목표
일매출은 사용자가 가장 구체적인 숫자로 받아들이는 값이다. 성격을 감추면 가장 크게
오해되므로, 고지가 빠지면 테스트가 깨져야 한다.
"""

import pytest
from fastapi.testclient import TestClient

from app.policy_params import PolicyParams

RAW = {
    "updated_at": "2026-07-28",
    "entries": {
        "loan.annual_rate_percent": {"value": 4.45, "basis": "PUBLISHED", "label": "공시 금리"},
        "loan.term_months": {"value": 60, "basis": "DEMO_ASSUMPTION", "label": "시연용 가정 — 만기"},
        "loan.guarantee_ceiling_krw": {"value": 100_000_000, "basis": "DEMO_ASSUMPTION", "label": "시연용 가정 — 보증한도"},
        "loan.policy_fund_ceiling_krw": {"value": 70_000_000, "basis": "DEMO_ASSUMPTION", "label": "시연용 가정 — 정책자금"},
        "stress.revenue_drop_ratio": {"value": 0.2, "basis": "DESIGN_DECISION", "label": "설계 결정"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "basis": "DESIGN_DECISION", "label": "설계 결정"},
        "working_capital.months": {"value": 3, "basis": "DESIGN_DECISION", "label": "설계 결정"},
    },
    "industries": {
        "CS100010": {"cogs_ratio": 0.32, "labor_ratio": 0.24, "fitout_krw_per_pyeong": 2_400_000,
                     "operating_days_per_month": 29, "basis": "DEMO_ASSUMPTION", "label": "시연용 가정 — 업종"},
    },
}


@pytest.fixture
def params():
    return PolicyParams(RAW)


def test_a_free_text_industry_resolves_to_its_service_code(params):
    """'카페'와 '커피'가 서로 다른 업종이 되면 같은 업종인데 한쪽만 계산된다."""
    assert params.missing("카페") == []
    assert params.missing("커피") == []
    assert params.industry("cafe")["cogs_ratio"] == 0.32


def test_an_unmappable_industry_is_still_reported_missing(params):
    gaps = params.missing("우주선정비소")
    assert gaps == ["industries.우주선정비소"]


def test_assumed_lists_every_demo_value_in_play(params):
    assumed = params.assumed("카페")
    assert set(assumed) == {"loan.term_months", "loan.guarantee_ceiling_krw",
                            "loan.policy_fund_ceiling_krw", "industries.CS100010"}


def test_published_and_design_values_are_not_reported_as_assumptions(params):
    assert "loan.annual_rate_percent" not in params.assumed("카페")
    assert "stress.revenue_drop_ratio" not in params.assumed("카페")


def test_assumed_is_empty_when_every_value_is_sourced():
    sourced = {"entries": {key: {**entry, "basis": "PUBLISHED"} for key, entry in RAW["entries"].items()},
               "industries": {"CS100010": {**RAW["industries"]["CS100010"], "basis": "PUBLISHED"}}}
    assert PolicyParams(sourced).assumed("카페") == []


def test_sources_uses_short_labels_not_the_full_prose(params):
    """좁은 패널에 문단을 실으면 정작 읽어야 할 경고가 그 안에 묻힌다."""
    for label in params.sources("카페"):
        assert len(label) < 60, f"출처 라벨이 너무 깁니다: {label}"


def test_industry_label_uses_the_official_industry_name(params):
    assert params.industry_label("카페") == "커피-음료"
    assert params.industry_label("우주선정비소") == "우주선정비소"


def test_missing_params_still_block_the_calculation():
    blank = {"entries": {**RAW["entries"], "loan.term_months": {"value": None}}, "industries": RAW["industries"]}
    assert "loan.term_months" in PolicyParams(blank).missing("카페")


def client():
    from app.main import app
    return TestClient(app)


def session_and_case(c: TestClient) -> str:
    c.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
    return c.post("/api/v1/cases", json={
        "title": "t", "inputs": {"industry": "카페", "district": "강남구", "budget_krw": 150_000_000,
                                 "equity_krw": 80_000_000, "business_stage": "PRE_OPEN",
                                 "startup_type": "INDEPENDENT", "priority": "DEMAND"}}).json()["id"]


def test_the_api_discloses_demo_assumptions_and_drops_confidence():
    from app.main import policy_params
    if not policy_params.assumed("카페"):
        return  # 제도값이 전부 공시로 대체되면 이 경로는 사라진다.
    with TestClient(__import__("app.main", fromlist=["app"]).app) as c:
        case_id = session_and_case(c)
        body = c.post("/api/v1/funding-bands", json={
            "case_id": case_id, "industry": "카페", "area_pyeong": 17.5, "deposit_krw": 51_000_000,
            "monthly_rent_krw": 3_090_000, "monthly_maintenance_krw": 250_000, "key_money_krw": 27_000_000,
            "equity_krw": 80_000_000, "existing_debt_krw": 0, "other_monthly_fixed_krw": 0}).json()
        assert body["status"] == "computed"
        # 값이 있다는 이유로 신뢰도가 올라가 보이면 안 된다.
        assert body["provenance"]["confidence"] == "INSUFFICIENT"
        assert any("시연용 가정값" in item for item in body["provenance"]["limitations"])
        assert any("시연용 가정값" in item for item in body["break_even"]["assumptions"])
