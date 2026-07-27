from fastapi.testclient import TestClient

from app.main import app, listings_service

# A district the demo data deliberately does not cover; derived so it survives coverage growth.
UNCOVERED = next(d for d in ["관악구", "금천구", "양천구"] if d not in listings_service.covered_districts())


def new_case(client: TestClient, district: str = "강남구", budget: int = 100_000_000) -> str:
    client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
    response = client.post("/api/v1/cases", json={
        "title": "테스트 케이스",
        "inputs": {"industry": "카페", "district": district, "budget_krw": budget, "equity_krw": 30_000_000,
                   "business_stage": "PRE_OPEN", "startup_type": "INDEPENDENT", "priority": "STABILITY"},
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_a_covered_district_returns_labelled_listings():
    with TestClient(app) as client:
        case_id = new_case(client)
        response = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": "강남구", "limit": 15})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success"
        assert len(body["candidates"]) > 0
        for candidate in body["candidates"]:
            assert candidate["listing"]["listing_kind"] == "DEMO_SYNTHETIC"
            assert candidate["evidence_grade"] == "C"


def test_an_uncovered_district_returns_an_empty_state_not_an_error():
    with TestClient(app) as client:
        case_id = new_case(client, district=UNCOVERED)
        response = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": UNCOVERED, "limit": 15})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["candidates"] == []
        assert body["status"] == "empty"
        assert body["message"]


def test_a_mismatched_district_is_still_rejected():
    with TestClient(app) as client:
        case_id = new_case(client, district="강남구")
        response = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": "마포구", "limit": 15})
        assert response.status_code == 400
