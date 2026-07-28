# 처방 단계 분리 — 조달과 서류

작성일 2026-07-28 · 대상 `components/kb/{JarimaegimPanel,JarimaegimPlan}.tsx`,
`lib/{use-jarimaegim,api,types}.ts`, `backend/app/{main,models,document_store}.py`,
`scripts/{flow,visual}-check.mjs`

선행 설계 `2026-07-28-funding-step-split-ai-conditions-design.md`는 자금을 1단계로 승격해
`자금 → 조건 → 입지 → 처방` 4단계를 만든다(아직 미구현). 이 문서는 그 **마지막 칸을 둘로 나눈다**.
선행 설계를 전제로 하며, 스테퍼는 두 설계가 공유한다.

**구현 순서.** 선행 설계(`자금` 승격)를 먼저 구현한다. 두 설계가 같은 `STEPS` 배열과 같은
`FlowStep` 유니온을 고치므로, 순서를 뒤집으면 스테퍼 인덱스 매핑을 두 번 쓰게 된다. 선행 설계를
보류하기로 하면 이 문서의 스테퍼는 `[조건][입지][조달][서류]` 4칸이 되고 나머지는 그대로다.

## 문제

### 1. 무게가 다른 셋이 같은 층위에 서 있다

`PlanPrescription`(`JarimaegimPlan.tsx:186-248`)은 한 스크롤에 번호 붙은 블록 셋을 세운다.

| 블록 | 실제로 담는 것 | 사용자가 하는 일 |
|---|---|---|
| ① 계획 기준 후보 | 입지에서 이미 확정한 후보의 이름·주소·출처 | 없음 (복창) |
| ② 자금조달 레포트 | 밴드 요약 `dl` + partial 고지 + 지원사업 고지 + 신청 잠금 callout + `KbProductSection`(헤더·매칭 리드·3행·절삭 고지·면책) + 공고 로딩/빈/매칭 | 없음 (읽기) |
| ③ 문서 초안 | 버튼 1개 + 고지 2개 | 버튼 누르기 |

②만 정보 단위가 여섯이고 ①③은 하나씩인데, `kb-prescription-no`가 셋에 같은 번호를 매겨 같은
비중으로 보이게 한다. 스크롤 길이의 대부분이 ②이고, 그 안에서 무엇이 결론이고 무엇이 참고인지
구분되지 않는다.

### 2. 이 단계에는 사용자가 내리는 결정이 없다

후보는 입지에서 확정했고, 상품·공고는 읽기 전용이며, 상호작용은 PDF 버튼 하나다.
"무엇을 확인해야 하는지 모르겠다"는 반응은 화면이 사용자에게 **아무것도 묻지 않기** 때문이다.
단계를 쪼개도 각 조각이 여전히 읽기 전용이면 스크롤만 세 번으로 나뉜다.

### 3. 문서가 "상담에 가져갈 것"에 못 미친다

`render_case_pdf`(`document_store.py:64-97`)가 담는 것은 표지 표·`case.inputs` 나열·매물 섹션·
비보장 고지뿐이다. 조달 금액도, 후보 상품·공고도 들어가지 않는다. 화면 문구도 그 사실을 그대로
말하고 있다(`JarimaegimPlan.tsx:236`).

이 설계가 함께 고치는 인접 결함 둘:

- **`committed_listing_id`가 KB 흐름에서 저장되지 않는다.** 구 화면(`Workspace.tsx:34`)은 후보
  확정 시 `api.updateCase(..., { committed_listing_id })`를 호출하는데, `commitCandidate`
  (`use-jarimaegim.ts:328-344`)는 로컬 상태만 바꾼다. 그래서 `listing_section_lines`
  (`document_store.py:52-61`)는 KB 흐름에서 **항상 빈 배열**이고, 확정 후보의 상권 수치를 챗
  컨텍스트에 넣어 주는 경로(`main.py:402`)도 죽어 있다.
- **동의 게이트가 무력하다.** `api.ts:221`이 `confirmed: true`를 상수로 박아
  `CONSENT_REQUIRED`(`main.py:578`)가 한 번도 발동하지 않는다.

## 설계

### 흐름

```
FlowStep  profile → capacity → ask → confirm → recommend → funding → paperwork
스테퍼    [① 자금 ─────────]  [② 조건 ────]  [③ 입지]   [④ 조달]  [⑤ 서류]
```

스테퍼 인덱스 매핑: `profile`·`capacity` → 0, `ask`·`confirm` → 1, `recommend` → 2,
`funding` → 3, `paperwork` → 4.

경계는 UI 편의가 아니라 데이터가 정한다. `commitCandidate`는 후보를 확정하는 순간 그 매물의
보증금·월세·권리금·평수를 `bandForm`에 채우고 밴드를 다시 계산한다(`use-jarimaegim.ts:328-344`).
즉 **부족분(차입 필요액)은 후보를 확정해야만 확정된다** — ④의 질문이 성립하는 최초 시점이 정확히
거기다. 그리고 ④의 선택은 문서 내용을 바꾸므로 ⑤보다 앞에 온다.

각 화면은 질문 하나만 갖는다.

| 단계 | 질문 | 끝나는 조건 |
|---|---|---|
| ④ 조달 | 부족분을 무엇으로 메울까 | 수단을 골랐거나, 고를 것이 없음을 확인함 |
| ⑤ 서류 | 이 내용으로 문서를 만들까 | 포함 정보를 확인하고 PDF를 받음 |

### ④ 조달

`StepNav`의 라벨은 `{ recommend: "입지", funding: "조달", paperwork: "서류" }`로 늘리고
`order`는 `["recommend", "funding", "paperwork"]`가 된다.

**상단 — 계획 기준 배지.** 지금의 블록 ①(복창)을 없애고 배지 한 줄로 바꾼다. 후보명 · 도로명주소 ·
`보증금/월세` + `바꾸기`(→`recommend`). `ProfileBadge`와 같은 자리·같은 모양을 쓰되 별도
컴포넌트(`PlanBadge`)로 둔다 — 둘은 다른 값을 요약하고 다른 곳으로 돌아간다.

**본문 — 부족분 카드.** 필요자금 / 자기자본 / **부족분**을 세 줄로 세우고 부족분만 크게 둔다.
부족분은 `recommendedLine(bands).loan_krw`이며 **새 산식을 만들지 않는다** — `BandBanner`
(`JarimaegimPanel.tsx:233`)와 `KbProductSection`의 `gapKrw`(`JarimaegimPlan.tsx:193`)가 이미 쓰는
값 그대로다.

| 상태 | 부족분 자리 | 목록 | 다음 버튼 |
|---|---|---|---|
| 밴드 산출 · `loan_krw > 0` | 금액 | 선택 가능 | `고른 n건으로 문서 만들기` |
| 밴드 산출 · `loan_krw === 0` | "추가 차입 없이 자기자본으로 가능합니다" | 표시하되 선택은 선택사항 | `선택 없이 서류로` |
| `required_capital_krw === null` (partial) | 금액 + "필요자금은 평수·보증금이 있어야 계산합니다. 이 값은 권장 조달선 기준 차입액입니다" | 선택 가능 | 동일 |
| `bands.status === "integration_pending"` | `bands.message` | 조건 대조만 하고 "부족분을 계산하지 못해 금액 대조는 하지 않았습니다" | 동일 |
| `committed === null` | — | — | 빈 상태 + `입지로 돌아가기` |

**선택 목록.** `matchKbProducts` / `matchPrograms` 결과 상위 `TOP_N`(3)에 체크박스를 붙인다.
매칭 근거 칩 · 원문 링크 · "겹치는 n건 중 상위 3건" 절삭 고지 · 면책 문구는 지금 것을 그대로 옮긴다.
체크박스 라벨은 **`문서에 담기`** — 자격이나 승인 가능성 판정이 아니라는 것을 라벨 자체가 말하게
한다. `id`가 없는 행은 체크박스를 렌더하지 않는다(선택의 단위가 id이므로 id를 지어내지 않는다).

상품·공고가 **둘 다 0건**이면 "고를 수단이 없습니다. 문서에는 확정 조건과 계획 기준 후보만
담깁니다"를 쓰고 진행은 막지 않는다. Supabase가 없는 환경에서 `knowledge.kb_products()`와
`knowledge.programs()`가 모두 `[]`를 돌려주므로(`knowledge.py:35-37`) **이것이 무키 환경의
정상 경로**다.

**게이트.** 후보 미확정이면 ③ 입지의 `다음` 버튼이 잠기고 그 자리에 사유를 쓴다
("계획 기준 후보를 하나 확정해야 조달 계획을 세울 수 있습니다"). 뒤로가기나 직접 `setStep`으로
들어온 경우를 위해 ④ 자체도 빈 상태 + `입지로 돌아가기`를 갖는다(현재 블록 ①의 빈 상태 문구를
재사용한다). 두 겹으로 두는 이유는 스텝 이동 경로가 버튼 하나가 아니기 때문이다.

### ⑤ 서류

**문서에 들어갈 것** 미리보기가 `render_case_pdf`가 실제로 담는 항목과 1:1로 대응한다.
대응이 깨지면 그것이 버그다.

| 미리보기 줄 | 문서 섹션 | 비었을 때 |
|---|---|---|
| 확정 조건 | 사용자 확인값 | 항상 있음 |
| 계획 기준 후보 | `listing_section_lines` | ④ 게이트가 막으므로 정상 경로에선 항상 있음. 케이스 저장이 실패했다면 "매물 정보를 케이스에 저장하지 못했습니다" |
| 조달 요약 | `funding_section_lines` (신규) | "조달 밴드를 계산하지 못해 이 문서에는 조달 요약이 없습니다" |
| 고른 조달 수단 n건 | `selection_section_lines` (신규) | "고른 조달 수단이 없습니다" |
| 출처·기준일 | 각 섹션 말미 | "확인 필요" |
| 비보장 고지 | 기존 문단 | 항상 있음 |

**동의 체크가 `confirmed`가 된다.** "위 내용이 문서에 담기는 것을 확인했습니다" 체크박스가 꺼져
있으면 준비 버튼이 잠긴다. `api.ts`는 더 이상 `confirmed: true`를 상수로 보내지 않고 화면의 값을
보낸다 — 서버의 422는 방어선으로 그대로 남는다.

준비하기 → 내려받기 전환, `docNotice`, 보관 고지, 상담 잠금 callout은 지금 동작을 유지한다.

### 계약

`DocumentCreate`(`models.py:257-261`)에 세 필드를 더한다.

```python
selected_product_ids: list[str] = Field(default_factory=list, max_length=10)
selected_program_ids: list[str] = Field(default_factory=list, max_length=10)
funding_input: FundingFacts | None = None
```

`FundingFacts`는 `FundingBandInput`(`models.py:274-287`)에서 `case_id`만 뺀 기반 모델이고
`FundingBandInput(FundingFacts)`가 `case_id`를 더한다. 필드 정의는 한 곳에 남고 전송 모양은
그대로다. 문서 요청에 `case_id`를 두 번 싣지 않는 것이 요점이다 — 바깥 `case_id`와 다른 값이
안쪽에 들어오면 A 케이스의 문서에 B 케이스의 금액이 찍힌다.

**id만 받고 표시 문자열은 서버가 채운다.** 클라이언트가 보낸 이름·금리·URL을 그대로 인쇄하면
조작된 상품명과 금리가 KB 문서 모양으로 찍힌다. 서버는 `knowledge.kb_products()` /
`knowledge.programs()`에서 id로 조회해 이름 · 기관 · 한도·금리 **공시 문자열** · `source_as_of` ·
`official_url`을 채운다. 금리·한도는 공시 문자열을 그대로 옮기고 **가공하지 않는다**
(부록 A 불변조건 4).

조회되지 않는 id는 문서에서 빼되 응답 `message`에 "n건은 공시 목록에서 확인되지 않아
제외했습니다"로 밝힌다. 422로 막지 않는 이유는 카탈로그가 갱신된 사이 사용자가 갇히기 때문이고,
조용히 빼지 않는 이유는 절삭을 밝히는 기존 규칙과 같다(`JarimaegimPlan.tsx:173-174`).

**조달 요약 수치는 서버가 다시 계산한다.** 화면이 계산한 숫자를 받아 인쇄하면 화면과 문서가
갈라질 수 있다. `bandForm`은 케이스에 저장되지 않으므로 `funding_input`으로 실어 보내고, 서버는
`funding.compute_bands`를 호출해 문서 수치를 만든다 — 산식은 하나로 유지된다. `funding_input`이
없거나 결과가 `integration_pending`이면 조달 요약 섹션을 **생략하고 생략했다는 사실을 문서에
한 줄로 쓴다**.

`api.ts`의 `createDocument(caseId, template, payload)`는 `Idempotency-Key`를 유지한다 — 서버
상태를 만드는 mutation이다.

### `committed_listing_id` 저장

`commitCandidate`가 로컬 상태를 바꾼 뒤 `api.updateCase(caseId, version, { committed_listing_id })`
를 호출한다. 실패해도 로컬 확정은 되돌리지 않는다 — 구 화면(`Workspace.tsx:34`)의 주석이 그 이유를
이미 적어 두었다("사용자가 방금 한 것을 저장 실패가 취소해서는 안 된다"). 해제(`null` 전달) 시에도
같은 경로로 케이스를 비운다.

이 한 줄이 PDF의 매물 섹션과 챗 컨텍스트(`main.py:402`)를 함께 살린다.

### `render_case_pdf` 확장

섹션 순서: 표지 표 → 확정 조건 → 계획 기준 후보 → 조달 요약 → 고른 조달 수단 → 비보장 고지.
각 섹션 말미에 출처명·기준일 한 줄을 붙이고, 없으면 "확인 필요"라고 쓴다(부록 A 불변조건 3).

검증 가능하게 두 순수 함수를 분리한다 — `listing_section_lines`와 같은 이유다(CID 폰트로 인코딩되어
PDF 바이트 단언이 무의미하다).

```python
def funding_section_lines(bands: dict | None) -> list[str]
def selection_section_lines(products: list[dict], programs: list[dict], dropped: int) -> list[str]
```

### 상태

`useJarimaegim`에 추가:

```ts
selected: { products: string[]; programs: string[] }   // 순서 유지 → 화면 순서 = 문서 순서
toggleFunding(kind: "product" | "program", id: string): void
docConfirmed: boolean
setDocConfirmed(value: boolean): void
```

- `commitCandidate`가 `selected`를 비운다. 후보가 바뀌면 부족분이 바뀌고, 그 부족분으로 고른 수단은
  근거를 잃는다. 지금 `documents`·`docNotice`를 비우는 것과 같은 이유이며(`use-jarimaegim.ts:330`),
  ④ 화면이 "후보를 바꿔 선택을 비웠습니다"라고 말한다.
- `restart()`가 `selected`와 `docConfirmed`를 비운다.
- 공고·상품 로딩 트리거를 `step === "prescribe"`에서 `step === "funding"`으로 옮긴다
  (`use-jarimaegim.ts:401-402`).
- `prepareDocument(template)`가 `selected` · `bandForm` · `docConfirmed`를 함께 보낸다.

## 오류 처리

| 상황 | 동작 |
|---|---|
| 후보 미확정으로 ④ 진입 | 빈 상태 + `입지로 돌아가기`. ③의 다음 버튼은 애초에 잠김 |
| 밴드 미산출 | 부족분 자리에 `bands.message`. 선택도 진행도 막지 않음 |
| 공시·공고 로딩 실패 | 그 목록만 오류 + 다시 시도. 다른 목록과 진행은 살아 있음 |
| 보낸 id가 카탈로그에 없음 | 그 항목만 제외하고 제외 건수를 `message`로 고지 |
| `funding_input` 누락·계산 실패 | 조달 요약 섹션 생략 + 생략 사유 한 줄 |
| 동의 미체크 | 준비 버튼 비활성. 서버는 그대로 422 |
| 후보 변경 | 선택·문서 초기화 후 화면이 그 사실을 말함 |
| 케이스 저장 실패(`committed_listing_id`) | 로컬 확정 유지. 문서의 매물 섹션만 비고 그 사실이 미리보기에 나타남 |

## 테스트

**pytest** (`backend/tests/`)

- `funding_section_lines`: 밴드 있음 / `None` / `integration_pending` 세 경우의 문자열
- `selection_section_lines`: 선택 0건 / n건 / 제외 발생 시 제외 문구
- 카탈로그에 없는 id는 문서에서 빠지고 응답 `message`에 건수가 실린다
- 공시의 금리·한도 문자열이 가공되지 않고 원문 그대로 들어간다
- `confirmed=false`는 그대로 422 (`CONSENT_REQUIRED`)
- `selected_product_ids` 상한 초과는 422

**scripts/flow-check.mjs**

- ③ 입지에서 후보를 확정하기 전에는 `다음` 버튼이 잠겨 있다
- 후보 확정 후 ④에 부족분 금액과 계획 기준 배지가 함께 뜬다
- 무키 환경에서 ④가 "고를 수단이 없습니다"를 보이고 **그래도 ⑤로 넘어간다**
- ⑤에서 동의 체크 전에는 준비 버튼이 잠겨 있다
- 처방 화면에 `kb-prescription-no` 번호 블록이 **없다**(단계 분리 회귀 방지)

**scripts/visual-check.mjs** — ④·⑤ 두 화면을 5개 뷰포트 스냅샷 대상에 추가한다.

## 하지 않는 것

- 실제 신청·상담 이관은 그대로 off(`FINANCIAL_APPLICATION_ENABLED`, `CONSULTATION_TRANSFER_ENABLED`).
  ④의 선택은 "문서에 담기"일 뿐 신청이 아니다.
- 자격 판정을 하지 않는다. 선택 목록은 텍스트 대조 결과이며 화면과 문서 양쪽이 그렇게 말한다.
- AI가 조달 수단을 고르거나 추천 순위를 만들지 않는다. 순서는 `matchKbProducts`/`matchPrograms`의
  기존 관련도 정렬 그대로다.
- 부족분을 새로 계산하지 않는다. `recommendedLine(bands).loan_krw`를 그대로 쓴다.
- `lib/domain.ts`는 이번에도 손대지 않는다(사용처 없음).
