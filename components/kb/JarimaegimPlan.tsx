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
    <div className="kb-band-head"><span>밴드</span><span>상한</span><span>월 상환</span><span>목표 일매출</span><span>현금소진</span></div>
    {lines.map((line) => <div key={line.band} className="kb-band-row" data-band={line.band} data-pass={line.stress_pass ? "true" : "false"}>
      <strong><em aria-hidden="true">{BAND_MARKS[line.band]}</em>{BAND_LABELS[line.band]}{line.is_estimate && <small>추정치</small>}</strong>
      <span>{formatKrw(line.ceiling_krw)}</span>
      <span>{line.monthly_repayment_krw > 0 ? formatKrw(line.monthly_repayment_krw) : "0원"}</span>
      <span>{formatKrw(line.target_daily_revenue_krw)}</span>
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
      <strong>조달 밴드 계산에 필요한 값이 아직 없습니다</strong>
      <p>{bands.message}</p>
      <ul className="kb-missing-params">{bands.missing_params.map((key) => <li key={key}>{key}</li>)}</ul>
    </div>}

    {bands?.status === "computed" && bands.break_even && <>
      <dl className="kb-summary">
        <div><dt>자기자본</dt><dd>{formatKrw(caseData.inputs.equity_krw)}</dd></div>
        <div><dt>필요자금</dt><dd>{bands.required_capital_krw === null ? "—" : formatKrw(bands.required_capital_krw)}</dd></div>
        <div><dt>월 고정지출<small>상환 전</small></dt><dd>{formatKrw(bands.break_even.monthly_fixed_cost_krw)}</dd></div>
        <div className="kb-summary-gap"><dt>공헌이익률</dt><dd>{Math.round(bands.break_even.contribution_margin_ratio * 100)}%</dd></div>
      </dl>
      <p className="kb-note"><Info aria-hidden="true" />목표 일매출은 밴드마다 다릅니다. 차입이 늘면 월 상환이 고정지출에 더해져 넘어야 하는 매출도 함께 올라갑니다.</p>
      <BandTable lines={bands.bands} />
      {bands.required_capital_band === "OUT_OF_RANGE" && <p className="kb-inline-error" role="alert"><Info aria-hidden="true" />필요자금이 최대 조달선을 넘습니다. 임대 조건을 낮추거나 자기자본을 늘려야 합니다.</p>}
      <ul className="kb-limitations">{bands.break_even.assumptions.map((item) => <li key={item}>{item}</li>)}</ul>
      {bands.provenance && <ul className="kb-limitations">{bands.provenance.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
    </>}
  </div>;
}

function rateLabel(product: KbProduct) {
  if (product.rate_min === null && product.rate_max === null) return "공시 금리 확인 필요";
  if (product.rate_min === product.rate_max) return `${product.rate_min}%`;
  return `${product.rate_min ?? "?"}~${product.rate_max ?? "?"}%`;
}

function ProductRow({ product, reasons }: { product: KbProduct; reasons?: string[] }) {
  return <li>
    <div className="kb-product-top">
      <strong>{product.name}</strong>
      <span className="kb-product-rate">{rateLabel(product)}</span>
    </div>
    {reasons && reasons.length > 0 && <div className="kb-match-reasons">{reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>}
    <small>{[product.loan_limit && `한도 ${product.loan_limit}`, product.join_way, product.rate_type].filter(Boolean).join(" · ")}</small>
    <a href={product.official_url} target="_blank" rel="noopener noreferrer">공시 원문 열기 <ExternalLink aria-hidden="true" /></a>
  </li>;
}

/** KB국민은행 개인사업자대출 공시. Matched rows lead; rates are the disclosed month's range, never an offer. */
function KbProductSection({ products, state, inputs, gapKrw }: { products: KbProduct[]; state: LocationState; inputs: CaseRecord["inputs"]; gapKrw: number | null }) {
  const [expanded, setExpanded] = useState(false);
  const matches = useMemo(() => matchKbProducts(products, inputs, gapKrw), [products, inputs, gapKrw]);
  if (state === "loading") return <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />KB 금융상품 공시를 불러오고 있습니다.</div>;
  if (products.length === 0) return null;

  const matchedIds = new Set(matches.map((match) => match.product.id));
  const rest = products.filter((product) => !matchedIds.has(product.id));
  return <section className="kb-products">
    <header><Landmark aria-hidden="true" /><div><strong>KB 금융상품</strong><small>개인사업자대출 {products.length}건 · 기준월 {products[0].source_as_of || "확인 필요"}</small></div></header>

    {matches.length > 0 ? <>
      <p className="kb-match-lead"><Sparkles aria-hidden="true" />입력한 조건이 공시 문구와 겹치는 {matches.length}건입니다. 자격이나 승인 가능성을 판단한 것이 아닙니다.</p>
      <ul>{matches.slice(0, 5).map((match) => <ProductRow key={match.product.id} product={match.product} reasons={match.reasons} />)}</ul>
    </> : <p className="kb-note"><Info aria-hidden="true" />현재 조건과 겹치는 공시 문구가 없어 전체 목록만 표시합니다.</p>}

    {expanded && <>
      <p className="kb-match-lead kb-match-rest">조건과 겹치지 않는 나머지 {rest.length}건</p>
      <ul>{rest.map((product) => <ProductRow key={product.id} product={product} />)}</ul>
    </>}
    {rest.length > 0 && <button className="kb-ghost" onClick={() => setExpanded(!expanded)}>{expanded ? "접기" : `나머지 ${rest.length}건 보기`}</button>}

    <p className="kb-note"><Info aria-hidden="true" />조건 일치는 입력값과 공시 문구의 텍스트 대조입니다. 실제 승인 금리·한도와 자격은 KB국민은행에서 직접 확인해야 합니다.</p>
  </section>;
}

export function PlanFunding({ programs, state, applicationEnabled, gapMin, kbProducts, kbState, inputs }: { programs: Program[]; state: LocationState; applicationEnabled: boolean; gapMin: number | null; kbProducts: KbProduct[]; kbState: LocationState; inputs: CaseRecord["inputs"] }) {
  return <div className="kb-step">
    <p className="kb-step-lead">정부지원 → 정책자금 → 지역보증 → 민간금융 순으로 확인합니다. 승인 여부는 단정하지 않습니다.</p>
    {gapMin !== null && gapMin > 0 && <div className="kb-callout"><Coins aria-hidden="true" /><span>비용 단계에서 계산한 부족액은 최소 <strong>{formatKrw(gapMin)}</strong>입니다.</span></div>}
    {!applicationEnabled && <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" /><span>실제 신청·상담 연결은 아직 제공하지 않습니다. 공식 원문으로 이동해 직접 확인해 주세요.</span></div>}
    <KbProductSection products={kbProducts} state={kbState} inputs={inputs} gapKrw={gapMin} />
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
