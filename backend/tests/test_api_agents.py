"""에이전트 층의 HTTP 표면.

  GET  /api/v1/agents                  12개 선언과 가동 현황 (가드 3 — "12개 축 중 N개 가동")
  POST /api/v1/cases/{id}/prescribe    메인 에이전트 1회 실행, 팀 단위 진행을 SSE 로 중계
"""
import json
import pytest
from fastapi.testclient import TestClient

CASE = {"title": "테스트", "inputs": {"industry": "카페", "district": "강남구",
        "budget_krw": 150_000_000, "equity_krw": 100_000_000, "business_stage": "PRE_OPEN",
        "startup_type": "INDEPENDENT", "priority": "STABILITY"}}

BODY = {"area_pyeong": 15.0, "deposit_krw": 100_000_000, "monthly_rent_krw": 2_500_000,
        "monthly_maintenance_krw": 300_000, "key_money_krw": 0, "fitout_krw": None,
        "existing_debt_krw": 0, "other_monthly_fixed_krw": 1_000_000}

FILLED = {
    "schema_version": 1, "updated_at": "2026-07-27",
    "entries": {
        "loan.annual_rate_percent": {"value": 4.5, "source": "테스트"},
        "loan.term_months": {"value": 60, "source": "테스트"},
        "loan.guarantee_ceiling_krw": {"value": 70_000_000, "source": "테스트"},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000, "source": "테스트"},
        "stress.revenue_drop_ratio": {"value": 0.2, "source": "테스트"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "source": "테스트"},
        "working_capital.months": {"value": 3, "source": "테스트"},
    },
    "industries": {"카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20,
                           "fitout_krw_per_pyeong": 2_500_000, "operating_days_per_month": 26,
                           "source": "테스트"}},
}


@pytest.fixture(autouse=True)
def offline_agents(monkeypatch):
    """이 파일이 시험하는 것은 HTTP 계약이다. 모델을 붙이면 네트워크를 타고 답이 매번 달라진다.

    메인 에이전트는 케이스 id 로 캐시되고 그 안에 가드 2의 재실행 캐시가 들어 있으므로,
    테스트 사이에 비워 둔다 — 안 그러면 앞 테스트의 결과가 뒤 테스트로 새어 나간다."""
    import app.main as main
    monkeypatch.setattr(main.ai, "responder", lambda *args, **kwargs: None)
    main._main_agents.clear()
    yield
    main._main_agents.clear()


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


def frames(response) -> list[dict]:
    out = []
    for block in response.text.split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        event = payload = None
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
        if event:
            out.append({"event": event, "data": payload})
    return out


# ── GET /api/v1/agents ────────────────────────────────────────────

def test_the_roster_lists_all_twelve_declarations(client):
    payload = client.get("/api/v1/agents").json()
    assert payload["total"] == 12
    assert len(payload["agents"]) == 12


def test_every_declaration_carries_its_source_and_team(client):
    for item in client.get("/api/v1/agents").json()["agents"]:
        assert item["source_name"]
        assert item["team"] in ("main", "condition", "finance", "location", "timing")


def test_the_roster_is_public_because_it_is_a_declaration_not_user_data():
    from app.main import app
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/agents").status_code == 200


def test_status_reports_the_same_twelve(client):
    payload = client.get("/api/v1/status").json()
    assert payload["agents"]["total"] == 12


# ── POST /api/v1/cases/{id}/prescribe ─────────────────────────────

def test_prescribe_requires_a_session(case_id):
    from app.main import app
    with TestClient(app) as anonymous:
        assert anonymous.post(f"/api/v1/cases/{case_id}/prescribe", json=BODY).status_code == 401


def test_prescribe_streams_team_progress_then_a_result(client, case_id, filled_params):
    response = client.post(f"/api/v1/cases/{case_id}/prescribe", json=BODY)
    assert response.status_code == 200
    names = [frame["event"] for frame in frames(response)]
    assert names[0] == "run_start"
    assert "team_start" in names
    assert "agent_end" in names
    assert names[-1] == "done"


def test_each_team_reports_before_the_next_one_starts(client, case_id, filled_params):
    response = client.post(f"/api/v1/cases/{case_id}/prescribe", json=BODY)
    teams = [frame["data"]["team"] for frame in frames(response) if frame["event"] == "team_start"]
    assert teams == ["condition", "finance", "location", "timing", "main"]


def test_every_agent_end_names_the_agent_and_its_status(client, case_id, filled_params):
    response = client.post(f"/api/v1/cases/{case_id}/prescribe", json=BODY)
    ends = [frame["data"] for frame in frames(response) if frame["event"] == "agent_end"]
    assert ends
    for item in ends:
        assert item["key"] and item["name"] and item["status"]


def test_the_done_frame_carries_activation_and_the_summary(client, case_id, filled_params):
    response = client.post(f"/api/v1/cases/{case_id}/prescribe", json=BODY)
    done = frames(response)[-1]["data"]
    assert done["activation"]["total"] == 12
    assert done["summary"]["recommended_ceiling_krw"] > 0


def test_unregistered_parameters_halt_the_run_at_the_finance_team(client, case_id):
    # 저장소의 실제 상태 — 파라미터 4개가 비어 있으므로 밴드를 그릴 수 없다.
    response = client.post(f"/api/v1/cases/{case_id}/prescribe", json=BODY)
    done = frames(response)[-1]["data"]
    assert done["halted_at"] == "finance"
    assert done["summary"] == {}


def test_the_chat_cannot_reach_this_endpoint_with_a_case_patch(client, case_id, filled_params):
    response = client.post(f"/api/v1/cases/{case_id}/prescribe",
                           json={**BODY, "confirmed_case_patch": [{"field": "industry"}]})
    assert response.status_code == 422


# ── POST /api/v1/conditions/interpret — 발화를 조건으로 읽는 경로 ─────────────
# 화면의 조건 카드를 채우는 것이 이 엔드포인트다. 정규식이 먼저 채우고, 이 응답이 빈칸만 덮는다.

class OneShotResponder:
    """condition.location 의 추출 한 번을 흉내 낸다. 네트워크를 타지 않는다."""

    def __init__(self, mentions):
        self.mentions = mentions

    async def respond(self, messages, tools, **options):
        return {"text": "", "tool_calls": [{"id": "c", "name": tools[0]["name"],
                                            "arguments": {"mentions": self.mentions}}]}


@pytest.fixture
def scripted_interpreter(monkeypatch):
    import app.main as main

    def install(mentions):
        monkeypatch.setattr(main.ai, "responder", lambda *a, **k: OneShotResponder(mentions))
    return install


def test_interpret_requires_a_session():
    from app.main import app
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/v1/conditions/interpret", json={"utterance": "강남구 카페"})
        assert response.status_code == 401


def test_interpret_reads_the_conditions_the_model_pointed_at(client, scripted_interpreter):
    scripted_interpreter([{"field": "district", "span": "강남구"},
                          {"field": "industry", "span": "카페"},
                          {"field": "monthly_rent_krw", "span": "300만원"}])
    response = client.post("/api/v1/conditions/interpret",
                           json={"utterance": "강남구에 카페, 월세 300만원까지 봅니다", "known": {}})
    body = response.json()
    assert body["patch"] == {"district": "강남구", "industry": "카페",
                             "monthly_rent_krw": 3_000_000}
    assert body["decision"]["source"] == "llm"


def test_interpret_never_overwrites_a_value_the_user_already_confirmed(client, scripted_interpreter):
    scripted_interpreter([{"field": "industry", "span": "카페"}])
    response = client.post("/api/v1/conditions/interpret",
                           json={"utterance": "강남구에 카페", "known": {"industry": "제과점"}})
    assert response.json()["patch"] == {}


def test_interpret_discards_a_span_that_is_not_in_the_utterance(client, scripted_interpreter):
    scripted_interpreter([{"field": "monthly_rent_krw", "span": "월세 500만원"}])
    response = client.post("/api/v1/conditions/interpret",
                           json={"utterance": "강남구에 카페 자리 찾아요", "known": {}})
    body = response.json()
    assert body["patch"] == {}
    assert body["decision"]["rejected"][0]["reason"] == "not_in_source"


def test_interpret_only_resolves_districts_inside_seoul(client, scripted_interpreter):
    # 범위 밖은 추정하지 않는다. 서울 25개 자치구가 아니면 자치구를 채우지 않는다.
    scripted_interpreter([{"field": "district", "span": "분당구"}])
    response = client.post("/api/v1/conditions/interpret",
                           json={"utterance": "분당구에 카페 열려고요", "known": {}})
    assert "district" not in response.json()["patch"]


def test_interpret_without_a_model_returns_an_empty_patch_rather_than_failing(client):
    response = client.post("/api/v1/conditions/interpret",
                           json={"utterance": "강남구에 카페", "known": {}})
    assert response.status_code == 200
    assert response.json() == {"patch": {}, "decision": {"source": "unavailable",
                                                         "schema": "extract_conditions",
                                                         "chosen": {}, "rejected": []}}
