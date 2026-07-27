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
