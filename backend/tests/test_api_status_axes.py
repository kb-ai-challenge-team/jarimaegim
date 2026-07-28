from fastapi.testclient import TestClient

EXPECTED_KEYS = {"finance.band", "finance.kb_products", "finance.subsidy", "finance.stress",
                 "location.demand", "location.competition", "location.viability",
                 "location.survival", "timing.policy"}


def client():
    from app.main import app
    return TestClient(app)


def test_status_lists_every_analysis_axis():
    payload = client().get("/api/v1/status").json()
    assert set(payload["axes"]) == EXPECTED_KEYS


def test_disabled_axes_carry_a_reason():
    axes = client().get("/api/v1/status").json()["axes"]
    for key, axis in axes.items():
        if not axis["enabled"]:
            assert axis["disabled_reason"], f"{key} is disabled without a reason"


def test_location_axes_stay_disabled_even_when_sources_are_configured():
    """설정만 있고 구현이 없는 축은 켜지지 않는다. 로컬 .env 값에 의존하지 않는다."""
    axes = client().get("/api/v1/status").json()["axes"]
    for key in ("location.demand", "location.competition", "location.viability"):
        assert axes[key]["enabled"] is False, f"{key} must not report as judged before it is implemented"
        assert "미구현" in axes[key]["disabled_reason"]


def test_product_axes_follow_their_endpoint_configuration(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main.settings, "finlife_api_key", "", raising=False)
    monkeypatch.setattr(main.settings, "bizinfo_api_key", "", raising=False)
    monkeypatch.setattr(main.settings, "kstartup_api_key", "", raising=False)
    axes = main.analysis_axes()
    assert axes["finance.kb_products"]["enabled"] is False
    assert axes["finance.subsidy"]["enabled"] is False

    monkeypatch.setattr(main.settings, "finlife_api_key", "k", raising=False)
    monkeypatch.setattr(main.settings, "finlife_api_url", "https://example.test/a", raising=False)
    assert main.analysis_axes()["finance.kb_products"]["enabled"] is True


def test_timing_axis_is_disabled_and_abstains():
    axis = client().get("/api/v1/status").json()["axes"]["timing.policy"]
    assert axis["enabled"] is False
    assert "판단 유보" in axis["disabled_reason"]


def test_stress_axis_is_enabled_because_it_needs_no_external_source():
    assert client().get("/api/v1/status").json()["axes"]["finance.stress"]["enabled"] is True


def test_status_says_plainly_when_the_chat_limit_is_off(monkeypatch):
    """한도를 끄면 /status 가 한도를 광고하면 안 된다 — 없는 제약을 있다고 말하는 셈이 된다."""
    import app.main as main
    monkeypatch.setattr(main.settings, "ai_daily_request_limit", -1)
    limits = client().get("/api/v1/status").json()["limits"]["chat_daily_turns"]
    assert limits["enabled"] is False
    assert limits["per_session"] is None


def test_status_reports_the_limit_when_it_is_on(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main.settings, "ai_daily_request_limit", 20)
    limits = client().get("/api/v1/status").json()["limits"]["chat_daily_turns"]
    assert limits["enabled"] is True
    assert limits["per_session"] == 20
