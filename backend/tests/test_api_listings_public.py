from fastapi.testclient import TestClient

from app.main import app, listings_service

# Derived, not hard-coded: coverage grows, and a test that pins the count to a literal
# goes stale every time a district is added.
COVERED = sorted(listings_service.covered_districts())
UNCOVERED = "관악구"


def test_summary_needs_no_session():
    with TestClient(app) as client:
        response = client.get("/api/v1/listings/summary")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["districts"]) == len(COVERED)
        assert all(entry["count"] > 0 for entry in body["districts"])
        assert "Set-Cookie" not in response.headers


def test_summary_entries_carry_a_pin_position():
    with TestClient(app) as client:
        entry = client.get("/api/v1/listings/summary").json()["districts"][0]
        assert 37.0 < entry["latitude"] < 38.0
        assert 126.0 < entry["longitude"] < 128.0
        assert entry["median_monthly_rent_krw"] > 0


def test_listings_for_a_covered_district_need_no_session():
    with TestClient(app) as client:
        response = client.get("/api/v1/listings", params={"district": "강남구", "limit": 15})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success"
        assert len(body["candidates"]) == 15
        for candidate in body["candidates"]:
            assert candidate["listing"]["listing_kind"] == "DEMO_SYNTHETIC"
        assert "Set-Cookie" not in response.headers


def test_listings_for_an_uncovered_district_explain_the_coverage():
    with TestClient(app) as client:
        body = client.get("/api/v1/listings", params={"district": UNCOVERED}).json()
        assert body["candidates"] == []
        assert body["status"] == "empty"
        assert COVERED[0] in body["message"]


def test_listings_reject_a_district_outside_seoul():
    with TestClient(app) as client:
        assert client.get("/api/v1/listings", params={"district": "부산 해운대구"}).status_code == 400


def test_listings_reject_an_out_of_range_limit_the_same_way_as_any_bad_input():
    with TestClient(app) as client:
        response = client.get("/api/v1/listings", params={"district": "강남구", "limit": 500})
        # The app's RequestValidationError handler maps every malformed parameter to 400,
        # so an out-of-range limit must not invent a different status.
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"
