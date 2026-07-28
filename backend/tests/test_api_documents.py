"""문서 엔드포인트. 카탈로그는 Supabase 가 없으면 빈 목록이므로 조회 함수를 직접 갈아 끼운다."""
import pytest
from fastapi.testclient import TestClient

from app import main

PRODUCT = {"id": "kb-1", "name": "KB 소호모바일대출", "loan_limit": "최대 1억원",
           "rate_min": 3.9, "rate_max": 5.2, "source_as_of": "2026-07",
           "official_url": "https://obank.kbstar.com/example"}
PROGRAM = {"id": "pg-1", "title": "소상공인 정책자금", "organization": "소상공인시장진흥공단",
           "application_period": "2026-08-01 ~ 2026-08-31",
           "official_url": "https://www.semas.or.kr/example"}
CASE_INPUTS = {"industry": "카페", "district": "강남구", "budget_krw": 100_000_000,
               "equity_krw": 100_000_000, "business_stage": "PRE_OPEN",
               "startup_type": "INDEPENDENT", "priority": "STABILITY"}
FACTS = {"industry": "카페", "monthly_rent_krw": 2_500_000, "equity_krw": 100_000_000}


@pytest.fixture()
def client(monkeypatch):
    async def products():
        return [PRODUCT]

    async def programs():
        return [PROGRAM]

    monkeypatch.setattr(main.knowledge, "kb_products", products)
    monkeypatch.setattr(main.knowledge, "programs", programs)
    with TestClient(main.app) as test_client:
        test_client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield test_client


def make_case(client) -> str:
    response = client.post("/api/v1/cases", json={"title": "강남구 카페", "inputs": CASE_INPUTS})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_unconfirmed_requests_are_still_refused(client):
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={"case_id": case_id, "template": "funding", "confirmed": False})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_a_document_is_created_without_any_selection(client):
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={"case_id": case_id, "template": "funding", "confirmed": True})
    assert response.status_code == 201, response.text
    assert "제외" not in response.json()["message"]


def test_unknown_ids_are_dropped_and_counted_in_the_message(client):
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1", "kb-does-not-exist"],
        "selected_program_ids": ["pg-gone"]})
    assert response.status_code == 201, response.text
    assert "2건" in response.json()["message"]
    assert "확인되지 않아 제외" in response.json()["message"]


def test_the_document_downloads_as_a_pdf(client):
    case_id = make_case(client)
    created = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1"], "funding_input": FACTS})
    document_id = created.json()["document_id"]
    downloaded = client.get(f"/api/v1/documents/{document_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF")


def test_a_mismatched_industry_does_not_break_the_request(client):
    """등록되지 않은 업종이면 조달 요약만 빠지고 문서는 그대로 만들어진다."""
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True,
        "funding_input": {**FACTS, "industry": "존재하지않는업종"}})
    assert response.status_code == 201, response.text
