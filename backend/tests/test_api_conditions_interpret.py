import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as instance:
        instance.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield instance


def test_requires_a_session():
    from app.main import app
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/v1/conditions/interpret", json={"text": "마포구 카페"})
    assert response.status_code == 401


def test_needs_no_case(client):
    """조건 추론은 케이스 생성 전에 돈다."""
    response = client.post("/api/v1/conditions/interpret",
                           json={"text": "마포구에서 카페를 준비 중이에요"})
    assert response.status_code == 200


def test_falls_back_to_the_rule_extractor_without_a_key(client, monkeypatch):
    """키 없는 환경에서도 흐름이 멈추지 않는다 — flow-check.mjs 가 이 경로를 돈다.

    AI 를 명시적으로 끈다. 개발 기계의 .env 에 키가 있으면 이 테스트가 실제 네트워크를 타고,
    그러면 시험하려던 폴백 경로 대신 AI 경로를 재는 테스트가 된다."""
    import app.main as main

    async def no_ai(text):
        return None
    monkeypatch.setattr(main.ai, "interpret_conditions", no_ai)
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "마포구에서 카페를 준비 중이에요"}).json()
    assert payload["source"] == "RULE"
    assert payload["fields"]["district"]["value"] == "마포구"
    assert payload["fields"]["industry"]["value"] == "카페"


def test_every_returned_evidence_is_in_the_user_text(client):
    text = "성동구에 2호점 낼 자리를 찾고 있고 월세는 400만원 정도 생각해요"
    payload = client.post("/api/v1/conditions/interpret", json={"text": text}).json()
    for field in payload["fields"].values():
        if field["evidence"] is not None:
            assert field["evidence"] in text


def test_reports_what_it_could_not_resolve(client):
    payload = client.post("/api/v1/conditions/interpret", json={"text": "안녕하세요"}).json()
    assert len(payload["unresolved"]) == 6
    assert payload["message"]


def test_does_not_return_equity_or_budget(client):
    """1단계가 소유하는 값을 2단계 발화가 덮어쓰면 안 된다."""
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "자기자본 5천만원 있고 강남구 카페요"}).json()
    assert "equity_krw" not in payload["fields"]
    assert "budget_krw" not in payload["fields"]


def test_a_district_outside_seoul_does_not_survive(client):
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "부산 해운대구에서 카페를 하려고요"}).json()
    assert payload["fields"]["district"]["value"] is None


def test_rejects_an_empty_text(client):
    response = client.post("/api/v1/conditions/interpret", json={"text": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rejects_an_overlong_text(client):
    response = client.post("/api/v1/conditions/interpret", json={"text": "가" * 501})
    assert response.status_code == 400


def test_a_hallucinated_field_is_dropped(client, monkeypatch):
    """모델이 원문에 없는 근거로 값을 채우면 응답에 남지 않는다."""
    async def fake(_text):
        return {"monthly_rent_krw": {"value": 3_000_000, "evidence": "월세는 300만원입니다"}}
    import app.main as main
    monkeypatch.setattr(main.ai, "interpret_conditions", fake)
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "강남구에서 카페를 준비 중이에요"}).json()
    assert payload["source"] == "AI"
    assert payload["fields"]["monthly_rent_krw"]["value"] is None


def test_a_model_returning_garbage_does_not_500(client, monkeypatch):
    """모델 응답이 어떤 모양이든 격리 경계를 넘어오면 안 된다."""
    async def fake(_text):
        return {"district": {"value": ["마포구"], "evidence": "강남구"},
                "business_stage": {"value": {"x": 1}, "evidence": "강남구"}}
    import app.main as main
    monkeypatch.setattr(main.ai, "interpret_conditions", fake)
    response = client.post("/api/v1/conditions/interpret",
                           json={"text": "강남구에서 카페를 준비 중이에요"})
    assert response.status_code == 200
    assert response.json()["fields"]["district"]["value"] is None


def test_the_ai_path_wins_when_it_returns_something(client, monkeypatch):
    async def fake(_text):
        return {"industry": {"value": "베이글집", "evidence": "베이글집"}}
    import app.main as main
    monkeypatch.setattr(main.ai, "interpret_conditions", fake)
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "강남구에 베이글집 내려고요"}).json()
    assert payload["source"] == "AI"
    assert payload["fields"]["industry"]["value"] == "베이글집"
