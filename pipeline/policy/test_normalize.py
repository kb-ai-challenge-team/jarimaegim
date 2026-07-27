from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from normalize import (canonical_regions, display_status, normalize_bizinfo, parse_compact_date,
                       parse_range_dates, resolve_status, strip_html)

FIXTURES = Path(__file__).parent / "fixtures"


def bizinfo_records() -> list[dict[str, str]]:
    root = ElementTree.fromstring((FIXTURES / "bizinfo.sample.xml").read_bytes())
    return [{child.tag: (child.text or "").strip() for child in item}
            for item in root.findall(".//body/items/item")]


def test_strip_html_removes_tags_and_entities():
    raw = '<p>지원 대상은 <b>중소기업</b>입니다.</p><p>&nbsp;</p><p>문의: A&amp;B</p>'
    assert strip_html(raw) == "지원 대상은 중소기업입니다. 문의: A&B"


def test_strip_html_on_empty_input_returns_empty_string():
    assert strip_html("") == ""
    assert strip_html(None) == ""


def test_parse_compact_date_reads_yyyymmdd():
    assert parse_compact_date("20260812") == date(2026, 8, 12)


def test_parse_compact_date_returns_none_for_unusable_input():
    assert parse_compact_date("") is None
    assert parse_compact_date("99991231") == date(9999, 12, 31)
    assert parse_compact_date("2026-08") is None


def test_parse_range_dates_splits_on_tilde():
    assert parse_range_dates("2026-07-22 ~ 2026-08-18") == (date(2026, 7, 22), date(2026, 8, 18))


def test_parse_range_dates_returns_none_pair_when_unparseable():
    assert parse_range_dates("접수기간 별도 공지") == (None, None)


def test_canonical_regions_normalises_full_names():
    assert canonical_regions("서울특별시") == ["서울"]
    assert canonical_regions("대구광역시") == ["대구"]


def test_canonical_regions_splits_comma_separated_values():
    assert canonical_regions("서울,경기") == ["경기", "서울"]


def test_canonical_regions_returns_none_when_nothing_maps():
    # '전남광주'처럼 원천이 붙여 보낸 값은 어느 지역인지 확정할 수 없으므로 버린다.
    assert canonical_regions("전남광주") is None
    assert canonical_regions("경북대학교 지산학연협력기술연구소") is None
    assert canonical_regions("") is None


def test_resolve_status_closes_only_on_a_past_end_date():
    today = date(2026, 7, 27)
    assert resolve_status(date(2026, 7, 1), today) == "CLOSED"
    assert resolve_status(date(2026, 8, 18), today) == "ACTIVE"
    assert resolve_status(None, today) == "UNKNOWN"


def test_display_status_never_reports_an_open_window_as_an_eligibility_verdict():
    today = date(2026, 7, 27)
    # 접수 중이어도 자격을 판정한 게 아니므로 UNKNOWN이다.
    assert display_status(date(2026, 8, 18), today) == "UNKNOWN"
    assert display_status(None, today) == "UNKNOWN"
    assert display_status(date(2026, 7, 1), today) == "CLOSED"


def test_normalize_bizinfo_builds_an_embeddable_document():
    doc = normalize_bizinfo(bizinfo_records()[0], today=date(2026, 7, 27))
    assert doc is not None
    assert doc.kind == "PROGRAM"
    assert doc.provider == "기업마당"
    assert doc.id.startswith("bizinfo:PBLN_")
    assert doc.official_url.startswith("https://")
    # 본문에 HTML 태그가 남으면 임베딩 품질이 떨어지고 인용문도 깨진다.
    assert "<" not in doc.body_text
    assert len(doc.body_text) > 100


def test_normalize_bizinfo_reads_the_application_window():
    doc = normalize_bizinfo(bizinfo_records()[0], today=date(2026, 7, 27))
    assert doc.application_start == date(2026, 7, 22)
    assert doc.application_end == date(2026, 8, 18)
    assert doc.status == "ACTIVE"


def test_normalize_bizinfo_takes_region_only_from_the_jurisdiction_field():
    # 소관기관이 광역지자체명일 때만 지역이 확정된다. 해시태그의 '서울'은 근거가 아니다.
    doc = normalize_bizinfo({"pblancNm": "제목", "pblancId": "PBLN_1",
                             "pblancUrl": "https://www.bizinfo.go.kr/x",
                             "jrsdInsttNm": "대구광역시", "bsnsSumryCn": "<p>내용</p>",
                             "hashtags": "서울,창업"}, today=date(2026, 7, 27))
    assert doc.regions == ["대구"]

    doc = normalize_bizinfo({"pblancNm": "제목", "pblancId": "PBLN_2",
                             "pblancUrl": "https://www.bizinfo.go.kr/x",
                             "jrsdInsttNm": "중소벤처기업부", "bsnsSumryCn": "<p>내용</p>",
                             "hashtags": "서울,창업"}, today=date(2026, 7, 27))
    assert doc.regions is None


def test_normalize_bizinfo_rejects_records_without_a_title_or_url():
    assert normalize_bizinfo({"pblancId": "PBLN_3"}, today=date(2026, 7, 27)) is None
    assert normalize_bizinfo({"pblancNm": "제목", "pblancUrl": ""}, today=date(2026, 7, 27)) is None


def test_normalize_bizinfo_display_matches_the_existing_frontend_contract():
    doc = normalize_bizinfo(bizinfo_records()[0], today=date(2026, 7, 27))
    display = doc.display
    # lib/types.ts의 Program과 필드 대 필드로 맞는다. 유니온 밖 값이 새면 UI가 깨진다.
    assert set(display) == {"id", "category", "title", "organization", "status",
                            "application_period", "matched_conditions",
                            "unknown_conditions", "official_url", "source_as_of"}
    assert display["status"] == "UNKNOWN"
    assert display["category"] == "GOVERNMENT"
    assert display["application_period"] == "2026-07-22 ~ 2026-08-18"
    assert display["matched_conditions"] == []
    assert display["unknown_conditions"]
