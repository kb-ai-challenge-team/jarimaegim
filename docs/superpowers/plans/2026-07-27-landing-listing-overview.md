# 첫 진입 매물 개요 지도 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 조건을 입력하지 않고 `/`에 들어온 사용자에게, 서울 전역 줌에서 5개 구 요약 핀을 보여주고 구를 누르면 그 구의 매물 55건이 펼쳐지게 한다.

**Architecture:** 케이스 없이 조회할 수 있는 공개 엔드포인트 두 개를 만든다 — `GET /api/v1/listings/summary`(구별 집계)와 `GET /api/v1/listings?district=`(구별 목록). 둘 다 세션을 요구하지 않는다. `KbMap`은 지금 `Candidate[]`만 그리므로, 요약 핀을 그릴 수 있도록 오버레이 종류를 하나 더 받는다. `KbShell`은 조건 입력 전에는 개요를, 조건 입력 후에는 기존 후보를 그대로 보여준다.

**Tech Stack:** FastAPI + pydantic (backend/.venv, Python 3.12, pytest), Next.js 16 App Router + TypeScript, Kakao Maps SDK, playwright-core (e2e)

**선행 조건:** `backend/app/listings.py`의 `ListingService`가 이미 5개 구 275건을 로드하고 `covered_districts()`, `search(district, budget_krw, limit)`, `get(id)`를 제공한다. 이 계획은 그 서비스에 집계 메서드를 더한다.

**범위 밖:** 마커 클러스터링, 매물 필터(가격·면적), 실제 매물 연동, 지도 위 검색.

---

## 결정 사항

| 항목 | 결정 | 이유 |
| --- | --- | --- |
| 초기 표시 | 구별 요약 핀 5개 → 클릭 시 펼침 | 프로덕션 실측에서 한 구 11개 마커도 서로 포개져 조건 줄이 안 읽혔다. 275건을 한 번에 찍으면 판독 불가 |
| 세션 | 요구하지 않음 | 매물은 사용자 데이터가 아닌 공용 참조 데이터이고 Supabase RLS도 익명 읽기를 허용한다. 둘러보기만 하는 사람에게 쿠키를 발급하지 않는다 |
| 요약에 담을 값 | 구 이름, 건수, 월세 중앙값, 대표 좌표 | 지도 핀 한 줄에 들어가는 최소한. 평균이 아니라 중앙값을 쓰는 이유는 이상치에 끌리지 않기 때문 |

---

## 현재 코드 상태 (읽고 확인한 사실)

- `components/kb/KbShell.tsx:73` — `<KbMap candidates={aiActive ? flow.candidates : []} focused={flow.focused} onFocus={flow.setFocused} aiActive={aiActive} />`
- `components/kb/KbShell.tsx:87` — 후보가 0건이고 트레이스가 돌지 않을 때 `kb-stage-notice`를 띄운다. 개요가 생기면 이 문구도 바뀌어야 한다
- `components/kb/KbMap.tsx:48` — `KbMap({ candidates, focused, onFocus, aiActive })`
- `components/kb/KbMap.tsx:61` — 초기 지도는 `SEOUL_CENTER`, `level: 6`
- `components/kb/KbMap.tsx:76~96` — 오버레이 재구성 effect. `candidates`가 바뀔 때마다 전부 지우고 다시 그린 뒤 `setBounds`로 맞춘다
- `lib/use-jarimaegim.ts:353` — 훅이 반환하는 값 목록. 여기에 개요 상태를 더한다
- `lib/api.ts:44` — `searchLocations(caseId, inputs)`가 `case_id`를 요구한다. 개요는 이 경로를 쓸 수 없다
- 백엔드 pytest는 `backend/tests/`. **단일 파일은 `backend/.venv/bin/python -m pytest backend/tests/<파일> -v`로 돌린다** — `npm run api:test -- <경로>`는 스크립트가 `cd backend`를 먼저 해서 경로가 이중 중첩된다. 전체는 `npm run api:test`, 현재 **90개 통과**
- `npm run lint`는 현재 경고 0. 유지한다

---

## File Structure

| 파일 | 책임 |
| --- | --- |
| `backend/app/models.py` | `DistrictSummary` 응답 모델 |
| `backend/app/listings.py` | `summary()` 집계 메서드 |
| `backend/app/main.py` | 공개 엔드포인트 2개 |
| `backend/tests/test_listings_summary.py` | 집계 단위 테스트 |
| `backend/tests/test_api_listings_public.py` | 엔드포인트 계약 테스트 |
| `lib/types.ts` | `DistrictSummary` 미러 |
| `lib/api.ts` | `getListingSummary()`, `getListings(district)` |
| `components/kb/KbMap.tsx` | 요약 핀 렌더링 + 클릭 핸들러 |
| `lib/use-jarimaegim.ts` | 개요 상태와 구 선택 |
| `components/kb/KbShell.tsx` | 개요/후보 전환, 안내 문구 |
| `app/globals.css` | 요약 핀 스타일 |
| `scripts/shell-check.mjs` | 첫 진입 개요 어서션 |

---

## Task 1: 구별 집계

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/listings.py`
- Test: `backend/tests/test_listings_summary.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_listings_summary.py`:

```python
import json

import pytest

from app.config import Settings
from app.listings import ListingService


def row(listing_id: str, district: str, lat: float, lng: float, rent: int, deposit: int = 20_000_000) -> dict:
    return {"id": listing_id, "name": f"{district} 상가", "address": f"서울 {district}", "district": district,
            "latitude": lat, "longitude": lng,
            "listing": {"listing_kind": "DEMO_SYNTHETIC", "deposit_krw": deposit, "monthly_rent_krw": rent,
                        "maintenance_fee_krw": None, "area_m2": 30.0, "floor": 1}}


ROWS = [
    row("a1", "강남구", 37.50, 127.05, 1_000_000),
    row("a2", "강남구", 37.52, 127.03, 12_000_000),
    row("a3", "강남구", 37.54, 127.07, 2_000_000),
    row("b1", "마포구", 37.55, 126.92, 5_000_000),
    row("b2", "마포구", 37.57, 126.90, 1_000_000),
]


@pytest.fixture
def service(tmp_path):
    seed = tmp_path / "listings.seoul.json"
    seed.write_text(json.dumps({"listings": ROWS}), encoding="utf-8")
    return ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=seed)


def test_summary_has_one_entry_per_covered_district(service):
    summaries = service.summary()
    assert [entry.district for entry in summaries] == ["강남구", "마포구"]


def test_summary_counts_listings(service):
    counts = {entry.district: entry.count for entry in service.summary()}
    assert counts == {"강남구": 3, "마포구": 2}


def test_summary_reports_the_median_rent_not_the_mean(service):
    rents = {entry.district: entry.median_monthly_rent_krw for entry in service.summary()}
    # 강남 1M/2M/12M -> median 2M but mean 5M, so this fails if the mean is used.
    # 마포 1M/5M -> median 3M, the midpoint of an even-sized sample.
    assert rents == {"강남구": 2_000_000, "마포구": 3_000_000}


def test_summary_pin_sits_at_the_centre_of_its_listings(service):
    gangnam = next(entry for entry in service.summary() if entry.district == "강남구")
    assert gangnam.latitude == pytest.approx((37.50 + 37.52 + 37.54) / 3)
    assert gangnam.longitude == pytest.approx((127.05 + 127.03 + 127.07) / 3)


def test_summary_is_sorted_by_district_name(service):
    districts = [entry.district for entry in service.summary()]
    assert districts == sorted(districts)


def test_summary_of_an_empty_service_is_empty(tmp_path):
    empty = ListingService(Settings(supabase_url="", supabase_service_role_key=""), seed_path=tmp_path / "absent.json")
    assert empty.summary() == []
```

강남구 표본을 한쪽으로 치우치게 잡은 이유: 1M/2M/12M은 중앙값 2M, 평균 5M이다. 구현이 평균을 쓰면 이 테스트가 깨진다. 마포구 1M/5M은 중앙값과 평균이 둘 다 3M이라 판별은 못 하지만, 짝수 개 표본의 중앙값이 두 값의 중점이라는 것을 검증한다.

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_listings_summary.py -v`
Expected: FAIL — `AttributeError: 'ListingService' object has no attribute 'summary'`

- [ ] **Step 3: 응답 모델 추가**

`backend/app/models.py`의 `class ListingTerms` 아래에 추가:

```python
class DistrictSummary(BaseModel):
    """One map pin per covered district, shown before the user enters any condition."""
    district: str
    count: int = Field(ge=0)
    median_monthly_rent_krw: int = Field(ge=0)
    latitude: float
    longitude: float
```

- [ ] **Step 4: 집계 구현**

`backend/app/listings.py` 상단 import에 `from statistics import median`을 더하고, `DistrictSummary`를 `.models` import에 추가한다. 그리고 `covered_districts()` 아래에 추가:

```python
    def summary(self) -> list[DistrictSummary]:
        """Per-district aggregate for the landing map. Median rather than mean so one
        expensive unit does not drag a district's headline number."""
        entries = []
        for district in sorted(self._by_district):
            bucket = self._by_district[district]
            entries.append(DistrictSummary(
                district=district,
                count=len(bucket),
                median_monthly_rent_krw=round(median(c.listing.monthly_rent_krw for c in bucket)),
                latitude=sum(c.latitude for c in bucket) / len(bucket),
                longitude=sum(c.longitude for c in bucket) / len(bucket),
            ))
        return entries
```

- [ ] **Step 5: 통과 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_listings_summary.py -v`
Expected: PASS, 6 tests

전체: `npm run api:test` → 96 passed (90 + 6)

- [ ] **Step 6: 실제 시드로 확인**

```bash
backend/.venv/bin/python -c "
import sys; sys.path.insert(0,'backend')
from app.config import Settings
from app.listings import ListingService
for e in ListingService(Settings(supabase_url='', supabase_service_role_key='')).summary():
    print(f'{e.district} {e.count}건 월세중앙값 {e.median_monthly_rent_krw:,}원 ({e.latitude:.4f},{e.longitude:.4f})')
"
```

Expected: 5개 구 각 55건, 좌표가 해당 구 범위 안. 건수가 55가 아니거나 좌표가 서울 밖이면 멈추고 보고한다.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/models.py backend/app/listings.py backend/tests/test_listings_summary.py
git commit -m "feat(api): aggregate listings per district for the landing map"
```

---

## Task 2: 공개 엔드포인트

**Files:**
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_api_listings_public.py`

두 엔드포인트 모두 `current_session`을 쓰지 않는다. 매물은 공용 참조 데이터이고, 둘러보기만 하는 사람에게 익명 쿠키를 발급하지 않기 위해서다.

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_api_listings_public.py`:

```python
from fastapi.testclient import TestClient

from app.main import app


def test_summary_needs_no_session():
    with TestClient(app) as client:
        response = client.get("/api/v1/listings/summary")
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["districts"]) == 5
        assert all(entry["count"] > 0 for entry in body["districts"])
        assert "Set-Cookie" not in response.headers


def test_summary_entries_carry_a_pin_position():
    with TestClient(app) as client:
        entry = client.get("/api/v1/listings/summary").json()["districts"][0]
        assert 37.0 < entry["latitude"] < 38.0
        assert 126.0 < entry["longitude"] < 128.0
        assert entry["median_monthly_rent_krw"] > 0


def test_listings_for_a_covered_district_need_no_session():
    with TestClient(app) as client:
        response = client.get("/api/v1/listings", params={"district": "강남구", "limit": 15})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "success"
        assert len(body["candidates"]) == 15
        for candidate in body["candidates"]:
            assert candidate["listing"]["listing_kind"] == "DEMO_SYNTHETIC"
        assert "Set-Cookie" not in response.headers


def test_listings_for_an_uncovered_district_explain_the_coverage():
    with TestClient(app) as client:
        body = client.get("/api/v1/listings", params={"district": "노원구"}).json()
        assert body["candidates"] == []
        assert body["status"] == "empty"
        assert "강남구" in body["message"]


def test_listings_reject_a_district_outside_seoul():
    with TestClient(app) as client:
        assert client.get("/api/v1/listings", params={"district": "부산 해운대구"}).status_code == 400


def test_listings_cap_the_limit():
    with TestClient(app) as client:
        assert client.get("/api/v1/listings", params={"district": "강남구", "limit": 500}).status_code == 422
```

`Set-Cookie` 어서션이 이 태스크의 핵심이다. 세션을 요구하지 않는다는 결정이 코드로 지켜지는지 확인한다.

- [ ] **Step 2: 실패 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_api_listings_public.py -v`
Expected: FAIL — 404, 두 경로 모두 없음

- [ ] **Step 3: 구현**

`backend/app/main.py`에 추가한다. `search_locations` 아래가 자연스럽다.

```python
@app.get("/api/v1/listings/summary")
async def listing_summary():
    """Public: per-district aggregate for the landing map. No session — listings are
    reference data, and browsing must not mint an anonymous cookie."""
    return {"districts": [entry.model_dump(mode="json") for entry in listings_service.summary()]}


@app.get("/api/v1/listings")
async def public_listings(district: str = Query(min_length=1, max_length=20), limit: int = Query(default=15, ge=1, le=55)):
    """Public: one district's demo listings. No session, for the same reason as the summary."""
    if district not in SEOUL_DISTRICTS:
        raise HTTPException(400, {"code": "VALIDATION_ERROR", "message": "서울 25개 자치구 중에서 선택해 주세요."})
    candidates, status, message = listings_service.search(district, None, limit)
    return {"candidates": [candidate.model_dump(mode="json") for candidate in candidates], "status": status, "message": message}
```

`budget_krw`에 `None`을 넘기는 이유: 개요 화면에는 아직 예산 조건이 없다. 조건을 입력한 뒤에는 기존 `POST /locations/search`가 예산 필터를 적용한다.

`Query`가 이미 import되어 있는지 확인하고, 없으면 `from fastapi import ... Query`에 더한다.

- [ ] **Step 4: 통과 확인**

Run: `backend/.venv/bin/python -m pytest backend/tests/test_api_listings_public.py -v`
Expected: PASS, 6 tests

전체: `npm run api:test` → 102 passed (96 + 6)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/main.py backend/tests/test_api_listings_public.py
git commit -m "feat(api): expose listings without a session for the landing map"
```

---

## Task 3: 프론트 타입과 API 클라이언트

**Files:**
- Modify: `lib/types.ts`
- Modify: `lib/api.ts`

- [ ] **Step 1: 타입 추가**

`lib/types.ts`의 `ListingTerms` 아래:

```ts
export interface DistrictSummary {
  district: string;
  count: number;
  median_monthly_rent_krw: number;
  latitude: number;
  longitude: number;
}
```

- [ ] **Step 2: API 함수 추가**

`lib/api.ts`의 `searchLocations` 아래에 두 줄 더한다. 파일의 기존 한 줄 스타일을 따른다.

```ts
  getListingSummary: () => request<{ districts: DistrictSummary[] }>("/listings/summary"),
  getListings: (district: string, limit = 15) => request<{ candidates: Candidate[]; status: "success" | "empty"; message?: string }>(`/listings?district=${encodeURIComponent(district)}&limit=${limit}`),
```

`lib/api.ts` 상단의 타입 import에 `DistrictSummary`를 더한다.

- [ ] **Step 3: 검증**

Run: `npm run typecheck` — 통과. `npm run lint` — 경고 0.

- [ ] **Step 4: 커밋**

```bash
git add lib/types.ts lib/api.ts
git commit -m "feat(web): add the public listing endpoints to the api client"
```

---

## Task 4: 요약 핀 렌더링

**Files:**
- Modify: `components/kb/KbMap.tsx`
- Modify: `app/globals.css`

`KbMap`은 지금 `Candidate[]`만 그린다. 요약 핀을 그리려면 오버레이 종류가 하나 더 필요하다. **후보 렌더링 로직은 건드리지 않는다** — 조건 입력 후 동작이 회귀하면 안 된다.

- [ ] **Step 1: 요약 핀 노드**

`components/kb/KbMap.tsx`의 `markerNode()` 아래에 추가:

```ts
/** Landing pin: one per covered district, before any condition is entered. */
function summaryNode(entry: DistrictSummary, onSelect: (district: string) => void) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "kb-district-pin";
  node.setAttribute("aria-label", `${entry.district} 시연용 매물 ${entry.count}건, 월세 중앙값 ${manwon(entry.median_monthly_rent_krw)}원. 눌러서 매물 보기`);
  const name = document.createElement("strong");
  name.textContent = entry.district;
  const count = document.createElement("span");
  count.textContent = `${entry.count}건`;
  const rent = document.createElement("small");
  rent.textContent = `월 ${manwon(entry.median_monthly_rent_krw)}`;
  node.append(name, count, rent);
  node.addEventListener("click", (event) => { event.stopPropagation(); onSelect(entry.district); });
  return node;
}
```

`import type { Candidate, DistrictSummary } from "@/lib/types";`로 타입을 더한다.

- [ ] **Step 2: props 확장**

시그니처를 바꾼다. 기존 네 개는 그대로 두고 두 개를 더한다:

```ts
export function KbMap({ candidates, summary, focused, onFocus, onSelectDistrict, aiActive }: { candidates: Candidate[]; summary: DistrictSummary[]; focused: string | null; onFocus: (id: string) => void; onSelectDistrict: (district: string) => void; aiActive: boolean }) {
```

- [ ] **Step 3: 요약 오버레이 effect 추가**

기존 후보 오버레이 effect 아래에 별도 effect를 둔다. 두 오버레이 집합을 각자의 ref로 관리해야 서로를 지우지 않는다. 파일 상단의 `overlaysRef` 옆에 추가:

```ts
  const summaryOverlaysRef = useRef<KakaoOverlay[]>([]);
```

그리고 effect:

```ts
  // District summary pins. Shown only while there are no candidates, so the two pin
  // kinds never occupy the map at the same time.
  useEffect(() => {
    const maps = mapsRef.current, map = mapRef.current;
    if (!maps || !map) return;
    summaryOverlaysRef.current.forEach((overlay) => overlay.setMap(null));
    summaryOverlaysRef.current = [];
    if (candidates.length > 0 || summary.length === 0) return;
    summaryOverlaysRef.current = summary.map((entry) => {
      const overlay = new maps.CustomOverlay({
        position: new maps.LatLng(entry.latitude, entry.longitude),
        content: summaryNode(entry, onSelectDistrict), yAnchor: 1.1, zIndex: 20, clickable: true
      });
      overlay.setMap(map);
      return overlay;
    });
    const bounds = new maps.LatLngBounds();
    summary.forEach((entry) => bounds.extend(new maps.LatLng(entry.latitude, entry.longitude)));
    if (!bounds.isEmpty()) map.setBounds(bounds, 100, 100, 100, 100);
  }, [summary, candidates.length, onSelectDistrict, state]);
```

`candidates.length > 0`일 때 요약 핀을 지우는 것이 중요하다. 조건을 입력하면 개별 매물로 넘어가야 하고 두 종류가 겹치면 안 된다.

- [ ] **Step 4: CSS**

`app/globals.css` 끝에 추가:

```css
.kb-district-pin{display:grid;gap:1px;min-width:74px;padding:7px 11px;border:1px solid var(--kb-line);border-radius:11px;background:#fff;box-shadow:0 3px 10px rgba(0,0,0,.16);text-align:center;cursor:pointer}
.kb-district-pin:hover{border-color:var(--kb-blue)}
.kb-district-pin strong{font-size:13px;color:var(--kb-ink)}
.kb-district-pin span{font-size:12px;font-weight:700;color:var(--kb-blue)}
.kb-district-pin small{font-size:10.5px;color:var(--kb-mute)}
```

네 변수 모두 `:root`에 존재하는 것을 확인했다 (`--kb-line`, `--kb-ink`, `--kb-blue`, `--kb-mute`). 그대로 쓰면 된다.

- [ ] **Step 5: 검증**

Run: `npm run typecheck` — 이 시점에는 `KbShell`이 새 props를 아직 안 넘겨서 **실패한다.** 정상이며 Task 5에서 해소된다. 오류가 `KbShell.tsx`의 props 누락 하나뿐인지 확인하고 그 사실을 보고한다.

- [ ] **Step 6: 커밋**

```bash
git add components/kb/KbMap.tsx app/globals.css
git commit -m "feat(web): render one summary pin per district on the landing map"
```

---

## Task 5: 개요 상태와 구 선택

**Files:**
- Modify: `lib/use-jarimaegim.ts`
- Modify: `components/kb/KbShell.tsx`

- [ ] **Step 1: 훅에 개요 상태 추가**

`lib/use-jarimaegim.ts`에 상태를 더한다. 기존 상태 선언들 근처에 둔다:

```ts
  const [summary, setSummary] = useState<DistrictSummary[]>([]);
  const [overviewDistrict, setOverviewDistrict] = useState<string | null>(null);
```

마운트 시 개요를 불러온다. 기존 `useEffect(() => { api.status()... }, []);` 아래에:

```ts
  useEffect(() => { api.getListingSummary().then((r) => setSummary(r.districts)).catch(() => setSummary([])); }, []);
```

실패 시 빈 배열로 두는 이유: 개요는 보조 정보다. 못 불러왔다고 랜딩이 깨지면 안 된다.

구를 고르면 그 구 매물을 불러온다:

```ts
  const selectOverviewDistrict = useCallback(async (district: string) => {
    setOverviewDistrict(district);
    try {
      const result = await api.getListings(district, 15);
      setCandidates(result.candidates);
      setLocationState(result.status);
      if (result.candidates[0]) setFocused(result.candidates[0].id);
    } catch { setLocationState("error"); }
  }, []);
```

개요로 돌아가는 것도 필요하다:

```ts
  const clearOverviewDistrict = useCallback(() => {
    setOverviewDistrict(null); setCandidates([]); setFocused(null); setLocationState("idle");
  }, []);
```

훅의 `return {...}`에 `summary, overviewDistrict, selectOverviewDistrict, clearOverviewDistrict`를 더한다.

`import type { ... DistrictSummary ... }`를 타입 import에 더한다.

세터 이름은 확인했다 — `setCandidates`, `setLocationState`, `setFocused` 그대로다.

- [ ] **Step 2: KbShell에서 배선**

`components/kb/KbShell.tsx:73`을 바꾼다:

```tsx
      <KbMap candidates={aiActive ? flow.candidates : []} summary={aiActive ? flow.summary : []} focused={flow.focused} onFocus={flow.setFocused} onSelectDistrict={flow.selectOverviewDistrict} aiActive={aiActive} />
```

- [ ] **Step 3: 안내 문구를 상태에 맞게**

`components/kb/KbShell.tsx:87`의 `kb-stage-notice`는 지금 "조건을 입력하면 이 지도에 표시됩니다"라고 말한다. 개요가 뜨면 거짓이 된다. 세 상태를 구분한다:

```tsx
      {flow.candidates.length === 0 && flow.summary.length > 0 && flow.trace.state !== "running" && <div className="kb-stage-notice"><strong>시연용 매물 데이터입니다</strong><p>실제 임대 매물이 아니며 계약 대상이 아닙니다. 지도의 자치구를 누르면 그 구의 매물을 볼 수 있고, 왼쪽 <em>자리매김</em>에서 조건을 입력하면 조건에 맞는 매물만 남습니다.</p></div>}
      {flow.candidates.length === 0 && flow.summary.length === 0 && flow.trace.state !== "running" && <div className="kb-stage-notice"><strong>매물 데이터를 불러오지 못했습니다</strong><p>연결을 확인한 뒤 새로고침해 주세요. 값을 만들어 채우지 않습니다.</p></div>}
      {flow.overviewDistrict && flow.candidates.length > 0 && <div className="kb-stage-notice compact"><strong>{flow.overviewDistrict} 시연용 매물 {flow.candidates.length}곳</strong><button type="button" className="kb-ghost" onClick={flow.clearOverviewDistrict}>전체 자치구 보기</button></div>}
```

세 번째 블록이 개요로 돌아가는 길이다. 이것이 없으면 구를 한 번 고른 뒤 서울 전역으로 되돌아갈 방법이 없다.

- [ ] **Step 4: CSS**

`app/globals.css` 끝에:

```css
.kb-stage-notice.compact{display:flex;align-items:center;justify-content:space-between;gap:12px}
.kb-stage-notice.compact strong{font-size:13px}
```

- [ ] **Step 5: 검증**

Run: `npm run typecheck` — 통과해야 한다 (Task 4에서 남은 오류가 여기서 해소된다).
Run: `npm run lint` — 경고 0.
Run: `npm run build` — 성공.

- [ ] **Step 6: 커밋**

```bash
git add lib/use-jarimaegim.ts components/kb/KbShell.tsx app/globals.css
git commit -m "feat(web): show the district overview before any condition is entered"
```

---

## Task 6: e2e 어서션

**Files:**
- Modify: `scripts/shell-check.mjs`

- [ ] **Step 1: 첫 진입 개요 어서션 추가**

`scripts/shell-check.mjs`가 `/`를 열고 `.kb-ai-panel`을 기다린 직후, 아직 아무 조건도 넣기 전 지점에 넣는다. 정확한 위치는 파일을 읽고 첫 상호작용(`.kb-examples button` 클릭) **앞**에 둔다.

```js
await page.waitForSelector(".kb-district-pin", { timeout: 30000 });
const overview = {
  pins: await page.locator(".kb-district-pin").count(),
  labels: await page.locator(".kb-district-pin strong").allInnerTexts(),
};
```

그리고 구를 눌러 펼쳐지는지 확인한다:

```js
await page.locator(".kb-district-pin").first().click();
await page.waitForSelector(".kb-marker", { timeout: 30000 });
const drilldown = {
  markers: await page.locator(".kb-marker").count(),
  badges: await page.locator(".kb-marker-demo").count(),
  pinsGone: await page.locator(".kb-district-pin").count() === 0,
};
```

`pinsGone`이 중요하다. 두 종류의 핀이 동시에 떠 있으면 안 된다.

드릴다운 뒤에는 기존 흐름이 이어지도록 개요로 되돌린다:

```js
await page.getByRole("button", { name: "전체 자치구 보기" }).click();
await page.waitForSelector(".kb-district-pin", { timeout: 30000 });
```

그다음에 기존의 `.kb-examples button` 클릭 흐름이 이어진다.

- [ ] **Step 2: 종료 조건에 반영**

스크립트의 최종 종료 조건에 항을 더한다. 기존 항들은 그대로 둔다:

```js
overview.pins !== 5 || drilldown.markers === 0 || drilldown.badges === 0 || !drilldown.pinsGone
```

출력 요약 객체에도 `overview`와 `drilldown`을 더한다.

- [ ] **Step 3: 실행**

개발 서버가 필요하다.

```bash
npm run dev > /tmp/dev.log 2>&1 &
DEV_PID=$!
until curl -sf http://127.0.0.1:4173/api/v1/status >/dev/null 2>&1; do sleep 1; done
node scripts/shell-check.mjs; SHELL_STATUS=$?
node scripts/flow-check.mjs; FLOW=$?
kill $DEV_PID 2>/dev/null
echo "shell=$SHELL_STATUS flow=$FLOW"
```

Expected: `shell=0 flow=0`. `flow-check`도 함께 돌리는 이유는 Workspace 경로가 회귀하지 않았는지 보기 위해서다.

**개발 서버를 반드시 정리한다.** 실패하면 어떤 어서션이 깨졌는지, 그리고 원인이 이번 변경인지 기존 문제인지 구분해 보고한다.

- [ ] **Step 4: 커밋**

```bash
git add scripts/shell-check.mjs
git commit -m "test: assert the district overview and its drilldown"
```

---

## Task 7: 전체 검증

- [ ] **Step 1: 모든 게이트**

```bash
npm run lint
npm run typecheck
npm run api:check
npm run api:test
npm run test:pipeline
```

Expected: lint 경고 0, typecheck 통과, api:test 102 passed, test:pipeline 48 passed.

- [ ] **Step 2: 세션이 정말 생기지 않는지 확인**

결정 사항이 코드로 지켜지는지 직접 본다:

```bash
curl -s -D - -o /dev/null http://127.0.0.1:4173/api/v1/listings/summary | grep -i 'set-cookie' && echo "PROBLEM: cookie issued" || echo "no cookie — correct"
curl -s "http://127.0.0.1:4173/api/v1/listings?district=강남구&limit=3" | python3 -c "
import sys, json; d=json.load(sys.stdin)
print('count:', len(d['candidates']), '| labelled:', all(c['listing']['listing_kind']=='DEMO_SYNTHETIC' for c in d['candidates']))
"
```

Expected: `no cookie — correct`, count 3, labelled True.

- [ ] **Step 3: 화면 확인**

스크린샷을 찍고 **직접 본다.** 요약 핀 5개가 서울 전역에 겹치지 않고 놓였는지, 구를 눌렀을 때 개별 매물로 바뀌는지 눈으로 확인한다. 타입이 맞는 것과 화면이 맞는 것은 다르다.

- [ ] **Step 4: 커밋**

```bash
git add -A
git commit -m "chore: verify the landing overview end to end"
```

---

## 완료 조건

- 조건 없이 `/`에 들어가면 서울 전역 줌에 구별 요약 핀 5개가 뜬다 (구 이름 · 건수 · 월세 중앙값)
- 구를 누르면 그 구 매물이 개별 마커로 펼쳐지고 요약 핀은 사라진다
- "전체 자치구 보기"로 개요로 돌아갈 수 있다
- 두 공개 엔드포인트가 세션 없이 응답하고 쿠키를 발급하지 않는다
- 조건을 입력한 뒤의 기존 흐름(`POST /locations/search`, 예산 필터)이 회귀하지 않는다
- `npm run api:test` 102개, `shell-check`·`flow-check` 통과

## 알려진 한계

- 요약 핀 위치는 그 구 매물 좌표의 산술 평균이라 행정구역 중심이 아니다. 매물이 한쪽에 몰린 구에서는 핀이 치우친다.
- 구를 펼치면 15건까지만 보여준다. 55건을 다 찍으면 프로덕션에서 확인된 마커 겹침이 재현된다.
- 클러스터링은 여전히 범위 밖이다.
