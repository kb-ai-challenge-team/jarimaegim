# 시연용 매물 데이터 파이프라인

설계 문서: `docs/superpowers/specs/2026-07-27-listing-data-pipeline-design.md`

공모전 시연용 임대 매물 275건(5개 구 × 55건)을 생성한다. 모든 산출 행은
`listing_kind: "DEMO_SYNTHETIC"` 라벨을 달고 있으며 실제 임대 매물이 아니다.

## 출처

크롤링은 쓰지 않는다. 2026-07-27 네이버부동산이 자동화 클라이언트를 차단하는 것을
확인하고 공공 출처로 전환했다(설계 문서 §2.2).

| 값 | 출처 | 성격 |
| --- | --- | --- |
| 좌표 | Kakao Local 키워드 검색 | 실제 상가 위치 |
| 월세·면적 분포 | 서울교통공사 지하상가 임대정보 OA-12927 | 실측 1,263건 |
| 역 → 자치구 | Kakao Local (`category_group_code=SW8`) | 209개 역 |
| 보증금 배수 | `ASSUMED_DEPOSIT_MULTIPLE` 상수 | **가정. 실측 아님** |
| 관리비 비율 | `ASSUMED_MAINTENANCE_FEE_RATE` 상수 | **가정. 실측 아님** |
| 층 | `ASSUMED_FLOOR` 상수 | **가정. 실측 아님** |
| 권리금·전용면적·준공년도·주차·코너·엘리베이터·총층수·전면폭·입주가능일 | `pipeline/lib/attribute-constants.mjs` | **가정. 실측 아님** |

보증금·관리비·층·부가 속성은 실측 출처가 없다. 그래서 측정값이 담기는 파일이 아니라 이름이
붙은 상수 한 곳에 두었다. 가정을 데이터 경로로 흘리면 나중에 어느 숫자가 측정값인지 알 수 없다.

## 가정값은 등급을 올리지 않는다

부가 속성(Stage 4)은 **매물 카드와 필요자금 계산에만** 쓰인다. 근거등급 A/B/C/U 에는
관여하지 않는다 — 등급 B는 서울시 상권분석서비스의 실측 집계에서만 나온다. 개별 상가의
권리금·전용면적을 공개하는 원천이 없으므로 이 값들로 입지를 판정하면 근거 없는 판단이 된다.

권리금만 예외적으로 계산에 들어간다. `FundingBandInput.key_money_krw` 를 통해 필요자금에
합산되고, 그 결과가 조달 밴드·손익분기 일매출로 이어진다. **즉 화면의 조달 금액에는 가정값이
섞여 있다.** 사용자는 입지 화면의 "정밀하게 맞추기"에서 이 값을 직접 고칠 수 있고, 필드에
"계약 전 직접 확인" 이라고 적혀 있다.

## 스테이지

| 단계 | 명령 | 입력 | 출력 |
| --- | --- | --- | --- |
| 0 수집 | `npm run pipeline:collect` | 공공 API | `pipeline/raw/{coords,prices}.<구>.jsonl` |
| 1 분포 | `npm run pipeline:build` | `pipeline/raw/` | `data/rent-distribution.seoul.json` |
| 2 검증 | `npm run pipeline:verify` | Stage 1 산출물 | `data/rent-distribution.verification.md` |
| 3 합성 | `npm run pipeline:build` | Stage 1 산출물 | `data/listings.seoul.json` |
| 4 부가속성 | `npm run pipeline:build` | Stage 3 산출물 | `data/listings.seoul.json` (가정값 9개 추가) |

`pipeline:build`가 Stage 1·3·4를 순서대로 돌린다. Stage 2는 그 사이에 수동으로 돌린다.

Stage 4는 매물 id 로 시드를 만들므로 **배열 순서에 의존하지 않는다.** 매물을 추가하거나
순서를 바꿔도 기존 매물의 속성은 그대로다. 임대 조건(보증금·월세·관리비·면적·층)은 덮지
않는다 — 그 값들은 실측 분포에서 나온 것이고 덮으면 출처를 알 수 없게 된다.

Stage 4 이후 `npm run seed:listings` 로 Supabase 에 다시 적재해야 한다. 마이그레이션
`202607280003_listings_assumed_attributes.sql` 이 선행 조건이다.

테스트: `npm run test:pipeline` (47개) 및
`cd pipeline/verify && ../../backend/.venv/bin/python -m pytest test_cross_check.py` (9개).

## Stage 2는 독립 검증이 아니다

임대료 표본과 기준선이 같은 출처라 비교 대상이 자기 자신이다. 남은 기능은 집계
경로의 버그(컬럼 오독, 역-자치구 매핑 오류, 구 누락)를 잡는 것뿐이다. 리포트
첫 문단이 이 사실을 밝힌다.

## 수집 필드 화이트리스트

Stage 0은 `lat, lng, sido, sigungu, dong, floor, area_m2` 일곱 필드만 저장하며
`pipeline/lib/raw-record.mjs`가 이를 강제한다. `pipeline/raw/`는 gitignore 대상이다.

좌표 레코드의 `floor`는 `ASSUMED_FLOOR`(1)로 고정한 기본값이고 `area_m2`는 0.1
자리표시자다. Kakao Local이 층과 면적을 주지 않기 때문이다. 이 둘의 생성 결과 반영
여부는 서로 다르다 — `area_m2`는 Stage 3의 재샘플링 충돌 가드를 위한 씨앗으로만
쓰이고 생성 결과에는 들어가지 않지만, `floor`는 그대로 통과해 매물의 `floor` 필드와
매물명(`OO동 1층 상가`)에 그대로 들어간다.

## 재현성

Stage 3은 `SYNTHESIS_SEED = 20260727`로 완전히 결정된다. 같은 입력이면
`listings` 배열이 바이트 단위로 같다. `generated_at`만 실행마다 바뀐다.

## 실행 이력

- 2026-07-27 Stage 0~3 최초 실행. 표본 371건 → 매물 275건, Stage 2 게이트 통과(0.73×~1.33×).

---

# 상권 프로파일 (서울시 우리마을가게 상권분석서비스)

`npm run pipeline:trade-area`

임대 조건은 시연용 생성 데이터지만, **후보를 고르고 줄 세우는 근거는 실측 공개 데이터다.**
이 파이프라인이 그 근거를 공급한다. 이전에는 업종·우선순위를 받아만 놓고 쓰지 않아
'강남구 카페'를 물어도 카페와 무관한 가장 싼 매물이 1순위였다.

## 출처

| 값 | 데이터셋 | 성격 |
| --- | --- | --- |
| 상권 위치·행정동 | `TbgisTrdarRelm` (상권영역) | 실측 1,650건 |
| 점포수·개폐업 | `VwsmTrdarStorQq` (점포) | 실측 75,972건 |
| 추정매출 | `VwsmTrdarSelngQq` (추정매출) | 카드매출 기반 추정 21,188건 |
| 유동인구 | `VwsmTrdarFlpopQq` (길단위인구) | 실측 1,649건 |
| 매물 → 행정동 | Kakao Local `coord2regioncode` | 실측 |

기준 분기는 `TRADE_AREA_QUARTER`(현재 `20261`). 2026-07-28 확인 시점에 네 데이터셋 모두
20261이 최신이고 20262는 비어 있다.

## 좌표계를 변환하지 않는 이유

상권영역은 중심좌표를 EPSG:5181 계열 TM으로 주고 매물 좌표는 WGS84다. 변환해서 최근접
상권을 붙일 수도 있지만 **상권영역 데이터셋에는 폴리곤이 없고 중심점과 면적뿐이다.**
중심점 거리로 소속을 정하면 근거 없는 정밀함이 생긴다.

대신 양쪽이 모두 갖고 있는 **행정동 코드**로 조인한다. 상권영역의 `ADSTRD_CD`(8자리)는
Kakao 역지오코딩이 주는 10자리 행정동 코드의 앞 8자리와 정확히 일치한다(실측 확인:
1,045개 매물 중 975건 조인, 이름 불일치 44건은 전부 `.` 대 `·` 구분자 차이로 같은 동).
그래서 공간 단위가 개별 상권이 아니라 **행정동 내 상권 집계**가 되며, 그 사실은
`provenance.spatial_unit`에 그대로 적혀 나간다.

## 비율은 평균하지 않는다

개업률·폐업률은 상권 하나에 대한 백분율이다. 크기가 다른 상권들의 백분율을 평균하면
점포 3개짜리가 점포 300개짜리와 같은 무게를 갖는다. 그래서 원자료인 개업·폐업 **점포 수**를
받아 행정동 합계끼리 다시 나눈다. 점포당 매출도 같다 — 분자와 분모가 같은 모집단이 되도록
매출이 확인된 상권의 점포만 분모에 넣는다.

## 미확보 시 동작

| 상황 | 동작 |
| --- | --- |
| 프로파일 파일 없음 | `location.*` 축 전체 비활성. `/status`가 사유를 밝힌다 |
| 업종 매핑 실패 | 상권 근거 없이 월세 순 정렬. 등급 C 유지 |
| 행정동에 상권 없음 (70건) | 그 후보만 등급 C, `trade_area_fit.reason`에 사유 |
| 해당 업종 점포 5곳 미만 | 그 행정동×업종만 미수록 |
| 추정매출 미제공 | 매출 축만 비활성. 나머지 세 축은 그대로 판정 |

## 스테이지

| 단계 | 스크립트 | 출력 |
| --- | --- | --- |
| 0b 수집 | `collect/fetch-trade-area.mjs` | `pipeline/raw/trade-area.*.jsonl` |
| 0c 행정동 | `collect/fetch-listing-dong.mjs` | `pipeline/raw/listing-dong.jsonl` |
| 4 집계 | `trade-area/build-trade-area.mjs` | `data/trade-area.seoul.json` |
| 5 부착 | `trade-area/attach-dong.mjs` | `data/listings.seoul.json` (행정동 열 추가) |

Stage 5 이후 `npm run seed:listings`로 Supabase에 다시 적재해야 한다. 마이그레이션
`202607280002_listings_admin_dong.sql`이 선행 조건이다.

테스트: `npm run test:pipeline`에 포함된다.

## 실행 이력

- 2026-07-28 최초 실행. 행정동 399개 · 행정동×업종 15,467건 · 업종 100종.
  매물 1,045건 전부 행정동 확인(자치구 불일치 0건), 그중 975건이 상권 프로파일과 조인.

---

# 정책공고·KB상품 인덱스

설계 문서: `docs/superpowers/specs/2026-07-27-policy-kb-rag-design.md`

지원사업 공고와 KB 금융상품 공시를 임베딩해 Supabase `knowledge_documents`에 넣는다.
백엔드의 `/programs`·`/products/kb`·`/knowledge/search`가 이 테이블만 읽는다.

## 출처

크롤링은 쓰지 않는다. 임베딩할 본문이 API 응답에 이미 실려 온다.

| 원천 | 본문 필드 | 형식 |
| --- | --- | --- |
| 기업마당 | `bsnsSumryCn` (HTML) | XML |
| K-Startup | `pbanc_ctnt`, `aply_trgt_ctnt`, `aply_excl_trgt_ctnt` | JSON |
| 금융상품 한눈에 | **없음.** 구조화 필드를 문장화한다 | JSON |

문서 하나가 최대 약 950자라 청킹하지 않는다. 문서 1건 = 임베딩 1개다.

## 스테이지

| 단계 | 명령 | 입력 | 출력 |
| --- | --- | --- | --- |
| 수집·임베딩 | `npm run pipeline:policy-index` | 공공 API 3종 | Supabase `knowledge_documents` |
| 확인 | `backend/.venv/bin/python pipeline/policy/verify_index.py` | Supabase | 표준출력 리포트 |

테스트: `cd pipeline/policy && ../../backend/.venv/bin/python -m pytest` (32개)

운영 서버는 `deploy/ter-doctor-policy-index.timer`가 하루 한 번 돌린다.

## 두 번 돌려야 알 수 있는 것

두 번째 실행에서 `임베딩 대상 0건`이 나와야 정상이다. 0이 아니면 차분이 깨진 것이고,
매 회차 전량 재임베딩되고 있다는 뜻이다.

`--reembed`는 임베딩 모델을 바꿀 때만 쓴다. 인덱스에 다른 모델의 벡터가 섞이면
유사도가 의미를 잃으므로, 스크립트는 불일치를 감지하면 멈추고 이 플래그를 요구한다.

## prune

이번 회차에 관측되지 않은 문서는 삭제한다. 원천이 목록에서 내렸다는 것 말고는 아는 게
없으므로 "종료된 공고"라고 주장하지 않고 인덱스에서 뺀다. 단 **해당 provider의 수집이
완전히 성공했을 때만** 그 provider의 문서를 지운다.

## 실행 이력

- 2026-07-27 최초 실행. 문서 1,843건(기업마당 1,501 · K-Startup 265 · KB상품 77),
  임베딩 결측 0건. 공고 1,766건 중 지역 확정 1,312건(74.3%).
