import pytest

from app.document_store import FUNDING_OMITTED, funding_section_lines, render_case_pdf, selection_section_lines

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


def test_compute_bands_output_satisfies_the_funding_section():
    """funding_section_lines 는 compute_bands 출력을 그대로 받는다. 두 계약이 어긋나면
    KeyError 가 나므로, 실제 출력으로 한 번 통과시켜 계약을 고정한다."""
    from app.config import get_settings
    from app.funding import compute_bands
    from app.policy_params import PolicyParams
    params = PolicyParams.load(get_settings().policy_params_path)
    industry = "카페"
    if params.missing(industry):
        pytest.skip("업종 파라미터가 등록되지 않아 계약을 검증할 수 없습니다")
    computed_bands = compute_bands(params, industry=industry, area_pyeong=None, deposit_krw=None,
                                   monthly_rent_krw=2_500_000, monthly_maintenance_krw=0,
                                   key_money_krw=0, fitout_krw=None, equity_krw=100_000_000,
                                   existing_debt_krw=0, other_monthly_fixed_krw=0)
    lines = funding_section_lines({**computed_bands, "assumed": [], "as_of": "2026-07-28"})
    assert lines[0] == "자금조달 요약"
    assert any("권장 조달선" in line for line in lines)


# 두 픽스처는 파이프라인이 실제로 싣는 행 모양이다. KB는 pipeline/policy/normalize.py 의
# _kb_display(:351-363), 공고는 _program_display(:163-176) 가 만드는 display dict 를 따른다.
# 그 두 함수가 바뀌면 이 픽스처도 함께 바뀌어야 한다.
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


def test_a_product_and_a_program_both_render():
    lines = selection_section_lines([PRODUCT], [PROGRAM], 0)
    assert any("KB 소호모바일대출" in line for line in lines)
    assert any(PRODUCT["official_url"] in line for line in lines)
    assert any("소상공인 정책자금" in line for line in lines)
    assert any(PROGRAM["official_url"] in line for line in lines)


def test_a_half_disclosed_rate_marks_the_missing_side():
    lines = selection_section_lines([{**PRODUCT, "rate_min": None}], [], 0)
    assert any("?~5.2%" in line for line in lines)


def test_dropped_items_are_reported_not_swallowed():
    lines = selection_section_lines([PRODUCT], [], 2)
    assert any("2건" in line and "확인되지 않아 제외" in line for line in lines)


def test_everything_dropped_still_produces_the_section():
    lines = selection_section_lines([], [], 3)
    assert lines[0] == "고른 조달 수단"
    assert any("3건" in line for line in lines)


def test_an_empty_required_field_falls_back_instead_of_printing_blank():
    lines = selection_section_lines([{**PRODUCT, "name": ""}], [], 0)
    assert any("이름 확인 필요" in line for line in lines)


def test_an_unloadable_catalog_says_so_instead_of_claiming_the_ids_are_absent():
    """조회 실패도 빈 목록으로 내려오므로, 그때 '목록에 없다'고 적으면 카탈로그 내용에 대한
    거짓 주장이 문서에 남는다. 무슨 일이 있었는지만 적고 목록의 내용은 말하지 않는다."""
    lines = selection_section_lines([], [], 2, unavailable=True)
    assert any("불러오지 못해" in line and "2건" in line for line in lines)
    assert not any("확인되지 않아 제외" in line for line in lines)


def test_a_populated_catalog_keeps_the_missing_wording():
    lines = selection_section_lines([PRODUCT], [], 1, unavailable=False)
    assert any("확인되지 않아 제외" in line for line in lines)
    assert not any("불러오지 못해" in line for line in lines)


CASE = {"id": "22222222-2222-2222-2222-222222222222", "title": "강남구 카페", "version": 2,
        "inputs": {"industry": "카페", "district": "강남구", "committed_listing_id": "demo-강남구-0001"}}
DESCRIPTOR = {"document_id": "d-1", "template": "funding"}


def test_the_pdf_still_renders_with_only_two_arguments():
    assert render_case_pdf(CASE, DESCRIPTOR).startswith(b"%PDF")


def test_the_pdf_renders_with_funding_and_a_selection():
    payload = render_case_pdf(CASE, DESCRIPTOR, funding=computed(),
                              products=[PRODUCT], programs=[PROGRAM], dropped=1)
    assert payload.startswith(b"%PDF")


def test_the_two_new_sections_actually_reach_the_story(monkeypatch):
    """%PDF 로만 단언하면 루프가 아무것도 붙이지 않아도 통과한다. 실제로 실린 문단을 확인한다."""
    from reportlab.platypus import SimpleDocTemplate
    captured: list[str] = []
    original = SimpleDocTemplate.build

    def capture(self, story, *args, **kwargs):
        captured.extend(getattr(item, "text", "") for item in story)
        return original(self, story, *args, **kwargs)

    monkeypatch.setattr(SimpleDocTemplate, "build", capture)
    render_case_pdf(CASE, DESCRIPTOR, funding=computed(), products=[PRODUCT], programs=[PROGRAM], dropped=1)
    assert any("자금조달 요약" in text for text in captured)
    assert any("120,000,000원" in text for text in captured)
    assert any("고른 조달 수단" in text for text in captured)
    assert any("KB 소호모바일대출" in text for text in captured)
    assert any("1건" in text and "제외" in text for text in captured)
    selection_index = next(i for i, text in enumerate(captured) if "고른 조달 수단" in text)
    notice_index = next(i for i, text in enumerate(captured) if "AI가 작성한 초안이며" in text)
    assert selection_index < notice_index
