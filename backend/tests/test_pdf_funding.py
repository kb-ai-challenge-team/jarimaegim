from app.document_store import FUNDING_OMITTED, funding_section_lines, selection_section_lines

RECOMMENDED = {"band": "RECOMMENDED", "ceiling_krw": 120_000_000, "loan_krw": 40_000_000,
               "monthly_repayment_krw": 780_000, "target_daily_revenue_krw": 620_000}
EQUITY = {"band": "EQUITY_ONLY", "ceiling_krw": 80_000_000, "loan_krw": 0,
          "monthly_repayment_krw": 0, "target_daily_revenue_krw": 410_000}


def computed(**overrides) -> dict:
    base = {"bands": [EQUITY, RECOMMENDED], "required_capital_krw": 110_000_000,
            "assumed": [], "as_of": "2026-07-28"}
    return {**base, **overrides}


def test_the_section_reports_the_recommended_line_not_the_first_one():
    lines = funding_section_lines(computed())
    assert any("120,000,000원" in line for line in lines)
    assert any("차입 필요액" in line and "40,000,000원" in line for line in lines)
    assert not any("80,000,000원" in line for line in lines)


def test_a_missing_required_capital_says_so_instead_of_guessing():
    lines = funding_section_lines(computed(required_capital_krw=None))
    assert any("확인 필요" in line for line in lines)
    assert any("평수·보증금" in line for line in lines)


def test_assumed_parameters_follow_the_numbers_into_the_document():
    lines = funding_section_lines(computed(assumed=["loan.term_months", "industries.카페"]))
    assert any("시연용 가정값" in line and "2개" in line for line in lines)


def test_no_assumed_parameters_means_no_disclaimer():
    lines = funding_section_lines(computed())
    assert not any("시연용 가정값" in line for line in lines)


def test_no_funding_says_the_section_was_omitted():
    assert funding_section_lines(None) == ["자금조달 요약", FUNDING_OMITTED]


def test_a_computation_without_a_recommended_band_is_treated_as_omitted():
    assert funding_section_lines(computed(bands=[EQUITY])) == ["자금조달 요약", FUNDING_OMITTED]


def test_the_source_line_falls_back_to_확인_필요():
    lines = funding_section_lines(computed(as_of=None))
    assert any(line.startswith("출처:") and "확인 필요" in line for line in lines)


PRODUCT = {"id": "kb-1", "name": "KB 소호모바일대출", "loan_limit": "최대 1억원",
           "rate_min": 3.9, "rate_max": 5.2, "source_as_of": "2026-07",
           "official_url": "https://obank.kbstar.com/example"}
PROGRAM = {"id": "pg-1", "title": "소상공인 정책자금", "organization": "소상공인시장진흥공단",
           "application_period": "2026-08-01 ~ 2026-08-31",
           "official_url": "https://www.semas.or.kr/example"}


def test_nothing_chosen_says_nothing_was_chosen():
    assert selection_section_lines([], [], 0) == ["고른 조달 수단", "고른 조달 수단이 없습니다."]


def test_a_product_keeps_the_disclosed_strings_verbatim():
    lines = selection_section_lines([PRODUCT], [], 0)
    assert any("KB 소호모바일대출" in line for line in lines)
    assert any("최대 1억원" in line for line in lines)
    assert any("3.9~5.2%" in line for line in lines)
    assert any("2026-07" in line for line in lines)
    assert any(PRODUCT["official_url"] in line for line in lines)


def test_a_product_without_disclosed_rates_says_so():
    lines = selection_section_lines([{**PRODUCT, "rate_min": None, "rate_max": None}], [], 0)
    assert any("공시 금리 확인 필요" in line for line in lines)


def test_a_program_carries_its_organization_and_period():
    lines = selection_section_lines([], [PROGRAM], 0)
    assert any("소상공인시장진흥공단" in line for line in lines)
    assert any("2026-08-01 ~ 2026-08-31" in line for line in lines)


def test_a_program_without_a_period_says_to_check_the_original():
    lines = selection_section_lines([], [{**PROGRAM, "application_period": None}], 0)
    assert any("기간 원문 확인" in line for line in lines)


def test_the_section_never_claims_eligibility():
    lines = selection_section_lines([PRODUCT], [PROGRAM], 0)
    assert any("자격" in line and "판단한 것이 아닙니다" in line for line in lines)


def test_dropped_items_are_reported_not_swallowed():
    lines = selection_section_lines([PRODUCT], [], 2)
    assert any("2건" in line and "확인되지 않아 제외" in line for line in lines)


def test_everything_dropped_still_produces_the_section():
    lines = selection_section_lines([], [], 3)
    assert lines[0] == "고른 조달 수단"
    assert any("3건" in line for line in lines)
