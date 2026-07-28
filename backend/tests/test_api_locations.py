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
            # 상권 통계를 붙인 후보는 B, 붙이지 못한 후보는 C 로 남는다. A 는 개별 이력이
            # 있어야 하므로 이 경로에서 나올 수 없다.
            assert candidate["evidence_grade"] in {"B", "C"}


def test_trade_area_candidates_carry_signals_and_a_fit_reason():
    """등급 B 후보는 근거 신호를, 판정 못 한 후보는 사유를 반드시 달고 나온다."""
    with TestClient(app) as client:
        case_id = new_case(client)
        body = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": "강남구", "limit": 15}).json()
        for candidate in body["candidates"]:
            fit = candidate["trade_area_fit"]
            if candidate["evidence_grade"] == "B":
                assert fit["status"] == "judged"
                assert candidate["context_signals"], "B등급인데 근거 신호가 없습니다"
                assert candidate["provenance"]["sample_n"], "B등급인데 표본 수가 없습니다"
            else:
                assert fit["status"] == "unavailable"
                assert fit["reason"], "판정하지 못한 이유가 비어 있습니다"


def test_judged_candidates_are_ordered_before_unjudged_ones():
    with TestClient(app) as client:
        case_id = new_case(client)
        body = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": "강남구", "limit": 15}).json()
        judged = [c["trade_area_fit"]["status"] == "judged" for c in body["candidates"]]
        # True 가 전부 앞에 몰려 있어야 한다 — 판정된 후보 뒤에 판정 못 한 후보가 붙는다.
        assert judged == sorted(judged, reverse=True)


def test_an_unmappable_industry_falls_back_without_inventing_a_verdict():
    with TestClient(app) as client:
        client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        case_id = client.post("/api/v1/cases", json={
            "title": "테스트", "inputs": {"industry": "우주선정비소", "district": "강남구", "budget_krw": 100_000_000,
                                       "equity_krw": 30_000_000, "business_stage": "PRE_OPEN",
                                       "startup_type": "INDEPENDENT", "priority": "STABILITY"}}).json()["id"]
        body = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "우주선정비소", "district": "강남구", "limit": 5}).json()
        assert body["status"] == "success"
        assert "업종 분류에 연결되지 않아" in body["message"]
        for candidate in body["candidates"]:
            assert candidate["evidence_grade"] == "C"
            assert candidate["context_signals"] == []


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
