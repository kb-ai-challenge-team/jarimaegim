from app.config import Settings
from app.services import AIService


def service() -> AIService:
    return AIService(Settings(openai_api_key="", ai_chat_model=""))


def test_the_prompt_tells_the_model_the_listings_are_not_real():
    prompt = service().build_prompt("이 매물 계약해도 되나요?", "강남구 카페, 보증금 5,600만원")
    assert "시연용" in prompt
    assert "실제 임대 매물이 아" in prompt


def test_the_prompt_still_forbids_inventing_numbers():
    prompt = service().build_prompt("질문", "요약")
    assert "만들지 마세요" in prompt


def test_the_prompt_carries_the_question_and_the_summary():
    prompt = service().build_prompt("보증금이 얼마인가요?", "강남구 카페 요약")
    assert "보증금이 얼마인가요?" in prompt
    assert "강남구 카페 요약" in prompt


def test_build_prompt_needs_no_api_key():
    # The guardrail wording must be assertable without network access or credentials.
    assert service().client is None
    assert service().build_prompt("q", "s")


def test_the_interpret_prompt_forbids_inventing_values():
    prompt = service().build_interpret_prompt("마포구에서 카페 준비 중이에요")
    assert "null" in prompt
    assert "추론" in prompt


def test_the_interpret_prompt_demands_verbatim_evidence():
    prompt = service().build_interpret_prompt("질문")
    assert "원문 그대로" in prompt


def test_the_interpret_prompt_forbids_arithmetic():
    """금액 환산은 서버가 한다. 모델에게 계산을 시키면 불변조건 4가 프롬프트에만 남는다."""
    prompt = service().build_interpret_prompt("질문")
    assert "계산" in prompt


def test_the_interpret_prompt_states_the_seoul_scope():
    assert "서울" in service().build_interpret_prompt("질문")


def test_the_interpret_prompt_leaves_the_rent_value_to_the_server():
    prompt = service().build_interpret_prompt("질문")
    assert "monthly_rent_krw" in prompt
    assert "서버" in prompt


def test_the_interpret_prompt_lists_every_enum_value():
    prompt = service().build_interpret_prompt("질문")
    for value in ("PRE_OPEN", "RELOCATING", "SECOND_STORE", "INDEPENDENT", "FRANCHISE",
                  "UNDECIDED", "STABILITY", "DEMAND", "COST", "GROWTH"):
        assert value in prompt


def test_the_interpret_prompt_carries_the_user_text():
    assert "마포구에서 카페" in service().build_interpret_prompt("마포구에서 카페")


def test_build_interpret_prompt_needs_no_api_key():
    assert service().client is None
    assert service().build_interpret_prompt("q")


async def test_interpret_conditions_returns_none_without_a_key():
    """키가 없으면 호출부가 규칙 경로로 내려갈 수 있도록 None 을 돌려준다."""
    assert await service().interpret_conditions("마포구에서 카페") is None


def test_loads_object_reads_a_bare_json_object():
    from app.services import _loads_object
    assert _loads_object('{"a": 1}') == {"a": 1}


def test_loads_object_unwraps_a_markdown_fence():
    """모델이 ```json 으로 감싸도 AI 경로가 조용히 죽으면 안 된다."""
    from app.services import _loads_object
    assert _loads_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_loads_object_ignores_prose_around_the_object():
    from app.services import _loads_object
    assert _loads_object('설명입니다.\n{"a": 1}\n이상입니다.') == {"a": 1}


def test_loads_object_returns_none_on_garbage():
    from app.services import _loads_object
    assert _loads_object("죄송합니다, 답할 수 없습니다.") is None
