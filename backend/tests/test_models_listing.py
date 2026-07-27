import pytest
from pydantic import ValidationError

from app.models import Candidate, ListingTerms, Provenance


def provenance() -> Provenance:
    return Provenance(source_name="시연용 생성 데이터", industry_scope="일반 상가",
                      spatial_unit="개별 상가 좌표", confidence="LOW", limitations=[])


def terms(**overrides) -> dict:
    base = {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 56_000_000, "monthly_rent_krw": 4_580_000,
            "maintenance_fee_krw": 370_000, "area_m2": 52.8, "floor": 1}
    return base | overrides


def test_listing_terms_accepts_the_demo_label():
    assert ListingTerms(**terms()).listing_kind == "DEMO_SYNTHETIC"


def test_listing_terms_rejects_any_other_label():
    with pytest.raises(ValidationError):
        ListingTerms(**terms(listing_kind="VERIFIED"))


def test_listing_terms_requires_the_label():
    payload = terms()
    del payload["listing_kind"]
    with pytest.raises(ValidationError):
        ListingTerms(**payload)


def test_listing_terms_rejects_a_non_positive_rent():
    with pytest.raises(ValidationError):
        ListingTerms(**terms(monthly_rent_krw=0))


def test_candidate_without_a_listing_stays_valid():
    candidate = Candidate(id="kakao-1", name="장소", address="서울 강남구", latitude=37.5, longitude=127.0,
                          evidence_grade="C", display_label="입지 환경 신호", context_signals=[], provenance=provenance())
    assert candidate.listing is None


def test_candidate_carries_listing_terms():
    candidate = Candidate(id="demo-강남구-0001", name="도곡동 1층 상가", address="서울 강남구 도곡동",
                          latitude=37.49, longitude=127.05, evidence_grade="C", display_label="시연용 매물",
                          context_signals=[], provenance=provenance(), listing=ListingTerms(**terms()))
    assert candidate.listing.deposit_krw == 56_000_000
    assert candidate.evidence_grade == "C"
