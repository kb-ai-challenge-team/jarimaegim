from app.condition_parse import amount_from, parse_conditions


def test_finds_a_district_by_full_name():
    result = parse_conditions("마포구에서 카페를 준비 중이에요")
    assert result["district"]["value"] == "마포구"
    assert result["district"]["evidence"] == "마포구"


def test_finds_a_district_by_stem():
    result = parse_conditions("성동에 가게를 내려고 해요")
    assert result["district"]["value"] == "성동구"
    assert result["district"]["evidence"] == "성동"


def test_does_not_read_중구_out_of_준비_중():
    """'준비 중이에요'의 '중'이 중구로 새면 자치구가 통째로 틀린다."""
    assert parse_conditions("강남구에서 카페를 준비 중이에요")["district"]["value"] == "강남구"
    assert parse_conditions("카페를 준비 중이에요")["district"]["value"] is None


def test_maps_an_industry_hint_to_a_registered_name():
    result = parse_conditions("커피 파는 가게 하고 싶어요")
    assert result["industry"]["value"] == "카페"
    assert result["industry"]["evidence"] == "커피"


def test_falls_back_to_a_named_industry():
    result = parse_conditions("꽃집을 창업하려고 해요")
    assert result["industry"]["value"] == "꽃집"


def test_reads_a_rent_with_a_unit():
    result = parse_conditions("월세는 300만원 정도 생각해요")
    assert result["monthly_rent_krw"]["value"] == 3_000_000
    assert "300만원" in result["monthly_rent_krw"]["evidence"]


def test_reads_a_bare_rent_number_as_manwon():
    """'월세 300'은 한국어 관행상 300만원이다. 확인 화면이 인용과 함께 보여주므로 고칠 수 있다."""
    assert parse_conditions("월세 300 정도요")["monthly_rent_krw"]["value"] == 3_000_000


def test_ignores_an_amount_with_no_rent_hint():
    """자기자본은 1단계가 소유한다. 발화가 그것을 덮어쓰면 안 된다."""
    assert parse_conditions("자기자본 5천만원 있어요")["monthly_rent_krw"]["value"] is None


def test_reads_the_business_stage():
    result = parse_conditions("2호점 낼 자리를 찾고 있어요")
    assert result["business_stage"]["value"] == "SECOND_STORE"
    assert result["business_stage"]["evidence"] == "2호점"


def test_reads_the_startup_type():
    assert parse_conditions("프랜차이즈로 하려고요")["startup_type"]["value"] == "FRANCHISE"


def test_reads_the_priority():
    assert parse_conditions("임대료가 제일 걱정이에요")["priority"]["value"] == "COST"


def test_every_evidence_is_a_substring_of_the_input():
    """규칙 경로도 AI 경로와 같은 evidence 계약을 지킨다."""
    text = "마포구에서 카페 준비 중이고 월세는 300 정도, 처음 창업이라 안정적이면 좋겠어요"
    for field in parse_conditions(text).values():
        if field["evidence"] is not None:
            assert field["evidence"] in text


def test_unmentioned_fields_are_null():
    result = parse_conditions("안녕하세요")
    assert all(field["value"] is None for field in result.values())


def test_amount_from_handles_units():
    assert amount_from("1억") == 100_000_000
    assert amount_from("5천만원") == 50_000_000
    assert amount_from("300만원") == 3_000_000
    assert amount_from("300") == 3_000_000
    assert amount_from("근거 없음") is None


def test_two_districts_resolve_to_the_first_one_every_time():
    """자치구 목록이 순서 없는 집합이면 같은 문장이 프로세스마다 다른 구를 냈다."""
    text = "강남구에서 하다가 마포구로 이전하려고요"
    assert parse_conditions(text)["district"]["value"] == "마포구"
    assert parse_conditions(text)["district"]["value"] == "마포구"


def test_amount_from_reads_a_comma_grouped_number_literally():
    """3,000,000원은 3백만원이다. 만원 관행을 덧씌우면 10배가 된다."""
    assert amount_from("3,000,000원") == 3_000_000
    assert amount_from("3000000") == 3_000_000


def test_amount_from_keeps_the_manwon_convention_for_small_bare_numbers():
    assert amount_from("300") == 3_000_000
    assert amount_from("1,200") == 12_000_000


def test_rent_evidence_quotes_the_whole_number():
    """인용이 잘리면 사용자가 확인 화면에서 오차를 잡을 수 없다."""
    result = parse_conditions("월세 3,000,000원 정도로 생각 중이에요")
    assert result["monthly_rent_krw"]["value"] == 3_000_000
    assert "3,000,000" in result["monthly_rent_krw"]["evidence"]


def test_rent_evidence_has_no_stray_whitespace():
    """확인 화면이 인용부호 안에 그대로 넣으므로 앞뒤 공백이 남으면 안 된다."""
    evidence = parse_conditions("월세는 300 정도 생각해요")["monthly_rent_krw"]["evidence"]
    assert evidence == evidence.strip()
    assert evidence in "월세는 300 정도 생각해요"
