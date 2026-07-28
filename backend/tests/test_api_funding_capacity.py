import json
import pytest
from fastapi.testclient import TestClient

BODY = {"equity_krw": 50_000_000, "existing_debt_krw": 0}

FILLED = {
    "schema_version": 1, "updated_at": "2026-07-27",
    "entries": {
        "loan.guarantee_ceiling_krw": {"value": 70_000_000, "verified": True, "source": "테스트", "as_of": "2026-07-01"},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000, "verified": True, "source": "테스트", "as_of": "2026-07-01"},
    },
    "industries": {},
}


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as instance:
        instance.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield instance


@pytest.fixture
def filled_params(tmp_path, monkeypatch):
    path = tmp_path / "policy-params.json"
    path.write_text(json.dumps(FILLED, ensure_ascii=False), encoding="utf-8")
    import app.main as main
    from app.policy_params import PolicyParams
    monkeypatch.setattr(main, "policy_params", PolicyParams.load(path))
    return path


@pytest.fixture
def demo_params(tmp_path, monkeypatch):
    raw = json.loads(json.dumps(FILLED))
    raw["entries"]["loan.policy_fund_ceiling_krw"]["basis"] = "DEMO_ASSUMPTION"
    path = tmp_path / "demo-params.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    import app.main as main
    from app.policy_params import PolicyParams
    monkeypatch.setattr(main, "policy_params", PolicyParams.load(path))
    return path


def test_requires_a_session():
    from app.main import app
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/v1/funding-capacity", json=BODY).status_code == 401


def test_needs_no_case(client, filled_params):
    """1단계는 케이스 생성 전에 돈다. 케이스를 요구하면 단계 분리가 성립하지 않는다."""
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert payload["status"] == "computed"
    assert payload["maximum_line_krw"] == 140_000_000


def test_reports_the_three_lines(client, filled_params):
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert payload["equity_line_krw"] == 50_000_000
    assert payload["borrowing_headroom_krw"] == 90_000_000
    assert payload["maximum_line_krw"] == 140_000_000


def test_says_why_the_recommended_line_is_not_here_yet(client, filled_params):
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert "업종" in payload["recommended_line_pending"]
    assert "월세" in payload["recommended_line_pending"]


def test_existing_debt_shrinks_the_headroom(client, filled_params):
    payload = client.post("/api/v1/funding-capacity",
                          json={**BODY, "existing_debt_krw": 200_000_000}).json()
    assert payload["borrowing_headroom_krw"] == 0
    assert payload["maximum_line_krw"] == 50_000_000


def test_unregistered_ceilings_yield_integration_pending(client):
    """배포 설정에 한도가 없으면 추정하지 않고 무엇이 빈지 말한다."""
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    if payload["status"] == "integration_pending":
        assert len(payload["missing_params"]) > 0
        assert payload["message"]
        assert payload["maximum_line_krw"] == 0


def test_demo_parameters_are_labelled(client, demo_params):
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert payload["parameter_status"] == "DEMO"
    assert "loan.policy_fund_ceiling_krw" in payload["unverified_params"]
    assert any("시연용" in item for item in payload["provenance"]["limitations"])


def test_rejects_a_negative_equity(client):
    response = client.post("/api/v1/funding-capacity", json={**BODY, "equity_krw": -1})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
