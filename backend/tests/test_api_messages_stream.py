import json
from uuid import uuid4
from fastapi.testclient import TestClient


def client_and_case():
    from app.main import app
    client = TestClient(app)
    client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
    created = client.post("/api/v1/cases", headers={"Idempotency-Key": "k1"},
                          # budget_krw must be > 0 (see app/models.py CaseInput: Field(gt=0, ...)) --
                          # 0 fails request validation with a 400 before a case ever exists, which
                          # would make every test below fail on a KeyError unrelated to the endpoint
                          # under test.
                          json={"title": "테스트", "inputs": {"industry": "카페", "district": "마포구",
                                                            "budget_krw": 100_000_000, "equity_krw": 0,
                                                            "business_stage": "PRE_OPEN",
                                                            "startup_type": "UNDECIDED", "priority": "STABILITY"}})
    # CaseRecord's identifier field is `id`, not `case_id` (see app/models.py CaseRecord) -- using
    # the wrong key here would KeyError on every test in this module regardless of whether
    # /messages/stream itself works, which is not a meaningful regression signal.
    return client, created.json()["id"]


def message_body(content="강남구 분양 알려줘", patch=None):
    # client_message_id is typed UUID on MessageCreate (see app/models.py) -- a plain "m1" string
    # fails request validation with a 400 before the handler runs at all, which would make every
    # test using this body pass or fail for the wrong reason (a validation error, not the behavior
    # under test).
    return {"client_message_id": str(uuid4()), "content": content, "base_case_version": 1,
            "confirmed_case_patch": patch or [], "locale": "ko-KR"}


def parse_events(text):
    events = []
    for block in text.split("\n\n"):
        name = payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                payload = json.loads(line[len("data: "):])
        if name:
            events.append((name, payload))
    return events


def test_a_case_patch_is_refused_with_422():
    client, case_id = client_and_case()
    response = client.post(f"/api/v1/cases/{case_id}/messages/stream",
                           json=message_body(patch=[{"field": "district", "value": "강남구"}]))
    assert response.status_code == 422


def test_the_stream_declares_the_sse_content_type():
    client, case_id = client_and_case()
    response = client.post(f"/api/v1/cases/{case_id}/messages/stream", json=message_body())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"


def test_without_keys_the_stream_reports_not_configured():
    client, case_id = client_and_case()
    events = parse_events(client.post(f"/api/v1/cases/{case_id}/messages/stream", json=message_body()).text)
    names = [name for name, _ in events]
    assert names[0] == "turn_start"
    assert names[-1] == "done"
    assert dict(events)["turn_start"]["tools_available"] is False
    assert dict(events)["done"]["integration_status"] == "not_configured"


def test_without_keys_the_stream_makes_no_claims_it_cannot_support():
    client, case_id = client_and_case()
    done = dict(parse_events(client.post(f"/api/v1/cases/{case_id}/messages/stream", json=message_body()).text))["done"]
    assert done["citations"] == []
    assert done["message"]


def test_another_session_cannot_stream_into_this_case():
    from app.main import app
    client, case_id = client_and_case()
    stranger = TestClient(app)
    stranger.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
    assert stranger.post(f"/api/v1/cases/{case_id}/messages/stream", json=message_body()).status_code == 404


def test_the_daily_limit_eventually_refuses_a_turn(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main.settings, "ai_daily_request_limit", 1, raising=False)
    client, case_id = client_and_case()
    client.post(f"/api/v1/cases/{case_id}/messages/stream", json=message_body())
    second = client.post(f"/api/v1/cases/{case_id}/messages/stream", json=message_body())
    assert second.status_code == 429


def test_a_refused_request_does_not_spend_a_turn(monkeypatch):
    """consume_daily_turn mutates, so it must run after every guard that can reject. If the
    order were reversed, a rejected request would burn a turn the user never got to use."""
    import app.main as main
    monkeypatch.setattr(main.settings, "ai_daily_request_limit", 1, raising=False)
    client, case_id = client_and_case()
    refused = client.post(f"/api/v1/cases/{case_id}/messages/stream",
                          json=message_body(patch=[{"field": "district", "value": "강남구"}]))
    assert refused.status_code == 422
    allowed = client.post(f"/api/v1/cases/{case_id}/messages/stream", json=message_body())
    assert allowed.status_code == 200, "422 가 턴을 소비했다"


def test_the_status_endpoint_exposes_the_ipzitalk_integration():
    from app.main import app
    payload = TestClient(app).get("/api/v1/status").json()
    assert payload["integrations"]["ipzitalk"] is False
