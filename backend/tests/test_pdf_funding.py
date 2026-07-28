from app.document_store import FUNDING_OMITTED, funding_section_lines

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


def test_no_funding_says_the_section_was_omitted():
    assert funding_section_lines(None) == ["자금조달 요약", FUNDING_OMITTED]


def test_a_computation_without_a_recommended_band_is_treated_as_omitted():
    assert funding_section_lines(computed(bands=[EQUITY])) == ["자금조달 요약", FUNDING_OMITTED]


def test_the_source_line_falls_back_to_확인_필요():
    lines = funding_section_lines(computed(as_of=None))
    assert any(line.startswith("출처:") and "확인 필요" in line for line in lines)
