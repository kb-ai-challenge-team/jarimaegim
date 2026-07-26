# D0 — 조달 밴드 3중선 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사용자 조건만으로 조달 밴드 3중선(자기자본선·권장 조달선·최대 조달선)과 손익분기선을 산출하는 `POST /api/v1/funding-bands`를 구현한다. 외부 데이터 원천은 사용하지 않는다.

**Architecture:** 순수 산술 서비스 `backend/app/funding.py`가 계산하고, 계산에 필요한 제도 파라미터는 `config/policy-params.json`에서 로드한다. **파라미터 값이 등록되지 않으면 계산하지 않고 `integration_pending`을 반환한다** — 금리·인테리어 단가를 코드가 지어내는 것은 부록 A 불변조건 1 위반이다. LLM은 이 경로에 전혀 관여하지 않는다.

**Tech Stack:** FastAPI · pydantic v2 (`model_validator(mode="after")`) · pytest (신규 도입) · TypeScript 미러링(`lib/types.ts`)

---

## 스펙 대응

| 스펙 절 | 이 계획에서 |
|---|---|
| §3.3 제도 파라미터 | Task 2 — `config/policy-params.json` + 로더. 값 미등록 시 `integration_pending` |
| §3.4 사용자 입력으로만 얻는 값 | Task 5 — `FundingBandInput` |
| §3.6 D0 | 전체 |
| §3.7 미확보 시 동작 계약 | Task 2·6·8 |
| §4.1 `BandLine` / `BreakEven` | Task 5 |
| §4.2 불변조건 강제 (항목 1) | Task 5 — `MAXIMUM → is_estimate` 강제 |
| §7 가드 3 (미검증 → 비활성) | Task 8 — `GET /status`에 축별 노출 |
| §8 API 계약 | Task 6 — `POST /api/v1/funding-bands` |
| §9 완료 정의 | Task 3·4·9 |

**D0 범위 밖(이 계획에서 하지 않음):** 후보 생성 변경, `location.*` 4축, 지원금 매칭(DS-07/08), KB 창업자금 상품, 타이밍팀, 밴드별 상권 수(DS-09), 가드 1·2, `AnalysisRepository`.

### 알려진 모델 편차 (실행자가 반드시 알아야 함)

제안서 PDF 예시는 밴드를 늘릴수록 **현금소진이 짧아지는** 것으로 그려져 있다. 그 그림은 "밴드를 늘려 더 비싼 상권으로 간다"는 효과를 전제하며, 그것은 DS-09(상권 임대 수준)가 있어야 계산된다.

**D0에서는 필요자금이 사용자 입력으로 고정되므로 밴드를 늘리면 현금소진이 길어지고 월 상환이 늘어난다.** 이것이 D0 모델의 정직한 답이다. 트레이드오프는 여전히 존재한다(상환 부담 ↔ 현금 여유). 이 방향을 뒤집으려고 계산을 조작하지 말 것.

### 권장 조달선의 판정 기준

현금소진 기준으로는 차입을 늘릴수록 항상 유리해져 권장선이 최대선과 같아진다(현금을 더 들고 있게 되므로). 따라서 권장 조달선은 **상환 부담률**로 판정한다.

```
목표 월매출        = 월고정지출_총액 / (1 − 원가율 − 인건비율)
스트레스 월매출     = 목표 월매출 × (1 − 매출하락률)
상환 부담률        = 월 상환액 / 스트레스 월매출
권장 조달선        = 상환 부담률 ≤ 부담률 상한 을 만족하는 최대 조달액
```

부담률은 차입액에 대해 단조증가하므로 이분 탐색이 성립한다. `월고정지출_총액`은 상환액을 포함하므로 차입이 늘면 목표매출도 함께 오른다.

---

## 파일 구조

| 파일 | 책임 |
|---|---|
| `config/policy-params.json` (생성) | 제도 파라미터. 값은 `null`로 커밋하고 출처·기준일과 함께 등록 |
| `backend/app/policy_params.py` (생성) | 파라미터 로드·검증. 누락 키 목록 산출 |
| `backend/app/funding.py` (생성) | 순수 산술 — 연금 상환액, 손익분기, 밴드 3종 |
| `backend/app/models.py` (수정) | `FundingBand` · `BandLine` · `BreakEven` · `FundingBandInput` · `FundingBandResult` |
| `backend/app/main.py` (수정) | `POST /api/v1/funding-bands`, `GET /status`에 축 노출 |
| `backend/tests/` (생성) | pytest 스위트 |
| `lib/types.ts` (수정) | 위 모델 미러링 |
| `lib/api.ts` (수정) | `fundingBands()` |
| `backend/requirements.txt` · `package.json` (수정) | pytest 도입 |

---

## Task 1: pytest 인프라

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `package.json` (scripts)
- Create: `backend/pytest.ini`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/test_smoke.py`

- [ ] **Step 1: requirements에 pytest 추가**

`backend/requirements.txt`의 알파벳 순서를 유지해 `openai` 아래에 한 줄 추가한다.

```
pytest==8.4.2
```

- [ ] **Step 2: 설치**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
backend/.venv/bin/pip install -r backend/requirements.txt
```

기대: `Successfully installed pytest-8.4.2` (또는 이미 충족).

- [ ] **Step 3: pytest 설정 생성**

`backend/pytest.ini` — `app.*` import가 되도록 `backend/`를 rootdir로 잡는다.

```ini
[pytest]
testpaths = tests
pythonpath = .
addopts = -q
```

- [ ] **Step 4: 스모크 테스트 작성**

`backend/tests/__init__.py` — 빈 파일.

`backend/tests/test_smoke.py`:

```python
def test_app_imports():
    from app.main import app
    assert app.title == "자리매김 API"
```

- [ ] **Step 5: 실행해서 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo/backend" && ../backend/.venv/bin/python -m pytest
```

기대: `1 passed`.

- [ ] **Step 6: npm 스크립트 추가**

`package.json`의 `scripts`에서 `"api:check"` 바로 아래에 추가한다.

```json
"api:test": "cd backend && .venv/bin/python -m pytest",
```

- [ ] **Step 7: npm 경로로 재확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `1 passed`.

- [ ] **Step 8: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add backend/requirements.txt backend/pytest.ini backend/tests package.json
git commit -m "test: add pytest suite for the backend"
```

---

## Task 2: 제도 파라미터 파일과 로더

`config/policy-params.json`은 **값을 비워서 커밋한다.** 금리·인테리어 단가를 코드나 커밋된 설정이 임의로 정하면 부록 A 불변조건 1을 위반한다. 값은 출처와 기준일을 확인한 사람이 등록한다.

**Files:**
- Create: `config/policy-params.json`
- Create: `backend/app/policy_params.py`
- Create: `backend/tests/test_policy_params.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_policy_params.py`:

```python
import json
import pytest
from app.policy_params import PolicyParams

FULL = {
    "schema_version": 1,
    "entries": {
        "loan.annual_rate_percent": {"value": 4.5, "unit": "PERCENT", "source": "테스트", "as_of": "2026-07-01"},
        "loan.term_months": {"value": 60, "unit": "MONTHS", "source": "테스트", "as_of": "2026-07-01"},
        "loan.guarantee_ceiling_krw": {"value": 70000000, "unit": "KRW", "source": "테스트", "as_of": "2026-07-01"},
        "loan.policy_fund_ceiling_krw": {"value": 20000000, "unit": "KRW", "source": "테스트", "as_of": "2026-07-01"},
        "stress.revenue_drop_ratio": {"value": 0.2, "unit": "RATIO", "source": "테스트", "as_of": "2026-07-01"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "unit": "RATIO", "source": "테스트", "as_of": "2026-07-01"},
        "working_capital.months": {"value": 3, "unit": "MONTHS", "source": "테스트", "as_of": "2026-07-01"},
    },
    "industries": {
        "카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20, "fitout_krw_per_pyeong": 2500000,
                 "operating_days_per_month": 26, "source": "테스트", "as_of": "2026-07-01"}
    },
}


def test_missing_is_empty_when_everything_registered():
    params = PolicyParams(FULL)
    assert params.missing("카페") == []


def test_missing_lists_null_entries():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.annual_rate_percent"]["value"] = None
    params = PolicyParams(raw)
    assert params.missing("카페") == ["loan.annual_rate_percent"]


def test_missing_lists_unregistered_industry():
    params = PolicyParams(FULL)
    assert params.missing("치킨집") == ["industries.치킨집"]


def test_missing_lists_partial_industry_fields():
    raw = json.loads(json.dumps(FULL))
    del raw["industries"]["카페"]["labor_ratio"]
    params = PolicyParams(raw)
    assert params.missing("카페") == ["industries.카페.labor_ratio"]


def test_value_returns_registered_number():
    assert PolicyParams(FULL).value("loan.term_months") == 60


def test_value_raises_on_missing():
    raw = json.loads(json.dumps(FULL))
    raw["entries"]["loan.term_months"]["value"] = None
    with pytest.raises(KeyError):
        PolicyParams(raw).value("loan.term_months")


def test_industry_returns_field_map():
    assert PolicyParams(FULL).industry("카페")["cogs_ratio"] == 0.35


def test_shipped_config_has_no_registered_values():
    """커밋된 설정은 값이 비어 있어야 한다 — 임의 값 커밋 방지."""
    from pathlib import Path
    path = Path(__file__).resolve().parents[2] / "config" / "policy-params.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    params = PolicyParams(raw)
    assert params.missing("카페") != []
```

- [ ] **Step 2: 실패 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `ModuleNotFoundError: No module named 'app.policy_params'`.

- [ ] **Step 3: 설정 파일 생성**

`config/policy-params.json` — **모든 `value`가 `null`이고 `industries`가 비어 있다.**

```json
{
  "schema_version": 1,
  "updated_at": null,
  "note": "값은 출처와 기준일을 확인한 뒤 등록한다. null인 항목은 계산에 사용되지 않고 integration_pending을 유발한다.",
  "entries": {
    "loan.annual_rate_percent": { "value": null, "unit": "PERCENT", "source": null, "as_of": null },
    "loan.term_months": { "value": null, "unit": "MONTHS", "source": null, "as_of": null },
    "loan.guarantee_ceiling_krw": { "value": null, "unit": "KRW", "source": null, "as_of": null },
    "loan.policy_fund_ceiling_krw": { "value": null, "unit": "KRW", "source": null, "as_of": null },
    "stress.revenue_drop_ratio": { "value": null, "unit": "RATIO", "source": null, "as_of": null },
    "stress.repayment_burden_cap_ratio": { "value": null, "unit": "RATIO", "source": null, "as_of": null },
    "working_capital.months": { "value": null, "unit": "MONTHS", "source": null, "as_of": null }
  },
  "industries": {}
}
```

- [ ] **Step 4: 로더 구현**

`backend/app/policy_params.py`:

```python
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

REQUIRED_ENTRIES = ("loan.annual_rate_percent", "loan.term_months", "loan.guarantee_ceiling_krw",
                    "loan.policy_fund_ceiling_krw", "stress.revenue_drop_ratio",
                    "stress.repayment_burden_cap_ratio", "working_capital.months")
REQUIRED_INDUSTRY_FIELDS = ("cogs_ratio", "labor_ratio", "fitout_krw_per_pyeong", "operating_days_per_month")


class PolicyParams:
    """제도·업종 파라미터. 등록되지 않은 값은 절대 추정하지 않고 누락으로 보고한다."""

    def __init__(self, raw: dict[str, Any]):
        self._entries = raw.get("entries") or {}
        self._industries = raw.get("industries") or {}
        self.updated_at = raw.get("updated_at")

    @classmethod
    def load(cls, path: str | Path) -> PolicyParams:
        target = Path(path)
        if not target.is_absolute() and not target.exists():
            # uvicorn은 저장소 루트에서, pytest는 backend/에서 실행되므로 루트 기준으로도 찾는다.
            target = Path(__file__).resolve().parents[2] / target
        if not target.exists():
            return cls({})
        return cls(json.loads(target.read_text(encoding="utf-8")))

    def missing(self, industry: str) -> list[str]:
        gaps = [key for key in REQUIRED_ENTRIES
                if (self._entries.get(key) or {}).get("value") is None]
        profile = self._industries.get(industry)
        if not profile:
            gaps.append(f"industries.{industry}")
            return gaps
        gaps.extend(f"industries.{industry}.{field}" for field in REQUIRED_INDUSTRY_FIELDS
                    if profile.get(field) is None)
        return gaps

    def value(self, key: str) -> float:
        entry = self._entries.get(key) or {}
        if entry.get("value") is None:
            raise KeyError(key)
        return float(entry["value"])

    def industry(self, name: str) -> dict[str, Any]:
        profile = self._industries.get(name)
        if not profile:
            raise KeyError(f"industries.{name}")
        return profile

    def sources(self, industry: str) -> list[str]:
        labels = {str((self._entries.get(key) or {}).get("source")) for key in REQUIRED_ENTRIES}
        profile = self._industries.get(industry) or {}
        if profile.get("source"):
            labels.add(str(profile["source"]))
        return sorted(label for label in labels if label and label != "None")
```

- [ ] **Step 5: 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `9 passed`.

- [ ] **Step 6: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add config/policy-params.json backend/app/policy_params.py backend/tests/test_policy_params.py
git commit -m "feat: load institutional policy parameters without inventing values"
```

---

## Task 3: 순수 산술 — 상환액과 손익분기

**Files:**
- Create: `backend/app/funding.py`
- Create: `backend/tests/test_funding_math.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_funding_math.py`:

```python
import pytest
from app.funding import breakeven_monthly_revenue_krw, monthly_annuity_krw


def test_annuity_is_zero_for_zero_principal():
    assert monthly_annuity_krw(0, 4.5, 60) == 0


def test_annuity_is_straight_division_at_zero_rate():
    assert monthly_annuity_krw(60_000_000, 0.0, 60) == 1_000_000


def test_annuity_matches_standard_formula():
    # 4.5% / 60개월 / 4,500만원 → 원리금균등 상환액
    assert monthly_annuity_krw(45_000_000, 4.5, 60) == 838_935


def test_annuity_grows_with_principal():
    small = monthly_annuity_krw(30_000_000, 4.5, 60)
    large = monthly_annuity_krw(60_000_000, 4.5, 60)
    assert large > small


def test_annuity_rejects_non_positive_term():
    with pytest.raises(ValueError):
        monthly_annuity_krw(10_000_000, 4.5, 0)


def test_breakeven_divides_fixed_cost_by_contribution_margin():
    # 고정비 380만, 원가율 0.35, 인건비율 0.20 → 공헌이익률 0.45
    assert breakeven_monthly_revenue_krw(3_800_000, 0.35, 0.20) == 8_444_444


def test_breakeven_rejects_non_positive_margin():
    with pytest.raises(ValueError):
        breakeven_monthly_revenue_krw(3_800_000, 0.6, 0.4)


def test_breakeven_is_zero_when_no_fixed_cost():
    assert breakeven_monthly_revenue_krw(0, 0.35, 0.20) == 0
```

- [ ] **Step 2: 실패 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `ModuleNotFoundError: No module named 'app.funding'`.

- [ ] **Step 3: 구현**

`backend/app/funding.py` — 이 파일은 Task 4에서 이어서 채운다.

```python
from __future__ import annotations


def monthly_annuity_krw(principal_krw: int, annual_rate_percent: float, term_months: int) -> int:
    """원리금균등 월 상환액. 원 단위로 내림한다."""
    if term_months <= 0:
        raise ValueError("term_months must be positive")
    if principal_krw <= 0:
        return 0
    monthly_rate = float(annual_rate_percent) / 100.0 / 12.0
    if monthly_rate == 0:
        return int(principal_krw // term_months)
    factor = (1.0 + monthly_rate) ** term_months
    return int(principal_krw * monthly_rate * factor / (factor - 1.0))


def breakeven_monthly_revenue_krw(fixed_cost_krw: int, cogs_ratio: float, labor_ratio: float) -> int:
    """손익분기 월매출 = 고정비 / 공헌이익률. 공헌이익률이 0 이하면 성립하지 않는다."""
    contribution_margin = 1.0 - float(cogs_ratio) - float(labor_ratio)
    if contribution_margin <= 0:
        raise ValueError("contribution margin must be positive")
    if fixed_cost_krw <= 0:
        return 0
    return int(fixed_cost_krw / contribution_margin)
```

- [ ] **Step 4: 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `17 passed`. `test_annuity_matches_standard_formula`가 실패하면 **테스트의 기대값을 고치지 말고** 계산식을 검산하라. 정답은 `45000000 * r * (1+r)^60 / ((1+r)^60 - 1)`, `r = 0.045/12`.

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add backend/app/funding.py backend/tests/test_funding_math.py
git commit -m "feat: add annuity and break-even arithmetic"
```

---

## Task 4: 밴드 3종 산출

**Files:**
- Modify: `backend/app/funding.py` (Task 3에서 만든 파일에 추가)
- Create: `backend/tests/test_funding_bands.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_funding_bands.py`:

```python
import pytest
from app.funding import compute_bands
from app.policy_params import PolicyParams

PARAMS = PolicyParams({
    "schema_version": 1,
    "entries": {
        "loan.annual_rate_percent": {"value": 4.5},
        "loan.term_months": {"value": 60},
        "loan.guarantee_ceiling_krw": {"value": 70_000_000},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000},
        "stress.revenue_drop_ratio": {"value": 0.2},
        "stress.repayment_burden_cap_ratio": {"value": 0.1},
        "working_capital.months": {"value": 3},
    },
    "industries": {
        "카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20, "fitout_krw_per_pyeong": 2_500_000,
                 "operating_days_per_month": 26, "source": "테스트", "as_of": "2026-07-01"}
    },
})

BASE = dict(industry="카페", area_pyeong=15.0, deposit_krw=100_000_000, monthly_rent_krw=2_500_000,
            monthly_maintenance_krw=300_000, key_money_krw=0, fitout_krw=None,
            equity_krw=100_000_000, existing_debt_krw=0, other_monthly_fixed_krw=1_000_000)


def test_required_capital_sums_deposit_fitout_and_working_capital():
    out = compute_bands(PARAMS, **BASE)
    # 보증금 1억 + 인테리어 15평×250만 = 3,750만 + 운전자금 (250+30+100)만 × 3개월 = 1,140만
    assert out["required_capital_krw"] == 100_000_000 + 37_500_000 + 11_400_000


def test_explicit_fitout_overrides_the_industry_estimate():
    out = compute_bands(PARAMS, **{**BASE, "fitout_krw": 20_000_000})
    assert out["required_capital_krw"] == 100_000_000 + 20_000_000 + 11_400_000
    assert out["fitout_is_estimate"] is False


def test_fitout_from_industry_table_is_marked_as_estimate():
    assert compute_bands(PARAMS, **BASE)["fitout_is_estimate"] is True


def test_three_bands_are_returned_in_ascending_order():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert [item["band"] for item in bands] == ["EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"]
    assert bands[0]["ceiling_krw"] <= bands[1]["ceiling_krw"] <= bands[2]["ceiling_krw"]


def test_equity_only_band_has_no_loan_and_no_repayment():
    band = compute_bands(PARAMS, **BASE)["bands"][0]
    assert band["loan_krw"] == 0
    assert band["monthly_repayment_krw"] == 0
    assert band["stress_pass"] is True


def test_maximum_band_is_capped_by_guarantee_plus_policy_fund_less_existing_debt():
    out = compute_bands(PARAMS, **{**BASE, "existing_debt_krw": 30_000_000})
    maximum = out["bands"][2]
    assert maximum["ceiling_krw"] == 100_000_000 + (70_000_000 + 20_000_000 - 30_000_000)


def test_maximum_band_is_always_flagged_as_estimate():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert bands[2]["is_estimate"] is True
    assert bands[0]["is_estimate"] is False


def test_recommended_band_satisfies_the_repayment_burden_cap():
    recommended = compute_bands(PARAMS, **BASE)["bands"][1]
    assert recommended["stress_pass"] is True
    assert recommended["repayment_burden_ratio"] <= 0.1 + 1e-9


def test_recommended_band_never_exceeds_maximum():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert bands[1]["ceiling_krw"] <= bands[2]["ceiling_krw"]


def test_tighter_burden_cap_lowers_the_recommended_ceiling():
    strict = PolicyParams({
        "entries": {**{k: dict(v) for k, v in PARAMS._entries.items()},
                    "stress.repayment_burden_cap_ratio": {"value": 0.02}},
        "industries": {"카페": PARAMS.industry("카페")},
    })
    loose = compute_bands(PARAMS, **BASE)["bands"][1]["ceiling_krw"]
    tight = compute_bands(strict, **BASE)["bands"][1]["ceiling_krw"]
    assert tight < loose


def test_break_even_target_rises_with_the_band():
    bands = compute_bands(PARAMS, **BASE)["bands"]
    assert bands[2]["target_monthly_revenue_krw"] > bands[0]["target_monthly_revenue_krw"]


def test_daily_target_uses_the_industry_operating_days():
    band = compute_bands(PARAMS, **BASE)["bands"][0]
    assert band["target_daily_revenue_krw"] == band["target_monthly_revenue_krw"] // 26


def test_runway_is_none_when_the_band_cannot_cover_required_capital():
    # 자기자본 5천만, 필요자금 약 1.5억 → 자기자본선으로는 조달 불가
    out = compute_bands(PARAMS, **{**BASE, "equity_krw": 50_000_000})
    assert out["bands"][0]["runway_months"] is None


def test_required_capital_band_reports_where_the_need_falls():
    out = compute_bands(PARAMS, **BASE)
    assert out["required_capital_band"] in {"EQUITY_ONLY", "RECOMMENDED", "MAXIMUM", "OUT_OF_RANGE"}


def test_out_of_range_when_required_capital_exceeds_maximum():
    out = compute_bands(PARAMS, **{**BASE, "deposit_krw": 900_000_000})
    assert out["required_capital_band"] == "OUT_OF_RANGE"


def test_trade_area_count_is_none_because_rent_level_data_is_absent():
    for band in compute_bands(PARAMS, **BASE)["bands"]:
        assert band["trade_area_count"] is None


def test_impossible_margin_raises():
    broken = PolicyParams({
        "entries": {k: dict(v) for k, v in PARAMS._entries.items()},
        "industries": {"카페": {**PARAMS.industry("카페"), "cogs_ratio": 0.7, "labor_ratio": 0.4}},
    })
    with pytest.raises(ValueError):
        compute_bands(broken, **BASE)
```

- [ ] **Step 2: 실패 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `ImportError: cannot import name 'compute_bands'`.

- [ ] **Step 3: 구현**

`backend/app/funding.py` 끝에 추가한다.

```python
BAND_ORDER = ("EQUITY_ONLY", "RECOMMENDED", "MAXIMUM")


def _band_line(band: str, ceiling_krw: int, *, equity_krw: int, required_capital_krw: int,
               base_monthly_fixed_krw: int, rate: float, term: int, cogs: float, labor: float,
               drop: float, burden_cap: float, operating_days: int) -> dict:
    loan = max(0, ceiling_krw - equity_krw)
    repayment = monthly_annuity_krw(loan, rate, term)
    monthly_fixed_total = base_monthly_fixed_krw + repayment
    target_monthly = breakeven_monthly_revenue_krw(monthly_fixed_total, cogs, labor)
    stressed_monthly = target_monthly * (1.0 - drop)
    burden = (repayment / stressed_monthly) if stressed_monthly > 0 else 0.0
    surplus_cash = equity_krw + loan - required_capital_krw
    monthly_deficit = drop * monthly_fixed_total
    runway = int(surplus_cash // monthly_deficit) if surplus_cash >= 0 and monthly_deficit > 0 else None
    return {
        "band": band, "ceiling_krw": int(ceiling_krw), "loan_krw": int(loan),
        "monthly_repayment_krw": int(repayment),
        "monthly_fixed_cost_krw": int(monthly_fixed_total),
        "target_monthly_revenue_krw": int(target_monthly),
        "target_daily_revenue_krw": int(target_monthly // operating_days) if operating_days > 0 else 0,
        "runway_months": runway, "stress_pass": burden <= burden_cap + 1e-9,
        "repayment_burden_ratio": round(burden, 6), "subsidy_uplift_krw": 0,
        "is_estimate": band == "MAXIMUM", "trade_area_count": None,
    }


def compute_bands(params, *, industry: str, area_pyeong: float, deposit_krw: int, monthly_rent_krw: int,
                  monthly_maintenance_krw: int, key_money_krw: int, fitout_krw: int | None,
                  equity_krw: int, existing_debt_krw: int, other_monthly_fixed_krw: int) -> dict:
    """조달 밴드 3종과 밴드별 손익분기선을 산출한다. 파라미터가 없으면 호출 전에 걸러야 한다."""
    profile = params.industry(industry)
    cogs, labor = float(profile["cogs_ratio"]), float(profile["labor_ratio"])
    if 1.0 - cogs - labor <= 0:
        raise ValueError("contribution margin must be positive")
    operating_days = int(profile["operating_days_per_month"])
    rate, term = params.value("loan.annual_rate_percent"), int(params.value("loan.term_months"))
    drop = params.value("stress.revenue_drop_ratio")
    burden_cap = params.value("stress.repayment_burden_cap_ratio")

    fitout_is_estimate = fitout_krw is None
    fitout = int(area_pyeong * float(profile["fitout_krw_per_pyeong"])) if fitout_is_estimate else int(fitout_krw)
    base_monthly_fixed = int(monthly_rent_krw + monthly_maintenance_krw + other_monthly_fixed_krw)
    working_capital = int(base_monthly_fixed * params.value("working_capital.months"))
    required_capital = int(deposit_krw + key_money_krw + fitout + working_capital)

    borrow_ceiling = max(0, int(params.value("loan.guarantee_ceiling_krw")
                                + params.value("loan.policy_fund_ceiling_krw") - existing_debt_krw))
    maximum_ceiling = int(equity_krw + borrow_ceiling)

    common = dict(equity_krw=equity_krw, required_capital_krw=required_capital,
                  base_monthly_fixed_krw=base_monthly_fixed, rate=rate, term=term, cogs=cogs,
                  labor=labor, drop=drop, burden_cap=burden_cap, operating_days=operating_days)

    # 부담률은 차입액에 대해 단조증가하므로 이분 탐색으로 권장 조달선을 찾는다.
    low, high = equity_krw, maximum_ceiling
    if _band_line("RECOMMENDED", high, **common)["stress_pass"]:
        recommended_ceiling = high
    else:
        for _ in range(48):
            mid = (low + high) // 2
            if _band_line("RECOMMENDED", mid, **common)["stress_pass"]:
                low = mid
            else:
                high = mid
            if high - low <= 1:
                break
        recommended_ceiling = low

    bands = [_band_line("EQUITY_ONLY", equity_krw, **common),
             _band_line("RECOMMENDED", recommended_ceiling, **common),
             _band_line("MAXIMUM", maximum_ceiling, **common)]

    if required_capital > maximum_ceiling:
        required_capital_band = "OUT_OF_RANGE"
    else:
        required_capital_band = next(item["band"] for item in bands if required_capital <= item["ceiling_krw"])

    return {"required_capital_krw": required_capital, "required_capital_band": required_capital_band,
            "fitout_krw": fitout, "fitout_is_estimate": fitout_is_estimate,
            "base_monthly_fixed_krw": base_monthly_fixed, "working_capital_krw": working_capital,
            "contribution_margin_ratio": round(1.0 - cogs - labor, 6), "bands": bands}
```

- [ ] **Step 4: 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `34 passed`.

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add backend/app/funding.py backend/tests/test_funding_bands.py
git commit -m "feat: derive the three funding bands from user conditions"
```

---

## Task 5: 모델과 불변조건 강제

**Files:**
- Modify: `backend/app/models.py` (파일 끝, `PrivacyRequestCreate` 뒤에 추가)
- Create: `backend/tests/test_models_funding.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_models_funding.py`:

```python
import pytest
from pydantic import ValidationError
from app.models import BandLine, BreakEven, FundingBandResult

LINE = dict(band="EQUITY_ONLY", ceiling_krw=100_000_000, loan_krw=0, monthly_repayment_krw=0,
            monthly_fixed_cost_krw=3_800_000, target_monthly_revenue_krw=8_444_444,
            target_daily_revenue_krw=324_786, runway_months=14, stress_pass=True,
            repayment_burden_ratio=0.0, subsidy_uplift_krw=0, is_estimate=False, trade_area_count=None)

BREAK_EVEN = dict(monthly_fixed_cost_krw=3_800_000, target_monthly_revenue_krw=8_444_444,
                  target_daily_revenue_krw=324_786, contribution_margin_ratio=0.45,
                  assumptions=["원가율 0.35 · 인건비율 0.20 (출처: 테스트, 기준일 2026-07-01)"])


def test_band_line_accepts_a_valid_row():
    assert BandLine(**LINE).band == "EQUITY_ONLY"


def test_maximum_band_must_be_flagged_as_estimate():
    with pytest.raises(ValidationError, match="MAXIMUM"):
        BandLine(**{**LINE, "band": "MAXIMUM", "is_estimate": False})


def test_maximum_band_passes_when_flagged():
    assert BandLine(**{**LINE, "band": "MAXIMUM", "is_estimate": True}).is_estimate is True


def test_band_line_rejects_a_loan_without_repayment():
    with pytest.raises(ValidationError, match="repayment"):
        BandLine(**{**LINE, "loan_krw": 50_000_000, "monthly_repayment_krw": 0})


def test_computed_result_requires_bands_and_break_even():
    with pytest.raises(ValidationError, match="computed"):
        FundingBandResult(status="computed", required_capital_krw=None, required_capital_band=None,
                          bands=[], break_even=None, missing_params=[], message=None)


def test_pending_result_requires_missing_params_and_no_bands():
    with pytest.raises(ValidationError, match="integration_pending"):
        FundingBandResult(status="integration_pending", required_capital_krw=None,
                          required_capital_band=None, bands=[], break_even=None,
                          missing_params=[], message="x")


def test_pending_result_is_valid_with_missing_params():
    result = FundingBandResult(status="integration_pending", required_capital_krw=None,
                               required_capital_band=None, bands=[], break_even=None,
                               missing_params=["loan.term_months"], message="등록 대기")
    assert result.bands == []


def test_computed_result_is_valid():
    result = FundingBandResult(status="computed", required_capital_krw=148_900_000,
                               required_capital_band="RECOMMENDED",
                               bands=[BandLine(**LINE)], break_even=BreakEven(**BREAK_EVEN),
                               missing_params=[], message=None)
    assert result.break_even.contribution_margin_ratio == 0.45


def test_break_even_rejects_non_positive_margin():
    with pytest.raises(ValidationError):
        BreakEven(**{**BREAK_EVEN, "contribution_margin_ratio": 0.0})


def test_break_even_requires_assumptions():
    with pytest.raises(ValidationError, match="assumptions"):
        BreakEven(**{**BREAK_EVEN, "assumptions": []})
```

- [ ] **Step 2: 실패 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `ImportError: cannot import name 'BandLine'`.

- [ ] **Step 3: 구현**

`backend/app/models.py` 끝에 추가한다. 파일 상단 import에 `StrEnum`이 이미 있는지 확인하고 없으면 `from enum import StrEnum`을 추가한다.

```python
class FundingBand(StrEnum):
    EQUITY_ONLY = "EQUITY_ONLY"
    RECOMMENDED = "RECOMMENDED"
    MAXIMUM = "MAXIMUM"
    OUT_OF_RANGE = "OUT_OF_RANGE"


class FundingBandInput(BaseModel):
    case_id: UUID
    industry: str = Field(min_length=1, max_length=120)
    area_pyeong: float = Field(gt=0, le=500)
    deposit_krw: int = Field(ge=0, le=100_000_000_000)
    monthly_rent_krw: int = Field(ge=0, le=1_000_000_000)
    monthly_maintenance_krw: int = Field(default=0, ge=0, le=1_000_000_000)
    key_money_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    fitout_krw: int | None = Field(default=None, ge=0, le=100_000_000_000)
    equity_krw: int = Field(ge=0, le=100_000_000_000)
    existing_debt_krw: int = Field(default=0, ge=0, le=100_000_000_000)
    other_monthly_fixed_krw: int = Field(default=0, ge=0, le=1_000_000_000)


class BandLine(BaseModel):
    band: FundingBand
    ceiling_krw: int = Field(ge=0)
    loan_krw: int = Field(ge=0)
    monthly_repayment_krw: int = Field(ge=0)
    monthly_fixed_cost_krw: int = Field(ge=0)
    target_monthly_revenue_krw: int = Field(ge=0)
    target_daily_revenue_krw: int = Field(ge=0)
    runway_months: int | None = None
    stress_pass: bool
    repayment_burden_ratio: float = Field(ge=0)
    subsidy_uplift_krw: int = Field(default=0, ge=0)
    is_estimate: bool
    trade_area_count: int | None = None

    @model_validator(mode="after")
    def band_contract(self):
        if self.band == FundingBand.MAXIMUM and not self.is_estimate:
            raise ValueError("MAXIMUM band is a pre-screening estimate and must set is_estimate")
        if self.loan_krw > 0 and self.monthly_repayment_krw <= 0:
            raise ValueError("a loan requires a positive monthly repayment")
        if self.loan_krw == 0 and self.monthly_repayment_krw != 0:
            raise ValueError("no loan must not carry a repayment")
        return self


class BreakEven(BaseModel):
    monthly_fixed_cost_krw: int = Field(ge=0)
    target_monthly_revenue_krw: int = Field(ge=0)
    target_daily_revenue_krw: int = Field(ge=0)
    contribution_margin_ratio: float = Field(gt=0, lt=1)
    assumptions: list[str] = Field(min_length=1)


class FundingBandResult(BaseModel):
    status: Literal["computed", "integration_pending"]
    required_capital_krw: int | None = None
    required_capital_band: FundingBand | None = None
    bands: list[BandLine] = Field(default_factory=list)
    break_even: BreakEven | None = None
    missing_params: list[str] = Field(default_factory=list)
    message: str | None = None
    provenance: Provenance | None = None

    @model_validator(mode="after")
    def result_contract(self):
        if self.status == "computed":
            if not self.bands or self.break_even is None or self.required_capital_krw is None:
                raise ValueError("computed result requires bands, break_even and required capital")
            if self.missing_params:
                raise ValueError("computed result must not report missing params")
        else:
            if not self.missing_params:
                raise ValueError("integration_pending result requires missing_params")
            if self.bands or self.break_even is not None:
                raise ValueError("integration_pending result must not contain computed values")
        return self
```

- [ ] **Step 4: 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `44 passed`.

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add backend/app/models.py backend/tests/test_models_funding.py
git commit -m "feat: enforce the funding band contract in the schema"
```

---

## Task 6: API 엔드포인트

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api_funding_bands.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_funding_bands.py`:

```python
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

CASE = {"title": "테스트", "inputs": {"industry": "카페", "district": "강남구", "budget_krw": 150_000_000,
        "equity_krw": 100_000_000, "business_stage": "PRE_OPEN", "startup_type": "INDEPENDENT",
        "priority": "STABILITY"}}

BODY = {"industry": "카페", "area_pyeong": 15.0, "deposit_krw": 100_000_000, "monthly_rent_krw": 2_500_000,
        "monthly_maintenance_krw": 300_000, "key_money_krw": 0, "fitout_krw": None,
        "equity_krw": 100_000_000, "existing_debt_krw": 0, "other_monthly_fixed_krw": 1_000_000}

FILLED = {
    "schema_version": 1, "updated_at": "2026-07-27",
    "entries": {
        "loan.annual_rate_percent": {"value": 4.5, "source": "테스트", "as_of": "2026-07-01"},
        "loan.term_months": {"value": 60, "source": "테스트", "as_of": "2026-07-01"},
        "loan.guarantee_ceiling_krw": {"value": 70_000_000, "source": "테스트", "as_of": "2026-07-01"},
        "loan.policy_fund_ceiling_krw": {"value": 20_000_000, "source": "테스트", "as_of": "2026-07-01"},
        "stress.revenue_drop_ratio": {"value": 0.2, "source": "테스트", "as_of": "2026-07-01"},
        "stress.repayment_burden_cap_ratio": {"value": 0.1, "source": "테스트", "as_of": "2026-07-01"},
        "working_capital.months": {"value": 3, "source": "테스트", "as_of": "2026-07-01"},
    },
    "industries": {"카페": {"cogs_ratio": 0.35, "labor_ratio": 0.20, "fitout_krw_per_pyeong": 2_500_000,
                            "operating_days_per_month": 26, "source": "테스트", "as_of": "2026-07-01"}},
}


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as instance:
        instance.post("/api/v1/sessions/anonymous", json={"retention_notice_accepted": True})
        yield instance


@pytest.fixture
def case_id(client):
    return client.post("/api/v1/cases", json=CASE).json()["id"]


@pytest.fixture
def filled_params(tmp_path, monkeypatch):
    path = tmp_path / "policy-params.json"
    path.write_text(json.dumps(FILLED, ensure_ascii=False), encoding="utf-8")
    import app.main as main
    from app.policy_params import PolicyParams
    monkeypatch.setattr(main, "policy_params", PolicyParams.load(path))
    return path


def test_requires_a_session(case_id):
    from app.main import app
    with TestClient(app) as anonymous:
        response = anonymous.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY})
    assert response.status_code == 401


def test_rejects_a_case_owned_by_another_session(client):
    from uuid import uuid4
    response = client.post("/api/v1/funding-bands", json={"case_id": str(uuid4()), **BODY})
    assert response.status_code == 404


def test_returns_integration_pending_with_the_shipped_empty_config(client, case_id):
    response = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "integration_pending"
    assert payload["bands"] == []
    assert "loan.annual_rate_percent" in payload["missing_params"]
    assert payload["message"]


def test_computes_three_bands_when_params_are_registered(client, case_id, filled_params):
    payload = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    assert payload["status"] == "computed"
    assert [band["band"] for band in payload["bands"]] == ["EQUITY_ONLY", "RECOMMENDED", "MAXIMUM"]
    assert payload["break_even"]["target_daily_revenue_krw"] > 0
    assert payload["provenance"]["confidence"] == "LOW"


def test_changing_equity_changes_the_bands(client, case_id, filled_params):
    low = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    high = client.post("/api/v1/funding-bands",
                       json={"case_id": case_id, **{**BODY, "equity_krw": 200_000_000}}).json()
    assert high["bands"][2]["ceiling_krw"] > low["bands"][2]["ceiling_krw"]


def test_changing_rent_changes_the_target_revenue(client, case_id, filled_params):
    cheap = client.post("/api/v1/funding-bands", json={"case_id": case_id, **BODY}).json()
    dear = client.post("/api/v1/funding-bands",
                       json={"case_id": case_id, **{**BODY, "monthly_rent_krw": 5_000_000}}).json()
    assert dear["break_even"]["target_monthly_revenue_krw"] > cheap["break_even"]["target_monthly_revenue_krw"]


def test_unregistered_industry_is_reported_as_missing(client, case_id, filled_params):
    payload = client.post("/api/v1/funding-bands",
                          json={"case_id": case_id, **{**BODY, "industry": "치킨집"}}).json()
    assert payload["status"] == "integration_pending"
    assert "industries.치킨집" in payload["missing_params"]


def test_rejects_a_non_positive_area(client, case_id):
    """이 앱은 요청 검증 오류를 400 VALIDATION_ERROR로 정규화한다 (main.py:54 validation_handler)."""
    response = client.post("/api/v1/funding-bands", json={"case_id": case_id, **{**BODY, "area_pyeong": 0}})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert any(field["path"].endswith("area_pyeong") for field in body["error"]["details"]["fields"])
```

- [ ] **Step 2: 실패 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: 8건 모두 실패하며 `404 Not Found`(엔드포인트 미존재)를 보고한다. `fastapi.testclient`는 이미 설치된 httpx로 동작하므로 추가 설치는 필요하지 않다.

- [ ] **Step 3: 설정에 파라미터 경로 추가**

`backend/app/config.py:15`의 `document_storage_dir` 바로 아래에 한 줄 추가한다.

```python
    policy_params_path: str = "config/policy-params.json"
```

`.env.example`의 `DOCUMENT_STORAGE_DIR` 아래에 추가한다.

```
POLICY_PARAMS_PATH=config/policy-params.json
```

- [ ] **Step 4: 엔드포인트 구현**

`backend/app/main.py`의 import 블록을 다음과 같이 바꾼다. 기존 `from .models import (...)` 목록에 다섯 개를 알파벳 순서로 끼워 넣고, 두 줄을 새로 추가한다.

```python
from .funding import compute_bands
from .models import (AnalysisCreate, BandLine, BreakEven, CaseCreate, CasePatch, CaseRecord, CostPlanCreate,
                     DocumentCreate, FundingBandInput, FundingBandResult, LocationSearch, MessageCreate,
                     PrivacyRequestCreate, Provenance, SessionCreate)
from .policy_params import PolicyParams
```

`Provenance`는 현재 import되어 있지 않으므로 반드시 추가해야 한다.

모듈 레벨 싱글턴 옆(`document_store = ...` 아래)에 추가한다.

```python
policy_params = PolicyParams.load(settings.policy_params_path)
```

`create_cost_plan` 라우트 아래에 추가한다.

```python
@app.post("/api/v1/funding-bands", response_model=FundingBandResult)
async def create_funding_bands(payload: FundingBandInput, session_id: UUID = Depends(current_session)):
    owned_case(session_id, payload.case_id)
    missing = policy_params.missing(payload.industry)
    if missing:
        return FundingBandResult(status="integration_pending", missing_params=missing,
                                 message="조달 밴드 계산에 필요한 제도·업종 파라미터가 아직 등록되지 않았습니다. 등록 전에는 추정하지 않습니다.")
    fields = payload.model_dump(exclude={"case_id"})
    try:
        computed = compute_bands(policy_params, **fields)
    except ValueError as error:
        raise HTTPException(422, {"code": "VALIDATION_FAILED", "message": f"업종 파라미터로는 손익분기를 계산할 수 없습니다: {error}"})
    first = computed["bands"][0]
    assumptions = [f"원가율·인건비율·평당 인테리어 단가는 등록된 업종 파라미터를 사용했습니다 (출처: {', '.join(policy_params.sources(payload.industry)) or '미기재'})",
                   f"운전자금 {int(policy_params.value('working_capital.months'))}개월분을 필요자금에 포함했습니다",
                   "인테리어비는 평수 기준 추정값입니다" if computed["fitout_is_estimate"] else "인테리어비는 사용자 입력값입니다",
                   "최대 조달선은 신용평가·보증 심사 전 추정치이며 확정 한도가 아닙니다"]
    provenance = Provenance(source_name="자리매김 조달 밴드 계산", industry_scope=payload.industry,
                            spatial_unit="사용자 입력 조건", source_as_of=policy_params.updated_at,
                            confidence="LOW",
                            limitations=["상권별 임대 수준 데이터가 없어 밴드별 진입 가능 상권 수는 제공하지 않습니다",
                                         "지원사업·창업자금 상품 반영분은 연동 대기 상태입니다",
                                         "제도 파라미터는 실측 검증 전 등록값입니다"])
    return FundingBandResult(status="computed", required_capital_krw=computed["required_capital_krw"],
                             required_capital_band=computed["required_capital_band"],
                             bands=[BandLine(**band) for band in computed["bands"]],
                             break_even=BreakEven(monthly_fixed_cost_krw=first["monthly_fixed_cost_krw"],
                                                  target_monthly_revenue_krw=first["target_monthly_revenue_krw"],
                                                  target_daily_revenue_krw=first["target_daily_revenue_krw"],
                                                  contribution_margin_ratio=computed["contribution_margin_ratio"],
                                                  assumptions=assumptions),
                             provenance=provenance)
```

- [ ] **Step 5: 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `52 passed`.

- [ ] **Step 6: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add backend/app/main.py backend/app/config.py .env.example backend/requirements.txt backend/tests/test_api_funding_bands.py
git commit -m "feat: expose POST /api/v1/funding-bands"
```

---

## Task 7: `GET /status`에 축별 가동 여부 노출 (가드 3)

**Files:**
- Modify: `backend/app/main.py:103-115` (`integration_status` — 함수명이 `get_status`가 아니다)
- Create: `backend/tests/test_api_status_axes.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_status_axes.py`:

```python
from fastapi.testclient import TestClient

EXPECTED_KEYS = {"finance.band", "finance.kb_products", "finance.subsidy", "finance.stress",
                 "location.demand", "location.competition", "location.viability",
                 "location.survival", "timing.policy"}


def client():
    from app.main import app
    return TestClient(app)


def test_status_lists_every_analysis_axis():
    payload = client().get("/api/v1/status").json()
    assert set(payload["axes"]) == EXPECTED_KEYS


def test_disabled_axes_carry_a_reason():
    axes = client().get("/api/v1/status").json()["axes"]
    for key, axis in axes.items():
        if not axis["enabled"]:
            assert axis["disabled_reason"], f"{key} is disabled without a reason"


def test_location_axes_are_disabled_without_trade_area_endpoints():
    axes = client().get("/api/v1/status").json()["axes"]
    assert axes["location.viability"]["enabled"] is False
    assert axes["location.demand"]["enabled"] is False


def test_timing_axis_is_disabled_and_abstains():
    axis = client().get("/api/v1/status").json()["axes"]["timing.policy"]
    assert axis["enabled"] is False
    assert "판단 유보" in axis["disabled_reason"]


def test_stress_axis_is_enabled_because_it_needs_no_external_source():
    assert client().get("/api/v1/status").json()["axes"]["finance.stress"]["enabled"] is True
```

- [ ] **Step 2: 실패 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `KeyError: 'axes'`.

- [ ] **Step 3: 구현**

`backend/app/main.py`에서 `integration_status` 라우트 **위에** 추가한다.

```python
def analysis_axes() -> dict[str, dict[str, Any]]:
    """각 분석 축의 가동 여부. 원천이 검증되지 않은 축은 켜지지 않는다 (스펙 §7 가드 3)."""
    trade_area = bool(settings.seoul_open_data_key and settings.seoul_commercial_api_url)
    finlife = bool(settings.finlife_api_key and (settings.finlife_api_url or settings.finlife_api_base_url))
    subsidy = bool((settings.bizinfo_api_key and settings.bizinfo_api_url)
                   or (settings.kstartup_api_key and settings.kstartup_api_url))
    return {
        "finance.band": {"enabled": True, "disabled_reason": None,
                         "note": "제도 파라미터 미등록 시 integration_pending을 반환합니다"},
        "finance.stress": {"enabled": True, "disabled_reason": None, "note": None},
        "finance.kb_products": {"enabled": finlife,
                                "disabled_reason": None if finlife else "금융상품 공시 endpoint 미검증",
                                "note": "finlife는 소비자 대출만 공시합니다. 창업자금 상품 정보는 연동 대기입니다"},
        "finance.subsidy": {"enabled": subsidy,
                            "disabled_reason": None if subsidy else "지원사업 endpoint 미검증",
                            "note": None},
        "location.demand": {"enabled": trade_area, "disabled_reason": None if trade_area else "서울 상권분석 인구 데이터 미연동", "note": None},
        "location.competition": {"enabled": trade_area, "disabled_reason": None if trade_area else "서울 상권분석 점포 데이터 미연동", "note": None},
        "location.viability": {"enabled": trade_area, "disabled_reason": None if trade_area else "서울 상권분석 추정매출 데이터 미연동", "note": None},
        "location.survival": {"enabled": False, "disabled_reason": "인허가 이력 코호트 미구축", "note": "유일한 A등급 경로입니다"},
        "timing.policy": {"enabled": False, "disabled_reason": "개발·정책 일정 원천 미확보 — 일정 확인 전 판단 유보", "note": None},
    }
```

`integration_status`의 반환 dict에서 `"feature_flags": {...}` 뒤에 한 항목을 추가한다.

```python
        "axes": analysis_axes(),
```

- [ ] **Step 4: 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test
```

기대: `57 passed`.

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add backend/app/main.py backend/tests/test_api_status_axes.py
git commit -m "feat: surface per-axis availability on the status endpoint"
```

---

## Task 8: 프론트엔드 타입과 클라이언트

계산 결과를 화면에 붙이는 것은 이 계획의 범위가 아니다. **타입 미러링과 fetch 계층만** 추가한다(`lib/types.ts`는 `models.py`와 필드 단위로 일치해야 한다).

**Files:**
- Modify: `lib/types.ts` (파일 끝)
- Modify: `lib/api.ts` (import 줄과 `api` 객체)

- [ ] **Step 1: 타입 추가**

`lib/types.ts` 끝에 추가한다.

```typescript
export type FundingBandKey = "EQUITY_ONLY" | "RECOMMENDED" | "MAXIMUM" | "OUT_OF_RANGE";

export interface FundingBandInput {
  industry: string;
  area_pyeong: number;
  deposit_krw: number;
  monthly_rent_krw: number;
  monthly_maintenance_krw: number;
  key_money_krw: number;
  fitout_krw: number | null;
  equity_krw: number;
  existing_debt_krw: number;
  other_monthly_fixed_krw: number;
}

export interface BandLine {
  band: FundingBandKey;
  ceiling_krw: number;
  loan_krw: number;
  monthly_repayment_krw: number;
  monthly_fixed_cost_krw: number;
  target_monthly_revenue_krw: number;
  target_daily_revenue_krw: number;
  runway_months: number | null;
  stress_pass: boolean;
  repayment_burden_ratio: number;
  subsidy_uplift_krw: number;
  is_estimate: boolean;
  trade_area_count: number | null;
}

export interface BreakEven {
  monthly_fixed_cost_krw: number;
  target_monthly_revenue_krw: number;
  target_daily_revenue_krw: number;
  contribution_margin_ratio: number;
  assumptions: string[];
}

export interface FundingBandResult {
  status: "computed" | "integration_pending";
  required_capital_krw: number | null;
  required_capital_band: FundingBandKey | null;
  bands: BandLine[];
  break_even: BreakEven | null;
  missing_params: string[];
  message: string | null;
  provenance: Provenance | null;
}

export interface AnalysisAxis {
  enabled: boolean;
  disabled_reason: string | null;
  note: string | null;
}
```

`StatusResponse`에 한 필드를 추가한다.

```typescript
export interface StatusResponse {
  mode: string;
  integrations: IntegrationStatus;
  feature_flags: FeatureFlags;
  axes: Record<string, AnalysisAxis>;
}
```

- [ ] **Step 2: 클라이언트 메서드 추가**

`lib/api.ts` 첫 줄의 import에 `FundingBandInput`, `FundingBandResult`를 추가하고, `api` 객체의 `createCostPlan` 아래에 추가한다.

```typescript
  fundingBands: (caseId: string, inputs: FundingBandInput) => request<FundingBandResult>("/funding-bands", { method: "POST", headers: { "Idempotency-Key": requestId() }, body: JSON.stringify({ case_id: caseId, ...inputs }) }),
```

- [ ] **Step 3: 타입 검사와 린트**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run typecheck && npm run lint
```

기대: 둘 다 오류 0건. `StatusResponse.axes`를 필수로 만들었으므로 기존 사용처가 깨지면 그 사용처를 고친다(추가만 했으므로 깨지지 않아야 한다).

- [ ] **Step 4: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add lib/types.ts lib/api.ts
git commit -m "feat: mirror the funding band contract in the client types"
```

---

## Task 9: 회귀 검증

**Files:**
- Modify: `scripts/flow-check.mjs` (파일 끝의 판정부)

- [ ] **Step 1: 백엔드 전체 테스트**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test && npm run api:check
```

기대: `57 passed`, compileall 오류 0건.

- [ ] **Step 2: 프론트 검사**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run typecheck && npm run lint && npm run build
```

기대: 전부 성공.

- [ ] **Step 3: flow-check에 밴드 안전 상태 단정 추가**

`scripts/flow-check.mjs`에서 `const funding = { emptySafeState: ... };` 줄 **아래**에 추가한다.

```javascript
const bandsResponse = await page.request.post("http://127.0.0.1:4173/api/v1/funding-bands", {
  data: { case_id: caseId, industry: "카페", area_pyeong: 15, deposit_krw: 100000000, monthly_rent_krw: 2500000,
          monthly_maintenance_krw: 300000, key_money_krw: 0, fitout_krw: null, equity_krw: 100000000,
          existing_debt_krw: 0, other_monthly_fixed_krw: 1000000 }
});
const bandsBody = await bandsResponse.json();
const bands = { pendingSafeState: bandsBody.status === "integration_pending" && bandsBody.bands.length === 0 && bandsBody.missing_params.length > 0 };
```

`caseId`가 스코프에 없으면 온보딩 단계에서 `page.url()`로 추출한다. `/cases/<uuid>/` 형태이므로 다음을 사용한다.

```javascript
const caseId = page.url().match(/\/cases\/([0-9a-f-]{36})/)?.[1];
```

- [ ] **Step 4: 판정부에 반영**

`const result = { onboarding, cost, funding, document, copilot, errors };` 를 다음으로 바꾼다.

```javascript
const result = { onboarding, cost, funding, bands, document, copilot, errors };
```

마지막 줄의 조건에 `|| !bands.pendingSafeState` 를 추가한다.

```javascript
if (errors.length || !onboarding.integrationPending || !cost.calculated || !funding.emptySafeState || !bands.pendingSafeState || !document.authGate || !copilot.noKeyFallback) process.exitCode = 1;
```

- [ ] **Step 5: flow-check 실행**

두 개의 터미널이 필요하다. 첫 터미널:

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run dev
```

두 번째 터미널:

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && node scripts/flow-check.mjs
```

기대: 종료 코드 0, 출력의 `bands.pendingSafeState`가 `true`. **키 없는 환경에서 `integration_pending`이 정답이며, 이것이 부록 A 불변조건 1의 회귀 고정이다.**

- [ ] **Step 6: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add scripts/flow-check.mjs
git commit -m "test: pin the funding band pending safe state in flow-check"
```

---

## 완료 정의 (스펙 §9 대조)

| 스펙 요구 | 확인 방법 |
|---|---|
| 자기자본·임대조건을 바꾸면 3중선과 목표매출이 바뀐다 | `test_changing_equity_changes_the_bands`, `test_changing_rent_changes_the_target_revenue` |
| 지원금·상품 정보는 "연동 대기"로 표시 | `finance.subsidy` / `finance.kb_products` 축이 `enabled: false` + `disabled_reason` (Task 7) |
| `flow-check.mjs`가 키 없는 환경에서 통과 | Task 9 Step 5 |
| placeholder 데이터 투입 시 실패 | `test_shipped_config_has_no_registered_values` — 값이 채워진 설정을 커밋하면 실패 |
| 최대 조달선은 추정치로만 표기 | `test_maximum_band_must_be_flagged_as_estimate` + `BandLine.band_contract` |
| 가동 불가 축이 노출된다 | `test_disabled_axes_carry_a_reason` |

## 이 계획에서 하지 않은 것

- **가드 1(EvidenceGate)·가드 2(영속화)** — D0에는 LLM 경로가 없어 가드 1이 적용될 대상이 없고, 밴드 계산은 결정론적이라 가드 2 없이도 동일 입력에 동일 출력이 나온다. 두 가드는 `location.*` 축이나 `main.orchestrator`를 붙이는 단계에서 구현한다.
- **화면 연결** — `components/kb/JarimaegimPlan.tsx`에 밴드 UI를 붙이는 것은 별도 계획으로 분리한다. 확장·축소 배너의 대칭 노출 요구(§2 결정 4)는 UI 계획에서 다룬다.
- **`store.py` idempotency 회수** — 가드 2와 함께 처리한다.
