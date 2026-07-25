"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, ArrowLeft, ArrowRight, Check, Info, LoaderCircle, MapPinned, ShieldCheck, Sparkles } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { DEFAULT_CASE, PRIORITY_LABELS, SEOUL_DISTRICTS, STAGE_LABELS, TYPE_LABELS, formatKrw } from "@/lib/constants";
import type { BusinessStage, CaseInput, StartupType } from "@/lib/types";

function parseNaturalLanguage(text: string, current: CaseInput): Partial<CaseInput> {
  const patch: Partial<CaseInput> = {};
  const district = SEOUL_DISTRICTS.find((item) => text.includes(item));
  if (district) patch.district = district;
  const industryMatch = text.match(/(?:에서|구에서|동에서)\s*([^\s,]+)(?:을|를)?\s*(?:준비|창업|열|하고)/);
  if (industryMatch?.[1]) patch.industry = industryMatch[1].replace(/[을를]$/, "");
  if (/카페|커피/.test(text)) patch.industry = "카페";
  if (/음식점|식당/.test(text)) patch.industry = "일반음식점";
  const amount = text.match(/(\d+(?:\.\d+)?)\s*(억|천만|백만|만)/);
  if (amount) {
    const value = Number(amount[1]);
    const unit = amount[2] === "억" ? 100_000_000 : amount[2] === "천만" ? 10_000_000 : amount[2] === "백만" ? 1_000_000 : 10_000;
    patch.budget_krw = Math.round(value * unit);
  }
  if (/이전/.test(text)) patch.business_stage = "RELOCATING";
  if (/2호점|두 번째/.test(text)) patch.business_stage = "SECOND_STORE";
  return { ...current, ...patch };
}

export function Onboarding() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const expand = searchParams.get("mode") === "expand";
  const [step, setStep] = useState<"input" | "confirm">("input");
  const [natural, setNatural] = useState("");
  const [parsedKeys, setParsedKeys] = useState<Set<keyof CaseInput>>(new Set());
  const [form, setForm] = useState<CaseInput>({ ...DEFAULT_CASE, business_stage: expand ? "RELOCATING" : "PRE_OPEN" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  const ready = useMemo(() => Boolean(form.industry.trim() && form.district && form.budget_krw > 0 && form.equity_krw >= 0), [form]);
  const setField = <K extends keyof CaseInput>(key: K, value: CaseInput[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setParsedKeys((prev) => { const next = new Set(prev); next.delete(key); return next; });
  };

  function interpret() {
    if (!natural.trim()) return;
    const parsed = parseNaturalLanguage(natural, form);
    const changed = new Set<keyof CaseInput>();
    (Object.keys(parsed) as (keyof CaseInput)[]).forEach((key) => { if (parsed[key] !== form[key]) changed.add(key); });
    setForm((prev) => ({ ...prev, ...parsed }));
    setParsedKeys(changed);
    setStep("confirm");
  }

  function validate() {
    const next: Record<string, string> = {};
    if (!form.industry.trim()) next.industry = "업종을 입력해 주세요.";
    if (!SEOUL_DISTRICTS.includes(form.district as (typeof SEOUL_DISTRICTS)[number])) next.district = "서울 25개 자치구 중에서 선택해 주세요.";
    if (!Number.isFinite(form.budget_krw) || form.budget_krw <= 0) next.budget_krw = "총예산을 0원보다 크게 입력해 주세요.";
    if (!Number.isFinite(form.equity_krw) || form.equity_krw < 0) next.equity_krw = "자기자본은 0원 이상이어야 합니다.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit() {
    if (!validate()) return;
    setSubmitting(true);
    setSubmitError("");
    let navigationStarted = false;
    try {
      await api.createAnonymousSession().catch((error) => { if (!(error instanceof ApiError && error.status === 409)) throw error; });
      const title = `${form.district} ${form.industry} ${STAGE_LABELS[form.business_stage]}`;
      const created = await api.createCase(form, title);
      sessionStorage.setItem(`ter-doctor:case:${created.id}`, JSON.stringify(created));
      navigationStarted = true;
      router.push(`/cases/${created.id}/explore`);
    } catch (error) {
      setSubmitError(error instanceof ApiError ? error.message : "서비스 연결을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    } finally {
      if (!navigationStarted) setSubmitting(false);
    }
  }

  return (
    <main id="main-content" className="onboarding-shell">
      <header className="onboarding-header">
        <button onClick={() => router.push("/")} className="back-button"><ArrowLeft/> 처음으로</button>
        <Link className="wordmark" href="/"><span className="brand-symbol"></span><span className="wordmark-partner">KB부동산 ×</span><strong>자리매김</strong></Link>
        <span>로그인 없이 시작</span>
      </header>
      <div className="onboarding-progress" aria-label="온보딩 진행">
        <span className="done"><i><Check/></i>조건 입력</span><b/>
        <span className={step === "confirm" ? "active" : ""}><i>2</i>조건 확인</span><b/>
        <span><i>3</i>후보 보기</span>
      </div>

      <div className="onboarding-workspace">
        <aside className="onboarding-diagnosis" aria-label="현재 창업 진단서">
          <div className="diagnosis-kicker"><ShieldCheck/> 창업 진단서</div>
          <h2>입력 조건</h2>
          <p>작성한 조건이 이후 모든 판단의 기준이 됩니다.</p>
          <dl>
            <div><dt>업종</dt><dd>{form.industry || "미입력"}</dd></div>
            <div><dt>지역</dt><dd>{form.district}</dd></div>
            <div><dt>총예산</dt><dd>{form.budget_krw > 0 ? formatKrw(form.budget_krw) : "미입력"}</dd></div>
            <div><dt>자기자본</dt><dd>{formatKrw(form.equity_krw)}</dd></div>
            <div><dt>사업단계</dt><dd>{STAGE_LABELS[form.business_stage]}</dd></div>
          </dl>
          <ol className="evidence-spine" aria-label="의사결정 흐름">
            <li className="active"><i>1</i><span><small>조건</small><strong>내 상황 확정</strong></span></li>
            <li><i>2</i><span><small>근거</small><strong>공식 데이터 연결</strong></span></li>
            <li><i>3</i><span><small>판단</small><strong>가능 범위 구분</strong></span></li>
            <li><i>4</i><span><small>다음 행동</small><strong>후보 비교·계획</strong></span></li>
          </ol>
        </aside>

        <section className="onboarding-content">
          <div className="onboarding-title">
            <span className="eyebrow">{expand ? "이전·추가 매장" : "처음 창업"}</span>
            <h1>{step === "input" ? "어떤 시작을 준비하고 있나요?" : "후보를 찾기 전에 조건을 확인해 주세요."}</h1>
            <p>{step === "input" ? "편한 문장으로 적거나, 아래 항목을 직접 채워도 됩니다." : "AI가 해석한 값도 사용자가 확인해야 적용됩니다."}</p>
          </div>
          <section className="natural-input" aria-labelledby="natural-title">
            <div><span className="ai-badge"><Sparkles/> AI 입력 도우미</span><h2 id="natural-title">한 문장으로 조건 적기</h2></div>
            <textarea value={natural} onChange={(event) => setNatural(event.target.value)} placeholder="예: 마포구에서 1억 원 예산으로 카페를 처음 준비하고 있어요."/>
            <button onClick={interpret} disabled={!natural.trim()}>조건으로 정리하기 <ArrowRight/></button>
            <p><Info/> 주민번호, 계좌 비밀번호, 신분증 정보는 입력하지 마세요.</p>
          </section>
          {Object.keys(errors).length > 0 && <div className="error-summary" role="alert"><AlertCircle/><div><strong>확인이 필요한 항목이 있습니다.</strong><p>{Object.values(errors).join(" ")}</p></div></div>}
          <section className="condition-form" aria-label="창업 조건 6개">
            <label className={errors.industry ? "has-error" : ""}><span>업종 <Required/>{parsedKeys.has("industry") && <Parsed/>}</span><input aria-label="업종 필수" value={form.industry} onChange={(e) => setField("industry", e.target.value)} placeholder="예: 카페, 미용실, 일반음식점"/><small>{errors.industry || "표준 업종과 매핑되지 않으면 분석 범위가 제한될 수 있습니다."}</small></label>
            <label className={errors.district ? "has-error" : ""}><span>지역 <Required/>{parsedKeys.has("district") && <Parsed/>}</span><select value={form.district} onChange={(e) => setField("district", e.target.value)}>{SEOUL_DISTRICTS.map((district) => <option key={district}>{district}</option>)}</select><small>{errors.district || "현재 서울 25개 자치구를 지원합니다."}</small></label>
            <MoneyField label="총예산" value={form.budget_krw} error={errors.budget_krw} parsed={parsedKeys.has("budget_krw")} onChange={(value) => setField("budget_krw", value)}/>
            <MoneyField label="자기자본" value={form.equity_krw} error={errors.equity_krw} parsed={parsedKeys.has("equity_krw")} onChange={(value) => setField("equity_krw", value)}/>
            <fieldset><legend>사업단계 <Required/></legend><div className="segmented">{(Object.keys(STAGE_LABELS) as BusinessStage[]).map((value) => <label key={value}><input type="radio" name="stage" checked={form.business_stage === value} onChange={() => setField("business_stage", value)}/><span>{STAGE_LABELS[value]}</span></label>)}</div></fieldset>
            <fieldset><legend>창업형태 <Required/></legend><div className="segmented">{(Object.keys(TYPE_LABELS) as StartupType[]).map((value) => <label key={value}><input type="radio" name="type" checked={form.startup_type === value} onChange={() => setField("startup_type", value)}/><span>{TYPE_LABELS[value]}</span></label>)}</div></fieldset>
            <fieldset className="full-field"><legend>이번 탐색에서 먼저 볼 기준</legend><div className="priority-options">{(Object.keys(PRIORITY_LABELS) as CaseInput["priority"][]).map((value) => <label key={value}><input type="radio" name="priority" checked={form.priority === value} onChange={() => setField("priority", value)}/><span>{PRIORITY_LABELS[value]}</span></label>)}</div></fieldset>
          </section>
          {submitError && <div className="inline-alert error" role="alert"><AlertCircle/><span>{submitError}</span></div>}
          <footer className="onboarding-actions">
            <div><strong>{ready ? "후보를 찾을 준비가 됐습니다." : "필수 조건을 채워 주세요."}</strong><span>{ready ? `${form.district} · ${form.industry} · ${formatKrw(form.budget_krw)}` : "입력한 값은 분석 전 한 번 더 확인됩니다."}</span></div>
            {step === "input" ? <button className="secondary-button" onClick={() => setStep("confirm")}>조건 검토하기</button> : <button className="primary-button" onClick={submit} disabled={submitting}>{submitting ? <><LoaderCircle className="spin"/> 후보를 찾는 중</> : <>이 조건으로 후보 찾기 <ArrowRight/></>}</button>}
          </footer>
        </section>

        <aside className="onboarding-guide" aria-label="AI 입력 안내">
          <header><span><Sparkles/></span><div><strong>자리매김 AI</strong><small>조건 정리 도우미</small></div></header>
          <div className="guide-message"><p>아직 정하지 못한 값은 비워 두지 않고 직접 확인할 수 있도록 표시해요.</p></div>
          <div className="guide-message user"><p>{natural || "마포구에서 카페를 준비하고 있어요."}</p></div>
          <section><MapPinned/><div><strong>서울 25개 자치구</strong><p>현재 지원하는 지역 안에서 공식 위치 후보를 찾습니다.</p></div></section>
          <section><ShieldCheck/><div><strong>적용 전 확인</strong><p>AI가 읽은 값은 노란 표식으로 구분하고 직접 승인받습니다.</p></div></section>
          <footer>AI는 비용과 점수를 임의로 만들지 않습니다.</footer>
        </aside>
      </div>
    </main>
  );
}

function Required() { return <em className="required">필수</em>; }
function Parsed() { return <em className="parsed">AI가 해석함</em>; }
function MoneyField({ label, value, error, parsed, onChange }: { label: string; value: number; error?: string; parsed: boolean; onChange: (value: number) => void }) {
  return <label className={error ? "has-error" : ""}><span>{label} <Required/>{parsed && <Parsed/>}</span><div className="money-field"><input type="number" min="0" step="10000" value={value || ""} onChange={(event) => onChange(Number(event.target.value))} placeholder="0"/><b>원</b></div><small>{error || (value > 0 ? formatKrw(value) : "만원 단위로 입력할 수 있습니다.")}</small></label>;
}
