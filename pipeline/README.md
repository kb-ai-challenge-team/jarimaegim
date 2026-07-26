# 시연용 매물 데이터 파이프라인

설계 문서: `docs/superpowers/specs/2026-07-27-listing-data-pipeline-design.md`

## 실행 정책

**Stage 0(좌표 수집)은 1회성이다.** 이미 실행이 끝났다면 다시 돌리지 않는다.
상시 크롤링 파이프라인으로 확장하지 않는다. 재실행이 필요한 경우
`pipeline/raw/`를 지우고 실행 확인 프롬프트에 명시적으로 동의해야 한다.

## 스테이지

| 단계 | 명령 | 입력 | 출력 |
| --- | --- | --- | --- |
| 0 수집 | `npm run pipeline:crawl` | (외부) | `pipeline/raw/coords.<구>.jsonl` |
| 1 분포 | `npm run pipeline:build` | `pipeline/raw/` | `data/rent-distribution.seoul.json` |
| 2 검증 | `npm run pipeline:verify` | Stage 1 산출물 | `data/rent-distribution.verification.md` |
| 3 합성 | `npm run pipeline:build` | Stage 1 산출물 | `data/listings.seoul.json` |

Stage 2는 게이트다. 실패하면 Stage 3 결과를 신뢰하지 않는다.

## 수집 필드 화이트리스트

Stage 0은 `lat, lng, sido, sigungu, dong, floor, area_m2` 일곱 필드만 저장한다.
매물번호·중개사·상호·사진·설명문·원본 URL·가격은 파서가 읽지 않는다.
`pipeline/lib/raw-record.mjs`가 이를 강제한다.
