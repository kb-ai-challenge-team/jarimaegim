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

보증금만 실측 출처가 없다. 그래서 측정값이 담기는 파일이 아니라 이름이 붙은 상수
한 곳에 두었다. 가정을 데이터 경로로 흘리면 나중에 어느 숫자가 측정값인지 알 수 없다.

## 스테이지

| 단계 | 명령 | 입력 | 출력 |
| --- | --- | --- | --- |
| 0 수집 | `npm run pipeline:collect` | 공공 API | `pipeline/raw/{coords,prices}.<구>.jsonl` |
| 1 분포 | `npm run pipeline:build` | `pipeline/raw/` | `data/rent-distribution.seoul.json` |
| 2 검증 | `npm run pipeline:verify` | Stage 1 산출물 | `data/rent-distribution.verification.md` |
| 3 합성 | `npm run pipeline:build` | Stage 1 산출물 | `data/listings.seoul.json` |

`pipeline:build`가 Stage 1과 3을 순서대로 돌린다. Stage 2는 그 사이에 수동으로 돌린다.

테스트: `npm run test:pipeline` (47개) 및
`cd pipeline/verify && ../../backend/.venv/bin/python -m pytest test_cross_check.py` (9개).

## Stage 2는 독립 검증이 아니다

임대료 표본과 기준선이 같은 출처라 비교 대상이 자기 자신이다. 남은 기능은 집계
경로의 버그(컬럼 오독, 역-자치구 매핑 오류, 구 누락)를 잡는 것뿐이다. 리포트
첫 문단이 이 사실을 밝힌다.

## 수집 필드 화이트리스트

Stage 0은 `lat, lng, sido, sigungu, dong, floor, area_m2` 일곱 필드만 저장하며
`pipeline/lib/raw-record.mjs`가 이를 강제한다. `pipeline/raw/`는 gitignore 대상이다.

좌표 레코드의 `floor`는 1로 고정한 기본값이고 `area_m2`는 0.1 자리표시자다. Kakao
Local이 층과 면적을 주지 않기 때문이다. 둘 다 생성 결과에 그대로 들어가지 않는다 —
면적은 Stage 3의 재샘플링 충돌 가드를 위한 씨앗으로만 쓰인다.

## 재현성

Stage 3은 `SYNTHESIS_SEED = 20260727`로 완전히 결정된다. 같은 입력이면
`listings` 배열이 바이트 단위로 같다. `generated_at`만 실행마다 바뀐다.

## 실행 이력

- 2026-07-27 Stage 0~3 최초 실행. 표본 371건 → 매물 275건, Stage 2 게이트 통과(0.73×~1.33×).
