# 자금 단계 분리와 자연어 조건 AI 추론

작성일 2026-07-28 · 대상 `components/kb/JarimaegimPanel.tsx`, `lib/use-jarimaegim.ts`,
`lib/{api,types,constants}.ts`, `backend/app/{main,models,services,policy_params,funding}.py`,
`backend/app/condition_parse.py`(신규), `config/policy-params.json`, `scripts/{flow,visual}-check.mjs`

선행 설계 `2026-07-28-profile-first-flow-design.md`를 이어받아 두 곳을 고친다.

## 문제

### 1. 금융 입력과 조건 입력이 한 단계에 섞여 있다

`2026-07-28-profile-first-flow-design.md`가 금융 프로필을 케이스 조건에서 떼어냈지만,
떼어낸 결과를 **스텝 0 관문**으로 두었다. 그래서 세 가지가 남았다.

1. 스테퍼는 `조건 → 입지 → 처방` 셋뿐이고 프로필은 `kb-gate-rail`의 "0"으로만 표시된다
   (`JarimaegimPanel.tsx:14-16, 35`). 사용자 입장에서 자금은 단계가 아니라 통과 절차다.
2. 프로필 확정은 **아무것도 돌려주지 않는다**. `confirmProfile()`은 값을 저장하고 곧바로
   `ask`로 넘긴다(`use-jarimaegim.ts:154-157`). 자기자본을 입력한 대가로 사용자가 얻는 것이 없다.
3. 조건 화면(`ConfirmStep`)이 **희망 월세라는 금융 입력을 다시 받고**(`JarimaegimPanel.tsx:171-182`),
   자기자본·기존부채·월 고정지출 칩을 조건 칩과 같은 카드에 나란히 세운다
   (`JarimaegimPanel.tsx:164-166`). 두 종류의 입력이 한 화면에서 다시 섞인다.

### 2. "자연어 추론"이 실제로는 클라이언트 정규식이다

`AskStep`이 부르는 것은 `parseCaseText()` — 업종 힌트 13개와 금액 정규식으로 된 순수 클라이언트
파서다(`lib/parse-case.ts`). 확인 화면은 값을 칩으로 보여주지만 **무엇을 근거로 그렇게 읽었는지**
말하지 않고(`source()`는 "발화"/"직접 입력" 두 글자뿐), "이 조건이 맞나요?"라고 묻지도 않는다.
정규식 밖의 표현("월세는 삼백 정도", "손님 많은 데가 좋아요")은 전부 무시된다.

### 3. 조달 밴드는 지금 한 번도 계산되지 않는다

`config/policy-params.json`에서 `loan.term_months` · `loan.guarantee_ceiling_krw` ·
`loan.policy_fund_ceiling_krw`가 `null`이고 `industries`는 `{}`다. `policy_params.missing()`이
항상 누락을 돌려주므로 `POST /api/v1/funding-bands`는 언제나 `integration_pending`이고,
`BandBanner`(`JarimaegimPanel.tsx:205-219`)는 실제로 렌더링된 적이 없다.

## 설계

### 흐름

```
FlowStep: profile → capacity → ask → confirm → recommend → prescribe
스테퍼:   [① 자금 ─────────────]  [② 조건 ────]  [③ 입지]  [④ 처방]
```

- 프로필은 관문에서 **1단계**로 승격한다. `kb-gate-rail`은 삭제하고 스테퍼가 4칸이 된다.
- `capacity`는 신규 화면이며 1단계의 **완결점**이다. 자금을 입력한 사용자가 그 자리에서
  "얼마까지 가능한가"를 돌려받고 단계를 끝낸다.
- 조건 화면에서 금융 입력은 전부 사라진다. 희망 월세는 임대 조건이므로 조건에 남되,
  `capacity`에서 잠긴 권장 조달선을 여는 열쇠로 제시된다.
- `profile`과 `capacity`는 스테퍼 인덱스 0, `ask`와 `confirm`은 인덱스 1에 매핑한다.

계산 구조가 이 분리와 일치한다. `funding.py:84-86`의

```
borrow_ceiling  = max(0, 보증한도 + 정책자금한도 − 기존부채)
maximum_ceiling = 자기자본 + borrow_ceiling
```

는 업종·월세 없이 프로필만으로 나온다. 권장 조달선만 스트레스 테스트(업종 원가율·인건비율 +
월 고정비)를 요구하므로 2단계 이후로 간다. 즉 **1단계 = 얼마까지 가능한가, 2단계 = 어디서 무엇을
할 것인가**이며, 이 경계는 UI 편의가 아니라 산식이 정한다.

### 1단계 — 자금

#### `profile` 화면

입력 세 개(자기자본·기존 대출 잔액·월 고정지출)와 마이데이터 잠금 안내는 그대로 둔다
(부록 A 불변조건 5). 확정 버튼 문구만 `확정하고 조달 여력 보기`로 바꾸고, 다음 목적지가
`ask`가 아니라 `capacity`가 된다. `kb-reuse` 목록에서 "조건 화면에서 자기자본을 다시 묻지
않습니다"는 유지한다.

#### `capacity` 화면 (신규)

`POST /api/v1/funding-capacity`의 결과를 표시한다. 케이스가 아직 없으므로 세션만 요구한다.

| 표시 | 산식 | 성격 |
|---|---|---|
| 자기자본선 | `equity_krw` | 입력값 그대로. 차입 없이 지금 쓸 수 있는 규모 |
| 차입 여력 | `max(0, guarantee_ceiling + policy_fund_ceiling − existing_debt)` | 제도 파라미터 기반 |
| 최대 조달선 | `equity + 차입 여력` | 심사 전 추정치이며 확정 한도가 아니다 |
| 권장 조달선 | **잠금** | "업종과 희망 월세를 받으면 스트레스 테스트로 계산합니다" |

권장선은 빈칸으로 두지 않는다. 왜 아직 없는지와 무엇을 받으면 나오는지를 적는 것이 2단계로
넘어가는 동기가 된다. `parameter_status`가 `DEMO`이면 화면 전체에 `시연용` 배지와 한계 문구를
붙인다. 하단 버튼은 `조건 입력으로`(primary)와 `금액 고치기`(ghost, `profile`로 복귀).

기존 부채가 차입 여력을 0으로 만들면 최대 조달선 = 자기자본선이 되고, 화면은 그 사실을
그대로 말한다("기존 대출 잔액이 한도를 모두 소진해 추가 차입 여력이 없습니다"). 추정으로
넓히지 않는다.

#### 신규 엔드포인트

```
POST /api/v1/funding-capacity     (세션 필요, 케이스 불필요)
요청  FundingCapacityInput  { equity_krw, existing_debt_krw }
응답  FundingCapacityResult {
        status: "computed" | "integration_pending",
        equity_line_krw, borrowing_headroom_krw, maximum_line_krw,
        parameter_status: "VERIFIED" | "DEMO",
        unverified_params: string[],
        recommended_line_pending: string,   // 권장선이 아직 없는 이유
        missing_params: string[],
        message: string | null,
        provenance: Provenance | null }
```

`loan.guarantee_ceiling_krw` 또는 `loan.policy_fund_ceiling_krw`가 없으면 계산하지 않고
`integration_pending`과 `missing_params`를 돌려준다 — 시연용 값을 나중에 걷어내도 화면이
추정으로 넘어가지 않는다. `funding.py`에 `compute_capacity(params, *, equity_krw,
existing_debt_krw)`를 추가하고 `compute_bands`가 같은 함수를 써서 두 경로의 산식이 갈라지지
않게 한다.

`provenance`는 `source_name="자리매김 조달 여력 계산"`, `confidence="LOW"`,
`limitations`에 미검증 파라미터 목록과 "신용평가·보증 심사 전 추정치" 문구를 싣는다
(부록 A 불변조건 3).

### 시연용 파라미터 등록

`config/policy-params.json`의 모든 entry와 industry 항목에 `"verified": true | false`를
명시한다. 미검증 값은 다음 모양으로만 들어간다.

```json
"loan.policy_fund_ceiling_krw": {
  "value": 70000000, "unit": "KRW", "verified": false,
  "source": "시연용 미검증 값 — 2차 출처 7,000만원. 2026년 융자사업 공고 원문 미확인.",
  "as_of": "2026-07-28"
}
```

등록 대상:

| 키 | 시연용 값 | 근거 상태 |
|---|---|---|
| `loan.term_months` | 60 | 2차 출처 5년(거치 2년 포함), 원문 미확인 |
| `loan.guarantee_ceiling_krw` | 100,000,000 | 지역신용보증재단 상품별 상이, 단일 값 미성립 |
| `loan.policy_fund_ceiling_krw` | 70,000,000 | 2차 출처, 공고 원문 미확인 |
| `industries.*` | 8개 업종 | 공적 통계에서 단일 값으로 뽑히지 않음 |

업종 8종은 `parse-case.ts`의 `INDUSTRY_HINTS`가 실제로 뱉는 이름과 일치시킨다. 값은 전부
`verified: false`이며 `source`는 "시연용 미검증 값 — 공적 통계에서 단일 값으로 뽑히지 않아
설계 가정값을 등록한다"로 통일한다.

| 업종 | `cogs_ratio` | `labor_ratio` | `fitout_krw_per_pyeong` | `operating_days_per_month` |
|---|---|---|---|---|
| 카페 | 0.35 | 0.25 | 2,500,000 | 30 |
| 제과점 | 0.40 | 0.25 | 3,000,000 | 30 |
| 치킨전문점 | 0.42 | 0.20 | 2,200,000 | 30 |
| 분식점 | 0.38 | 0.22 | 1,800,000 | 26 |
| 주점 | 0.33 | 0.25 | 2,600,000 | 26 |
| 편의점 | 0.72 | 0.12 | 1,500,000 | 30 |
| 미용실 | 0.20 | 0.40 | 2,800,000 | 26 |
| 일반음식점 | 0.40 | 0.25 | 2,400,000 | 26 |

공헌이익률(`1 − cogs − labor`)이 8종 모두 양수여야 `compute_bands`가 `ValueError`를 던지지
않는다. 위 값은 최소 0.16(편의점)으로 전부 양수다. 목록에 없는 업종은
지금처럼 `industries.<업종>` 누락으로 `integration_pending`이 되며, 화면은 "등록된 업종
파라미터가 없어 밴드를 계산하지 않습니다"라고 말한다. 이것이 정상 경로다.

`policy-params.json` 상단의 `note`는 "비워 둔다"에서 "시연용 값으로 채웠고 `verified: false`로
표시했다. 실서비스 전에 공고 원문으로 대체해야 한다"로 갱신하고, 대체가 필요한 항목 목록은
그대로 남긴다.

코드 변경:

- `PolicyParams.unverified(industry) -> list[str]` 추가. 해당 산출에 실제로 쓰인 키 중
  `verified`가 false인 것만 돌려준다.
- `FundingBandResult`와 `FundingCapacityResult`가 `parameter_status`와 `unverified_params`를
  싣는다. `unverified_params`가 비어 있지 않으면 `parameter_status`는 반드시 `DEMO`다.
- UI는 `DEMO`일 때 `시연용` 배지와 "미검증 시연용 파라미터로 계산했습니다" 한계 문구를
  **끌 수 없게** 붙인다. `data/listings.seoul.json`의 시연용 매물이 `demo-badge`를 다는 것과
  같은 취급이다(부록 A 불변조건 1의 "없는 근거는 만들지 않는다"를 만족시키는 방법은
  값을 숨기는 것이 아니라 값의 성격을 밝히는 것이다).

### 2단계 — 조건

#### `ask` 화면

textarea와 예시 버튼 구조는 유지한다. 자기자본은 프로필이 들고 있으므로 예시 문장에서 금액은
희망 월세 쪽으로 바꾼다.

```
"마포구에서 카페 준비 중이고 월세는 300 정도 생각해요"
"성동구에 2호점 낼 자리 찾고 있어요. 임대료 부담이 제일 걱정이에요"
"관악구 분식점 자리요. 처음 창업이라 안정적인 곳이면 좋겠어요"
```

제출하면 `POST /api/v1/conditions/interpret`를 호출하고, 응답을 `confirm`으로 넘긴다.
호출 중에는 버튼이 스피너 상태가 되며(`flow.busy === "interpret"`), 실패해도 흐름이 막히지
않도록 서버가 규칙 추출 결과로 응답한다(아래 폴백 참조).

`직접 입력으로 시작`은 남기되 서버를 거치지 않고 빈 제안으로 곧장 `confirm`에 들어간다.

#### 신규 엔드포인트

```
POST /api/v1/conditions/interpret   (세션 필요, 케이스 불필요)
요청  ConditionInterpretRequest { text: string }        // 1..500자
응답  ConditionInterpretResult {
        source: "AI" | "RULE",
        fields: {
          industry:         ConditionField<string>,
          district:         ConditionField<string>,
          monthly_rent_krw: ConditionField<int>,
          business_stage:   ConditionField<BusinessStage>,
          startup_type:     ConditionField<StartupType>,
          priority:         ConditionField<Priority> },
        unresolved: string[],      // value 가 null 인 필드 이름
        message: string }

ConditionField<T> { value: T | null, evidence: string | null }
```

`equity_krw`와 `budget_krw`는 **추출 대상이 아니다**. 프로필이 소유하는 값을 발화가 덮어쓰면
1단계에서 확정한 것이 2단계에서 조용히 흔들린다.

#### AI가 값을 만들지 못하게 막는 법

프롬프트 문구가 아니라 코드로 강제한다. `AIService.interpret_conditions(text)`가 Responses API
구조화 출력으로 위 모양을 받은 뒤, 서버가 필드마다 다음 게이트를 통과시킨다.

1. **evidence 부분문자열 검증** — `evidence`가 사용자 원문의 부분문자열이 아니면 그 필드를
   버리고 `unresolved`에 넣는다. 모델이 "카페면 보통 월세 300쯤"이라고 채우면 그 근거 문구가
   원문에 없으므로 통과할 수 없다. 이것이 이 설계의 핵심 게이트다.
2. **서울 스코프** — `district`가 `SEOUL_DISTRICTS` 밖이면 버린다(부록 A 불변조건 6).
3. **금액 범위** — `monthly_rent_krw`는 정수·양수·`MAX_KRW`(1,000억) 이하만 통과한다.
4. **열거형 일치** — `business_stage` / `startup_type` / `priority`는 정의된 값만 통과한다.
5. **null 우선** — 문장에 없는 것은 전부 `null`. 프롬프트는 추론·보완·평균값 채우기를 금지하고,
   산술(합계·평당 환산·비율)도 금지한다(부록 A 불변조건 4).
6. `store=False`로 호출한다.

모델 호출이 실패하거나, 빈 응답이거나, 스키마를 어기면 예외를 삼키고 규칙 추출로 내려간다.
`AIService.explain`이 이미 쓰는 실패 처리 방식과 같다.

#### 무키 폴백

`OPENAI_API_KEY`가 없거나 `ai_explanation_enabled`가 꺼져 있으면 `source: "RULE"`로
`backend/app/condition_parse.py`가 응답을 만든다. 이 파일은 `lib/parse-case.ts`의 이식본이며,
자기자본·총예산 추출은 빼고 희망 월세 추출을 넣는다. 규칙 경로도 **같은 evidence 계약을 지킨다** —
정규식이 맞춘 원문 구간을 그대로 `evidence`에 넣으므로 확인 화면의 인용 표시가 두 경로에서
동일하게 동작한다.

`lib/parse-case.ts`는 삭제한다. 추출 규칙이 클라이언트와 서버 두 곳에 살아 있으면 반드시
갈라진다.

#### `confirm` 화면 — "이 조건이 맞나요?"

제목이 말 그대로 질문이 되고, 필드마다 값·발화 인용·출처가 한 줄로 붙는다.

```
업종       카페         「카페 준비」        AI 추론    [고치기]
자치구     마포구       「마포구에서」       AI 추론    [고치기]
희망 월세  300만원      「월세는 300 정도」  AI 추론    [고치기]
사업단계   처음 창업     —                   기본값     [고치기]
창업형태   미정          —                   기본값     [고치기]

        [ 네, 맞아요 ]   [ 아니요, 고칠게요 ]   [ 다시 말할게요 ]
```

- 출처 라벨은 `AI 추론` · `규칙 추출` · `직접 입력` · `기본값` 네 가지다(부록 A 불변조건 3).
  응답의 `source`가 `AI`면 evidence가 있는 필드는 `AI 추론`, `RULE`이면 `규칙 추출`이다.
  사용자가 고친 필드는 `직접 입력`, 한 번도 채워지지 않아 `DEFAULT_CASE` 값이 남은 필드는
  `기본값`이다.
- 인용구는 서버가 부분문자열 검증을 통과시킨 `evidence` 값 그대로다. 없으면 `—`.
- `네, 맞아요`는 `flow.start()`를 호출한다. 필수 항목(업종·희망 월세)이 비어 있으면 잠기고,
  그 항목만 인라인 질문으로 남는다. 지금 `ConfirmStep`의 "이 화면에 있는 동안 질문은 더해지기만
  한다" 로직(`JarimaegimPanel.tsx:143-148`)과 그 주석은 그대로 유지한다 — 입력 중 언마운트
  버그를 다시 만들지 않기 위해 존재하는 코드다.
- `아니요, 고칠게요`는 지금의 `조건 고치기` 접이식을 펼친다(업종·자치구·사업단계·창업형태·우선순위).
- `다시 말할게요`는 `ask`로 돌아가되 입력했던 문장을 그대로 복원한다.
- **자기자본·기존부채·월 고정지출 칩은 이 카드에서 제거한다.** 상단 `ProfileBadge`가 확정 요약과
  `수정` 경로를 계속 제공하므로 정보는 사라지지 않고, 입력 화면에서만 빠진다.

### 상태

`useJarimaegim`에 추가:

```ts
capacity: FundingCapacityResult | null
capacityState: LocationState
proposal: ConditionInterpretResult | null   // 출처 라벨과 인용의 원본
interpretText: string                        // '다시 말할게요' 복원용
```

- `confirmProfile()`은 프로필을 저장한 뒤 `capacity`로 가고 여력 조회를 띄운다.
- `interpret()`은 서버 호출을 감싸는 async 함수가 되고, 응답의 non-null 필드를 `form`/`bandForm`에
  반영한 뒤 `confirm`으로 넘긴다. `parsedKeys: Set<keyof CaseInput>`는 `proposal` 기반 출처 계산으로
  대체하고 제거한다.
- `restart()`는 `ask`로 돌아가며 `proposal`·`interpretText`를 비운다. 프로필과 `capacity`는
  건드리지 않는다 — 조건을 다시 받는다고 자금을 다시 묻지 않는다는 기존 원칙 그대로다.
- 복원된 프로필이 있을 때 마운트 시 건너뛰는 목적지는 `ask`가 아니라 `capacity`다. 저장된 값으로
  계산한 여력을 먼저 보여주고 조건으로 보낸다.

### 계약 정합

`backend/app/models.py`에 `FundingCapacityInput` · `FundingCapacityResult` ·
`ConditionInterpretRequest` · `ConditionField` · `ConditionInterpretResult`를 추가하고,
`lib/types.ts`에 snake_case 그대로 필드 대 필드로 미러링한다. `lib/api.ts`에
`fundingCapacity(profile)`와 `interpretConditions(text)`를 추가한다. 둘 다 서버 상태를 만들지
않는 조회형 POST이므로 `Idempotency-Key`를 붙이지 않는다 — 같은 성격인 `searchLocations`
(`lib/api.ts:203`)의 선례를 따른다. 컴포넌트는 `fetch`를 직접 부르지 않는다.

## 오류 처리

| 상황 | 동작 |
|---|---|
| 여력 조회 실패 | `capacityState="error"`, 재시도 버튼. 조건으로 넘어가는 길은 막지 않는다 |
| 제도 파라미터 누락 | `integration_pending` + 누락 키 표시. 추정하지 않는다 |
| AI 호출 실패·빈 응답·스키마 위반 | 규칙 추출로 폴백. `source: "RULE"` |
| evidence 검증 실패 | 해당 필드만 드롭 후 `unresolved`. 전체 응답은 유지 |
| 서울 밖 자치구 | 해당 필드 드롭 + "서울 25개 자치구만 지원합니다" 안내 |
| 빈 발화 | 버튼 비활성. 서버는 1자 미만을 422로 거절 |

## 테스트

**pytest** (`backend/tests/`)

- `compute_capacity` 산식: 기존부채 0 / 부분 소진 / 전액 소진(차입 여력 0) / 한도 미등록
- `PolicyParams.unverified`: 시연용 값이 `DEMO`를 유발하고 검증 값만 쓰면 `VERIFIED`
- evidence 부분문자열 검증: 원문에 없는 evidence를 단 필드는 드롭된다
- 서울 밖 자치구 드롭, 금액 상한·음수 거절, 열거형 밖 값 거절
- 무키 폴백이 `source: "RULE"`과 evidence를 채운 응답을 돌려준다
- `POST /api/v1/conditions/interpret`가 케이스 없이 세션만으로 200을 준다

**scripts/flow-check.mjs**

버튼 라벨 변경을 반영한다: `확정하고 조달 여력 보기` → `조건 입력으로` → `조건으로 정리하기`
→ `네, 맞아요` → `이 조건으로 입지 찾기`. 추가 단언:

- `capacity` 화면에 최대 조달선 금액과 `시연용` 배지가 함께 뜬다
- 무키 환경에서 확인 화면의 출처 라벨이 `규칙 추출`이다
- 확인 화면에 자기자본·기존부채·월 고정지출 칩이 **없다**(단계 분리 회귀 방지)

**scripts/visual-check.mjs** — `capacity` 화면을 5개 뷰포트 스냅샷 대상에 추가한다.

## 하지 않는 것

- 대화(`/messages`, `/messages/stream`)로 조건을 바꾸는 경로는 열지 않는다. `confirmed_case_patch`
  422는 그대로다. 조건 추론은 별도 엔드포인트이며 사용자의 명시적 확인 없이는 케이스가 되지 않는다.
- 마이데이터 실연동, 금융 신청, 상담 이관 게이트는 그대로 off.
- `lib/domain.ts`는 이번에도 손대지 않는다(사용처 없음).
