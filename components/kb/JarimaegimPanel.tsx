"use client";

import { useState } from "react";
import { AlertCircle, ArrowRight, Check, ChevronRight, CircleHelp, Info, LoaderCircle, RefreshCw, RotateCcw, Search, ShieldCheck, Sparkles, X } from "lucide-react";
import { EVIDENCE_BADGES, EVIDENCE_LABELS, PRIORITY_LABELS, SEOUL_DISTRICTS, SIGNAL_LABELS, STAGE_LABELS, TYPE_LABELS, formatKrw } from "@/lib/constants";
import { parseCaseText } from "@/lib/parse-case";
import type { AnalysisResult, CaseInput, FundingBandResult } from "@/lib/types";
import type { FlowStep, Jarimaegim } from "@/lib/use-jarimaegim";
import { ProvenanceBar } from "../ProvenanceBar";
import { PlanBands, PlanFunding } from "./JarimaegimPlan";

const STEPS: { id: FlowStep; label: string }[] = [
  { id: "ask", label: "조건" }, { id: "bands", label: "자금" }, { id: "recommend", label: "입지" },
  { id: "evidence", label: "근거" }, { id: "prescribe", label: "처방" }
];
const EXAMPLES = ["마포구에서 카페 창업하려는데 예산 1억, 자기자본 4천만이에요", "성동구에 2호점 낼 자리 찾고 있어요. 안정성이 제일 중요해요", "관악구 분식점, 총예산 8천만원으로 알아보는 중이에요"];

export function JarimaegimPanel({ flow, onClose }: { flow: Jarimaegim; onClose: () => void }) {
  const stepIndex = Math.max(0, STEPS.findIndex((step) => step.id === (flow.step === "confirm" ? "ask" : flow.step)));
  return <div className="kb-ai-panel">
    <header className="kb-ai-head">
      <span className="kb-ai-badge" aria-hidden="true">AI</span>
      <div><strong>자리매김 AI</strong><small>서울 창업 입지 · 자금조달 도우미</small></div>
      <button className="kb-icon-button" onClick={onClose} aria-label="자리매김 AI 닫기"><X aria-hidden="true" /></button>
    </header>
    <ol className="kb-stepper">{STEPS.map((step, index) => <li key={step.id} data-state={index < stepIndex ? "done" : index === stepIndex ? "current" : "todo"}>
      <span aria-hidden="true">{index < stepIndex ? <Check /> : index + 1}</span>{step.label}
    </li>)}</ol>
    <div className="kb-ai-scroll">
      {flow.error && <div className="kb-alert" role="alert"><AlertCircle aria-hidden="true" /><span>{flow.error}</span><button onClick={() => flow.setError("")} aria-label="알림 닫기"><X aria-hidden="true" /></button></div>}
      {flow.step === "ask" && <AskStep flow={flow} />}
      {flow.step === "confirm" && <ConfirmStep flow={flow} />}
      {flow.step === "recommend" && <RecommendStep flow={flow} />}
      {flow.step === "evidence" && <EvidenceStep flow={flow} />}
      {flow.step === "bands" && flow.caseData && <PlanBands caseData={flow.caseData} form={flow.bandForm} bands={flow.bands} state={flow.bandState} busy={flow.busy === "bands"} onField={flow.setBandField} onRecompute={flow.recomputeBands} />}
      {flow.step === "prescribe" && flow.caseData && <PlanFunding programs={flow.programs} state={flow.programState} applicationEnabled={Boolean(flow.status?.feature_flags.financial_application)} bands={flow.bands} kbProducts={flow.kbProducts.filter((product) => product.category === "BUSINESS_LOAN")} kbState={flow.kbState} inputs={flow.caseData.inputs} />}
      {flow.caseData && flow.step !== "ask" && flow.step !== "confirm" && <StepNav flow={flow} />}
    </div>
  </div>;
}

function AskStep({ flow }: { flow: Jarimaegim }) {
  const [text, setText] = useState("");
  const submit = () => { const value = text.trim(); if (!value) return; flow.interpret(value, parseCaseText(value)); };
  return <div className="kb-step">
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>{flow.messages[0].text}</p></div>
    <label className="kb-field kb-field-block"><span>상황 설명</span>
      <textarea rows={3} value={text} onChange={(event) => setText(event.target.value)} placeholder="예: 마포구에서 카페를 준비 중이고 예산은 1억이에요"
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} />
    </label>
    <button className="kb-primary" onClick={submit} disabled={!text.trim()}>조건으로 정리하기 <ArrowRight aria-hidden="true" /></button>
    <div className="kb-examples"><span>이렇게 물어보세요</span>{EXAMPLES.map((example) => <button key={example} onClick={() => setText(example)}>{example}</button>)}</div>
    <button className="kb-ghost" onClick={() => flow.interpret("직접 조건을 입력할게요", {})}>직접 입력으로 시작 <ChevronRight aria-hidden="true" /></button>
    <p className="kb-note"><ShieldCheck aria-hidden="true" />별도 계정 없이 익명 세션으로 진행하며, 입력한 조건은 최대 24시간 보관됩니다.</p>
  </div>;
}

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
    <p className="kb-note"><Info aria-hidden="true" />임대 조건은 상업용 임대료 공개 원천이 없어 직접 입력받습니다. 비우면 조달 밴드를 계산하지 않고 대기 상태로 둡니다.</p>
  </div>;
}

function ChipRow({ label, value, options, onSelect, mark }: { label: string; value: string; options: Record<string, string>; onSelect: (value: string) => void; mark?: string }) {
  return <div className="kb-chiprow" data-mark={mark}><span>{label}</span><div>{Object.entries(options).map(([key, text]) => <button key={key} type="button" aria-pressed={value === key} onClick={() => onSelect(key)}>{text}</button>)}</div></div>;
}

/** 확장·축소를 같은 비중으로 보여준다. 한쪽만 노출하면 대출 권유가 된다. */
function BandBanner({ bands }: { bands: FundingBandResult }) {
  const equity = bands.bands.find((line) => line.band === "EQUITY_ONLY");
  const recommended = bands.bands.find((line) => line.band === "RECOMMENDED");
  const maximum = bands.bands.find((line) => line.band === "MAXIMUM");
  if (!equity || !recommended || !maximum) return null;
  const describe = (line: typeof equity) => `상환 ${line.monthly_repayment_krw > 0 ? formatKrw(line.monthly_repayment_krw) : "0원"} · 목표 일매출 ${formatKrw(line.target_daily_revenue_krw)} · 소진 ${line.runway_months === null ? "조달 부족" : `${line.runway_months}개월`}`;
  return <div className="kb-band-banner">
    <div className="kb-band-banner-row"><span><strong>권장 조달선 {formatKrw(recommended.ceiling_krw)}</strong> 기준</span><span>{describe(recommended)}</span></div>
    <div className="kb-band-banner-row"><span>▼ 자기자본만 {formatKrw(equity.ceiling_krw)}으로 줄이면</span><span>{describe(equity)}</span></div>
    <div className="kb-band-banner-row"><span>▲ 최대 {formatKrw(maximum.ceiling_krw)}까지 늘리면</span><span>{describe(maximum)}{maximum.stress_pass ? "" : " · 스트레스 실패"}</span></div>
    <p className="kb-band-banner-note">밴드에 따라 열리는 상권 수는 상권 임대 수준 데이터 연동 후 제공됩니다. 지금 후보 목록은 밴드로 걸러지지 않았습니다.</p>
  </div>;
}

function RecommendStep({ flow }: { flow: Jarimaegim }) {
  const { candidates, locationState, focused, caseData, trace, bands } = flow;
  const conditions = `${flow.form.district} ${flow.form.industry}`.trim();
  return <div className="kb-step">
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>{trace.state === "running"
      ? `${conditions} 조건으로 공식 장소 데이터를 확인하는 중입니다. 아래에서 지금 어떤 단계를 거치고 있는지 확인할 수 있습니다.`
      : trace.state === "failed" ? `${conditions} 조건의 확인이 중간에 멈췄습니다. 어느 단계에서 멈췄는지 아래에 그대로 남겨 두었습니다.`
      : caseData ? `${caseData.inputs.district} ${caseData.inputs.industry} 조건으로 공식 장소 데이터를 확인했습니다. 지도의 마커와 아래 목록이 같은 후보입니다.` : "조건을 확정하면 후보를 찾습니다."}</p></div>
    {bands?.status === "computed" && <BandBanner bands={bands} />}
    {bands?.status === "integration_pending" && <p className="kb-note"><Info aria-hidden="true" />조달 밴드는 아직 계산되지 않았습니다. 자금 단계에서 무엇이 비어 있는지 확인할 수 있습니다.</p>}
    {locationState === "loading" && <div className="kb-skeletons">{[0, 1, 2].map((row) => <div key={row} className="kb-skeleton" />)}</div>}
    {trace.state !== "running" && locationState !== "loading" && locationState !== "error" && candidates.length === 0 && <div className="kb-empty">
      <Search aria-hidden="true" />
      <strong>{locationState === "integration_pending" ? "공식 위치 API 연결을 기다리고 있습니다" : "현재 조건에서 표시할 후보가 없습니다"}</strong>
      <p>{locationState === "integration_pending" ? "Kakao Local REST 키가 설정되면 실제 장소를 불러옵니다. 연결 전에는 가상 후보를 만들지 않습니다." : "업종 이름이나 자치구를 바꿔 다시 확인해 주세요."}</p>
      <button className="kb-ghost" onClick={flow.retrySearch}><RefreshCw aria-hidden="true" /> 다시 확인</button>
    </div>}
    {candidates.length > 0 && <>
      <p className="kb-step-lead">공식 장소 검색 정확도순 {candidates.length}곳입니다. 순서는 적합도 점수가 아니며, 개별 점포 생존등급은 근거 A에서만 제공합니다.</p>
      <ul className="kb-candidates">{candidates.map((candidate, index) => <li key={candidate.id} data-focused={candidate.id === focused ? "true" : undefined}>
        <button className="kb-candidate-main" onClick={() => flow.setFocused(candidate.id)} aria-pressed={candidate.id === focused}>
          <span className="kb-rank">{index + 1}</span>
          <span className="kb-candidate-body">
            <strong>{candidate.name}</strong>
            <small>{candidate.road_address || candidate.address}</small>
            <span className="kb-grade" data-grade={candidate.evidence_grade}>{EVIDENCE_BADGES[candidate.evidence_grade]} · {EVIDENCE_LABELS[candidate.evidence_grade]}</span>
          </span>
        </button>
        <ProvenanceBar data={candidate.provenance} />
        <button className="kb-ghost kb-candidate-cta" onClick={() => flow.runAnalysis(candidate.id)}>근거 자세히 보기 <ArrowRight aria-hidden="true" /></button>
      </li>)}</ul>
    </>}
  </div>;
}

function EvidenceStep({ flow }: { flow: Jarimaegim }) {
  const candidate = flow.candidates.find((item) => item.id === flow.focused) || null;
  const result = flow.focused ? flow.analysis[flow.focused] : undefined;
  if (!candidate) return <div className="kb-empty"><Search aria-hidden="true" /><strong>후보를 먼저 선택해 주세요</strong><p>입지 단계에서 후보를 고르면 확인 가능한 근거 범위를 보여드립니다.</p><button className="kb-ghost" onClick={() => flow.setStep("recommend")}>입지로 돌아가기</button></div>;
  if (flow.busy === `analysis:${candidate.id}` || !result) return <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />{candidate.name}에서 확인 가능한 근거를 정리하고 있습니다.</div>;
  return <div className="kb-step">
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p><strong>{candidate.name}</strong>에서 지금 확인할 수 있는 범위입니다. 연결된 공식 데이터 수준을 넘는 결과는 만들지 않습니다.</p></div>
    <EvidenceContract result={result} />
    <section className="kb-signals">
      <h3>판단 근거</h3>
      {result.context_signals.length > 0
        ? <ul>{result.context_signals.map((signal) => <li key={signal.name}><strong>{SIGNAL_LABELS[signal.name] || signal.label}</strong><span data-band={signal.score_band}>{signal.label}</span><p>{signal.explanation}</p></li>)}</ul>
        : <p className="kb-note"><CircleHelp aria-hidden="true" />표시할 수 있는 맥락 신호가 아직 없습니다.</p>}
    </section>
    <ProvenanceBar data={result.provenance} />
    {result.limitations.length > 0 && <ul className="kb-limitations">{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
  </div>;
}

/** Mirrors the A/B/C/U union exactly — survival grades and probabilities exist only under A. */
function EvidenceContract({ result }: { result: AnalysisResult }) {
  switch (result.evidence_grade) {
    case "A": return <div className="kb-verdict" data-grade="A"><span>{EVIDENCE_LABELS.A}</span><strong>{result.horizon_months}개월 생존 추정범위 {result.probability_lower}~{result.probability_upper}%</strong><p>등급 {result.survival_grade} · 단일 확정값이나 보장이 아닙니다.</p></div>;
    case "B": return <div className="kb-verdict" data-grade="B"><span>{EVIDENCE_LABELS.B}</span><strong>상권 위험 수준 {result.context_risk_grade === "LOW" ? "낮음" : result.context_risk_grade === "HIGH" ? "높음" : "보통"}</strong><p>상권×업종 집계 신호이며 개별 점포의 생존 결과가 아닙니다.</p></div>;
    case "C": return <div className="kb-verdict" data-grade="C"><span>{EVIDENCE_LABELS.C}</span><strong>관측 가능한 입지 신호를 확인했습니다</strong><p>개체·집계 사건이 충분하지 않아 확인된 맥락만 표시합니다. 생존·폐업 확률은 제공하지 않습니다.</p></div>;
    case "U": return <div className="kb-verdict" data-grade="U"><span>{EVIDENCE_LABELS.U}</span><strong>{result.blocked_reason}</strong><ul>{result.required_actions.map((item) => <li key={item}>{item}</li>)}</ul></div>;
    default: return assertNever(result);
  }
}
function assertNever(value: never): never { throw new Error(`Unexpected contract: ${String(value)}`); }

function StepNav({ flow }: { flow: Jarimaegim }) {
  const order: FlowStep[] = ["bands", "recommend", "evidence", "prescribe"];
  const index = order.indexOf(flow.step);
  const next = order[index + 1];
  const previous = order[index - 1];
  const labels: Record<string, string> = { bands: "자금", recommend: "입지", evidence: "근거", prescribe: "처방" };
  return <div className="kb-stepnav">
    {previous ? <button className="kb-ghost" onClick={() => flow.setStep(previous)}>← {labels[previous]}</button> : <button className="kb-ghost" onClick={flow.reset}><RotateCcw aria-hidden="true" /> 조건 다시 입력</button>}
    {next && <button className="kb-primary kb-primary-sm" onClick={() => flow.setStep(next)}>{labels[next]}로 <ArrowRight aria-hidden="true" /></button>}
  </div>;
}
