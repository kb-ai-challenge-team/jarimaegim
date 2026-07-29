"""조사가 붙은 채 들어온 업종을 표에 있는 형태로 되돌린다.

모델은 "강남구에서 카페를 준비 중"에서 업종을 `카페를` 로 뽑는다. 인용은 사용자의 말 그대로여야
하므로 evidence 게이트는 이것을 통과시키지만, `카페를` 은 별칭 표에 없어 상권 코드로 풀리지
않는다. 그러면 후보는 근거 B(상권 위험 진단)가 아니라 근거 C 로 떨어진다 — 조사 한 글자가
이 제품의 핵심 판정을 조용히 지운다.
"""
from app.industry import _ALIASES, canonical, resolve


def test_a_trailing_particle_is_removed_when_the_stem_resolves():
    assert canonical("카페를") == "카페"
    assert resolve(canonical("카페를")) == "CS100010"


def test_the_particles_the_model_actually_attaches():
    for text, expected in [("카페는", "카페"), ("카페가", "카페"), ("카페에서", "카페"),
                           ("편의점을", "편의점"), ("미용실은", "미용실"), ("커피숍이", "커피숍")]:
        assert canonical(text) == expected, text


def test_a_longer_particle_wins_over_its_suffix():
    # '에서' 를 먼저 보지 않으면 '서' 나 '에' 만 떼어 낸 이상한 줄기가 남는다.
    assert canonical("카페에서") == "카페"


def test_canonical_is_identity_on_every_known_alias():
    # 이 함수가 지켜야 하는 성질 — 이미 풀리는 값은 절대 다른 곳으로 옮기지 않는다.
    for alias in _ALIASES:
        assert canonical(alias) == alias, alias


def test_an_unknown_industry_is_left_alone_even_with_a_particle():
    # 줄기도 표에 없으면 손대지 않는다. '스터디카페' 를 '카페' 로 넘겨짚지 않는 것과 같은 이유다.
    assert canonical("스터디카페를") == "스터디카페를"
    assert resolve(canonical("스터디카페를")) is None


def test_a_bare_particle_is_not_stripped_into_nothing():
    assert canonical("를") == "를"
    assert canonical("") == ""


def test_whitespace_is_trimmed_but_the_value_is_otherwise_untouched():
    assert canonical("  카페  ") == "카페"


def test_the_gate_returns_the_resolvable_form_from_a_particled_model_answer():
    """추출 게이트가 조사를 떼고 내보내는지. 인용은 사용자의 말 그대로 남아야 한다."""
    from app.condition_interpret import sanitize
    utterance = "강남구에서 카페를 준비 중이고 월세는 250 정도 생각해요"
    result = sanitize(utterance, {"industry": {"value": "카페를", "evidence": "카페를"}})
    field = result["fields"]["industry"]
    assert field["value"] == "카페"
    assert field["evidence"] == "카페를"


def test_a_case_created_with_a_particled_industry_is_stored_resolvable(monkeypatch):
    """직접 입력으로 조사가 붙어 들어와도 케이스에는 표에 있는 형태로 남아야 한다.
    저장된 값이 매물·상권·제도 파라미터 세 조회의 입력이기 때문이다."""
    from fastapi.testclient import TestClient
    from app import main
    with TestClient(main.app) as client:
        client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        response = client.post("/api/v1/cases", json={"title": "강남구 카페", "inputs": {
            "industry": "카페를", "district": "강남구", "budget_krw": 100_000_000,
            "equity_krw": 100_000_000, "business_stage": "PRE_OPEN",
            "startup_type": "INDEPENDENT", "priority": "STABILITY"}})
        assert response.status_code == 201, response.text
        assert response.json()["inputs"]["industry"] == "카페"
