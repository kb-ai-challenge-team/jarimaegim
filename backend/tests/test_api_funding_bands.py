import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

CASE = {"title": "테스트", "inputs": {"industry": "카페", "district": "강남구", "budget_krw": 150_000_000,
        "equity_krw": 100_000_000, "business_stage": "PRE_OPEN", "startup_type": "INDEPENDENT",
        "priority": "STABILITY"}}

BODY = {"industry": "카페", "area_pyeong": 15.0, "deposit_krw": 100_000_000, "monthly_rent_krw": 2_500_000,
        "monthly_maintenance_krw": 300_000, "key_money_krw": 0, "fitout_krw": None,
        "equity_krw": 100_000_000, "existing_debt_krw": 0, "other_monthly_fixed_krw": 1_000_000}

FILLED = {
    "schema_version": 1, "updated_at": "2026-07-27",
    "entries": {
        "loan.annual_rate_percent": {"value": 4.5, "source": "테스트", "as_of": "2026-07-01"},
        "loan.term_months": {"value": 60, "source": "테스트", "as_of": "2026-07-01"},
        "loan.guarantee_ceiling_krw": {"value": 70_000_000, "source": "테스트", "as_of": "2026-07-01"},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000, "source": "테스트", "as_of": "2026-07-01"},
        "stress.revenue_drop_ratio": {"value": 0.2, "source": "테스트", "as_of": "2026-07-01"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "source": "테스트", "as_of": "2026-07-01"},
        "working_capital.months": {"value": 3, "source": "테스트", "as_of": "2026-07-01"},
    },
    "industries": {"카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20, "fitout_krw_per_pyeong": 2_500_000,
                            "operating_days_per_month": 26, "source": "테스트", "as_of": "2026-07-01"}},
}


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as instance:
        instance.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield instance


@pytest.fixture
def case_id(client):
    return client.post("/api/v1/cases", json=CASE).json()["id"]


@pytest.fixture
def filled_params(tmp_path, monkeypatch):
    path = tmp_path / "policy-params.json"
    path.write_text(json.dumps(FILLED, ensure_ascii=False), encoding="utf-8")
    import app.main as main
    from app.policy_params import PolicyParams
    monkeypatch.setattr(main, "policy_params", PolicyParams.load(path))
    return path


def test_requires_a_session(case_id):
    from app.main import app
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY})
    assert response.status_code == 401


def test_rejects_a_case_owned_by_another_session(client):
    from uuid import uuid4
    response = client.post("/api/v1/funding-bands", json={"case_id": str(uuid4()), **BODY})
    assert response.status_code == 404


def test_returns_integration_pending_while_parameters_are_unregistered(client, case_id, monkeypatch):
    """제도 파라미터가 비면 추정하지 않고 누락 목록을 돌려준다.

    지켜야 하는 규칙은 "누락이 있으면 계산하지 않고 무엇이 빈지 알려준다"이지 "지금 파라미터가
    비어 있다"가 아니다. 그래서 등록 상태에 기대지 않고 빈 파라미터를 직접 주입해 규칙만
    확인한다 — 실제 config 가 채워져도 이 규칙은 살아 있어야 한다."""
    import app.main as main
    from app.policy_params import PolicyParams

    monkeypatch.setattr(main, "policy_params", PolicyParams({}))
    response = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "integration_pending"
    assert payload["bands"] == []
    assert payload["break_even"] is None
    assert payload["missing_params"]
    assert payload["message"]


def test_returns_integration_pending_for_an_unregistered_industry(client, case_id):
    """업종 프로파일이 없으면 비슷한 업종으로 대신 계산하지 않는다. 누락은 업종 단위로도 성립한다."""
    response = client.post("/api/v1/funding-bands",
                           json={"case_id": case_id, **{**BODY, "industry": "우주정거장"}})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "integration_pending"
    assert payload["bands"] == []
    assert payload["break_even"] is None
    assert "industries.우주정거장" in payload["missing_params"]
    assert payload["message"]


def test_the_shipped_config_computes_and_says_its_values_are_assumed(client, case_id):
    """등록이 끝나면 밴드가 나와야 하고, 그 값이 시연용 가정이라는 사실도 함께 나가야 한다."""
    from app.main import policy_params

    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    if policy_params.missing(BODY["industry"]):
        return  # 아직 등록 전인 환경. 위 테스트가 그 경로를 지킨다.
    assert payload["status"] in {"computed", "partial"}
    assert payload["bands"]
    if policy_params.assumed(BODY["industry"]):
        assert payload["provenance"]["confidence"] == "INSUFFICIENT"
        assert any("시연용 가정값" in item for item in payload["provenance"]["limitations"])


def test_computes_three_bands_when_params_are_registered(client, case_id, filled_params):
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    assert payload["status"] == "computed"
    assert [band["band"] for band in payload["bands"]] == ["EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"]
    assert payload["break_even"]["target_daily_revenue_krw"] > 0
    assert payload["provenance"]["confidence"] == "LOW"


def test_bands_report_the_parameter_grade(client, case_id, filled_params):
    """검증된 파라미터로 계산하면 시연용 표시가 붙지 않는다."""
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    assert payload["parameter_status"] == "VERIFIED"
    assert payload["unverified_params"] == []


def test_changing_equity_changes_the_bands(client, case_id, filled_params):
    low = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    high = client.post("/api/v1/funding-bands",
                       json={"case_id": case_id, **{**BODY, "equity_krw": 200_000_000}}).json()
    assert high["bands"][2]["ceiling_krw"] > low["bands"][2]["ceiling_krw"]


def test_changing_rent_changes_the_target_revenue(client, case_id, filled_params):
    cheap = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    dear = client.post("/api/v1/funding-bands",
                       json={"case_id": case_id, **{**BODY, "monthly_rent_krw": 5_000_000}}).json()
    assert dear["break_even"]["target_monthly_revenue_krw"] > cheap["break_even"]["target_monthly_revenue_krw"]


def test_unregistered_industry_is_reported_as_missing(client, case_id, filled_params):
    payload = client.post("/api/v1/funding-bands",
                          json={"case_id": case_id, **{**BODY, "industry": "치킨집"}}).json()
    assert payload["status"] == "integration_pending"
    assert "industries.치킨집" in payload["missing_params"]


def test_bands_are_computed_without_area_and_deposit(client, case_id, filled_params):
    """평수·보증금은 필요자금(→현금소진)에만 쓰인다. 없다고 밴드 전체를 막지 않는다."""
    body = {k: v for k, v in BODY.items() if k not in ("area_pyeong", "deposit_krw")}
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **body}).json()
    assert payload["status"] == "partial"
    assert [band["band"] for band in payload["bands"]] == ["EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"]
    assert payload["break_even"]["target_daily_revenue_krw"] > 0
    assert payload["missing_params"] == ["희망 평수", "희망 보증금"]


def test_partial_bands_report_no_runway_and_no_required_capital(client, case_id, filled_params):
    body = {k: v for k, v in BODY.items() if k not in ("area_pyeong", "deposit_krw")}
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **body}).json()
    assert payload["required_capital_krw"] is None
    assert payload["required_capital_band"] is None
    assert all(band["runway_months"] is None for band in payload["bands"])


def test_partial_bands_match_the_full_run_on_every_rent_driven_figure(client, case_id, filled_params):
    """평수·보증금은 상한·상환·목표매출에 관여하지 않는다. 두 응답이 그 축에서 같아야 한다."""
    body = {k: v for k, v in BODY.items() if k not in ("area_pyeong", "deposit_krw")}
    partial = client.post("/api/v1/funding-bands", json={"case_id": case_id, **body}).json()
    full = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    keys = ("ceiling_krw", "loan_krw", "monthly_repayment_krw", "target_daily_revenue_krw", "stress_pass")
    assert [{k: band[k] for k in keys} for band in partial["bands"]] == \
           [{k: band[k] for k in keys} for band in full["bands"]]


def test_only_the_deposit_missing_still_yields_partial(client, case_id, filled_params):
    body = {k: v for k, v in BODY.items() if k != "deposit_krw"}
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **body}).json()
    assert payload["status"] == "partial"
    assert payload["missing_params"] == ["희망 보증금"]


def test_partial_result_states_what_it_did_not_calculate(client, case_id, filled_params):
    """추정으로 메우지 않았다는 사실이 화면에 붙을 수 있어야 한다."""
    body = {k: v for k, v in BODY.items() if k not in ("area_pyeong", "deposit_krw")}
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **body}).json()
    assert any("추정하지 않습니다" in item for item in payload["provenance"]["limitations"])
    assert any("계산하지 않았습니다" in item for item in payload["break_even"]["assumptions"])


def test_rejects_a_non_positive_area(client, case_id):
    """이 앱은 요청 검증 오류를 400 VALIDATION_ERROR로 정규화한다 (main.py:54 validation_handler)."""
    response = client.post("/api/v1/funding-bands", json={"case_id": case_id, **{**BODY, "area_pyeong": 0}})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(field["path"].endswith("area_pyeong") for field in body["error"]["details"]["fields"])
