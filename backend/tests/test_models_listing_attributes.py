"""가정값 속성의 모델 계약.

이 값들은 실측이 아니므로 두 가지를 지켜야 한다.
1. 전부 선택이다 — 열이 없는 저장소에서 읽어도 매물 자체는 뜬다.
2. 물리적으로 불가능한 조합은 만들 수 없다 — 생성기 버그를 타입 층에서 잡는다.
"""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models import ListingTerms

BASE = {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 30_000_000,
        "monthly_rent_krw": 2_000_000, "maintenance_fee_krw": 160_000,
        "area_m2": 50.0, "floor": 1}


def test_assumed_attributes_are_all_optional():
    """마이그레이션 이전 Supabase 에서 읽어도 매물은 그대로 떠야 한다."""
    terms = ListingTerms(**BASE)
    assert terms.key_money_krw is None
    assert terms.exclusive_area_m2 is None
    assert terms.available_from is None
    assert terms.corner is None


def test_a_full_attribute_set_round_trips():
    terms = ListingTerms(**BASE, key_money_krw=48_000_000, exclusive_area_m2=33.1,
                         built_year=1995, parking_slots=0, corner=True, elevator=True,
                         floors_total=11, frontage_m=6.4, available_from="2026-10-24")
    assert terms.key_money_krw == 48_000_000
    assert terms.available_from == date(2026, 10, 24)
    assert terms.corner is True


def test_zero_key_money_is_valid_because_무권리_매물이_실제로_있다():
    assert ListingTerms(**BASE, key_money_krw=0).key_money_krw == 0


def test_exclusive_area_cannot_exceed_the_contract_area():
    with pytest.raises(ValidationError):
        ListingTerms(**BASE, exclusive_area_m2=60.0)


def test_exclusive_area_equal_to_the_contract_area_is_allowed():
    assert ListingTerms(**BASE, exclusive_area_m2=50.0).exclusive_area_m2 == 50.0


def test_floor_cannot_exceed_the_buildings_total_floors():
    with pytest.raises(ValidationError):
        ListingTerms(**{**BASE, "floor": 3}, floors_total=1)


@pytest.mark.parametrize("field,value", [
    ("key_money_krw", -1), ("exclusive_area_m2", 0), ("parking_slots", -1),
    ("built_year", 1800), ("floors_total", 0), ("frontage_m", 0),
])
def test_out_of_range_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        ListingTerms(**BASE, **{field: value})


def test_the_demo_label_is_still_required():
    """가정값을 늘렸다고 라벨이 느슨해지면 안 된다."""
    with pytest.raises(ValidationError):
        ListingTerms(**{**BASE, "listing_kind": "REAL"}, key_money_krw=1_000_000)
