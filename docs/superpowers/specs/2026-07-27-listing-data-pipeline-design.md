# 시연용 매물 데이터 파이프라인 및 지도 연동 설계

- 작성일: 2026-07-27
- 상태: 승인됨 (구현 계획 대기)
- 범위: 자리매김 지도에 임대 매물을 표시하기 위한 데이터 수집·가공·서빙·표시 전 구간

## 1. 배경과 문제

자리매김은 현재 지도에 `Candidate`(Kakao Local 장소 검색 결과, 근거등급 C)만 표시한다. 사용자가 "여기에 자리를 잡아라"라는 처방을 받아도 그 자리가 실제로 임차 가능한 대상인지 알 수 없고, 보증금·월세가 없으므로 비용 단계와 자금 단계로 서사가 이어지지 않는다.

2026-07-26 조사에서 확인된 제약:

- 네이버부동산·직방·다방·네모 모두 공식 Open API 미제공. B2B 제휴만 존재한다.
- 공공 API로 열린 매물은 온비드 공매·임대와 LH 분양임대공고뿐이며, LH는 최근 60일 서울 상가 공고가 2건이라 지도를 채울 물량이 아니다.
- 국토부 상업업무용 실거래가는 매매만 있고 전월세 오퍼레이션이 없어 상가 임대료를 공공 API로 확보할 수 없다.
- 서울교통공사 지하상가 임대정보(OA-12927)에 매물 해당 126건이 있으나 지하상가 한정이고 좌표가 역 단위다.

따라서 실제 임대 매물을 합법적으로 충분히 확보할 경로가 없다.

## 2. 결정 사항

브레인스토밍에서 확정된 전제:

| 항목 | 결정 |
| --- | --- |
| 용도 | 공모전 시연용 데모 데이터 |
| 부록 A 불변조건 1 | **유지.** 가공 데이터는 반드시 라벨링한다 |
| 수집 방법 | **공공 API·공공데이터만. 크롤링 없음** (2026-07-27 개정, §2.2) |
| 매물의 위상 | 후보지 자체를 매물로 교체 (지도 핀 = 매물) |
| 커버리지 | 강남·마포·서초·성동·영등포 5개 구, 구당 40~60건 (총 250~300건) |
| 저장·서빙 | Supabase 테이블 시드 + 시드 JSON 폴백 |
| 위치 생성 | **Kakao Local 키워드 검색의 실제 상가 좌표** (2026-07-27 개정) |
| 가격 생성 | **서울교통공사 지하상가 임대정보 실측 분포** (2026-07-27 개정) |
| 보증금 | **실측 출처 없음 → 명시적 가정으로 선언** (§2.3) |
| 라벨링 | 상시 배지 + provenance 명시 |
| 업종 범위 | 업종 무관 일반 상가 |

### 2.1 좌표 재배포에 관한 명시적 판단

원래 이 절은 크롤링한 좌표를 그대로 쓰기로 한 결정의 위험을 다뤘다. §2.2에서 크롤링 경로가 폐기되면서 재배포 위험 자체가 사라졌다. 다만 두 장치는 그대로 유지한다. 출처가 공공데이터로 바뀌어도 "출력 행이 특정 실재 대상을 재현하지 않는다"는 성질은 여전히 지킬 값어치가 있고, 이미 테스트로 고정되어 있다.

1. **수집 필드 화이트리스트.** 좌표·행정동·층·면적만 저장한다. 그 외 식별 정보는 파서 단계에서 객체에 담지 않는다.
2. **1:1 대응 차단.** 좌표 풀을 셔플한 뒤 면적과 가격을 각각 독립적으로 분포에서 샘플링한다. 좌표가 원본에서 갖고 있던 면적이 다시 뽑히면 재샘플링한다.

이 두 장치의 효과는 테스트로 고정한다(§6 참조).

### 2.2 크롤링 경로 폐기 (2026-07-27)

Stage 0을 실행하려 했으나 **네이버부동산이 이 클라이언트를 거부**했다. 측정 결과:

- `new.land.naver.com/offices?ms=...` 딥링크는 301 리다이렉트 후 `/404`로 떨어졌고, 내부 API 호출의 좌표는 강남구가 아니라 경기도 성남시 분당구(`cortarNo=4113510300`)를 가리켰다. 2026-07-26에 측정된 `ms=` 평문 좌표 규약이 그사이 바뀌었다.
- 파라미터를 모두 뺀 `new.land.naver.com/offices`도, 루트 `new.land.naver.com/`도 똑같이 `/404`였다. 라우트 변경이 아니라 쿠키 없는 자동화 브라우저에 대한 차단이다.
- `api/articles/clusters`, `api/articles` 요청은 모두 `net::ERR_ABORTED`.

차단을 우회하는 것은 탐지 회피에 해당하므로 시도하지 않았다. 크롤링 경로는 폐기한다.

**대체 출처는 실호출로 검증했다.**

| 용도 | 출처 | 검증 결과 |
| --- | --- | --- |
| 좌표 | Kakao Local 키워드 검색 | 200, "강남구 상가" 738건, 실좌표 반환 |
| 가격 | 서울교통공사 지하상가 임대정보 OA-12927 | 200, 1,509행, 면적·월임대료 동시 보유 1,263건 |
| 역→자치구 | Kakao Local (`category_group_code=SW8`) | 209개 역 **전부** 매핑 성공, 실패 0 |

5개 구 임대료 표본: 강남 107 / 마포 105 / 서초 67 / 성동 59 / 영등포 33. 모두 `MIN_BAND_SAMPLES`(5)를 크게 웃돈다.

CSV 컬럼명은 `면적㎡`가 아니라 **`면적(제곱미터)`**이다.

### 2.3 보증금은 실측이 아니라 선언된 가정이다

지하상가 임대정보에는 월임대료만 있고 보증금이 없다. 상가 보증금을 실측으로 주는 공개 출처를 찾지 못했다. 상가임대차보호법의 월차임 전환율은 보증금→월세 전환의 *상한* 규제라 시장 배수와 자릿수가 다르다.

따라서 보증금은 **`ASSUMED_DEPOSIT_MULTIPLE` 상수 한 곳에 선언된 가정**으로 둔다(월세의 10~20배). 이 값을 실측 월세와 같은 파일에 섞지 않는 것이 핵심이다 — 가정을 데이터 경로로 흘리면 나중에 어느 숫자가 측정값이고 어느 것이 가정인지 구분할 수 없게 된다. Stage 1 산출물은 `assumptions` 필드에 이 가정을 명시하고, provenance와 UI는 보증금을 월세·면적과 구분해 "관행 배수 가정, 실측 아님"으로 표기한다.

## 3. 파이프라인

새 디렉터리 `pipeline/` 아래 4단계. 각 단계는 파일로만 통신하며 서로 직접 호출하지 않는다. 따라서 독립적으로 실행하고 검증할 수 있다.

```
pipeline/
  collect/fetch-coords.mjs        Stage 0a — Kakao Local
  collect/fetch-prices.mjs        Stage 0b — 지하상가 CSV
  distribution/build-distribution.mjs  Stage 1
  verify/cross_check.py           Stage 2
  synthesize/build-listings.mjs   Stage 3
  lib/                            shared pure functions
  raw/                            gitignore
  README.md
```

### Stage 0a — 좌표 수집 (Kakao Local)

`pipeline/collect/fetch-coords.mjs`. 구별 키워드 검색으로 실제 상가 좌표를 모은다. `KAKAO_REST_API_KEY`는 이미 설정되어 있고 `LocationService`가 쓰는 것과 같은 키다.

수집 필드는 화이트리스트로 강제한다.

```js
{ lat, lng, sido, sigungu, dong, floor, area_m2 }
```

그 외 필드는 파서가 읽지 않는다. `area_m2`는 Stage 1의 분포 집계에만 쓰이며 결과 행에는 그대로 붙지 않는다(§2.1의 1:1 대응 차단). 산출물 `pipeline/raw/coords.<구>.jsonl`은 `.gitignore` 대상이다.

### Stage 0b — 가격 표본 수집 (지하상가 CSV)

`pipeline/collect/fetch-prices.mjs`. OA-12927 CSV를 받아 `면적(제곱미터)`과 `월임대료`가 모두 양수인 1,263행을 추린 뒤, 역명을 Kakao Local로 지오코딩해 자치구로 묶는다. 산출물 `pipeline/raw/prices.<구>.jsonl`의 각 행은 **측정값만** 담는다.

```js
{ sigungu, area_m2, monthly_rent_krw }
```

보증금은 여기 없다. §2.3에 따라 가정이므로 데이터 파일에 섞지 않는다.

### Stage 1 — 가격 분포 추출 (집계만)

개별 가격은 남기지 않고 집계만 남긴다.

- 구별 면적 분위수: P10 / P25 / P50 / P75 / P90
- 구 × 면적구간별 **월세** 분위수: P10 / P25 / P50 / P75 / P90
- 구간별 표본 수 `n`
- 보증금 배수는 측정하지 않고 `ASSUMED_DEPOSIT_MULTIPLE` 상수에서 가져와 `assumptions` 필드에 명시한다

면적구간은 `~33㎡ / 33~66㎡ / 66~99㎡ / 99㎡~` 4구간으로 고정한다. 실제 소규모 상가 임대 시장의 구획과 맞고, 구당 40~60건이면 구간별 표본이 통계로 쓸 만한 크기가 된다. 표본이 5건 미만인 구간은 상위 구간과 병합하고 그 사실을 검증 리포트에 남긴다.

산출물 `data/rent-distribution.seoul.json`은 **커밋한다.** 통계 집계는 개별 매물의 재배포가 아니며, 생성된 숫자의 근거를 사후에 추적하려면 이 파일이 남아 있어야 한다. `n`은 `Provenance.sample_n`으로 이어진다.

### Stage 2 — 자기일관성 게이트

**이 단계는 더 이상 독립적인 교차검증이 아니다.** 원래는 크롤링한 가격을 공공데이터로 대조할 계획이었으나, §2.2에서 가격 출처가 지하상가 CSV로 바뀌면서 기준선과 검증 대상이 같은 데이터가 되었다. 비교는 자기 자신과의 비교가 된다. 이 사실을 리포트에 명시한다.

그럼에도 유지할 값어치가 있다. 남은 기능은 **집계 경로의 버그를 잡는 것**이다: 컬럼을 뒤바꿔 읽거나, 자치구 매핑이 어긋나거나, 특정 구가 통째로 빠지면 그 구의 ㎡당 중앙값이 전체 중앙값에서 크게 벗어난다.

- 기준선: OA-12927 전체 ㎡당 월임대료 중앙값 98,770원 (기준일 2025-12-31)
- 허용 범위 0.5×~3.0× 유지. 자치구별 시세 차이(강남 대 노원)가 실재하므로 좁히지 않는다.
- 구별 ㎡당 월세 중앙값이 범위를 벗어나면 종료 코드 1

리포트 `data/rent-distribution.verification.md`는 이 게이트가 독립 검증이 아님을 첫 문단에 밝힌다.

### Stage 3 — 합성

`pipeline/synthesize/build-listings.mjs`. 고정 시드 `20260727`으로 재현 가능하게 한다.

1. 좌표 풀을 셔플한다.
2. 각 좌표에 대해 면적을 해당 구의 면적 분포에서 독립 샘플링한다.
3. 월세를 해당 구 · 면적구간 분포에서 독립 샘플링한다.
4. 보증금은 Stage 1에서 구한 배수 중앙값에 분산을 적용해 산출한다.
5. 매물명을 `행정동 + 층 + 유형` 규칙으로 생성한다(예: "역삼동 1층 상가"). 실제 상호는 쓰지 않는다.

면적을 좌표에 붙여 오지 않고 독립 샘플링하는 이유는 §2.1의 1:1 대응 차단이다. 그 대가로 생성된 면적은 해당 건물의 실제 면적과 무관하다. 이는 의도된 트레이드오프다.

산출물 `data/listings.seoul.json`을 커밋한다.

### Stage 4 — 적재

- `supabase/migrations/202607270001_listings.sql`: 스키마
- `scripts/seed-listings.mjs`: 데이터 적재

같은 JSON이 Supabase 미설정 환경의 폴백 원본을 겸한다.

## 4. 데이터 모델과 백엔드

### 4.1 `Candidate` 확장

매물을 새 타입으로 만들지 않고 `Candidate`에 거래 조건을 추가한다. `Candidate`는 이미 id·name·address·좌표·evidence_grade·context_signals·provenance를 갖고 있어 매물이 되려면 조건만 더 필요하다. 별도 타입을 만들면 `KbMap`, `AnalysisService`, `AnalysisContract`, `lib/types.ts`가 모두 두 갈래로 갈라진다.

```python
class ListingTerms(BaseModel):
    listing_kind: Literal["DEMO_SYNTHETIC"]
    deposit_krw: int
    monthly_rent_krw: int
    maintenance_fee_krw: int | None = None
    area_m2: float
    floor: int

class Candidate(BaseModel):
    ...기존 필드 유지...
    listing: ListingTerms | None = None
```

`listing_kind`를 필수 Literal로 두는 것이 이 설계의 핵심이다. 라벨 없는 매물은 타입 시스템상 만들어질 수 없으므로 불변조건 1이 코드 리뷰가 아니라 pydantic 검증으로 강제된다. 나중에 실제 매물이 확보되면 `Literal["DEMO_SYNTHETIC", "VERIFIED"]`로 넓힌다.

`lib/types.ts`에 동일한 형태를 snake_case로 미러링한다.

**`evidence_grade`는 C를 유지한다.** 매물 조건이 붙었다고 생존확률이 생기는 것이 아니므로 불변조건 2(A 등급에서만 생존확률 노출)와 충돌하지 않는다.

### 4.2 `backend/app/listings.py` — ListingService

`repository.py`의 이중 모드 관례를 그대로 따른다.

- `supabase_configured`가 참이면 Supabase `listings` 테이블에서 읽는다.
- 아니면 `data/listings.seoul.json`에서 읽는다.

어느 쪽이든 기동 시 1회 로드해 메모리에 인덱싱한다(300건이므로 부담 없음). 구와 예산 상한으로 필터링하고 월세 오름차순으로 정렬해 반환한다.

### 4.3 `POST /api/v1/locations/search` 전환

응답 형태는 `list[Candidate]` 그대로이므로 프론트 계약이 깨지지 않는다.

- 5개 구: 매물 반환
- 그 외 20개 구: 빈 목록 + `status: "empty"` + `"현재 시연용 매물 데이터는 강남·마포·서초·성동·영등포 5개 구만 준비되어 있습니다"`

Kakao Local 후보로 폴백하지 않는다. 매물 카드와 장소 카드가 섞이면 사용자가 무엇을 보고 있는지 알 수 없어진다. `LocationService`는 코드에 남기되 이 경로에서 호출하지 않는다.

**부수효과.** 현재 `LocationService._candidate_index`가 프로세스 메모리에 있어 `/analyses`가 워커를 넘어가면 후보를 찾지 못하는 알려진 갭이 있다. 시드 매물은 ID가 안정적이므로 이 갭이 자연히 해소된다.

### 4.4 비용 단계 연동

매물을 선택하면 보증금·월세가 비용 단계에 프리필된다. 이때 `CostItem.source_type`은 `ESTIMATE`로 넣는다. `USER`가 아니다 — 사용자가 입력한 값이 아니기 때문이다. `note`에 "시연용 매물 조건에서 자동 입력"을 적는다. 사용자가 값을 확인하거나 수정하면 `USER`로 승격된다.

`CostService`의 산술은 수정하지 않는다.

### 4.5 Supabase 스키마

`supabase/migrations/202607270001_listings.sql`.

`listings` 테이블은 세션 스코프가 아닌 공용 참조 데이터다. RLS는 익명 읽기 허용 / service role 쓰기로 둔다. `listing_kind` 컬럼에 `CHECK (listing_kind = 'DEMO_SYNTHETIC')` 제약을 걸어 DB 층에서도 라벨을 강제한다.

`supabase/archive/`는 건드리지 않는다.

## 5. 프론트엔드

### 5.1 지도 마커

`components/kb/KbMap.tsx`의 `markerNode()`가 `candidate.listing` 유무로 갈린다. 매물이면 이름 줄 아래에 조건 줄을 추가하고 `[시연용]` 칩을 붙인다.

```
┌────────────────────────────────┐
│ 1. 역삼동 1층 상가  [시연용] │C│
│ 33㎡ · 보 3,000 / 월 180      │
└────────────────────────────────┘
```

핀이 두 줄로 커지므로 `yAnchor`와 `setBounds` 패딩을 조정한다.

**`LocationSearch.limit`의 상한 15를 유지한다.** 250건을 한 화면에 찍으면 겹쳐서 읽을 수 없다. 구당 15핀이면 화면은 충분히 차고 클러스터링 없이 읽힌다.

### 5.2 라벨 노출 지점

라벨은 네 곳 전부에 붙인다.

1. 지도 핀
2. 후보 카드
3. `ProvenanceBar`
4. **PDF** (`render_case_pdf`)

PDF가 가장 중요하다. 종이로 출력된 순간 화면의 배너는 사라지므로, 문서 자체에 "시연용 생성 데이터 / 실제 임대 매물이 아님"이 들어 있어야 한다.

`Provenance` 값:

```
source_name:  "시연용 생성 데이터"
spatial_unit: "개별 상가 좌표"
confidence:   "LOW"
sample_n:     <Stage 1의 구간별 표본 수>
limitations: [
  "실제 임대 매물이 아니며 계약 대상이 아닙니다",
  "위치는 실제 상가 좌표이나 면적·보증금·월세는 시세 분포에서 생성한 값입니다"
]
```

### 5.3 AI 가드레일

`AIService.explain` 프롬프트에 매물이 시연용이라는 사실을 명시한다. 현재 프롬프트는 "숫자를 지어내지 말 것"까지만 지시하는데, 매물 조건이 컨텍스트로 들어가면 AI가 이를 실제 매물로 단정해 서술할 수 있다.

`POST /cases/{id}/messages`가 `confirmed_case_patch`를 422로 거부하는 규칙은 그대로 유지한다.

## 6. 검증

### 6.1 `scripts/flow-check.mjs` 갱신

현재 이 스크립트는 "키가 없으면 후보 목록이 비어 있다"를 어서션한다. 매물이 키 없이도 나오므로 **이 어서션은 그대로 두면 깨진다.** 다음으로 교체한다.

- 강남구 요청 → 매물 1건 이상 + `[시연용]` 배지가 DOM에 존재
- 노원구 요청 → 빈 상태 + 커버리지 안내 문구
- AI 폴백 메시지 안전 상태 유지
- 자금 밴드 `integration_pending` 안전 상태 유지

### 6.2 신규 테스트 `pipeline/synthesize/build-listings.test.mjs`

`node --test`로 실행한다.

- 같은 시드로 두 번 실행하면 바이트 단위로 동일하다 (재현성)
- 모든 행에 `listing_kind: "DEMO_SYNTHETIC"`이 있다
- 모든 가격이 해당 구 · 면적구간 분포의 P10~P90 범위 안에 있다
- 어떤 행도 `(좌표, 면적, 보증금, 월세)` 조합이 원본 raw와 일치하지 않는다 — §2.1의 1:1 대응 차단을 테스트로 고정한다

### 6.3 기존 게이트

`npm run lint`, `npm run typecheck`, `npm run api:check`, `node scripts/visual-check.mjs`를 모두 통과시킨다. 시각 회귀 스크린샷은 갱신한다.

### 6.4 신규 npm 스크립트

```
pipeline:crawl     1회성, 확인 프롬프트 포함
pipeline:build     분포 → 합성 → data/listings.seoul.json
pipeline:verify    공공데이터 교차검증 게이트
seed:listings      Supabase 적재
```

## 7. 작업 순서

1. Stage 0~1 (수집 + 분포) → `data/rent-distribution.seoul.json`
2. Stage 2 교차검증 게이트 → `data/rent-distribution.verification.md`
3. Stage 3 합성 + 테스트 → `data/listings.seoul.json`
4. 백엔드: `ListingTerms`, `listings.py`, `locations/search` 전환
5. Supabase 마이그레이션 + 시드
6. 프론트: `lib/types.ts`, `KbMap`, 후보 카드, `ProvenanceBar`, 비용 프리필
7. PDF·AI 프롬프트 라벨
8. `flow-check.mjs` 갱신 + 전체 검증

1~3이 끝나면 백엔드 없이 데이터 품질을 검토할 수 있다. 그 시점에 사람이 한 번 확인한 뒤 4로 넘어간다.

## 8. 범위 밖

- 상시 크롤링 파이프라인 (1회성 수집만)
- 실제 매물 연동 및 계약 기능
- 5개 구 외 20개 구의 매물 데이터
- 매물 사진·중개사 정보·상세 설명
- 마커 클러스터링 (limit 15로 회피)
- `store.py` / `integrations.py` 등 미연결 레거시 클러스터
