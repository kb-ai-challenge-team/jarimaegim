import json

import pytest

from app.config import Settings
from app.listings import ListingService


def row(listing_id: str, district: str, lat: float, lng: float, rent: int, deposit: int = 20_000_000) -> dict:
    return {"id": listing_id, "name": f"{district} 상가", "address": f"서울 {district}", "district": district,
            "latitude": lat, "longitude": lng,
            "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": deposit, "monthly_rent_krw": rent,
                        "maintenance_fee_krw": None, "area_m2": 30.0, "floor": 1}}


ROWS = [
    row("a1", "강남구", 37.50, 127.05, 1_000_000),
    row("a2", "강남구", 37.52, 127.03, 12_000_000),
    row("a3", "강남구", 37.54, 127.07, 2_000_000),
    row("b1", "마포구", 37.55, 126.92, 5_000_000),
    row("b2", "마포구", 37.57, 126.90, 1_000_000),
]


@pytest.fixture
def service(tmp_path):
    seed = tmp_path / "listings.seoul.json"
    seed.write_text(json.dumps({"listings": ROWS}), encoding="utf-8")
    return ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=seed)


def test_summary_has_one_entry_per_covered_district(service):
    summaries = service.summary()
    assert [entry.district for entry in summaries] == ["강남구", "마포구"]


def test_summary_counts_listings(service):
    counts = {entry.district: entry.count for entry in service.summary()}
    assert counts == {"강남구": 3, "마포구": 2}


def test_summary_reports_the_median_rent_not_the_mean(service):
    rents = {entry.district: entry.median_monthly_rent_krw for entry in service.summary()}
    # 강남 1M/2M/12M -> median 2M but mean 5M, so this fails if the mean is used.
    # 마포 1M/5M -> median 3M, the midpoint of an even-sized sample.
    assert rents == {"강남구": 2_000_000, "마포구": 3_000_000}


def test_summary_pin_sits_at_the_centre_of_its_listings(service):
    gangnam = next(entry for entry in service.summary() if entry.district == "강남구")
    assert gangnam.latitude == pytest.approx((37.50 + 37.52 + 37.54) / 3)
    assert gangnam.longitude == pytest.approx((127.05 + 127.03 + 127.07) / 3)


def test_summary_is_sorted_by_district_name(service):
    districts = [entry.district for entry in service.summary()]
    assert districts == sorted(districts)


def test_summary_of_an_empty_service_is_empty(tmp_path):
    empty = ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=tmp_path / "absent.json")
    assert empty.summary() == []
