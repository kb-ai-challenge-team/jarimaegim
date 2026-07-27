from app.document_store import listing_section_lines, render_case_pdf


def case_with_listing() -> dict:
    return {
        "id": "11111111-1111-1111-1111-111111111111", "title": "테스트", "version": 1,
        "inputs": {"industry": "카페", "district": "강남구", "budget_krw": 100_000_000,
                   "committed_listing_id": "demo-강남구-0001"},
    }


def test_the_section_names_the_listing_and_labels_it_as_demo():
    lines = listing_section_lines(case_with_listing())
    assert any("demo-강남구-0001" in line for line in lines)
    assert any("시연용" in line for line in lines)
    assert any("실제 임대 매물이 아니" in line for line in lines)


def test_a_case_without_a_committed_listing_has_no_section():
    assert listing_section_lines({"inputs": {"industry": "카페"}}) == []


def test_a_case_with_no_inputs_at_all_has_no_section():
    assert listing_section_lines({}) == []


def test_the_pdf_renders_with_a_listing():
    payload = render_case_pdf(case_with_listing(), {"document_id": "d1", "template": "cost"})
    assert payload.startswith(b"%PDF")


def test_the_pdf_renders_without_a_listing():
    payload = render_case_pdf({"id": "x", "title": "t", "version": 1, "inputs": {"industry": "카페"}},
                              {"document_id": "d2", "template": "cost"})
    assert payload.startswith(b"%PDF")
