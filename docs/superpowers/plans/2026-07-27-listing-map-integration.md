# 매물 지도 연동 (Stage 4 + 백엔드 + 프론트) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `data/listings.seoul.json`의 시연용 매물 275건을 자리매김의 두 지도(Workspace, KbShell)에 핀으로 띄우고, 선택한 매물의 **보증금**이 비용 단계로 이어지게 한다.

**Architecture:** 매물을 새 타입으로 만들지 않고 기존 `Candidate`에 `listing` 필드를 붙인다. `POST /api/v1/locations/search`의 응답 형태가 `list[Candidate]` 그대로이므로 프론트 계약이 깨지지 않는다. 새 `ListingService`는 `repository.py`의 이중 모드 관례를 따라 Supabase가 설정되면 테이블에서, 아니면 시드 JSON에서 읽는다. 라벨(`DEMO_SYNTHETIC`)은 pydantic Literal, DB CHECK 제약, UI 배지, PDF 네 층에서 강제된다.

**Tech Stack:** FastAPI + pydantic (backend/.venv, Python 3.12, pytest), Next.js 16 App Router + TypeScript, Kakao Maps SDK, Supabase (postgres), playwright-core (e2e)

**설계 문서:** `docs/superpowers/specs/2026-07-27-listing-data-pipeline-design.md` §4~§6

**선행 조건:** `data/listings.seoul.json`(275건)과 `data/rent-distribution.seoul.json`이 이미 커밋되어 있다. 이 계획은 그 파일을 소비만 하고 다시 생성하지 않는다.

**범위 밖:** 실제 매물 연동, 매물 사진·중개사 정보, 마커 클러스터링, `store.py`/`integrations.py` 레거시 클러스터.

---

## 현재 코드 상태 (읽고 확인한 사실)

계획을 쓰기 전에 실제 코드를 읽었다. 설계 문서와 다른 점이 있으니 그대로 따르지 말 것.

- `backend/app/main.py:200` `search_locations`가 `locations.search(payload)`를 호출하고 `{"candidates": [...], "status", "message"}`를 반환한다.
- `backend/app/models.py:84` `Candidate`에는 `listing` 필드가 없다.
- `backend/app/services.py:21` `LocationService`는 Kakao Local을 실시간 호출한다. 키가 없으면 `[]`와 `integration_pending`을 반환한다.
- **`backend/app/document_store.py:48` `render_case_pdf`는 `case["inputs"]`만 렌더링한다. 매물이 PDF에 들어갈 경로가 아직 없다.** 설계 §5.2가 PDF 라벨을 요구하므로, 매물을 케이스에 영속화하는 작업이 선행되어야 한다 (Task 8).
- `backend/app/models.py:20` `CaseInput`은 엄격한 모델이다. 필드를 추가하려면 모델을 고쳐야 한다.
- **프론트 표면이 둘이다.** `app/cases/[caseId]/[[...section]]/page.tsx` → `components/Workspace.tsx`(실제 작업 화면, `flow-check.mjs`가 검증). `app/page.tsx`와 `app/today/page.tsx` → `components/kb/KbShell.tsx`(랜딩 셸, `shell-check.mjs`가 검증). **둘은 지도 컴포넌트도 다르다.**
- `components/KakaoMap.tsx`(Workspace용)는 마커를 `real-map-label` 버튼으로 만들고 `${index+1} ${candidate.name}`만 넣는다.
- `components/kb/KbMap.tsx:13` `markerNode()`(KbShell용)는 `kb-marker`를 이름 + 등급 배지 2단으로 만든다.
- `components/Workspace.tsx:56` `ExploreView`가 후보 카드(`candidate-row`)를 렌더링하고 이미 `ProvenanceBar`를 붙인다.
- `components/kb/JarimaegimPanel.tsx:127`이 KbShell 쪽 후보 목록(`kb-candidates`)을 렌더링한다.
- **`components/Workspace.tsx:65` `CostView`는 창업 소요자금 계산기다.** 항목이 보증금·권리금·인테리어·초기재고·안전예비비이고, 합계에서 자기자본을 빼 조달 차이를 낸다. **월세는 매달 나가는 운영비라 이 합계에 들어가면 총소요자금이 왜곡된다.** 설계 §4.4는 "보증금·월세 프리필"이라고 적었지만 **월세는 넣지 않는다.**
- `CostView`의 출처 라벨은 `item.source_type==="USER"?"사용자 입력":"확인 불가"` 뿐이다. `ESTIMATE`를 넣으면 "확인 불가"로 잘못 표시된다.
- `components/Workspace.tsx:32` `commitCandidate`의 토스트가 "비용 값은 자동으로 만들지 않습니다"라고 말한다. 프리필하면 이 문장이 거짓이 된다.
- `components/kb/KbShell.tsx:87`에 "매물·시세 데이터는 표시하지 않습니다" 안내가 하드코딩되어 있다. 매물이 표시되면 거짓이 된다.
- `components/ProvenanceBar.tsx`는 6줄짜리 한 줄 컴포넌트이고 `limitations`를 이미 렌더링한다. **Workspace와 KbShell 양쪽이 같은 것을 쓴다** — `ListingService`가 provenance를 채우므로 별도 작업 없이 라벨이 표시된다.
- 프론트에는 단위 테스트 프레임워크가 없다. 검증은 `scripts/flow-check.mjs`와 `scripts/shell-check.mjs`(둘 다 playwright)로만 한다.
- 백엔드 pytest는 `backend/tests/`에 있고 `npm run api:test`로 돈다 (현재 59개 통과). **단일 파일을 돌릴 때 `npm run api:test -- <경로>`는 동작하지 않는다** — `api:test`가 `cd backend`를 먼저 하므로 경로가 이중 중첩된다. 대신 `backend/.venv/bin/python -m pytest backend/tests/<파일> -v`를 쓴다.

---

## File Structure

| 파일 | 책임 |
| --- | --- |
| `supabase/migrations/202607270001_listings.sql` | `listings` 테이블 + RLS + 라벨 CHECK 제약 |
| `scripts/seed-listings.mjs` | 시드 JSON → Supabase 적재 (멱등) |
| `backend/app/models.py` | `ListingTerms` 추가, `Candidate.listing`, `CaseInput.committed_listing_id` |
| `backend/app/listings.py` | `ListingService` — 이중 모드 로드, 구·예산 필터 |
| `backend/app/main.py` | `locations/search`를 `ListingService`로 전환 |
| `backend/app/document_store.py` | PDF에 매물 조건 + 시연용 라벨 |
| `backend/app/services.py` | `AIService.explain` 프롬프트에 시연용 사실 추가 |
| `backend/tests/test_listings.py` | `ListingService` 단위 테스트 |
| `backend/tests/test_api_locations.py` | `locations/search` 계약 테스트 |
| `lib/types.ts` | `ListingTerms` 미러 |
| `lib/format.ts` | 두 표면이 공유하는 금액 표기 (`manwon`) |
| `components/KakaoMap.tsx` | Workspace 지도 마커 |
| `components/kb/KbMap.tsx` | KbShell 지도 마커 |
| `components/Workspace.tsx` | 후보 카드 조건 표시, 보증금 프리필, 토스트 문구 |
| `components/kb/JarimaegimPanel.tsx` | KbShell 후보 목록 조건 표시 |
| `components/kb/KbShell.tsx` | 거짓이 된 안내 문구 교체 |
| `scripts/flow-check.mjs` | Workspace 경로 어서션 갱신 |
| `scripts/shell-check.mjs` | KbShell 경로 어서션 추가 |

---

## Task 1: Supabase 스키마

**Files:**
- Create: `supabase/migrations/202607270001_listings.sql`

`supabase/archive/`는 건드리지 않는다. `202607200001_initial.sql`이 활성 베이스라인이다.

- [ ] **Step 1: 마이그레이션 작성**

```sql
-- 시연용 매물. 세션 스코프가 아닌 공용 참조 데이터이므로 익명 읽기를 허용한다.
create table public.listings (
  id text primary key,
  district text not null,
  name text not null,
  address text not null,
  latitude double precision not null,
  longitude double precision not null,
  listing_kind text not null default 'DEMO_SYNTHETIC',
  deposit_krw bigint not null check(deposit_krw >= 0),
  monthly_rent_krw bigint not null check(monthly_rent_krw > 0),
  maintenance_fee_krw bigint check(maintenance_fee_krw >= 0),
  area_m2 double precision not null check(area_m2 > 0),
  floor int not null,
  created_at timestamptz not null default now(),
  -- 라벨을 DB 층에서도 강제한다. 실제 매물이 생기면 이 제약을 넓힌다.
  constraint listings_kind_is_demo check (listing_kind = 'DEMO_SYNTHETIC')
);

create index listings_district_rent_idx on public.listings(district, monthly_rent_krw);

alter table public.listings enable row level security;

-- 읽기는 공개, 쓰기는 service role만. service role은 RLS를 우회하므로 정책을 따로 두지 않는다.
create policy listings_public_read on public.listings for select to anon, authenticated using (true);
```

- [ ] **Step 2: 문법 확인**

Supabase에 적용하지 말고 문법만 본다. `SUPABASE_DB_URL`이 `.env`에 있지만 **이 태스크에서 원격 DB에 적용하지 않는다** — 스키마 변경은 사람이 승인할 일이다.

Run: `grep -c 'create table\|create policy\|create index' supabase/migrations/202607270001_listings.sql`
Expected: `3`

- [ ] **Step 3: 커밋**

```bash
git add supabase/migrations/202607270001_listings.sql
git commit -m "feat(db): add the demo listings table"
```

---

## Task 2: `ListingTerms` 모델과 `Candidate` 확장

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_models_listing.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_models_listing.py`:

```python
import pytest
from pydantic import ValidationError

from app.models import Candidate, ListingTerms, Provenance


def provenance() -> Provenance:
    return Provenance(source_name="시연용 생성 데이터", industry_scope="일반 상가",
                      spatial_unit="개별 상가 좌표", confidence="LOW", limitations=[])


def terms(**overrides) -> dict:
    base = {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 56_000_000, "monthly_rent_krw": 4_580_000,
            "maintenance_fee_krw": 370_000, "area_m2": 52.8, "floor": 1}
    return base | overrides


def test_listing_terms_accepts_the_demo_label():
    assert ListingTerms(**terms()).listing_kind == "DEMO_SYNTHETIC"


def test_listing_terms_rejects_any_other_label():
    with pytest.raises(ValidationError):
        ListingTerms(**terms(listing_kind="VERIFIED"))


def test_listing_terms_requires_the_label():
    payload = terms()
    del payload["listing_kind"]
    with pytest.raises(ValidationError):
        ListingTerms(**payload)


def test_listing_terms_rejects_a_non_positive_rent():
    with pytest.raises(ValidationError):
        ListingTerms(**terms(monthly_rent_krw=0))


def test_candidate_without_a_listing_stays_valid():
    candidate = Candidate(id="kakao-1", name="장소", address="서울 강남구", latitude=37.5, longitude=127.0,
                          evidence_grade="C", display_label="입지 환경 신호", context_signals=[], provenance=provenance())
    assert candidate.listing is None


def test_candidate_carries_listing_terms():
    candidate = Candidate(id="demo-강남구-0001", name="도곡동 1층 상가", address="서울 강남구 도곡동",
                          latitude=37.49, longitude=127.05, evidence_grade="C", display_label="시연용 매물",
                          context_signals=[], provenance=provenance(), listing=ListingTerms(**terms()))
    assert candidate.listing.deposit_krw == 56_000_000
    assert candidate.evidence_grade == "C"
```

마지막 테스트가 `evidence_grade == "C"`를 확인하는 이유: 매물 조건이 붙어도 생존확률 등급이 생기면 안 된다(불변조건 2).

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_models_listing.py` -v
Expected: FAIL — `ImportError: cannot import name 'ListingTerms'`

- [ ] **Step 3: 모델 추가**

`backend/app/models.py`의 `class Candidate` 바로 위에 추가:

```python
class ListingTerms(BaseModel):
    """Demo listing terms. The label is a required Literal so an unlabelled listing cannot be constructed."""
    listing_kind: Literal["DEMO_SYNTHETIC"]
    deposit_krw: int = Field(ge=0)
    monthly_rent_krw: int = Field(gt=0)
    maintenance_fee_krw: int | None = Field(default=None, ge=0)
    area_m2: float = Field(gt=0)
    floor: int
```

`Candidate`에 필드 하나 추가 (기존 필드는 그대로):

```python
    listing: ListingTerms | None = None
```

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_models_listing.py` -v
Expected: PASS, 6 tests

전체도 확인: `npm run api:test`
Expected: 65 passed (기존 59 + 신규 6)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/models.py backend/tests/test_models_listing.py
git commit -m "feat(api): let a candidate carry demo listing terms"
```

---

## Task 3: `ListingService`

**Files:**
- Create: `backend/app/listings.py`
- Test: `backend/tests/test_listings.py`

`repository.py`의 이중 모드 관례를 따른다. Supabase가 설정되면 테이블에서, 아니면 `data/listings.seoul.json`에서 읽는다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_listings.py`:

```python
import json

import pytest

from app.config import Settings
from app.listings import ListingService

ROWS = [
    {"id": "demo-강남구-0001", "name": "도곡동 1층 상가", "address": "서울 강남구 도곡동", "district": "강남구",
     "latitude": 37.49, "longitude": 127.05,
     "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 56_000_000, "monthly_rent_krw": 4_580_000,
                 "maintenance_fee_krw": 370_000, "area_m2": 52.8, "floor": 1}},
    {"id": "demo-강남구-0002", "name": "역삼동 1층 상가", "address": "서울 강남구 역삼동", "district": "강남구",
     "latitude": 37.50, "longitude": 127.03,
     "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 20_000_000, "monthly_rent_krw": 1_800_000,
                 "maintenance_fee_krw": 140_000, "area_m2": 30.0, "floor": 1}},
    {"id": "demo-마포구-0001", "name": "서교동 1층 상가", "address": "서울 마포구 서교동", "district": "마포구",
     "latitude": 37.55, "longitude": 126.92,
     "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": 30_000_000, "monthly_rent_krw": 2_600_000,
                 "maintenance_fee_krw": 200_000, "area_m2": 40.0, "floor": 1}},
]


@pytest.fixture
def service(tmp_path):
    seed = tmp_path / "listings.seoul.json"
    seed.write_text(json.dumps({
        "generated_at": "2026-07-27T00:00:00Z", "seed": 20260727, "listing_kind": "DEMO_SYNTHETIC",
        "notice": "시연용 생성 데이터입니다.", "method": "…", "assumed": "…", "listings": ROWS,
    }), encoding="utf-8")
    return ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=seed)


def test_covered_districts_are_derived_from_the_seed(service):
    assert service.covered_districts() == {"강남구", "마포구"}


def test_search_returns_candidates_for_a_covered_district(service):
    candidates, status, message = service.search("강남구", budget_krw=None, limit=15)
    assert status == "success"
    assert message is None
    assert len(candidates) == 2
    assert all(candidate.listing.listing_kind == "DEMO_SYNTHETIC" for candidate in candidates)


def test_search_sorts_by_monthly_rent_ascending(service):
    candidates, _, _ = service.search("강남구", budget_krw=None, limit=15)
    rents = [candidate.listing.monthly_rent_krw for candidate in candidates]
    assert rents == sorted(rents)


def test_search_respects_the_limit(service):
    candidates, _, _ = service.search("강남구", budget_krw=None, limit=1)
    assert len(candidates) == 1


def test_budget_filters_out_listings_whose_deposit_exceeds_it(service):
    candidates, _, _ = service.search("강남구", budget_krw=25_000_000, limit=15)
    assert [candidate.id for candidate in candidates] == ["demo-강남구-0002"]


def test_an_uncovered_district_returns_an_explanatory_empty_state(service):
    candidates, status, message = service.search("노원구", budget_krw=None, limit=15)
    assert candidates == []
    assert status == "empty"
    assert "강남구" in message and "마포구" in message


def test_a_budget_that_excludes_everything_says_so(service):
    candidates, status, message = service.search("강남구", budget_krw=1_000, limit=15)
    assert candidates == []
    assert status == "empty"
    assert "예산" in message


def test_every_candidate_is_grade_c(service):
    candidates, _, _ = service.search("강남구", budget_krw=None, limit=15)
    assert {candidate.evidence_grade for candidate in candidates} == {"C"}


def test_provenance_declares_the_data_is_not_a_real_listing(service):
    candidate, *_ = service.search("강남구", budget_krw=None, limit=15)[0]
    assert candidate.provenance.source_name == "시연용 생성 데이터"
    assert any("실제 임대 매물이 아니" in item for item in candidate.provenance.limitations)


def test_get_resolves_a_candidate_by_id(service):
    assert service.get("demo-강남구-0001").name == "도곡동 1층 상가"
    assert service.get("nope") is None


def test_a_missing_seed_file_yields_an_empty_service(tmp_path):
    empty = ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=tmp_path / "absent.json")
    assert empty.covered_districts() == set()
    candidates, status, message = empty.search("강남구", budget_krw=None, limit=15)
    assert candidates == [] and status == "empty" and message is not None
```

시드 파일이 없을 때 예외를 던지지 않고 빈 상태를 반환하는 이유: 불변조건 1이 요구하는 것은 "없으면 빈 상태"이지 크래시가 아니다. 다만 조용히 빈 것이 아니라 메시지가 붙어야 한다.

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_listings.py` -v
Expected: FAIL — `ModuleNotFoundError: No module named 'app.listings'`

- [ ] **Step 3: 구현**

`backend/app/listings.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from supabase import Client, create_client

from .config import Settings
from .models import Candidate, ListingTerms, Provenance

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "listings.seoul.json"

LIMITATIONS = [
    "실제 임대 매물이 아니며 계약 대상이 아닙니다.",
    "위치는 실제 상가 좌표이나 면적·월세는 서울교통공사 지하상가 임대정보 분포에서 생성했고, 보증금·관리비·층은 가정값입니다.",
]


class ListingService:
    """Demo listings, read once at startup. Supabase when configured, otherwise the committed seed file.

    Mirrors the dual-mode convention in repository.py so a machine with no keys still renders the map.
    """

    def __init__(self, settings: Settings, seed_path: Path | None = None):
        self.settings = settings
        self._by_id: dict[str, Candidate] = {}
        self._by_district: dict[str, list[Candidate]] = {}
        rows = self._load_supabase() if settings.supabase_configured else self._load_seed(seed_path or DEFAULT_SEED_PATH)
        for row in rows:
            candidate = self._to_candidate(row)
            self._by_id[candidate.id] = candidate
            self._by_district.setdefault(row["district"], []).append(candidate)
        for bucket in self._by_district.values():
            bucket.sort(key=lambda candidate: candidate.listing.monthly_rent_krw)

    def _load_seed(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8")).get("listings", [])

    def _load_supabase(self) -> list[dict[str, Any]]:
        client: Client = create_client(self.settings.supabase_url, self.settings.supabase_service_role_key)
        rows = client.table("listings").select("*").execute().data or []
        return [{
            "id": row["id"], "name": row["name"], "address": row["address"], "district": row["district"],
            "latitude": row["latitude"], "longitude": row["longitude"],
            "listing": {
                "listing_kind": row["listing_kind"], "deposit_krw": row["deposit_krw"],
                "monthly_rent_krw": row["monthly_rent_krw"], "maintenance_fee_krw": row["maintenance_fee_krw"],
                "area_m2": row["area_m2"], "floor": row["floor"],
            },
        } for row in rows]

    def _to_candidate(self, row: dict[str, Any]) -> Candidate:
        terms = ListingTerms(**row["listing"])
        provenance = Provenance(
            source_name="시연용 생성 데이터", source_as_of="2026-07-27",
            industry_scope="업종 무관 일반 상가", spatial_unit="개별 상가 좌표",
            confidence="LOW", limitations=LIMITATIONS,
        )
        return Candidate(
            id=row["id"], name=row["name"], address=row["address"],
            latitude=row["latitude"], longitude=row["longitude"],
            evidence_grade="C", display_label="시연용 매물", context_signals=[],
            provenance=provenance, listing=terms,
        )

    def covered_districts(self) -> set[str]:
        return set(self._by_district)

    def get(self, candidate_id: str) -> Candidate | None:
        return self._by_id.get(candidate_id)

    def search(self, district: str, budget_krw: int | None, limit: int) -> tuple[list[Candidate], str, str | None]:
        bucket = self._by_district.get(district)
        if not bucket:
            covered = " · ".join(sorted(self._by_district)) or "없음"
            return [], "empty", f"현재 시연용 매물 데이터는 {covered} 에만 준비되어 있습니다."
        matched = [c for c in bucket if budget_krw is None or c.listing.deposit_krw <= budget_krw]
        if not matched:
            return [], "empty", "입력한 예산 안에 들어오는 시연용 매물이 없습니다. 예산을 조정해 다시 확인해 주세요."
        return matched[:limit], "success", None
```

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_listings.py` -v
Expected: PASS, 11 tests

- [ ] **Step 5: 실제 시드로도 로드되는지 확인**

Run:

```bash
backend/.venv/bin/python -c "
import sys; sys.path.insert(0, 'backend')
from app.config import Settings
from app.listings import ListingService
s = ListingService(Settings(supabase_url='', supabase_service_role_key=''))
print('districts:', sorted(s.covered_districts()))
c, status, msg = s.search('강남구', None, 15)
print('강남구:', len(c), status, c[0].name, c[0].listing.monthly_rent_krw)
print('노원구:', s.search('노원구', None, 15)[1:])
"
```

Expected: 5개 구가 나오고, 강남구 15건이 `success`로, 노원구는 `empty` + 안내 문구.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/listings.py backend/tests/test_listings.py
git commit -m "feat(api): serve demo listings from supabase or the committed seed"
```

---

## Task 4: `locations/search`를 매물로 전환

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_locations.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_locations.py`:

기존 테스트가 세션·케이스를 어떻게 만드는지 먼저 확인한다: `sed -n '1,40p' backend/tests/test_api_funding_bands.py`. 같은 헬퍼 방식을 따른다.

```python
from fastapi.testclient import TestClient

from app.main import app


def new_case(client: TestClient, district: str = "강남구", budget: int = 100_000_000) -> str:
    client.post("/api/v1/sessions/anonymous", json={})
    response = client.post("/api/v1/cases", json={
        "title": "테스트 케이스",
        "inputs": {"industry": "카페", "district": district, "budget_krw": budget, "equity_krw": 30_000_000,
                   "business_stage": "PRE_OPEN", "startup_type": "FIRST_TIME", "priority": "STABILITY"},
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_a_covered_district_returns_labelled_listings():
    with TestClient(app) as client:
        case_id = new_case(client)
        response = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": "강남구", "limit": 15})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success"
        assert len(body["candidates"]) > 0
        for candidate in body["candidates"]:
            assert candidate["listing"]["listing_kind"] == "DEMO_SYNTHETIC"
            assert candidate["evidence_grade"] == "C"


def test_an_uncovered_district_returns_an_empty_state_not_an_error():
    with TestClient(app) as client:
        case_id = new_case(client, district="노원구")
        response = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": "노원구", "limit": 15})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["candidates"] == []
        assert body["status"] == "empty"
        assert body["message"]


def test_a_mismatched_district_is_still_rejected():
    with TestClient(app) as client:
        case_id = new_case(client, district="강남구")
        response = client.post("/api/v1/locations/search", json={
            "case_id": case_id, "industry": "카페", "district": "마포구", "limit": 15})
        assert response.status_code == 400
```

마지막 테스트가 중요하다: 매물로 바꾸면서 기존 "케이스 조건과 검색 조건이 다르면 400" 규칙을 잃으면 안 된다.

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_api_locations.py` -v
Expected: FAIL — `KeyError: 'listing'` 또는 후보 0건 (아직 Kakao 경로를 타므로)

- [ ] **Step 3: 전환**

`backend/app/main.py` 상단 import에 추가:

```python
from .listings import ListingService
```

모듈 수준 싱글턴이 모여 있는 곳(다른 서비스가 만들어지는 줄 근처)에 추가:

```python
listings_service = ListingService(settings)
```

`search_locations` 본문을 교체한다. 케이스 조건 검증(400)은 그대로 두고 그 아래만 바꾼다:

```python
@app.post("/api/v1/locations/search")
async def search_locations(payload: LocationSearch, session_id: UUID = Depends(current_session)):
    case = owned_case(session_id, payload.case_id)
    if payload.district != case.inputs.district or payload.industry != case.inputs.industry:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "확정된 케이스 조건과 검색 조건이 다릅니다."})
    candidates, status, message = listings_service.search(payload.district, case.inputs.budget_krw, payload.limit)
    return {"candidates": [candidate.model_dump(mode="json") for candidate in candidates], "status": status, "message": message}
```

`LocationService`와 그 import는 **삭제하지 않는다.** 실제 매물이 생기면 다시 쓸 수 있고, 지우면 `AnalysisService`가 깨진다.

`AnalysisService`가 후보를 찾지 못하게 되므로 `analyses` 생성자에 넘기는 조회자를 `listings_service`로 바꾼다. `backend/app/services.py`의 `AnalysisService.__init__`은 `location_service`를 받아 `self.locations.get_candidate(...)`를 호출한다. `ListingService`에는 `get()`만 있으므로, `ListingService`에 별칭을 추가한다 (`backend/app/listings.py`):

```python
    def get_candidate(self, candidate_id: str) -> Candidate | None:
        """Alias so AnalysisService can take either service without knowing which."""
        return self.get(candidate_id)
```

그리고 `main.py`에서 `analyses = AnalysisService(listings_service)`로 바꾼다.

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_api_locations.py` -v
Expected: PASS, 3 tests

전체: `npm run api:test`
Expected: 79 passed (59 + 6 + 11 + 3)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/main.py backend/app/listings.py backend/tests/test_api_locations.py
git commit -m "feat(api): serve listings from the location search endpoint"
```

---

## Task 5: `lib/types.ts` 미러

**Files:**
- Modify: `lib/types.ts`

`lib/types.ts`는 `backend/app/models.py`와 필드 단위로 정렬된 snake_case 타입이다. `lib/domain.ts`는 죽은 파일이니 건드리지 않는다.

- [ ] **Step 1: 타입 추가**

`lib/types.ts`의 `export interface Candidate` 바로 위에 추가:

```ts
export interface ListingTerms {
  listing_kind: "DEMO_SYNTHETIC";
  deposit_krw: number;
  monthly_rent_krw: number;
  maintenance_fee_krw?: number | null;
  area_m2: number;
  floor: number;
}
```

`Candidate`에 필드 추가:

```ts
  listing?: ListingTerms | null;
```

- [ ] **Step 2: 타입 검사**

Run: `npm run typecheck`
Expected: 통과 (아직 아무도 `listing`을 읽지 않으므로 변화 없음)

- [ ] **Step 3: 커밋**

```bash
git add lib/types.ts
git commit -m "feat(web): mirror the listing terms type"
```

---

## Task 6: 지도 마커와 후보 카드 (두 표면 모두)

**Files:**
- Create: `lib/format.ts`
- Modify: `components/KakaoMap.tsx` (Workspace 지도)
- Modify: `components/kb/KbMap.tsx` (KbShell 지도)
- Modify: `components/Workspace.tsx` (후보 카드)
- Modify: `components/kb/JarimaegimPanel.tsx` (KbShell 후보 목록)
- Modify: `components/kb/KbShell.tsx` (거짓이 된 안내 문구)
- Modify: `app/globals.css`

`ProvenanceBar`는 손대지 않는다. 두 표면 모두 이미 붙여 쓰고 있고, `ListingService`가 `source_name`을 "시연용 생성 데이터"로, `limitations`를 경고 문구로 채우므로 자동으로 라벨이 나온다.

- [ ] **Step 1: 금액 포맷 헬퍼**

`lib/format.ts`:

```ts
/** 4,580,000 → "458만". 지도 핀과 후보 카드가 같은 표기를 쓰도록 한 곳에 둔다. */
export function manwon(krw: number): string {
  return `${Math.round(krw / 10_000).toLocaleString("ko-KR")}만`;
}
```

- [ ] **Step 2: Workspace 지도 마커**

`components/KakaoMap.tsx`에서 마커 라벨을 만드는 부분이 현재 이렇다:

```ts
node.textContent=`${index+1} ${candidate.name}`;
```

교체한다:

```ts
node.textContent=`${index+1} ${candidate.name}`;
if(candidate.listing){node.classList.add("has-listing");const terms=document.createElement("small");terms.textContent=`${candidate.listing.area_m2}㎡ · 보 ${manwon(candidate.listing.deposit_krw)} / 월 ${manwon(candidate.listing.monthly_rent_krw)}`;const chip=document.createElement("i");chip.className="demo-chip";chip.textContent="시연용";node.append(chip,terms);}
```

파일 상단에 `import { manwon } from "@/lib/format";`를 추가한다.

- [ ] **Step 3: KbShell 지도 마커**

`components/kb/KbMap.tsx`의 `markerNode()`를 교체한다. 기존 `kb-marker-name` / `kb-marker-value` 구조는 유지한다.

```ts
function markerNode(candidate: Candidate, rank: number, isFocused: boolean, onFocus: (id: string) => void) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "kb-marker";
  node.dataset.grade = candidate.evidence_grade;
  if (candidate.listing) node.dataset.demo = "true";
  if (isFocused) node.dataset.focused = "true";
  const listing = candidate.listing;
  const spoken = listing ? ` ${listing.area_m2}제곱미터 보증금 ${manwon(listing.deposit_krw)}원 월세 ${manwon(listing.monthly_rent_krw)}원 시연용 데이터` : "";
  node.setAttribute("aria-label", `${candidate.name} ${EVIDENCE_BADGES[candidate.evidence_grade]}${spoken}`);
  const head = document.createElement("span");
  head.className = "kb-marker-head";
  const name = document.createElement("span");
  name.className = "kb-marker-name";
  name.textContent = `${rank}. ${candidate.name}`;
  const value = document.createElement("span");
  value.className = "kb-marker-value";
  value.textContent = candidate.evidence_grade;
  head.append(name, value);
  node.append(head);
  if (listing) {
    const chip = document.createElement("span");
    chip.className = "kb-marker-demo";
    chip.textContent = "시연용";
    name.append(chip);
    const line = document.createElement("span");
    line.className = "kb-marker-terms";
    line.textContent = `${listing.area_m2}㎡ · 보 ${manwon(listing.deposit_krw)} / 월 ${manwon(listing.monthly_rent_krw)}`;
    node.append(line);
  }
  node.addEventListener("click", (event) => { event.stopPropagation(); onFocus(candidate.id); });
  return node;
}
```

`import { manwon } from "@/lib/format";`를 추가한다. 핀이 두 줄이 되므로 같은 파일의 `CustomOverlay` 옵션에서 `yAnchor: 1.35`를 `yAnchor: 1.15`로 낮춘다.

- [ ] **Step 4: Workspace 후보 카드**

`components/Workspace.tsx`의 `ExploreView` 안, `<p>{candidate.road_address||candidate.address}</p>` 바로 뒤에 삽입한다:

```tsx
{candidate.listing&&<div className="listing-terms"><span className="demo-badge">시연용</span><span>{candidate.listing.area_m2}㎡</span><span>보증금 <strong>{manwon(candidate.listing.deposit_krw)}원</strong></span><span>월세 <strong>{manwon(candidate.listing.monthly_rent_krw)}원</strong></span>{candidate.listing.maintenance_fee_krw?<span>관리비 {manwon(candidate.listing.maintenance_fee_krw)}원</span>:null}</div>}
```

`import { manwon } from "@/lib/format";`를 추가한다. 이 파일은 한 줄에 여러 문장을 쓰는 밀도 높은 스타일이니 그에 맞춘다.

- [ ] **Step 5: KbShell 후보 목록**

`components/kb/JarimaegimPanel.tsx:127`의 `candidates.map(...)` 안에서 후보 이름을 렌더링하는 곳 바로 뒤에 같은 블록을 넣는다. 실제 JSX 구조를 먼저 읽고(`sed -n '125,142p' components/kb/JarimaegimPanel.tsx`) 그 구조에 맞춰 삽입한다. 이름과 주소가 어느 태그에 있는지 확인한 뒤 그 아래에 붙인다.

```tsx
{candidate.listing&&<div className="listing-terms"><span className="demo-badge">시연용</span><span>{candidate.listing.area_m2}㎡</span><span>보 <strong>{manwon(candidate.listing.deposit_krw)}</strong></span><span>월 <strong>{manwon(candidate.listing.monthly_rent_krw)}</strong></span></div>}
```

- [ ] **Step 6: 거짓이 된 안내 문구 교체**

`components/kb/KbShell.tsx:87`의 문구는 매물이 표시되는 순간 거짓이 된다:

```tsx
{flow.candidates.length === 0 && flow.trace.state !== "running" && <div className="kb-stage-notice"><strong>시연용 매물 데이터입니다</strong><p>실제 임대 매물이 아니며 계약 대상이 아닙니다. 강남·마포·서초·성동·영등포 5개 구만 준비되어 있습니다. 왼쪽 <em>자리매김</em>에서 조건을 입력하면 이 지도에 표시됩니다.</p></div>}
```

- [ ] **Step 7: CSS**

`app/globals.css` 끝에 추가한다. 기존 규칙은 건드리지 않는다.

```css
.kb-marker-head{display:flex;align-items:center;gap:6px}
.kb-marker-terms{display:block;padding:2px 8px 4px;font-size:11px;color:var(--kb-mute);white-space:nowrap}
.kb-marker-demo{margin-left:4px;padding:1px 5px;border-radius:999px;background:#8a5a00;color:#fff;font-size:10px;font-weight:600}
.real-map-label.has-listing{display:grid;gap:2px;text-align:left}
.real-map-label small{display:block;font-size:10px;opacity:.85;white-space:nowrap}
.real-map-label .demo-chip{display:inline-block;margin-left:4px;padding:0 5px;border-radius:999px;background:#8a5a00;color:#fff;font-size:9px;font-style:normal;font-weight:700}
.listing-terms{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:6px;font-size:12px;color:var(--muted)}
.listing-terms strong{color:var(--text)}
.demo-badge{padding:1px 6px;border-radius:999px;background:#8a5a00;color:#fff;font-size:10px;font-weight:700}
```

- [ ] **Step 8: 검증**

Run: `npm run lint && npm run typecheck`
Expected: 둘 다 통과, 경고 0

- [ ] **Step 9: 커밋**

```bash
git add lib/format.ts components/KakaoMap.tsx components/kb/KbMap.tsx components/Workspace.tsx components/kb/JarimaegimPanel.tsx components/kb/KbShell.tsx app/globals.css
git commit -m "feat(web): show listing terms and a demo badge on both surfaces"
```

---

## Task 7: 비용 단계 프리필 (보증금만)

**Files:**
- Modify: `components/Workspace.tsx`

**월세와 관리비는 넣지 않는다.** `CostView`는 창업 소요자금 계산기이고 합계에서 자기자본을 빼 조달 차이를 낸다. 매달 나가는 월세를 그 합계에 더하면 총소요자금이 왜곡된다. 매물의 월세·관리비는 Task 6에서 후보 카드에 이미 보인다.

KbShell에는 비용 단계가 없으므로 이 태스크는 `Workspace`만 건드린다.

- [ ] **Step 1: `ESTIMATE` 출처 라벨 지원**

`components/Workspace.tsx`의 `CostView` 안, 출처를 렌더링하는 곳이 지금 두 값만 안다:

```tsx
<em className={`source ${item.source_type.toLowerCase()}`}>{item.source_type==="USER"?"사용자 입력":"확인 불가"}</em>
```

세 값을 구분하도록 바꾼다. `ESTIMATE`를 "확인 불가"로 보여주면 사용자가 값이 채워진 이유를 알 수 없다:

```tsx
<em className={`source ${item.source_type.toLowerCase()}`}>{item.source_type==="USER"?"사용자 입력":item.source_type==="ESTIMATE"?"시연용 매물 조건":"확인 불가"}</em>
```

- [ ] **Step 2: 확정 매물의 보증금으로 초기값 세팅**

`CostView`의 `useState<CostItem[]>([...])` 초기값은 지금 하드코딩된 배열이다. 확정 매물이 있으면 `deposit` 행만 채운다.

`CostView` 함수 본문 맨 위, `const [items,setItems]=useState...` 앞에 넣는다:

```tsx
const deposit=committed?.listing?.deposit_krw??null;
```

그리고 `useState` 초기값의 첫 항목을 바꾼다:

```tsx
{key:"deposit",label:"임차보증금",min_krw:deposit,max_krw:deposit,source_type:deposit?"ESTIMATE":"USER",note:deposit?"시연용 매물 조건에서 자동 입력":undefined}
```

나머지 네 항목(`premium`, `interior`, `inventory`, `reserve`)은 그대로 둔다.

`useState`의 초기값은 첫 렌더에서만 쓰이므로, 사용자가 값을 고친 뒤 다른 매물을 확정해도 입력이 덮어써지지 않는다. 이것이 원하는 동작이다 — 사용자가 고친 값을 자동 입력이 되돌리면 안 된다.

- [ ] **Step 3: 사용자가 고치면 USER로 승격**

`update()` 함수가 지금 값만 바꾸고 출처는 그대로 둔다. 사용자가 손댄 값은 더 이상 추정치가 아니다:

```tsx
function update(key:string,side:"min_krw"|"max_krw",value:number){setItems(prev=>prev.map(item=>item.key===key?{...item,[side]:value,source_type:item.source_type==="ESTIMATE"?"USER":item.source_type,note:item.source_type==="ESTIMATE"?undefined:item.note}:item))}
```

- [ ] **Step 4: 거짓이 된 토스트 교체**

`components/Workspace.tsx:32`의 토스트가 "비용 값은 자동으로 만들지 않습니다"라고 말한다. 보증금을 자동으로 채우므로 이 문장은 거짓이 된다:

```tsx
function commitCandidate(id:string){setCommitted(id);setTrace(true);setTimeout(()=>setTrace(false),650);showToast("계획 기준 후보를 확정했습니다. 시연용 매물의 보증금만 비용에 채웠으니 확인해 주세요.");}
```

- [ ] **Step 5: 검증**

Run: `npm run lint && npm run typecheck`
Expected: 통과

- [ ] **Step 6: 커밋**

```bash
git add components/Workspace.tsx
git commit -m "feat(web): prefill the deposit from the chosen listing as an estimate"
```
## Task 8: 매물 영속화와 PDF 라벨

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/document_store.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_pdf_listing.py`

`render_case_pdf`는 현재 `case["inputs"]`만 렌더링한다. 매물을 PDF에 넣으려면 케이스가 확정 매물을 기억해야 한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_pdf_listing.py`:

```python
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
    # reportlab writes text into the content stream; the label must survive into the file.
    assert "demo-" in text or "시연용" in text


def test_a_case_without_a_listing_still_renders():
    payload = render_case_pdf({"id": "x", "title": "t", "version": 1, "inputs": {"industry": "카페"}},
                              {"document_id": "d2", "template": "cost"})
    assert payload.startswith(b"%PDF")
```

두 번째 테스트가 중요하다: 매물 없는 케이스도 계속 PDF를 만들 수 있어야 한다.

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_pdf_listing.py` -v
Expected: 첫 테스트 FAIL (라벨이 PDF에 없음)

- [ ] **Step 3: `CaseInput`에 확정 매물 필드 추가**

`backend/app/models.py`의 `CaseInput`에 추가:

```python
    committed_listing_id: str | None = Field(default=None, max_length=64)
```

기본값이 `None`이므로 기존 케이스 생성 요청은 그대로 통과한다.

- [ ] **Step 4: PDF에 매물 블록 추가**

`backend/app/document_store.py`의 `render_case_pdf`에서, `story.extend([...])`로 끝나는 마지막 줄 **앞에** 삽입한다:

```python
    listing_id = case.get("inputs", {}).get("committed_listing_id")
    if listing_id:
        story.extend([
            Spacer(1, 16),
            Paragraph("선택한 자리 (시연용 생성 데이터)", styles["Heading2"]),
            Paragraph(f"매물 ID: {listing_id}", styles["BodyText"]),
            Paragraph("실제 임대 매물이 아니며 계약 대상이 아닙니다. 위치는 실제 상가 좌표이나 "
                      "면적·월세는 서울교통공사 지하상가 임대정보 분포에서 생성했고, 보증금·관리비·층은 가정값입니다.",
                      styles["BodyText"]),
        ])
```

매물 조건 자체가 아니라 ID와 라벨만 넣는 이유: `document_store`는 `ListingService`를 모르고, 알게 하면 순환 의존이 생긴다. ID와 경고 문구만으로 "이 문서가 시연용 매물을 근거로 한다"는 사실은 충분히 전달된다.

- [ ] **Step 5: 확정 매물을 케이스에 저장**

`committed_listing_id`를 추가해도 아무도 값을 넣지 않으면 PDF는 영원히 비어 있다. `components/Workspace.tsx`의 `commitCandidate`가 케이스를 패치하게 한다.

`lib/api.ts:43`에 이미 `updateCase(id, version, inputs)`가 있다 (`If-Match`로 낙관적 동시성). `commitCandidate`를 async로 바꾼다:

```tsx
async function commitCandidate(id:string){setCommitted(id);setTrace(true);setTimeout(()=>setTrace(false),650);showToast("계획 기준 후보를 확정했습니다. 시연용 매물의 보증금만 비용에 채웠으니 확인해 주세요.");if(!caseData)return;try{const updated=await api.updateCase(caseId,caseData.version,{committed_listing_id:id});setCaseData(updated);}catch{/* 확정 자체는 로컬 상태로 이미 반영됐다. 저장 실패가 화면을 되돌리면 안 된다. */}}
```

저장에 실패해도 화면을 되돌리지 않는 이유: 확정은 사용자가 방금 한 행동이고, 서버 저장 실패로 그것을 취소하면 사용자가 무엇을 잃었는지 알 수 없다. 저장이 안 되면 PDF에 매물이 안 실릴 뿐이다.

`ExploreView`에 넘기는 `onCommit` prop 타입이 `(id:string)=>void`이므로 async 함수를 넘겨도 타입은 맞는다.

`lib/types.ts`의 `CaseInput`에도 필드를 추가한다:

```ts
  committed_listing_id?: string | null;
```

- [ ] **Step 6: 통과 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_pdf_listing.py` -v
Expected: PASS, 2 tests

Run: `npm run typecheck`
Expected: 통과

전체: `npm run api:test`
Expected: 81 passed

- [ ] **Step 7: 커밋**

```bash
git add backend/app/models.py backend/app/document_store.py backend/tests/test_pdf_listing.py components/Workspace.tsx lib/types.ts
git commit -m "feat(api): carry the demo listing label into the pdf"
```

---

## Task 9: AI 가드레일

**Files:**
- Modify: `backend/app/services.py`
- Test: `backend/tests/test_ai_prompt.py`

현재 프롬프트는 "새로운 숫자를 만들지 말 것"까지만 지시한다. 매물 조건이 케이스 요약에 들어가면 AI가 이를 실제 매물로 단정해 서술할 수 있다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_ai_prompt.py`:

```python
from app.config import Settings
from app.services import AIService


def test_prompt_tells_the_model_the_listings_are_not_real():
    service = AIService(Settings(openai_api_key="", ai_chat_model=""))
    prompt = service.build_prompt("이 매물 계약해도 되나요?", "강남구 카페, 보증금 5,600만원")
    assert "시연용" in prompt
    assert "실제 임대 매물이 아" in prompt


def test_prompt_still_forbids_inventing_numbers():
    service = AIService(Settings(openai_api_key="", ai_chat_model=""))
    prompt = service.build_prompt("질문", "요약")
    assert "만들지 마세요" in prompt
    assert "질문" in prompt and "요약" in prompt
```

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_ai_prompt.py` -v
Expected: FAIL — `AttributeError: 'AIService' object has no attribute 'build_prompt'`

- [ ] **Step 3: 프롬프트를 메서드로 빼고 문구 추가**

`backend/app/services.py`의 `AIService`에 메서드를 추가하고 `explain`이 그것을 쓰게 한다. 인라인 문자열을 메서드로 빼는 이유는 테스트 가능하게 만들기 위해서다.

```python
    def build_prompt(self, user_text: str, case_summary: str) -> str:
        return (
            "당신은 자리매김의 설명 도우미입니다. 새로운 숫자, 점수, 비용, 금융 자격을 만들지 마세요. "
            "제공된 케이스 요약 안의 사실만 짧고 명확한 한국어로 설명하세요. 개인정보 입력을 요청하지 마세요. "
            "요약에 매물 조건이 있다면 그것은 시연용 생성 데이터이며 실제 임대 매물이 아닙니다. "
            "계약 가능 여부나 실제 거래 조건을 단정하지 말고, 시연용 데이터임을 밝히세요. "
            "좁은 사이드 패널에 표시되므로 5문장 이내로 답하세요.\n"
            f"케이스: {case_summary}\n사용자 질문: {user_text}"
        )
```

`explain` 안의 `prompt = (...)` 블록을 `prompt = self.build_prompt(user_text, case_summary)`로 교체한다.

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_ai_prompt.py` -v
Expected: PASS, 2 tests

- [ ] **Step 5: 커밋**

```bash
git add backend/app/services.py backend/tests/test_ai_prompt.py
git commit -m "feat(api): tell the assistant the listings are demo data"
```

---

## Task 10: 시드 스크립트

**Files:**
- Create: `scripts/seed-listings.mjs`
- Modify: `package.json`

- [ ] **Step 1: 스크립트 작성**

`scripts/seed-listings.mjs`:

```js
import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SEED = join(ROOT, "data", "listings.seoul.json");

/** Minimal .env reader; the repo has no dotenv dependency. Never print the values. */
async function env(name) {
  const text = await fs.readFile(join(ROOT, ".env"), "utf8");
  const line = text.split("\n").find((entry) => entry.startsWith(`${name}=`));
  return line ? line.slice(name.length + 1).trim() : "";
}

async function main() {
  const url = await env("SUPABASE_URL");
  const key = await env("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) {
    console.log("SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY가 없어 적재를 건너뜁니다. 백엔드는 시드 JSON을 그대로 읽습니다.");
    return;
  }
  const payload = JSON.parse(await fs.readFile(SEED, "utf8"));
  const rows = payload.listings.map((entry) => ({
    id: entry.id, district: entry.district, name: entry.name, address: entry.address,
    latitude: entry.latitude, longitude: entry.longitude,
    listing_kind: entry.listing.listing_kind, deposit_krw: entry.listing.deposit_krw,
    monthly_rent_krw: entry.listing.monthly_rent_krw, maintenance_fee_krw: entry.listing.maintenance_fee_krw,
    area_m2: entry.listing.area_m2, floor: entry.listing.floor,
  }));
  const unlabelled = rows.filter((row) => row.listing_kind !== "DEMO_SYNTHETIC");
  if (unlabelled.length > 0) throw new Error(`라벨 없는 행 ${unlabelled.length}건이 있어 적재를 중단합니다.`);

  const response = await fetch(`${url}/rest/v1/listings`, {
    method: "POST",
    headers: {
      apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates,return=minimal",
    },
    body: JSON.stringify(rows),
  });
  if (!response.ok) throw new Error(`적재 실패 ${response.status}: ${await response.text()}`);
  console.log(`매물 ${rows.length}건 적재 완료.`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
```

`Prefer: resolution=merge-duplicates`로 upsert가 되므로 재실행이 안전하다. 가드는 `pathToFileURL` 패턴을 쓴다 — 저장소 경로에 공백이 있어 템플릿 리터럴 비교는 절대 일치하지 않는다.

- [ ] **Step 2: npm 스크립트 추가**

`package.json`의 `"pipeline:verify"` 아래:

```json
    "seed:listings": "node scripts/seed-listings.mjs",
```

- [ ] **Step 3: 키 없는 환경에서 안전한지 확인**

Run: `npm run seed:listings`
Expected: Supabase 키가 있으면 275건 적재. 없으면 건너뛴다는 안내가 나오고 종료 코드 0.

**주의:** 이 명령은 원격 DB에 씁니다. 실행 전 사용자에게 확인받으세요. Task 1의 마이그레이션이 아직 적용되지 않았다면 테이블이 없어 실패합니다 — 그 경우 실패 내용을 보고하고 마이그레이션 적용 여부를 물어보세요.

- [ ] **Step 4: 커밋**

```bash
git add scripts/seed-listings.mjs package.json
git commit -m "feat(db): seed the demo listings into supabase"
```

---

## Task 11: e2e 검증 갱신 (두 표면)

**Files:**
- Modify: `scripts/flow-check.mjs` (Workspace 경로)
- Modify: `scripts/shell-check.mjs` (KbShell 경로)

`flow-check.mjs`는 현재 "키가 없으면 후보 목록이 비어 있다"를 어서션한다. 매물은 키 없이도 나오므로 **이 어서션은 그대로 두면 깨진다.**

- [ ] **Step 1: 현재 어서션 확인**

Run: `grep -n 'integrationPending\|empty-state\|candidate-row\|kb-marker' scripts/flow-check.mjs scripts/shell-check.mjs`

`flow-check.mjs`의 `onboarding.integrationPending`이 `.empty-state` 가시성으로 판정된다. 매물이 표시되면 이 값이 `false`가 된다.

- [ ] **Step 2: flow-check 어서션 교체**

강남구 경로에서는 매물이 나오고 라벨이 DOM에 있어야 한다. `onboarding` 객체를 만드는 줄 근처에 추가한다:

```js
const listings = {
  rows: await page.locator(".candidate-row").count(),
  badges: await page.locator(".demo-badge").count(),
};
if (listings.rows === 0) throw new Error("강남구에서 시연용 매물 후보가 표시되지 않았습니다.");
if (listings.badges === 0) throw new Error("후보 카드에 시연용 배지가 없습니다.");
```

기존 `integrationPending` 기반 어서션은 제거한다. **AI 폴백 메시지와 자금 밴드 `integration_pending` 안전 상태 어서션은 그대로 둔다** — 그 둘은 여전히 키 없는 안전 상태를 지키는 검사이며, 매물과 무관하다.

온보딩에서 자치구를 고르는 부분이 강남구가 아니면 강남구로 바꾼다. 커버리지 밖 자치구를 쓰면 매물이 0건이라 이 어서션이 실패한다.

- [ ] **Step 3: shell-check 어서션 추가**

`scripts/shell-check.mjs`가 KbShell(`/`)을 연다. 매물 핀과 배지를 확인한다:

```js
const markers = {
  pins: await page.locator(".kb-marker").count(),
  demo: await page.locator(".kb-marker-demo").count(),
};
```

`shell-check.mjs`가 조건 입력까지 진행하는지 먼저 읽고(`sed -n '1,60p' scripts/shell-check.mjs`), 후보가 실제로 그려지는 지점 뒤에 어서션을 넣는다. 조건 입력 흐름이 없어 후보가 아예 안 뜨는 스크립트라면 **핀 어서션을 넣지 말고** 그 사실을 보고한다 — 억지로 흐름을 만들지 않는다.

- [ ] **Step 4: 실행**

개발 서버가 필요하다.

```bash
npm run dev > /tmp/dev.log 2>&1 &
DEV_PID=$!
sleep 15
node scripts/flow-check.mjs; FLOW=$?
node scripts/shell-check.mjs; SHELL=$?
kill $DEV_PID
echo "flow=$FLOW shell=$SHELL"
```

Expected: `flow=0 shell=0`. 실패하면 어떤 어서션이 깨졌는지, 그리고 그것이 매물 연동 때문인지 기존 흐름 문제인지 구분해 보고한다.

개발 서버를 반드시 정리한다.

- [ ] **Step 5: 커밋**

```bash
git add scripts/flow-check.mjs scripts/shell-check.mjs
git commit -m "test: assert the demo listings and their badge end to end"
```
## Task 12: 전체 검증

- [ ] **Step 1: 모든 게이트**

```bash
npm run lint
npm run typecheck
npm run api:check
npm run api:test
npm run test:pipeline
```

Expected: lint 경고 0, typecheck 통과, api:test 83 passed, test:pipeline 48 passed.

- [ ] **Step 2: 키 없는 환경 확인**

`.env`를 임시로 옮겨 키 없이도 매물이 뜨는지 본다.

```bash
mv .env .env.backup
backend/.venv/bin/python -c "
import sys; sys.path.insert(0, 'backend')
from app.config import Settings
from app.listings import ListingService
s = ListingService(Settings())
print('districts:', sorted(s.covered_districts()))
print('강남구:', len(s.search('강남구', None, 15)[0]))
"
mv .env.backup .env
```

Expected: 5개 구, 강남구 15건. **`.env` 복구를 반드시 확인한다.**

- [ ] **Step 3: 불변조건 재확인**

```bash
node -e '
const d = require("./data/listings.seoul.json");
console.log("라벨 누락:", d.listings.filter(l => l.listing.listing_kind !== "DEMO_SYNTHETIC").length);
'
grep -c 'DEMO_SYNTHETIC' backend/app/models.py backend/app/listings.py lib/types.ts supabase/migrations/202607270001_listings.sql
```

Expected: 라벨 누락 0. 네 파일 모두 `DEMO_SYNTHETIC`을 최소 1회 포함.

- [ ] **Step 4: 커밋**

```bash
git add -A
git commit -m "chore: verify the listing integration end to end"
```

---

## 완료 조건

- 강남·마포·서초·성동·영등포에서 매물 핀이 **두 지도 모두에** 뜨고, 각 핀에 `시연용` 배지와 보증금·월세가 보인다
- 나머지 20개 구는 빈 상태 + 커버리지 안내 문구를 보여준다 (오류가 아니다)
- 매물을 고르면 **보증금만** 비용 단계에 `ESTIMATE`로 채워지고 "시연용 매물 조건"으로 표시된다. 월세는 운영비라 창업 소요자금 합계에 넣지 않는다. 사용자가 값을 고치면 `USER`로 승격된다
- `DEMO_SYNTHETIC` 라벨이 pydantic Literal · DB CHECK · 지도 핀 · 카드 · ProvenanceBar · PDF 여섯 곳에서 강제된다
- Supabase 키가 없어도 시드 JSON으로 동작한다
- `npm run api:test` 83개, `npm run test:pipeline` 48개, `flow-check.mjs`와 `shell-check.mjs` 통과

## 알려진 한계

- PDF는 매물 ID와 경고 문구만 담고 조건 수치는 담지 않는다. `document_store`가 `ListingService`를 알면 순환 의존이 생긴다.
- `LocationService`(Kakao 실시간 검색)는 코드에 남지만 호출되지 않는다. 실제 매물이 확보되면 되살릴 자리다.
- 마커 클러스터링이 없으므로 `LocationSearch.limit` 상한 15를 유지해야 한다.
