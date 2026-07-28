from fastapi.testclient import TestClient

#: 판단 축 8개. 밴드·스트레스는 커널이라 여기 없다 — 계산이지 판단이 아니고, 축으로 세면
#: 화면의 "N개 축 중 M개 가동"이 실제 판단 개수보다 많아진다.
EXPECTED_KEYS = {"finance.kb_products", "finance.subsidy",
                 "location.demand", "location.competition", "location.viability",
                 "location.survival", "location.access", "timing.policy"}


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
    for key in ("location.demand", "location.competition"):
        assert axes[key]["enabled"] is False
        assert "미생성" in axes[key]["disabled_reason"]


def test_location_axes_turn_on_once_the_profile_is_loaded():
    """`data/trade-area.seoul.json` 이 있는 저장소에서는 세 축이 켜지고 사유가 비어야 한다."""
    from app.main import trade_areas
    if not trade_areas.available:
        return
    axes = client().get("/api/v1/status").json()["axes"]
    for key in ("location.demand", "location.competition"):
        assert axes[key]["enabled"] is True
        assert axes[key]["disabled_reason"] is None


def test_the_sales_axis_stays_off_even_with_a_profile_loaded():
    """예전에는 상권 파일만 읽히면 이 축을 켜졌다고 보고했지만, 실행은 언제나 연동 대기를
    돌려주고 있었다 — 화면과 런타임이 정반대를 말한 것이다. 백분위 정의가 정해지기 전에는
    꺼져 있는 것이 사실이고, 탈락 권한을 가진 유일한 축이라 더욱 그렇다."""
    axis = client().get("/api/v1/status").json()["axes"]["location.viability"]
    assert axis["enabled"] is False
    assert "백분위 정의" in axis["disabled_reason"]


def test_the_access_axis_declares_why_it_is_off_rather_than_guessing_coordinates():
    axis = client().get("/api/v1/status").json()["axes"]["location.access"]
    if not axis["enabled"]:
        assert "추측" in axis["disabled_reason"]


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


def test_the_kernels_are_not_listed_as_axes():
    """밴드·스트레스는 계산이지 판단이 아니다. 축으로 세면 화면의 축 개수가 판단 개수보다 많아진다."""
    axes = client().get("/api/v1/status").json()["axes"]
    assert "finance.band" not in axes
    assert "finance.stress" not in axes

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
