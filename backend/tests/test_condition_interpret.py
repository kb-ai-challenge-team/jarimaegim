from app.condition_interpret import sanitize


def test_keeps_a_field_whose_evidence_is_in_the_text():
    text = "마포구에서 카페를 준비 중이에요"
    result = sanitize(text, {"district": {"value": "마포구", "evidence": "마포구에서"}})
    assert result["fields"]["district"]["value"] == "마포구"
    assert result["fields"]["district"]["evidence"] == "마포구에서"


def test_drops_a_field_whose_evidence_is_not_in_the_text():
    """모델이 지어낸 값은 근거 문구가 원문에 없으므로 통과할 수 없다 — 이 게이트가 핵심이다."""
    text = "마포구에서 카페를 준비 중이에요"
    result = sanitize(text, {"monthly_rent_krw": {"value": 3_000_000, "evidence": "월세는 300만원"}})
    assert result["fields"]["monthly_rent_krw"]["value"] is None
    assert "monthly_rent_krw" in result["unresolved"]


def test_drops_a_field_with_a_value_but_no_evidence():
    result = sanitize("카페 준비 중", {"industry": {"value": "카페", "evidence": None}})
    assert result["fields"]["industry"]["value"] is None


def test_drops_a_district_outside_seoul():
    text = "부산진구에서 카페를 하려고요"
    result = sanitize(text, {"district": {"value": "부산진구", "evidence": "부산진구"}})
    assert result["fields"]["district"]["value"] is None
    assert "부산진구" in result["message"] or "서울" in result["message"]


def test_computes_the_rent_from_the_evidence_not_from_the_model():
    """모델은 구간만 지목하고 산술은 코드가 한다(부록 A 불변조건 4)."""
    text = "월세는 300만원 정도 생각해요"
    result = sanitize(text, {"monthly_rent_krw": {"value": 999, "evidence": "월세는 300만원"}})
    assert result["fields"]["monthly_rent_krw"]["value"] == 3_000_000


def test_drops_a_rent_whose_evidence_holds_no_number():
    text = "월세가 부담돼요"
    result = sanitize(text, {"monthly_rent_krw": {"value": 3_000_000, "evidence": "월세가 부담돼요"}})
    assert result["fields"]["monthly_rent_krw"]["value"] is None


def test_drops_an_enum_value_outside_the_union():
    text = "처음 창업이에요"
    result = sanitize(text, {"business_stage": {"value": "FRANCHISING", "evidence": "처음 창업"}})
    assert result["fields"]["business_stage"]["value"] is None


def test_keeps_a_valid_enum_value():
    text = "처음 창업이에요"
    result = sanitize(text, {"business_stage": {"value": "PRE_OPEN", "evidence": "처음 창업"}})
    assert result["fields"]["business_stage"]["value"] == "PRE_OPEN"


def test_drops_an_industry_that_is_not_a_string():
    result = sanitize("카페", {"industry": {"value": 42, "evidence": "카페"}})
    assert result["fields"]["industry"]["value"] is None


def test_always_returns_every_field_key():
    result = sanitize("안녕하세요", {})
    assert set(result["fields"]) == {"industry", "district", "monthly_rent_krw",
                                     "business_stage", "startup_type", "priority"}
    assert len(result["unresolved"]) == 6


def test_ignores_keys_the_model_invented():
    result = sanitize("카페", {"budget_krw": {"value": 1, "evidence": "카페"}})
    assert "budget_krw" not in result["fields"]


def test_message_counts_what_survived():
    text = "마포구에서 카페 준비 중이에요"
    result = sanitize(text, {"district": {"value": "마포구", "evidence": "마포구"},
                             "industry": {"value": "카페", "evidence": "카페"}})
    assert "2" in result["message"]


def test_survives_a_malformed_proposal_entry():
    """모델이 필드 자리에 dict 가 아닌 것을 넣어도 응답 전체가 죽으면 안 된다."""
    result = sanitize("카페", {"industry": "카페", "district": None, "priority": ["COST"]})
    assert result["fields"]["industry"]["value"] is None
    assert len(result["unresolved"]) == 6


def test_one_bad_field_does_not_discard_the_good_ones():
    text = "마포구에서 카페 준비 중이에요"
    result = sanitize(text, {"industry": {"value": "카페", "evidence": "카페"},
                             "monthly_rent_krw": {"value": 3_000_000, "evidence": "월세 300만원"}})
    assert result["fields"]["industry"]["value"] == "카페"
    assert result["fields"]["monthly_rent_krw"]["value"] is None


def test_an_overlong_industry_is_dropped():
    """케이스 모델의 상한(120자)을 넘는 값은 여기서 걸러 422 대신 확인 화면으로 보낸다."""
    text = "가" * 200
    result = sanitize(text, {"industry": {"value": "가" * 200, "evidence": "가" * 200}})
    assert result["fields"]["industry"]["value"] is None
