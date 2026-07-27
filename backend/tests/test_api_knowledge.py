import pytest
from fastapi.testclient import TestClient

from app.main import app

# TestClient는 쿠키를 유지한다. 세션을 두 번 만들면 엔드포인트가 409 SESSION_EXISTS를
# 내므로, 세션이 필요한 테스트는 이 클라이언트를 공유한다.
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def anonymous_session():
    response = client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
    assert response.status_code == 201


def test_status_reports_index_freshness():
    body = client.get("/api/v1/status").json()
    assert "knowledge_index" in body
    index = body["knowledge_index"]
    assert set(index) >= {"documents", "missing_embeddings", "last_collected_at"}
    assert "retrieval" in body["integrations"]


def test_search_requires_a_session():
    # 쿠키를 공유하지 않는 별도 클라이언트여야 인증 요구가 실제로 확인된다.
    with TestClient(app) as anonymous:
        response = anonymous.get("/api/v1/knowledge/search", params={"q": "창업"})
    assert response.status_code == 401


def test_search_returns_a_documented_status():
    body = client.get("/api/v1/knowledge/search", params={"q": "창업"}).json()
    assert body["status"] in {"success", "integration_pending", "unavailable"}
    assert body["evidence_grade"] == "C"
    assert isinstance(body["items"], list)


def test_search_rejects_a_district_outside_seoul():
    response = client.get("/api/v1/knowledge/search", params={"q": "창업", "district": "수원시"})
    assert response.status_code == 400


def test_search_rejects_an_unknown_document_kind():
    response = client.get("/api/v1/knowledge/search", params={"q": "창업", "kind": "SOMETHING"})
    assert response.status_code == 400


def test_program_catalog_items_keep_the_frontend_contract():
    body = client.get("/api/v1/programs/catalog").json()
    assert body["status"] in {"success", "integration_pending"}
    for item in body["items"]:
        assert set(item) == {"id", "category", "title", "organization", "status",
                             "application_period", "matched_conditions",
                             "unknown_conditions", "official_url", "source_as_of"}
        # 유니온 밖의 값이 새면 UI가 렌더하지 못한다.
        assert item["status"] in {"ELIGIBLE_PRECHECK", "CONDITIONAL", "MANUAL_CHECK",
                                  "CLOSED", "UNKNOWN"}
        assert item["category"] in {"GOVERNMENT", "POLICY_FUND", "GUARANTEE", "PRIVATE"}


def test_kb_product_items_keep_the_frontend_contract():
    body = client.get("/api/v1/products/kb").json()
    assert body["status"] in {"success", "integration_pending"}
    for item in body["items"]:
        assert set(item) == {"id", "name", "category", "category_label", "rate_kind",
                             "organization", "product_type", "rate_min", "rate_max", "rate_avg",
                             "rate_type", "loan_limit", "join_way", "repay_type",
                             "source_as_of", "official_url", "unknown_conditions"}
        assert item["category"] in {"BUSINESS_LOAN", "CREDIT_LOAN", "MORTGAGE_LOAN",
                                    "RENT_LOAN", "DEPOSIT", "SAVING"}
        # 공시되지 않은 금리는 0이 아니라 null이어야 한다.
        for field in ("rate_min", "rate_max", "rate_avg"):
            assert item[field] is None or isinstance(item[field], (int, float))
