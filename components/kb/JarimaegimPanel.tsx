"use client";

import { useState } from "react";
import { AlertCircle, ArrowRight, Check, ChevronRight, CircleHelp, Info, Landmark, LoaderCircle, LockKeyhole, Quote, RefreshCw, RotateCcw, Search, ShieldCheck, Sparkles, Trash2, X } from "lucide-react";
import { EVIDENCE_BADGES, EVIDENCE_LABELS, PRIORITY_LABELS, SEOUL_DISTRICTS, SIGNAL_LABELS, STAGE_LABELS, TYPE_LABELS, formatKrw } from "@/lib/constants";
import type { AnalysisResult, CaseInput, ConditionKey, FundingBandResult, ListingTerms } from "@/lib/types";
import { manwon } from "@/lib/format";
import type { FlowStep, Jarimaegim, Profile } from "@/lib/use-jarimaegim";
import { ProvenanceBar } from "../ProvenanceBar";
import { PlanPrescription, PlanTuning, runwayLabel } from "./JarimaegimPlan";

// 금융 프로필은 관문이 아니라 1단계다. profile·capacity 가 ①, ask·confirm 이 ②에 매핑된다.
const STEPS: { id: FlowStep; label: string }[] = [
  { id: "profile", label: "자금" }, { id: "ask", label: "조건" },
  { id: "recommend", label: "입지" }, { id: "prescribe", label: "처방" }
];
const STEP_OF: Record<FlowStep, FlowStep> = {
  profile: "profile", capacity: "profile", ask: "ask", confirm: "ask",
  recommend: "recommend", prescribe: "prescribe"
};

export function JarimaegimPanel({ flow, onClose }: { flow: Jarimaegim; onClose: () => void }) {
  const stepIndex = Math.max(0, STEPS.findIndex((step) => step.id === STEP_OF[flow.step]));
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
      {flow.step === "profile" && <ProfileStep flow={flow} />}
      {flow.step === "capacity" && <CapacityStep flow={flow} />}
      {flow.step === "ask" && <AskStep flow={flow} />}
      {flow.step === "confirm" && <ConfirmStep flow={flow} />}
      {flow.step === "recommend" && <RecommendStep flow={flow} />}
      {flow.step === "prescribe" && flow.caseData && <PlanPrescription caseData={flow.caseData}
        committed={flow.candidates.find((item) => item.id === flow.committed) || null}
        programs={flow.programs} state={flow.programState}
        applicationEnabled={Boolean(flow.status?.feature_flags.financial_application)} bands={flow.bands}
        kbProducts={flow.kbProducts.filter((product) => product.category === "BUSINESS_LOAN")} kbState={flow.kbState}
        documents={flow.documents} docBusy={flow.docBusy} docNotice={flow.docNotice}
        onPrepareDocument={(template) => flow.documents[template] ? flow.downloadDocument(template) : flow.prepareDocument(template)}
        onBackToLocation={() => flow.setStep("recommend")} />}
      {flow.caseData && (flow.step === "recommend" || flow.step === "prescribe") && <StepNav flow={flow} />}
    </div>
  </div>;
}

/** 스텝 0. 마이데이터가 주 동선이고, 게이트가 닫혀 있으면 수동 입력이 같은 항목을 채운다.
 *  잠긴 사실을 숨기지 않는 것이 부록 A 불변조건 5의 요구다. */
function ProfileStep({ flow }: { flow: Jarimaegim }) {
  const { profile, setProfileField, status, profileRestored } = flow;
  const mydataOn = Boolean(status?.feature_flags.mydata);
  const ready = profile.equity_krw > 0;
  const money = (key: keyof Profile, label: string, note: string) => <label key={key} className="kb-field">
    <span>{label}<small>{note}</small></span>
    <input type="number" min="0" step="1000000" inputMode="numeric" value={profile[key] || ""}
      onChange={(event) => setProfileField(key, Math.max(0, Number(event.target.value)))} placeholder="0" />
    <em>{profile[key] > 0 ? formatKrw(profile[key]) : "원"}</em>
  </label>;

  return <div className="kb-step">
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>시작하기 전에 <strong>자금 상황을 한 번만</strong> 확인할게요. 여기서 확정한 값은 이후 화면에서 다시 묻지 않고 그대로 다시 씁니다.</p></div>

    <section className="kb-mydata">
      <h3><Landmark aria-hidden="true" />KB 마이데이터로 자동 채우기</h3>
      <p>자기자본 · 기존 대출 잔액 · 월 고정지출을 계좌·대출 정보에서 가져옵니다.</p>
      <button className="kb-primary" disabled={!mydataOn}>마이데이터 연결하고 자동 입력</button>
      {!mydataOn && <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" />
        <span>마이데이터 연동은 아직 열려 있지 않습니다. 아래 직접 입력이 <strong>같은 항목</strong>을 채우므로 이후 흐름은 완전히 같습니다.</span></div>}
    </section>

    <p className="kb-divider"><span>또는 직접 입력</span></p>
    <div className="kb-form kb-profile-form">
      {money("equity_krw", "자기자본", "지금 바로 쓸 수 있는 돈")}
      {money("existing_debt_krw", "기존 대출 잔액", "최대 조달선을 그만큼 낮춥니다")}
      {money("other_monthly_fixed_krw", "월 고정지출", "생활비 등 사업 외 고정지출")}
    </div>

    <button className="kb-primary" onClick={flow.confirmProfile} disabled={!ready}>확정하고 조달 여력 보기 <ArrowRight aria-hidden="true" /></button>
    {!ready && <p className="kb-note"><CircleHelp aria-hidden="true" />자기자본을 채워야 조달 밴드를 계산할 수 있습니다.</p>}

    <div className="kb-reuse">
      <strong>한 번 확정하면 여기에 자동으로 쓰입니다</strong>
      <ul>
        <li>조건 화면에서 자기자본을 다시 묻지 않습니다</li>
        <li>자기자본선과 최대 조달선이 곧바로 계산됩니다</li>
        <li>산출된 권장 조달선이 후보를 거르는 상한이 됩니다</li>
        <li>세션이 만료돼 다시 들어와도 이 화면을 건너뜁니다</li>
      </ul>
    </div>
    <p className="kb-note"><Info aria-hidden="true" />업종 · 자치구 · 희망 임대조건은 마이데이터에 없습니다. 조달 여력을 확인한 뒤 다음 단계에서 받습니다.</p>
    {/* 저장 위치와 지우는 방법을 같은 자리에서 말한다. 금액을 남긴다는 사실을 묻어 두지 않는다. */}
    <p className="kb-note"><ShieldCheck aria-hidden="true" />별도 계정 없이 익명 세션으로 진행합니다. 이 세 항목은 <strong>이 브라우저에만</strong> 저장해 다음 방문에 다시 묻지 않고, 서버에는 조건을 확정해 케이스를 만들 때만 전송합니다.</p>
    {profileRestored && <button className="kb-ghost" onClick={flow.forgetProfile}><Trash2 aria-hidden="true" /> 이 브라우저에 저장된 값 지우기</button>}
  </div>;
}

/** 확정한 프로필을 이후 모든 화면 상단에 상주시킨다. 어디서든 한 번의 클릭으로 되돌아갈 수 있어야 한다. */
function ProfileBadge({ flow }: { flow: Jarimaegim }) {
  if (!flow.profileConfirmed) return null;
  const { equity_krw, existing_debt_krw, other_monthly_fixed_krw } = flow.profile;
  return <div className="kb-gate">
    <Check aria-hidden="true" />
    <span>금융 프로필 확정 — 자기자본 <strong>{formatKrw(equity_krw)}</strong> · 기존부채 <strong>{formatKrw(existing_debt_krw)}</strong> · 월 고정지출 <strong>{formatKrw(other_monthly_fixed_krw)}</strong>
      {flow.profileRestored && <small>이 브라우저에 저장됨</small>}</span>
    <button className="kb-gate-edit" onClick={() => flow.setStep("profile")}>수정</button>
  </div>;
}

/** 1단계의 완결점. 자금을 입력한 대가로 "얼마까지 가능한가"를 돌려준다.
 *  권장 조달선은 여기서 내지 않는다 — 스트레스 테스트가 업종과 월 고정비를 요구하기 때문이고,
 *  그 사실을 빈칸이 아니라 문장으로 말하는 것이 2단계로 넘어가는 동기가 된다. */
function CapacityStep({ flow }: { flow: Jarimaegim }) {
  const { capacity, capacityState } = flow;
  const demo = capacity?.parameter_status === "DEMO";
  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>확정하신 자금으로 <strong>지금 검토할 수 있는 규모</strong>를 계산했습니다. 여기까지가 1단계입니다.</p></div>

    {capacityState === "loading" && <div className="kb-skeletons">{[0, 1].map((row) => <div key={row} className="kb-skeleton" />)}</div>}

    {capacityState === "error" && <div className="kb-empty">
      <AlertCircle aria-hidden="true" /><strong>조달 여력을 계산하지 못했습니다</strong>
      <p>연결 상태를 확인한 뒤 다시 시도해 주세요. 조건 입력은 그대로 진행할 수 있습니다.</p>
      <button className="kb-ghost" onClick={() => flow.loadCapacity(flow.profile)}><RefreshCw aria-hidden="true" /> 다시 계산</button>
    </div>}

    {capacity && capacity.status === "computed" && <section className="kb-capacity">
      {demo && <p className="kb-capacity-demo"><span className="demo-badge">시연용</span>미검증 시연용 제도 파라미터로 계산했습니다. 실제 심사 결과가 아닙니다.</p>}
      <ul className="kb-capacity-lines">
        <li><span>자기자본선</span><strong>{formatKrw(capacity.equity_line_krw)}</strong><small>차입 없이 지금 쓸 수 있는 규모</small></li>
        <li><span>차입 여력</span><strong>{formatKrw(capacity.borrowing_headroom_krw)}</strong><small>보증·정책자금 한도에서 기존 대출 잔액을 뺀 값</small></li>
        <li data-lead="true"><span>최대 조달선</span><strong>{formatKrw(capacity.maximum_line_krw)}</strong><small>신용평가·보증 심사 전 추정치이며 확정 한도가 아닙니다</small></li>
      </ul>
      {capacity.borrowing_headroom_krw === 0 && flow.profile.existing_debt_krw > 0 && <p className="kb-note"><Info aria-hidden="true" />기존 대출 잔액이 한도를 모두 소진해 추가 차입 여력이 없습니다. 최대 조달선이 자기자본선과 같습니다.</p>}
      <div className="kb-capacity-locked">
        <LockKeyhole aria-hidden="true" />
        <div><strong>권장 조달선은 아직 계산하지 않았습니다</strong><p>{capacity.recommended_line_pending}</p></div>
      </div>
      {/* ProvenanceBar 는 한계 문구를 접어 두므로, 사용자가 반드시 봐야 하는 사실은 위처럼 펼쳐 둔다. */}
      {capacity.provenance && <ProvenanceBar data={capacity.provenance} />}
    </section>}

    {capacity && capacity.status === "integration_pending" && <p className="kb-note"><Info aria-hidden="true" />{capacity.message}</p>}

    <button className="kb-primary" onClick={() => flow.setStep("ask")}>조건 입력으로 <ArrowRight aria-hidden="true" /></button>
    <button className="kb-ghost" onClick={() => flow.setStep("profile")}>금액 고치기</button>
  </div>;
}

const EXAMPLES = [
  "마포구에서 카페 준비 중이고 월세는 300 정도 생각해요",
  "성동구에 2호점 낼 자리 찾고 있어요. 임대료 부담이 제일 걱정이에요",
  "관악구 분식점 자리요. 처음 창업이라 안정적인 곳이면 좋겠어요"
];

function AskStep({ flow }: { flow: Jarimaegim }) {
  const [text, setText] = useState(flow.interpretText);
  const busy = flow.busy === "interpret";
  const submit = () => { const value = text.trim(); if (value && !busy) void flow.interpret(value); };
  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>어떤 업종으로 서울 어디에 자리를 잡을지, 희망 월세까지 편하게 말씀해 주세요. 말씀하신 내용을 조건으로 정리해 확인받겠습니다.</p></div>
    <label className="kb-field kb-field-block"><span>상황 설명</span>
      <textarea rows={3} value={text} onChange={(event) => setText(event.target.value)} placeholder="예: 마포구에서 카페 준비 중이고 월세는 300 정도 생각해요" disabled={busy}
        onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); } }} />
    </label>
    <button className="kb-primary" onClick={submit} disabled={!text.trim() || busy}>{busy ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}조건으로 정리하기 <ArrowRight aria-hidden="true" /></button>
    <div className="kb-examples"><span>이렇게 말씀해 보세요</span>{EXAMPLES.map((example) => <button key={example} onClick={() => setText(example)} disabled={busy}>{example}</button>)}</div>
    <button className="kb-ghost" onClick={flow.startManual} disabled={busy}>직접 입력으로 시작 <ChevronRight aria-hidden="true" /></button>
  </div>;
}

// 확인 화면이 한 줄씩 보여주는 조건 전부. 순서가 화면 순서다.
const CONFIRM_ROWS: { key: ConditionKey; label: string }[] = [
  { key: "industry", label: "업종" }, { key: "district", label: "자치구" },
  { key: "monthly_rent_krw", label: "희망 월세" }, { key: "business_stage", label: "사업단계" },
  { key: "startup_type", label: "창업형태" }, { key: "priority", label: "우선순위" }
];

/** 답이 후보를 바꾸는 항목만 비었을 때 묻는다. 최대 3을 넘지 않는다. */
type AskKey = "industry" | "monthly_rent_krw";
const ASK_FIELDS: { key: AskKey; label: string; note: string }[] = [
  { key: "industry", label: "업종", note: "검색 질의어와 업종 파라미터를 정합니다" },
  { key: "monthly_rent_krw", label: "희망 월세", note: "권장 조달선과 목표 매출을 정합니다" }
];

/** "이 조건이 맞나요?" — 값과 함께 무엇에서 그렇게 읽었는지를 같은 줄에 놓는다.
 *  금융 프로필 칩은 여기 없다. 자금은 1단계에서 끝났고 상단 배지가 요약과 수정 경로를 맡는다. */
function ConfirmStep({ flow }: { flow: Jarimaegim }) {
  const { form, bandForm, proposal, edited, setField, setBandField } = flow;
  const [editing, setEditing] = useState(false);
  const filled = (key: AskKey) => key === "industry" ? Boolean(form.industry.trim()) : bandForm.monthly_rent_krw > 0;
  const blanks = ASK_FIELDS.filter((ask) => !filled(ask.key)).map((ask) => ask.key);
  // 질문은 답이 들어오는 순간 사라지면 안 된다. 목록을 값에서 그대로 유도하면 이 필드를 그린 조건이
  // 첫 입력에 곧바로 거짓이 되어 입력 중인 필드가 스스로 언마운트된다 — 스피너 위로 버튼 한 번에
  // 10만 원이 확정되고 타이핑은 첫 글자만 남는다. 그래서 이 화면에 있는 동안 질문은 더해지기만 한다.
  // (조건 고치기에서 값을 다시 비우면 그때 새로 붙는다. 답을 지웠는데 물음이 없으면 안 되기 때문이다.)
  const [asked, setAsked] = useState<AskKey[]>(blanks);
  if (blanks.some((key) => !asked.includes(key))) setAsked(ASK_FIELDS.map((ask) => ask.key).filter((key) => asked.includes(key) || blanks.includes(key)));
  const asks = ASK_FIELDS.filter((ask) => asked.includes(ask.key));
  const ready = blanks.length === 0;

  const shown = (key: ConditionKey): string => {
    if (key === "monthly_rent_krw") return bandForm.monthly_rent_krw > 0 ? formatKrw(bandForm.monthly_rent_krw) : "—";
    if (key === "industry") return form.industry.trim() || "—";
    if (key === "district") return form.district;
    if (key === "business_stage") return STAGE_LABELS[form.business_stage];
    if (key === "startup_type") return TYPE_LABELS[form.startup_type];
    return PRIORITY_LABELS[form.priority];
  };
  /** 출처는 네 가지다. 사용자가 고쳤으면 그것이 이기고, 아니면 제안이 어디서 왔는지를 따른다. */
  const source = (key: ConditionKey): string => {
    if (edited.has(key)) return "직접 입력";
    const field = proposal?.fields[key];
    if (!field || field.value === null) return "기본값";
    return proposal?.source === "AI" ? "AI 추론" : "규칙 추출";
  };
  const evidence = (key: ConditionKey): string | null => edited.has(key) ? null : proposal?.fields[key]?.evidence ?? null;

  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>{blanks.length > 0
      ? <>말씀을 이렇게 읽었습니다. <strong>{blanks.length}개</strong>만 더 알려주시면 바로 찾아드릴게요.</>
      : <><strong>이 조건이 맞나요?</strong> 맞으면 이대로 후보를 찾고, 다르면 고쳐 주세요.</>}</p></div>

    <section className="kb-condcard">
      <h3><Check aria-hidden="true" />이 조건이 맞나요?</h3>
      <ul className="kb-condrows">{CONFIRM_ROWS.map((row) => <li key={row.key}>
        <span className="kb-condrow-label">{row.label}</span>
        <strong className="kb-condrow-value">{shown(row.key)}</strong>
        <small className="kb-condrow-source">{source(row.key)}</small>
        <span className="kb-condrow-evidence">{evidence(row.key)
          ? <><Quote aria-hidden="true" />{evidence(row.key)}</>
          : <em>—</em>}</span>
      </li>)}</ul>
    </section>

    {asks.length > 0 && <section className="kb-askbox">
      <header><span>더 필요한 것</span><small>{asks.length} / 최대 3</small></header>
      {asks.map((ask) => <label key={ask.key} className="kb-field" data-done={filled(ask.key) ? "true" : undefined}>
        <span>{ask.label}<small>{ask.note}</small></span>
        {ask.key === "industry"
          ? <input value={form.industry} onChange={(event) => setField("industry", event.target.value)} placeholder="예: 카페" />
          : <input type="number" min="0" step="100000" inputMode="numeric" value={bandForm.monthly_rent_krw || ""}
              onChange={(event) => setBandField("monthly_rent_krw", Math.max(0, Number(event.target.value)))} placeholder="0" />}
        {ask.key === "monthly_rent_krw" && <em>{bandForm.monthly_rent_krw > 0 ? formatKrw(bandForm.monthly_rent_krw) : "원"}</em>}
      </label>)}
      <p className="kb-note"><Info aria-hidden="true" />평수·보증금·권리금은 후보를 바꾸지 않으므로 묻지 않습니다. 다음 화면의 <strong>정밀하게 맞추기</strong>에서 언제든 넣을 수 있습니다.</p>
    </section>}

    <div className="kb-disclosure" data-open={editing}>
      <button onClick={() => setEditing(!editing)}><span>아니요, 고칠게요</span><small>업종 · 자치구 · 사업단계 · 창업형태 · 우선순위 <ChevronRight aria-hidden="true" /></small></button>
      {editing && <div className="kb-disclosure-body">
        <label className="kb-field"><span>업종</span><input value={form.industry} onChange={(event) => setField("industry", event.target.value)} placeholder="예: 카페" /></label>
        <label className="kb-field"><span>자치구</span><select value={form.district} onChange={(event) => setField("district", event.target.value)}>{SEOUL_DISTRICTS.map((district) => <option key={district} value={district}>{district}</option>)}</select></label>
        <ChipRow label="사업단계" value={form.business_stage} options={STAGE_LABELS} onSelect={(value) => setField("business_stage", value as CaseInput["business_stage"])} />
        <ChipRow label="창업형태" value={form.startup_type} options={TYPE_LABELS} onSelect={(value) => setField("startup_type", value as CaseInput["startup_type"])} />
        <ChipRow label="우선순위" value={form.priority} options={PRIORITY_LABELS} onSelect={(value) => setField("priority", value as CaseInput["priority"])} />
      </div>}
    </div>

    <button className="kb-primary" onClick={flow.start} disabled={!ready || flow.busy === "case"}>{flow.busy === "case" ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}네, 맞아요 · 이 조건으로 입지 찾기</button>
    <button className="kb-ghost" onClick={() => flow.setStep("ask")}><RotateCcw aria-hidden="true" /> 다시 말할게요</button>
    <p className="kb-note"><Check aria-hidden="true" />여기가 마지막 입력 화면입니다. 다음은 곧바로 후보 목록이고, 조달 금액 결정은 후보를 본 뒤에 합니다.</p>
  </div>;
}

function ChipRow({ label, value, options, onSelect }: { label: string; value: string; options: Record<string, string>; onSelect: (value: string) => void }) {
  return <div className="kb-chiprow"><span>{label}</span><div>{Object.entries(options).map(([key, text]) => <button key={key} type="button" aria-pressed={value === key} onClick={() => onSelect(key)}>{text}</button>)}</div></div>;
}

/** 밴드 한 줄. 제목과 수치를 같은 줄에 밀어 넣지 않고 위아래로 나눈다.
 *
 *  좌우 두 칸으로 두면 좁은 패널에서 양쪽이 폭을 다투다가 '늘리 / 면' 처럼 낱말 가운데가
 *  끊긴다. 한국어는 기본 줄바꿈 규칙이 글자 단위라 이런 절단이 그대로 나온다. 제목을 한 줄로
 *  세우고 수치는 아래 줄에 항목 단위로 흘려 보내면 어느 쪽도 잘리지 않는다. */
function BandRow({ label, facts, tone }: { label: React.ReactNode; facts: string[]; tone?: "primary" }) {
  return <div className="kb-band-banner-line" data-tone={tone}>
    <p className="kb-band-banner-line-head">{label}</p>
    <p className="kb-band-banner-facts">{facts.map((fact) => <span key={fact}>{fact}</span>)}</p>
  </div>;
}

/** 확장·축소를 같은 비중으로 보여준다. 한쪽만 노출하면 대출 권유가 된다. */
function BandBanner({ bands }: { bands: FundingBandResult }) {
  const equity = bands.bands.find((line) => line.band === "EQUITY_ONLY");
  const recommended = bands.bands.find((line) => line.band === "RECOMMENDED");
  const maximum = bands.bands.find((line) => line.band === "MAXIMUM");
  if (!equity || !recommended || !maximum) return null;
  const partial = bands.status === "partial";
  // 사실을 한 문자열로 이어 붙이면 좁은 패널에서 '스트레스 실/패' 처럼 낱말 가운데가 끊긴다.
  // 항목별로 쪼개 두면 각 항목이 통째로 줄을 넘어간다.
  const facts = (line: typeof equity) => [
    `상환 ${line.monthly_repayment_krw > 0 ? formatKrw(line.monthly_repayment_krw) : "0원"}`,
    `목표 일매출 ${formatKrw(line.target_daily_revenue_krw)}`,
    `소진 ${runwayLabel(line, partial)}`,
    ...(line.stress_pass ? [] : ["스트레스 실패"])
  ];
  return <div className="kb-band-banner">
    <BandRow tone="primary" label={<><strong>권장 조달선 {formatKrw(recommended.ceiling_krw)}</strong> 기준</>} facts={facts(recommended)} />
    <p className="kb-band-banner-source"><span>자기자본 {formatKrw(equity.ceiling_krw)} + 차입 {formatKrw(recommended.loan_krw)}</span><span>금융 프로필에서 자동 반영</span></p>
    <BandRow label={<>▼ 자기자본만 {formatKrw(equity.ceiling_krw)}으로 줄이면</>} facts={facts(equity)} />
    <BandRow label={<>▲ 최대 {formatKrw(maximum.ceiling_krw)}까지 늘리면</>} facts={facts(maximum)} />
    {/* 이 배너는 화면에서 가장 구체적인 금액을 보여 주는 자리다. 그 숫자가 시연용 가정값
        위에 서 있다면 숫자 옆에서 말해야 한다 — API 응답에만 있고 화면에 없으면 고지한 게
        아니다. 파라미터가 전부 공시값으로 바뀌면 이 줄은 저절로 사라진다. */}
    {assumedNotice(bands) && <p className="kb-band-banner-warning"><AlertCircle aria-hidden="true" />{assumedNotice(bands)}</p>}
    <p className="kb-band-banner-note">아래 목록은 보증금이 권장 조달선을 넘는 매물을 제외한 결과입니다. 밴드별로 열리는 상권 수는 상권 임대 수준 데이터 연동 후 제공합니다.</p>
  </div>;
}

/** 조달 밴드가 시연용 가정값 위에 서 있으면 그 고지 문장을 돌려준다. 아니면 null. */
function assumedNotice(bands: FundingBandResult): string | null {
  return bands.provenance?.limitations.find((line) => line.includes("시연용 가정값")) ?? null;
}

/** 매물의 가정값 속성. 실측이 아니므로 임대 조건과 같은 줄에 섞지 않고 별도 줄에 둔다.
 *  값이 없는 항목은 아예 렌더하지 않는다 — 마이그레이션 이전 저장소에서 읽으면 비어 있다. */
function AssumedTerms({ listing }: { listing: ListingTerms }) {
  const parts: string[] = [];
  if (typeof listing.exclusive_area_m2 === "number") parts.push(`전용 ${listing.exclusive_area_m2}㎡`);
  if (typeof listing.built_year === "number") parts.push(`${listing.built_year}년 준공`);
  if (typeof listing.floors_total === "number") parts.push(`${listing.floor}/${listing.floors_total}층`);
  if (typeof listing.frontage_m === "number") parts.push(`전면 ${listing.frontage_m}m`);
  if (typeof listing.parking_slots === "number") parts.push(listing.parking_slots > 0 ? `주차 ${listing.parking_slots}대` : "주차 불가");
  if (listing.corner) parts.push("코너");
  if (listing.elevator) parts.push("엘리베이터");
  if (listing.available_from) parts.push(`${listing.available_from} 입주`);
  if (parts.length === 0) return null;
  return <span className="listing-assumed"><span className="assumed-badge" title="실측 출처가 없어 가정한 값입니다. 계약 전 직접 확인해야 합니다.">가정값</span>{parts.join(" · ")}</span>;
}

function RecommendStep({ flow }: { flow: Jarimaegim }) {
  const { candidates, locationState, focused, caseData, trace, bands, analysis } = flow;
  const [tuning, setTuning] = useState(false);
  const [openEvidence, setOpenEvidence] = useState<string | null>(null);
  const conditions = flow.form.district.trim();
  const toggleEvidence = (id: string) => {
    if (openEvidence === id) { setOpenEvidence(null); return; }
    setOpenEvidence(id); void flow.runAnalysis(id);
  };

  return <div className="kb-step">
    <ProfileBadge flow={flow} />
    <div className="kb-bubble"><Sparkles aria-hidden="true" /><p>{trace.state === "running"
      ? `${conditions} 시연용 매물 데이터를 확인하는 중입니다. 아래에서 지금 어떤 단계를 거치고 있는지 확인할 수 있습니다.`
      : trace.state === "failed" ? `${conditions} 조건의 확인이 중간에 멈췄습니다. 어느 단계에서 멈췄는지 아래에 그대로 남겨 두었습니다.`
      : caseData ? `${caseData.inputs.district} 시연용 매물을 ${caseData.inputs.industry} 업종의 서울시 상권분석 집계로 확인했습니다. 지도의 마커와 아래 목록이 같은 후보입니다.` : "조건을 확정하면 후보를 찾습니다."}</p></div>

    {bands && bands.status !== "integration_pending" && <BandBanner bands={bands} />}
    {bands?.status === "integration_pending" && <p className="kb-note"><Info aria-hidden="true" />{bands.message}</p>}

    {caseData && <div className="kb-disclosure" data-open={tuning}>
      <button onClick={() => setTuning(!tuning)}><span>정밀하게 맞추기</span><small>평수 · 보증금 · 권리금 · 인테리어 · 관리비 <ChevronRight aria-hidden="true" /></small></button>
      {tuning && <div className="kb-disclosure-body">
        <PlanTuning profile={flow.profile} form={flow.bandForm} bands={bands} state={flow.bandState}
          busy={flow.busy === "bands"} onField={flow.setBandField} onRecompute={flow.recomputeBands}
          onEditProfile={() => flow.setStep("profile")} />
      </div>}
    </div>}

    {locationState === "loading" && <div className="kb-skeletons">{[0, 1, 2].map((row) => <div key={row} className="kb-skeleton" />)}</div>}
    {trace.state !== "running" && locationState !== "loading" && locationState !== "error" && candidates.length === 0 && <div className="kb-empty">
      <Search aria-hidden="true" />
      <strong>{locationState === "integration_pending" ? "시연용 매물 데이터 연결을 기다리고 있습니다" : "현재 조건에서 표시할 후보가 없습니다"}</strong>
      <p>{locationState === "integration_pending" ? "매물 데이터가 연결되면 후보를 불러옵니다. 연결 전에는 가상 후보를 만들지 않습니다." : "시연용 매물이 준비된 자치구인지, 총예산이 보증금보다 낮지 않은지 확인해 주세요."}</p>
      <button className="kb-ghost" onClick={flow.retrySearch}><RefreshCw aria-hidden="true" /> 다시 확인</button>
    </div>}

    {candidates.length > 0 && <>
      {/* 정렬 근거를 그대로 말한다. 상권 통계로 판정한 후보가 먼저 오고, 판정하지 못한 후보는
          월세 순으로 뒤에 붙는다. 뒤로 보낸 것이지 떨어뜨린 것이 아니다. */}
      <p className="kb-step-lead">시연용 매물 {candidates.length}곳입니다. 업종·우선순위와 서울시 상권분석 집계로 줄 세웠고, 상권 통계를 확인하지 못한 곳은 뒤에 월세 순으로 붙였습니다. 실제 임대 매물이 아니고, 개별 점포 생존등급은 근거 A에서만 제공합니다.</p>
      <ul className="kb-candidates">{candidates.map((candidate, index) => <li key={candidate.id} data-focused={candidate.id === focused ? "true" : undefined}>
        <button className="kb-candidate-main" onClick={() => flow.setFocused(candidate.id)} aria-pressed={candidate.id === focused}>
          <span className="kb-rank">{index + 1}</span>
          <span className="kb-candidate-body">
            <strong>{candidate.name}</strong>
            <small>{candidate.road_address || candidate.address}</small>
            <span className="kb-grade" data-grade={candidate.evidence_grade}>{EVIDENCE_BADGES[candidate.evidence_grade]} · {EVIDENCE_LABELS[candidate.evidence_grade]}</span>
            {candidate.listing && <span className="listing-terms"><span className="demo-badge">시연용</span><span>{candidate.listing.area_m2}㎡</span><span>보증금 <strong>{manwon(candidate.listing.deposit_krw)}</strong></span><span>월세 <strong>{manwon(candidate.listing.monthly_rent_krw)}</strong></span>{typeof candidate.listing.key_money_krw === "number" && <span>권리금 <strong>{candidate.listing.key_money_krw > 0 ? manwon(candidate.listing.key_money_krw) : "없음"}</strong></span>}</span>}
            {candidate.listing && <AssumedTerms listing={candidate.listing} />}
          </span>
        </button>
        <ProvenanceBar data={candidate.provenance} />
        <div className="kb-candidate-actions">
          <button className="kb-ghost" aria-expanded={openEvidence === candidate.id} onClick={() => toggleEvidence(candidate.id)}>
            {openEvidence === candidate.id ? "근거 접기" : "근거 펼치기"} <ChevronRight aria-hidden="true" />
          </button>
          {flow.committed === candidate.id
            ? <button className="kb-primary kb-primary-sm" onClick={() => flow.commitCandidate(null)}><Check aria-hidden="true" /> 계획 기준</button>
            : <button className="kb-ghost" onClick={() => flow.commitCandidate(candidate.id)}>계획 기준으로 확정</button>}
        </div>
        {openEvidence === candidate.id && <Evidence name={candidate.name} result={analysis[candidate.id]} />}
      </li>)}</ul>
      <p className="kb-note"><Info aria-hidden="true" />조달 밴드를 넘어 탈락한 후보는 없습니다. 상권 임대 수준 데이터가 연동되기 전에는 밴드로 상권을 거를 수 없어 탈락 목록도 만들지 않습니다.</p>
    </>}
  </div>;
}

/** 목록 안에서 펼쳐지는 근거. 스텝을 옮기지 않으므로 다른 후보로 바로 넘어갈 수 있다. */
function Evidence({ name, result }: { name: string; result: AnalysisResult | undefined }) {
  if (!result) return <div className="kb-evidence"><div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />{name}에서 확인 가능한 근거를 정리하고 있습니다.</div></div>;
  return <div className="kb-evidence">
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
  const order: FlowStep[] = ["recommend", "prescribe"];
  const index = order.indexOf(flow.step);
  const next = order[index + 1];
  const previous = order[index - 1];
  const labels: Record<string, string> = { recommend: "입지", prescribe: "처방" };
  return <div className="kb-stepnav">
    {previous ? <button className="kb-ghost" onClick={() => flow.setStep(previous)} aria-label={`이전 단계 ${labels[previous]}`}>← 이전</button>
      : <button className="kb-ghost" onClick={flow.restart}><RotateCcw aria-hidden="true" /> 조건 다시 입력</button>}
    {next && <button className="kb-primary kb-primary-sm" onClick={() => flow.setStep(next)} aria-label={`다음 단계 ${labels[next]}`}>다음 <ArrowRight aria-hidden="true" /></button>}
  </div>;
}
