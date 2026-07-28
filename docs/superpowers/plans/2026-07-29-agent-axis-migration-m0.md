# 에이전트 축 마이그레이션 · M0 조건 확인 단계 제거 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 조건 카드를 눌러 확정하는 단계를 없애고, 업종·자치구·자기자본만 있으면 확인 클릭 없이 여력 산출과 입지 판단까지 자동으로 진행하되, 무엇을 어떤 발화 조각에서 읽었는지는 실행 중에도 계속 보이게 한다.

**Architecture:** 확인 게이트를 없애는 대가로 두 가지를 코드로 고정한다. (1) 추출 검증은 그대로 남는다 — 모델은 여전히 원문 조각만 가리키고 금액·평수는 코드가 다시 읽는다. (2) 조건 스트립이 실행 중·실행 후에도 화면에 남아 값·근거 인용·출처를 계속 보여주고, 인라인 수정이 재실행을 유발한다. 백엔드에서는 `REQUIRED_*` 를 차단 항목(업종·자치구·자기자본)과 유보 항목(월세·평수·보증금·운영형태)으로 가르고, 희망 월세가 없을 때 `finance.band` 가 실행을 멈추는 대신 여력 커널 결과만 싣고 `deferred` 로 무엇을 못 냈는지 밝힌다.

**Tech Stack:** FastAPI + pydantic v2, pytest, Next.js App Router + React 19 클라이언트 컴포넌트, 순수 CSS(`app/globals.css`), playwright-core 기반 `scripts/*.mjs`

**상위 명세:** 사용자 제시 "자리매김 에이전트 구조 마이그레이션" M0. M1~M5 는 이 문서의 범위 밖이며 각각 별도 plan 문서로 전개한다.

**전제:** 모든 명령은 `ter-doctor-demo/` 에서 실행한다. 백엔드 venv 가 `backend/.venv` 에 있어야 한다(python3.12). pytest 는 `backend/` 에서 돈다.

**작업 브랜치:** `worktree-agent-axis-migration` (`.claude/worktrees/agent-axis-migration`, `main` 기반)

**시작 시점 기준선:** `pytest -m "not slow"` 646 passed / 1 deselected, `npm run typecheck` 통과, `npm run lint` 경고 1건(`components/Workspace.tsx` 의 `<img>` — 이 작업의 범위 밖이므로 그대로 둔다)

---

## 조사 결과 — 상위 명세에서 고친 것

이 계획을 쓰기 전에 `backend/app/agents/` 전체, `main.py` 의 에이전트 배선, 조건 추출 두 경로, 프론트 확인 흐름을 읽었다. 상위 명세의 M0 서술과 실제 코드가 어긋나는 지점이 넷 있고, 아래 과업들이 그것을 반영한다.

### 1. 추출 경로가 하나가 아니라 둘이다

상위 명세의 M0 완료 정의는 "`ConditionLayer.interpret()` 경로와 실행 경로가 같은 추출 결과를 낸다"이지만, **`ConditionLayer.interpret()` 은 어떤 엔드포인트도 부르지 않는다.** `POST /api/v1/conditions/interpret` 은 `main.py:519` 에서 `ai.interpret_conditions` → `condition_parse.parse_conditions` → `condition_interpret.sanitize` 로 간다.

| | `agents/conditions.py` (실행 경로) | `condition_parse.py` + `condition_interpret.py` (화면 경로) |
|---|---|---|
| 검증 | `Span` 원문 그대로 포함 | `evidence in text` 부분문자열 |
| 항목 | industry, district, area_pyeong, operating_style, deposit, rent | industry, district, rent, business_stage, startup_type, priority |
| 금액 | `conditions.amount_krw` | `condition_parse.amount_from` |

두 금액 파서는 **서로 다른 답을 낸다.**

- `amount_from("300")` → `3_000_000` (단위 없는 1만 미만은 만원 관행, `condition_parse.py:77`)
- `amount_krw("300")` → `300` (단위 없으면 곱수 1, `conditions.py:90`)
- `amount_from("1억 5천만원")` → `100_000_000` (`AMOUNT.search` 가 첫 성분만 읽는다)
- `amount_krw("1억 5천만원")` → `150_000_000` (성분을 전부 더한다)

각자 상대가 고친 버그를 갖고 있다. 지금은 화면 경로가 먼저 `monthly_rent_krw` 를 채우고 `_extracted()` 가 빈칸만 채우기 때문에 실행 경로의 오독이 가려져 있다 — **확인 게이트를 없앤다는 것이 바로 그 가림막을 없앤다는 뜻이다.** 그래서 Task 1 이 파서 단일화이고, 이것은 검증 항목이 아니라 산출물이다.

### 2. M0 는 "여력 커널 분리"를 M4 에서 앞당겨 와야 성립한다

상위 명세는 희망 월세가 없으면 "손익분기만 못 냄. 입지 축은 전부 가능 → 되묻지 않고 진행"이라고 적었다. 그러나 현재 `finance.band` 는 `monthly_rent_krw` 기본값 0(`finance.py:61`)으로 `compute_bands` 를 그대로 부르고, 월세 0 은 손익분기와 목표매출을 **말없이 과소 산출한다.** 반대로 여기서 유보(`WITHHELD`)를 반환하면 `FinanceReport.halted`(`finance.py:48`)가 참이 되어 실행 전체가 금융 단계에서 멈춘다 — M0 가 사려는 자동 진행을 M0 가 되판다.

빠져나갈 길은 하나다. `compute_capacity`(`funding.py:65`)는 이미 업종·월세 없이 자기자본선·차입 여력·최대 조달선을 낸다. `finance.band` 가 월세가 없을 때 이 여력 결과만 싣고 `OK` 로 끝내면 실행은 계속되고 못 낸 수치만 유보된다. 이것이 M4 의 "`funding.compute_capacity` 를 여력 커널로 앞으로 뺀다"를 축소한 형태다.

**따라서 M0 가 여력 커널 분리를 흡수하고, M4 는 축 재편만 남는다.** `FinanceReport.halted` 의 정의는 손대지 않는다(유보가 아니라 `OK` 를 반환하므로) — 그 오버라이드 제거는 M3 의 몫으로 남는다.

### 3. 되묻기 3항목 중 둘은 이미 되물을 수 없다

- **자치구**는 절대 비지 않는다. `DEFAULT_CASE.district = "마포구"`(`lib/constants.ts:11`)이고 편집 컨트롤이 `<select>` 다.
- **자기자본**은 조건 단계 이전, 프로필 단계(`ProfileStep`, `JarimaegimPanel.tsx:84`)에서 이미 확정을 강제한다.

그러므로 화면 A 에서 실제로 되묻게 되는 것은 **업종 하나**다. 백엔드의 차단 집합에는 셋 다 선언하되(케이스 API 로 직접 들어오는 경로가 있으므로), 화면 쪽 기대치는 "업종만 묻는다"로 적는다.

### 4. 유보 이상치 두 개는 소프트 경고로 강등한다

사용자 결정 사항이다. `DEPOSIT_EXCEEDS_EQUITY` 는 정상 상황이다(보증금을 조달하려고 대출을 받는다). 상위 명세 M2 처럼 `WITHHOLDABLE ∩ observed` 로 결정론적 유보를 만들면 흔한 입력에서 실행이 멈춘다. 두 술어 모두 조건 카드의 확인 요청 표시로 내리고, 밴드는 계속 산출한다. **M0 에서는 배선만 준비하고(경고를 실어 보내는 자리), 실제 강등은 M2 에서 한다** — M0 는 LLM 경로를 건드리지 않는다.

---

## 파일 구조

### 신규

| 파일 | 책임 |
|---|---|
| `components/kb/ConditionStrip.tsx` | 조건 값 + 근거 인용 + 출처 + 인라인 수정. 확인 화면이 아니라 **모든 단계에 상주하는** 스트립 |
| `backend/tests/test_amount_parsing.py` | 단일화된 금액 파서의 계약 |
| `backend/tests/test_condition_blocking.py` | 차단/유보 항목 분리와 되묻기 규칙 |
| `backend/tests/test_agent_finance_deferred.py` | 희망 월세 없이 여력만 내고 실행이 계속되는 경로 |

### 수정

| 파일 | 변경 |
|---|---|
| `backend/app/condition_parse.py` | `amount_from` 를 성분 합산 + 만원 관행 + 상한으로 단일화. 인접 성분만 더한다 |
| `backend/app/agents/conditions.py` | `amount_krw`·`_AMOUNT`·`_AMOUNT_UNITS` 삭제 후 `amount_from` 사용. `REQUIRED_*` → `BLOCKING`/`DEFERRABLE`. `halted` 재정의. 충돌 제안(`proposals`) 추가. 업종 정규화 실패 복구 경로 |
| `backend/app/agents/finance.py` | `_band` 가 월세 유보 시 여력 커널 결과로 `OK` 반환. `_BAND_FIELDS` 주석 갱신 |
| `backend/app/agents/orchestrator.py` | `_summary` 가 RECOMMENDED 부재를 견디고 여력만 있는 요약을 낸다. `questions` 외에 `proposals` 를 결과에 싣는다 |
| `backend/app/models.py` | `ConditionInterpretResult` 에 필드 유지, prescribe done 프레임에 `proposals` 추가 |
| `lib/types.ts` | `models.py` 미러링 (불변조건 5) |
| `lib/use-jarimaegim.ts` | `interpret()` 가 차단 항목이 차 있으면 `start()` 로 자동 진행. `edited` 수정이 재실행을 유발. `missingBandInputs` 는 유지하되 흐름을 막지 않음 |
| `components/kb/JarimaegimPanel.tsx` | `ConfirmStep` 해체 → `ConditionStrip` + 차단 항목 되묻기만. `ASK_FIELDS` 에서 월세 제거 |
| `app/globals.css` | `.kb-condstrip` 계열 |
| `scripts/flow-check.mjs` | 확인 클릭 제거, 자동 진행 단언, 근거 인용 상주 단언 |
| `backend/tests/test_agent_conditions_llm.py` | 파서 단일화·차단 규칙 반영 |
| `backend/tests/test_agent_timing_conditions.py` | `:58,71,84` 세 건이 옛 halt 의미를 고정하고 있다 |
| `backend/tests/test_condition_parse.py` | 합산 규칙 추가 단언 |
| `CLAUDE.md` | 테스트 개수, 조건 흐름 서술 |

### 삭제

없음. `condition_parse.py` / `condition_interpret.py` 는 남는다 — 화면 경로의 필드 집합(`business_stage`·`startup_type`·`priority`)이 실행 경로에 없기 때문이다. 두 경로의 **금액 산술만** 하나로 모은다.

---

## Task 1: 금액 파서 단일화

두 파서가 같은 문자열에 다른 답을 내는 상태를 먼저 없앤다. 이걸 안 고치고 확인 게이트를 없애면 "월세 300"이 실행 경로에서 300원이 된다.

**Files:**
- Create: `backend/tests/test_amount_parsing.py`
- Modify: `backend/app/condition_parse.py:34-83`, `backend/app/agents/conditions.py:57-93`
- Modify: `backend/tests/test_agent_conditions_llm.py:46-56`

- [ ] **Step 1: 계약을 테스트로 먼저 쓴다**

`backend/tests/test_amount_parsing.py`:

```python
"""금액 파서의 단일 계약.

두 경로(`agents/conditions.py` 의 Span 추출, `condition_parse.py` 의 규칙 추출)가 같은
문자열에 같은 답을 내야 한다. 예전에는 "월세 300" 이 한쪽에서 3,000,000원, 다른 쪽에서
300원이었고, 확인 화면이 먼저 값을 채워 넣는 덕에 그 차이가 가려져 있었다.
"""
import pytest

from app.condition_parse import amount_from
from app.agents.conditions import resolve_mention


@pytest.mark.parametrize("text,expected", [
    ("1억", 100_000_000),
    ("3천만원", 30_000_000),
    ("250만원", 2_500_000),
    ("2,500,000원", 2_500_000),
    ("보증금 5천만", 50_000_000),
    ("3000000", 3_000_000),
])
def test_a_single_component_is_read_the_same_either_way(text, expected):
    assert amount_from(text) == expected


def test_adjacent_components_are_summed():
    """"1억 5천만원" 은 두 성분이다. 첫 성분만 읽으면 5천만원이 조용히 사라진다."""
    assert amount_from("1억 5천만원") == 150_000_000
    assert amount_from("1억 5000") == 150_000_000


def test_components_separated_by_words_are_not_summed():
    """관리비까지 월세에 더하면 사용자가 말하지 않은 금액이 조건에 들어간다.
    공백 말고 다른 것이 사이에 있으면 거기서 멈춘다."""
    assert amount_from("300, 관리비 20") == 3_000_000
    assert amount_from("월세 300 정도이고 보증금은 5000") == 3_000_000


def test_a_bare_number_under_ten_thousand_uses_the_manwon_convention():
    """"월세 300" 이라고 쓴 사람은 300원을 뜻한 것이 아니다."""
    assert amount_from("300") == 3_000_000
    assert amount_from("1,200") == 12_000_000


def test_a_bare_number_at_or_above_ten_thousand_is_literal():
    """"3,000,000" 을 쓴 사람은 정확히 그 금액을 뜻한 것이지 300억을 뜻한 게 아니다."""
    assert amount_from("3,000,000원") == 3_000_000


def test_no_amount_yields_none_rather_than_zero():
    """0 을 돌려주면 "월세 0원" 이라는 조건이 조용히 만들어진다."""
    assert amount_from("적당한 가격이면 좋겠어요") is None
    assert amount_from("근거 없음") is None


def test_an_absurd_amount_is_refused_rather_than_capped():
    assert amount_from("9999억원") is None


def test_the_span_path_uses_the_same_function():
    """`resolve_mention` 이 자체 산술을 갖지 않아야 두 경로가 갈라지지 않는다."""
    assert resolve_mention("monthly_rent_krw", "월세 300") == 3_000_000
    assert resolve_mention("deposit_krw", "보증금 1억 5천만원") == 150_000_000
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_amount_parsing.py -q`

Expected: FAIL — `test_adjacent_components_are_summed` 는 `100000000 != 150000000`, `test_the_span_path_uses_the_same_function` 은 `300 != 3000000`.

- [ ] **Step 3: `amount_from` 을 단일 계약으로 다시 쓴다**

`backend/app/condition_parse.py` 의 `amount_from` 을 통째로 교체한다(시그니처와 이름은 그대로 — `condition_interpret._keep` 이 이 이름을 부른다):

```python
def amount_from(text: str) -> int | None:
    """'300만원'·'1억 5천만원'·'300'·'3,000,000원'을 원 단위 정수로. 두 경로의 유일한 산술이다.

    성분마다 세 갈래 규칙을 따른다:
    (1) 억/천만/백만/만 단위어가 있으면 그 단위를 곱한다.
    (2) 단위어가 없고 숫자가 1만 미만이면 만원 관행을 적용한다 — "월세 300" 은 300만원이다.
    (3) 단위어가 없고 숫자가 1만 이상이면 그대로 원 단위로 읽는다 — "3,000,000" 을 쓴 사람은
        정확히 그 금액을 뜻한 것이지, 300억을 뜻한 게 아니다.
    쉼표는 천단위 구분자로만 벗겨내고 자릿수 판단에는 관여하지 않는다.

    **인접한 성분만 더한다.** "1억 5천만원" 은 한 금액의 두 성분이므로 더해야 하지만,
    "월세 300, 관리비 20" 의 20 은 다른 항목이다. 성분 사이에 공백 아닌 것이 끼면 거기서
    멈춘다 — 더 관대하게 두면 사용자가 말하지 않은 금액이 조건에 들어간다.

    AI 경로도 이 함수를 쓴다 — 모델은 근거 구간만 지목하고 산술은 코드가 한다
    (부록 A 불변조건 4). `agents/conditions.resolve_mention` 도 같은 이유로 이것을 부른다.
    """
    total, found, cursor = 0, False, None
    for match in AMOUNT.finditer(text or ""):
        if cursor is not None and text[cursor:match.start()].strip():
            # 앞 성분과 공백만으로 이어지지 않았다. 여기서부터는 다른 항목이다.
            break
        try:
            raw = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if raw <= 0:
            continue
        unit = match.group(2)
        if unit:
            value = round(raw * UNITS[unit])
        elif raw < 10_000:
            value = round(raw * 10_000)
        else:
            value = round(raw)
        total += value
        found = True
        cursor = match.end()
    if not found or total <= 0 or total > MAX_KRW:
        return None
    return total
```

- [ ] **Step 4: 실행 경로의 자체 산술을 지운다**

`backend/app/agents/conditions.py` 에서 `_AMOUNT_UNITS`(57행), `_AMOUNT`(58-60행), `amount_krw` 함수(74-93행)를 삭제하고, 상단 import 에 다음을 더한다:

```python
from ..condition_parse import amount_from
```

`resolve_mention` 의 금액 분기를 바꾼다:

```python
    if field_name in ("deposit_krw", "monthly_rent_krw"):
        return amount_from(text)
```

파일 상단 docstring 의 "`amount_krw` · `resolve_mention`" 을 "`amount_from` · `resolve_mention`" 으로 고친다. **주석의 설계 근거는 지우지 않는다** — 삭제하는 `amount_krw` 의 docstring 이 담고 있던 "0 을 돌려주면 '월세 0원'이 조용히 만들어진다"와 "천단위 쉼표는 반복될 수 있으므로 `*` 다"의 판단은 위 Step 3 의 새 docstring 과 `NUMBER` 정규식 주석이 이미 담고 있다.

- [ ] **Step 5: 기존 테스트를 새 계약에 맞춘다**

`backend/tests/test_agent_conditions_llm.py:46-56` 의 `amount_krw` 참조를 지운다. 이 파일 상단 import 에서 `amount_krw` 를 빼고, 두 테스트(`test_amounts_are_read_from_the_text_by_code`, `test_text_without_an_amount_yields_nothing_rather_than_zero`)를 삭제한다 — `test_amount_parsing.py` 가 같은 계약을 더 넓게 고정하므로 중복이다.

- [ ] **Step 6: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_amount_parsing.py tests/test_condition_parse.py tests/test_condition_interpret.py tests/test_agent_conditions_llm.py -q`

Expected: PASS, 실패 0건.

- [ ] **Step 7: 전체 회귀**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q 2>&1 | tail -3`

Expected: `... passed` 만, failed 0건.

- [ ] **Step 8: 커밋**

```bash
git add backend/app/condition_parse.py backend/app/agents/conditions.py \
        backend/tests/test_amount_parsing.py backend/tests/test_agent_conditions_llm.py
git commit -m "fix(conditions): give both extraction paths one amount parser

두 경로가 '월세 300'을 3,000,000원과 300원으로 다르게 읽고 있었다. 확인 화면이 먼저 값을
채우는 덕에 가려져 있었을 뿐이고, 확인 단계를 없애면 그 가림막이 사라진다."
```

---

## Task 2: 차단 항목과 유보 항목을 가른다

**Files:**
- Create: `backend/tests/test_condition_blocking.py`
- Modify: `backend/app/agents/conditions.py:38-46,113-124,155-182`

- [ ] **Step 1: 새 계약을 테스트로 쓴다**

`backend/tests/test_condition_blocking.py`:

```python
"""차단 항목과 유보 항목의 경계.

되묻는 기준은 "답이 후보를 바꾸는가" 가 아니라 **"없으면 계산 자체가 불가능한가"** 다.
업종이 없으면 `compute_bands` 가 업종 파라미터를 못 찾고, 자기자본이 없으면 `compute_capacity`
가 여력을 못 내고, 자치구가 없으면 탐색 공간을 못 자른다. 희망 월세는 손익분기만 못 내므로
입지 축은 전부 그대로 돈다 — 그래서 되묻지 않고 그 수치만 유보한다.
"""
from app.agents.conditions import BLOCKING, DEFERRABLE, ConditionLayer

FULL = {"industry": "카페", "district": "마포구", "equity_krw": 50_000_000,
        "monthly_rent_krw": 2_500_000}


def layer():
    return ConditionLayer()


def test_the_blocking_set_is_exactly_the_three_that_stop_a_calculation():
    assert [key for key, _ in BLOCKING] == ["industry", "district", "equity_krw"]


def test_the_rent_is_deferrable_not_blocking():
    assert "monthly_rent_krw" in [key for key, _ in DEFERRABLE]
    assert "monthly_rent_krw" not in [key for key, _ in BLOCKING]


def test_complete_conditions_settle_and_do_not_halt():
    report = layer().run(FULL)
    assert report.settled is True
    assert report.halted is False
    assert report.questions == []


def test_a_missing_rent_does_not_halt_the_run():
    """M0 의 핵심 — 손익분기만 못 내는 항목이 입지 판단을 인질로 잡지 않는다."""
    report = layer().run({**FULL, "monthly_rent_krw": None})
    assert report.halted is False
    assert report.questions == []
    assert "monthly_rent_krw" in report.deferred


def test_a_missing_area_or_deposit_does_not_halt_the_run():
    report = layer().run({**FULL, "area_pyeong": None, "deposit_krw": None})
    assert report.halted is False
    assert report.questions == []


def test_a_missing_industry_halts_and_asks_for_exactly_that():
    report = layer().run({**FULL, "industry": None})
    assert report.halted is True
    assert [item["field"] for item in report.questions] == ["industry"]


def test_a_missing_equity_halts_and_asks_for_exactly_that():
    report = layer().run({**FULL, "equity_krw": None})
    assert report.halted is True
    assert [item["field"] for item in report.questions] == ["equity_krw"]


def test_a_deferred_gap_never_becomes_a_question_even_alongside_a_blocking_one():
    """되묻기는 차단 항목만이다. 유보 항목을 같이 물으면 질문 수가 다시 늘어난다."""
    report = layer().run({"district": "마포구", "equity_krw": 50_000_000})
    assert [item["field"] for item in report.questions] == ["industry"]


def test_questions_are_still_capped_at_three():
    report = layer().run({})
    assert len(report.questions) <= 3


def test_a_zero_equity_counts_as_missing_rather_than_as_an_answer():
    """0 원을 확정된 자기자본으로 읽으면 여력 커널이 0 을 진짜 답으로 낸다."""
    report = layer().run({**FULL, "equity_krw": 0})
    assert report.halted is True
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_condition_blocking.py -q`

Expected: FAIL — `ImportError: cannot import name 'BLOCKING'`.

- [ ] **Step 3: 상수와 판정을 바꾼다**

`backend/app/agents/conditions.py:38-46` 을 교체한다:

```python
#: 없으면 계산 자체가 불가능한 항목. 이것만 되묻는다.
#:
#: 되묻기 기준을 "답이 후보를 바꾸는가" 에서 "없으면 무엇을 못 내는가" 로 옮긴 것이 M0 다.
#: 업종이 없으면 `compute_bands` 가 업종 파라미터를 못 찾고, 자기자본이 없으면
#: `compute_capacity` 가 여력을 못 내며, 자치구가 없으면 탐색 공간을 못 자른다.
BLOCKING = (("industry", "업종"), ("district", "자치구"), ("equity_krw", "자기자본"))

#: 없으면 그 수치만 못 내는 항목. 되묻지 않고 진행하며 무엇을 못 냈는지만 밝힌다.
#:
#: 희망 월세는 손익분기와 권장 조달선만 막는다 — 입지 네 축은 월세를 읽지 않으므로 그대로 돈다.
#: 평수·보증금은 필요자금(→현금소진)에만 관여한다. 예전에는 월세가 `REQUIRED_FINANCE` 에 있어
#: "이 자리에 손님이 있나" 까지 월세 입력을 기다렸다.
DEFERRABLE = (("monthly_rent_krw", "희망 월세"), ("deposit_krw", "희망 보증금"),
              ("area_pyeong", "희망 평수"), ("operating_style", "운영형태"))

QUESTION_LIMIT = 3
```

`REQUIRED_LOCATION` / `REQUIRED_FINANCE` / `OPTIONAL_LOCATION` 세 이름은 지운다. 참조하는 곳은 이 파일 안이 전부다(`_extract` 202행, `_ask` 232행, `run` 156-175행).

`_blank` 를 금액 0 까지 비어 있는 것으로 본다:

```python
def _blank(value: Any) -> bool:
    """0 원을 확정된 답으로 읽지 않는다 — 자기자본 0 을 진짜 답으로 받으면 여력 커널이
    0 을 산출하고, 사용자는 자기가 입력하지 않은 결론을 받게 된다."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value <= 0
    return False
```

- [ ] **Step 4: `ConditionReport` 를 바꾼다**

`backend/app/agents/conditions.py:113-124`:

```python
@dataclass(frozen=True)
class ConditionReport(TeamReport):
    questions: list[dict[str, str]] = field(default_factory=list)
    settled: bool = False
    #: 발화에서 읽어 채운 값까지 반영된 조건. 후속 팀은 이것을 받는다.
    conditions: dict[str, Any] = field(default_factory=dict)
    #: 없어서 그 수치만 못 내는 항목. 실행은 계속되고 화면이 무엇이 빠졌는지 말한다.
    deferred: list[str] = field(default_factory=list)
    #: 발화가 이미 확정된 값과 충돌한 것. 조용히 덮어쓰지 않고 제안으로만 올린다.
    proposals: list[dict[str, Any]] = field(default_factory=list)

    @property
    def halted(self) -> bool:
        """기본 규칙(`활성 0건`)을 쓰지 않는다. 차단 항목이 하나라도 비면 계산이 성립하지
        않으므로 멈추고, 유보 항목은 아무리 비어도 멈추지 않는다."""
        return not self.settled
```

- [ ] **Step 5: `run()` 을 새 상수로 다시 배선한다**

`backend/app/agents/conditions.py:147-182` 의 `run` 본문에서 갭 계산과 결과 조립을 바꾼다:

```python
        blocking_gaps = _missing(merged, BLOCKING)
        deferred_gaps = _missing(merged, DEFERRABLE)

        location = spec("condition.location")
        finance = spec("condition.finance")
        outcomes = [
            location.outcome(
                AgentStatus.WITHHELD if blocking_gaps else AgentStatus.OK,
                message="입지 최소 조건이 아직 확정되지 않았습니다." if blocking_gaps else None,
                data={"settled": {key: merged.get(key) for key, _ in BLOCKING},
                      "deferred": {key: merged.get(key) for key, _ in DEFERRABLE},
                      "extracted": extracted, "decision": extraction.as_data(),
                      "proposals": proposals,
                      "missing": [key for key, _ in blocking_gaps]}),
            finance.outcome(
                AgentStatus.WITHHELD if blocking_gaps else AgentStatus.OK,
                message="금융 프로필이 아직 확정되지 않았습니다." if blocking_gaps else None,
                data={"source": "MYDATA" if self.mydata_enabled else "MANUAL",
                      "mydata_enabled": self.mydata_enabled, "decision": asked.as_data(),
                      "settled": {"equity_krw": merged.get("equity_krw")},
                      "missing": [key for key, _ in blocking_gaps if key == "equity_krw"]}),
        ]

        questions = self._questions(blocking_gaps, asked)
        settled = not blocking_gaps
        return ConditionReport(
            team=self.team, name=self.name, outcomes=outcomes, blocking=True,
            questions=questions, settled=settled, conditions=merged,
            deferred=[key for key, _ in deferred_gaps], proposals=proposals,
            message=None if settled else "확정되지 않은 조건이 있어 후보를 생성하지 않았습니다.")
```

`proposals` 는 Task 4 에서 채운다. 이 단계에서는 `run()` 서두에 `proposals: list[dict[str, Any]] = []` 를 두어 빈 목록으로 흐르게 한다.

`_extract`(202행)와 `_ask`(232행)의 `REQUIRED_LOCATION + REQUIRED_FINANCE + OPTIONAL_LOCATION` 참조를 `BLOCKING + DEFERRABLE` 로, `_missing(merged, REQUIRED_LOCATION + REQUIRED_FINANCE)` 를 `_missing(merged, BLOCKING)` 으로 바꾼다.

- [ ] **Step 6: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_condition_blocking.py -q`

Expected: PASS.

- [ ] **Step 7: 옛 halt 의미를 고정하던 테스트를 새 계약으로 옮긴다**

`backend/tests/test_agent_timing_conditions.py` 의 세 테스트를 고친다.

`test_a_missing_minimum_condition_produces_a_question_not_a_guess`(58행) — `monthly_rent_krw` 를 비우던 것을 `industry` 로 바꾼다. `test_the_layer_blocks_candidate_generation_until_settled`(71행) — 같은 이유로 차단 항목을 비운다. `test_optional_fields_do_not_hold_the_run`(84행) — 이제 월세도 여기 속하므로 케이스에 더한다:

```python
def test_optional_fields_do_not_hold_the_run():
    """평수·운영형태·보증금에 더해 희망 월세까지 — 없어도 후보는 나온다.
    없으면 손익분기만 못 내고, 그 사실은 `deferred` 로 밝힌다."""
    report = ConditionLayer().run({"industry": "카페", "district": "마포구",
                                   "equity_krw": 50_000_000})
    assert report.settled is True
    assert report.halted is False
    assert set(report.deferred) >= {"monthly_rent_krw", "area_pyeong", "deposit_krw"}
```

- [ ] **Step 8: 전체 회귀**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q 2>&1 | tail -3`

Expected: failed 0건. `test_agent_orchestrator.py::test_unsettled_conditions_stop_before_the_finance_team_runs` 가 여전히 통과해야 한다 — 차단 항목을 비운 케이스이므로 그대로 멈춘다.

- [ ] **Step 9: 커밋**

```bash
git add backend/app/agents/conditions.py backend/tests/test_condition_blocking.py \
        backend/tests/test_agent_timing_conditions.py
git commit -m "feat(conditions): ask only for what stops a calculation

되묻기 기준을 '답이 후보를 바꾸는가'에서 '없으면 무엇을 못 내는가'로 옮긴다. 희망 월세는
손익분기만 막고 입지 네 축은 그대로 돌므로, 되묻지 않고 그 수치만 유보한다."
```

---

## Task 3: 희망 월세 없이도 여력을 내고 실행을 잇는다

Task 2 가 월세를 유보 항목으로 옮겼으므로, 이제 `finance.band` 가 월세 없이 무엇을 낼지 정해야 한다. 지금은 기본값 0 으로 `compute_bands` 를 불러 손익분기를 말없이 과소 산출한다.

**Files:**
- Create: `backend/tests/test_agent_finance_deferred.py`
- Modify: `backend/app/agents/finance.py:55-72,186-231`
- Modify: `backend/app/agents/orchestrator.py:268-282`

- [ ] **Step 1: 계약을 테스트로 쓴다**

`backend/tests/test_agent_finance_deferred.py`:

```python
"""희망 월세가 없을 때 금융 축이 무엇을 내는가.

여력(자기자본선·차입 여력·최대 조달선)은 금융 프로필만으로 나온다 — `compute_capacity` 가
업종도 월세도 읽지 않기 때문이다. 권장 조달선과 손익분기만 월세를 요구한다. 그래서 월세가
없으면 밴드를 통째로 유보하는 대신 여력만 싣고 무엇을 못 냈는지 밝힌다.

유보(`WITHHELD`)로 반환하면 `FinanceReport.halted` 가 참이 되어 실행 전체가 멈추고, 그러면
"이 자리에 손님이 있나" 까지 월세 입력을 기다리게 된다. 그것이 M0 가 없애려는 상태다.
"""
from app.agents.contracts import AgentStatus
from app.agents.finance import FinanceTeam
from app.policy_params import PolicyParams

# `test_agent_finance.py` 와 같은 인라인 파라미터를 쓴다 — 저장소의 실제 파일을 읽으면
# 시연용 가정값이 바뀔 때마다 이 테스트가 같이 흔들린다.
FULL = PolicyParams({
    "updated_at": "2026-07-27",
    "entries": {
        "loan.annual_rate_percent": {"value": 4.45, "source": "소진공"},
        "loan.term_months": {"value": 60, "source": "소진공"},
        "loan.guarantee_ceiling_krw": {"value": 70_000_000, "source": "테스트"},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000, "source": "테스트"},
        "stress.revenue_drop_ratio": {"value": 0.2, "source": "설계"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "source": "설계"},
        "working_capital.months": {"value": 3, "source": "설계"},
    },
    "industries": {"카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20,
                           "fitout_krw_per_pyeong": 2_500_000, "operating_days_per_month": 26,
                           "source": "테스트"}},
})

EMPTY = PolicyParams({"updated_at": "2026-07-27", "entries": {}, "industries": {}})

BASE = {"industry": "카페", "district": "마포구", "equity_krw": 50_000_000,
        "existing_debt_krw": 0, "other_monthly_fixed_krw": 0,
        "monthly_maintenance_krw": 0, "key_money_krw": 0,
        "area_pyeong": None, "deposit_krw": None, "fitout_krw": None}


def team(params=FULL):
    return FinanceTeam(params, kb_products=[], programs=[])


def band_of(report):
    return next(item for item in report.outcomes if item.key == "finance.band")


def test_without_a_rent_the_band_agent_still_reports_ok():
    outcome = band_of(team().run({**BASE, "monthly_rent_krw": None}))
    assert outcome.status is AgentStatus.OK


def test_without_a_rent_the_run_is_not_halted():
    """이것이 M0 의 핵심 단언이다."""
    assert team().run({**BASE, "monthly_rent_krw": None}).halted is False


def test_without_a_rent_the_capacity_lines_are_still_produced():
    data = band_of(team().run({**BASE, "monthly_rent_krw": None})).data
    assert data["capacity"]["equity_line_krw"] == 50_000_000
    assert data["capacity"]["maximum_line_krw"] >= 50_000_000


def test_without_a_rent_no_recommended_ceiling_is_invented():
    """월세 0 으로 계산하면 손익분기가 과소 산출되고 목표매출이 낮게 나온다."""
    data = band_of(team().run({**BASE, "monthly_rent_krw": None})).data
    assert data["bands"] == []
    assert data["deferred"] == ["monthly_rent_krw"]


def test_the_deferred_reason_is_stated_rather_than_left_blank():
    outcome = band_of(team().run({**BASE, "monthly_rent_krw": None}))
    assert "희망 월세" in outcome.message


def test_with_a_rent_the_bands_come_back_exactly_as_before():
    data = band_of(team().run({**BASE, "monthly_rent_krw": 2_500_000})).data
    assert data["deferred"] == []
    assert {line["band"] for line in data["bands"]} == {"EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"}


def test_the_capacity_is_carried_even_when_the_bands_are_computed():
    """화면이 여력과 밴드를 한 곳에서 읽도록 두 경우 모두 같은 키를 싣는다."""
    data = band_of(team().run({**BASE, "monthly_rent_krw": 2_500_000})).data
    assert data["capacity"]["maximum_line_krw"] == data["bands"][-1]["ceiling_krw"]


def test_unregistered_parameters_still_win_over_a_deferred_rent():
    """원천이 없으면 여력조차 낼 수 없다. 유보보다 연동 대기가 먼저다."""
    outcome = band_of(team(EMPTY).run({**BASE, "monthly_rent_krw": None}))
    assert outcome.status is AgentStatus.INTEGRATION_PENDING
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_finance_deferred.py -q`

Expected: FAIL — `data["capacity"]` KeyError.

- [ ] **Step 3: `_band` 를 여력 커널 위로 다시 세운다**

`backend/app/agents/finance.py` 상단 import 에 `compute_capacity` 를 더한다:

```python
from ..funding import ScenarioParams, compute_bands, compute_capacity
```

상수를 하나 더한다(`_BAND_PENDING` 옆):

```python
_RENT_DEFERRED = ("희망 월세를 받기 전에는 권장 조달선과 손익분기를 계산하지 않았습니다. "
                  "자기자본선·차입 여력·최대 조달선은 금융 프로필만으로 나오므로 그대로 냅니다.")
```

`_band`(186행)의 `inputs` 계산 뒤에 유보 분기를 넣는다:

```python
        inputs = self._inputs(conditions)
        # 여력은 금융 프로필만으로 나온다 — `compute_capacity` 는 업종도 월세도 읽지 않는다.
        # 그래서 월세가 없어도 이 세 줄은 낼 수 있고, 못 내는 것은 권장 조달선과 손익분기뿐이다.
        # 여기서 유보(WITHHELD)로 돌려주면 `FinanceReport.halted` 가 참이 되어 입지 판단까지
        # 월세 입력을 기다리게 된다 — 그것이 M0 가 없애려는 상태다.
        capacity = compute_capacity(self.params, equity_krw=inputs["equity_krw"],
                                    existing_debt_krw=inputs["existing_debt_krw"])
        if not inputs["monthly_rent_krw"]:
            return declaration.outcome(
                AgentStatus.OK, message=_RENT_DEFERRED,
                data={"capacity": capacity, "bands": [], "deferred": ["monthly_rent_krw"],
                      "required_capital_krw": None, "required_capital_band": None,
                      "anomalies": [], "decision": (review or Decision.deterministic(
                          "finance.band", schema=BAND_REVIEW_SCHEMA.name)).as_data()},
                provenance=self._provenance(industry),
            ), None
        try:
            computed = compute_bands(self.params, **inputs)
        except ValueError as error:
```

그리고 성공 반환(224행)에 `capacity` 와 `deferred` 를 싣는다:

```python
        return declaration.outcome(
            AgentStatus.OK, data={**computed, "capacity": capacity, "deferred": [],
                                  "anomalies": confirmed, "decision": audit},
            provenance=self._provenance(industry),
        ), computed
```

`compute_capacity` 는 한도 미등록 시 `KeyError` 를 던진다. `self.params.missing(industry)` 검사가 이미 그 앞에 있으므로 도달하지 않지만, `_BAND_FIELDS` 주석(55-57행)에 다음 한 줄을 더한다:

```python
#: `monthly_rent_krw` 의 기본값 0 은 "말하지 않았다" 가 아니라 "0원이다" 라는 뜻이므로,
#: `_band` 가 그 전에 유보 분기로 갈라진다. 여기 기본값만 믿으면 손익분기가 과소 산출된다.
```

- [ ] **Step 4: `_stress` 가 유보 밴드를 견디게 한다**

`_stress`(277행)는 `computed is None` 일 때 밴드의 상태를 물려받는다. 유보 분기는 `computed=None` 을 반환하지만 상태가 `OK` 이므로, 스트레스가 `OK` 인데 데이터가 없는 상태가 된다. 분기를 명시한다:

```python
    def _stress(self, band: AgentOutcome, computed: dict[str, Any] | None,
                selection: Decision | None, conditions: dict[str, Any]) -> AgentOutcome:
        declaration = spec("finance.stress")
        if computed is None:
            # 밴드가 못 나온 이유를 그대로 물려받는다. 여기서 따로 진단하지 않는다.
            # 월세 유보로 밴드가 OK 인 채 산출물이 없는 경우도 여기로 온다 — 스트레스는
            # 밴드 산출물을 읽는 축이므로, 읽을 것이 없으면 유보다.
            status = AgentStatus.WITHHELD if band.active else band.status
            return declaration.outcome(status, message=band.message)
```

- [ ] **Step 5: `_summary` 가 권장 조달선 부재를 견디게 한다**

`backend/app/agents/orchestrator.py:268-282` 의 `_summary` 는 `next(...)` 로 RECOMMENDED 를 찾으므로 빈 `bands` 에서 `StopIteration` 이 난다:

```python
    @staticmethod
    def _summary(prescription: TeamReport) -> dict[str, Any]:
        """팀이 낸 수치를 고르기만 한다. 여기서 새로 계산하는 값은 하나도 없다.

        희망 월세가 없으면 권장 조달선이 없다. 그때도 여력 세 줄은 있으므로 빈 요약을 내지
        않고 낼 수 있는 것만 낸다 — 빈 요약은 "아무것도 못 냈다" 로 읽힌다."""
        band = next((item for item in prescription.outcomes if item.key == "finance.band"), None)
        if band is None or not band.active:
            return {}
        capacity = band.data.get("capacity") or {}
        summary: dict[str, Any] = {
            "equity_line_krw": capacity.get("equity_line_krw"),
            "borrowing_headroom_krw": capacity.get("borrowing_headroom_krw"),
            "maximum_line_krw": capacity.get("maximum_line_krw"),
            "deferred": band.data.get("deferred", []),
        }
        recommended = next((line for line in band.data.get("bands", [])
                            if line["band"] == "RECOMMENDED"), None)
        if recommended is None:
            return summary
        summary.update({
            "recommended_ceiling_krw": recommended["ceiling_krw"],
            "monthly_repayment_krw": recommended["monthly_repayment_krw"],
            "target_monthly_revenue_krw": recommended["target_monthly_revenue_krw"],
            "target_daily_revenue_krw": recommended["target_daily_revenue_krw"],
            "runway_months": recommended["runway_months"],
            "required_capital_krw": band.data.get("required_capital_krw"),
        })
        return summary
```

- [ ] **Step 6: 통과와 회귀를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_finance_deferred.py tests/test_agent_finance.py tests/test_agent_finance_llm.py tests/test_agent_orchestrator.py -q`

Expected: PASS. `test_agent_orchestrator.py::test_the_summary_only_repeats_numbers_the_teams_produced` 와 `test_the_integration_outcome_carries_the_same_numbers_as_the_summary` 가 여전히 통과해야 한다 — 요약에 키가 늘었을 뿐 값은 전부 팀 산출물에서 온다.

- [ ] **Step 7: 전체 회귀**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q 2>&1 | tail -3`

Expected: failed 0건.

- [ ] **Step 8: 커밋**

```bash
git add backend/app/agents/finance.py backend/app/agents/orchestrator.py \
        backend/tests/test_agent_finance_deferred.py
git commit -m "feat(finance): produce the capacity lines without a rent

여력은 금융 프로필만으로 나온다. 월세가 없을 때 밴드를 통째로 유보하면 halted 가 참이 되어
입지 판단까지 월세 입력을 기다리게 되므로, 여력만 싣고 못 낸 것을 deferred 로 밝힌다."
```

---

## Task 4: 발화가 확정된 값과 충돌하면 제안으로만 올린다

**Files:**
- Modify: `backend/app/agents/conditions.py:200-228`
- Modify: `backend/tests/test_agent_conditions_llm.py` (테스트 추가)

- [ ] **Step 1: 계약을 테스트로 쓴다**

`backend/tests/test_agent_conditions_llm.py` 끝에 더한다:

```python
# ── 충돌은 덮어쓰지 않고 제안으로 올린다 ──────────────────────────────────

@pytest.mark.asyncio
async def test_an_utterance_that_contradicts_a_settled_value_never_overwrites_it():
    """폼에 강남구를 확정해 놓고 "마포는 어때" 라고 말해도 조건은 바뀌지 않는다.
    조건 변경은 재실행을 유발하므로 조용히 일어나면 안 된다."""
    responder = ScriptedResponder([mentions({"field": "district", "span": "마포구"})])
    report = await layer(responder).arun(
        {"industry": "카페", "district": "강남구", "equity_krw": 50_000_000,
         "utterance": "마포구는 어때요"})
    assert report.conditions["district"] == "강남구"


@pytest.mark.asyncio
async def test_a_contradicting_utterance_is_surfaced_as_a_proposal():
    responder = ScriptedResponder([mentions({"field": "district", "span": "마포구"})])
    report = await layer(responder).arun(
        {"industry": "카페", "district": "강남구", "equity_krw": 50_000_000,
         "utterance": "마포구는 어때요"})
    assert report.proposals == [
        {"field": "district", "current": "강남구", "proposed": "마포구", "span": "마포구"}]


@pytest.mark.asyncio
async def test_an_utterance_that_agrees_with_a_settled_value_is_not_a_proposal():
    """같은 값을 다시 말한 것은 변경 제안이 아니다."""
    responder = ScriptedResponder([mentions({"field": "district", "span": "강남구"})])
    report = await layer(responder).arun(
        {"industry": "카페", "district": "강남구", "equity_krw": 50_000_000,
         "utterance": "강남구에서 찾고 있어요"})
    assert report.proposals == []


@pytest.mark.asyncio
async def test_a_span_that_is_not_in_the_utterance_never_becomes_a_proposal_either():
    """검증은 채우기와 제안 양쪽에 똑같이 걸린다."""
    responder = ScriptedResponder([mentions({"field": "district", "span": "송파구"})])
    report = await layer(responder).arun(
        {"industry": "카페", "district": "강남구", "equity_krw": 50_000_000,
         "utterance": "마포구는 어때요"})
    assert report.proposals == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_conditions_llm.py -q -k proposal`

Expected: FAIL — `proposals` 가 언제나 빈 목록이다.

- [ ] **Step 3: 추출이 확정된 항목까지 보게 한다**

지금 `_extract`(200행)는 빈 항목이 없으면 모델을 부르지 않고(`not gaps` 조기 반환), 문맥에도 빈 항목만 싣는다. 충돌을 보려면 확정된 항목까지 후보에 넣어야 한다:

```python
    async def _extract(self, conditions: dict[str, Any]) -> Decision:
        utterance = str(conditions.get("utterance") or "").strip()
        if self.llm is None or not utterance:
            # 대조할 원문이 없으면 부르지 않는다 — 검증할 수 없는 추출은 하지 않는다.
            # (예전에는 "빈 칸이 없으면" 도 부르지 않았다. 이제는 이미 확정된 값과 발화가
            #  어긋나는 것을 찾아야 하므로, 빈 칸이 없어도 부른다. 덮어쓰지는 않는다.)
            return Decision.deterministic("condition.location", schema=EXTRACT_SCHEMA.name)
        settled = {key: conditions.get(key) for key, _ in BLOCKING + DEFERRABLE
                   if not _blank(conditions.get(key))}
        return await self.llm.choose(
            agent_key="condition.location", schema=EXTRACT_SCHEMA, verify_against=utterance,
            instruction=("발화에서 각 조건이 언급된 곳을 가리키세요. 이미 확정된 항목이라도 "
                         "발화가 다른 값을 말하면 그것도 가리키세요 — 덮어쓰지 않고 확인만 받습니다. "
                         "금액을 계산하지 말고 원문 조각을 그대로 적으세요."),
            context={"발화": utterance,
                     "비어 있는 항목": [key for key, _ in BLOCKING + DEFERRABLE
                                  if _blank(conditions.get(key))],
                     "이미 확정된 항목": settled})
```

- [ ] **Step 4: 채우기와 제안을 가른다**

`_extracted`(217행) 옆에 짝을 더한다:

```python
    @staticmethod
    def _extracted(conditions: dict[str, Any], extraction: Decision) -> dict[str, Any]:
        """검증된 조각에서 값을 읽어, 비어 있던 항목만 채운다.

        사용자가 화면에서 확정한 값을 모델의 해석이 덮어쓰면 조건이 조용히 바뀌고, 조건이
        바뀌면 재실행이 일어난다. 재실행은 사용자가 아는 상태에서만 일어나야 한다."""
        filled: dict[str, Any] = {}
        for row in extraction.chosen.get("mentions", []):
            name = row.get("field")
            if name not in EXTRACTABLE or name in filled or not _blank(conditions.get(name)):
                continue
            value = resolve_mention(name, row.get("span", ""))
            if value is not None:
                filled[name] = value
        return filled

    @staticmethod
    def _proposals(conditions: dict[str, Any], extraction: Decision) -> list[dict[str, Any]]:
        """발화가 이미 확정된 값과 다른 값을 말한 것. 적용하지 않고 화면에 올리기만 한다.

        검증은 채우기와 똑같다 — 원문에 없는 조각은 제안도 되지 못한다. 그렇지 않으면
        "덮어쓰지는 않으니까" 를 핑계로 검증되지 않은 값이 화면에 오른다."""
        seen: set[str] = set()
        found: list[dict[str, Any]] = []
        for row in extraction.chosen.get("mentions", []):
            name = row.get("field")
            if name not in EXTRACTABLE or name in seen or _blank(conditions.get(name)):
                continue
            value = resolve_mention(name, row.get("span", ""))
            if value is None or value == conditions.get(name):
                continue
            seen.add(name)
            found.append({"field": name, "current": conditions.get(name),
                          "proposed": value, "span": row.get("span", "")})
        return found
```

`run()` 서두의 `proposals: list[dict[str, Any]] = []` 를 실제 호출로 바꾼다:

```python
        extracted = self._extracted(conditions, extraction)
        proposals = self._proposals(conditions, extraction)
        merged = {**conditions, **extracted}
```

파일 상단 docstring 의 "추출은 **비어 있던 항목만 채운다.**" 문단에 다음을 이어 붙인다:

```
발화가 이미 확정된 값과 어긋나면 덮어쓰지 않고 **변경 제안으로 올린다**(`proposals`). 조건
변경은 재실행을 유발하므로 사용자가 모르는 사이에 일어나면 안 된다. 확인 클릭을 없앤 뒤에도
이 경계는 남는다 — 없애는 것은 "맞다고 눌러야 시작한다" 이지 "말한 적 없는 값이 들어간다" 가 아니다.
```

- [ ] **Step 5: 통과와 회귀를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_agent_conditions_llm.py -q`

Expected: PASS. `test_without_an_utterance_the_model_is_not_called_at_all` 은 그대로 통과한다(발화 없음 분기는 남겼다). 빈 칸이 없을 때 모델을 부르지 않던 단언이 있으면 이제 부르는 것이 맞으므로 그 테스트의 이름과 주석을 새 계약으로 고친다.

- [ ] **Step 6: 전체 회귀**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q 2>&1 | tail -3`

Expected: failed 0건.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/agents/conditions.py backend/tests/test_agent_conditions_llm.py
git commit -m "feat(conditions): surface a contradicting utterance as a proposal

확인 클릭을 없애도 조건이 조용히 바뀌어서는 안 된다. 발화가 확정된 값과 어긋나면 덮어쓰지
않고 제안으로만 올리고, 검증은 채우기와 똑같이 건다."
```

---

## Task 5: 제안과 유보를 API 응답에 싣는다

**Files:**
- Modify: `backend/app/main.py:456-470`
- Modify: `lib/types.ts`
- Modify: `backend/tests/test_api_agents.py` (단언 추가)

- [ ] **Step 1: done 프레임 계약을 테스트로 쓴다**

`backend/tests/test_api_agents.py` 끝에 더한다:

```python
def test_the_done_frame_carries_the_deferred_items_and_any_proposals(client, case_id, filled_params):
    """화면이 "무엇을 못 냈는지" 와 "무엇을 바꾸자고 제안하는지" 를 한 프레임에서 읽는다."""
    response = client.post(f"/api/v1/cases/{case_id}/prescribe", json={})
    done = next(frame for frame in frames(response) if frame["event"] == "done")
    assert "deferred" in done["data"]
    assert "proposals" in done["data"]
    assert isinstance(done["data"]["proposals"], list)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_agents.py -q -k deferred`

Expected: FAIL — `KeyError: 'deferred'`.

- [ ] **Step 3: `RunResult` 와 done 프레임에 싣는다**

`backend/app/agents/orchestrator.py` 의 `RunResult` 에 두 필드를 더한다:

```python
    questions: list[dict[str, str]] = field(default_factory=list)
    #: 없어서 그 수치만 못 낸 항목. 되묻지 않고 진행했다는 사실을 화면이 말할 수 있어야 한다.
    deferred: list[str] = field(default_factory=list)
    #: 발화가 확정된 값과 어긋나 올라온 변경 제안. 적용되지 않은 상태로 전달된다.
    proposals: list[dict[str, Any]] = field(default_factory=list)
```

`run_events` 에서 조건 보고를 받은 직후, 두 경로(멈춤·계속) 모두에 넘긴다:

```python
        settled = await self.conditions.arun(conditions)
        for event in self._team_events(settled):
            yield event
        reports.append(settled)
        carried = {"deferred": list(settled.deferred), "proposals": list(settled.proposals)}
        if settled.halted:
            async for event in self._close(fingerprint, reports, halted_at="condition",
                                           questions=list(settled.questions), **carried):
                yield event
            return
```

그리고 마지막 `_close` 호출에도 `**carried` 를 더한다.

`backend/app/main.py:458-462` 의 done 프레임에 두 키를 더한다:

```python
                yield sse_frame({"event": "done", "data": {
                    "fingerprint": result.fingerprint, "reused": result.reused,
                    "halted_at": result.halted_at, "questions": result.questions,
                    "deferred": result.deferred, "proposals": result.proposals,
                    "activation": result.activation, "summary": result.summary,
```

- [ ] **Step 4: `lib/types.ts` 를 맞춘다 (불변조건 5)**

`PrescribeResult` 에 더한다:

```ts
  /** 없어서 그 수치만 내지 못한 조건 항목. 되묻지 않고 진행했다는 사실을 화면이 말한다. */
  deferred: string[];
  /** 발화가 확정된 값과 어긋나 올라온 변경 제안. 적용되지 않은 상태로 온다. */
  proposals: ConditionProposal[];
```

같은 파일에 타입을 더한다:

```ts
export interface ConditionProposal { field: string; current: string | number | null; proposed: string | number; span: string }
```

- [ ] **Step 5: 통과를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_agents.py -q && cd .. && npm run typecheck`

Expected: 둘 다 PASS.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/agents/orchestrator.py backend/app/main.py lib/types.ts \
        backend/tests/test_api_agents.py
git commit -m "feat(prescribe): carry deferred items and proposals to the client"
```

---

## Task 6: 조건 스트립 — 값·근거·출처가 실행 중에도 남는다

확인 클릭을 없애는 대가다. 클릭을 없앨수록 "AI 가 내 말을 뭘로 알아들었는지" 가 계속 보여야 한다.

**Files:**
- Create: `components/kb/ConditionStrip.tsx`
- Modify: `app/globals.css`
- Modify: `components/kb/JarimaegimPanel.tsx:179-272`

- [ ] **Step 1: 스트립 컴포넌트를 만든다**

`components/kb/ConditionStrip.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Pencil, Quote } from "lucide-react";
import { PRIORITY_LABELS, STAGE_LABELS, TYPE_LABELS, SEOUL_DISTRICTS, formatKrw } from "@/lib/constants";
import type { CaseInput, ConditionKey } from "@/lib/types";
import type { Jarimaegim } from "@/lib/use-jarimaegim";

// `ConditionKey` 는 `lib/types.ts:467` 이 이미 갖고 있다. 여기서 다시 선언하면 같은 것을
// 두 곳에서 정의하게 되고, `ConditionInterpretResult.fields` 와 어긋나도 컴파일러가 못 잡는다.

const ROWS: { key: ConditionKey; label: string }[] = [
  { key: "industry", label: "업종" }, { key: "district", label: "자치구" },
  { key: "monthly_rent_krw", label: "희망 월세" }, { key: "business_stage", label: "사업단계" },
  { key: "startup_type", label: "창업형태" }, { key: "priority", label: "우선순위" }
];

/** 확인 화면이 아니라 상주 스트립이다. 확인 클릭을 없앤 대신, 무엇을 어떤 발화 조각에서
 *  읽었는지가 실행 중에도 화면에 남아야 한다. 값은 언제든 인라인으로 고칠 수 있고, 고치면
 *  영향받는 축이 다시 돈다(M4 전까지는 전체 재실행).
 *
 *  추출에 실패한 항목은 빈칸으로 두고 추측으로 채우지 않는다 — 빈칸이 보여야 사용자가
 *  자기가 말하지 않은 것을 알아본다. */
export function ConditionStrip({ flow, editable, onEdited }: {
  flow: Jarimaegim; editable: boolean; onEdited?: () => void;
}) {
  const { form, bandForm, proposal, edited, setField, setBandField } = flow;
  const [open, setOpen] = useState<ConditionKey | null>(null);

  const shown = (key: ConditionKey): string => {
    if (key === "monthly_rent_krw") return bandForm.monthly_rent_krw > 0 ? formatKrw(bandForm.monthly_rent_krw) : "—";
    if (key === "industry") return form.industry.trim() || "—";
    if (key === "district") return form.district;
    if (key === "business_stage") return STAGE_LABELS[form.business_stage];
    if (key === "startup_type") return TYPE_LABELS[form.startup_type];
    return PRIORITY_LABELS[form.priority];
  };
  const source = (key: ConditionKey): string => {
    if (edited.has(key)) return "직접 입력";
    const field = proposal?.fields[key];
    if (!field || field.value === null) return "기본값";
    return proposal?.source === "AI" ? "AI 추론" : "규칙 추출";
  };
  const evidence = (key: ConditionKey): string | null =>
    edited.has(key) ? null : proposal?.fields[key]?.evidence ?? null;

  return <section className="kb-condstrip">
    <h3>이렇게 읽었습니다</h3>
    <ul className="kb-condrows">{ROWS.map((row) => <li key={row.key}>
      <span className="kb-condrow-label">{row.label}</span>
      <strong className="kb-condrow-value">{shown(row.key)}</strong>
      <small className="kb-condrow-source">{source(row.key)}</small>
      <span className="kb-condrow-evidence">{evidence(row.key)
        ? <><Quote aria-hidden="true" />{evidence(row.key)}</>
        : <em>—</em>}</span>
      {/* 편집 패널을 **닫을 때만** 재실행을 알린다. 타이핑 한 글자마다 실행이 돌면 안 된다. */}
      {editable && <button type="button" className="kb-condrow-edit" aria-label={`${row.label} 고치기`}
        onClick={() => { if (open === row.key) { setOpen(null); onEdited?.(); } else setOpen(row.key); }}>
        <Pencil aria-hidden="true" /></button>}
    </li>)}</ul>
    {open && editable && <div className="kb-condstrip-edit">
      {open === "industry" && <label className="kb-field"><span>업종</span>
        <input value={form.industry} onChange={(event) => setField("industry", event.target.value)} placeholder="예: 카페" /></label>}
      {open === "district" && <label className="kb-field"><span>자치구</span>
        <select value={form.district} onChange={(event) => setField("district", event.target.value)}>
          {SEOUL_DISTRICTS.map((district) => <option key={district} value={district}>{district}</option>)}</select></label>}
      {open === "monthly_rent_krw" && <label className="kb-field"><span>희망 월세</span>
        <input type="number" min="0" step="100000" inputMode="numeric" value={bandForm.monthly_rent_krw || ""}
          onChange={(event) => setBandField("monthly_rent_krw", Math.max(0, Number(event.target.value)))} placeholder="0" /></label>}
      {open === "business_stage" && <ChipRow label="사업단계" value={form.business_stage} options={STAGE_LABELS}
        onSelect={(value) => setField("business_stage", value as CaseInput["business_stage"])} />}
      {open === "startup_type" && <ChipRow label="창업형태" value={form.startup_type} options={TYPE_LABELS}
        onSelect={(value) => setField("startup_type", value as CaseInput["startup_type"])} />}
      {open === "priority" && <ChipRow label="우선순위" value={form.priority} options={PRIORITY_LABELS}
        onSelect={(value) => setField("priority", value as CaseInput["priority"])} />}
      <p className="kb-note">고치면 영향받는 분석을 다시 돌립니다.</p>
    </div>}
  </section>;
}

function ChipRow({ label, value, options, onSelect }: { label: string; value: string; options: Record<string, string>; onSelect: (value: string) => void }) {
  return <div className="kb-chiprow"><span>{label}</span><div>{Object.entries(options).map(([key, text]) =>
    <button key={key} type="button" aria-pressed={value === key} onClick={() => onSelect(key)}>{text}</button>)}</div></div>;
}
```

`onEdited` 는 이 과업에서는 아무도 넘기지 않는다(선택 prop). Task 7 이 `flow.rerun` 을 만든 뒤
거기서 배선한다 — 여기서 `flow.rerun` 을 직접 부르면 아직 없는 것을 참조해 타입 검사가 깨진다.

- [ ] **Step 2: 스타일을 더한다**

`app/globals.css` 끝에:

```css
.kb-condstrip{border:1px solid var(--line);border-radius:14px;padding:14px 16px;background:var(--surface)}
.kb-condstrip h3{margin:0 0 10px;font-size:13px;color:var(--muted);font-weight:600}
.kb-condrow-edit{border:0;background:none;padding:4px;color:var(--muted);cursor:pointer;display:flex}
.kb-condrow-edit:hover{color:var(--fg)}
.kb-condstrip-edit{margin-top:12px;padding-top:12px;border-top:1px dashed var(--line);display:grid;gap:10px}
```

- [ ] **Step 3: `ConfirmStep` 을 해체한다**

`components/kb/JarimaegimPanel.tsx` 에서 `CONFIRM_ROWS`(180-184행), `ConfirmStep`(195-272행), `ChipRow`(274-276행)를 삭제하고, 대신 차단 항목만 묻는 `GateStep` 을 둔다:

```tsx
/** 차단 항목만 묻는다. 없으면 계산 자체가 불가능한 것 — 업종·자치구·자기자본뿐이다.
 *  자치구는 기본값이 있고 자기자본은 프로필 단계가 이미 강제하므로, 실제로 여기 남는 것은 업종이다. */
function GateStep({ flow }: { flow: Jarimaegim }) {
  const { form, setField } = flow;
  const ready = Boolean(form.industry.trim());
  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>
      업종만 알려주시면 바로 찾아드릴게요. 나머지는 말씀하신 대로 읽었고, 아래에서 언제든 고칠 수 있습니다.</p></div>
    <ConditionStrip flow={flow} editable />
    {!ready && <section className="kb-askbox">
      <header><span>더 필요한 것</span><small>1 / 최대 3</small></header>
      <label className="kb-field"><span>업종<small>검색 질의어와 업종 파라미터를 정합니다</small></span>
        <input value={form.industry} onChange={(event) => setField("industry", event.target.value)}
          placeholder="예: 카페" autoFocus /></label>
      <p className="kb-note"><Info aria-hidden="true" />희망 월세·평수·보증금은 없어도 진행합니다.
        손익분기와 현금소진만 그때 계산하지 않고 유보합니다.</p>
    </section>}
    <button className="kb-primary" onClick={flow.start} disabled={!ready || flow.busy === "case"}>
      {flow.busy === "case" ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}이 조건으로 입지 찾기</button>
    <button className="kb-ghost" onClick={() => flow.setStep("ask")}><RotateCcw aria-hidden="true" /> 다시 말할게요</button>
  </div>;
}
```

37-38행의 렌더 분기를 바꾼다:

```tsx
      {flow.step === "ask" && <AskStep flow={flow} />}
      {flow.step === "confirm" && <GateStep flow={flow} />}
```

`recommend`·`prescribe` 단계의 렌더에도 스트립을 상주시킨다 — 해당 분기 최상단에 `<ConditionStrip flow={flow} editable />` 를 넣는다.

상단 import 를 정리한다: `Check`·`Quote` 가 더 이상 이 파일에서 쓰이지 않으면 지우고, `ConditionStrip` 을 더한다.

- [ ] **Step 4: 타입 검사와 린트**

Run: `npm run typecheck && npm run lint`

Expected: 에러 0건. 경고는 기준선의 `Workspace.tsx` 한 건만.

- [ ] **Step 5: 커밋**

```bash
git add components/kb/ConditionStrip.tsx components/kb/JarimaegimPanel.tsx app/globals.css
git commit -m "feat(kb): keep the condition strip on screen instead of gating on it

확인 클릭을 없앤 대가다. 클릭을 없앨수록 무엇을 어떤 발화 조각에서 읽었는지가 실행 중에도
보여야 하고, 값은 그 자리에서 고칠 수 있어야 한다."
```

---

## Task 7: 자동 진행 배선

**Files:**
- Modify: `lib/use-jarimaegim.ts:177-208,353-422`

- [ ] **Step 1: `interpret` 이 차단 항목이 차 있으면 그대로 시작하게 한다**

`interpret`(178행)의 `setStep("confirm")` 직전을 바꾼다:

```tsx
      setMessages((prev) => [...prev, { role: "user", text }, { role: "assistant", text: result.message }]);
      // 차단 항목(업종)이 발화에서 채워졌으면 확인을 기다리지 않고 그대로 진행한다.
      // 자치구는 기본값이 있고 자기자본은 프로필 단계가 이미 확정했으므로, 여기서 볼 것은 업종뿐이다.
      // 확인을 없앤 대신 조건 스트립이 실행 화면에 상주하며 무엇을 어떻게 읽었는지 계속 보여준다.
      const industry = typeof field.industry.value === "string" ? field.industry.value.trim() : "";
      if (industry) { setStep("recommend"); void startWith({ ...patch, industry }); return; }
      setStep("confirm");
```

- [ ] **Step 2: `start` 를 조건 오버라이드를 받는 형태로 가른다**

`start`(353행)는 `runInputs` 를 `useMemo` 로 읽는다. `setForm` 직후에 부르면 아직 이전 상태를 본다. 오버라이드를 받는 내부 함수로 가른다:

```tsx
  const startWith = useCallback(async (patch: Partial<CaseInput>) => {
    setError(""); setBusy("case"); setStep("recommend");
    // `form` 은 `setForm` 직후에도 아직 이전 값이다. 자동 진행은 방금 읽은 값으로 시작해야
    // 하므로 상태를 기다리지 않고 패치를 직접 받는다.
    const inputs: CaseInput = { ...form, ...patch, equity_krw: profile.equity_krw, budget_krw: profile.equity_krw };
    beginTrace(planTrace(inputs, "full"));
    try {
      await ensureSession();
      const title = `${inputs.district} ${inputs.industry}`.trim() || "새 케이스";
      const created = await api.createCase(inputs, title);
      setCaseData(created);

      // 실행 순서는 백엔드의 메인 에이전트가 가진다. 여기서는 도착한 판정을 줄에 옮길 뿐,
      // 어느 팀이 먼저인지도 어디서 멈추는지도 클라이언트가 정하지 않는다.
      const settled = new Set<string>();
      const rowId = (key: string) => (key === "main.integrate" ? "grade" : key);
      let outcome: PrescribeResult | null = null;
      let mainOutcome: AgentProgress | null = null;
      await api.prescribeStream(created.id, {
        monthly_rent_krw: bandForm.monthly_rent_krw, monthly_maintenance_krw: bandForm.monthly_maintenance_krw,
        key_money_krw: bandForm.key_money_krw, area_pyeong: bandForm.area_pyeong || null,
        deposit_krw: bandForm.deposit_krw || null, fitout_krw: bandForm.fitout_krw || null,
        existing_debt_krw: profile.existing_debt_krw, other_monthly_fixed_krw: profile.other_monthly_fixed_krw,
        // 운영형태는 화면이 묻지 않는다. 발화에 있으면 처방 때 condition.location 이 읽는다.
        utterance,
      }, {
        onRunStart: () => {},
        onTeamStart: () => {},
        onAgentEnd: (agent) => {
          // 메인 통합은 마지막 줄이다. 여기서 바로 정착시키면 트레이스가 done 으로 넘어가고,
          // 그 뒤에 오는 정리 루프가 전부 무시되어 중간 줄이 "진행 중"인 채로 남는다.
          if (agent.key === "main.integrate") { mainOutcome = agent; return; }
          settled.add(rowId(agent.key));
          settleStep(rowId(agent.key), agent.status === "ok" ? "done" : "skipped", noteFor(agent));
        },
        onDone: (result) => {
          outcome = result;
          for (const row of AGENT_ROWS) {
            if (settled.has(row.id)) continue;
            if (row.id === "grade") {
              const main = mainOutcome;
              settleStep("grade", main && main.status === "ok" ? "done" : "skipped",
                main ? noteFor(main) : "실행이 끝나지 않아 종합하지 못했습니다.");
            } else {
              settleStep(row.id, "skipped", "앞 단계에서 멈춰 순서가 오지 않았습니다.");
            }
          }
        },
      });

      const band = await runBands(created, bandForm, profile);
      const line = recommendedLine(band);
      const ceiling = (outcome as PrescribeResult | null)?.summary?.recommended_ceiling_krw ?? line?.ceiling_krw ?? null;
      // 후보를 거르는 상한은 사용자가 스스로 좁힌 예산이 아니라 산출된 권장 조달선이다.
      // 희망 월세가 없으면 권장 조달선도 없다 — 그때는 케이스 예산을 그대로 둔다.
      const record = ceiling && ceiling > created.inputs.budget_krw
        ? await api.updateCase(created.id, created.version, { budget_krw: ceiling })
        : created;
      if (record !== created) setCaseData(record);
      await runSearch(record);
      await handoff();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "케이스를 만들지 못했습니다.";
      failTrace(message); setLocationState("error"); setError(message);
    } finally { setBusy(""); }
  }, [bandForm, beginTrace, ensureSession, failTrace, form, handoff, profile, runBands, runSearch, settleStep, utterance]);

  const start = useCallback(() => startWith({}), [startWith]);
```

기존 `start`(353-422행)는 통째로 지운다. `runInputs` 는 화면이 상단 배지에서 계속 읽으므로 남긴다.

`startWith` 를 `interpret` 보다 먼저 선언해야 한다 — `interpret` 의 의존성 배열에 `startWith` 를 더한다.

- [ ] **Step 3: 조건 수정이 재실행을 유발하게 한다**

`setField` / `setBandField` 뒤에 재실행 훅을 붙인다. M4 전까지는 전체 재실행이다:

```tsx
  /** 조건을 고치면 영향받는 분석을 다시 돌린다. 부분 무효화는 M5 의 몫이고, 그전까지는
   *  전체를 다시 돈다 — 낡은 판정을 새 조건 옆에 남겨 두는 것보다 낫다. */
  const rerun = useCallback(() => {
    if (!caseData || trace.state === "running") return;
    void startWith({});
  }, [caseData, startWith, trace.state]);
```

Task 6 이 만든 `ConditionStrip` 의 `onEdited` 를 이제 배선한다. `components/kb/JarimaegimPanel.tsx` 의 세 자리(`GateStep`, `recommend` 분기, `prescribe` 분기)에서:

```tsx
<ConditionStrip flow={flow} editable onEdited={flow.rerun} />
```

`GateStep` 에서는 아직 케이스가 없어 `rerun` 이 즉시 반환한다(`!caseData` 가드). 실행 뒤 화면에서만 실제로 다시 돈다.

- [ ] **Step 4: 반환 객체에 더한다**

```tsx
    start, startWith, rerun, retrySearch, runAnalysis, sendChat, loadCatalog, loadKbProducts, dismissTrace
```

- [ ] **Step 5: 타입 검사**

Run: `npm run typecheck && npm run lint`

Expected: 에러 0건.

- [ ] **Step 6: 커밋**

```bash
git add lib/use-jarimaegim.ts components/kb/ConditionStrip.tsx
git commit -m "feat(kb): run straight through when the blocking condition is filled

발화에 업종이 있으면 확인을 기다리지 않고 여력 산출과 입지 판단까지 그대로 간다."
```

---

## Task 8: 흐름 검증 스크립트

**Files:**
- Modify: `scripts/flow-check.mjs:204-259`

- [ ] **Step 1: KB 구간을 자동 진행으로 바꾼다**

`scripts/flow-check.mjs:204-227` 을 교체한다:

```js
await kb.getByRole("button", { name: /^조건 입력으로/ }).click();
await kb.locator(".kb-field-block textarea").fill("강남구에서 카페를 준비 중이고 월세는 250 정도 생각해요");
await kb.getByRole("button", { name: /조건으로 정리하기/ }).click();
// 확인 클릭이 없다. 업종이 발화에서 읽히면 그대로 후보 목록까지 간다.
await kb.waitForSelector(".kb-candidates li, .kb-empty", { timeout: 40000 });

// ② 조건은 발화를 읽어 되돌려주고 **확인 없이 진행한다.** 금융 입력은 이 화면에 없어야 한다.
const rows = await kb.locator(".kb-condstrip .kb-condrows li").allTextContents();
const conditionStep = {
  rowCount: rows.length,
  // "준비 중이에요"의 "중"이 중구로 새지 않아야 한다.
  districtParsed: rows.some(row => row.includes("자치구") && row.includes("강남구")),
  rentParsed: rows.some(row => row.includes("희망 월세") && row.includes("250")),
  // 키가 없는 환경에서는 규칙 추출로 내려가되 출처를 숨기지 않아야 한다.
  sourceLabelled: rows.some(row => row.includes("AI 추론") || row.includes("규칙 추출")),
  // 확인 클릭을 없앤 대가 — 근거 인용이 실행 뒤에도 화면에 남아야 한다.
  evidencePersists: await kb.locator(".kb-condstrip .kb-condrow-evidence svg").count() > 0,
  // 확인 게이트가 되살아나면 회귀다.
  noConfirmGate: await kb.getByRole("button", { name: /네, 맞아요/ }).count() === 0,
  // 단계 분리 회귀 방지 — 자금 항목이 조건 화면의 입력으로 돌아오면 안 된다.
  noProfileChips: !rows.some(row => row.includes("자기자본") || row.includes("기존부채") || row.includes("월 고정지출"))
};
```

- [ ] **Step 2: 월세 없이도 진행되는 경로를 새로 단언한다**

`conditionStep` 블록 뒤에 더한다:

```js
// 희망 월세를 말하지 않아도 입지 판단까지 간다. 손익분기만 유보된다 — 이것이 M0 의 핵심이다.
const noRent = await kbContext.newPage();
await noRent.goto(`${base}/kb`, { waitUntil: "networkidle" });
await noRent.locator(".kb-profile-form input").nth(0).fill("50000000");
await noRent.getByRole("button", { name: /확정하고 조달 여력 보기/ }).click();
await noRent.getByRole("button", { name: /^조건 입력으로/ }).click();
await noRent.locator(".kb-field-block textarea").fill("성동구에서 카페 하려고요");
await noRent.getByRole("button", { name: /조건으로 정리하기/ }).click();
const rentlessRun = {
  reached: await noRent.waitForSelector(".kb-candidates li, .kb-empty", { timeout: 40000 }).then(() => true).catch(() => false),
  // 월세를 지어내지 않고 빈칸으로 둬야 한다.
  rentBlank: (await noRent.locator(".kb-condstrip .kb-condrows li").allTextContents())
    .some(row => row.includes("희망 월세") && row.includes("—"))
};
await noRent.close();
```

- [ ] **Step 3: 출력과 종료 코드를 갱신한다**

`result` 객체에 `rentlessRun` 을 더하고, 마지막 종료 코드 줄을 바꾼다:

```js
if (!kbFlow.stepsAreFour || !kbFlow.tuningInPlace || !kbFlow.bandSafeState || !kbFlow.bandDemoLabelled || !kbFlow.evidenceInline) process.exitCode = 1;
if (!conditionStep.evidencePersists || !conditionStep.noConfirmGate || !rentlessRun.reached || !rentlessRun.rentBlank) process.exitCode = 1;
```

- [ ] **Step 4: 실행한다**

두 터미널이 필요하다. 하나에서 `npm run dev`, 다른 하나에서:

Run: `node scripts/flow-check.mjs`

Expected: 종료 코드 0. `conditionStep.evidencePersists`·`noConfirmGate`·`rentlessRun.reached`·`rentlessRun.rentBlank` 가 전부 `true`.

키가 없는 환경에서 도는 것이 계약이다 — 후보가 0건이면 `.kb-empty` 로 통과하고, 그때도 조건 스트립과 근거 인용은 보여야 한다.

- [ ] **Step 5: 커밋**

```bash
git add scripts/flow-check.mjs
git commit -m "test(flow): assert the run proceeds without a confirm click or a rent"
```

---

## Task 9: 문서 갱신

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 조건 흐름 서술을 고친다**

`CLAUDE.md` 의 프론트엔드 절에 조건 확인 게이트를 전제한 서술이 있으면 상주 스트립으로 바꾸고, `flow-check.mjs` 설명에 "확인 클릭 없이 진행되는지와 근거 인용이 실행 뒤에도 남는지를 단언한다"를 더한다.

- [ ] **Step 2: 테스트 개수를 실제 값으로 갱신한다**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q 2>&1 | tail -3`

출력의 `N passed` 를 `CLAUDE.md` 의 `npm run api:test` 설명에 반영한다(현재 문서는 191, 기준선 실측은 646).

- [ ] **Step 3: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: record the removal of the condition confirm gate"
```

---

## Task 10: 업종 정규화 실패는 되묻기로 복구한다

Task 2 이후 언제든 할 수 있다 — Task 6~9(프론트)와 독립이다.

업종이 채워져 있어도 `industry.resolve()` 가 실패하면("브런치 카페", "스터디카페") 입지 네 축이 통째로 꺼진다. 값이 있으므로 Task 2 의 차단 검사는 통과하고, 사용자는 왜 아무 판정도 없는지 알 수 없다. 이건 확인 절차가 아니라 **실패 복구**이므로 되묻기 경로를 남긴다.

**Files:**
- Modify: `backend/app/industry.py`
- Modify: `backend/app/agents/conditions.py`
- Modify: `backend/tests/test_condition_blocking.py`

- [ ] **Step 1: 계약을 테스트로 쓴다**

`backend/tests/test_condition_blocking.py` 끝에 더한다:

```python
# ── 업종 정규화 실패는 값이 있어도 복구를 요구한다 ────────────────────────

def test_an_unmappable_industry_halts_even_though_the_field_is_filled():
    """'스터디카페'는 값이 있지만 코드로 정규화되지 않는다. 그대로 진행하면 입지 네 축이
    통째로 꺼진 채 아무 설명 없이 빈 결과가 나온다."""
    report = layer().run({**FULL, "industry": "스터디카페"})
    assert report.halted is True
    assert [item["field"] for item in report.questions] == ["industry"]


def test_the_recovery_question_offers_normalisable_candidates():
    """제시는 하되 붙이지는 않는다. 코드가 '스터디카페'를 '커피-음료'에 자동으로 이어 붙이면
    그것이 바로 유사 매칭이고, 전혀 다른 업종의 원가율로 손익분기를 계산하게 된다."""
    question = layer().run({**FULL, "industry": "스터디카페"})["questions"][0] \
        if False else layer().run({**FULL, "industry": "스터디카페"}).questions[0]
    assert question["reason"] == "UNMAPPED_INDUSTRY"
    assert "카페" in question["options"]


def test_a_mappable_industry_produces_no_recovery_question():
    assert layer().run({**FULL, "industry": "카페"}).questions == []


def test_the_unmapped_industry_is_never_silently_replaced():
    report = layer().run({**FULL, "industry": "스터디카페"})
    assert report.conditions["industry"] == "스터디카페"
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest tests/test_condition_blocking.py -q -k unmap`

Expected: FAIL — `report.halted is False`.

- [ ] **Step 3: 후보 제시 함수를 더한다**

`backend/app/industry.py` 끝에:

```python
#: 되묻기에 함께 보여줄 후보 수. 목록이 길면 사용자가 고르지 않고 아무거나 누른다.
SUGGESTION_LIMIT = 6


def suggest(industry: str) -> list[str]:
    """정규화에 실패한 입력에 대해 **표시용** 후보를 고른다. 매칭이 아니다.

    `resolve()` 가 부분 문자열 매칭을 하지 않는 이유와 이 함수가 존재하는 이유는 같다 —
    '스터디카페'를 '카페'로 **자동으로 붙이면** 전혀 다른 업종의 원가율과 폐업률이 그 사람의
    판단 근거가 된다. 그래서 여기서는 고를 수 있는 것을 보여 주기만 하고, 무엇이 선택되는지는
    사용자가 정한다. 반환값이 조건에 자동으로 들어가는 경로는 없다.
    """
    key = normalise(industry)
    if not key:
        return []
    near = [alias for alias in _ALIASES if alias in key or key in alias]
    # 겹치는 것이 없으면 대표 업종을 보여준다 — 빈 목록은 "고칠 방법이 없다" 로 읽힌다.
    fallback = ["카페", "한식", "치킨", "미용실", "편의점", "학원"]
    ordered = near + [item for item in fallback if item not in near]
    return ordered[:SUGGESTION_LIMIT]
```

- [ ] **Step 4: 조건 레이어에 복구 경로를 붙인다**

`backend/app/agents/conditions.py` 상단 import 에 더한다:

```python
from ..industry import resolve as resolve_industry, suggest as suggest_industry
```

`run()` 의 갭 계산 뒤, `questions` 조립 앞에 넣는다:

```python
        # 업종이 채워져 있어도 코드로 정규화되지 않으면 입지 네 축이 통째로 꺼진다. 값이 있으니
        # 차단 검사는 통과하고, 사용자는 왜 아무 판정도 없는지 알 수 없다. 확인 절차가 아니라
        # 실패 복구이므로 여기서만 되묻는다.
        unmapped = (not blocking_gaps
                    and not _blank(merged.get("industry"))
                    and resolve_industry(str(merged["industry"])) is None)
```

`questions` 와 `settled` 조립을 바꾼다:

```python
        questions = self._questions(blocking_gaps, asked)
        if unmapped:
            questions = [{"field": "industry", "label": "업종",
                          "reason": "UNMAPPED_INDUSTRY",
                          "message": (f"'{merged['industry']}' 은(는) 상권 통계의 업종 코드로 "
                                      "이어지지 않아 입지 판단을 할 수 없습니다. 가까운 업종을 골라 주세요."),
                          "options": suggest_industry(str(merged["industry"]))}]
        settled = not blocking_gaps and not unmapped
```

`_questions`(247행)가 내는 항목에는 `reason`·`message`·`options` 가 없으므로, 두 모양이 섞이지 않도록 그쪽에도 빈 값을 채운다:

```python
        return [{"field": key, "label": labels[key], "reason": "MISSING",
                 "message": "", "options": []} for key in ordered][:QUESTION_LIMIT]
```

- [ ] **Step 5: 테스트를 정리한다**

Step 1 의 `test_the_recovery_question_offers_normalisable_candidates` 에 남은 삼항 잔재를 지운다:

```python
def test_the_recovery_question_offers_normalisable_candidates():
    question = layer().run({**FULL, "industry": "스터디카페"}).questions[0]
    assert question["reason"] == "UNMAPPED_INDUSTRY"
    assert "카페" in question["options"]
```

- [ ] **Step 6: 통과와 회귀를 확인한다**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q 2>&1 | tail -3`

Expected: failed 0건. `test_api_agents.py` 의 되묻기 관련 단언이 `questions` 항목 모양 변화를 견디는지 확인한다 — `field` 키는 그대로이므로 통과해야 한다.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/industry.py backend/app/agents/conditions.py backend/tests/test_condition_blocking.py
git commit -m "feat(conditions): recover from an industry that cannot be normalised

값이 있어도 코드로 이어지지 않으면 입지 네 축이 통째로 꺼진다. 후보를 보여주며 되묻되,
자동으로 붙이지는 않는다 — 붙이는 순간 그것이 유사 매칭이다."
```

---

## 완료 기준

- [ ] 업종·자치구·자기자본이 발화에 있으면 확인 클릭 없이 여력 산출과 입지 판단까지 자동 진행된다
- [ ] 셋 중 하나라도 없으면 그것만 되묻는다. 희망 월세·평수·보증금은 되묻지 않는다
- [ ] 희망 월세 없이도 실행이 입지 축까지 도달하고, 손익분기·권장 조달선만 유보된다
- [ ] 두 추출 경로가 같은 금액 파서를 쓰고, "월세 300" 이 양쪽에서 3,000,000원이다
- [ ] 발화에 없는 값이 조건에 들어가지 않는다 (`test_amount_parsing.py`, `test_agent_conditions_llm.py` 로 고정)
- [ ] 발화가 확정된 값과 충돌하면 덮어쓰지 않고 제안으로만 올라온다
- [ ] 모든 추출 값에 근거 원문 조각이 붙고, 실행이 끝난 뒤에도 화면에 남는다
- [ ] 추출에 실패한 항목은 빈칸이고 추측으로 채워지지 않는다
- [ ] 조건을 인라인으로 고치면 재실행된다 (M4 전까지는 전체 재실행)
- [ ] 정규화되지 않는 업종은 후보를 제시하며 되묻고, 코드가 자동으로 다른 업종에 붙이지 않는다
- [ ] `TeamReport` / `FinanceReport.halted` / `AgentStatus` / `ACTIVE_STATUSES` 는 그대로다 — 구조 변경은 M1 이후의 몫이다
- [ ] `npm run lint && npm run typecheck && npm run build && npm run api:test && node scripts/flow-check.mjs` 전부 통과

---

## M1~M5 로드맵

이 문서는 M0 만 다룬다. 나머지는 각각 별도 plan 문서로 전개하며, M0 에서 확인된 사실이 아래 범위를 이미 바꿔 놓았다.

| 단계 | 범위 | M0 조사로 바뀐 것 |
|---|---|---|
| **M1** 계약 재정의 | `AgentSpec.display_group` 추가, `registry.py` 채우기, `/api/v1/status` 노출 | `test_api_agents.py::test_the_roster_lists_all_twelve_declarations` 와 `test_agent_registry.py` 8건이 함께 바뀐다 |
| **M2** 계산 단일화 | `compute_bands` 중복 호출 제거, `ANOMALY_PREDICATES` 전량 코드 평가, `BAND_REVIEW_SCHEMA`·`STRESS_SCHEMA` LLM 호출 제거 | **"4회 → 최대 1회" 는 "4회 → 2회"** 다 (`kb_products`·`subsidy` 선택이 남는다). 유보 이상치 둘은 **소프트 경고로 강등** — 결정론적 유보를 만들면 흔한 입력에서 실행이 멈춘다 |
| **M3** 팀 계층 제거 | `TeamReport` 삭제, halt 규칙을 orchestrator 한 곳으로, 축 이벤트로 교체 | halt 규칙이 셋이 아니라 **둘**이다 (입력 정합성 유보가 M2 에서 사라지므로). `lib/use-jarimaegim.ts:33` 의 `AGENT_ROWS` 12행 하드코딩과 `settleStep` 의 순서 결합, `AgentRunOverlay` 의 `id === "grade"` 조회가 함께 무너진다 |
| **M4** 커널 분리와 축 재편 | 축 8개로 재편, 접근성 축 신설, 축소 규칙 결정론 모듈 분리 | **여력 커널 분리는 M0 가 이미 했다.** `_narrow` 에 탈락 경로가 **둘**이다(viability + `stress_check`) — 후자는 `main.py:407` 에서 배선되지 않아 죽어 있고 `test_agent_location.py:102` 만 살려 두고 있다. 매출 축은 어댑터가 영구 `integration_pending` 이라 **한 번도 돈 적이 없고**, `main.py:183` 은 `enabled=True` 로 보고해 모순이다 — 이걸 고치는 것이 M4 완료 정의에 들어간다 |
| **M5** 병렬 실행과 부분 무효화 | `asyncio.gather` 병렬화, 축 단위 부분 해시 | `RunBudget` 이 선착순(`llm.py:54`)이라 병렬화하면 **어느 축이 `budget_exhausted` 를 받는지가 스케줄링에 좌우된다** — 가드 2(같은 조건 같은 결과)가 깨지므로, 축별 결정론적 예산 배분이 병렬화보다 먼저다 |
