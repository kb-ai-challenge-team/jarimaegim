import pytest
from pydantic import ValidationError

from app.models import DocumentCreate, FundingBandInput, FundingFacts

CASE_ID = "11111111-1111-1111-1111-111111111111"
FACTS = {"industry": "카페", "monthly_rent_krw": 2_500_000, "equity_krw": 100_000_000}


def test_funding_facts_has_no_case_id():
    facts = FundingFacts(**FACTS)
    assert "case_id" not in facts.model_dump()


def test_funding_band_input_still_carries_the_case_id():
    payload = FundingBandInput(case_id=CASE_ID, **FACTS)
    assert str(payload.case_id) == CASE_ID
    # 밴드 엔드포인트는 case_id 를 뺀 나머지를 compute_bands 에 그대로 넘긴다.
    assert set(payload.model_dump(exclude={"case_id"})) == set(FundingFacts(**FACTS).model_dump())


def test_document_create_defaults_to_no_selection_and_no_funding():
    payload = DocumentCreate(case_id=CASE_ID, template="funding", confirmed=True)
    assert payload.selected_product_ids == []
    assert payload.selected_program_ids == []
    assert payload.funding_input is None


def test_document_create_accepts_ids_and_facts():
    payload = DocumentCreate(case_id=CASE_ID, template="funding", confirmed=True,
                             selected_product_ids=["kb-1"], selected_program_ids=["pg-1"],
                             funding_input=FACTS)
    assert payload.selected_product_ids == ["kb-1"]
    assert payload.funding_input.industry == "카페"


def test_document_create_rejects_more_than_ten_ids():
    with pytest.raises(ValidationError):
        DocumentCreate(case_id=CASE_ID, template="funding", confirmed=True,
                       selected_product_ids=[f"kb-{index}" for index in range(11)])
