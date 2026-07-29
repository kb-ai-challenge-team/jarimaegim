"""문서 엔드포인트. 카탈로그는 Supabase 가 없으면 빈 목록이므로 조회 함수를 직접 갈아 끼운다."""
import pytest
from fastapi.testclient import TestClient

from app import main

# 두 픽스처는 파이프라인이 실제로 싣는 행 모양이다. KB는 pipeline/policy/normalize.py 의
# _kb_display(:351-363), 공고는 _program_display(:163-176) 가 만드는 display dict 를 따른다.
# 그 두 함수가 바뀌면 이 픽스처도 함께 바뀌어야 한다.
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


@pytest.fixture()
def rendered(monkeypatch):
    """render_case_pdf 에 실제로 넘어간 kwargs. 엔드포인트가 되찾은 값을 렌더러까지
    들려 보내는지는 상태코드로 알 수 없어 이 자리에서 확인한다."""
    captured: dict = {}
    original = main.render_case_pdf

    def spy(case, descriptor, **kwargs):
        captured.update(kwargs)
        return original(case, descriptor, **kwargs)

    monkeypatch.setattr(main, "render_case_pdf", spy)
    return captured


def make_case(client, **overrides) -> str:
    response = client.post("/api/v1/cases", json={"title": "강남구 카페", "inputs": {**CASE_INPUTS, **overrides}})
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


def test_an_unregistered_industry_does_not_break_the_request(client, rendered):
    """등록되지 않은 업종이면 조달 요약만 빠지고 문서는 그대로 만들어진다.

    업종은 케이스에서 온다(요청이 보낸 값은 무시된다). 그래서 미등록 경로를 타려면
    케이스 자체의 업종이 미등록이어야 한다."""
    case_id = make_case(client, industry="존재하지않는업종")
    response = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True, "funding_input": FACTS})
    assert response.status_code == 201, response.text
    assert rendered["funding"] is None
    assert "업종 파라미터가 등록되지 않아" in response.json()["message"]


def test_the_chosen_product_reaches_the_renderer(client, rendered):
    """되찾은 카탈로그 항목이 렌더러까지 실제로 도달하는지 — 201 만으로는 알 수 없다."""
    client.post("/api/v1/documents", json={
        "case_id": make_case(client), "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1"], "funding_input": FACTS})
    assert [item["name"] for item in rendered["products"]] == ["KB 소호모바일대출"]
    assert rendered["funding"]["bands"]


def test_the_chosen_program_reaches_the_renderer(client, rendered):
    client.post("/api/v1/documents", json={
        "case_id": make_case(client), "template": "funding", "confirmed": True,
        "selected_program_ids": ["pg-1"]})
    assert [item["title"] for item in rendered["programs"]] == ["소상공인 정책자금"]


def test_the_case_industry_and_equity_win_over_the_request(client, rendered):
    """요청이 보낸 업종·자기자본은 무시하고 케이스의 확정값으로 계산한다 — 문서의
    '사용자 확인값' 블록과 그 아래 조달 요약이 다른 조건 위에 서면 안 되기 때문이다."""
    case_id = make_case(client)  # 카페 · 자기자본 1억
    response = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True,
        "funding_input": {**FACTS, "industry": "존재하지않는업종", "equity_krw": 500_000_000}})
    assert response.status_code == 201, response.text
    # 요청의 업종을 썼다면 미등록으로 걸려 None 이었을 것이다.
    assert rendered["funding"] is not None
    equity_only = next(band for band in rendered["funding"]["bands"] if band["band"] == "EQUITY_ONLY")
    assert equity_only["ceiling_krw"] == CASE_INPUTS["equity_krw"]


def test_a_duplicated_id_renders_once_and_reports_no_drop(client, rendered):
    response = client.post("/api/v1/documents", json={
        "case_id": make_case(client), "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1", "kb-1"]})
    assert len(rendered["products"]) == 1
    assert "제외" not in response.json()["message"]
    assert "담지 못했습니다" not in response.json()["message"]


def test_a_catalog_that_failed_to_load_does_not_claim_the_id_is_absent(client, rendered, monkeypatch):
    """조회 실패도 빈 목록으로 내려온다(knowledge.py:34-40). 그때 '공시 목록에서 확인되지
    않았다'고 적으면 카탈로그 내용에 대한 거짓 주장이 은행에 가져갈 PDF 에 찍힌다."""
    async def empty():
        return []

    monkeypatch.setattr(main.knowledge, "kb_products", empty)
    response = client.post("/api/v1/documents", json={
        "case_id": make_case(client), "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1"]})
    assert response.status_code == 201, response.text
    message = response.json()["message"]
    assert "불러오지 못해" in message and "1건" in message
    assert "확인되지 않아 제외" not in message
    assert rendered["unavailable"] is True


def test_a_populated_catalog_still_reports_a_real_miss_as_a_miss(client):
    response = client.post("/api/v1/documents", json={
        "case_id": make_case(client), "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-gone"]})
    assert "확인되지 않아 제외" in response.json()["message"]
    assert "불러오지 못해" not in response.json()["message"]


def test_only_the_catalog_that_was_asked_for_is_fetched(client, monkeypatch):
    """고르지 않은 쪽의 카탈로그는 건드리지 않는다."""
    calls: list[str] = []

    async def programs():
        calls.append("programs")
        return [PROGRAM]

    monkeypatch.setattr(main.knowledge, "programs", programs)
    client.post("/api/v1/documents", json={
        "case_id": make_case(client), "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1"]})
    assert calls == []


def test_markup_in_a_case_input_does_not_500_the_endpoint(client):
    """reportlab 의 Paragraph 는 미니 HTML 을 파싱한다. 케이스에 적힌 <b> 가 그대로 들어가면
    ValueError 가 나는데 create_document 는 OSError 만 잡으므로 그대로 500 이 된다."""
    case_id = make_case(client, industry="<b>카페")
    response = client.post("/api/v1/documents",
                           json={"case_id": case_id, "template": "funding", "confirmed": True})
    assert response.status_code == 201, response.text


def test_an_absent_funding_input_says_why_the_summary_is_missing(client):
    response = client.post("/api/v1/documents", json={
        "case_id": make_case(client), "template": "funding", "confirmed": True})
    assert "조달 입력이 없어" in response.json()["message"]
