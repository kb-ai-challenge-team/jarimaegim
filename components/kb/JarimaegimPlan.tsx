"use client";

import { useState } from "react";
import { CircleHelp, Coins, ExternalLink, Info, Landmark, LoaderCircle, LockKeyhole } from "lucide-react";
import { PROGRAM_CATEGORY_LABELS, formatKrw } from "@/lib/constants";
import type { CaseRecord, CostItem, CostPlan, KbProduct, Program } from "@/lib/types";
import type { LocationState } from "@/lib/use-jarimaegim";

const BLANK_ITEMS: CostItem[] = [
  { key: "deposit", label: "임차보증금", min_krw: null, max_krw: null, source_type: "USER" },
  { key: "premium", label: "권리금", min_krw: null, max_krw: null, source_type: "UNAVAILABLE", note: "계약 전 직접 확인" },
  { key: "interior", label: "인테리어·설비", min_krw: null, max_krw: null, source_type: "USER" },
  { key: "inventory", label: "초기 재고·운영", min_krw: null, max_krw: null, source_type: "USER" },
  { key: "reserve", label: "안전예비비", min_krw: null, max_krw: null, source_type: "USER" }
];

export function PlanCost({ caseData, plan, busy, onSave }: { caseData: CaseRecord; plan: CostPlan | null; busy: boolean; onSave: (items: CostItem[]) => void }) {
  const [items, setItems] = useState<CostItem[]>(BLANK_ITEMS);
  const [issue, setIssue] = useState("");
  const update = (key: string, side: "min_krw" | "max_krw", raw: string) => {
    const value = raw === "" ? null : Math.max(0, Number(raw));
    setItems((prev) => prev.map((item) => item.key === key ? { ...item, [side]: value } : item));
  };
  const filled = items.some((item) => item.min_krw !== null || item.max_krw !== null);

  /** A row left blank is "not confirmed", not "zero" — send it as UNAVAILABLE so it stays out of the sum. */
  function submit() {
    const problems: string[] = [];
    const payload = items.map((item) => {
      if (item.source_type === "UNAVAILABLE") return item;
      if (item.min_krw === null && item.max_krw === null) return { ...item, source_type: "UNAVAILABLE" as const, note: "미입력 · 합계에서 제외" };
      if (item.min_krw === null || item.max_krw === null) problems.push(`${item.label}: 최소와 최대를 모두 입력해 주세요.`);
      else if (item.max_krw < item.min_krw) problems.push(`${item.label}: 최대가 최소보다 작습니다.`);
      return item;
    });
    if (problems.length > 0) { setIssue(problems[0]); return; }
    setIssue(""); onSave(payload);
  }

  return <div className="kb-step">
    <p className="kb-step-lead">확인한 금액만 합산합니다. 비워 둔 항목은 합계에서 빠지며, AI는 비용을 만들거나 바꾸지 않습니다.</p>
    <div className="kb-cost-table">
      <div className="kb-cost-head"><span>항목</span><span>최소</span><span>최대</span></div>
      {items.map((item) => <div key={item.key} className="kb-cost-row">
        <strong>{item.label}{item.note && <small>{item.note}</small>}</strong>
        {item.source_type === "UNAVAILABLE"
          ? <><em className="kb-cost-na">확인 필요</em><em className="kb-cost-na">확인 필요</em></>
          : <>
            <label><span className="sr-only">{item.label} 최소 금액</span><input type="number" min="0" step="100000" inputMode="numeric" value={item.min_krw ?? ""} onChange={(event) => update(item.key, "min_krw", event.target.value)} placeholder="0" /></label>
            <label><span className="sr-only">{item.label} 최대 금액</span><input type="number" min="0" step="100000" inputMode="numeric" value={item.max_krw ?? ""} onChange={(event) => update(item.key, "max_krw", event.target.value)} placeholder="0" /></label>
          </>}
      </div>)}
    </div>
    {issue && <p className="kb-inline-error" role="alert"><Info aria-hidden="true" />{issue}</p>}
    <button className="kb-primary" onClick={submit} disabled={!filled || busy}>{busy ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}입력값으로 조달 차이 계산</button>
    <dl className="kb-summary">
      <div><dt>총예산</dt><dd>{formatKrw(caseData.inputs.budget_krw)}</dd></div>
      <div><dt>자기자본</dt><dd>{formatKrw(caseData.inputs.equity_krw)}</dd></div>
      <div><dt>소요자금 범위</dt><dd>{plan ? `${formatKrw(plan.total_min_krw)} ~ ${formatKrw(plan.total_max_krw)}` : "계산 전"}</dd></div>
      <div className="kb-summary-gap"><dt>조달 차이</dt><dd>{plan ? `${formatKrw(plan.gap_min_krw)} ~ ${formatKrw(plan.gap_max_krw)}` : "—"}</dd></div>
    </dl>
    <p className="kb-note"><Info aria-hidden="true" />합계는 입력값의 단순 합산입니다.{plan ? ` 합계에서 제외된 항목: ${plan.items.filter((item) => item.source_type === "UNAVAILABLE").map((item) => item.label).join(", ") || "없음"}.` : " 권리금처럼 확인하지 못한 항목은 합계에 넣지 않습니다."}</p>
  </div>;
}

function rateLabel(product: KbProduct) {
  if (product.rate_min === null && product.rate_max === null) return "공시 금리 확인 필요";
  if (product.rate_min === product.rate_max) return `${product.rate_min}%`;
  return `${product.rate_min ?? "?"}~${product.rate_max ?? "?"}%`;
}

/** KB국민은행 개인사업자대출 공시. Rates are the disclosed month's range, never an offer. */
function KbProductSection({ products, state }: { products: KbProduct[]; state: LocationState }) {
  const [expanded, setExpanded] = useState(false);
  if (state === "loading") return <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />KB 금융상품 공시를 불러오고 있습니다.</div>;
  if (products.length === 0) return null;
  const online = products.filter((product) => /인터넷|스마트폰/.test(product.join_way || ""));
  const shown = expanded ? products : products.slice(0, 6);
  return <section className="kb-products">
    <header><Landmark aria-hidden="true" /><div><strong>KB 금융상품</strong><small>개인사업자대출 {products.length}건 · 비대면 가입 {online.length}건 · 기준월 {products[0].source_as_of || "확인 필요"}</small></div></header>
    <ul>{shown.map((product) => <li key={product.id}>
      <div className="kb-product-top">
        <strong>{product.name}</strong>
        <span className="kb-product-rate">{rateLabel(product)}</span>
      </div>
      <small>{[product.loan_limit && `한도 ${product.loan_limit}`, product.join_way, product.rate_type].filter(Boolean).join(" · ")}</small>
      <a href={product.official_url} target="_blank" rel="noopener noreferrer">공시 원문 열기 <ExternalLink aria-hidden="true" /></a>
    </li>)}</ul>
    {products.length > 6 && <button className="kb-ghost" onClick={() => setExpanded(!expanded)}>{expanded ? "접기" : `${products.length - 6}건 더 보기`}</button>}
    <p className="kb-note"><Info aria-hidden="true" />금융감독원 금융상품 통합 비교공시의 기준월 공시 범위입니다. 실제 승인 금리·한도와 자격은 KB국민은행에서 직접 확인해야 합니다.</p>
  </section>;
}

export function PlanFunding({ programs, state, applicationEnabled, gapMin, kbProducts, kbState }: { programs: Program[]; state: LocationState; applicationEnabled: boolean; gapMin: number | null; kbProducts: KbProduct[]; kbState: LocationState }) {
  return <div className="kb-step">
    <p className="kb-step-lead">정부지원 → 정책자금 → 지역보증 → 민간금융 순으로 확인합니다. 승인 여부는 단정하지 않습니다.</p>
    {gapMin !== null && gapMin > 0 && <div className="kb-callout"><Coins aria-hidden="true" /><span>비용 단계에서 계산한 부족액은 최소 <strong>{formatKrw(gapMin)}</strong>입니다.</span></div>}
    {!applicationEnabled && <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" /><span>실제 신청·상담 연결은 아직 제공하지 않습니다. 공식 원문으로 이동해 직접 확인해 주세요.</span></div>}
    <KbProductSection products={kbProducts} state={kbState} />
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
