from app.document_store import render_case_pdf


def case_with_listing() -> dict:
    return {
        "id": "11111111-1111-1111-1111-111111111111", "title": "테스트", "version": 1,
        "inputs": {"industry": "카페", "district": "강남구", "budget_krw": 100_000_000,
                   "committed_listing_id": "demo-강남구-0001"},
    }


def test_pdf_names_the_listing_and_labels_it_as_demo():
    payload = render_case_pdf(case_with_listing(), {"document_id": "d1", "template": "cost"})
    assert payload.startswith(b"%PDF")
    text = payload.decode("latin-1", errors="ignore")
    # reportlab writes the listing id into the content stream; the label must survive into the file.
    assert "demo-" in text


def test_a_case_without_a_listing_still_renders():
    payload = render_case_pdf({"id": "x", "title": "t", "version": 1, "inputs": {"industry": "카페"}},
                              {"document_id": "d2", "template": "cost"})
    assert payload.startswith(b"%PDF")
