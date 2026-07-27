from datetime import date

from normalize import (canonical_regions, display_status, parse_compact_date, parse_range_dates,
                      resolve_status, strip_html)


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
