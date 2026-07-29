# 처방 단계 분리 — 조달과 서류 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한 화면에 쌓여 있던 처방(계획 기준 후보 · 자금조달 레포트 · 문서 초안)을 질문 하나씩을 가진 두 단계 — ④ 조달, ⑤ 서류 — 로 나누고, ④에서 고른 조달 수단이 실제로 ⑤의 PDF에 담기게 한다.

**Architecture:** 백엔드가 먼저다. `/api/v1/documents`가 선택된 상품·공고의 **id만** 받아 서버 카탈로그에서 표시 문자열을 되찾고, `funding_input`으로 받은 사실로 `compute_bands`를 다시 돌려 문서 수치를 만든다. PDF 본문은 `listing_section_lines`와 같은 방식으로 순수 함수(`funding_section_lines`, `selection_section_lines`)로 분리해 문자열로 단언한다. 그 위에서 프론트가 `FlowStep`에 `funding` · `paperwork`를 더하고 `PlanPrescription`을 `PlanFunding` · `PlanPaperwork` 둘로 가른다.

**Tech Stack:** FastAPI + pydantic v2 + reportlab (backend), Next.js App Router + React 19 클라이언트 컴포넌트 + 순수 CSS (frontend), pytest + playwright-core 스크립트 (검증)

**설계 문서:** `docs/superpowers/specs/2026-07-28-prescribe-step-split-design.md`

---

## 선행 조건과 스테퍼 칸 수

설계 문서는 선행 설계(`2026-07-28-funding-step-split-ai-conditions-design.md`, 자금을 ①로 승격)를 먼저 구현할 것을 권한다. **이 계획은 현재 저장소 상태(`STEPS`가 조건·입지·처방 3칸, `components/kb/JarimaegimPanel.tsx:14-16`) 위에서 실행 가능하도록 쓰여 있다.** 실행 후 스테퍼는 `[조건][입지][조달][서류]` 4칸이 된다.

선행 계획이 먼저 머지되면 달라지는 것은 **Task 8의 `STEPS` 배열 한 곳뿐이다** — 앞에 `{ id: "capacity", label: "자금" }`이 붙고 `stepIndex` 매핑에 `profile`·`capacity` → 0이 더해진다. 나머지 태스크는 영향을 받지 않는다. 검증(Task 6)의 단언도 칸 수를 세지 않고 라벨의 존재만 보므로 양쪽에서 그대로 통과한다.

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `backend/app/models.py` | 요청/응답 모델 | `FundingFacts` 분리, `DocumentCreate` 확장 |
| `backend/app/document_store.py` | PDF 바이트 생성 + 섹션 문자열 | `funding_section_lines` · `selection_section_lines` 신규, `render_case_pdf` 확장 |
| `backend/app/main.py` | 엔드포인트 배선 | `/documents`에 카탈로그 조회·밴드 재계산 추가 |
| `backend/tests/test_models_document.py` | 문서 요청 모델 계약 | 신규 |
| `backend/tests/test_pdf_funding.py` | 두 섹션 함수의 문자열 | 신규 |
| `backend/tests/test_api_documents.py` | 엔드포인트 동작 | 신규 |
| `lib/api.ts` | 유일한 fetch 계층 | `createDocument` 시그니처 확장 |
| `lib/use-jarimaegim.ts` | 흐름 전체의 상태 | `FlowStep` 확장, `selected`·`docConfirmed`, `commitCandidate` 저장 |
| `components/kb/JarimaegimPanel.tsx` | 스텝 라우팅·스테퍼·StepNav | 4칸 스테퍼, 두 새 화면 배선, 입지 다음 버튼 게이트 |
| `components/kb/JarimaegimPlan.tsx` | 처방 계열 화면 | `PlanPrescription` 제거, `PlanFunding`·`PlanPaperwork` 신규, 두 목록 섹션에 선택 기능 |
| `app/globals.css` | 스타일 | 새 클래스 4종 |
| `scripts/flow-check.mjs` | 무키 안전 상태 e2e | KB 흐름을 ⑤까지 연장 |
| `scripts/visual-check.mjs` | 뷰포트 스냅샷 | ④·⑤ 스냅샷 추가 |

---

## Task 1: `FundingFacts` 분리와 `DocumentCreate` 확장

**Files:**
- Modify: `backend/app/models.py:257-261`(DocumentCreate), `backend/app/models.py:274-287`(FundingBandInput)
- Test: `backend/tests/test_models_document.py` (신규)

문서 요청에 `case_id`가 두 번 실리면 바깥과 다른 값이 안쪽에 들어와 A 케이스의 문서에 B 케이스의 금액이 찍힐 수 있다. `case_id` 없는 기반 모델을 만들어 그 길을 닫는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_models_document.py`:

```python
import pytest
from pydantic import ValidationError

from app.models import DocumentCreate, FundingBandInput, FundingFacts

CASE_ID = "11111111-1111-1111-1111-111111111111"
FACTS = {"industry": "카페", "monthly_rent_krw": 2_500_000, "equity_krw": 100_000_000}


def test_funding_facts_has_no_case_id():
    facts = FundingFacts(**FACTS)
    assert "case_id" not in facts.model_dump()


def test_funding_band_input_still_carries_the_case_id():
    payload = FundingBandInput(case_id=CASE_ID, **FACTS)
    assert str(payload.case_id) == CASE_ID
    # 밴드 엔드포인트는 case_id 를 뺀 나머지를 compute_bands 에 그대로 넘긴다.
    assert set(payload.model_dump(exclude={"case_id"})) == set(FundingFacts(**FACTS).model_dump())


def test_document_create_defaults_to_no_selection_and_no_funding():
    payload = DocumentCreate(case_id=CASE_ID, template="funding", confirmed=True)
    assert payload.selected_product_ids == []
    assert payload.selected_program_ids == []
    assert payload.funding_input is None


def test_document_create_accepts_ids_and_facts():
    payload = DocumentCreate(case_id=CASE_ID, template="funding", confirmed=True,
                             selected_product_ids=["kb-1"], selected_program_ids=["pg-1"],
                             funding_input=FACTS)
    assert payload.selected_product_ids == ["kb-1"]
    assert payload.funding_input.industry == "카페"


def test_document_create_rejects_more_than_ten_ids():
    with pytest.raises(ValidationError):
        DocumentCreate(case_id=CASE_ID, template="funding", confirmed=True,
                       selected_product_ids=[f"kb-{index}" for index in range(11)])
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_document.py -v`
Expected: FAIL — `ImportError: cannot import name 'FundingFacts' from 'app.models'`

- [ ] **Step 3: 모델을 고친다**

`backend/app/models.py`에서 `class DocumentCreate`(257-261행)를 다음으로 바꾼다:

```python
class DocumentCreate(BaseModel):
    case_id: UUID
    template: Literal["location", "cost", "funding", "business", "checklist"]
    confirmed: bool
    # 선택은 id 로만 받는다. 이름·금리·URL 은 서버가 카탈로그에서 되찾는다 — 클라이언트가 보낸
    # 문자열을 그대로 인쇄하면 조작된 상품명과 금리가 KB 문서 모양으로 찍힌다.
    selected_product_ids: list[str] = Field(default_factory=list, max_length=10)
    selected_program_ids: list[str] = Field(default_factory=list, max_length=10)
    funding_input: "FundingFacts | None" = None
```

이어서 `class FundingBandInput`(274-287행)을 두 개로 가른다:

```python
class FundingFacts(BaseModel):
    """밴드 산출에 필요한 사실만. 케이스 식별자는 담지 않는다 — 문서 요청처럼 바깥에 이미
    case_id 가 있는 곳에서 두 번 싣지 않기 위해서다.

    평수·보증금은 필요자금(→현금소진)에만 쓰이므로 없어도 밴드 상한과 손익분기는 계산된다."""

    industry: str = Field(min_length=1, max_length=120)
    area_pyeong: float | None = Field(default=None, gt=0, le=500)
    deposit_krw: int | None = Field(default=None, ge=0, le=100_000_000_000)
    monthly_rent_krw: int = Field(ge=0, le=1_000_000_000)
    monthly_maintenance_krw: int = Field(default=0, ge=0, le=1_000_000_000)
    key_money_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    fitout_krw: int | None = Field(default=None, ge=0, le=100_000_000_000)
    equity_krw: int = Field(ge=0, le=100_000_000_000)
    existing_debt_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    other_monthly_fixed_krw: int = Field(default=0, ge=0, le=1_000_000_000)


class FundingBandInput(FundingFacts):
    case_id: UUID
```

`DocumentCreate`가 `FundingFacts`를 문자열 주석으로 참조하므로 `FundingBandInput` 정의 뒤에 한 줄을 더한다:

```python
DocumentCreate.model_rebuild()
```

이 줄은 `class FundingBandInput(FundingFacts):` 블록 바로 아래에 둔다.

- [ ] **Step 4: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_document.py tests/test_models_funding.py tests/test_api_funding_bands.py -v`
Expected: PASS — 새 5건과 기존 밴드 테스트 전부

- [ ] **Step 5: 커밋**

```bash
git add backend/app/models.py backend/tests/test_models_document.py
git commit -m "feat(models): let a document request carry chosen ids and funding facts"
```

---

## Task 2: `funding_section_lines`

**Files:**
- Modify: `backend/app/document_store.py:48-49` 아래
- Test: `backend/tests/test_pdf_funding.py` (신규)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_pdf_funding.py`:

```python
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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_funding.py -v`
Expected: FAIL — `ImportError: cannot import name 'FUNDING_OMITTED'`

- [ ] **Step 3: 함수를 쓴다**

`backend/app/document_store.py`의 `LISTING_DEMO_NOTICE`(48-49행) 아래에 넣는다:

```python
FUNDING_OMITTED = "조달 밴드를 계산하지 못해 이 문서에는 조달 요약이 없습니다."


def krw(value: int | None) -> str:
    """금액 표기. 없는 값은 0 이 아니라 '확인 필요'다 — 없는 것을 0 으로 적으면 계산된 0 처럼 읽힌다."""
    return "확인 필요" if value is None else f"{value:,}원"


def funding_section_lines(funding: dict[str, Any] | None) -> list[str]:
    """조달 요약 줄. 첫 줄은 언제나 제목이고, 계산이 없으면 없다는 사실을 그 자리에 적는다.

    화면이 계산한 숫자를 받지 않는다. 호출부가 compute_bands 를 다시 돌린 결과를 넘긴다.
    """
    bands = (funding or {}).get("bands") or []
    line = next((band for band in bands if band["band"] == "RECOMMENDED"), None)
    if funding is None or line is None:
        return ["자금조달 요약", FUNDING_OMITTED]
    lines = ["자금조달 요약",
             f"권장 조달선: {krw(line['ceiling_krw'])}",
             f"차입 필요액: {krw(line['loan_krw'])}",
             f"월 상환: {krw(line['monthly_repayment_krw'])}",
             f"넘어야 하는 일매출: {krw(line['target_daily_revenue_krw'])}"]
    required = funding.get("required_capital_krw")
    lines.append(f"필요자금: {krw(required)}" if required is not None
                 else "필요자금: 확인 필요 — 평수·보증금을 입력하지 않아 계산하지 않았습니다")
    assumed = funding.get("assumed") or []
    if assumed:
        lines.append(f"위 금액은 시연용 가정값 {len(assumed)}개 항목 위에서 계산했습니다. "
                     "공고 원문으로 확인한 값이 아니므로 실제 심사 결과와 다릅니다.")
    lines.append(f"출처: 자리매김 조달 밴드 계산 · 기준일 {funding.get('as_of') or '확인 필요'}")
    return lines
```

- [ ] **Step 4: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_funding.py -v`
Expected: PASS — 6건

- [ ] **Step 5: 커밋**

```bash
git add backend/app/document_store.py backend/tests/test_pdf_funding.py
git commit -m "feat(pdf): say the funding numbers, or say why they are absent"
```

---

## Task 3: `selection_section_lines`

**Files:**
- Modify: `backend/app/document_store.py` (Task 2가 넣은 함수 아래)
- Test: `backend/tests/test_pdf_funding.py` (같은 파일에 추가)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_pdf_funding.py` 끝에 덧붙인다:

```python
from app.document_store import selection_section_lines

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
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_funding.py -v`
Expected: FAIL — `ImportError: cannot import name 'selection_section_lines'`

- [ ] **Step 3: 함수를 쓴다**

`backend/app/document_store.py`의 `funding_section_lines` 아래에 넣는다:

```python
def rate_text(product: dict[str, Any]) -> str:
    """공시 금리 표기. 두 공시값을 나란히 적을 뿐 평균·환산 같은 계산을 하지 않는다.
    화면의 rateLabel(components/kb/JarimaegimPlan.tsx)과 같은 규칙이어야 문서와 화면이 갈라지지 않는다."""
    low, high = product.get("rate_min"), product.get("rate_max")
    if low is None and high is None:
        return "공시 금리 확인 필요"
    if low == high:
        return f"{low}%"
    return f"{'?' if low is None else low}~{'?' if high is None else high}%"


def selection_section_lines(products: list[dict[str, Any]], programs: list[dict[str, Any]],
                            dropped: int) -> list[str]:
    """사용자가 고른 조달 수단. 전달된 dict 는 서버 카탈로그에서 되찾은 것이며 클라이언트 문자열이 아니다."""
    if not products and not programs and dropped == 0:
        return ["고른 조달 수단", "고른 조달 수단이 없습니다."]
    lines = ["고른 조달 수단"]
    for product in products:
        lines.append(f"[KB 공시] {product.get('name', '이름 확인 필요')} · "
                     f"{product.get('loan_limit') or '한도 원문 확인'} · {rate_text(product)} · "
                     f"기준월 {product.get('source_as_of') or '확인 필요'}")
        lines.append(f"원문: {product.get('official_url', '확인 필요')}")
    for program in programs:
        lines.append(f"[공고] {program.get('title', '제목 확인 필요')} · "
                     f"{program.get('organization', '기관 확인 필요')} · "
                     f"{program.get('application_period') or '기간 원문 확인'}")
        lines.append(f"원문: {program.get('official_url', '확인 필요')}")
    lines.append("공시·공고 문구와 입력 조건을 텍스트로 대조해 고른 목록이며, 자격이나 승인 가능성을 판단한 것이 아닙니다.")
    if dropped:
        lines.append(f"{dropped}건은 공시 목록에서 확인되지 않아 제외했습니다.")
    return lines
```

- [ ] **Step 4: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_funding.py -v`
Expected: PASS — 14건(Task 2의 6건 + 8건)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/document_store.py backend/tests/test_pdf_funding.py
git commit -m "feat(pdf): list the chosen funding options with their disclosed strings"
```

---

## Task 4: `render_case_pdf`에 두 섹션을 싣는다

**Files:**
- Modify: `backend/app/document_store.py:64-97`
- Test: `backend/tests/test_pdf_funding.py` (추가)

기존 호출부(`main.py`)와 기존 테스트(`test_pdf_listing.py`)가 인자 두 개로 부르므로 새 인자는 전부 기본값 있는 키워드여야 한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_pdf_funding.py` 끝에 덧붙인다:

```python
from app.document_store import render_case_pdf

CASE = {"id": "22222222-2222-2222-2222-222222222222", "title": "강남구 카페", "version": 2,
        "inputs": {"industry": "카페", "district": "강남구", "committed_listing_id": "demo-강남구-0001"}}
DESCRIPTOR = {"document_id": "d-1", "template": "funding"}


def test_the_pdf_still_renders_with_only_two_arguments():
    assert render_case_pdf(CASE, DESCRIPTOR).startswith(b"%PDF")


def test_the_pdf_renders_with_funding_and_a_selection():
    payload = render_case_pdf(CASE, DESCRIPTOR, funding=computed(),
                              products=[PRODUCT], programs=[PROGRAM], dropped=1)
    assert payload.startswith(b"%PDF")
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_funding.py -k render -v`
Expected: FAIL — `TypeError: render_case_pdf() got an unexpected keyword argument 'funding'`

- [ ] **Step 3: 시그니처와 본문을 고친다**

`backend/app/document_store.py:64`의 선언을 바꾼다:

```python
def render_case_pdf(case: dict[str, Any], document: dict[str, Any], *,
                    funding: dict[str, Any] | None = None,
                    products: list[dict[str, Any]] | None = None,
                    programs: list[dict[str, Any]] | None = None,
                    dropped: int = 0) -> bytes:
```

그리고 매물 섹션을 붙이는 블록(89-94행) 바로 뒤, 비보장 고지(95행) 바로 앞에 넣는다:

```python
    # 조달 요약과 고른 수단은 언제나 제목 + 최소 한 줄을 돌려주므로 빈 검사가 필요 없다.
    # 계산하지 못했다는 사실도 문서에 남아야 하기 때문에 그렇게 설계했다.
    for section in (funding_section_lines(funding),
                    selection_section_lines(products or [], programs or [], dropped)):
        heading, *body = section
        story.append(Spacer(1, 16))
        story.append(Paragraph(heading, styles["Heading2"]))
        story.extend(Paragraph(line, styles["BodyText"]) for line in body)
```

- [ ] **Step 4: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pdf_funding.py tests/test_pdf_listing.py -v`
Expected: PASS — 16건 전부(기존 매물 테스트 5건 포함)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/document_store.py backend/tests/test_pdf_funding.py
git commit -m "feat(pdf): put the funding summary and the chosen options into the draft"
```

---

## Task 5: `/documents`가 id를 되찾고 밴드를 다시 계산한다

**Files:**
- Modify: `backend/app/main.py:24`(import), `backend/app/main.py:575-588`
- Test: `backend/tests/test_api_documents.py` (신규)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_api_documents.py`:

```python
"""문서 엔드포인트. 카탈로그는 Supabase 가 없으면 빈 목록이므로 조회 함수를 직접 갈아 끼운다."""
import pytest
from fastapi.testclient import TestClient

from app import main

PRODUCT = {"id": "kb-1", "name": "KB 소호모바일대출", "loan_limit": "최대 1억원",
           "rate_min": 3.9, "rate_max": 5.2, "source_as_of": "2026-07",
           "official_url": "https://obank.kbstar.com/example"}
PROGRAM = {"id": "pg-1", "title": "소상공인 정책자금", "organization": "소상공인시장진흥공단",
           "application_period": "2026-08-01 ~ 2026-08-31",
           "official_url": "https://www.semas.or.kr/example"}
CASE_INPUTS = {"industry": "카페", "district": "강남구", "budget_krw": 100_000_000,
               "equity_krw": 100_000_000, "business_stage": "PRE_OPEN",
               "startup_type": "INDEPENDENT", "priority": "STABILITY"}
FACTS = {"industry": "카페", "monthly_rent_krw": 2_500_000, "equity_krw": 100_000_000}


@pytest.fixture()
def client(monkeypatch):
    async def products():
        return [PRODUCT]

    async def programs():
        return [PROGRAM]

    monkeypatch.setattr(main.knowledge, "kb_products", products)
    monkeypatch.setattr(main.knowledge, "programs", programs)
    with TestClient(main.app) as test_client:
        test_client.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield test_client


def make_case(client) -> str:
    response = client.post("/api/v1/cases", json={"title": "강남구 카페", "inputs": CASE_INPUTS})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_unconfirmed_requests_are_still_refused(client):
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={"case_id": case_id, "template": "funding", "confirmed": False})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CONSENT_REQUIRED"


def test_a_document_is_created_without_any_selection(client):
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={"case_id": case_id, "template": "funding", "confirmed": True})
    assert response.status_code == 201, response.text
    assert "제외" not in response.json()["message"]


def test_unknown_ids_are_dropped_and_counted_in_the_message(client):
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1", "kb-does-not-exist"],
        "selected_program_ids": ["pg-gone"]})
    assert response.status_code == 201, response.text
    assert "2건" in response.json()["message"]
    assert "확인되지 않아 제외" in response.json()["message"]


def test_the_document_downloads_as_a_pdf(client):
    case_id = make_case(client)
    created = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True,
        "selected_product_ids": ["kb-1"], "funding_input": FACTS})
    document_id = created.json()["document_id"]
    downloaded = client.get(f"/api/v1/documents/{document_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF")


def test_a_mismatched_industry_does_not_break_the_request(client):
    """등록되지 않은 업종이면 조달 요약만 빠지고 문서는 그대로 만들어진다."""
    case_id = make_case(client)
    response = client.post("/api/v1/documents", json={
        "case_id": case_id, "template": "funding", "confirmed": True,
        "funding_input": {**FACTS, "industry": "존재하지않는업종"}})
    assert response.status_code == 201, response.text
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_documents.py -v`
Expected: FAIL — `test_unknown_ids_are_dropped_and_counted_in_the_message`가 `message`에 "2건"이 없어 실패(나머지는 통과할 수 있다)

- [ ] **Step 3: 엔드포인트를 고친다**

`backend/app/main.py:24`의 models import에 `FundingFacts`를 더한다:

```python
from .models import (AnalysisCreate, BandLine, BreakEven, CaseCreate, CasePatch, CaseRecord, CostPlanCreate,
                     DocumentCreate, FundingBandInput, FundingBandResult, FundingFacts, LocationSearch,
                     MessageCreate, PrivacyRequestCreate, Provenance, RetrievalResponse, SessionCreate)
```

`document_store` import(23행)를 두 함수까지 받도록 바꾼다:

```python
from .document_store import DocumentStore, render_case_pdf
```

는 그대로 두고, `create_document` 바로 위에 두 헬퍼를 넣는다:

```python
async def catalog_selection(payload: DocumentCreate) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """고른 id 를 서버 카탈로그에서 되찾는다. 화면이 보낸 이름·금리·URL 은 쓰지 않는다.

    조회되지 않는 id 는 422 로 막지 않고 제외한 뒤 건수를 알린다 — 카탈로그가 갱신된 사이
    사용자가 갇히지 않게 하되, 조용히 자르지도 않기 위해서다."""
    if not payload.selected_product_ids and not payload.selected_program_ids:
        return [], [], 0
    products = {item["id"]: item for item in await knowledge.kb_products() if item.get("id")}
    programs = {item["id"]: item for item in await knowledge.programs() if item.get("id")}
    chosen_products = [products[key] for key in payload.selected_product_ids if key in products]
    chosen_programs = [programs[key] for key in payload.selected_program_ids if key in programs]
    dropped = ((len(payload.selected_product_ids) - len(chosen_products))
               + (len(payload.selected_program_ids) - len(chosen_programs)))
    return chosen_products, chosen_programs, dropped


def document_funding(facts: FundingFacts | None) -> dict[str, Any] | None:
    """문서에 실을 조달 요약. 화면이 계산한 숫자를 받지 않고 같은 산식을 다시 돌린다 —
    /funding-bands 와 문서가 갈라지지 않는 유일한 방법이다. 계산할 수 없으면 None 이고,
    그때 문서는 조달 요약이 없다는 사실을 그대로 적는다."""
    if facts is None or policy_params.missing(facts.industry):
        return None
    try:
        computed = compute_bands(policy_params, **facts.model_dump())
    except ValueError:
        return None
    return {**computed, "assumed": policy_params.assumed(facts.industry), "as_of": policy_params.updated_at}
```

그리고 `create_document`(575-588행)의 본문에서 `pdf = ...` 줄과 `return` 줄을 바꾼다:

```python
    funding = document_funding(payload.funding_input)
    products, programs, dropped = await catalog_selection(payload)
    try:
        pdf = await asyncio.to_thread(render_case_pdf, case.model_dump(mode="json"), descriptor,
                                      funding=funding, products=products, programs=programs, dropped=dropped)
        document = document_store.save(owner_session_id=session_id, case_id=payload.case_id, template=payload.template, pdf=pdf, document_id=document_id)
    except OSError as exc:
        raise HTTPException(500, {"code": "DOCUMENT_STORAGE_FAILED", "message": "PDF를 안전하게 저장하지 못했습니다."}) from exc
    message = "PDF가 준비되었습니다. 현재 익명 세션에서 다운로드할 수 있습니다."
    if dropped:
        message += f" {dropped}건은 공시 목록에서 확인되지 않아 제외했습니다."
    return {**document, "message": message}
```

`render_case_pdf`가 두 섹션 함수를 부르므로 `document_store` 안에서 해결된다 — `main.py`는 추가 import가 필요 없다.

- [ ] **Step 4: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_documents.py -v`
Expected: PASS — 5건

- [ ] **Step 5: 백엔드 전체를 돌린다**

Run: `npm run api:test`
Expected: PASS — 기존 191건 + 새 27건 (`-m "not slow"`로 빠르게 돌려도 된다)

- [ ] **Step 6: 커밋**

```bash
git add backend/app/main.py backend/tests/test_api_documents.py
git commit -m "feat(documents): resolve chosen ids server-side and recompute the bands"
```

---

## Task 6: 검증 스크립트를 먼저 늘린다 (실패하는 e2e)

**Files:**
- Modify: `scripts/flow-check.mjs:172-234`

UI를 만들기 전에 단언을 먼저 둔다. 이 태스크가 끝나면 `flow-check`는 **실패해야 한다**.

- [ ] **Step 1: KB 흐름 단언을 고쳐 쓴다**

`scripts/flow-check.mjs:205-217`의 `stepperLabels`·`kbFlow` 블록을 다음으로 바꾼다:

```js
const stepperLabels = await kb.locator(".kb-stepper li").allTextContents();
const bandBannerShown = await kb.locator(".kb-band-banner").count() > 0;
const kbFlow = {
  gateVisible,
  stepCount: stepperLabels.length,
  // 처방 한 칸이 조달·서류 두 칸으로 갈라졌는지만 본다. 칸 수를 세지 않는 이유는 자금 단계
  // 분리가 먼저 들어오면 앞에 한 칸이 더 붙기 때문이다 — 그때도 이 단언은 그대로 옳다.
  prescribeSplit: stepperLabels.some(label => label.includes("조달"))
    && stepperLabels.some(label => label.includes("서류"))
    && !stepperLabels.some(label => label.includes("처방")),
  candidates: await kb.locator(".kb-candidates li").count(),
  tuningInPlace: await kb.getByRole("button", { name: /정밀하게 맞추기/ }).count() > 0,
  bandSafeState: bandBannerShown || await kb.locator(".kb-step > .kb-note", { hasText: "파라미터가 아직 등록되지" }).count() > 0
};
```

- [ ] **Step 2: 조달·서류 단계를 실제로 걸어가는 블록을 더한다**

`scripts/flow-check.mjs`의 근거 펼치기 블록(219-226행) **뒤**, `const result = {...}`(228행) **앞**에 넣는다:

```js
// ④ 조달 · ⑤ 서류. 후보를 확정해야 부족분이 확정되므로 확정 전에는 다음으로 갈 수 없어야 한다.
const prescribe = { reachedFunding: false, reachedPaperwork: false };
if (kbFlow.candidates > 0) {
  prescribe.nextLockedBeforeCommit = await kb.getByRole("button", { name: /다음/ }).isDisabled();
  await kb.getByRole("button", { name: "계획 기준으로 확정" }).first().click();
  // 계획 기준 배지는 조달 화면에만 있다. 확정 직후에는 아직 입지 화면이므로 목록 안에서
  // 확정 표시(kb-primary-sm)로 바뀐 것을 기다린다.
  await kb.waitForSelector(".kb-candidate-actions .kb-primary-sm");
  prescribe.nextUnlockedAfterCommit = !(await kb.getByRole("button", { name: /다음/ }).isDisabled());

  await kb.getByRole("button", { name: /다음/ }).click();
  await kb.waitForSelector(".kb-gap-card");
  prescribe.reachedFunding = true;
  // 무키 환경에서는 Supabase 가 없어 공시·공고가 둘 다 0건이다. 그것이 정상 경로이며,
  // 그때도 서류로 넘어갈 수 있어야 한다.
  prescribe.emptyCatalogExplained = await kb.getByText("고를 수단이 없습니다").count() > 0
    || await kb.locator(".kb-select-row").count() > 0;

  await kb.getByRole("button", { name: /문서 만들기|서류로/ }).click();
  await kb.waitForSelector(".kb-doc-preview");
  prescribe.reachedPaperwork = true;
  prescribe.previewListsSections = (await kb.locator(".kb-doc-preview li").count()) >= 4;
  // 동의 전에는 준비 버튼이 잠겨 있어야 한다. 서버의 422 는 그대로 남아 있는 방어선이다.
  prescribe.prepareLockedBeforeConsent = await kb.getByRole("button", { name: /초안 준비하기/ }).isDisabled();
  await kb.getByRole("checkbox", { name: /문서에 담기는 것을 확인/ }).check();
  prescribe.prepareUnlockedAfterConsent = !(await kb.getByRole("button", { name: /초안 준비하기/ }).isDisabled());
}
// 번호 매긴 처방 블록이 남아 있으면 단계 분리가 되돌아간 것이다.
prescribe.noNumberedBlocks = await kb.locator(".kb-prescription-no").count() === 0;
```

- [ ] **Step 3: 결과와 종료 코드에 반영한다**

228행의 `const result = ...`에 `prescribe`를 더한다:

```js
const result = { onboarding, listings, cost, funding, search, bands, axes, document: documentResult, copilot, kbFlow, mydataGate, conditionStep, prescribe, errors };
```

232행을 다음으로 바꾼다:

```js
if (!kbFlow.gateVisible || !kbFlow.prescribeSplit || !kbFlow.tuningInPlace || !kbFlow.bandSafeState || !kbFlow.evidenceInline) process.exitCode = 1;
if (!prescribe.noNumberedBlocks) process.exitCode = 1;
if (kbFlow.candidates > 0 && (!prescribe.reachedFunding || !prescribe.reachedPaperwork || !prescribe.nextLockedBeforeCommit || !prescribe.nextUnlockedAfterCommit || !prescribe.emptyCatalogExplained || !prescribe.previewListsSections || !prescribe.prepareLockedBeforeConsent || !prescribe.prepareUnlockedAfterConsent)) process.exitCode = 1;
```

- [ ] **Step 4: 실패를 확인한다**

두 터미널이 필요하다. 하나에서 `npm run dev`를 띄운 뒤:

Run: `node scripts/flow-check.mjs; echo "exit=$?"`
Expected: 실패 — `.kb-plan-badge`를 기다리다 타임아웃하거나 `prescribeSplit: false`로 `exit=1`

- [ ] **Step 5: 커밋**

```bash
git add scripts/flow-check.mjs
git commit -m "test(flow): assert the prescribe step split before it exists"
```

---

## Task 7: 흐름 상태 — 두 스텝, 선택, 케이스 저장

**Files:**
- Modify: `lib/use-jarimaegim.ts:11`, `:328-344`, `:346-357`, `:401-402`, `:434-440`, `:442-450`
- Modify: `lib/api.ts:221`

- [ ] **Step 1: `FlowStep`을 늘린다**

`lib/use-jarimaegim.ts:9-11`의 주석과 타입을 바꾼다:

```ts
// 금융 프로필을 한 번 확정한 뒤 조건 → 입지 → 조달 → 서류로 간다. 프로필은 스텝이 아니라 진입 관문이고,
// 확정한 값은 케이스 생성·밴드 산출·재검색이 전부 다시 읽는다. 후보를 보기 전에 다시 금액을 묻지 않는다.
// 조달과 서류가 갈라져 있는 이유는 데이터에 있다 — 부족분은 후보를 확정해야 확정되고, 조달에서 고른
// 수단은 서류가 만드는 문서의 내용을 바꾼다.
export type FlowStep = "profile" | "ask" | "confirm" | "recommend" | "funding" | "paperwork";
```

- [ ] **Step 2: 선택 상태를 더한다**

`const [docNotice, setDocNotice] = useState("");`(89행) 바로 아래에 넣는다:

```ts
  // 화면에 보인 순서를 그대로 들고 있는다. 문서의 나열 순서가 화면과 같아야 대조가 된다.
  const [selected, setSelected] = useState<{ products: string[]; programs: string[] }>({ products: [], programs: [] });
  const [docConfirmed, setDocConfirmed] = useState(false);
```

`setProfileField` 정의(149-151행) 아래에 토글을 더한다:

```ts
  const toggleFunding = useCallback((kind: "products" | "programs", id: string) => {
    setSelected((prev) => {
      const list = prev[kind];
      return { ...prev, [kind]: list.includes(id) ? list.filter((item) => item !== id) : [...list, id] };
    });
  }, []);
```

- [ ] **Step 3: `commitCandidate`가 케이스에 저장하고 선택을 비운다**

328-344행의 `commitCandidate`를 다음으로 바꾼다(주석 블록 322-327행은 그대로 두고 그 아래 본문만):

```ts
  const commitCandidate = useCallback((candidateId: string | null) => {
    setCommitted(candidateId);
    // 후보가 바뀌면 부족분이 바뀐다. 그 부족분으로 고른 수단은 근거를 잃으므로 함께 비운다.
    setDocuments({}); setDocNotice(""); setSelected({ products: [], programs: [] }); setDocConfirmed(false);
    if (!caseData) return;
    // 케이스에 남겨야 PDF 의 매물 섹션과 대화의 상권 맥락이 산다. 저장이 실패해도 방금 한
    // 확정을 되돌리지 않는다 — 사용자가 누른 것을 서버 사정으로 취소해서는 안 된다.
    void api.updateCase(caseData.id, caseData.version, { committed_listing_id: candidateId })
      .then(setCaseData).catch(() => undefined);
    if (!candidateId) return;
    const listing = candidates.find((candidate) => candidate.id === candidateId)?.listing;
    if (!listing) return;
    const next: BandForm = {
      ...bandForm,
      area_pyeong: Number((listing.area_m2 / PYEONG_IN_M2).toFixed(1)),
      deposit_krw: listing.deposit_krw,
      monthly_rent_krw: listing.monthly_rent_krw,
      monthly_maintenance_krw: listing.maintenance_fee_krw ?? 0,
      key_money_krw: listing.key_money_krw ?? 0
    };
    setBandForm(next);
    void runBands(caseData, next, profile).catch(() => setBandState("error"));
  }, [bandForm, candidates, caseData, profile, runBands]);
```

- [ ] **Step 4: `prepareDocument`가 선택과 사실을 보낸다**

346-357행의 `prepareDocument`를 바꾼다:

```ts
  /** 문서 초안. 백엔드가 PDF 를 만들고 익명 세션에서만 내려받을 수 있다.
   *  선택은 id 로만 보내고 표시 문자열은 서버가 카탈로그에서 되찾는다. 금액은 서버가
   *  같은 산식으로 다시 계산하므로 여기서 계산한 값을 보내지 않는다. */
  const prepareDocument = useCallback(async (template: string) => {
    if (!caseData || !docConfirmed) return;
    setDocBusy(template); setDocNotice("");
    try {
      const record = await api.createDocument(caseData.id, template, {
        confirmed: docConfirmed,
        selected_product_ids: selected.products,
        selected_program_ids: selected.programs,
        funding_input: bandForm.monthly_rent_krw > 0
          ? { industry: caseData.inputs.industry, ...bandForm, ...profile }
          : null
      });
      setDocuments((prev) => ({ ...prev, [template]: record.document_id }));
      setDocNotice(record.message);
    } catch (err) {
      setDocNotice(err instanceof ApiError ? err.message : "문서를 준비하지 못했습니다.");
    } finally { setDocBusy(""); }
  }, [bandForm, caseData, docConfirmed, profile, selected]);
```

- [ ] **Step 5: 로딩 트리거와 `restart`를 옮긴다**

401-402행을 바꾼다:

```ts
  useEffect(() => { if (step === "funding" && programState === "idle") void loadPrograms(); }, [step, programState, loadPrograms]);
  useEffect(() => { if (step === "funding" && kbState === "idle") void loadKbProducts(); }, [step, kbState, loadKbProducts]);
```

439행(`setCommitted(null); setDocuments({}); ...`)을 바꾼다:

```ts
    setCommitted(null); setDocuments({}); setDocBusy(""); setDocNotice(""); setTraceOpen(false);
    setSelected({ products: [], programs: [] }); setDocConfirmed(false);
```

- [ ] **Step 6: 반환 객체에 더한다**

447행(`committed, commitCandidate, documents, ...`)을 바꾼다:

```ts
    committed, commitCandidate, documents, docBusy, docNotice, prepareDocument, downloadDocument,
    selected, toggleFunding, docConfirmed, setDocConfirmed,
```

- [ ] **Step 7: `lib/api.ts`의 `createDocument`를 바꾼다**

221행을 다음으로 바꾼다:

```ts
  // 선택은 id 로만 보낸다. 이름·금리·URL 을 실어 보내면 서버가 그것을 그대로 인쇄하게 되고,
  // 조작된 문자열이 KB 문서 모양으로 찍히는 길이 열린다.
  createDocument: (caseId: string, template: string, plan: { confirmed: boolean; selected_product_ids: string[]; selected_program_ids: string[]; funding_input: FundingBandInput | null }) =>
    request<DocumentRecord>("/documents", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, template, ...plan }) }),
```

`lib/api.ts` 상단의 타입 import에 `FundingBandInput`이 이미 있는지 확인하고 없으면 더한다(`lib/types.ts:364`의 `FundingBandInput`은 `case_id`를 담지 않으므로 서버의 `FundingFacts`와 정확히 같은 모양이다 — TS 쪽에 새 타입이 필요 없다).

- [ ] **Step 8: 타입을 확인한다**

Run: `npm run typecheck`
Expected: `components/kb/JarimaegimPanel.tsx`에서 `prescribe` 스텝을 참조하는 오류만 남는다(Task 8이 고친다). `use-jarimaegim.ts`와 `api.ts` 자체 오류는 없어야 한다.

- [ ] **Step 9: 커밋**

```bash
git add lib/use-jarimaegim.ts lib/api.ts
git commit -m "feat(flow): add the 조달/서류 steps, keep the chosen options, save the commit to the case"
```

---

## Task 8: 스테퍼·라우팅·입지 게이트

**Files:**
- Modify: `components/kb/JarimaegimPanel.tsx:13-16`, `:44-53`, `:361-372`

- [ ] **Step 1: `STEPS`를 4칸으로**

13-16행을 바꾼다:

```tsx
// 금융 프로필은 스텝이 아니라 진입 관문이다. 스테퍼는 조건 → 입지 → 조달 → 서류 넷이다.
const STEPS: { id: FlowStep; label: string }[] = [
  { id: "ask", label: "조건" }, { id: "recommend", label: "입지" },
  { id: "funding", label: "조달" }, { id: "paperwork", label: "서류" }
];
```

> 선행 계획(자금 승격)이 먼저 머지되어 있다면 이 배열 맨 앞에 `{ id: "capacity", label: "자금" }`을 넣고, 아래 `stepIndex` 계산의 삼항에 `flow.step === "capacity" ? "capacity" : ...`를 더한다. 그 외에는 이 태스크의 나머지가 그대로다.

- [ ] **Step 2: 두 화면을 배선한다**

44-53행(`{flow.step === "recommend" && ...}`부터 `<StepNav .../>`까지)을 바꾼다:

```tsx
      {flow.step === "recommend" && <RecommendStep flow={flow} />}
      {flow.step === "funding" && flow.caseData && <PlanFunding caseData={flow.caseData}
        committed={flow.candidates.find((item) => item.id === flow.committed) || null}
        bands={flow.bands} programs={flow.programs} programState={flow.programState}
        kbProducts={flow.kbProducts.filter((product) => product.category === "BUSINESS_LOAN")} kbState={flow.kbState}
        applicationEnabled={Boolean(flow.status?.feature_flags.financial_application)}
        selected={flow.selected} onToggle={flow.toggleFunding}
        onBackToLocation={() => flow.setStep("recommend")} onNext={() => flow.setStep("paperwork")} />}
      {flow.step === "paperwork" && flow.caseData && <PlanPaperwork caseData={flow.caseData}
        committed={flow.candidates.find((item) => item.id === flow.committed) || null}
        bands={flow.bands}
        products={flow.kbProducts.filter((product) => flow.selected.products.includes(product.id))}
        programs={flow.programs.filter((program) => flow.selected.programs.includes(program.id))}
        documents={flow.documents} docBusy={flow.docBusy} docNotice={flow.docNotice}
        confirmed={flow.docConfirmed} onConfirm={flow.setDocConfirmed}
        onPrepareDocument={(template) => flow.documents[template] ? flow.downloadDocument(template) : flow.prepareDocument(template)}
        onBackToFunding={() => flow.setStep("funding")} />}
      {flow.caseData && (flow.step === "recommend" || flow.step === "funding" || flow.step === "paperwork") && <StepNav flow={flow} />}
```

11행의 import를 바꾼다:

```tsx
import { PlanFunding, PlanPaperwork, PlanTuning, runwayLabel } from "./JarimaegimPlan";
```

- [ ] **Step 3: `StepNav`에 게이트를 단다**

361-372행의 `StepNav`를 바꾼다:

```tsx
/** 후보를 확정해야 부족분이 확정되므로, 확정 전에는 조달로 넘어가지 못한다.
 *  잠그는 이유를 버튼 옆에 쓴다 — 눌리지 않는 버튼만 두면 고장으로 읽힌다. */
function StepNav({ flow }: { flow: Jarimaegim }) {
  const order: FlowStep[] = ["recommend", "funding", "paperwork"];
  const index = order.indexOf(flow.step);
  const next = order[index + 1];
  const previous = order[index - 1];
  const labels: Record<string, string> = { recommend: "입지", funding: "조달", paperwork: "서류" };
  const blocked = flow.step === "recommend" && !flow.committed;
  return <>
    {blocked && <p className="kb-note"><CircleHelp aria-hidden="true" />계획 기준 후보를 하나 확정해야 조달 계획을 세울 수 있습니다.</p>}
    <div className="kb-stepnav">
      {previous ? <button className="kb-ghost" onClick={() => flow.setStep(previous)} aria-label={`이전 단계 ${labels[previous]}`}>← 이전</button>
        : <button className="kb-ghost" onClick={flow.restart}><RotateCcw aria-hidden="true" /> 조건 다시 입력</button>}
      {next && <button className="kb-primary kb-primary-sm" disabled={blocked} onClick={() => flow.setStep(next)} aria-label={`다음 단계 ${labels[next]}`}>다음 <ArrowRight aria-hidden="true" /></button>}
    </div>
  </>;
}
```

- [ ] **Step 4: 타입을 확인한다**

Run: `npm run typecheck`
Expected: `PlanFunding`·`PlanPaperwork`가 아직 없어 실패(Task 9·10이 만든다). `prescribe` 관련 오류는 사라져 있어야 한다.

- [ ] **Step 5: 커밋**

```bash
git add components/kb/JarimaegimPanel.tsx
git commit -m "feat(kb): route the two new steps and lock 다음 until a candidate is committed"
```

---

## Task 9: ④ 조달 화면

**Files:**
- Modify: `components/kb/JarimaegimPlan.tsx:118-183`(두 목록 섹션), `:186-248`(PlanPrescription 자리)

- [ ] **Step 1: 두 목록 섹션에 선택 기능을 단다**

`ProductRow`(118-128행)를 바꾼다:

```tsx
type Selection = { ids: string[]; onToggle: (id: string) => void } | null;

function SelectBox({ id, selection }: { id: string; selection: Selection }) {
  if (!selection) return null;
  return <label className="kb-select-row">
    <input type="checkbox" checked={selection.ids.includes(id)} onChange={() => selection.onToggle(id)} />
    <span>문서에 담기</span>
  </label>;
}

function ProductRow({ product, reasons, selection }: { product: KbProduct; reasons?: string[]; selection?: Selection }) {
  return <li>
    <div className="kb-product-top">
      <strong>{product.name}</strong>
      <span className="kb-product-rate">{rateLabel(product)}</span>
    </div>
    {reasons && reasons.length > 0 && <div className="kb-match-reasons">{reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>}
    <small>{[product.loan_limit && `한도 ${product.loan_limit}`, product.join_way, product.rate_type].filter(Boolean).join(" · ")}</small>
    <a href={product.official_url} target="_blank" rel="noopener noreferrer">공시 원문 열기 <ExternalLink aria-hidden="true" /></a>
    <SelectBox id={product.id} selection={selection ?? null} />
  </li>;
}
```

`ProgramSection`(135-156행)의 시그니처와 `<li>`를 바꾼다 — 나머지 문구는 그대로 둔다:

```tsx
function ProgramSection({ programs, inputs, selection }: { programs: Program[]; inputs: CaseRecord["inputs"]; selection?: Selection }) {
```

그리고 `<li key={program.id}>` 안의 `<a ...>공식 원문 열기 ...</a>` 바로 아래에 한 줄을 더한다:

```tsx
      <SelectBox id={program.id} selection={selection ?? null} />
```

`KbProductSection`(159-183행)도 같은 방식으로 `selection`을 받아 `ProductRow`에 넘긴다:

```tsx
function KbProductSection({ products, state, inputs, gapKrw, selection }: { products: KbProduct[]; state: LocationState; inputs: CaseRecord["inputs"]; gapKrw: number | null; selection?: Selection }) {
```

```tsx
      <ul>{shown.map((match) => <ProductRow key={match.product.id} product={match.product} reasons={match.reasons} selection={selection} />)}</ul>
```

- [ ] **Step 2: `PlanPrescription`을 지우고 `PlanFunding`을 쓴다**

186-248행의 `PlanPrescription` 전체를 다음으로 교체한다:

```tsx
/** 확정한 후보를 어느 화면에서나 한 줄로 요약한다. 계획의 기준이 무엇인지 잊지 않게 하고,
 *  바꾸는 경로를 그 자리에 둔다. ProfileBadge 와 자리는 같지만 요약하는 값도 돌아가는 곳도 다르다. */
function PlanBadge({ committed, onBack }: { committed: Candidate; onBack: () => void }) {
  const listing = committed.listing;
  return <div className="kb-plan-badge">
    <MapPin aria-hidden="true" />
    <span><strong>{committed.name}</strong><small>{committed.road_address || committed.address}
      {listing && ` · 보증금 ${formatKrw(listing.deposit_krw)} · 월세 ${formatKrw(listing.monthly_rent_krw)}`}</small></span>
    <button className="kb-gate-edit" onClick={onBack}>바꾸기</button>
  </div>;
}

/** 후보를 확정하지 않으면 부족분이 없고, 부족분이 없으면 이 화면의 질문이 성립하지 않는다. */
function NoCommitted({ onBackToLocation }: { onBackToLocation: () => void }) {
  return <div className="kb-step"><div className="kb-empty compact"><MapPin aria-hidden="true" />
    <strong>계획 기준 후보를 확정하지 않았습니다</strong>
    <p>입지 단계에서 후보를 하나 확정하면 그 후보의 임대 조건으로 부족분을 계산합니다.</p>
    <button className="kb-ghost" onClick={onBackToLocation}>입지로 돌아가기</button></div></div>;
}

/** ④ 조달. 질문은 하나다 — 부족분을 무엇으로 메울 것인가.
 *  부족분은 새로 계산하지 않는다. 권장 조달선의 차입액(loan_krw)이 이미 그 값이다. */
export function PlanFunding({ caseData, committed, bands, programs, programState, kbProducts, kbState, applicationEnabled, selected, onToggle, onBackToLocation, onNext }: {
  caseData: CaseRecord; committed: Candidate | null; bands: FundingBandResult | null;
  programs: Program[]; programState: LocationState; kbProducts: KbProduct[]; kbState: LocationState;
  applicationEnabled: boolean; selected: { products: string[]; programs: string[] };
  onToggle: (kind: "products" | "programs", id: string) => void;
  onBackToLocation: () => void; onNext: () => void;
}) {
  if (!committed) return <NoCommitted onBackToLocation={onBackToLocation} />;
  const recommended = bands?.bands.find((line) => line.band === "RECOMMENDED") ?? null;
  const equityLine = bands?.bands.find((line) => line.band === "EQUITY_ONLY") ?? null;
  const gapKrw = recommended ? recommended.loan_krw : null;
  const pending = !bands || bands.status === "integration_pending";
  const partial = bands?.status === "partial";
  const chosen = selected.products.length + selected.programs.length;
  const catalogEmpty = kbState !== "loading" && programState !== "loading" && kbProducts.length === 0 && programs.length === 0;

  return <div className="kb-step">
    <PlanBadge committed={committed} onBack={onBackToLocation} />

    <section className="kb-gap-card">
      <dl>
        <div><dt>필요자금</dt><dd>{bands?.required_capital_krw === null || bands?.required_capital_krw === undefined ? "확인 필요" : formatKrw(bands.required_capital_krw)}</dd></div>
        {/* 자기자본선은 EQUITY_ONLY 밴드가 이미 들고 있는 값이다. 권장선에서 차입액을 빼는
            식을 화면에 만들지 않는다 — 산식은 백엔드에만 있어야 두 곳이 갈라지지 않는다. */}
        <div><dt>자기자본</dt><dd>{equityLine ? formatKrw(equityLine.ceiling_krw) : "확인 필요"}</dd></div>
      </dl>
      {pending
        ? <p className="kb-gap-pending"><Info aria-hidden="true" />{bands?.message || "조달 밴드를 아직 계산하지 못했습니다."}</p>
        : gapKrw === 0
          ? <p className="kb-gap-headline">추가 차입 없이 자기자본으로 가능합니다</p>
          : <p className="kb-gap-headline"><strong>부족분 {formatKrw(gapKrw ?? 0)}</strong>을 무엇으로 메울까요?</p>}
      {partial && <p className="kb-note"><Info aria-hidden="true" />필요자금은 평수·보증금이 있어야 계산합니다. 위 부족분은 권장 조달선 기준 차입액입니다.</p>}
      {pending && <p className="kb-note"><Info aria-hidden="true" />부족분을 계산하지 못해 아래 목록은 조건 대조만 했습니다. 금액 대조는 하지 않았습니다.</p>}
    </section>

    {catalogEmpty
      ? <div className="kb-empty compact"><Coins aria-hidden="true" />
          <strong>고를 수단이 없습니다</strong>
          <p>확인된 KB 공시와 공식 공고가 없어 아무것도 추천하지 않습니다. 문서에는 확정 조건과 계획 기준 후보만 담깁니다.</p></div>
      : <>
          <KbProductSection products={kbProducts} state={kbState} inputs={caseData.inputs} gapKrw={gapKrw}
            selection={{ ids: selected.products, onToggle: (id) => onToggle("products", id) }} />
          {programState === "loading" && <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />공식 공고를 확인하고 있습니다.</div>}
          {programs.length > 0 && <ProgramSection programs={programs} inputs={caseData.inputs}
            selection={{ ids: selected.programs, onToggle: (id) => onToggle("programs", id) }} />}
        </>}

    <p className="kb-note"><Info aria-hidden="true" />지원사업 endpoint 연동 후 조달선에 반영됩니다. 현재 밴드에는 지원금이 포함되지 않았습니다.</p>
    {!applicationEnabled && <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" /><span>실제 신청과 상담 자동 연결은 제공하지 않습니다. 고르는 것은 문서에 담는다는 뜻이며 신청이 아닙니다.</span></div>}

    <button className="kb-primary" onClick={onNext}>
      {chosen > 0 ? `고른 ${chosen}건으로 문서 만들기` : "선택 없이 서류로"} <ArrowRight aria-hidden="true" />
    </button>
  </div>;
}
```

4행의 아이콘 import에 `ArrowRight`를 더한다:

```tsx
import { ArrowRight, CircleHelp, Coins, ExternalLink, FileDown, FileText, Info, Landmark, LoaderCircle, LockKeyhole, MapPin, ShieldCheck, Sparkles } from "lucide-react";
```

- [ ] **Step 3: 타입을 확인한다**

Run: `npm run typecheck`
Expected: `PlanPaperwork`가 없다는 오류만 남는다(Task 10이 만든다).

- [ ] **Step 4: 커밋**

```bash
git add components/kb/JarimaegimPlan.tsx
git commit -m "feat(kb): ask one question in 조달 — what fills the gap"
```

---

## Task 10: ⑤ 서류 화면

**Files:**
- Modify: `components/kb/JarimaegimPlan.tsx` (Task 9가 만든 `PlanFunding` 아래)

- [ ] **Step 1: `PlanPaperwork`를 쓴다**

`PlanFunding` 아래에 넣는다:

```tsx
/** ⑤ 서류. 미리보기 줄은 render_case_pdf 가 실제로 담는 섹션과 1:1 로 대응한다.
 *  대응이 깨지면 그것이 버그다 — 문서에 없는 것을 있다고 적는 화면은 만들지 않는다. */
export function PlanPaperwork({ caseData, committed, bands, products, programs, documents, docBusy, docNotice, confirmed, onConfirm, onPrepareDocument, onBackToFunding }: {
  caseData: CaseRecord; committed: Candidate | null; bands: FundingBandResult | null;
  products: KbProduct[]; programs: Program[];
  documents: Record<string, string>; docBusy: string; docNotice: string;
  confirmed: boolean; onConfirm: (value: boolean) => void;
  onPrepareDocument: (template: string) => void; onBackToFunding: () => void;
}) {
  const recommended = bands?.bands.find((line) => line.band === "RECOMMENDED") ?? null;
  const chosen = products.length + programs.length;
  const rows: { label: string; value: string }[] = [
    { label: "확정 조건", value: `${caseData.inputs.district} · ${caseData.inputs.industry}` },
    // 케이스에 저장된 것만 문서에 담긴다. 로컬 확정과 저장 결과가 다르면 그 사실을 여기서 말한다.
    { label: "계획 기준 후보", value: !committed ? "확정한 후보가 없습니다"
      : caseData.inputs.committed_listing_id === committed.id ? `${committed.name} (시연용 매물)`
      : `${committed.name} — 매물 정보를 케이스에 저장하지 못해 문서에는 담기지 않습니다` },
    { label: "조달 요약", value: recommended
      ? `권장 조달선 ${formatKrw(recommended.ceiling_krw)} · 차입 필요액 ${formatKrw(recommended.loan_krw)} · 월 상환 ${recommended.monthly_repayment_krw > 0 ? formatKrw(recommended.monthly_repayment_krw) : "0원"} · 넘어야 하는 일매출 ${formatKrw(recommended.target_daily_revenue_krw)}`
      : "조달 밴드를 계산하지 못해 이 문서에는 조달 요약이 없습니다" },
    { label: "고른 조달 수단", value: chosen === 0 ? "고른 조달 수단이 없습니다"
      : [...products.map((product) => product.name), ...programs.map((program) => program.title)].join(" · ") },
    { label: "출처·기준일", value: "각 섹션 말미에 출처명과 기준일을 적습니다. 확인되지 않은 값은 '확인 필요'로 남습니다." },
    { label: "비보장 고지", value: "AI가 작성한 초안이며 결과를 보장하지 않습니다" }
  ];

  return <div className="kb-step">
    {committed && <PlanBadge committed={committed} onBack={onBackToFunding} />}
    <p className="kb-step-lead">아래가 문서에 담기는 전부입니다. 화면에 없는 값은 문서에도 없습니다.</p>

    <ul className="kb-doc-preview">{rows.map((row) => <li key={row.label}>
      <strong>{row.label}</strong><span>{row.value}</span>
    </li>)}</ul>

    <label className="kb-consent">
      <input type="checkbox" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} />
      <span>위 내용이 문서에 담기는 것을 확인했습니다</span>
    </label>

    <div className="kb-doc-actions">
      <button className="kb-primary" disabled={!confirmed || Boolean(docBusy)} onClick={() => onPrepareDocument("funding")}>
        {docBusy === "funding" ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : <FileDown aria-hidden="true" />}
        {documents.funding ? "초안 내려받기" : "초안 준비하기"}
      </button>
    </div>
    {docNotice && <p className="kb-inline-notice" role="status">{docNotice}</p>}

    <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" /><span>상담 자동 연결은 제공하지 않습니다. <strong>초안을 내려받아 지점 상담에 가져가시면 됩니다.</strong> 초안은 상담의 입력이며 승인을 보장하지 않습니다.</span></div>
    <p className="kb-note"><ShieldCheck aria-hidden="true" />문서는 비공개 저장소에 보관하며 현재 익명 세션에서만 내려받을 수 있습니다. 세션은 최대 24시간 유지됩니다.</p>
    <p className="kb-note"><FileText aria-hidden="true" />조달 수단을 더 고르거나 빼려면 <button className="kb-linklike" onClick={onBackToFunding}>조달 단계</button>로 돌아가면 됩니다.</p>
  </div>;
}
```

- [ ] **Step 2: 쓰이지 않게 된 것을 지운다**

`PlanPrescription`은 Task 9에서 이미 교체했다. `TOP_N`, `matchKbProducts`, `matchPrograms`는 계속 쓰인다. import 중 실제로 쓰이지 않는 것이 남았는지 확인한다.

Run: `npm run lint`
Expected: PASS — `no-unused-vars` 위반 없음. 있으면 해당 import만 지운다.

- [ ] **Step 3: 타입을 확인한다**

Run: `npm run typecheck`
Expected: PASS — 오류 없음

- [ ] **Step 4: 커밋**

```bash
git add components/kb/JarimaegimPlan.tsx
git commit -m "feat(kb): show exactly what the draft will contain, then ask for consent"
```

---

## Task 11: 스타일

**Files:**
- Modify: `app/globals.css` (`.kb-band-banner` 규칙 근처)

- [ ] **Step 1: 새 클래스를 더한다**

`app/globals.css`의 `.kb-band-banner` 규칙 블록 뒤에 넣는다:

```css
.kb-plan-badge{display:flex;align-items:center;gap:8px;padding:10px 12px;border:1px solid var(--kb-line);border-radius:10px;background:var(--kb-fill);font-size:12px}
.kb-plan-badge svg{width:16px;height:16px;flex:none;color:var(--kb-blue)}
.kb-plan-badge span{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px}
.kb-plan-badge small{color:var(--kb-sub);font-size:11px}
.kb-gap-card{border:1px solid var(--kb-line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:10px}
.kb-gap-card dl{margin:0;display:flex;flex-direction:column;gap:6px}
.kb-gap-card dl div{display:flex;justify-content:space-between;gap:12px;font-size:12px}
.kb-gap-card dt{color:var(--kb-sub)}
.kb-gap-card dd{margin:0;font-weight:600}
.kb-gap-headline{margin:0;padding-top:8px;border-top:1px solid var(--kb-line);font-size:14px;line-height:1.5}
.kb-gap-headline strong{font-size:18px;color:var(--kb-blue)}
.kb-gap-pending{margin:0;padding-top:8px;border-top:1px solid var(--kb-line);display:flex;gap:6px;font-size:12px;color:var(--kb-sub)}
.kb-gap-pending svg{width:14px;height:14px;flex:none}
.kb-select-row{display:flex;align-items:center;gap:6px;margin-top:8px;font-size:12px;font-weight:600;color:var(--kb-ink);cursor:pointer}
.kb-select-row input{width:16px;height:16px;accent-color:var(--kb-blue)}
.kb-doc-preview{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.kb-doc-preview li{display:flex;flex-direction:column;gap:3px;padding:10px 12px;border:1px solid var(--kb-line);border-radius:10px}
.kb-doc-preview strong{font-size:12px;color:var(--kb-sub)}
.kb-doc-preview span{font-size:12px;line-height:1.5}
.kb-consent{display:flex;align-items:flex-start;gap:8px;padding:10px 12px;border:1px solid var(--kb-blue-soft);border-radius:10px;font-size:12px;cursor:pointer}
.kb-consent input{width:16px;height:16px;margin-top:1px;accent-color:var(--kb-blue)}
.kb-linklike{border:0;background:none;padding:0;color:var(--kb-blue);font:inherit;text-decoration:underline;cursor:pointer}
```

- [ ] **Step 2: 눈으로 확인한다**

`npm run dev`를 띄운 뒤 `http://127.0.0.1:4173/kb`에서 자기자본 입력 → 조건 → 후보 확정 → 다음 → 다음으로 걸어가 ④·⑤가 320px 폭에서 가로 스크롤 없이 그려지는지 본다(브라우저 devtools 반응형).

Expected: 두 화면 모두 가로 넘침 없음, 낱말 가운데가 끊기지 않음(`.kb-ai-panel`의 `word-break:keep-all`이 이미 적용된다)

- [ ] **Step 3: 커밋**

```bash
git add app/globals.css
git commit -m "style(kb): style the gap card, the option checkboxes and the draft preview"
```

---

## Task 12: 검증 스크립트 마무리와 전체 확인

**Files:**
- Modify: `scripts/visual-check.mjs:13` 아래 (KB 흐름 스냅샷)

- [ ] **Step 1: `flow-check`를 통과시킨다**

`npm run dev`를 띄운 뒤:

Run: `node scripts/flow-check.mjs; echo "exit=$?"`
Expected: `exit=0`. `prescribe` 객체가 `reachedFunding: true`, `reachedPaperwork: true`, `noNumberedBlocks: true`를 담고, 무키 환경이면 `emptyCatalogExplained: true`.

실패하면 출력된 JSON의 어느 키가 false인지 보고 해당 태스크로 돌아간다.

- [ ] **Step 2: `visual-check`에 두 화면을 더한다**

`scripts/visual-check.mjs`의 뷰포트 루프 안, `publicRoutes` 루프가 끝난 직후(`await context.request.post(base + "/api/v1/sessions/anonymous"...)` 바로 앞)에 넣는다:

```js
  // KB 흐름의 ④ 조달 · ⑤ 서류. 시연용 매물이 없으면 도달할 수 없으므로 건너뛴 사실을 남긴다 —
  // 조용히 지나가면 "찍었다"로 읽힌다.
  const kbSteps = { viewport: viewport.name, funding: false, paperwork: false, skipped: null };
  try {
    await page.goto(base + "/kb", { waitUntil: "networkidle" });
    await page.locator(".kb-profile-form input").nth(0).fill("100000000");
    await page.getByRole("button", { name: /확정하고 조건 입력으로/ }).click();
    await page.locator(".kb-field-block textarea").fill("강남구에서 카페를 준비 중이에요");
    await page.getByRole("button", { name: /조건으로 정리하기/ }).click();
    await page.locator(".kb-askbox input").first().fill("2500000");
    await page.getByRole("button", { name: "이 조건으로 입지 찾기" }).click();
    await page.waitForSelector(".kb-candidates li, .kb-empty", { timeout: 30000 });
    if (await page.locator(".kb-candidates li").count() === 0) {
      kbSteps.skipped = "시연용 매물 없음";
    } else {
      await page.getByRole("button", { name: "계획 기준으로 확정" }).first().click();
      await page.getByRole("button", { name: /다음/ }).click();
      await page.waitForSelector(".kb-gap-card");
      await page.screenshot({ path: outputPath(`${viewport.name}-kb-funding.png`), fullPage: true });
      kbSteps.funding = true;
      await page.getByRole("button", { name: /문서 만들기|서류로/ }).click();
      await page.waitForSelector(".kb-doc-preview");
      await page.screenshot({ path: outputPath(`${viewport.name}-kb-paperwork.png`), fullPage: true });
      kbSteps.paperwork = true;
    }
  } catch (error) {
    kbSteps.skipped = error.message;
  }
  results.push(kbSteps);
```

- [ ] **Step 3: 스냅샷을 만든다**

Run: `node scripts/visual-check.mjs; echo "exit=$?"`
Expected: `exit=0`, `artifacts/visual/`에 `*-kb-funding.png` · `*-kb-paperwork.png`가 뷰포트마다 생긴다. 매물이 없어 건너뛴 뷰포트가 있으면 출력 JSON의 `skipped`에 사유가 남는다.

- [ ] **Step 4: 전체 검증**

```bash
npm run typecheck && npm run lint && npm run api:check && npm run api:test
```
Expected: 넷 다 통과. pytest는 기존 191건 + 새 27건.

- [ ] **Step 5: 커밋**

```bash
git add scripts/visual-check.mjs
git commit -m "test(visual): snapshot the 조달 and 서류 steps, and record when they are skipped"
```

---

## 완료 조건

- [ ] `npm run typecheck` · `npm run lint` · `npm run api:check` · `npm run api:test` 전부 통과
- [ ] `node scripts/flow-check.mjs`가 `exit=0`이고 `prescribe.reachedPaperwork === true`
- [ ] 스테퍼에 `조달`·`서류`가 있고 `처방`이 없다
- [ ] 후보 미확정 상태에서 `다음`이 잠기고 사유가 화면에 있다
- [ ] 동의 체크 전에는 초안 준비 버튼이 잠긴다
- [ ] 무키 환경에서 ④가 "고를 수단이 없습니다"를 말하고 ⑤까지 갈 수 있다
- [ ] 내려받은 PDF에 조달 요약과 고른 수단(또는 없다는 사실)이 들어 있다
