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


def test_location_axes_follow_the_trade_area_profile_not_the_env(monkeypatch):
    """축이 켜지는 기준은 키 설정이 아니라 판정에 쓸 집계가 실제로 메모리에 있느냐다."""
    import app.main as main

    class Empty:
        available, quarter, dong_count = False, None, 0

    monkeypatch.setattr(main, "trade_areas", Empty(), raising=False)
    axes = main.analysis_axes()
    for key in ("location.demand", "location.competition", "location.viability"):
        assert axes[key]["enabled"] is False
        assert "미생성" in axes[key]["disabled_reason"]


def test_location_axes_turn_on_once_the_profile_is_loaded():
    """`data/trade-area.seoul.json` 이 있는 저장소에서는 세 축이 켜지고 사유가 비어야 한다."""
    from app.main import trade_areas
    if not trade_areas.available:
        return
    axes = client().get("/api/v1/status").json()["axes"]
    for key in ("location.demand", "location.competition", "location.viability"):
        assert axes[key]["enabled"] is True
        assert axes[key]["disabled_reason"] is None


def test_survival_axis_stays_disabled_because_it_is_the_only_grade_a_path():
    """상권 집계로는 A등급을 낼 수 없다. 개별 이력 코호트가 붙기 전까지 이 축은 꺼져 있어야 한다."""
    axis = client().get("/api/v1/status").json()["axes"]["location.survival"]
    assert axis["enabled"] is False
    assert axis["disabled_reason"]


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
