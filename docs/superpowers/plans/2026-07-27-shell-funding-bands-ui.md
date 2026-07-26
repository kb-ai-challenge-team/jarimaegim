# 화면 A — 조달 밴드 UI 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 랜딩(`/`)의 `자리매김 AI` 패널 5단계(`상황 · 입지 · 근거 · 비용 · 자금`)에 조달 밴드 3중선과 손익분기선을 반영한다. `비용` 단계를 밴드 화면으로 교체하고, 케이스 생성 직후 밴드를 자동 산출한다.

**Architecture:** 흐름 상태는 전부 `lib/use-jarimaegim.ts` 한 곳이 소유한다. 밴드도 같은 훅에 넣고, 기존 `trace`(네트워크 경계마다 한 단계) 시스템에 `bands` 단계를 추가해 산출 과정이 화면에 그대로 보이게 한다. 패널 컴포넌트는 훅이 준 값을 렌더만 한다.

**Tech Stack:** Next.js 16 App Router · React 클라이언트 컴포넌트 · `lib/api.ts`(유일한 fetch 계층) · `app/globals.css` 평문 CSS · lucide-react

---

## 스펙 대응

| 스펙 절 | 이 계획에서 |
|---|---|
| §5.1 스테이지 매핑 | 화면 A의 5단계에 매핑. **아래 "스펙 §5.1 정정" 참조** |
| 결정 4 (권장 밴드 자동 진행 + 대칭 배너) | Task 1(자동 산출) · Task 4(배너) |
| §3.7 DS-09 미확보 시 동작 | Task 4 — 밴드별 상권 수를 표시하지 않는다 |
| §3.7 파라미터 미등록 시 동작 | Task 3 — `integration_pending` 안내 + 누락 키 목록 |
| §5.2 `CostService` 폐기 | **화면 A에서만 폐기.** 아래 참조 |

### 스펙 §5.1 정정이 필요하다

스펙 §5.1은 매핑을 **화면 B(`Workspace`, `/cases/{id}/…`)의 6스테이지 URL** 기준으로 적었다. 실제 구현 대상은 **화면 A(`KbShell`의 `자리매김 AI` 패널 5단계)** 다. 두 화면은 서로 링크가 없는 별개 UI다.

| 화면 A 단계 (`FlowStep`) | 라벨 | 이 계획에서의 역할 |
|---|---|---|
| `ask` → `confirm` | 상황 | 조건 입력. **임대 조건 3필드 추가** (평수·보증금·월세) |
| — | — | 케이스 생성 직후 **밴드 자동 산출** (trace 단계로 노출) |
| `recommend` | 입지 | 후보 목록 + **밴드 컨텍스트 · 확장·축소 배너** |
| `evidence` | 근거 | 현행 유지 (4축은 D2~D6, 전부 비활성) |
| `cost` | 비용 | **조달 밴드 3중선 + 손익분기선 + 필요자금 내역 조정** |
| `funding` | 자금 | KB 상품 + 공고 + **밴드 요약**. 매칭 기준을 밴드 차입액으로 |

**Task 7에서 스펙 §5.1을 이 표로 교체한다.**

### `CostService`는 화면 A에서만 폐기한다

스펙 §5.2는 `POST /api/v1/cost-plans`·`CostService`·`CostItem`·`CostPlan`의 전면 제거를 지시한다. 그러나 **화면 B(`Workspace.tsx`의 `CostView`)가 같은 API를 쓰고 있고, 화면 B는 이 계획의 범위가 아니다.** API를 지우면 화면 B가 깨진다.

따라서 이 계획은:

- 화면 A에서 `PlanCost`와 `flow.saveCost`·`flow.costPlan` 사용을 **제거**한다. 화면 A는 더 이상 같은 값을 두 번 묻지 않는다.
- `POST /api/v1/cost-plans`·`CostService`·`CostItem`·`CostPlan` 타입은 **남긴다.** 화면 B가 계속 쓴다.
- 전면 폐기는 화면 B의 처리 방침이 정해진 뒤 별도 계획으로 한다. **Task 7에서 스펙 §5.2에 이 단서를 기록한다.**

### 범위 밖

후보를 밴드 내 상권에서 생성하는 것(DS-09·DS-04 필요), 4축 판정(D2~D6), 지원금의 조달선 상향 반영(DS-07/08), 밴드 결과 영속화(가드 2), 화면 B 수정.

---

## 파일 구조

| 파일 | 책임 | 변경 |
|---|---|---|
| `lib/constants.ts` | `DEFAULT_BAND_FORM` 추가 | 수정 |
| `lib/use-jarimaegim.ts` | 밴드 상태·산출·trace 단계 소유 | 수정 |
| `components/kb/JarimaegimPanel.tsx` | 상황 단계 3필드, 입지 단계 배너, 비용 단계 교체 | 수정 |
| `components/kb/JarimaegimPlan.tsx` | `PlanCost` 제거, `PlanBands` 신설, `PlanFunding` 확장 | 수정 |
| `app/globals.css` | 밴드 표·배너 스타일 | 수정 |
| `scripts/shell-check.mjs` | **화면 A e2e 안전 상태 검증 (신규)** | 생성 |
| `package.json` | `check:shell` 스크립트 | 수정 |

`lib/api.ts`·`lib/types.ts`는 D0에서 이미 `fundingBands`와 타입을 갖췄으므로 변경하지 않는다.

**화면 B 무영향 확인됨.** `PlanCost`·`PlanFunding`을 참조하는 곳은 `components/kb/JarimaegimPanel.tsx` 뿐이다. 화면 B(`Workspace.tsx`)는 자체 `CostView`와 `api.createCostPlan`을 따로 쓰므로, `PlanCost`를 지우고 `POST /cost-plans`를 남기면 화면 B는 그대로 동작한다. `formatKrw`는 `lib/constants.ts:67`에 있다(`lib/domain.ts`의 동명 함수는 사문이므로 쓰지 않는다).

---

## Task 1: 훅에 밴드 상태와 자동 산출 추가

**Files:**
- Modify: `lib/constants.ts`
- Modify: `lib/use-jarimaegim.ts`

- [ ] **Step 1: 기본값 상수 추가**

`lib/constants.ts`에서 `DEFAULT_CASE` 선언 **바로 아래**에 추가한다.

```typescript
export const DEFAULT_BAND_FORM = {
  area_pyeong: 0,
  deposit_krw: 0,
  monthly_rent_krw: 0,
  monthly_maintenance_krw: 0,
  key_money_krw: 0,
  fitout_krw: null as number | null,
  existing_debt_krw: 0,
  other_monthly_fixed_krw: 0
};
```

- [ ] **Step 2: 훅 import와 타입 추가**

`lib/use-jarimaegim.ts`의 import 두 줄을 바꾼다.

```typescript
import { DEFAULT_BAND_FORM, DEFAULT_CASE, formatKrw } from "./constants";
import type { AnalysisResult, BandLine, Candidate, CaseInput, CaseRecord, CostItem, CostPlan, FundingBandResult, KbProduct, Program, StatusResponse } from "./types";
```

`FlowStep` 선언 아래에 추가한다.

```typescript
export type BandForm = typeof DEFAULT_BAND_FORM;
```

- [ ] **Step 3: trace에 `bands` 단계 추가**

`planTrace`의 `steps` 배열에서 `case`와 `search` **사이에** 한 항목을 넣고, 마지막 줄의 `slice(2)`를 `slice(3)`으로 바꾼다.

```typescript
function planTrace(inputs: CaseInput, leg: "full" | "search"): TraceStep[] {
  const steps: TraceStep[] = [
    { id: "session", label: "익명 세션 확인", detail: "계정 없이 익명 세션으로 진행합니다. 조건은 최대 24시간만 보관합니다.", status: "idle" },
    { id: "case", label: "입력 조건 확정", detail: "서울 25개 자치구 범위인지 서버에서 검증하고 케이스로 저장합니다.", status: "idle" },
    { id: "bands", label: "조달 밴드 산출", detail: "자기자본과 임대 조건으로 자기자본선·권장 조달선·최대 조달선과 손익분기선을 계산합니다. 외부 데이터는 쓰지 않습니다.", status: "idle" },
    { id: "search", label: "공식 장소 데이터 조회", detail: `Kakao Local 장소 검색 · 질의어 "서울 ${inputs.district} ${inputs.industry}" · 정확도순 최대 12곳`, status: "idle" },
    { id: "grade", label: "근거 등급·출처 정리", detail: "후보마다 확인 가능한 근거 등급과 출처만 붙입니다. 없는 근거는 만들지 않습니다.", status: "idle" }
  ];
  return leg === "full" ? steps : steps.slice(3);
}
```

- [ ] **Step 4: 권장 밴드 추출 헬퍼와 입력 가드 추가**

> **실행 중 발견된 편차.** 백엔드 `FundingBandInput.area_pyeong`은 `gt=0`이다. 기본값 0으로 호출하면 400 `VALIDATION_ERROR`가 나고, 그 예외가 `start()`의 catch로 흘러 **입지 검색까지 통째로 중단된다.** 평수 미입력이 후보 찾기를 막아서는 안 되므로, 입력이 부족하면 **서버를 부르지 않고** 명시적 대기 상태를 반환한다(스펙 §3.7 패턴).

`gradeNote` 함수 **아래**에 추가한다.

```typescript
/** 권장 조달선. 밴드는 항상 자기자본선·권장·최대 순서로 오지만 순서에 의존하지 않는다. */
export function recommendedLine(result: FundingBandResult | null): BandLine | null {
  return result?.bands.find((line) => line.band === "RECOMMENDED") ?? null;
}

/** 밴드 계산에 필요한 임대 조건이 채워졌는지. 비면 서버를 부르지 않고 대기 상태로 둔다. */
function missingBandInputs(input: BandForm): string[] {
  const gaps: string[] = [];
  if (input.area_pyeong <= 0) gaps.push("희망 평수");
  if (input.deposit_krw <= 0) gaps.push("희망 보증금");
  if (input.monthly_rent_krw <= 0) gaps.push("희망 월세");
  return gaps;
}

function inputPending(gaps: string[]): FundingBandResult {
  return {
    status: "integration_pending", required_capital_krw: null, required_capital_band: null,
    bands: [], break_even: null, missing_params: gaps,
    message: `${gaps.join(" · ")}을 입력하면 조달 밴드를 계산합니다. 입력 전에는 값을 추정하지 않습니다.`, provenance: null
  };
}
```

- [ ] **Step 5: 훅에 상태와 산출 함수 추가**

`const [costPlan, setCostPlan] = useState<CostPlan | null>(null);` **아래**에 세 줄을 추가한다.

```typescript
  const [bandForm, setBandForm] = useState<BandForm>(DEFAULT_BAND_FORM);
  const [bands, setBands] = useState<FundingBandResult | null>(null);
  const [bandState, setBandState] = useState<LocationState>("idle");
```

`setField` 콜백 **아래**에 추가한다.

```typescript
  /** 모든 BandForm 값이 number 또는 number|null 이므로 단일 시그니처로 둔다.
   *  제네릭으로 두면 컴포넌트 prop 으로 넘길 때 반공변 위치에서 타입이 어긋난다. */
  const setBandField = useCallback((key: keyof BandForm, value: number | null) => {
    setBandForm((prev) => ({ ...prev, [key]: value } as BandForm));
  }, []);
```

`runSearch` 콜백 **아래**에 추가한다.

```typescript
  /** 조달 밴드 산출. 후보와 무관하게 사용자 조건만으로 계산되므로 입지 조회보다 먼저 실행한다. */
  const runBands = useCallback(async (record: CaseRecord, input: BandForm) => {
    const gaps = missingBandInputs(input);
    if (gaps.length > 0) {
      const pending = inputPending(gaps);
      setBands(pending); setBandState("integration_pending");
      return pending;
    }
    setBandState("loading");
    const result = await api.fundingBands(record.id, {
      industry: record.inputs.industry, equity_krw: record.inputs.equity_krw, ...input
    });
    setBands(result);
    setBandState(result.status === "computed" ? "success" : "integration_pending");
    return result;
  }, []);
```

- [ ] **Step 6: `start()`에서 밴드를 자동 산출**

`start` 콜백의 `try` 블록에서 `settleStep("case", ...)` 다음 줄에 밴드 산출을 끼워 넣고, 의존성 배열에 `bandForm`·`runBands`를 추가한다.

```typescript
  const start = useCallback(async () => {
    setError(""); setBusy("case"); setStep("recommend");
    beginTrace(planTrace(form, "full"));
    try {
      await ensureSession();
      settleStep("session", "done", "익명 세션 확인됨");
      const title = `${form.district} ${form.industry}`.trim() || "새 케이스";
      const record = await api.createCase(form, title);
      setCaseData(record);
      settleStep("case", "done", `케이스 저장됨 · 버전 ${record.version}`);
      const band = await runBands(record, bandForm);
      const line = recommendedLine(band);
      settleStep("bands", band.status === "computed" ? "done" : "skipped",
        line && band.break_even
          ? `권장 조달선 ${formatKrw(line.ceiling_krw)} · 목표 일매출 ${formatKrw(band.break_even.target_daily_revenue_krw)}`
          : band.message || "제도 파라미터 등록 대기");
      await runSearch(record);
      await handoff();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "케이스를 만들지 못했습니다.";
      failTrace(message); setLocationState("error"); setError(message);
    } finally { setBusy(""); }
  }, [bandForm, beginTrace, ensureSession, failTrace, form, handoff, runBands, runSearch, settleStep]);
```

- [ ] **Step 7: 비용 단계용 재계산 함수 추가**

`saveCost` 콜백 **아래**에 추가한다. `saveCost`는 화면 B가 계속 쓰므로 남긴다.

```typescript
  /** 비용 단계에서 필요자금 내역을 고친 뒤 다시 계산한다. */
  const recomputeBands = useCallback(async () => {
    if (!caseData) return;
    setBusy("bands"); setError("");
    try { await runBands(caseData, bandForm); }
    catch (err) {
      setBandState("error");
      setError(err instanceof ApiError ? err.message : "조달 밴드를 계산하지 못했습니다.");
    } finally { setBusy(""); }
  }, [bandForm, caseData, runBands]);
```

- [ ] **Step 8: `reset`과 반환값 갱신**

`reset` 콜백의 마지막 `setTraceOpen(false);` 앞에 추가한다.

```typescript
    setBandForm(DEFAULT_BAND_FORM); setBands(null); setBandState("idle");
```

반환 객체의 첫 줄과 둘째 줄을 바꾼다.

```typescript
    step, setStep, form, setField, parsedKeys, interpret, caseData, candidates, locationState, focused, setFocused,
    bandForm, setBandField, bands, bandState, recomputeBands,
```

- [ ] **Step 9: 타입 검사**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run typecheck && npm run lint
```

기대: 둘 다 오류 0건. `formatKrw`가 `lib/constants.ts`에 없다면 실제 export 위치를 확인해 import를 고친다.

- [ ] **Step 10: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add lib/constants.ts lib/use-jarimaegim.ts
git commit -m "feat: compute the funding band right after the case is created"
```

---

## Task 2: 상황 단계에 임대 조건 3필드

밴드 계산에 필요한 8개 값 중 **평수·보증금·월세 3개만** 여기서 받는다. 나머지 5개(관리비·권리금·인테리어·기존부채·기타고정비)는 0/미입력으로 두고 비용 단계에서 조정한다. 조건 화면이 이미 촘촘하므로 더 늘리지 않는다.

**Files:**
- Modify: `components/kb/JarimaegimPanel.tsx`

- [ ] **Step 1: `ConfirmStep`에 필드 추가**

`ConfirmStep`의 `ready` 계산과 `kb-form` 블록을 바꾼다.

```tsx
function ConfirmStep({ flow }: { flow: Jarimaegim }) {
  const { form, bandForm, parsedKeys, setField, setBandField } = flow;
  const ready = Boolean(form.industry.trim()) && form.budget_krw > 0 && form.equity_krw >= 0;
  const mark = (key: keyof CaseInput) => parsedKeys.has(key) ? "parsed" : undefined;
  return <div className="kb-step">
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>정리한 조건입니다. 확인하고 고쳐 주세요. 이 값이 그대로 분석 기준이 됩니다.</p></div>
    <div className="kb-form">
      <label className="kb-field" data-mark={mark("industry")}><span>업종</span><input value={form.industry} onChange={(event) => setField("industry", event.target.value)} placeholder="예: 카페" /></label>
      <label className="kb-field" data-mark={mark("district")}><span>자치구</span><select value={form.district} onChange={(event) => setField("district", event.target.value)}>{SEOUL_DISTRICTS.map((district) => <option key={district} value={district}>{district}</option>)}</select></label>
      <label className="kb-field" data-mark={mark("budget_krw")}><span>총예산</span><input type="number" min="0" step="1000000" inputMode="numeric" value={form.budget_krw || ""} onChange={(event) => setField("budget_krw", Math.max(0, Number(event.target.value)))} placeholder="0" /><em>{form.budget_krw > 0 ? formatKrw(form.budget_krw) : "원"}</em></label>
      <label className="kb-field" data-mark={mark("equity_krw")}><span>자기자본</span><input type="number" min="0" step="1000000" inputMode="numeric" value={form.equity_krw || ""} onChange={(event) => setField("equity_krw", Math.max(0, Number(event.target.value)))} placeholder="0" /><em>{form.equity_krw > 0 ? formatKrw(form.equity_krw) : "원"}</em></label>
      <label className="kb-field"><span>희망 평수</span><input type="number" min="0" step="1" inputMode="numeric" value={bandForm.area_pyeong || ""} onChange={(event) => setBandField("area_pyeong", Math.max(0, Number(event.target.value)))} placeholder="0" /><em>{bandForm.area_pyeong > 0 ? `${bandForm.area_pyeong}평` : "평"}</em></label>
      <label className="kb-field"><span>희망 보증금</span><input type="number" min="0" step="1000000" inputMode="numeric" value={bandForm.deposit_krw || ""} onChange={(event) => setBandField("deposit_krw", Math.max(0, Number(event.target.value)))} placeholder="0" /><em>{bandForm.deposit_krw > 0 ? formatKrw(bandForm.deposit_krw) : "원"}</em></label>
      <label className="kb-field"><span>희망 월세</span><input type="number" min="0" step="100000" inputMode="numeric" value={bandForm.monthly_rent_krw || ""} onChange={(event) => setBandField("monthly_rent_krw", Math.max(0, Number(event.target.value)))} placeholder="0" /><em>{bandForm.monthly_rent_krw > 0 ? formatKrw(bandForm.monthly_rent_krw) : "원"}</em></label>
    </div>
    <ChipRow label="사업단계" mark={mark("business_stage")} value={form.business_stage} options={STAGE_LABELS} onSelect={(value) => setField("business_stage", value as CaseInput["business_stage"])} />
    <ChipRow label="창업형태" mark={mark("startup_type")} value={form.startup_type} options={TYPE_LABELS} onSelect={(value) => setField("startup_type", value as CaseInput["startup_type"])} />
    <ChipRow label="우선순위" mark={mark("priority")} value={form.priority} options={PRIORITY_LABELS} onSelect={(value) => setField("priority", value as CaseInput["priority"])} />
    <button className="kb-primary" onClick={flow.start} disabled={!ready || flow.busy === "case"}>{flow.busy === "case" ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}이 조건으로 입지 찾기</button>
    {!ready && <p className="kb-note"><CircleHelp aria-hidden="true" />업종과 총예산을 채워야 시작할 수 있습니다.</p>}
    <p className="kb-note"><Info aria-hidden="true" />임대 조건은 상업용 임대료 공개 원천이 없어 직접 입력받습니다. 비용 단계에서 항목을 더 조정할 수 있습니다.</p>
  </div>;
}
```

- [ ] **Step 2: `Info` 아이콘 import 추가**

`components/kb/JarimaegimPanel.tsx` 첫 import 줄의 lucide 목록에 `Info`를 알파벳 순서로 넣는다.

```tsx
import { AlertCircle, ArrowRight, Check, ChevronRight, CircleHelp, Info, LoaderCircle, RefreshCw, RotateCcw, Search, ShieldCheck, Sparkles, X } from "lucide-react";
```

- [ ] **Step 3: 타입 검사와 린트**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run typecheck && npm run lint
```

기대: 오류 0건.

- [ ] **Step 4: 눈으로 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && node -e '
const {createRequire}=require("module");const {chromium}=require("playwright-core");
(async()=>{const b=await chromium.launch({headless:true,executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"});
const p=await(await b.newContext({viewport:{width:560,height:1000}})).newPage();
await p.goto("http://127.0.0.1:4173/",{waitUntil:"networkidle"});
await p.locator(".kb-examples button").first().click();
await p.getByRole("button",{name:"조건으로 정리하기"}).click();
await p.waitForSelector(".kb-form");
console.log(await p.locator(".kb-form .kb-field span").allTextContents());
await p.screenshot({path:"/private/tmp/claude-501/-Users-jiwon-Desktop-KB-AI-Challenge/bc52a3c0-16d4-4702-adbb-0ae89228b0a6/scratchpad/confirm.png",fullPage:true});
await b.close();})();'
```

기대: 출력에 `희망 평수`, `희망 보증금`, `희망 월세`가 포함된다. dev 서버(`npm run dev`)가 떠 있어야 한다.

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add components/kb/JarimaegimPanel.tsx
git commit -m "feat: collect the lease conditions the funding band needs"
```

---

## Task 3: 비용 단계를 밴드 화면으로 교체

**Files:**
- Modify: `components/kb/JarimaegimPlan.tsx`
- Modify: `components/kb/JarimaegimPanel.tsx`

- [ ] **Step 1: `PlanCost`와 `BLANK_ITEMS` 제거하고 `PlanBands` 추가**

`components/kb/JarimaegimPlan.tsx`의 `BLANK_ITEMS` 상수와 `PlanCost` 함수를 **통째로 지우고** 그 자리에 아래를 넣는다. import 줄도 함께 바꾼다.

```tsx
"use client";

import { useMemo, useState } from "react";
import { CircleHelp, Coins, ExternalLink, Info, Landmark, LoaderCircle, LockKeyhole, Sparkles } from "lucide-react";
import { PROGRAM_CATEGORY_LABELS, formatKrw } from "@/lib/constants";
import type { BandLine, CaseRecord, FundingBandResult, KbProduct, Program } from "@/lib/types";
import { matchKbProducts } from "@/lib/kb-match";
import type { BandForm, LocationState } from "@/lib/use-jarimaegim";

const BAND_LABELS: Record<string, string> = { EQUITY_ONLY: "자기자본선", RECOMMENDED: "권장 조달선", MAXIMUM: "최대 조달선", OUT_OF_RANGE: "조달 불가" };
const BAND_MARKS: Record<string, string> = { EQUITY_ONLY: "●", RECOMMENDED: "◐", MAXIMUM: "◑", OUT_OF_RANGE: "○" };

const CAPITAL_FIELDS: { key: keyof BandForm; label: string; step: number; note?: string }[] = [
  { key: "deposit_krw", label: "임차보증금", step: 1000000 },
  { key: "key_money_krw", label: "권리금", step: 1000000, note: "계약 전 직접 확인" },
  { key: "fitout_krw", label: "인테리어·설비", step: 1000000, note: "비우면 평수 기준 추정값을 씁니다" }
];
const MONTHLY_FIELDS: { key: keyof BandForm; label: string; step: number }[] = [
  { key: "monthly_rent_krw", label: "월세", step: 100000 },
  { key: "monthly_maintenance_krw", label: "관리비", step: 100000 },
  { key: "other_monthly_fixed_krw", label: "기타 월 고정비", step: 100000 }
];

export function BandTable({ lines }: { lines: BandLine[] }) {
  return <div className="kb-band-table">
    <div className="kb-band-head"><span>밴드</span><span>상한</span><span>월 상환</span><span>현금소진</span></div>
    {lines.map((line) => <div key={line.band} className="kb-band-row" data-band={line.band} data-pass={line.stress_pass ? "true" : "false"}>
      <strong><em aria-hidden="true">{BAND_MARKS[line.band]}</em>{BAND_LABELS[line.band]}{line.is_estimate && <small>추정치</small>}</strong>
      <span>{formatKrw(line.ceiling_krw)}</span>
      <span>{line.monthly_repayment_krw > 0 ? formatKrw(line.monthly_repayment_krw) : "0원"}</span>
      <span>{line.runway_months === null ? "조달 부족" : `${line.runway_months}개월`}</span>
    </div>)}
  </div>;
}

/** 비용 단계. 필요자금 내역을 조정하고 조달 밴드 3중선과 손익분기선을 본다. */
export function PlanBands({ caseData, form, bands, state, busy, onField, onRecompute }: {
  caseData: CaseRecord; form: BandForm; bands: FundingBandResult | null; state: LocationState;
  busy: boolean; onField: (key: keyof BandForm, value: number | null) => void; onRecompute: () => void;
}) {
  const numeric = (key: keyof BandForm) => {
    const value = form[key];
    return value === null ? "" : String(value || "");
  };
  return <div className="kb-step">
    <p className="kb-step-lead">자기자본과 임대 조건으로 조달 가능 범위를 계산합니다. 임대료는 공개 원천이 없어 입력값을 그대로 사용하며, AI는 금액을 만들거나 바꾸지 않습니다.</p>

    <div className="kb-band-form">
      <span className="kb-band-form-title">필요자금 항목</span>
      {CAPITAL_FIELDS.map((field) => <label key={field.key} className="kb-field">
        <span>{field.label}{field.note && <small>{field.note}</small>}</span>
        <input type="number" min="0" step={field.step} inputMode="numeric" value={numeric(field.key)}
          onChange={(event) => onField(field.key, event.target.value === "" ? null : Math.max(0, Number(event.target.value)))} placeholder="0" />
      </label>)}
      <span className="kb-band-form-title">월 고정지출</span>
      {MONTHLY_FIELDS.map((field) => <label key={field.key} className="kb-field">
        <span>{field.label}</span>
        <input type="number" min="0" step={field.step} inputMode="numeric" value={numeric(field.key)}
          onChange={(event) => onField(field.key, Math.max(0, Number(event.target.value)))} placeholder="0" />
      </label>)}
      <span className="kb-band-form-title">기존 부채</span>
      <label className="kb-field"><span>기존 대출 잔액</span>
        <input type="number" min="0" step={1000000} inputMode="numeric" value={numeric("existing_debt_krw")}
          onChange={(event) => onField("existing_debt_krw", Math.max(0, Number(event.target.value)))} placeholder="0" />
      </label>
    </div>
    <button className="kb-primary" onClick={onRecompute} disabled={busy}>{busy ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}입력값으로 다시 계산</button>

    {state === "loading" && <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />조달 밴드를 계산하고 있습니다.</div>}

    {bands?.status === "integration_pending" && <div className="kb-empty">
      <Coins aria-hidden="true" />
      <strong>조달 밴드 계산에 필요한 파라미터가 아직 등록되지 않았습니다</strong>
      <p>{bands.message}</p>
      <ul className="kb-missing-params">{bands.missing_params.map((key) => <li key={key}>{key}</li>)}</ul>
    </div>}

    {bands?.status === "computed" && bands.break_even && <>
      <dl className="kb-summary">
        <div><dt>자기자본</dt><dd>{formatKrw(caseData.inputs.equity_krw)}</dd></div>
        <div><dt>필요자금</dt><dd>{bands.required_capital_krw === null ? "—" : formatKrw(bands.required_capital_krw)}</dd></div>
        <div><dt>월 고정지출</dt><dd>{formatKrw(bands.break_even.monthly_fixed_cost_krw)}</dd></div>
        <div className="kb-summary-gap"><dt>손익분기 목표매출</dt><dd>월 {formatKrw(bands.break_even.target_monthly_revenue_krw)} · 일 {formatKrw(bands.break_even.target_daily_revenue_krw)}</dd></div>
      </dl>
      <BandTable lines={bands.bands} />
      {bands.required_capital_band === "OUT_OF_RANGE" && <p className="kb-inline-error" role="alert"><Info aria-hidden="true" />필요자금이 최대 조달선을 넘습니다. 임대 조건을 낮추거나 자기자본을 늘려야 합니다.</p>}
      <ul className="kb-limitations">{bands.break_even.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
      {bands.provenance && <ul className="kb-limitations">{bands.provenance.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
    </>}
  </div>;
}
```

- [ ] **Step 2: 패널에서 `PlanBands`로 교체**

`components/kb/JarimaegimPanel.tsx`의 import를 바꾸고 `cost` 단계 렌더 줄을 교체한다.

```tsx
import { PlanBands, PlanFunding } from "./JarimaegimPlan";
```

```tsx
      {flow.step === "cost" && flow.caseData && <PlanBands caseData={flow.caseData} form={flow.bandForm} bands={flow.bands} state={flow.bandState} busy={flow.busy === "bands"} onField={flow.setBandField} onRecompute={flow.recomputeBands} />}
```

- [ ] **Step 3: 스타일 추가**

`app/globals.css` 맨 끝에 추가한다.

```css
.kb-band-form{display:grid;gap:8px;margin:12px 0}
.kb-band-form-title{font-size:11px;font-weight:800;letter-spacing:.08em;color:var(--muted,#6b7280);margin-top:6px}
.kb-band-form .kb-field small{display:block;font-weight:400;font-size:10px;color:var(--muted,#6b7280)}
.kb-band-table{border:1px solid var(--line,#e5e7eb);border-radius:8px;overflow:hidden;margin:12px 0}
.kb-band-head,.kb-band-row{display:grid;grid-template-columns:1.5fr 1fr 1fr .9fr;gap:6px;padding:8px 10px;align-items:baseline}
.kb-band-head{background:#f7f8fa;font-size:10px;font-weight:800;letter-spacing:.06em;color:var(--muted,#6b7280);text-transform:uppercase}
.kb-band-row{border-top:1px solid var(--line,#e5e7eb);font-size:12px;font-variant-numeric:tabular-nums}
.kb-band-row strong{display:flex;align-items:baseline;gap:5px;font-size:12px}
.kb-band-row strong em{font-style:normal}
.kb-band-row strong small{font-size:9px;font-weight:700;padding:1px 4px;border-radius:3px;background:#fdece8;color:#a8552f}
.kb-band-row[data-band="RECOMMENDED"]{background:#fffdf5}
.kb-band-row[data-pass="false"] span:last-child{color:#b23a2f}
.kb-missing-params{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-wrap:wrap;gap:4px}
.kb-missing-params li{font-family:ui-monospace,monospace;font-size:10px;padding:2px 6px;border-radius:4px;background:#f1efeb;color:#4a4a4a}
.kb-band-banner{display:grid;gap:6px;border:1px solid var(--line,#e5e7eb);border-radius:8px;padding:10px;margin:10px 0}
.kb-band-banner-row{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;font-variant-numeric:tabular-nums}
.kb-band-banner-row strong{font-weight:700}
.kb-band-banner-note{font-size:10.5px;color:var(--muted,#6b7280);margin:0}
```

- [ ] **Step 4: 타입 검사·린트·빌드**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run typecheck && npm run lint && npm run build
```

기대: 전부 성공. `CostItem`·`CostPlan` import가 남아 오류가 나면 `JarimaegimPlan.tsx`에서 제거한다(`Workspace.tsx`는 그대로 둔다).

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add components/kb/JarimaegimPlan.tsx components/kb/JarimaegimPanel.tsx app/globals.css
git commit -m "feat: replace the cost step with the funding band screen"
```

---

## Task 4: 입지 단계에 밴드 컨텍스트와 대칭 배너

**DS-09(상권 임대 수준)가 없으므로 밴드별로 열리는 상권 수를 표시하지 않는다.** 배너는 밴드를 바꿨을 때의 상환·소진 대비만 보여주는 **비교 표시**이며, 후보를 다시 뽑는 동작이 아니다. 후보를 밴드 내 상권에서 생성하는 것은 DS-04·DS-09가 붙은 뒤다. 그 사실을 화면에 적는다.

**Files:**
- Modify: `components/kb/JarimaegimPanel.tsx`

- [ ] **Step 1: 배너 컴포넌트 추가**

`components/kb/JarimaegimPanel.tsx`의 `RecommendStep` 함수 **위**에 추가한다.

```tsx
/** 확장·축소를 같은 비중으로 보여준다. 한쪽만 노출하면 대출 권유가 된다. */
function BandBanner({ bands }: { bands: FundingBandResult }) {
  const equity = bands.bands.find((line) => line.band === "EQUITY_ONLY");
  const recommended = bands.bands.find((line) => line.band === "RECOMMENDED");
  const maximum = bands.bands.find((line) => line.band === "MAXIMUM");
  if (!equity || !recommended || !maximum) return null;
  const describe = (line: typeof equity) => `상환 ${line.monthly_repayment_krw > 0 ? formatKrw(line.monthly_repayment_krw) : "0원"} · 소진 ${line.runway_months === null ? "조달 부족" : `${line.runway_months}개월`}`;
  return <div className="kb-band-banner">
    <div className="kb-band-banner-row"><span><strong>권장 조달선 {formatKrw(recommended.ceiling_krw)}</strong> 기준</span><span>{describe(recommended)}</span></div>
    <div className="kb-band-banner-row"><span>▼ 자기자본만 {formatKrw(equity.ceiling_krw)}으로 줄이면</span><span>{describe(equity)}</span></div>
    <div className="kb-band-banner-row"><span>▲ 최대 {formatKrw(maximum.ceiling_krw)}까지 늘리면</span><span>{describe(maximum)}{maximum.stress_pass ? "" : " · 스트레스 실패"}</span></div>
    <p className="kb-band-banner-note">밴드에 따라 열리는 상권 수는 상권 임대 수준 데이터 연동 후 제공됩니다. 지금 후보 목록은 밴드로 걸러지지 않았습니다.</p>
  </div>;
}
```

- [ ] **Step 2: `RecommendStep`에서 배너 렌더**

`RecommendStep`의 첫 구조 분해와 `kb-bubble` 다음 줄을 바꾼다.

```tsx
function RecommendStep({ flow }: { flow: Jarimaegim }) {
  const { candidates, locationState, focused, caseData, trace, bands } = flow;
  const conditions = `${flow.form.district} ${flow.form.industry}`.trim();
  return <div className="kb-step">
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>{trace.state === "running"
      ? `${conditions} 조건으로 공식 장소 데이터를 확인하는 중입니다. 아래에서 지금 어떤 단계를 거치고 있는지 확인할 수 있습니다.`
      : trace.state === "failed" ? `${conditions} 조건의 확인이 중간에 멈췄습니다. 어느 단계에서 멈췄는지 아래에 그대로 남겨 두었습니다.`
      : caseData ? `${caseData.inputs.district} ${caseData.inputs.industry} 조건으로 공식 장소 데이터를 확인했습니다. 지도의 마커와 아래 목록이 같은 후보입니다.` : "조건을 확정하면 후보를 찾습니다."}</p></div>
    {bands?.status === "computed" && <BandBanner bands={bands} />}
    {bands?.status === "integration_pending" && <p className="kb-note"><Info aria-hidden="true" />조달 밴드는 제도 파라미터 등록 후 계산됩니다. 비용 단계에서 누락 항목을 확인할 수 있습니다.</p>}
```

나머지 본문은 그대로 둔다.

- [ ] **Step 3: 타입 import 추가**

`components/kb/JarimaegimPanel.tsx`의 타입 import 줄을 바꾼다.

```tsx
import type { AnalysisResult, CaseInput, FundingBandResult } from "@/lib/types";
```

- [ ] **Step 4: 타입 검사·린트**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run typecheck && npm run lint
```

기대: 오류 0건.

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add components/kb/JarimaegimPanel.tsx
git commit -m "feat: show the band context and a symmetric banner on the location step"
```

---

## Task 5: 자금 단계에 밴드 요약, 매칭 기준을 밴드 차입액으로

기존 `PlanFunding`은 `gapMin`(CostPlan의 부족액)을 받아 KB 상품 매칭에 넘긴다. 화면 A에서 CostPlan을 더 쓰지 않으므로 **권장 조달선의 차입액**으로 바꾼다. `matchKbProducts`의 시그니처는 그대로다.

**Files:**
- Modify: `components/kb/JarimaegimPlan.tsx`
- Modify: `components/kb/JarimaegimPanel.tsx`

- [ ] **Step 1: `PlanFunding` 시그니처와 본문 교체**

`components/kb/JarimaegimPlan.tsx`의 `PlanFunding` 함수를 통째로 바꾼다.

```tsx
export function PlanFunding({ programs, state, applicationEnabled, bands, kbProducts, kbState, inputs }: {
  programs: Program[]; state: LocationState; applicationEnabled: boolean; bands: FundingBandResult | null;
  kbProducts: KbProduct[]; kbState: LocationState; inputs: CaseRecord["inputs"];
}) {
  const recommended = bands?.bands.find((line) => line.band === "RECOMMENDED") ?? null;
  const loanKrw = recommended ? recommended.loan_krw : null;
  return <div className="kb-step">
    <p className="kb-step-lead">정부지원 → 정책자금 → 지역보증 → 민간금융 순으로 확인합니다. 승인 여부는 단정하지 않습니다.</p>
    {recommended
      ? <div className="kb-callout"><Coins aria-hidden="true" /><span>권장 조달선 <strong>{formatKrw(recommended.ceiling_krw)}</strong> 기준 차입 필요액은 <strong>{formatKrw(recommended.loan_krw)}</strong>이며 월 상환은 {formatKrw(recommended.monthly_repayment_krw)}입니다.</span></div>
      : <div className="kb-callout"><Coins aria-hidden="true" /><span>비용 단계에서 조달 밴드를 계산하면 필요 차입액을 기준으로 상품을 대조합니다.</span></div>}
    {bands?.status === "computed" && <BandTable lines={bands.bands} />}
    <p className="kb-note"><Info aria-hidden="true" />지원사업이 조달선을 얼마나 올리는지는 지원사업 endpoint 연동 후 반영됩니다. 현재 밴드에는 지원금이 포함되지 않았습니다.</p>
    {!applicationEnabled && <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" /><span>실제 신청·상담 연결은 아직 제공하지 않습니다. 공식 원문으로 이동해 직접 확인해 주세요.</span></div>}
    <KbProductSection products={kbProducts} state={kbState} inputs={inputs} gapKrw={loanKrw} />
    {state === "loading" && <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />공식 공고를 확인하고 있습니다.</div>}
    {state !== "loading" && programs.length === 0 && <div className="kb-empty">
      <Coins aria-hidden="true" />
      <strong>표시할 수 있는 공식 공고가 없습니다</strong>
      <p>검증된 공공 API endpoint와 키가 설정되기 전에는 공고를 만들어 표시하지 않습니다. 원문 URL이 확인되지 않은 항목은 공개하지 않습니다.</p>
    </div>}
    {programs.length > 0 && <ul className="kb-program-list">{programs.map((program) => <li key={program.id}>
      <span className="kb-program-tag">{PROGRAM_CATEGORY_LABELS[program.category]}</span>
      <strong>{program.title}</strong>
      <small>{program.organization} · {program.application_period || "기간 원문 확인"}</small>
      {program.unknown_conditions.length > 0 && <div className="kb-unknown">{program.unknown_conditions.map((condition) => <span key={condition}><CircleHelp aria-hidden="true" />{condition}</span>)}</div>}
      <a href={program.official_url} target="_blank" rel="noopener noreferrer">공식 원문 열기 <ExternalLink aria-hidden="true" /></a>
    </li>)}</ul>}
  </div>;
}
```

- [ ] **Step 2: 패널의 `funding` 단계 렌더 교체**

`components/kb/JarimaegimPanel.tsx`의 `funding` 줄에서 `gapMin`을 `bands`로 바꾼다.

```tsx
      {flow.step === "funding" && flow.caseData && <PlanFunding programs={flow.programs} state={flow.programState} applicationEnabled={Boolean(flow.status?.feature_flags.financial_application)} bands={flow.bands} kbProducts={flow.kbProducts.filter((product) => product.category === "BUSINESS_LOAN")} kbState={flow.kbState} inputs={flow.caseData.inputs} />}
```

- [ ] **Step 3: 타입 검사·린트·빌드**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run typecheck && npm run lint && npm run build
```

기대: 전부 성공.

- [ ] **Step 4: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add components/kb/JarimaegimPlan.tsx components/kb/JarimaegimPanel.tsx
git commit -m "feat: match KB products against the recommended band's borrowing need"
```

---

## Task 6: 화면 A 안전 상태 회귀 검증 스크립트

`scripts/flow-check.mjs`는 `/start` → 화면 B 경로만 검증한다. **화면 A는 e2e 검증이 전혀 없다.** 이 계획이 화면 A를 바꾸므로 여기서 만든다.

**Files:**
- Create: `scripts/shell-check.mjs`
- Modify: `package.json`

- [ ] **Step 1: 스크립트 작성**

`scripts/shell-check.mjs`:

```javascript
import { chromium } from "playwright-core";

const base = process.env.BASE_URL || "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(`page:${error.message}`));
page.on("console", message => {
  if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) errors.push(`console:${message.text()}`);
});
page.on("response", response => { if (response.status() >= 400) errors.push(`http:${response.status()}:${response.url()}`); });

await page.goto(base, { waitUntil: "networkidle" });
await page.waitForSelector(".kb-ai-panel");
const stepper = { labels: await page.locator(".kb-stepper li").allTextContents() };

// 상황 — 예시 문장으로 조건을 채우고 확인 단계로
await page.locator(".kb-examples button").first().click();
await page.getByRole("button", { name: "조건으로 정리하기" }).click();
await page.waitForSelector(".kb-form");
const confirmLabels = await page.locator(".kb-form .kb-field span").allTextContents();
const lease = { fieldsPresent: ["희망 평수", "희망 보증금", "희망 월세"].every(label => confirmLabels.some(text => text.includes(label))) };

// 임대 조건 입력
const fields = page.locator('.kb-form .kb-field input[type="number"]');
await fields.nth(2).fill("15");         // 희망 평수
await fields.nth(3).fill("100000000");  // 희망 보증금
await fields.nth(4).fill("2500000");    // 희망 월세

const bandsResponsePromise = page.waitForResponse(r => r.url().includes("/api/v1/funding-bands") && r.request().method() === "POST");
await page.getByRole("button", { name: "이 조건으로 입지 찾기" }).click();
const bandsResponse = await bandsResponsePromise;
const bandsBody = await bandsResponse.json();
const bands = { autoComputed: bandsResponse.ok(), pendingSafeState: bandsBody.status === "integration_pending" && bandsBody.bands.length === 0 && bandsBody.missing_params.length > 0 };

await page.waitForSelector(".kb-candidates, .kb-empty", { timeout: 30000 });
const location = { rendered: await page.locator(".kb-candidates, .kb-empty").first().isVisible() };

// 비용 — StepNav 의 다음 버튼을 밴드 화면이 나올 때까지 누른다 (입지 → 근거 → 비용)
for (let hop = 0; hop < 4; hop += 1) {
  if (await page.locator(".kb-band-form").isVisible().catch(() => false)) break;
  const next = page.locator(".kb-stepnav .kb-primary-sm");
  if (await next.count() === 0) throw new Error("StepNav 다음 버튼을 찾지 못했습니다.");
  await next.click();
  await page.waitForTimeout(500);
}
await page.waitForSelector(".kb-band-form", { timeout: 15000 });
const cost = {
  bandScreen: await page.locator(".kb-band-form").isVisible(),
  pendingShown: await page.locator(".kb-missing-params li").count() > 0
};

// 자금 — 공고 빈 상태
const nextButton = page.locator(".kb-stepnav .kb-primary-sm");
if (await nextButton.count() > 0) { await nextButton.click(); await page.waitForTimeout(600); }
const funding = { emptySafeState: await page.getByText("표시할 수 있는 공식 공고가 없습니다").isVisible().catch(() => false) };

const statusBody = await (await page.request.get(`${base}/api/v1/status`)).json();
const axes = { disabledCarryReason: Object.values(statusBody.axes).every(axis => axis.enabled || Boolean(axis.disabled_reason)) };

const result = { stepper, lease, bands, location, cost, funding, axes, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
const expected = ["상황", "입지", "근거", "비용", "자금"];
const stepperOk = expected.every((label, index) => (stepper.labels[index] || "").includes(label));
if (errors.length || !stepperOk || !lease.fieldsPresent || !bands.autoComputed || !bands.pendingSafeState
  || !location.rendered || !cost.bandScreen || !cost.pendingShown || !funding.emptySafeState || !axes.disabledCarryReason) process.exitCode = 1;
```

- [ ] **Step 2: npm 스크립트 추가**

`package.json`의 `scripts`에서 `"check:kakao-build-assets"` 아래에 추가한다.

```json
"check:shell": "node scripts/shell-check.mjs"
```

- [ ] **Step 3: 실행**

dev 서버가 떠 있어야 한다. 다른 터미널에서 `npm run dev`.

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run check:shell; echo "EXIT=$?"
```

기대: `EXIT=0`. 실패하면 출력된 JSON에서 어느 항목이 `false`인지 보고 해당 단계를 고친다. **단정을 약화시켜 통과시키지 말 것** — `cost.pendingShown`은 제도 파라미터가 비어 있을 때 누락 키가 화면에 보여야 한다는 부록 A 불변조건 1의 회귀 고정이다.

- [ ] **Step 4: 기존 검증도 함께 통과 확인**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo" && npm run api:test 2>&1 | grep -E "passed|failed" && npm run typecheck && npm run lint && npm run build >/dev/null && echo "build OK" && node scripts/flow-check.mjs >/dev/null; echo "flow-check EXIT=$?"
```

기대: `58 passed`, typecheck·lint 오류 0건, build OK, `flow-check EXIT=0`. **화면 B를 건드리지 않았으므로 flow-check는 계속 통과해야 한다.**

- [ ] **Step 5: 커밋**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add scripts/shell-check.mjs package.json
git commit -m "test: pin the landing shell safe states end to end"
```

---

## Task 7: 스펙 정정

**Files:**
- Modify: `docs/superpowers/specs/2026-07-27-multi-agent-architecture-design.md`

- [ ] **Step 1: §5.1 표를 화면 A 기준으로 교체**

§5.1의 8행 표(`/cases/new` … `/documents`)를 이 계획 상단의 "스펙 §5.1 정정" 표로 바꾼다. 표 위 설명 문단에 다음 문장을 추가한다.

```markdown
> **적용 대상은 화면 A(`KbShell`의 `자리매김 AI` 패널 5단계)다.** 이 문서 초판은 화면 B(`Workspace`, `/cases/{id}/…`의 6스테이지)를 기준으로 적었으나, 실제 구현 대상은 랜딩에 붙어 있는 화면 A다. 두 화면은 서로 링크가 없는 별개 UI이며, 화면 B의 처리 방침은 아직 정해지지 않았다.
```

- [ ] **Step 2: §5.2에 단서 추가**

§5.2의 폐기 표 아래에 추가한다.

```markdown
> **부분 실행됨.** 화면 A는 `PlanCost`를 `PlanBands`로 교체해 더 이상 같은 값을 두 번 묻지 않는다. 그러나 `POST /api/v1/cost-plans`·`CostService`·`CostItem`·`CostPlan`은 **화면 B(`Workspace.tsx`의 `CostView`)가 계속 사용하므로 남겨 두었다.** 전면 폐기는 화면 B의 처리 방침이 정해진 뒤 별도 계획으로 한다.
```

- [ ] **Step 3: 커밋과 푸시**

```bash
cd "/Users/jiwon/Desktop/KB AI Challenge/ter-doctor-demo"
git add docs/superpowers/specs
git commit -m "docs: correct the stage mapping to the landing shell"
git push origin main
```

---

## 완료 정의

| 요구 | 확인 방법 |
|---|---|
| 5단계 라벨 `상황·입지·근거·비용·자금` 유지 | `shell-check`의 `stepper` |
| 임대 조건을 상황 단계에서 받는다 | `shell-check`의 `lease.fieldsPresent` |
| 케이스 생성 직후 밴드가 자동 산출된다 | `shell-check`의 `bands.autoComputed` |
| 파라미터 미등록 시 추정하지 않고 누락 키를 보여준다 | `shell-check`의 `bands.pendingSafeState` · `cost.pendingShown` |
| 비용 단계가 밴드 화면이다 | `shell-check`의 `cost.bandScreen` |
| 확장·축소가 대칭으로 노출된다 | `BandBanner`가 ▼/▲ 두 줄을 항상 함께 렌더 |
| 밴드별 상권 수를 지어내지 않는다 | `BandBanner`의 안내 문구 + `trade_area_count`를 화면에 쓰지 않음 |
| 화면 B가 깨지지 않는다 | `flow-check EXIT=0` |

## 이 계획에서 하지 않은 것

- **후보를 밴드 내 상권에서 생성하기** — DS-04(상권 경계)·DS-09(임대 수준)가 필요하다. 그전까지 후보는 Kakao 검색 결과이고 밴드로 걸러지지 않으며, 그 사실을 배너에 적는다.
- **4축 판정** — `location.*` 축이 전부 비활성이므로 `근거` 단계는 손대지 않는다.
- **지원금의 조달선 상향** — DS-07/08 연동 후.
- **밴드 결과 영속화** — 가드 2와 함께.
- **화면 B 수정과 `CostService` 전면 폐기** — 화면 B 처리 방침 결정 후.
