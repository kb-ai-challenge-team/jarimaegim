import json

import pytest

from app.config import Settings
from app.listings import ListingService

ROWS = [
    {"id": "demo-강남구-0001", "name": "도곡동 1층 상가", "address": "서울 강남구 도곡동", "district": "강남구",
     "latitude": 37.49, "longitude": 127.05,
     "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 56_000_000, "monthly_rent_krw": 4_580_000,
                 "maintenance_fee_krw": 370_000, "area_m2": 52.8, "floor": 1}},
    {"id": "demo-강남구-0002", "name": "역삼동 1층 상가", "address": "서울 강남구 역삼동", "district": "강남구",
     "latitude": 37.50, "longitude": 127.03,
     "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 20_000_000, "monthly_rent_krw": 1_800_000,
                 "maintenance_fee_krw": 140_000, "area_m2": 30.0, "floor": 1}},
    {"id": "demo-마포구-0001", "name": "서교동 1층 상가", "address": "서울 마포구 서교동", "district": "마포구",
     "latitude": 37.55, "longitude": 126.92,
     "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 30_000_000, "monthly_rent_krw": 2_600_000,
                 "maintenance_fee_krw": 200_000, "area_m2": 40.0, "floor": 1}},
]


@pytest.fixture
def service(tmp_path):
    seed = tmp_path / "listings.seoul.json"
    seed.write_text(json.dumps({
        "generated_at": "2026-07-27T00:00:00Z", "seed": 20260727, "listing_kind": "DEMO_SYNTHETIC",
        "notice": "시연용 생성 데이터입니다.", "method": "…", "assumed": "…", "listings": ROWS,
    }), encoding="utf-8")
    return ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=seed)


def test_covered_districts_are_derived_from_the_seed(service):
    assert service.covered_districts() == {"강남구", "마포구"}


def test_search_returns_candidates_for_a_covered_district(service):
    candidates, status, message = service.search("강남구", budget_krw=None, limit=15)
    assert status == "success"
    assert message is None
    assert len(candidates) == 2
    assert all(candidate.listing.listing_kind == "DEMO_SYNTHETIC" for candidate in candidates)


def test_search_sorts_by_monthly_rent_ascending(service):
    candidates, _, _ = service.search("강남구", budget_krw=None, limit=15)
    rents = [candidate.listing.monthly_rent_krw for candidate in candidates]
    assert rents == sorted(rents)


def test_search_respects_the_limit(service):
    candidates, _, _ = service.search("강남구", budget_krw=None, limit=1)
    assert len(candidates) == 1


def test_budget_filters_out_listings_whose_deposit_exceeds_it(service):
    candidates, _, _ = service.search("강남구", budget_krw=25_000_000, limit=15)
    assert [candidate.id for candidate in candidates] == ["demo-강남구-0002"]


def test_an_uncovered_district_returns_an_explanatory_empty_state(service):
    candidates, status, message = service.search("노원구", budget_krw=None, limit=15)
    assert candidates == []
    assert status == "empty"
    assert "강남구" in message and "마포구" in message


def test_a_budget_that_excludes_everything_says_so(service):
    candidates, status, message = service.search("강남구", budget_krw=1_000, limit=15)
    assert candidates == []
    assert status == "empty"
    assert "예산" in message


def test_every_candidate_is_grade_c(service):
    candidates, _, _ = service.search("강남구", budget_krw=None, limit=15)
    assert {candidate.evidence_grade for candidate in candidates} == {"C"}


def test_provenance_declares_the_data_is_not_a_real_listing(service):
    candidates, _, _ = service.search("강남구", budget_krw=None, limit=15)
    candidate = candidates[0]
    assert candidate.provenance.source_name == "시연용 생성 데이터"
    assert any("실제 임대 매물이 아니" in item for item in candidate.provenance.limitations)


def test_get_resolves_a_candidate_by_id(service):
    assert service.get("demo-강남구-0001").name == "도곡동 1층 상가"
    assert service.get("nope") is None


def test_a_missing_seed_file_yields_an_empty_service(tmp_path):
    empty = ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=tmp_path / "absent.json")
    assert empty.covered_districts() == set()
    candidates, status, message = empty.search("강남구", budget_krw=None, limit=15)
    assert candidates == [] and status == "empty" and message is not None


def test_a_broken_supabase_falls_back_to_the_seed(tmp_path):
    seed = tmp_path / "listings.seoul.json"
    seed.write_text(json.dumps({"listings": ROWS}), encoding="utf-8")
    # Port 1 refuses immediately, so this exercises the failure path without a slow timeout.
    service = ListingService(Settings(supabase_url="http://127.0.0.1:1", supabase_service_role_key="bogus"),
                             seed_path=seed)
    assert service.covered_districts() == {"강남구", "마포구"}


def test_construction_never_raises_when_both_sources_are_unavailable(tmp_path):
    service = ListingService(Settings(supabase_url="http://127.0.0.1:1", supabase_service_role_key="bogus"),
                             seed_path=tmp_path / "absent.json")
    assert service.covered_districts() == set()
    candidates, status, message = service.search("강남구", budget_krw=None, limit=15)
    assert candidates == [] and status == "empty" and message is not None
