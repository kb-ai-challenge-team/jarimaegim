import json
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from normalize import (canonical_regions, display_status, normalize_bizinfo, normalize_kb_product,
                       normalize_kstartup, parse_business_age_limit, parse_compact_date,
                       parse_range_dates, resolve_status, strip_html)

KB_BASE = {"fin_prdt_cd": "CR0001A", "fin_prdt_nm": "KB Star 신용대출",
           "kor_co_nm": "KB국민은행", "join_way": "영업점,인터넷,스마트폰",
           "crdt_prdt_type_nm": "일반신용대출", "dcls_month": "202607", "loan_limit": "최대 1억원"}
KB_OPTION = {"lend_rate_min": "4.5", "lend_rate_max": "6.2", "lend_rate_avg": "5.1",
             "lend_rate_type_nm": "변동금리"}

FIXTURES = Path(__file__).parent / "fixtures"


def bizinfo_records() -> list[dict[str, str]]:
    root = ElementTree.fromstring((FIXTURES / "bizinfo.sample.xml").read_bytes())
    return [{child.tag: (child.text or "").strip() for child in item}
            for item in root.findall(".//body/items/item")]


def kstartup_records() -> list[dict]:
    return json.loads((FIXTURES / "kstartup.sample.json").read_text())["data"]


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


def test_parse_business_age_limit_takes_the_widest_bound():
    assert parse_business_age_limit("7년미만,10년미만") == 10
    assert parse_business_age_limit("3년미만") == 3
    assert parse_business_age_limit("") is None
    assert parse_business_age_limit("예비창업자") is None


def test_normalize_kstartup_builds_an_embeddable_document():
    doc = normalize_kstartup(kstartup_records()[0], today=date(2026, 7, 27))
    assert doc is not None
    assert doc.provider == "K-Startup"
    assert doc.id.startswith("kstartup:")
    assert doc.official_url.startswith("https://")
    assert len(doc.body_text) > 50


def test_normalize_kstartup_keeps_the_declared_region():
    doc = normalize_kstartup({"pbanc_sn": "1", "biz_pbanc_nm": "제목",
                              "detl_pg_url": "https://www.k-startup.go.kr/x",
                              "supt_regin": "서울", "pbanc_rcpt_end_dt": "20260812",
                              "biz_enyy": "7년미만"}, today=date(2026, 7, 27))
    assert doc.regions == ["서울"]
    assert doc.business_age_limit_years == 7
    assert doc.application_end == date(2026, 8, 12)
    assert doc.status == "ACTIVE"


def test_normalize_kstartup_drops_regions_it_cannot_resolve():
    doc = normalize_kstartup({"pbanc_sn": "2", "biz_pbanc_nm": "제목",
                              "detl_pg_url": "https://www.k-startup.go.kr/x",
                              "supt_regin": "전남광주"}, today=date(2026, 7, 27))
    assert doc.regions is None


def test_normalize_kstartup_rejects_records_without_a_usable_url():
    assert normalize_kstartup({"pbanc_sn": "3", "biz_pbanc_nm": "제목"},
                              today=date(2026, 7, 27)) is None


def test_normalize_kstartup_display_renders_the_period_in_the_same_shape():
    # 기업마당은 원천이 '2026-07-22 ~ 2026-08-18' 문자열을 주지만 K-Startup은 두 필드로
    # 온다. 화면에서 같은 모양이어야 하므로 여기서 합쳐 준다.
    doc = normalize_kstartup({"pbanc_sn": "4", "biz_pbanc_nm": "제목",
                              "detl_pg_url": "https://www.k-startup.go.kr/x",
                              "pbanc_rcpt_bgng_dt": "20260724",
                              "pbanc_rcpt_end_dt": "20260812"}, today=date(2026, 7, 27))
    assert doc.display["application_period"] == "2026-07-24 ~ 2026-08-12"
    assert doc.display["status"] == "UNKNOWN"


def test_normalize_kb_product_states_only_disclosed_values():
    doc = normalize_kb_product(KB_BASE, KB_OPTION, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN",
                               source_url="https://finlife.fss.or.kr/finlife/ldng/indvCrdt/list.do")
    assert doc.kind == "KB_PRODUCT"
    assert doc.id == "kb-credit_loan-CR0001A"
    assert doc.status == "UNKNOWN"          # 공시 상품에 신청기간이 없다
    assert doc.regions is None
    assert "KB Star 신용대출" in doc.body_text
    assert "4.5" in doc.body_text and "6.2" in doc.body_text
    assert "개인신용대출" in doc.body_text


def test_normalize_kb_product_omits_rates_the_disclosure_does_not_carry():
    doc = normalize_kb_product(KB_BASE, {}, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN",
                               source_url="https://finlife.fss.or.kr/x")
    # 금리가 공시되지 않았으면 문장에 금리 문구 자체가 없어야 한다. 0%로 채우지 않는다.
    assert "금리" not in doc.body_text
    assert doc.body_text.startswith("KB국민은행 개인신용대출")


def test_normalize_kb_product_rejects_records_without_a_code_or_name():
    assert normalize_kb_product({"fin_prdt_nm": "이름만"}, {}, category="CREDIT_LOAN",
                                label="개인신용대출", kind_of_rate="LOAN",
                                source_url="https://finlife.fss.or.kr/x") is None


def test_normalize_kb_product_display_matches_the_existing_frontend_contract():
    doc = normalize_kb_product(KB_BASE, KB_OPTION, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN", source_url="https://finlife.fss.or.kr/x")
    display = doc.display
    # lib/types.ts의 KbProduct와 필드 대 필드로 맞는다.
    assert set(display) == {"id", "name", "category", "category_label", "rate_kind",
                            "organization", "product_type", "rate_min", "rate_max", "rate_avg",
                            "rate_type", "loan_limit", "join_way", "repay_type",
                            "source_as_of", "official_url", "unknown_conditions"}
    assert display["rate_min"] == 4.5 and display["rate_max"] == 6.2
    assert display["category_label"] == "개인신용대출"
    assert display["rate_kind"] == "대출금리"
    assert display["source_as_of"] == "2026-07-01"
    assert len(display["unknown_conditions"]) == 2


def test_normalize_kb_product_display_leaves_undisclosed_rates_null():
    doc = normalize_kb_product(KB_BASE, {}, category="CREDIT_LOAN", label="개인신용대출",
                               kind_of_rate="LOAN", source_url="https://finlife.fss.or.kr/x")
    # 공시되지 않은 금리를 0으로 채우지 않는다. null이 '모른다'는 뜻이다.
    assert doc.display["rate_min"] is None
    assert doc.display["rate_max"] is None
    assert doc.display["rate_avg"] is None
