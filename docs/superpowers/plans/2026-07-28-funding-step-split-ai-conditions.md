# 자금 단계 분리와 자연어 조건 AI 추론 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 금융 프로필을 조달 여력 결과로 완결되는 독립 1단계로 승격하고, 자연어 조건을 백엔드가 해석해 "이 조건이 맞나요?"로 확인받는 흐름을 만든다.

**Architecture:** 백엔드에 조회형 POST 두 개(`/funding-capacity`, `/conditions/interpret`)를 추가한다. 여력은 `funding.py`의 기존 산식을 함수로 떼어내 밴드와 공유한다. 조건 추론은 AI 경로와 규칙 경로가 **같은 sanitize 게이트**를 통과하며, 그 게이트의 핵심은 evidence가 사용자 원문의 부분문자열인지 확인하는 기계적 검증이다. 금액 산술은 AI가 아니라 코드가 한다 — AI는 근거 구간만 지목한다. 프론트는 `FlowStep`에 `capacity`를 추가하고 스테퍼를 4칸으로 늘린다.

**Tech Stack:** FastAPI + pydantic v2 (backend), pytest, Next.js App Router + React 19 클라이언트 컴포넌트, 순수 CSS(`app/globals.css`), playwright-core 기반 `scripts/*.mjs`

**설계 문서:** `docs/superpowers/specs/2026-07-28-funding-step-split-ai-conditions-design.md`

**전제:** 모든 명령은 `ter-doctor-demo/`에서 실행한다. 백엔드 venv가 `backend/.venv`에 있어야 한다. pytest는 `backend/`에서 돈다.

---

## 파일 구조

### 신규

| 파일 | 책임 |
|---|---|
| `backend/app/districts.py` | 서울 25개 자치구 단일 출처. 지금 `main.py:53`과 `chat_tools.py:10`에 중복된 집합을 여기로 모은다 |
| `backend/app/condition_parse.py` | 규칙 기반 조건 추출. `lib/parse-case.ts`의 이식본이며 evidence 구간을 함께 돌려준다 |
| `backend/app/condition_interpret.py` | AI/규칙 두 경로가 공유하는 sanitize 게이트. evidence 부분문자열 검증이 여기 산다 |
| `backend/tests/test_condition_parse.py` | 규칙 추출 단위 테스트 |
| `backend/tests/test_condition_interpret.py` | sanitize 게이트 단위 테스트 |
| `backend/tests/test_api_conditions_interpret.py` | 엔드포인트 테스트 |
| `backend/tests/test_api_funding_capacity.py` | 여력 엔드포인트 테스트 |

### 수정

| 파일 | 변경 |
|---|---|
| `backend/app/policy_params.py` | `missing_of` / `unverified_of` / `unverified` 추가 |
| `backend/app/funding.py` | `compute_capacity` 분리, `compute_bands`가 재사용 |
| `backend/app/models.py` | 여력·조건추론 모델 5종 추가, `FundingBandResult`에 `parameter_status`·`unverified_params` 추가 |
| `backend/app/services.py` | `AIService.build_interpret_prompt` / `interpret_conditions` 추가 |
| `backend/app/main.py` | 엔드포인트 2개 추가, `SEOUL_DISTRICTS`를 `districts.py`에서 import |
| `backend/app/chat_tools.py` | `SEOUL_DISTRICTS`를 `districts.py`에서 import |
| `config/policy-params.json` | `verified` 플래그 전면 부여 + 시연용 값 등록 |
| `lib/types.ts` | 백엔드 모델 미러링 |
| `lib/api.ts` | `fundingCapacity` / `interpretConditions` 추가 |
| `lib/use-jarimaegim.ts` | `capacity` 스텝·상태, `interpret` async화, `parsedKeys` 제거 |
| `components/kb/JarimaegimPanel.tsx` | 스테퍼 4칸, `CapacityStep` 신규, `ConfirmStep` 재작성, `AskStep` 수정 |
| `app/globals.css` | 신규 클래스 |
| `scripts/flow-check.mjs` | 바뀐 라벨 + 신규 단언 |
| `scripts/visual-check.mjs` | `capacity` 화면 추가 |

### 삭제

- `lib/parse-case.ts` (추출 규칙이 서버로 이주)

---

## Task 1: 자치구 목록 단일 출처

**Files:**
- Create: `backend/app/districts.py`
- Modify: `backend/app/main.py:53`, `backend/app/chat_tools.py:10-12`

- [ ] **Step 1: 모듈 생성**

`backend/app/districts.py`:

```python
from __future__ import annotations

# 서울 25개 자치구. 부록 A 불변조건 6의 스코프이며, 서버에서 이 집합 밖은 전부 거절한다.
# main.py·chat_tools.py·condition_interpret.py 세 곳이 같은 판단을 하므로 출처를 하나로 둔다.
SEOUL_DISTRICTS = frozenset({
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구",
    "도봉구", "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구",
    "영등포구", "동작구", "관악구", "서초구", "강남구", "송파구", "강동구",
})
```

- [ ] **Step 2: 테스트 작성**

`backend/tests/test_districts.py` 생성:

```python
from app.districts import SEOUL_DISTRICTS


def test_holds_all_twenty_five_districts():
    assert len(SEOUL_DISTRICTS) == 25


def test_main_and_chat_tools_share_the_same_source():
    """같은 판단을 하는 세 모듈이 서로 다른 목록을 들면 스코프 게이트가 갈라진다."""
    from app.main import SEOUL_DISTRICTS as from_main
    from app.chat_tools import SEOUL_DISTRICTS as from_tools
    assert from_main is SEOUL_DISTRICTS
    assert from_tools is SEOUL_DISTRICTS
```

- [ ] **Step 3: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_districts.py -v`
Expected: `test_main_and_chat_tools_share_the_same_source` FAIL — `main.py`가 자기 집합을 들고 있어 `is` 비교가 거짓이다.

- [ ] **Step 4: 두 모듈이 import 하게 바꾸기**

`backend/app/main.py`에서 53행의 `SEOUL_DISTRICTS = {...}` 한 줄을 삭제하고, import 블록의 `from .config import get_settings` 바로 아래에 추가:

```python
from .districts import SEOUL_DISTRICTS
```

`backend/app/chat_tools.py`에서 10-12행의 `SEOUL_DISTRICTS = {...}`를 삭제하고 같은 자리에 추가:

```python
from .districts import SEOUL_DISTRICTS
```

- [ ] **Step 5: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_districts.py tests/test_chat_tools.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/app/districts.py backend/app/main.py backend/app/chat_tools.py backend/tests/test_districts.py
git commit -m "refactor(scope): give the Seoul district set one home"
```

---

## Task 2: PolicyParams 미검증 파라미터 보고

**Files:**
- Modify: `backend/app/policy_params.py:30-39`
- Test: `backend/tests/test_policy_params.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_policy_params.py` 맨 아래(`_shipped_config` 정의 **위**, 즉 `test_industry_returns_field_map` 다음)에 추가:

```python
def test_unverified_is_empty_when_nothing_is_flagged():
    """verified 키가 없는 항목은 검증된 것으로 본다 — 배포 설정은 별도 테스트가 명시를 강제한다."""
    assert PolicyParams(FULL).unverified("카페") == []


def test_unverified_lists_demo_entries():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.policy_fund_ceiling_krw"]["verified"] = False
    assert PolicyParams(raw).unverified("카페") == ["loan.policy_fund_ceiling_krw"]


def test_unverified_lists_a_demo_industry():
    raw = json.loads(json.dumps(FULL))
    raw["industries"]["카페"]["verified"] = False
    assert PolicyParams(raw).unverified("카페") == ["industries.카페"]


def test_unverified_ignores_industries_other_than_the_one_asked_for():
    raw = json.loads(json.dumps(FULL))
    raw["industries"]["분식점"] = {"cogs_ratio": 0.4, "labor_ratio": 0.2, "fitout_krw_per_pyeong": 1,
                                   "operating_days_per_month": 26, "verified": False,
                                   "source": "테스트", "as_of": "2026-07-01"}
    assert PolicyParams(raw).unverified("카페") == []


def test_missing_of_reports_only_the_keys_asked_for():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.term_months"]["value"] = None
    params = PolicyParams(raw)
    assert params.missing_of(("loan.guarantee_ceiling_krw",)) == []
    assert params.missing_of(("loan.term_months",)) == ["loan.term_months"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_policy_params.py -v`
Expected: 5건 FAIL — `AttributeError: 'PolicyParams' object has no attribute 'unverified'`

- [ ] **Step 3: 구현**

`backend/app/policy_params.py`의 `missing` 메서드(30-39행)를 다음으로 교체:

```python
    def missing_of(self, keys: tuple[str, ...]) -> list[str]:
        """주어진 키 중 값이 없는 것. 산출마다 필요한 키가 다르므로 목록을 받는다."""
        return [key for key in keys if (self._entries.get(key) or {}).get("value") is None]

    def missing(self, industry: str) -> list[str]:
        gaps = self.missing_of(REQUIRED_ENTRIES)
        profile = self._industries.get(industry)
        if not profile:
            gaps.append(f"industries.{industry}")
            return gaps
        gaps.extend(f"industries.{industry}.{field}" for field in REQUIRED_INDUSTRY_FIELDS
                    if profile.get(field) is None)
        return gaps

    def unverified_of(self, keys: tuple[str, ...]) -> list[str]:
        """주어진 키 중 verified 가 명시적으로 false 인 것. 값이 없는 키는 missing 이 먼저 잡는다."""
        return [key for key in keys if (self._entries.get(key) or {}).get("verified") is False]

    def unverified(self, industry: str) -> list[str]:
        """이 업종의 밴드 산출에 실제로 쓰이는 값 중 미검증인 것.
        화면이 '시연용'을 표시할지 결정하는 단일 근거다 — 비어 있지 않으면 반드시 표시한다."""
        keys = self.unverified_of(REQUIRED_ENTRIES)
        if (self._industries.get(industry) or {}).get("verified") is False:
            keys.append(f"industries.{industry}")
        return keys
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_policy_params.py -v`
Expected: PASS (전부)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/policy_params.py backend/tests/test_policy_params.py
git commit -m "feat(params): report which registered values are unverified"
```

---

## Task 3: 조달 여력 산식 분리

**Files:**
- Modify: `backend/app/funding.py:84-86`
- Test: `backend/tests/test_funding_math.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_funding_math.py` 맨 위 import를 다음으로 바꾸고:

```python
import pytest
from app.funding import breakeven_monthly_revenue_krw, compute_capacity, monthly_annuity_krw
from app.policy_params import PolicyParams
```

파일 맨 아래에 추가:

```python
CEILINGS = PolicyParams({"entries": {
    "loan.guarantee_ceiling_krw": {"value": 70_000_000},
    "loan.policy_fund_ceiling_krw": {"value": 20_000_000},
}})


def test_capacity_adds_both_ceilings_to_equity():
    result = compute_capacity(CEILINGS, equity_krw=50_000_000, existing_debt_krw=0)
    assert result == {"equity_line_krw": 50_000_000, "borrowing_headroom_krw": 90_000_000,
                      "maximum_line_krw": 140_000_000}


def test_existing_debt_eats_into_the_headroom():
    result = compute_capacity(CEILINGS, equity_krw=50_000_000, existing_debt_krw=30_000_000)
    assert result["borrowing_headroom_krw"] == 60_000_000
    assert result["maximum_line_krw"] == 110_000_000


def test_headroom_never_goes_negative():
    """기존부채가 한도를 넘겨도 음수 여력을 만들지 않는다 — 최대선이 자기자본선 아래로 내려갈 수 없다."""
    result = compute_capacity(CEILINGS, equity_krw=50_000_000, existing_debt_krw=200_000_000)
    assert result["borrowing_headroom_krw"] == 0
    assert result["maximum_line_krw"] == 50_000_000


def test_capacity_needs_no_industry_and_no_rent():
    """1단계가 2단계 입력 없이 성립한다는 사실 자체가 계약이다."""
    assert compute_capacity(CEILINGS, equity_krw=0, existing_debt_krw=0)["maximum_line_krw"] == 90_000_000


def test_capacity_raises_when_a_ceiling_is_unregistered():
    empty = PolicyParams({"entries": {"loan.guarantee_ceiling_krw": {"value": None},
                                      "loan.policy_fund_ceiling_krw": {"value": 20_000_000}}})
    with pytest.raises(KeyError):
        compute_capacity(empty, equity_krw=1, existing_debt_krw=0)
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_funding_math.py -v`
Expected: FAIL — `ImportError: cannot import name 'compute_capacity'`

- [ ] **Step 3: 구현**

`backend/app/funding.py`의 `BAND_ORDER` 선언(28행) 바로 아래에 추가:

```python
# 여력 산출에만 필요한 키. 업종 파라미터도 임대조건도 요구하지 않는다.
CAPACITY_ENTRIES = ("loan.guarantee_ceiling_krw", "loan.policy_fund_ceiling_krw")


def compute_capacity(params, *, equity_krw: int, existing_debt_krw: int) -> dict:
    """자기자본선·차입 여력·최대 조달선. 금융 프로필만으로 나온다.

    권장 조달선은 스트레스 테스트(업종 원가율·인건비율 + 월 고정비)를 요구하므로 여기서 내지 않는다.
    그 경계가 1단계(자금)와 2단계(조건)를 가르는 근거다. 한도가 미등록이면 KeyError 를 던지고,
    호출부가 integration_pending 으로 바꾼다 — 추정으로 메우지 않는다."""
    headroom = max(0, int(params.value("loan.guarantee_ceiling_krw")
                          + params.value("loan.policy_fund_ceiling_krw") - existing_debt_krw))
    return {"equity_line_krw": int(equity_krw), "borrowing_headroom_krw": headroom,
            "maximum_line_krw": int(equity_krw) + headroom}
```

- [ ] **Step 4: `compute_bands`가 같은 함수를 쓰게 하기**

`backend/app/funding.py:84-86`의 세 줄

```python
    borrow_ceiling = max(0, int(params.value("loan.guarantee_ceiling_krw")
                                + params.value("loan.policy_fund_ceiling_krw") - existing_debt_krw))
    maximum_ceiling = int(equity_krw + borrow_ceiling)
```

를 다음으로 교체:

```python
    # 여력과 밴드가 같은 산식을 쓰도록 한 곳에서만 계산한다. 두 화면이 다른 최대선을 말하면 안 된다.
    maximum_ceiling = compute_capacity(params, equity_krw=equity_krw,
                                       existing_debt_krw=existing_debt_krw)["maximum_line_krw"]
```

- [ ] **Step 5: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_funding_math.py tests/test_funding_bands.py tests/test_api_funding_bands.py -v`
Expected: PASS — 밴드 회귀 없음

- [ ] **Step 6: 커밋**

```bash
git add backend/app/funding.py backend/tests/test_funding_math.py
git commit -m "feat(funding): split the profile-only capacity out of the band math"
```

---

## Task 4: 여력·시연용 표기 모델

**Files:**
- Modify: `backend/app/models.py:297-310`
- Test: `backend/tests/test_models_funding.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_models_funding.py` 맨 아래에 추가:

```python
import pytest
from pydantic import ValidationError
from app.models import FundingCapacityResult

PENDING_TEXT = "권장 조달선은 업종과 희망 월세를 받은 뒤 계산합니다."


def test_capacity_result_accepts_a_computed_shape():
    result = FundingCapacityResult(status="computed", equity_line_krw=50_000_000,
                                   borrowing_headroom_krw=90_000_000, maximum_line_krw=140_000_000,
                                   recommended_line_pending=PENDING_TEXT)
    assert result.parameter_status == "VERIFIED"
    assert result.unverified_params == []


def test_unverified_params_force_the_demo_label():
    """미검증 값으로 계산해 놓고 검증됐다고 표시하는 응답은 만들 수 없어야 한다."""
    with pytest.raises(ValidationError):
        FundingCapacityResult(status="computed", equity_line_krw=1, borrowing_headroom_krw=0,
                              maximum_line_krw=1, parameter_status="VERIFIED",
                              unverified_params=["loan.policy_fund_ceiling_krw"],
                              recommended_line_pending=PENDING_TEXT)


def test_demo_label_is_accepted_with_the_reason_listed():
    result = FundingCapacityResult(status="computed", equity_line_krw=1, borrowing_headroom_krw=0,
                                   maximum_line_krw=1, parameter_status="DEMO",
                                   unverified_params=["loan.policy_fund_ceiling_krw"],
                                   recommended_line_pending=PENDING_TEXT)
    assert result.parameter_status == "DEMO"


def test_maximum_line_cannot_fall_below_the_equity_line():
    with pytest.raises(ValidationError):
        FundingCapacityResult(status="computed", equity_line_krw=100, borrowing_headroom_krw=0,
                              maximum_line_krw=50, recommended_line_pending=PENDING_TEXT)


def test_pending_result_needs_no_numbers():
    result = FundingCapacityResult(status="integration_pending",
                                   missing_params=["loan.guarantee_ceiling_krw"],
                                   recommended_line_pending=PENDING_TEXT,
                                   message="한도 파라미터가 등록되지 않았습니다.")
    assert result.maximum_line_krw == 0
```

`backend/tests/test_api_funding_bands.py`의 `test_computes_three_bands_when_params_are_registered`
바로 아래에 추가:

```python
def test_bands_report_the_parameter_grade(client, case_id, filled_params):
    """검증된 파라미터로 계산하면 시연용 표시가 붙지 않는다."""
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    assert payload["parameter_status"] == "VERIFIED"
    assert payload["unverified_params"] == []
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_funding.py tests/test_api_funding_bands.py -v`
Expected: FAIL — `ImportError: cannot import name 'FundingCapacityResult'`

- [ ] **Step 3: 모델 추가**

`backend/app/models.py`의 `FundingBandResult` 클래스(297행) **바로 위**에 추가:

```python
class FundingCapacityInput(BaseModel):
    """조달 여력은 금융 프로필만 요구한다. 업종·임대조건은 2단계에서 받는다."""

    equity_krw: int = Field(ge=0, le=100_000_000_000)
    existing_debt_krw: int = Field(default=0, ge=0, le=100_000_000_000)


class FundingCapacityResult(BaseModel):
    """1단계의 완결 결과. 권장 조달선은 여기서 내지 않고 왜 아직 없는지를 문장으로 말한다."""

    status: Literal["computed", "integration_pending"]
    equity_line_krw: int = Field(default=0, ge=0)
    borrowing_headroom_krw: int = Field(default=0, ge=0)
    maximum_line_krw: int = Field(default=0, ge=0)
    parameter_status: Literal["VERIFIED", "DEMO"] = "VERIFIED"
    unverified_params: list[str] = Field(default_factory=list)
    recommended_line_pending: str = Field(min_length=1)
    missing_params: list[str] = Field(default_factory=list)
    message: str | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def capacity_contract(self):
        if self.unverified_params and self.parameter_status != "DEMO":
            raise ValueError("unverified parameters must mark the result as DEMO")
        if self.status == "computed" and self.maximum_line_krw < self.equity_line_krw:
            raise ValueError("maximum line cannot fall below the equity line")
        return self
```

- [ ] **Step 4: `FundingBandResult`에 같은 두 필드 추가**

`backend/app/models.py`의 `FundingBandResult` 안, `missing_params` 선언 바로 위에 추가:

```python
    parameter_status: Literal["VERIFIED", "DEMO"] = "VERIFIED"
    unverified_params: list[str] = Field(default_factory=list)
```

그리고 같은 클래스의 기존 `@model_validator(mode="after")` 함수 본문 **첫 줄**에 추가:

```python
        if self.unverified_params and self.parameter_status != "DEMO":
            raise ValueError("unverified parameters must mark the result as DEMO")
```

- [ ] **Step 5: 밴드 엔드포인트가 등급을 싣게 하기**

`backend/app/main.py`의 `create_funding_bands`에서 `provenance = Provenance(...)` 문장 **바로 위**에 추가:

```python
    unverified = policy_params.unverified(payload.industry)
    if unverified:
        limitations.insert(0, f"미검증 시연용 파라미터로 계산했습니다: {' · '.join(unverified)}")
```

같은 함수의 `return FundingBandResult(` 인자 목록에서 `missing_params=...` 줄 바로 앞에 추가:

```python
                             parameter_status="DEMO" if unverified else "VERIFIED",
                             unverified_params=unverified,
```

`backend/app/models.py` import 줄(main.py 24-26행)의 `FundingBandInput, FundingBandResult`를
`FundingBandInput, FundingBandResult, FundingCapacityInput, FundingCapacityResult`로 바꾼다.

- [ ] **Step 6: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_funding.py tests/test_api_funding_bands.py -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add backend/app/models.py backend/app/main.py backend/tests/test_models_funding.py backend/tests/test_api_funding_bands.py
git commit -m "feat(funding): carry the parameter grade on every band result"
```

---

## Task 5: 여력 엔드포인트

**Files:**
- Modify: `backend/app/main.py` (`create_funding_bands` 아래)
- Test: `backend/tests/test_api_funding_capacity.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_api_funding_capacity.py` 생성:

```python
import json
import pytest
from fastapi.testclient import TestClient

BODY = {"equity_krw": 50_000_000, "existing_debt_krw": 0}

FILLED = {
    "schema_version": 1, "updated_at": "2026-07-27",
    "entries": {
        "loan.guarantee_ceiling_krw": {"value": 70_000_000, "verified": True, "source": "테스트", "as_of": "2026-07-01"},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000, "verified": True, "source": "테스트", "as_of": "2026-07-01"},
    },
    "industries": {},
}


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as instance:
        instance.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield instance


@pytest.fixture
def filled_params(tmp_path, monkeypatch):
    path = tmp_path / "policy-params.json"
    path.write_text(json.dumps(FILLED, ensure_ascii=False), encoding="utf-8")
    import app.main as main
    from app.policy_params import PolicyParams
    monkeypatch.setattr(main, "policy_params", PolicyParams.load(path))
    return path


@pytest.fixture
def demo_params(tmp_path, monkeypatch):
    raw = json.loads(json.dumps(FILLED))
    raw["entries"]["loan.policy_fund_ceiling_krw"]["verified"] = False
    path = tmp_path / "demo-params.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    import app.main as main
    from app.policy_params import PolicyParams
    monkeypatch.setattr(main, "policy_params", PolicyParams.load(path))
    return path


def test_requires_a_session():
    from app.main import app
    with TestClient(app) as anonymous:
        assert anonymous.post("/api/v1/funding-capacity", json=BODY).status_code == 401


def test_needs_no_case(client, filled_params):
    """1단계는 케이스 생성 전에 돈다. 케이스를 요구하면 단계 분리가 성립하지 않는다."""
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert payload["status"] == "computed"
    assert payload["maximum_line_krw"] == 140_000_000


def test_reports_the_three_lines(client, filled_params):
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert payload["equity_line_krw"] == 50_000_000
    assert payload["borrowing_headroom_krw"] == 90_000_000
    assert payload["maximum_line_krw"] == 140_000_000


def test_says_why_the_recommended_line_is_not_here_yet(client, filled_params):
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert "업종" in payload["recommended_line_pending"]
    assert "월세" in payload["recommended_line_pending"]


def test_existing_debt_shrinks_the_headroom(client, filled_params):
    payload = client.post("/api/v1/funding-capacity",
                          json={**BODY, "existing_debt_krw": 200_000_000}).json()
    assert payload["borrowing_headroom_krw"] == 0
    assert payload["maximum_line_krw"] == 50_000_000


def test_unregistered_ceilings_yield_integration_pending(client):
    """배포 설정에 한도가 없으면 추정하지 않고 무엇이 빈지 말한다."""
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    if payload["status"] == "integration_pending":
        assert len(payload["missing_params"]) > 0
        assert payload["message"]
        assert payload["maximum_line_krw"] == 0


def test_demo_parameters_are_labelled(client, demo_params):
    payload = client.post("/api/v1/funding-capacity", json=BODY).json()
    assert payload["parameter_status"] == "DEMO"
    assert "loan.policy_fund_ceiling_krw" in payload["unverified_params"]
    assert any("시연용" in item for item in payload["provenance"]["limitations"])


def test_rejects_a_negative_equity(client):
    response = client.post("/api/v1/funding-capacity", json={**BODY, "equity_krw": -1})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_funding_capacity.py -v`
Expected: 대부분 FAIL with 404 — 엔드포인트 없음

- [ ] **Step 3: 엔드포인트 구현**

`backend/app/main.py`의 `from .funding import compute_bands`를
`from .funding import CAPACITY_ENTRIES, compute_bands, compute_capacity`로 바꾸고,
`create_funding_bands` 함수 **바로 아래**에 추가:

```python
RECOMMENDED_LINE_PENDING = ("권장 조달선은 업종과 희망 월세를 받은 뒤 스트레스 테스트로 계산합니다. "
                            "지금은 추정하지 않습니다.")


@app.post("/api/v1/funding-capacity", response_model=FundingCapacityResult)
async def create_funding_capacity(payload: FundingCapacityInput, session_id: UUID = Depends(current_session)):
    """1단계의 완결점. 케이스 이전에 돌며 금융 프로필만으로 나오는 세 줄을 돌려준다."""
    missing = policy_params.missing_of(CAPACITY_ENTRIES)
    if missing:
        return FundingCapacityResult(
            status="integration_pending", missing_params=missing,
            recommended_line_pending=RECOMMENDED_LINE_PENDING,
            message="조달 한도 파라미터가 아직 등록되지 않았습니다. 등록 전에는 추정하지 않습니다.")
    computed = compute_capacity(policy_params, equity_krw=payload.equity_krw,
                                existing_debt_krw=payload.existing_debt_krw)
    unverified = policy_params.unverified_of(CAPACITY_ENTRIES)
    limitations = ["최대 조달선은 신용평가·보증 심사 전 추정치이며 확정 한도가 아닙니다",
                   "권장 조달선은 업종 파라미터와 희망 월세가 있어야 계산됩니다"]
    if unverified:
        limitations.insert(0, f"미검증 시연용 파라미터로 계산했습니다: {' · '.join(unverified)}")
    if computed["borrowing_headroom_krw"] == 0 and payload.existing_debt_krw > 0:
        limitations.append("기존 대출 잔액이 한도를 모두 소진해 추가 차입 여력이 없습니다")
    provenance = Provenance(source_name="자리매김 조달 여력 계산", industry_scope="업종 무관",
                            spatial_unit="사용자 입력 금융 프로필", source_as_of=policy_params.updated_at,
                            confidence="LOW", limitations=limitations)
    return FundingCapacityResult(status="computed", **computed,
                                 parameter_status="DEMO" if unverified else "VERIFIED",
                                 unverified_params=unverified,
                                 recommended_line_pending=RECOMMENDED_LINE_PENDING,
                                 provenance=provenance)
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_funding_capacity.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/main.py backend/tests/test_api_funding_capacity.py
git commit -m "feat(api): return funding capacity from the profile alone"
```

---

## Task 6: 시연용 제도 파라미터 등록

**Files:**
- Modify: `config/policy-params.json`
- Test: `backend/tests/test_policy_params.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_policy_params.py`의 `test_shipped_values_all_carry_a_source_and_date` 아래에 추가:

```python
def test_shipped_entries_state_verification_explicitly():
    """verified 를 빼먹으면 미검증 값이 검증된 값으로 조용히 통과한다. 명시를 강제한다."""
    raw = _shipped_config()
    for key, entry in raw["entries"].items():
        assert isinstance(entry.get("verified"), bool), f"{key} 에 verified 가 없습니다"
    for name, profile in (raw.get("industries") or {}).items():
        assert isinstance(profile.get("verified"), bool), f"industries.{name} 에 verified 가 없습니다"


def test_shipped_demo_values_say_so_in_their_source():
    raw = _shipped_config()
    for key, entry in raw["entries"].items():
        if entry.get("verified") is False:
            assert "시연용" in (entry.get("source") or ""), f"{key} 출처가 시연용임을 밝히지 않습니다"


def test_shipped_industries_all_have_a_positive_contribution_margin():
    """공헌이익률이 0 이하면 compute_bands 가 ValueError 로 죽는다."""
    raw = _shipped_config()
    for name, profile in (raw.get("industries") or {}).items():
        margin = 1.0 - profile["cogs_ratio"] - profile["labor_ratio"]
        assert margin > 0, f"industries.{name} 의 공헌이익률이 {margin} 입니다"


def test_shipped_config_computes_bands_for_every_registered_industry():
    """등록해 놓고 계산이 안 되면 등록한 의미가 없다."""
    from app.funding import compute_bands
    params = PolicyParams(_shipped_config())
    for name in (_shipped_config().get("industries") or {}):
        assert params.missing(name) == []
        result = compute_bands(params, industry=name, area_pyeong=15.0, deposit_krw=50_000_000,
                               monthly_rent_krw=2_500_000, monthly_maintenance_krw=300_000,
                               key_money_krw=0, fitout_krw=None, equity_krw=100_000_000,
                               existing_debt_krw=0, other_monthly_fixed_krw=1_000_000)
        assert len(result["bands"]) == 3
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_policy_params.py -v`
Expected: FAIL — `verified` 없음, `industries`가 비어 있어 `missing`이 비지 않음

- [ ] **Step 3: 설정 파일 교체**

`config/policy-params.json` 전체를 다음으로 교체:

```json
{
  "schema_version": 1,
  "updated_at": "2026-07-28",
  "note": "verified:true 는 출처 원문을 확인한 값, verified:false 는 시연용 미검증 값이다. 미검증 값으로 계산한 결과는 API 가 parameter_status:\"DEMO\" 와 unverified_params 를 실어 보내고 화면이 '시연용' 배지를 끌 수 없게 붙인다(부록 A 불변조건 1: 값을 숨기는 대신 값의 성격을 밝힌다).\n실서비스 전 원문으로 대체해야 하는 항목:\n  loan.term_months — 2026년 융자사업 공고 원문(hwpx/pdf) 확인 필요.\n  loan.guarantee_ceiling_krw — 지역신용보증재단·보증상품별로 한도가 달라 대상 재단과 상품을 먼저 정해야 한다.\n  loan.policy_fund_ceiling_krw — 2차 출처는 7,000만원이라 하나 공고 원문 미확인.\n  industries.* — 원가율·인건비율·평당 인테리어 단가·월 영업일수. 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값이다.",
  "entries": {
    "loan.annual_rate_percent": {
      "value": 4.45,
      "unit": "PERCENT",
      "verified": true,
      "source": "소상공인시장진흥공단 정책자금 안내 — 2026년 3/4분기 일반경영안정자금 대리대출 금리(정책자금 기준금리 3.85% + 0.6%p). https://www.semas.or.kr/web/SUP01/SUP0103/SUP010301.kmdc — KB 상품 제시 금리가 아니라 정책자금 공시 금리다.",
      "as_of": "2026-07-01"
    },
    "loan.term_months": {
      "value": 60,
      "unit": "MONTHS",
      "verified": false,
      "source": "시연용 미검증 값 — 2차 출처 5년(거치 2년 포함). 2026년 융자사업 공고 원문 미확인.",
      "as_of": "2026-07-28"
    },
    "loan.guarantee_ceiling_krw": {
      "value": 100000000,
      "unit": "KRW",
      "verified": false,
      "source": "시연용 미검증 값 — 지역신용보증재단 보증상품별 한도가 상이해 단일 값이 성립하지 않는다. 대상 재단·상품 확정 전 가정값.",
      "as_of": "2026-07-28"
    },
    "loan.policy_fund_ceiling_krw": {
      "value": 70000000,
      "unit": "KRW",
      "verified": false,
      "source": "시연용 미검증 값 — 2차 출처 7,000만원. 공고 원문 미확인.",
      "as_of": "2026-07-28"
    },
    "stress.revenue_drop_ratio": {
      "value": 0.2,
      "unit": "RATIO",
      "verified": true,
      "source": "자리매김 설계 결정 — 스펙 §6 하드 탈락 규칙의 스트레스 시나리오(매출 −20%)",
      "as_of": "2026-07-27"
    },
    "stress.repayment_burden_cap_ratio": {
      "value": 0.1,
      "unit": "RATIO",
      "verified": true,
      "source": "자리매김 설계 결정 — 권장 조달선 판정 기준(스트레스 매출 대비 월 상환 비율 상한)",
      "as_of": "2026-07-27"
    },
    "working_capital.months": {
      "value": 3,
      "unit": "MONTHS",
      "verified": true,
      "source": "자리매김 설계 결정 — 필요자금에 포함하는 초기 운전자금 개월수",
      "as_of": "2026-07-27"
    }
  },
  "industries": {
    "카페": {"cogs_ratio": 0.35, "labor_ratio": 0.25, "fitout_krw_per_pyeong": 2500000, "operating_days_per_month": 30, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"},
    "제과점": {"cogs_ratio": 0.40, "labor_ratio": 0.25, "fitout_krw_per_pyeong": 3000000, "operating_days_per_month": 30, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"},
    "치킨전문점": {"cogs_ratio": 0.42, "labor_ratio": 0.20, "fitout_krw_per_pyeong": 2200000, "operating_days_per_month": 30, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"},
    "분식점": {"cogs_ratio": 0.38, "labor_ratio": 0.22, "fitout_krw_per_pyeong": 1800000, "operating_days_per_month": 26, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"},
    "주점": {"cogs_ratio": 0.33, "labor_ratio": 0.25, "fitout_krw_per_pyeong": 2600000, "operating_days_per_month": 26, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"},
    "편의점": {"cogs_ratio": 0.72, "labor_ratio": 0.12, "fitout_krw_per_pyeong": 1500000, "operating_days_per_month": 30, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"},
    "미용실": {"cogs_ratio": 0.20, "labor_ratio": 0.40, "fitout_krw_per_pyeong": 2800000, "operating_days_per_month": 26, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"},
    "일반음식점": {"cogs_ratio": 0.40, "labor_ratio": 0.25, "fitout_krw_per_pyeong": 2400000, "operating_days_per_month": 26, "verified": false, "source": "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아 설계 가정값을 등록한다.", "as_of": "2026-07-28"}
  }
}
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_policy_params.py tests/test_api_funding_capacity.py -v`
Expected: PASS. `test_unregistered_ceilings_yield_integration_pending`은 이제 `computed` 경로로 들어가 단언을 건너뛴다(조건부 테스트).

- [ ] **Step 5: 전체 회귀 확인**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q`
Expected: 전부 PASS. `test_api_funding_bands.py::test_returns_integration_pending_while_parameters_are_unregistered`가
이제 깨진다면(파라미터가 다 찼으므로) 그 테스트를 다음으로 바꾼다:

```python
def test_returns_integration_pending_for_an_unregistered_industry(client, case_id):
    """미등록 업종이 남아 있는 동안은 추정하지 않고 누락 목록을 돌려준다."""
    response = client.post("/api/v1/funding-bands",
                           json={"case_id": case_id, **{**BODY, "industry": "우주정거장"}})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "integration_pending"
    assert payload["bands"] == []
    assert payload["break_even"] is None
    assert "industries.우주정거장" in payload["missing_params"]
    assert payload["message"]
```

- [ ] **Step 6: 커밋**

```bash
git add config/policy-params.json backend/tests/test_policy_params.py backend/tests/test_api_funding_bands.py
git commit -m "feat(params): register demo policy values flagged as unverified"
```

---

## Task 7: 규칙 기반 조건 추출

**Files:**
- Create: `backend/app/condition_parse.py`
- Test: `backend/tests/test_condition_parse.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_condition_parse.py` 생성:

```python
from app.condition_parse import amount_from, parse_conditions


def test_finds_a_district_by_full_name():
    result = parse_conditions("마포구에서 카페를 준비 중이에요")
    assert result["district"]["value"] == "마포구"
    assert result["district"]["evidence"] == "마포구"


def test_finds_a_district_by_stem():
    result = parse_conditions("성동에 가게를 내려고 해요")
    assert result["district"]["value"] == "성동구"
    assert result["district"]["evidence"] == "성동"


def test_does_not_read_중구_out_of_준비_중():
    """'준비 중이에요'의 '중'이 중구로 새면 자치구가 통째로 틀린다."""
    assert parse_conditions("강남구에서 카페를 준비 중이에요")["district"]["value"] == "강남구"
    assert parse_conditions("카페를 준비 중이에요")["district"]["value"] is None


def test_maps_an_industry_hint_to_a_registered_name():
    result = parse_conditions("커피 파는 가게 하고 싶어요")
    assert result["industry"]["value"] == "카페"
    assert result["industry"]["evidence"] == "커피"


def test_falls_back_to_a_named_industry():
    result = parse_conditions("꽃집을 창업하려고 해요")
    assert result["industry"]["value"] == "꽃집"


def test_reads_a_rent_with_a_unit():
    result = parse_conditions("월세는 300만원 정도 생각해요")
    assert result["monthly_rent_krw"]["value"] == 3_000_000
    assert "300만원" in result["monthly_rent_krw"]["evidence"]


def test_reads_a_bare_rent_number_as_manwon():
    """'월세 300'은 한국어 관행상 300만원이다. 확인 화면이 인용과 함께 보여주므로 고칠 수 있다."""
    assert parse_conditions("월세 300 정도요")["monthly_rent_krw"]["value"] == 3_000_000


def test_ignores_an_amount_with_no_rent_hint():
    """자기자본은 1단계가 소유한다. 발화가 그것을 덮어쓰면 안 된다."""
    assert parse_conditions("자기자본 5천만원 있어요")["monthly_rent_krw"]["value"] is None


def test_reads_the_business_stage():
    result = parse_conditions("2호점 낼 자리를 찾고 있어요")
    assert result["business_stage"]["value"] == "SECOND_STORE"
    assert result["business_stage"]["evidence"] == "2호점"


def test_reads_the_startup_type():
    assert parse_conditions("프랜차이즈로 하려고요")["startup_type"]["value"] == "FRANCHISE"


def test_reads_the_priority():
    assert parse_conditions("임대료가 제일 걱정이에요")["priority"]["value"] == "COST"


def test_every_evidence_is_a_substring_of_the_input():
    """규칙 경로도 AI 경로와 같은 evidence 계약을 지킨다."""
    text = "마포구에서 카페 준비 중이고 월세는 300 정도, 처음 창업이라 안정적이면 좋겠어요"
    for field in parse_conditions(text).values():
        if field["evidence"] is not None:
            assert field["evidence"] in text


def test_unmentioned_fields_are_null():
    result = parse_conditions("안녕하세요")
    assert all(field["value"] is None for field in result.values())


def test_amount_from_handles_units():
    assert amount_from("1억") == 100_000_000
    assert amount_from("5천만원") == 50_000_000
    assert amount_from("300만원") == 3_000_000
    assert amount_from("300") == 3_000_000
    assert amount_from("근거 없음") is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_condition_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.condition_parse'`

- [ ] **Step 3: 구현**

`backend/app/condition_parse.py` 생성:

```python
from __future__ import annotations
import re
from typing import Any

from .districts import SEOUL_DISTRICTS

# lib/parse-case.ts 의 이식본. 자기자본·총예산 추출은 뺐다 — 1단계 금융 프로필이 소유하는 값을
# 발화가 덮어쓰면 확정한 것이 조용히 흔들린다. 대신 희망 월세를 뽑는다.
# 모든 필드는 value 와 함께 evidence(원문 구간)를 돌려준다. AI 경로와 같은 계약을 지켜야
# 확인 화면의 인용 표시가 두 경로에서 동일하게 동작한다.

FIELDS = ("industry", "district", "monthly_rent_krw", "business_stage", "startup_type", "priority")

INDUSTRY_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"카페|커피|coffee", re.I), "카페"),
    (re.compile(r"베이커리|빵집|제과"), "제과점"),
    (re.compile(r"치킨"), "치킨전문점"),
    (re.compile(r"분식"), "분식점"),
    (re.compile(r"술집|주점|호프|이자카야|와인바"), "주점"),
    (re.compile(r"편의점"), "편의점"),
    (re.compile(r"미용실|헤어|미용"), "미용실"),
    (re.compile(r"네일|속눈썹"), "네일샵"),
    (re.compile(r"학원|공부방|교습소"), "학원"),
    (re.compile(r"세탁"), "세탁소"),
    (re.compile(r"피시방|PC방", re.I), "PC방"),
    (re.compile(r"무인|셀프\s*빨래"), "무인점포"),
    (re.compile(r"음식점|식당|밥집|한식|중식|일식|양식"), "일반음식점"),
]
NAMED_INDUSTRY = re.compile(r"([가-힣A-Za-z]{2,10})\s*(?:을|를|)\s*(?:창업|개업|오픈|차리|열려|열고|준비)")

UNITS = {"억": 100_000_000, "천만": 10_000_000, "백만": 1_000_000, "만": 10_000}
AMOUNT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(억|천만|백만|만)?\s*원?")
# 월세 힌트 뒤 18자 안에서 금액을 찾는다. 힌트가 없으면 금액을 월세로 읽지 않는다.
RENT = re.compile(r"(월세|임대료|월\s*임대)[^\d]{0,18}(\d+(?:[.,]\d+)?\s*(?:억|천만|백만|만)?\s*원?)")

STAGES = [(re.compile(r"이전|옮기|이사"), "RELOCATING"),
          (re.compile(r"2호점|두\s*번째|분점|추가\s*매장"), "SECOND_STORE"),
          (re.compile(r"처음|첫\s*가게|초보|신규"), "PRE_OPEN")]
TYPES = [(re.compile(r"프랜차이즈|가맹"), "FRANCHISE"),
         (re.compile(r"개인\s*창업|독립|자체\s*브랜드"), "INDEPENDENT")]
PRIORITIES = [(re.compile(r"안정|오래|버티|리스크|위험"), "STABILITY"),
              (re.compile(r"유동인구|손님|수요|매출"), "DEMAND"),
              (re.compile(r"저렴|싼|비용|임대료|월세\s*낮"), "COST"),
              (re.compile(r"성장|확장|뜨는|상권\s*발전"), "GROWTH")]

MAX_KRW = 100_000_000_000


def amount_from(text: str) -> int | None:
    """'300만원'·'1억'·'300'을 원 단위 정수로. 단위 없는 수는 만원 관행을 따른다.

    AI 경로도 이 함수를 쓴다 — 모델은 근거 구간만 지목하고 산술은 코드가 한다
    (부록 A 불변조건 4)."""
    match = AMOUNT.search(text)
    if not match:
        return None
    try:
        raw = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = match.group(2)
    value = round(raw * UNITS[unit]) if unit else round(raw * 10_000)
    if value <= 0 or value > MAX_KRW:
        return None
    return value


def _field(value: Any = None, evidence: str | None = None) -> dict[str, Any]:
    return {"value": value, "evidence": evidence}


def _first(patterns: list[tuple[re.Pattern[str], str]], text: str) -> dict[str, Any]:
    for pattern, value in patterns:
        match = pattern.search(text)
        if match:
            return _field(value, match.group(0))
    return _field()


def _district(text: str) -> dict[str, Any]:
    # 전체 이름을 먼저 찾고, 없을 때만 "마포에서"처럼 조사를 뗀 어간을 본다. 어간이 한 글자인
    # 중구는 "준비 중이에요"의 "중"에 걸려 자치구를 통째로 잘못 채우므로 어간 검색에서 제외한다.
    for name in SEOUL_DISTRICTS:
        if name in text:
            return _field(name, name)
    for name in SEOUL_DISTRICTS:
        stem = name[:-1]
        if len(stem) >= 2 and stem in text:
            return _field(name, stem)
    return _field()


def _industry(text: str) -> dict[str, Any]:
    for pattern, name in INDUSTRY_HINTS:
        match = pattern.search(text)
        if match:
            return _field(name, match.group(0))
    named = NAMED_INDUSTRY.search(text)
    if named:
        return _field(named.group(1), named.group(1))
    return _field()


def _rent(text: str) -> dict[str, Any]:
    match = RENT.search(text)
    if not match:
        return _field()
    value = amount_from(match.group(2))
    return _field(value, match.group(0)) if value is not None else _field()


def parse_conditions(text: str) -> dict[str, dict[str, Any]]:
    """문장이 실제로 말한 필드만 채운다. 말하지 않은 것은 value·evidence 모두 None 이다."""
    return {
        "industry": _industry(text),
        "district": _district(text),
        "monthly_rent_krw": _rent(text),
        "business_stage": _first(STAGES, text),
        "startup_type": _first(TYPES, text),
        "priority": _first(PRIORITIES, text),
    }
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_condition_parse.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/condition_parse.py backend/tests/test_condition_parse.py
git commit -m "feat(conditions): port the rule extractor to the server with evidence spans"
```

---

## Task 8: sanitize 게이트

**Files:**
- Create: `backend/app/condition_interpret.py`
- Test: `backend/tests/test_condition_interpret.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_condition_interpret.py` 생성:

```python
from app.condition_interpret import sanitize


def test_keeps_a_field_whose_evidence_is_in_the_text():
    text = "마포구에서 카페를 준비 중이에요"
    result = sanitize(text, {"district": {"value": "마포구", "evidence": "마포구에서"}})
    assert result["fields"]["district"]["value"] == "마포구"
    assert result["fields"]["district"]["evidence"] == "마포구에서"


def test_drops_a_field_whose_evidence_is_not_in_the_text():
    """모델이 지어낸 값은 근거 문구가 원문에 없으므로 통과할 수 없다 — 이 게이트가 핵심이다."""
    text = "마포구에서 카페를 준비 중이에요"
    result = sanitize(text, {"monthly_rent_krw": {"value": 3_000_000, "evidence": "월세는 300만원"}})
    assert result["fields"]["monthly_rent_krw"]["value"] is None
    assert "monthly_rent_krw" in result["unresolved"]


def test_drops_a_field_with_a_value_but_no_evidence():
    result = sanitize("카페 준비 중", {"industry": {"value": "카페", "evidence": None}})
    assert result["fields"]["industry"]["value"] is None


def test_drops_a_district_outside_seoul():
    text = "부산진구에서 카페를 하려고요"
    result = sanitize(text, {"district": {"value": "부산진구", "evidence": "부산진구"}})
    assert result["fields"]["district"]["value"] is None
    assert "부산진구" in result["message"] or "서울" in result["message"]


def test_computes_the_rent_from_the_evidence_not_from_the_model():
    """모델은 구간만 지목하고 산술은 코드가 한다(부록 A 불변조건 4)."""
    text = "월세는 300만원 정도 생각해요"
    result = sanitize(text, {"monthly_rent_krw": {"value": 999, "evidence": "월세는 300만원"}})
    assert result["fields"]["monthly_rent_krw"]["value"] == 3_000_000


def test_drops_a_rent_whose_evidence_holds_no_number():
    text = "월세가 부담돼요"
    result = sanitize(text, {"monthly_rent_krw": {"value": 3_000_000, "evidence": "월세가 부담돼요"}})
    assert result["fields"]["monthly_rent_krw"]["value"] is None


def test_drops_an_enum_value_outside_the_union():
    text = "처음 창업이에요"
    result = sanitize(text, {"business_stage": {"value": "FRANCHISING", "evidence": "처음 창업"}})
    assert result["fields"]["business_stage"]["value"] is None


def test_keeps_a_valid_enum_value():
    text = "처음 창업이에요"
    result = sanitize(text, {"business_stage": {"value": "PRE_OPEN", "evidence": "처음 창업"}})
    assert result["fields"]["business_stage"]["value"] == "PRE_OPEN"


def test_drops_an_industry_that_is_not_a_string():
    result = sanitize("카페", {"industry": {"value": 42, "evidence": "카페"}})
    assert result["fields"]["industry"]["value"] is None


def test_always_returns_every_field_key():
    result = sanitize("안녕하세요", {})
    assert set(result["fields"]) == {"industry", "district", "monthly_rent_krw",
                                     "business_stage", "startup_type", "priority"}
    assert len(result["unresolved"]) == 6


def test_ignores_keys_the_model_invented():
    result = sanitize("카페", {"budget_krw": {"value": 1, "evidence": "카페"}})
    assert "budget_krw" not in result["fields"]


def test_message_counts_what_survived():
    text = "마포구에서 카페 준비 중이에요"
    result = sanitize(text, {"district": {"value": "마포구", "evidence": "마포구"},
                             "industry": {"value": "카페", "evidence": "카페"}})
    assert "2" in result["message"]
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_condition_interpret.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.condition_interpret'`

- [ ] **Step 3: 구현**

`backend/app/condition_interpret.py` 생성:

```python
from __future__ import annotations
from typing import Any

from .condition_parse import FIELDS, amount_from
from .districts import SEOUL_DISTRICTS

# AI 경로와 규칙 경로가 함께 통과하는 단 하나의 게이트.
#
# 부록 A 불변조건 4("AI는 설명, 계산은 코드")를 프롬프트 문구가 아니라 코드로 강제한다.
# 핵심은 evidence 부분문자열 검증이다 — 모델이 "카페면 보통 월세 300쯤"이라고 채우면 그
# 근거 문구가 사용자 원문에 없으므로 여기서 죽는다. 프롬프트는 어길 수 있지만 이 검사는 없다.
#
# 금액은 모델이 준 value 를 믿지 않고 evidence 구간에서 코드가 다시 계산한다. 모델이 하는 일은
# "어느 구간이 월세를 말하는가"를 지목하는 것뿐이다.

STAGES = frozenset({"PRE_OPEN", "RELOCATING", "SECOND_STORE"})
TYPES = frozenset({"INDEPENDENT", "FRANCHISE", "UNDECIDED"})
PRIORITIES = frozenset({"STABILITY", "DEMAND", "COST", "GROWTH"})
ENUMS = {"business_stage": STAGES, "startup_type": TYPES, "priority": PRIORITIES}


def _blank() -> dict[str, Any]:
    return {"value": None, "evidence": None}


def sanitize(text: str, proposed: dict[str, Any]) -> dict[str, Any]:
    """제안된 필드를 검증해 살아남은 것만 돌려준다. 실패한 필드는 조용히 버리고 unresolved 로 옮긴다.

    응답 전체를 버리지 않는 것이 의도다 — 여섯 필드 중 하나가 어긋났다고 나머지 다섯을
    사용자에게 다시 입력받게 만들 이유가 없다."""
    fields: dict[str, dict[str, Any]] = {}
    notes: list[str] = []
    for name in FIELDS:
        fields[name] = _keep(text, name, proposed.get(name), notes)
    unresolved = [name for name, field in fields.items() if field["value"] is None]
    kept = len(FIELDS) - len(unresolved)
    message = (f"말씀에서 조건 {kept}개를 찾았습니다. 맞는지 확인해 주세요."
               if kept else "말씀에서 확정할 수 있는 조건을 찾지 못했습니다. 아래에서 직접 골라 주세요.")
    if notes:
        message = f"{message} {' '.join(notes)}"
    return {"fields": fields, "unresolved": unresolved, "message": message}


def _keep(text: str, name: str, raw: Any, notes: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _blank()
    evidence, value = raw.get("evidence"), raw.get("value")
    # 게이트 1 — 근거 없는 값은 통과하지 못한다.
    if not isinstance(evidence, str) or not evidence or evidence not in text:
        return _blank()
    if name == "monthly_rent_krw":
        # 게이트 2 — 산술은 코드가 한다. 모델이 준 숫자는 읽지 않는다.
        amount = amount_from(evidence)
        return {"value": amount, "evidence": evidence} if amount is not None else _blank()
    if name == "district":
        # 게이트 3 — 서울 25개 자치구 밖은 거절한다(부록 A 불변조건 6).
        if value not in SEOUL_DISTRICTS:
            notes.append("서울 25개 자치구만 지원해 지역은 직접 골라 주세요.")
            return _blank()
        return {"value": value, "evidence": evidence}
    if name in ENUMS:
        # 게이트 4 — 정의된 열거값만 통과한다.
        return {"value": value, "evidence": evidence} if value in ENUMS[name] else _blank()
    # industry — 자유 문자열이지만 길이와 타입은 케이스 모델의 상한을 따른다.
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        return _blank()
    return {"value": value.strip(), "evidence": evidence}
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_condition_interpret.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/condition_interpret.py backend/tests/test_condition_interpret.py
git commit -m "feat(conditions): gate every proposed field on evidence in the user's own words"
```

---

## Task 9: 조건 추론 모델

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_models_funding.py` (조건 모델도 여기에 둔다 — 새 파일을 만들 만큼 크지 않다)

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_models_funding.py` 맨 아래에 추가:

```python
from app.models import ConditionInterpretRequest, ConditionInterpretResult


def test_interpret_request_rejects_an_empty_text():
    with pytest.raises(ValidationError):
        ConditionInterpretRequest(text="")


def test_interpret_request_rejects_an_overlong_text():
    with pytest.raises(ValidationError):
        ConditionInterpretRequest(text="가" * 501)


def test_interpret_result_holds_a_field_map():
    result = ConditionInterpretResult(
        source="RULE",
        fields={"industry": {"value": "카페", "evidence": "카페"},
                "district": {"value": None, "evidence": None},
                "monthly_rent_krw": {"value": None, "evidence": None},
                "business_stage": {"value": None, "evidence": None},
                "startup_type": {"value": None, "evidence": None},
                "priority": {"value": None, "evidence": None}},
        unresolved=["district", "monthly_rent_krw", "business_stage", "startup_type", "priority"],
        message="조건 1개를 찾았습니다.")
    assert result.fields["industry"].value == "카페"
    assert result.source == "RULE"


def test_interpret_result_rejects_an_unknown_field_name():
    with pytest.raises(ValidationError):
        ConditionInterpretResult(source="RULE", fields={"budget_krw": {"value": 1, "evidence": "1"}},
                                 unresolved=[], message="x")
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_funding.py -v`
Expected: FAIL — `ImportError: cannot import name 'ConditionInterpretRequest'`

- [ ] **Step 3: 모델 추가**

`backend/app/models.py` 맨 아래에 추가:

```python
class ConditionField(BaseModel):
    """추출된 값 하나와 그 근거. evidence 는 사용자 원문의 부분문자열이며 서버가 검증한 뒤에만 채워진다."""

    value: str | int | None = None
    evidence: str | None = None


class ConditionInterpretRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class ConditionInterpretResult(BaseModel):
    """조건 제안. 케이스를 만들지 않으며, 사용자가 확인 화면에서 승인해야 조건이 된다.
    equity_krw·budget_krw 는 의도적으로 없다 — 1단계 금융 프로필이 소유하는 값이다."""

    source: Literal["AI", "RULE"]
    fields: dict[Literal["industry", "district", "monthly_rent_krw",
                         "business_stage", "startup_type", "priority"], ConditionField]
    unresolved: list[str] = Field(default_factory=list)
    message: str
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_models_funding.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/models.py backend/tests/test_models_funding.py
git commit -m "feat(models): add the condition proposal contract"
```

---

## Task 10: AI 추출 프롬프트와 호출

**Files:**
- Modify: `backend/app/services.py` (`AIService`)
- Test: `backend/tests/test_ai_prompt.py`

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_ai_prompt.py` 맨 아래에 추가:

```python
import pytest


def test_the_interpret_prompt_forbids_inventing_values():
    prompt = service().build_interpret_prompt("마포구에서 카페 준비 중이에요")
    assert "null" in prompt
    assert "추론" in prompt


def test_the_interpret_prompt_demands_verbatim_evidence():
    prompt = service().build_interpret_prompt("질문")
    assert "원문 그대로" in prompt


def test_the_interpret_prompt_forbids_arithmetic():
    """금액 환산은 서버가 한다. 모델에게 계산을 시키면 불변조건 4가 프롬프트에만 남는다."""
    prompt = service().build_interpret_prompt("질문")
    assert "계산" in prompt


def test_the_interpret_prompt_states_the_seoul_scope():
    assert "서울" in service().build_interpret_prompt("질문")


def test_the_interpret_prompt_carries_the_user_text():
    assert "마포구에서 카페" in service().build_interpret_prompt("마포구에서 카페")


def test_build_interpret_prompt_needs_no_api_key():
    assert service().client is None
    assert service().build_interpret_prompt("q")


async def test_interpret_conditions_returns_none_without_a_key():
    """키가 없으면 호출부가 규칙 경로로 내려갈 수 있도록 None 을 돌려준다."""
    assert await service().interpret_conditions("마포구에서 카페") is None
```

`backend/pytest.ini`가 `asyncio_mode = auto`이므로 마커 없이 `async def`만으로 돈다.
파일 맨 위에 `import pytest`를 더할 필요도 없다.

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_ai_prompt.py -v`
Expected: FAIL — `AttributeError: 'AIService' object has no attribute 'build_interpret_prompt'`

- [ ] **Step 3: 구현**

`backend/app/services.py`의 `AIService` 클래스 안, `explain` 메서드 **아래**에 추가:

```python
    # 모델에게 값을 채우게 하지 않고 "어느 구간이 그 말을 하는가"를 지목하게 한다.
    # 금액 환산조차 시키지 않는다 — monthly_rent_krw 의 value 는 서버가 evidence 에서 다시 계산한다.
    CONDITION_SCHEMA = {
        "type": "object", "additionalProperties": False,
        "required": ["industry", "district", "monthly_rent_krw", "business_stage",
                     "startup_type", "priority"],
        "properties": {
            name: {
                "type": "object", "additionalProperties": False,
                "required": ["value", "evidence"],
                "properties": {
                    "value": {"type": ["string", "integer", "null"]},
                    "evidence": {"type": ["string", "null"]},
                },
            }
            for name in ("industry", "district", "monthly_rent_krw", "business_stage",
                         "startup_type", "priority")
        },
    }

    def build_interpret_prompt(self, user_text: str) -> str:
        """조건 추출기의 지시문. explain 과 마찬가지로 키 없이도 단정할 수 있게 분리해 둔다."""
        return (
            "당신은 자리매김의 조건 추출기입니다. 사용자 문장이 명시적으로 말한 것만 뽑습니다.\n"
            "1. 문장에 없는 값은 반드시 null 로 두세요. 추론·보완·평균값 채우기를 금지합니다.\n"
            "2. 값을 채운 필드는 evidence 에 근거가 된 사용자 문장의 일부를 원문 그대로 복사하세요. "
            "요약·번역·재작성은 금지이며, 원문에 없는 문구를 넣으면 그 필드는 버려집니다.\n"
            "3. 어떤 계산도 하지 마세요. 합계·단위 환산·비율·기간 환산 전부 금지입니다.\n"
            "4. district 는 서울 25개 자치구 이름만 허용합니다. 그 밖의 지역은 null 입니다.\n"
            "5. monthly_rent_krw 의 value 는 비워 두고(null) evidence 에 월세를 말한 구간만 넣으세요. "
            "금액 환산은 서버가 합니다.\n"
            "6. business_stage 는 PRE_OPEN·RELOCATING·SECOND_STORE, "
            "startup_type 은 INDEPENDENT·FRANCHISE·UNDECIDED, "
            "priority 는 STABILITY·DEMAND·COST·GROWTH 중 하나입니다.\n"
            f"사용자 문장: {user_text}"
        )

    async def interpret_conditions(self, user_text: str) -> dict[str, Any] | None:
        """모델이 제안한 필드 맵. 키가 없거나 호출이 실패하면 None 을 돌려주고 호출부가 규칙 경로로 간다.

        여기서 나온 값은 아직 신뢰 대상이 아니다 — condition_interpret.sanitize 를 반드시 통과해야 한다."""
        if not self.client or not self.settings.ai_chat_model or not self.settings.ai_explanation_enabled:
            return None
        try:
            response = await self._respond(self.build_interpret_prompt(user_text))
            text = (response.output_text or "").strip()
            if not text:
                return None
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
```

`backend/app/services.py` 맨 위 import 블록에 `import json`이 없다면 추가한다.

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_ai_prompt.py -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services.py backend/tests/test_ai_prompt.py
git commit -m "feat(ai): ask the model to point at evidence, never to fill in values"
```

---

## Task 11: 조건 추론 엔드포인트

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_conditions_interpret.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`backend/tests/test_api_conditions_interpret.py` 생성:

```python
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as instance:
        instance.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield instance


def test_requires_a_session():
    from app.main import app
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/v1/conditions/interpret", json={"text": "마포구 카페"})
    assert response.status_code == 401


def test_needs_no_case(client):
    """조건 추론은 케이스 생성 전에 돈다."""
    response = client.post("/api/v1/conditions/interpret",
                           json={"text": "마포구에서 카페를 준비 중이에요"})
    assert response.status_code == 200


def test_falls_back_to_the_rule_extractor_without_a_key(client):
    """키 없는 환경에서도 흐름이 멈추지 않는다 — flow-check.mjs 가 이 경로를 돈다."""
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "마포구에서 카페를 준비 중이에요"}).json()
    assert payload["source"] == "RULE"
    assert payload["fields"]["district"]["value"] == "마포구"
    assert payload["fields"]["industry"]["value"] == "카페"


def test_every_returned_evidence_is_in_the_user_text(client):
    text = "성동구에 2호점 낼 자리를 찾고 있고 월세는 400만원 정도 생각해요"
    payload = client.post("/api/v1/conditions/interpret", json={"text": text}).json()
    for field in payload["fields"].values():
        if field["evidence"] is not None:
            assert field["evidence"] in text


def test_reports_what_it_could_not_resolve(client):
    payload = client.post("/api/v1/conditions/interpret", json={"text": "안녕하세요"}).json()
    assert len(payload["unresolved"]) == 6
    assert payload["message"]


def test_does_not_return_equity_or_budget(client):
    """1단계가 소유하는 값을 2단계 발화가 덮어쓰면 안 된다."""
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "자기자본 5천만원 있고 강남구 카페요"}).json()
    assert "equity_krw" not in payload["fields"]
    assert "budget_krw" not in payload["fields"]


def test_a_district_outside_seoul_does_not_survive(client):
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "부산 해운대구에서 카페를 하려고요"}).json()
    assert payload["fields"]["district"]["value"] is None


def test_rejects_an_empty_text(client):
    response = client.post("/api/v1/conditions/interpret", json={"text": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_rejects_an_overlong_text(client):
    response = client.post("/api/v1/conditions/interpret", json={"text": "가" * 501})
    assert response.status_code == 400


def test_a_hallucinated_field_is_dropped(client, monkeypatch):
    """모델이 원문에 없는 근거로 값을 채우면 응답에 남지 않는다."""
    async def fake(_text):
        return {"monthly_rent_krw": {"value": 3_000_000, "evidence": "월세는 300만원입니다"}}
    import app.main as main
    monkeypatch.setattr(main.ai, "interpret_conditions", fake)
    payload = client.post("/api/v1/conditions/interpret",
                          json={"text": "강남구에서 카페를 준비 중이에요"}).json()
    assert payload["source"] == "AI"
    assert payload["fields"]["monthly_rent_krw"]["value"] is None
```

- [ ] **Step 2: 실패 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_conditions_interpret.py -v`
Expected: FAIL — 404

- [ ] **Step 3: 엔드포인트 구현**

`backend/app/main.py`의 import 블록에 추가:

```python
from .condition_interpret import sanitize as sanitize_conditions
from .condition_parse import parse_conditions
```

`.models` import 목록에 `ConditionInterpretRequest, ConditionInterpretResult`를 더한다.

`create_funding_capacity` 함수 아래에 추가:

```python
@app.post("/api/v1/conditions/interpret", response_model=ConditionInterpretResult)
async def interpret_conditions(payload: ConditionInterpretRequest,
                               session_id: UUID = Depends(current_session)):
    """발화를 조건 제안으로 바꾼다. 케이스를 만들지 않으며, 확인 화면의 승인이 있어야 조건이 된다.

    AI 경로와 규칙 경로가 같은 sanitize 게이트를 지난다. AI 가 없거나 실패하면 규칙 경로로
    내려가며, 두 경로 모두 evidence 가 사용자 원문의 부분문자열임을 검증받는다."""
    proposed = await ai.interpret_conditions(payload.text)
    source = "AI" if proposed is not None else "RULE"
    if proposed is None:
        proposed = parse_conditions(payload.text)
    result = sanitize_conditions(payload.text, proposed)
    return ConditionInterpretResult(source=source, **result)
```

- [ ] **Step 4: 통과 확인**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api_conditions_interpret.py -v`
Expected: PASS

- [ ] **Step 5: 백엔드 전체 회귀**

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q`
Expected: 전부 PASS

- [ ] **Step 6: 커밋**

```bash
git add backend/app/main.py backend/tests/test_api_conditions_interpret.py
git commit -m "feat(api): interpret free-form conditions into a proposal to confirm"
```

---

## Task 12: 프론트 타입과 API 클라이언트

**Files:**
- Modify: `lib/types.ts`, `lib/api.ts`

- [ ] **Step 1: 타입 추가**

`lib/types.ts`의 `FundingBandResult` 인터페이스 안, `missing_params` 줄 바로 위에 추가:

```ts
  parameter_status: "VERIFIED" | "DEMO";
  unverified_params: string[];
```

같은 파일 `FundingBandResult` 인터페이스 **아래**에 추가:

```ts
/** 1단계의 완결 결과. 권장 조달선은 여기 없고, 왜 아직 없는지를 문장으로 말한다. */
export interface FundingCapacityResult {
  status: "computed" | "integration_pending";
  equity_line_krw: number;
  borrowing_headroom_krw: number;
  maximum_line_krw: number;
  parameter_status: "VERIFIED" | "DEMO";
  unverified_params: string[];
  recommended_line_pending: string;
  missing_params: string[];
  message: string | null;
  provenance: Provenance | null;
}

export type ConditionKey = "industry" | "district" | "monthly_rent_krw" | "business_stage" | "startup_type" | "priority";

/** evidence 는 사용자 원문의 부분문자열이며, 서버 검증을 통과한 값만 채워져 온다. */
export interface ConditionField { value: string | number | null; evidence: string | null }

/** 조건 제안. 케이스가 아니며 확인 화면의 승인이 있어야 조건이 된다.
 *  equity_krw·budget_krw 는 의도적으로 없다 — 1단계 금융 프로필이 소유한다. */
export interface ConditionInterpretResult {
  source: "AI" | "RULE";
  fields: Record<ConditionKey, ConditionField>;
  unresolved: string[];
  message: string;
}
```

- [ ] **Step 2: API 클라이언트 추가**

`lib/api.ts` 첫 줄의 `import type { ... }` 목록에 `ConditionInterpretResult`, `FundingCapacityResult`를 더한다.

`export const api = {` 블록 안, `fundingBands:` 줄 **바로 아래**에 추가:

```ts
  // 서버 상태를 만들지 않는 조회형 POST 다. searchLocations 와 같은 성격이므로 Idempotency-Key 를 붙이지 않는다.
  fundingCapacity: (equity_krw: number, existing_debt_krw: number) => request<FundingCapacityResult>("/funding-capacity", { method: "POST", body: JSON.stringify({ equity_krw, existing_debt_krw }) }),
  interpretConditions: (text: string) => request<ConditionInterpretResult>("/conditions/interpret", { method: "POST", body: JSON.stringify({ text }) }),
```

- [ ] **Step 3: 타입 검사**

Run: `npm run typecheck`
Expected: 통과 (`parsedKeys` 관련 오류는 Task 13에서 정리하므로 이 시점에는 없어야 한다)

- [ ] **Step 4: 커밋**

```bash
git add lib/types.ts lib/api.ts
git commit -m "feat(api): mirror the capacity and condition contracts on the client"
```

---

## Task 13: 흐름 상태 확장

**Files:**
- Modify: `lib/use-jarimaegim.ts`
- Delete: `lib/parse-case.ts`

- [ ] **Step 1: `FlowStep`과 상태 추가**

`lib/use-jarimaegim.ts:11`의 타입 선언과 그 위 주석을 다음으로 교체:

```ts
// 금융 프로필은 관문이 아니라 1단계다. 자기자본을 입력한 사용자는 그 자리에서 조달 여력을
// 돌려받고 단계를 끝낸다(capacity). 조건은 그다음 단계이며 금융 입력을 일절 받지 않는다.
// 최대 조달선은 프로필만으로 나오고 권장 조달선만 업종·월세를 요구한다 — 이 경계가 단계를 가른다.
export type FlowStep = "profile" | "capacity" | "ask" | "confirm" | "recommend" | "prescribe";
```

7행의 `import type { ... }`에 `ConditionInterpretResult`, `FundingCapacityResult`를 더한다.

- [ ] **Step 2: `parsedKeys` 제거하고 제안 상태로 교체**

`lib/use-jarimaegim.ts:72`의

```ts
  const [parsedKeys, setParsedKeys] = useState<Set<keyof CaseInput>>(new Set());
```

를 다음으로 교체:

```ts
  // 출처 라벨과 인용의 원본. 필드별로 "무엇에서 그렇게 읽었는지"를 화면이 말할 수 있어야 한다.
  const [proposal, setProposal] = useState<ConditionInterpretResult | null>(null);
  // '다시 말할게요'로 돌아갔을 때 입력했던 문장을 복원한다.
  const [interpretText, setInterpretText] = useState("");
  const [edited, setEdited] = useState<Set<string>>(new Set());
  const [capacity, setCapacity] = useState<FundingCapacityResult | null>(null);
  const [capacityState, setCapacityState] = useState<LocationState>("idle");
```

- [ ] **Step 3: `interpret`을 서버 호출로 바꾸기**

`lib/use-jarimaegim.ts:131-141`의 `interpret`과 `setField`를 다음으로 교체:

```ts
  /** 발화를 서버 제안으로 바꾼다. 케이스는 아직 만들지 않는다 — 확인 화면의 승인이 그 일을 한다. */
  const interpret = useCallback(async (text: string) => {
    setBusy("interpret"); setError(""); setInterpretText(text);
    try {
      await ensureSession();
      const result = await api.interpretConditions(text);
      setProposal(result); setEdited(new Set());
      const patch: Partial<CaseInput> = {};
      const rent = result.fields.monthly_rent_krw.value;
      if (typeof result.fields.industry.value === "string") patch.industry = result.fields.industry.value;
      if (typeof result.fields.district.value === "string") patch.district = result.fields.district.value;
      if (typeof result.fields.business_stage.value === "string") patch.business_stage = result.fields.business_stage.value as CaseInput["business_stage"];
      if (typeof result.fields.startup_type.value === "string") patch.startup_type = result.fields.startup_type.value as CaseInput["startup_type"];
      if (typeof result.fields.priority.value === "string") patch.priority = result.fields.priority.value as CaseInput["priority"];
      setForm((prev) => ({ ...prev, ...patch }));
      if (typeof rent === "number" && rent > 0) setBandForm((prev) => ({ ...prev, monthly_rent_krw: rent }));
      setMessages((prev) => [...prev, { role: "user", text }, { role: "assistant", text: result.message }]);
      setStep("confirm");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "조건을 정리하지 못했습니다. 아래에서 직접 골라 주세요.");
      setProposal(null); setStep("confirm");
    } finally { setBusy(""); }
  }, [ensureSession]);

  /** 직접 입력으로 시작. 서버를 거치지 않고 빈 제안으로 확인 화면에 들어간다. */
  const startManual = useCallback(() => {
    setProposal(null); setEdited(new Set()); setInterpretText(""); setStep("confirm");
  }, []);

  const setField = useCallback(<K extends keyof CaseInput>(key: K, value: CaseInput[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setEdited((prev) => new Set(prev).add(key as string));
  }, []);
```

- [ ] **Step 4: `setBandField`가 편집을 기록하게 하기**

`lib/use-jarimaegim.ts:145-147`의 `setBandField` 본문을 다음으로 교체:

```ts
  const setBandField = useCallback((key: keyof BandForm, value: number | null) => {
    setBandForm((prev) => ({ ...prev, [key]: value } as BandForm));
    setEdited((prev) => new Set(prev).add(key as string));
  }, []);
```

- [ ] **Step 5: 여력 조회와 프로필 확정 연결**

`lib/use-jarimaegim.ts:154-157`의 `confirmProfile`을 다음으로 교체하고, 그 **바로 위**에 `loadCapacity`를 둔다:

```ts
  /** 조달 여력. 케이스 이전이라 프로필만 보낸다. 실패해도 조건으로 가는 길은 막지 않는다. */
  const loadCapacity = useCallback(async (financial: Profile) => {
    setCapacityState("loading");
    try {
      await ensureSession();
      const result = await api.fundingCapacity(financial.equity_krw, financial.existing_debt_krw);
      setCapacity(result);
      setCapacityState(result.status === "computed" ? "success" : "integration_pending");
    } catch { setCapacity(null); setCapacityState("error"); }
  }, [ensureSession]);

  /** 프로필 확정. 여기서 끝내지 않고 조달 여력까지 돌려준 뒤에야 1단계가 완결된다. */
  const confirmProfile = useCallback(() => {
    saveProfile(profile);
    setProfileConfirmed(true); setProfileRestored(true); setStep("capacity");
    void loadCapacity(profile);
  }, [loadCapacity, profile]);
```

- [ ] **Step 6: 복원 경로와 초기화 정리**

`lib/use-jarimaegim.ts:108-113`의 복원 effect 본문 마지막 줄을 다음으로 교체:

```ts
    setStep((current) => current === "profile" ? "capacity" : current);
```

같은 effect 안 `setProfileRestored(true);` 다음 줄에 추가:

```ts
    void loadCapacity(stored);
```

그리고 그 effect의 의존성 배열을 `[]`에서 `[loadCapacity]`로 바꾼다.

`forgetProfile`(159-163행) 본문 끝에 추가:

```ts
    setCapacity(null); setCapacityState("idle");
```

`restart`(409-415행)의 첫 줄을 다음으로 교체:

```ts
    setStep("ask"); setForm(DEFAULT_CASE); setProposal(null); setInterpretText(""); setEdited(new Set()); setCaseData(null);
```

(프로필과 `capacity`는 건드리지 않는다 — 조건을 다시 받는다고 자금을 다시 묻지 않는다.)

- [ ] **Step 7: 반환 객체 갱신**

`lib/use-jarimaegim.ts:417-425`의 return 문에서 `parsedKeys, interpret,`를
`proposal, interpretText, edited, interpret, startManual,`로 바꾸고,
`profile, setProfileField,` 앞에 `capacity, capacityState, loadCapacity,`를 더한다.

- [ ] **Step 8: 정규식 파서 삭제**

```bash
git rm lib/parse-case.ts
```

- [ ] **Step 9: 타입 검사**

Run: `npm run typecheck`
Expected: `JarimaegimPanel.tsx`에서 `parseCaseText`·`parsedKeys` 관련 오류. Task 14에서 고친다.

- [ ] **Step 10: 커밋**

이 시점에는 빌드가 깨져 있으므로 Task 14와 함께 커밋한다. 여기서는 커밋하지 않는다.

---

## Task 14: 스테퍼 4단계와 여력 화면

**Files:**
- Modify: `components/kb/JarimaegimPanel.tsx`

- [ ] **Step 1: 스테퍼 교체**

`components/kb/JarimaegimPanel.tsx:13-16`을 다음으로 교체:

```tsx
// 금융 프로필은 관문이 아니라 1단계다. profile·capacity 가 ①, ask·confirm 이 ②에 매핑된다.
const STEPS: { id: FlowStep; label: string }[] = [
  { id: "profile", label: "자금" }, { id: "ask", label: "조건" },
  { id: "recommend", label: "입지" }, { id: "prescribe", label: "처방" }
];
const STEP_OF: Record<FlowStep, FlowStep> = {
  profile: "profile", capacity: "profile", ask: "ask", confirm: "ask",
  recommend: "recommend", prescribe: "prescribe"
};
```

`JarimaegimPanel` 함수 본문 첫 두 줄(26-27행)을 다음으로 교체:

```tsx
  const stepIndex = Math.max(0, STEPS.findIndex((step) => step.id === STEP_OF[flow.step]));
```

그리고 34-38행의 조건부 스테퍼(`{onGate ? ... : ...}`)를 다음 한 덩어리로 교체:

```tsx
    <ol className="kb-stepper">{STEPS.map((step, index) => <li key={step.id} data-state={index < stepIndex ? "done" : index === stepIndex ? "current" : "todo"}>
      <span aria-hidden="true">{index < stepIndex ? <Check /> : index + 1}</span>{step.label}
    </li>)}</ol>
```

41행 아래(`{flow.step === "profile" && <ProfileStep flow={flow} />}` 다음)에 추가:

```tsx
      {flow.step === "capacity" && <CapacityStep flow={flow} />}
```

- [ ] **Step 2: `ProfileStep` 버튼 문구와 안내 수정**

89행의 확정 버튼을 다음으로 교체:

```tsx
    <button className="kb-primary" onClick={flow.confirmProfile} disabled={!ready}>확정하고 조달 여력 보기 <ArrowRight aria-hidden="true" /></button>
```

101행의 안내 문구를 다음으로 교체:

```tsx
    <p className="kb-note"><Info aria-hidden="true" />업종 · 자치구 · 희망 임대조건은 마이데이터에 없습니다. 조달 여력을 확인한 뒤 다음 단계에서 받습니다.</p>
```

- [ ] **Step 3: `CapacityStep` 추가**

`ProfileBadge` 함수 **아래**에 추가:

```tsx
/** 1단계의 완결점. 자금을 입력한 대가로 "얼마까지 가능한가"를 돌려준다.
 *  권장 조달선은 여기서 내지 않는다 — 스트레스 테스트가 업종과 월 고정비를 요구하기 때문이고,
 *  그 사실을 빈칸이 아니라 문장으로 말하는 것이 2단계로 넘어가는 동기가 된다. */
function CapacityStep({ flow }: { flow: Jarimaegim }) {
  const { capacity, capacityState } = flow;
  const demo = capacity?.parameter_status === "DEMO";
  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>확정하신 자금으로 <strong>지금 검토할 수 있는 규모</strong>를 계산했습니다. 여기까지가 1단계입니다.</p></div>

    {capacityState === "loading" && <div className="kb-skeletons">{[0, 1].map((row) => <div key={row} className="kb-skeleton" />)}</div>}

    {capacityState === "error" && <div className="kb-empty">
      <AlertCircle aria-hidden="true" /><strong>조달 여력을 계산하지 못했습니다</strong>
      <p>연결 상태를 확인한 뒤 다시 시도해 주세요. 조건 입력은 그대로 진행할 수 있습니다.</p>
      <button className="kb-ghost" onClick={() => flow.loadCapacity(flow.profile)}><RefreshCw aria-hidden="true" /> 다시 계산</button>
    </div>}

    {capacity && capacity.status === "computed" && <section className="kb-capacity">
      {demo && <p className="kb-capacity-demo"><span className="demo-badge">시연용</span>미검증 시연용 제도 파라미터로 계산했습니다. 실제 심사 결과가 아닙니다.</p>}
      <ul className="kb-capacity-lines">
        <li><span>자기자본선</span><strong>{formatKrw(capacity.equity_line_krw)}</strong><small>차입 없이 지금 쓸 수 있는 규모</small></li>
        <li><span>차입 여력</span><strong>{formatKrw(capacity.borrowing_headroom_krw)}</strong><small>보증·정책자금 한도에서 기존 대출 잔액을 뺀 값</small></li>
        <li data-lead="true"><span>최대 조달선</span><strong>{formatKrw(capacity.maximum_line_krw)}</strong><small>신용평가·보증 심사 전 추정치이며 확정 한도가 아닙니다</small></li>
      </ul>
      {capacity.borrowing_headroom_krw === 0 && flow.profile.existing_debt_krw > 0 && <p className="kb-note"><Info aria-hidden="true" />기존 대출 잔액이 한도를 모두 소진해 추가 차입 여력이 없습니다. 최대 조달선이 자기자본선과 같습니다.</p>}
      <div className="kb-capacity-locked">
        <LockKeyhole aria-hidden="true" />
        <div><strong>권장 조달선은 아직 계산하지 않았습니다</strong><p>{capacity.recommended_line_pending}</p></div>
      </div>
      {/* ProvenanceBar 는 한계 문구를 접어 두므로, 사용자가 반드시 봐야 하는 사실은 위처럼 펼쳐 둔다. */}
      {capacity.provenance && <ProvenanceBar data={capacity.provenance} />}
    </section>}

    {capacity && capacity.status === "integration_pending" && <p className="kb-note"><Info aria-hidden="true" />{capacity.message}</p>}

    <button className="kb-primary" onClick={() => flow.setStep("ask")}>조건 입력으로 <ArrowRight aria-hidden="true" /></button>
    <button className="kb-ghost" onClick={() => flow.setStep("profile")}>금액 고치기</button>
  </div>;
}
```

- [ ] **Step 4: 타입 검사**

Run: `npm run typecheck`
Expected: `ConfirmStep`/`AskStep`의 `parsedKeys`·`parseCaseText` 오류만 남는다. Task 15에서 고친다.

---

## Task 15: 확인 화면 재작성

**Files:**
- Modify: `components/kb/JarimaegimPanel.tsx` (`AskStep`, `ConfirmStep`)

- [ ] **Step 1: import 정리**

`components/kb/JarimaegimPanel.tsx:6`의 `import { parseCaseText } from "@/lib/parse-case";`를 삭제한다.

5행의 `lucide-react` import 목록에 `Quote`를 더한다(인용 표시용).

7행 타입 import에 `ConditionKey` 를 더한다:

```tsx
import type { AnalysisResult, CaseInput, ConditionKey, FundingBandResult } from "@/lib/types";
```

- [ ] **Step 2: `AskStep` 교체**

120-134행의 `AskStep` 전체를 다음으로 교체:

```tsx
const EXAMPLES = [
  "마포구에서 카페 준비 중이고 월세는 300 정도 생각해요",
  "성동구에 2호점 낼 자리 찾고 있어요. 임대료 부담이 제일 걱정이에요",
  "관악구 분식점 자리요. 처음 창업이라 안정적인 곳이면 좋겠어요"
];

function AskStep({ flow }: { flow: Jarimaegim }) {
  const [text, setText] = useState(flow.interpretText);
  const busy = flow.busy === "interpret";
  const submit = () => { const value = text.trim(); if (value && !busy) void flow.interpret(value); };
  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>어떤 업종으로 서울 어디에 자리를 잡을지, 희망 월세까지 편하게 말씀해 주세요. 말씀하신 내용을 조건으로 정리해 확인받겠습니다.</p></div>
    <label className="kb-field kb-field-block"><span>상황 설명</span>
      <textarea rows={3} value={text} onChange={(event) => setText(event.target.value)} placeholder="예: 마포구에서 카페 준비 중이고 월세는 300 정도 생각해요" disabled={busy}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} />
    </label>
    <button className="kb-primary" onClick={submit} disabled={!text.trim() || busy}>{busy ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}조건으로 정리하기 <ArrowRight aria-hidden="true" /></button>
    <div className="kb-examples"><span>이렇게 말씀해 보세요</span>{EXAMPLES.map((example) => <button key={example} onClick={() => setText(example)} disabled={busy}>{example}</button>)}</div>
    <button className="kb-ghost" onClick={flow.startManual} disabled={busy}>직접 입력으로 시작 <ChevronRight aria-hidden="true" /></button>
  </div>;
}
```

17행의 기존 `const EXAMPLES = [...]` 선언을 삭제한다(위에서 새로 선언했다).

18-23행의 `// 확인 화면이 물을 수 있는 전부...` 주석과 `type AskKey`·`const ASK_FIELDS` 선언도
삭제한다 — Task 15 Step 3의 `ConfirmStep` 블록이 같은 이름을 다시 선언하므로, 두면
`Cannot redeclare block-scoped variable` 로 빌드가 깨진다.

- [ ] **Step 3: `ConfirmStep` 교체**

136-198행의 `ConfirmStep` 전체를 다음으로 교체:

```tsx
// 확인 화면이 한 줄씩 보여주는 조건 전부. 순서가 화면 순서다.
const CONFIRM_ROWS: { key: ConditionKey; label: string }[] = [
  { key: "industry", label: "업종" }, { key: "district", label: "자치구" },
  { key: "monthly_rent_krw", label: "희망 월세" }, { key: "business_stage", label: "사업단계" },
  { key: "startup_type", label: "창업형태" }, { key: "priority", label: "우선순위" }
];

/** 답이 후보를 바꾸는 항목만 비었을 때 묻는다. 최대 3을 넘지 않는다. */
type AskKey = "industry" | "monthly_rent_krw";
const ASK_FIELDS: { key: AskKey; label: string; note: string }[] = [
  { key: "industry", label: "업종", note: "검색 질의어와 업종 파라미터를 정합니다" },
  { key: "monthly_rent_krw", label: "희망 월세", note: "권장 조달선과 목표 매출을 정합니다" }
];

/** "이 조건이 맞나요?" — 값과 함께 무엇에서 그렇게 읽었는지를 같은 줄에 놓는다.
 *  금융 프로필 칩은 여기 없다. 자금은 1단계에서 끝났고 상단 배지가 요약과 수정 경로를 맡는다. */
function ConfirmStep({ flow }: { flow: Jarimaegim }) {
  const { form, bandForm, proposal, edited, setField, setBandField } = flow;
  const [editing, setEditing] = useState(false);
  const filled = (key: AskKey) => key === "industry" ? Boolean(form.industry.trim()) : bandForm.monthly_rent_krw > 0;
  const blanks = ASK_FIELDS.filter((ask) => !filled(ask.key)).map((ask) => ask.key);
  // 질문은 답이 들어오는 순간 사라지면 안 된다. 목록을 값에서 그대로 유도하면 이 필드를 그린 조건이
  // 첫 입력에 곧바로 거짓이 되어 입력 중인 필드가 스스로 언마운트된다 — 스피너 위로 버튼 한 번에
  // 10만 원이 확정되고 타이핑은 첫 글자만 남는다. 그래서 이 화면에 있는 동안 질문은 더해지기만 한다.
  // (조건 고치기에서 값을 다시 비우면 그때 새로 붙는다. 답을 지웠는데 물음이 없으면 안 되기 때문이다.)
  const [asked, setAsked] = useState<AskKey[]>(blanks);
  if (blanks.some((key) => !asked.includes(key))) setAsked(ASK_FIELDS.map((ask) => ask.key).filter((key) => asked.includes(key) || blanks.includes(key)));
  const asks = ASK_FIELDS.filter((ask) => asked.includes(ask.key));
  const ready = blanks.length === 0;

  const shown = (key: ConditionKey): string => {
    if (key === "monthly_rent_krw") return bandForm.monthly_rent_krw > 0 ? formatKrw(bandForm.monthly_rent_krw) : "—";
    if (key === "industry") return form.industry.trim() || "—";
    if (key === "district") return form.district;
    if (key === "business_stage") return STAGE_LABELS[form.business_stage];
    if (key === "startup_type") return TYPE_LABELS[form.startup_type];
    return PRIORITY_LABELS[form.priority];
  };
  /** 출처는 네 가지다. 사용자가 고쳤으면 그것이 이기고, 아니면 제안이 어디서 왔는지를 따른다. */
  const source = (key: ConditionKey): string => {
    if (edited.has(key)) return "직접 입력";
    const field = proposal?.fields[key];
    if (!field || field.value === null) return "기본값";
    return proposal?.source === "AI" ? "AI 추론" : "규칙 추출";
  };
  const evidence = (key: ConditionKey): string | null => edited.has(key) ? null : proposal?.fields[key]?.evidence ?? null;

  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>{blanks.length > 0
      ? <>말씀을 이렇게 읽었습니다. <strong>{blanks.length}개</strong>만 더 알려주시면 바로 찾아드릴게요.</>
      : <><strong>이 조건이 맞나요?</strong> 맞으면 이대로 후보를 찾고, 다르면 고쳐 주세요.</>}</p></div>

    <section className="kb-condcard">
      <h3><Check aria-hidden="true" />이 조건이 맞나요?</h3>
      <ul className="kb-condrows">{CONFIRM_ROWS.map((row) => <li key={row.key}>
        <span className="kb-condrow-label">{row.label}</span>
        <strong className="kb-condrow-value">{shown(row.key)}</strong>
        <span className="kb-condrow-evidence">{evidence(row.key)
          ? <><Quote aria-hidden="true" />{evidence(row.key)}</>
          : <em>—</em>}</span>
        <small className="kb-condrow-source">{source(row.key)}</small>
      </li>)}</ul>
    </section>

    {asks.length > 0 && <section className="kb-askbox">
      <header><span>더 필요한 것</span><small>{asks.length} / 최대 3</small></header>
      {asks.map((ask) => <label key={ask.key} className="kb-field" data-done={filled(ask.key) ? "true" : undefined}>
        <span>{ask.label}<small>{ask.note}</small></span>
        {ask.key === "industry"
          ? <input value={form.industry} onChange={(event) => setField("industry", event.target.value)} placeholder="예: 카페" />
          : <input type="number" min="0" step="100000" inputMode="numeric" value={bandForm.monthly_rent_krw || ""}
              onChange={(event) => setBandField("monthly_rent_krw", Math.max(0, Number(event.target.value)))} placeholder="0" />}
        {ask.key === "monthly_rent_krw" && <em>{bandForm.monthly_rent_krw > 0 ? formatKrw(bandForm.monthly_rent_krw) : "원"}</em>}
      </label>)}
      <p className="kb-note"><Info aria-hidden="true" />평수·보증금·권리금은 후보를 바꾸지 않으므로 묻지 않습니다. 다음 화면의 <strong>정밀하게 맞추기</strong>에서 언제든 넣을 수 있습니다.</p>
    </section>}

    <div className="kb-disclosure" data-open={editing}>
      <button onClick={() => setEditing(!editing)}><span>아니요, 고칠게요</span><small>업종 · 자치구 · 사업단계 · 창업형태 · 우선순위 <ChevronRight aria-hidden="true" /></small></button>
      {editing && <div className="kb-disclosure-body">
        <label className="kb-field"><span>업종</span><input value={form.industry} onChange={(event) => setField("industry", event.target.value)} placeholder="예: 카페" /></label>
        <label className="kb-field"><span>자치구</span><select value={form.district} onChange={(event) => setField("district", event.target.value)}>{SEOUL_DISTRICTS.map((district) => <option key={district} value={district}>{district}</option>)}</select></label>
        <ChipRow label="사업단계" value={form.business_stage} options={STAGE_LABELS} onSelect={(value) => setField("business_stage", value as CaseInput["business_stage"])} />
        <ChipRow label="창업형태" value={form.startup_type} options={TYPE_LABELS} onSelect={(value) => setField("startup_type", value as CaseInput["startup_type"])} />
        <ChipRow label="우선순위" value={form.priority} options={PRIORITY_LABELS} onSelect={(value) => setField("priority", value as CaseInput["priority"])} />
      </div>}
    </div>

    <button className="kb-primary" onClick={flow.start} disabled={!ready || flow.busy === "case"}>{flow.busy === "case" ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}네, 맞아요 · 이 조건으로 입지 찾기</button>
    <button className="kb-ghost" onClick={() => flow.setStep("ask")}><RotateCcw aria-hidden="true" /> 다시 말할게요</button>
    <p className="kb-note"><Check aria-hidden="true" />여기가 마지막 입력 화면입니다. 다음은 곧바로 후보 목록이고, 조달 금액 결정은 후보를 본 뒤에 합니다.</p>
  </div>;
}
```

- [ ] **Step 4: 타입 검사와 린트**

Run: `npm run typecheck && npm run lint`
Expected: 통과

- [ ] **Step 5: 커밋**

```bash
git add lib/use-jarimaegim.ts components/kb/JarimaegimPanel.tsx
git commit -m "feat(flow): finish 자금 with a capacity readout, then confirm read-back conditions"
```

---

## Task 16: 스타일

**Files:**
- Modify: `app/globals.css`

- [ ] **Step 1: 신규 클래스 추가**

`app/globals.css` 맨 아래에 추가:

쓰는 변수는 전부 `:root`에 이미 있는 것들이다 — `--kb-line`(#e0e0e0), `--kb-sub`(#515a68,
보조 텍스트), `--kb-mute`(#8b95a1, 더 흐린 텍스트), `--kb-blue-soft`(#eef3ff),
`--kb-brown-deep`(#26221f). `--kb-surface`·`--kb-muted` 같은 이름은 이 저장소에 없으므로 쓰지 않는다.

```css
.kb-capacity{display:flex;flex-direction:column;gap:12px;padding:14px;border:1px solid var(--kb-line);border-radius:12px;background:#fff}
.kb-capacity-demo{display:flex;align-items:center;gap:8px;margin:0;font-size:12px;color:var(--kb-sub)}
.kb-capacity-lines{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}
.kb-capacity-lines li{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding-bottom:10px;border-bottom:1px dashed var(--kb-line)}
.kb-capacity-lines li:last-child{border-bottom:0;padding-bottom:0}
.kb-capacity-lines li span{font-size:13px;color:var(--kb-sub)}
.kb-capacity-lines li strong{font-size:16px;text-align:right}
.kb-capacity-lines li small{grid-column:1/-1;font-size:11px;color:var(--kb-mute);line-height:1.5}
.kb-capacity-lines li[data-lead="true"] strong{font-size:20px;color:var(--kb-brown-deep)}
.kb-capacity-locked{display:flex;gap:10px;padding:12px;border-radius:10px;background:var(--kb-blue-soft)}
.kb-capacity-locked svg{width:16px;height:16px;flex:0 0 16px;margin-top:2px}
.kb-capacity-locked strong{display:block;font-size:13px}
.kb-capacity-locked p{margin:4px 0 0;font-size:12px;color:var(--kb-sub);line-height:1.6}
.kb-condrows{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:8px}
.kb-condrows li{display:grid;grid-template-columns:64px 1fr auto;gap:2px 8px;align-items:baseline;padding-bottom:8px;border-bottom:1px dashed var(--kb-line)}
.kb-condrows li:last-child{border-bottom:0;padding-bottom:0}
.kb-condrow-label{font-size:12px;color:var(--kb-sub)}
.kb-condrow-value{font-size:14px}
.kb-condrow-source{font-size:11px;color:var(--kb-mute);white-space:nowrap}
.kb-condrow-evidence{grid-column:2/-1;display:flex;align-items:center;gap:4px;font-size:11px;color:var(--kb-mute);line-height:1.5}
.kb-condrow-evidence svg{width:11px;height:11px;flex:0 0 11px}
.kb-condrow-evidence em{font-style:normal;opacity:.5}
```

- [ ] **Step 2: 빌드 확인**

Run: `npm run build`
Expected: 성공

- [ ] **Step 3: 커밋**

```bash
git add app/globals.css
git commit -m "style(kb): dress the capacity readout and the condition read-back rows"
```

---

## Task 17: 흐름 검증 스크립트 갱신

**Files:**
- Modify: `scripts/flow-check.mjs:162-225`

- [ ] **Step 1: KB 구간 교체**

`scripts/flow-check.mjs`의 162행 주석부터 207행(`};` — `kbFlow` 객체 닫는 줄)까지를 다음으로 교체:

```js
// KB 셸의 새 흐름 — ① 자금(프로필 → 여력) → ② 조건(발화 → 확인) → ③ 입지. 세션을 섞지 않도록 새 컨텍스트에서 돈다.
const kbContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const kb = await kbContext.newPage();
kb.on("pageerror", error => errors.push(`kb-page:${error.message}`));
await kb.goto(`${base}/kb`, { waitUntil: "networkidle" });

// 마이데이터는 게이트 off 가 기본이다. 잠긴 사실을 숨기지 않고 수동 입력이 같은 항목을 채워야 한다.
const mydataGate = {
  buttonDisabled: await kb.getByRole("button", { name: "마이데이터 연결하고 자동 입력" }).isDisabled(),
  lockExplained: await kb.getByText("마이데이터 연동은 아직 열려 있지 않습니다").isVisible(),
  manualAdapter: await kb.locator(".kb-profile-form input").count() === 3
};

await kb.locator(".kb-profile-form input").nth(0).fill("100000000");
await kb.getByRole("button", { name: /확정하고 조달 여력 보기/ }).click();
await kb.waitForSelector(".kb-capacity, .kb-step > .kb-note, .kb-empty", { timeout: 20000 });

// ① 자금은 여력을 돌려주고 끝난다. 값을 냈다면 시연용 파라미터임을 반드시 밝혀야 한다.
const capacityShown = await kb.locator(".kb-capacity").count() > 0;
const capacityStep = {
  // 계산했거나, 못 했으면 왜 못 했는지를 말했거나 — 둘 중 하나여야 한다.
  resolved: capacityShown || await kb.locator(".kb-step > .kb-note").count() > 0,
  demoLabelled: !capacityShown || await kb.locator(".kb-capacity .demo-badge").count() > 0,
  // 권장 조달선을 여기서 지어내지 않고 잠금 사유를 밝혀야 한다.
  recommendedDeferred: !capacityShown || await kb.locator(".kb-capacity-locked").count() > 0,
  // 자금 화면에 조건 입력이 섞이면 단계 분리가 무너진 것이다.
  noConditionInputs: await kb.locator(".kb-condcard, .kb-askbox").count() === 0
};

await kb.getByRole("button", { name: /^조건 입력으로/ }).click();
await kb.locator(".kb-field-block textarea").fill("강남구에서 카페를 준비 중이고 월세는 250 정도 생각해요");
await kb.getByRole("button", { name: /조건으로 정리하기/ }).click();
await kb.waitForSelector(".kb-condrows", { timeout: 20000 });

// ② 조건은 발화를 읽어 되돌려주고 확인을 받는다. 금융 입력은 이 화면에 없어야 한다.
const rows = await kb.locator(".kb-condrows li").allTextContents();
const conditionStep = {
  rowCount: rows.length,
  // "준비 중이에요"의 "중"이 중구로 새지 않아야 한다.
  districtParsed: rows.some(row => row.includes("자치구") && row.includes("강남구")),
  rentParsed: rows.some(row => row.includes("희망 월세") && row.includes("250")),
  // 키가 없는 환경에서는 규칙 추출로 내려가되 출처를 숨기지 않아야 한다.
  sourceLabelled: rows.some(row => row.includes("AI 추론") || row.includes("규칙 추출")),
  // 추출한 값에는 사용자 발화 인용이 붙어야 한다.
  evidenceShown: await kb.locator(".kb-condrow-evidence svg").count() > 0,
  // 단계 분리 회귀 방지 — 자금 항목이 조건 화면의 입력으로 돌아오면 안 된다.
  noProfileChips: !rows.some(row => row.includes("자기자본") || row.includes("기존부채") || row.includes("월 고정지출"))
};

const askCount = await kb.locator(".kb-askbox .kb-field").count();
if (askCount > 0) await kb.locator(".kb-askbox input").first().fill("2500000");
await kb.getByRole("button", { name: /네, 맞아요/ }).click();
await kb.waitForSelector(".kb-candidates li, .kb-empty", { timeout: 30000 });

const stepperLabels = await kb.locator(".kb-stepper li").allTextContents();
const bandBannerShown = await kb.locator(".kb-band-banner").count() > 0;
const kbFlow = {
  stepCount: stepperLabels.length,
  // 자금이 별도 단계로 서 있어야 하고, 근거는 여전히 단계가 아니어야 한다.
  stepsAreFour: stepperLabels.length === 4
    && stepperLabels.some(label => label.includes("자금"))
    && !stepperLabels.some(label => label.includes("근거")),
  candidates: await kb.locator(".kb-candidates li").count(),
  tuningInPlace: await kb.getByRole("button", { name: /정밀하게 맞추기/ }).count() > 0,
  // 제도 파라미터가 미등록이면 밴드를 지어내지 않고 사유를 밝혀야 한다.
  // 진행 오버레이에도 같은 문구가 남으므로 패널 본문 쪽 고지만 센다.
  bandSafeState: bandBannerShown || await kb.locator(".kb-step > .kb-note", { hasText: "파라미터가 아직 등록되지" }).count() > 0
};
```

- [ ] **Step 2: 출력과 종료 코드 갱신**

217행의 `const result = {...}` 줄에서 `mydataGate, conditionStep,`을 `mydataGate, capacityStep, conditionStep,`으로 바꾼다.

221행의 `if (!kbFlow.gateVisible || !kbFlow.stepsAreThree || ...)` 줄을 다음으로 교체:

```js
if (!kbFlow.stepsAreFour || !kbFlow.tuningInPlace || !kbFlow.bandSafeState || !kbFlow.evidenceInline) process.exitCode = 1;
```

223행의 `if (conditionStep.askCount !== 1 || ...)` 줄을 다음 두 줄로 교체:

```js
if (!capacityStep.resolved || !capacityStep.demoLabelled || !capacityStep.recommendedDeferred || !capacityStep.noConditionInputs) process.exitCode = 1;
if (conditionStep.rowCount !== 6 || !conditionStep.districtParsed || !conditionStep.sourceLabelled || !conditionStep.evidenceShown || !conditionStep.noProfileChips) process.exitCode = 1;
```

- [ ] **Step 3: 실행**

Run: `npm run dev` (별도 터미널) 후 `node scripts/flow-check.mjs`
Expected: exit 0. `capacityStep`과 `conditionStep`의 모든 불리언이 `true`.

실패하면 출력된 JSON에서 어느 키가 `false`인지 보고 해당 Task로 돌아간다.

- [ ] **Step 4: 커밋**

```bash
git add scripts/flow-check.mjs
git commit -m "test(flow): assert the funding step stands alone and conditions read back with evidence"
```

---

## Task 18: 시각 검증과 최종 확인

**Files:**
- Modify: `scripts/visual-check.mjs`

- [ ] **Step 1: `capacity` 화면 스냅샷 추가**

`/kb`는 이미 `publicRoutes`에 있지만 프로필 화면까지만 찍는다. `scripts/visual-check.mjs`의
route 루프 안, `results.push({ viewport: viewport.name, route, ...geometry });` 줄 **바로 아래**에
추가한다:

```js
    // /kb 는 1단계 첫 화면(프로필)만 보여준다. 단계의 완결점인 조달 여력까지 밀어 한 장 더 찍는다.
    if (route === "/kb") {
      await page.locator(".kb-profile-form input").nth(0).fill("100000000");
      await page.getByRole("button", { name: /확정하고 조달 여력 보기/ }).click();
      await page.waitForSelector(".kb-capacity, .kb-step > .kb-note", { timeout: 20000 });
      const capacity = await page.evaluate(() => ({
        title: document.title,
        viewportWidth: document.documentElement.clientWidth,
        documentWidth: document.documentElement.scrollWidth,
        main: Boolean(document.querySelector("main")),
        horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
      }));
      await page.screenshot({ path: outputPath(`${viewport.name}-kb-capacity.png`), fullPage: true });
      results.push({ viewport: viewport.name, route: "/kb (조달 여력)", ...capacity });
    }
```

`main` 을 함께 재는 이유는 스크립트 마지막의 `failures` 필터가 `item.main === false` 를 실패로
세기 때문이다. 그 키를 빼면 `undefined` 가 되어 통과해 버린다.

- [ ] **Step 2: 실행**

Run: `node scripts/visual-check.mjs`
Expected: exit 0, `artifacts/visual/`에 `*-kb-capacity.png` 5장 생성

- [ ] **Step 3: 전체 검증**

```bash
npm run lint
npm run typecheck
npm run build
npm run api:check
cd backend && .venv/bin/python -m pytest -m "not slow" -q && cd ..
node scripts/flow-check.mjs
```

Expected: 전부 통과, 마지막 명령 exit 0

- [ ] **Step 4: `parse-case.ts` 잔재 확인**

Run: `grep -rn "parse-case\|parseCaseText\|parsedKeys" app components lib scripts`
Expected: 결과 없음

- [ ] **Step 5: 커밋**

```bash
git add scripts/visual-check.mjs
git commit -m "test(visual): snapshot the capacity readout across viewports"
```

---

## Task 19: 문서 갱신

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 흐름 설명 갱신**

`CLAUDE.md`의 "Frontend" 절에서 스테이지 목록을 설명하는 문장에 자금 단계 분리를 반영하고,
"Non-negotiable product rules" 절 1번 뒤에 다음 문단을 추가:

```markdown
`config/policy-params.json`의 각 항목은 `verified: true | false`를 명시한다. `false`인 값으로
계산한 결과는 `parameter_status: "DEMO"`와 `unverified_params`를 응답에 실어 보내고, UI가
`시연용` 배지를 끌 수 없게 붙인다. 값을 숨기는 대신 값의 성격을 밝히는 방식이며, 시연용 매물
데이터(`data/listings.seoul.json`)가 `demo-badge`를 다는 것과 같은 취급이다. 새 파라미터를
등록할 때 `verified`를 빠뜨리면 `test_shipped_entries_state_verification_explicitly`가 막는다.
```

같은 절 4번 끝에 다음 문장을 추가:

```markdown
`POST /api/v1/conditions/interpret`도 같은 규칙 아래 있다. 모델은 사용자 발화의 어느 구간이
어떤 조건을 말하는지 지목할 뿐이고, 금액 환산을 포함한 모든 산술은 `condition_parse.amount_from`이
한다. `condition_interpret.sanitize`가 evidence를 사용자 원문의 부분문자열로 검증해 통과하지
못한 필드를 버리므로, 프롬프트를 어긴 값은 응답에 남지 않는다.
```

- [ ] **Step 2: 명령 목록 확인**

`CLAUDE.md`의 `npm run api:test` 설명에 있는 테스트 개수(191)를 실제 개수로 갱신한다.

Run: `cd backend && .venv/bin/python -m pytest -m "not slow" -q 2>&1 | tail -3`

- [ ] **Step 3: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: record the funding step split and the condition interpretation gate"
```

---

## 완료 기준

- [ ] 스테퍼가 `자금 · 조건 · 입지 · 처방` 4칸이다
- [ ] 프로필 확정이 조달 여력 화면으로 이어지고, 최대 조달선이 실제 금액으로 나온다
- [ ] 여력 화면이 권장 조달선을 빈칸이 아니라 잠금 사유로 표시한다
- [ ] 밴드·여력 응답이 시연용 파라미터를 썼을 때 `DEMO`를 싣고 UI가 배지를 붙인다
- [ ] 조건 화면에 자기자본·기존부채·월 고정지출 입력이 없다
- [ ] 발화가 서버에서 해석되고, 확인 화면이 값·인용·출처를 한 줄로 보여준다
- [ ] 원문에 없는 evidence를 단 필드는 응답에 남지 않는다(pytest로 단언됨)
- [ ] 키 없는 환경에서 `source: "RULE"`로 끝까지 진행된다
- [ ] `lib/parse-case.ts`가 저장소에 없다
- [ ] `npm run lint && npm run typecheck && npm run build && npm run api:test && node scripts/flow-check.mjs` 전부 통과
