# 금융 프로필 선행 flow 재설계

작성일 2026-07-28 · 대상 `components/kb/*`, `lib/use-jarimaegim.ts`, `backend/app/{models,funding,main}.py`

## 문제

현재 flow는 `ask → confirm → bands → recommend → evidence → prescribe` 6단계(스테퍼 5칸)다.
순서는 제안서대로 금융이 입지보다 먼저 돌지만, **사용자를 세우는 지점**이 제안서와 어긋난다.

1. `start()`가 `setStep("bands")`로 끝나 사용자는 후보를 하나도 보기 전에 금액 7개짜리 폼과
   "다시 계산" 버튼 앞에 선다. 제안서 05단계 "후보를 보기 전에 금융 결정을 요구하지 않습니다"와
   02단계 "사용자를 세우지 않고 ◐ 권장 조달선으로 자동 진행"을 정면으로 어긴다.
2. `confirm` 스텝이 평수·보증금·월세를 받고 `bands` 스텝이 같은 값을 다시 받는다.
3. `evidence`가 별도 스텝이라 후보 목록이 사라진다. 후보 3곳 비교에 화면 전환 6회.
4. `prescribe`가 `bands`에서 이미 본 `BandTable`을 한 번 더 렌더한다.
5. 자기자본·기존부채·월 고정지출이 케이스 조건과 섞여 있어, 조건을 바꿀 때마다 자금 정보를
   다시 확인하게 된다. 제안서 03의 "'주체' → 조건 레이어. 자본 체급은 후보의 성질이 아니라
   사용자의 성질이므로 8회 반복할 이유가 없습니다"가 코드에 반영되지 않았다.

## 설계

### 흐름

```
스텝 0 · 금융 프로필      시작 전 1회. 스테퍼에 포함하지 않는다.
   ↓ equity_krw · existing_debt_krw · other_monthly_fixed_krw 를 세션에 확정
① 조건 → ② 입지 → ③ 처방
   ↑ 프로필 값은 세 화면 전부에서 자동 재사용하며 다시 묻지 않는다
```

`FlowStep`은 `"profile" | "ask" | "confirm" | "recommend" | "prescribe"`. `bands`와 `evidence`는
삭제하되 **기능은 삭제하지 않는다** — 각각 입지 화면의 접이식과 후보 카드의 인라인 확장으로 옮긴다.

### 스텝 0 — 금융 프로필

마이데이터 자동 채우기가 주 동선이고, 게이트가 닫혀 있으면 수동 입력이 **동일 스키마**를 채운다
(부록 A 불변조건 5 · 제안서 07 "마이데이터 실연동 — 게이트 off, 수동 입력 어댑터로 동일 스키마 충족").

- `GET /api/v1/status`의 `feature_flags.mydata`가 false면 연동 버튼은 `disabled`,
  잠금 사유를 화면에 그대로 표시한다. 숨기지 않는다.
- 확정 시 `profile`을 훅 상태에 올리고 이후 `createCase` / `fundingBands` / 재검색이 모두 이 값을 읽는다.
- 익명 세션(24시간)에 종속된다. 세션이 만료되면 프로필도 사라지고 스텝 0부터 다시 시작한다.
  계정을 만들지 않는 현재 구조에서 이보다 오래 보관할 수단은 도입하지 않는다.

### 조건 화면이 묻는 것

`compute_bands`(`backend/app/funding.py:54`)를 기준으로 입력이 무엇을 여는지 갈린다.

| 입력 | 없으면 못 나오는 것 | 후보를 바꾸는가 |
|---|---|---|
| `equity_krw` | 세 밴드 전부 | O (프로필이 이미 확정) |
| `existing_debt_krw` | 최대 조달선 | O (프로필이 이미 확정) |
| `monthly_rent_krw` | 권장 조달선, 손익분기 목표매출 | O |
| `industry` · `district` | 업종 파라미터, 검색 질의어 | O |
| `area_pyeong` | 인테리어 추정 → 필요자금 → **현금소진만** | X |
| `deposit_krw` · `key_money_krw` | 필요자금 → **현금소진 · OUT_OF_RANGE 판정만** | X |
| `monthly_maintenance_krw` · `other_monthly_fixed_krw` | 정밀도만 (0이 유효한 기본값) | X |

자기자본선(`= equity`)과 최대 조달선(`= equity + 보증한도 − 기존부채`)은 임대조건에 의존하지 않는다.
권장 조달선은 `base_monthly_fixed`에만 의존하므로 **희망 월세 하나면 나온다.**

→ 조건 화면의 필수는 **업종 · 자치구 · 희망 월세** 셋. 자유발화에서 파싱되거나 프로필에서 온 값은
출처를 붙인 칩으로 보여주고(탭하면 수정), **비어 있는 것만 최대 3개** 묻는다.
사업단계·창업형태·우선순위는 기본값을 두고 "선택 조건 더 보기" 접이식으로 내린다.

지금처럼 평수·보증금·월세가 없다고 밴드 전체를 `integration_pending`으로 막는 것은 불변조건 1의
과잉 적용이다. **없는 값을 만들지 않는 것**과 **없는 값에 의존하지 않는 계산까지 막는 것**은 다르다.

### 입지 화면

하나의 스크롤 안에 전부 둔다.

- 상단 `BandBanner` — 권장 조달선 기준선, 그 아래 `자기자본 + 차입` 내역(프로필 출처 명시),
  확장(▲)·축소(▼)를 **같은 비중·같은 위치**로 대칭 노출(제안서 02의 UI 불변조건).
  임대조건 미입력으로 못 내는 값은 "확인 필요"로 표기하고 추정하지 않는다.
- "정밀하게 맞추기" 접이식 — 기존 `PlanBands`의 폼과 `BandTable`을 그대로 재사용한다.
  기존부채는 프로필에서 확정됐으므로 입력란 대신 확정 배지 + 수정 링크로 대체한다.
  저장하면 배너와 후보가 그 자리에서 갱신되고 **화면을 떠나지 않는다.**
- 후보 카드 — "근거 펼치기"로 `EvidenceContract` + 맥락 신호 + `ProvenanceBar`를 인라인 확장.
- 하단 "탈락 N곳 · 사유" 접이식 — 사유가 있는 것만 탈락시키고 개수를 고정하지 않는다.
  상권 임대 수준 원천이 없어 현재는 밴드 기반 탈락이 발생하지 않으므로, 그 사실을 그대로 고지한다.

### 처방 화면

`PlanPrescription`은 유지하되 중복된 `BandTable`을 제거하고 요약 `dl`만 남긴다.

### 채팅 · 진행 표시

`JarimaegimChat`은 상시 우측 레일로 변경 없음. `AgentRunOverlay`도 변경 없이 유지하되,
이 설계에서 조달 밴드 산출을 보여주는 유일한 화면이 되므로 역할이 커진다.

## 계약 변경

### `backend/app/models.py`

- `FundingBandInput.area_pyeong: float | None = None`, `deposit_krw: int | None = None`.
  `monthly_rent_krw`는 필수 유지.
- `FundingBandResult.status`에 `"partial"` 추가.
  - `computed` — 기존 규칙 유지 (`bands` + `break_even` + `required_capital_krw` 전부 존재, `missing_params` 비어야 함).
  - `partial` — `bands`와 `break_even`은 존재하고 `required_capital_krw`는 `None`,
    `missing_params`는 비어 있으면 안 된다.
  - `integration_pending` — 기존 규칙 유지.
- `BandLine.runway_months`는 이미 nullable이라 변경 없음.

### `backend/app/funding.py`

`compute_bands`가 `area_pyeong`/`deposit_krw`의 `None`을 받는다.
필요자금을 낼 수 없으면 `required_capital_krw = None`, 각 밴드의 `runway_months = None`,
`required_capital_band = None`을 돌려준다. 세 밴드의 상한·월 상환·목표매출·`stress_pass`는
그대로 계산된다. 추정으로 메우지 않는다.

### `backend/app/main.py`

`create_funding_bands`가 부분 산출을 `partial`로 반환하고 `missing_params`에 빠진 입력을 담는다.
`assumptions`의 인테리어 문구는 미입력 시 "평수 미입력으로 필요자금과 현금소진은 계산하지
않았습니다"로 바꾼다.

### 프론트

- `lib/types.ts` — 위 계약을 필드 단위로 미러.
- `lib/constants.ts` — `DEFAULT_BAND_FORM`의 `area_pyeong`·`deposit_krw`를 `number | null`로,
  `DEFAULT_PROFILE` 신설.
- `lib/use-jarimaegim.ts` — `FlowStep` 교체, `profile` 상태 추가,
  `missingBandInputs`는 희망 월세만 검사.
- `components/kb/JarimaegimPanel.tsx` — `STEPS` 3칸, `ProfileStep` 신설, `ConfirmStep` 재구성,
  `RecommendStep`에 배너·접이식·인라인 근거·탈락 목록, `EvidenceStep` 제거, `StepNav` 2칸.
- `components/kb/JarimaegimPlan.tsx` — `PlanBands`를 접이식 본문으로, `PlanPrescription`에서
  `BandTable` 중복 제거.
- `app/globals.css` — 신규 클래스 추가. `.kb-missing-params`는 제거한다 —
  `missing_params`는 `loan.term_months` 같은 내부 파라미터 키라 화면에 노출하지 않는다.
  무엇이 비었는지는 `message`가 우리말로 말하므로 고지 의무는 그대로 지켜진다.
- `lib/parse-case.ts` — 자치구는 전체 이름을 먼저 찾고, 없을 때만 어간을 본다.
  한 글자 어간(중구 → "중")은 "준비 중이에요"에 걸려 자치구를 통째로 잘못 채우므로 어간 검색에서 제외한다.

## 테스트

- `backend/tests` — `partial` 경로 신규 케이스. 평수·보증금 미입력 시 세 밴드의 상한과
  `stress_pass`는 나오고 `runway_months`·`required_capital_krw`가 `None`인지 확인.
  기존 191개는 그대로 통과해야 한다.
- `npm run lint` · `npm run typecheck` · `npm run api:check` · `npm run api:test`.
- `node scripts/flow-check.mjs` — 구 Workspace 경로는 그대로 두고, KB 셸의 새 흐름
  (프로필 관문 → 조건 → 입지)을 검증하는 절을 덧붙인다. 키 없는 환경의 안전 상태
  (빈 후보 목록, 빈 지원사업 목록, AI 대체 문구)를 계속 단언해야 한다.
- `node scripts/shell-check.mjs` — 옛 5스텝 전제로 짜여 있으므로 새 흐름에 맞춰 다시 쓴다.
  화면 배치 대신 **호출 순서**로 "금융이 입지보다 먼저"를 단언한다(`funding-bands` POST가
  `locations/search` POST보다 앞서야 한다). 화면 배치는 바뀔 수 있어도 이 순서는 계약이다.
  추가로 partial일 때 현금소진을 지어내지 않는지, 처방에서 밴드 표를 반복하지 않는지,
  내부 파라미터 키가 노출되지 않는지를 단언한다.

## 하지 않는 것

- 마이데이터 실연동. 게이트는 `false`로 두고 수동 어댑터만 만든다.
- 상권 임대 수준 데이터가 없으므로 "밴드별로 열리는 상권 N곳"은 여전히 제공하지 않는다.
  배너에 그 사실을 고지한다.
- 세션 만료를 넘어서는 프로필 보관. 계정을 만들지 않는다.
