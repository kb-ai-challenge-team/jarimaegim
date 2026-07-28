"use client";

import { useMemo } from "react";
import { ArrowRight, CircleHelp, Coins, ExternalLink, FileDown, FileText, Info, Landmark, LoaderCircle, LockKeyhole, MapPin, ShieldCheck, Sparkles } from "lucide-react";
import { PRIORITY_LABELS, PROGRAM_CATEGORY_LABELS, STAGE_LABELS, TYPE_LABELS, formatKrw } from "@/lib/constants";
import type { BandLine, Candidate, CaseRecord, FundingBandResult, KbProduct, Program } from "@/lib/types";
import { matchKbProducts } from "@/lib/kb-match";
import { matchPrograms } from "@/lib/program-match";
import type { BandForm, LocationState, Profile } from "@/lib/use-jarimaegim";

const BAND_LABELS: Record<string, string> = { EQUITY_ONLY: "자기자본선", RECOMMENDED: "권장 조달선", MAXIMUM: "최대 조달선", OUT_OF_RANGE: "조달 불가" };
const BAND_MARKS: Record<string, string> = { EQUITY_ONLY: "●", RECOMMENDED: "◐", MAXIMUM: "◑", OUT_OF_RANGE: "○" };

type TuneField = { key: keyof BandForm; label: string; step: number; unit: string; note?: string };

// 필요자금 축. 여기 값이 비면 현금소진과 필요자금 밴드 판정만 못 낸다 — 상한과 목표매출은 그대로 나온다.
const CAPITAL_FIELDS: TuneField[] = [
  { key: "area_pyeong", label: "희망 평수", step: 1, unit: "평", note: "비우면 인테리어비를 추정하지 않습니다" },
  { key: "deposit_krw", label: "임차보증금", step: 1000000, unit: "원" },
  { key: "key_money_krw", label: "권리금", step: 1000000, unit: "원", note: "계약 전 직접 확인" },
  { key: "fitout_krw", label: "인테리어·설비", step: 1000000, unit: "원", note: "비우면 평수 기준 추정값을 씁니다" }
];
// 월 고정지출 축. 월세는 권장 조달선과 목표매출을 직접 움직인다.
const MONTHLY_FIELDS: TuneField[] = [
  { key: "monthly_rent_krw", label: "월세", step: 100000, unit: "원" },
  { key: "monthly_maintenance_krw", label: "관리비", step: 100000, unit: "원" }
];

/** 현금소진이 비는 이유는 둘이다 — 조달이 필요자금에 못 미쳤거나, 계산할 입력이 없거나.
 *  둘을 같은 문구로 묶으면 "돈이 모자란다"는 잘못된 신호를 준다. */
export function runwayLabel(line: BandLine, partial: boolean) {
  if (line.runway_months !== null) return `${line.runway_months}개월`;
  return partial ? "확인 필요" : "조달 부족";
}

export function BandTable({ lines, partial }: { lines: BandLine[]; partial: boolean }) {
  return <div className="kb-band-table">
    <div className="kb-band-head"><span>밴드</span><span>상한</span><span>월 상환</span><span>목표 일매출</span><span>현금소진</span></div>
    {lines.map((line) => <div key={line.band} className="kb-band-row" data-band={line.band} data-pass={line.stress_pass ? "true" : "false"}>
      <strong><em aria-hidden="true">{BAND_MARKS[line.band]}</em>{BAND_LABELS[line.band]}{line.is_estimate && <small>추정치</small>}</strong>
      <span>{formatKrw(line.ceiling_krw)}</span>
      <span>{line.monthly_repayment_krw > 0 ? formatKrw(line.monthly_repayment_krw) : "0원"}</span>
      <span>{formatKrw(line.target_daily_revenue_krw)}</span>
      <span>{runwayLabel(line, partial)}</span>
    </div>)}
  </div>;
}

/** 입지 화면의 "정밀하게 맞추기" 본문. 여기서 고쳐도 화면을 떠나지 않고 배너와 후보가 그 자리에서 갱신된다.
 *  자기자본·기존부채·월 고정지출은 금융 프로필이 이미 확정했으므로 다시 묻지 않는다. */
export function PlanTuning({ profile, form, bands, state, busy, onField, onRecompute, onEditProfile }: {
  profile: Profile; form: BandForm; bands: FundingBandResult | null; state: LocationState;
  busy: boolean; onField: (key: keyof BandForm, value: number | null) => void;
  onRecompute: () => void; onEditProfile: () => void;
}) {
  const numeric = (key: keyof BandForm) => {
    const value = form[key];
    return value === null ? "" : String(value || "");
  };
  const partial = bands?.status === "partial";
  const field = (item: TuneField) => <label key={item.key} className="kb-field">
    <span>{item.label}{item.note && <small>{item.note}</small>}</span>
    <input type="number" min="0" step={item.step} inputMode="numeric" value={numeric(item.key)}
      onChange={(event) => onField(item.key, event.target.value === "" ? null : Math.max(0, Number(event.target.value)))}
      placeholder={item.unit === "평" ? "미입력" : "0"} />
  </label>;

  return <div className="kb-tune">
    <p className="kb-step-lead">임대료는 공개 원천이 없어 입력값을 그대로 사용합니다. 비워 두면 그 항목에 딸린 값만 계산하지 않을 뿐, 나머지는 그대로 나옵니다. AI는 금액을 만들거나 바꾸지 않습니다.</p>

    <div className="kb-band-form">
      <span className="kb-band-form-title">필요자금 항목</span>
      {CAPITAL_FIELDS.map(field)}
      <span className="kb-band-form-title">월 고정지출</span>
      {MONTHLY_FIELDS.map(field)}
    </div>

    <div className="kb-gate">
      <ShieldCheck aria-hidden="true" />
      <span>자기자본 <strong>{formatKrw(profile.equity_krw)}</strong> · 기존부채 <strong>{formatKrw(profile.existing_debt_krw)}</strong> · 월 고정지출 <strong>{formatKrw(profile.other_monthly_fixed_krw)}</strong> — 금융 프로필에서 확정했습니다.</span>
      <button className="kb-gate-edit" onClick={onEditProfile}>수정</button>
    </div>

    <button className="kb-primary" onClick={onRecompute} disabled={busy}>{busy ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : null}입력값으로 다시 계산</button>

    {state === "loading" && <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />조달 밴드를 계산하고 있습니다.</div>}

    {/* 무엇이 비었는지는 message 가 우리말로 말한다. missing_params 는 내부 파라미터 키라 화면에 내보내지 않는다. */}
    {bands?.status === "integration_pending" && <div className="kb-empty">
      <Coins aria-hidden="true" />
      <strong>조달 밴드 계산에 필요한 값이 아직 없습니다</strong>
      <p>{bands.message}</p>
    </div>}

    {bands && bands.break_even && <>
      <dl className="kb-summary">
        <div><dt>자기자본</dt><dd>{formatKrw(profile.equity_krw)}</dd></div>
        <div><dt>필요자금</dt><dd>{bands.required_capital_krw === null ? "확인 필요" : formatKrw(bands.required_capital_krw)}</dd></div>
        <div><dt>월 고정지출<small>상환 전</small></dt><dd>{formatKrw(bands.break_even.monthly_fixed_cost_krw)}</dd></div>
        <div className="kb-summary-gap"><dt>공헌이익률</dt><dd>{Math.round(bands.break_even.contribution_margin_ratio * 100)}%</dd></div>
      </dl>
      <p className="kb-note"><Info aria-hidden="true" />목표 일매출은 밴드마다 다릅니다. 차입이 늘면 월 상환이 고정지출에 더해져 넘어야 하는 매출도 함께 올라갑니다.</p>
      <BandTable lines={bands.bands} partial={partial} />
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

/** 고르는 것은 문서에 담는다는 뜻이다. 자격 판정도 신청도 아니므로 라벨이 그 말을 그대로 한다. */
type Selection = { ids: string[]; onToggle: (id: string) => void } | null;

/** 보이는 라벨은 여섯 행이 모두 같아도 된다 — 옆에 상품명이 보이니까. 낭독기에는 그 상품명이
 *  같이 읽히지 않으므로 어느 행인지 name 으로 접근성 이름에만 붙인다. KbMap 의 마커와 같은 방식이다. */
function SelectBox({ id, name, selection }: { id: string; name: string; selection: Selection }) {
  if (!selection) return null;
  return <label className="kb-select-row">
    <input type="checkbox" aria-label={`${name} 문서에 담기`} checked={selection.ids.includes(id)} onChange={() => selection.onToggle(id)} />
    <span>문서에 담기</span>
  </label>;
}

function ProductRow({ product, reasons, selection }: { product: KbProduct; reasons?: string[]; selection?: Selection }) {
  return <li>
    <div className="kb-product-top">
      <strong>{product.name}</strong>
      <span className="kb-product-rate">{rateLabel(product)}</span>
    </div>
    {reasons && reasons.length > 0 && <div className="kb-match-reasons">{reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>}
    <small>{[product.loan_limit && `한도 ${product.loan_limit}`, product.join_way, product.rate_type].filter(Boolean).join(" · ")}</small>
    <a href={product.official_url} target="_blank" rel="noopener noreferrer">공시 원문 열기 <ExternalLink aria-hidden="true" /></a>
    <SelectBox id={product.id} name={product.name} selection={selection ?? null} />
  </li>;
}

/** 처방은 검토할 수 있는 분량이어야 한다. 관련도 순으로 이만큼만 보여주고, 줄인 건수를 밝힌다. */
const TOP_N = 3;

/** 전국 공고 카탈로그에서 이 케이스와 겹치는 것만 관련도 순으로 추린다.
 *  다른 광역자치단체 공고와 근거 없는 공고는 아예 내보내지 않는다. */
function ProgramSection({ programs, inputs, selection }: { programs: Program[]; inputs: CaseRecord["inputs"]; selection?: Selection }) {
  const matches = useMemo(() => matchPrograms(programs, inputs), [programs, inputs]);
  const shown = matches.slice(0, TOP_N);
  if (matches.length === 0) return <div className="kb-empty compact">
    <Coins aria-hidden="true" />
    <strong>이 조건과 겹치는 공고가 없습니다</strong>
    <p>확인한 {programs.length}건은 다른 지역 공고이거나 이 케이스와 겹치는 문구가 없어 추천하지 않습니다. 전체 공고는 왼쪽 <strong>정책</strong> 메뉴에서 볼 수 있습니다.</p>
  </div>;

  return <>
    <p className="kb-match-lead"><Sparkles aria-hidden="true" />확인한 {programs.length}건 중 이 조건과 가장 많이 겹치는 {shown.length}건입니다. 자격을 판단한 것이 아닙니다.</p>
    <ul className="kb-program-list">{shown.map(({ program, reasons }) => <li key={program.id}>
      <span className="kb-program-tag">{PROGRAM_CATEGORY_LABELS[program.category]}</span>
      <strong>{program.title}</strong>
      <small>{program.organization} · {program.application_period || "기간 원문 확인"}</small>
      <div className="kb-match-reasons">{reasons.map((reason) => <span key={reason}>{reason}</span>)}</div>
      {program.unknown_conditions.length > 0 && <div className="kb-unknown">{program.unknown_conditions.map((condition) => <span key={condition}><CircleHelp aria-hidden="true" />{condition}</span>)}</div>}
      <a href={program.official_url} target="_blank" rel="noopener noreferrer">공식 원문 열기 <ExternalLink aria-hidden="true" /></a>
      <SelectBox id={program.id} name={program.title} selection={selection ?? null} />
    </li>)}</ul>
    {matches.length > shown.length && <p className="kb-note"><Info aria-hidden="true" />겹치는 {matches.length}건 중 관련도 상위 {shown.length}건만 보여드립니다. 나머지 {matches.length - shown.length}건을 포함한 전체 공고는 왼쪽 <strong>정책</strong> 메뉴에 있습니다.</p>}
  </>;
}

/** KB국민은행 개인사업자대출 공시. Matched rows lead; rates are the disclosed month's range, never an offer. */
function KbProductSection({ products, state, inputs, gapKrw, selection }: { products: KbProduct[]; state: LocationState; inputs: CaseRecord["inputs"]; gapKrw: number | null; selection?: Selection }) {
  const matches = useMemo(() => matchKbProducts(products, inputs, gapKrw), [products, inputs, gapKrw]);
  const shown = matches.slice(0, TOP_N);
  if (state === "loading") return <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />KB 금융상품 공시를 불러오고 있습니다.</div>;
  if (products.length === 0) return null;

  // 처방은 이 케이스에 대한 답이다. 조건과 겹치지 않는 상품은 답이 아니므로 여기서 보여주지 않는다.
  // 전체 공시는 상품 탭에 그대로 있으므로 감추는 것이 아니라 자리를 옮기는 것이다.
  return <section className="kb-products">
    <header><Landmark aria-hidden="true" /><div><strong>KB 금융상품</strong><small>개인사업자대출 공시 {products.length}건 대조 · 기준월 {products[0].source_as_of || "확인 필요"}</small></div></header>

    {matches.length > 0 ? <>
      <p className="kb-match-lead"><Sparkles aria-hidden="true" />조건과 가장 많이 겹치는 {shown.length}건입니다. 자격이나 승인 가능성을 판단한 것이 아닙니다.</p>
      <ul>{shown.map((match) => <ProductRow key={match.product.id} product={match.product} reasons={match.reasons} selection={selection} />)}</ul>
      {/* 몇 건을 줄였는지 밝힌다. 조용히 자르면 "이게 전부"로 읽힌다. */}
      {matches.length > shown.length && <p className="kb-note"><Info aria-hidden="true" />겹치는 {matches.length}건 중 관련도 상위 {shown.length}건만 보여드립니다. 나머지 {matches.length - shown.length}건을 포함한 전체 공시는 왼쪽 <strong>상품</strong> 메뉴에 있습니다.</p>}
    </> : <div className="kb-empty compact">
      <Landmark aria-hidden="true" />
      <strong>현재 조건과 겹치는 공시 문구가 없습니다</strong>
      <p>대조한 {products.length}건 중 조건에 걸리는 상품이 없어 아무것도 추천하지 않습니다. 전체 공시는 왼쪽 <strong>상품</strong> 메뉴에서 볼 수 있습니다.</p>
    </div>}

    <p className="kb-note"><Info aria-hidden="true" />조건 일치는 입력값과 공시 문구의 텍스트 대조입니다. 실제 승인 금리·한도와 자격은 KB국민은행에서 직접 확인해야 합니다.</p>
  </section>;
}

/** 확정한 후보를 어느 화면에서나 한 줄로 요약한다. 계획의 기준이 무엇인지 잊지 않게 하고,
 *  바꾸는 경로를 그 자리에 둔다. ProfileBadge 와 자리는 같지만 요약하는 값도 돌아가는 곳도 다르다. */
function PlanBadge({ committed, onBack }: { committed: Candidate; onBack: () => void }) {
  const listing = committed.listing;
  return <div className="kb-plan-badge">
    <MapPin aria-hidden="true" />
    <span><strong>{committed.name}</strong><small>{committed.road_address || committed.address}
      {listing && ` · 보증금 ${formatKrw(listing.deposit_krw)} · 월세 ${formatKrw(listing.monthly_rent_krw)}`}</small></span>
    <button className="kb-gate-edit" onClick={onBack}>바꾸기</button>
  </div>;
}

/** 후보를 확정하지 않으면 부족분이 없고, 부족분이 없으면 이 화면의 질문이 성립하지 않는다. */
function NoCommitted({ onBackToLocation }: { onBackToLocation: () => void }) {
  return <div className="kb-step"><div className="kb-empty compact"><MapPin aria-hidden="true" />
    <strong>계획 기준 후보를 확정하지 않았습니다</strong>
    <p>입지 단계에서 후보를 하나 확정하면 그 후보의 임대 조건으로 부족분을 계산합니다.</p>
    <button className="kb-ghost" onClick={onBackToLocation}>입지로 돌아가기</button></div></div>;
}

/** ④ 조달. 질문은 하나다 — 부족분을 무엇으로 메울 것인가.
 *  부족분은 새로 계산하지 않는다. 권장 조달선의 차입액(loan_krw)이 이미 그 값이다. */
export function PlanFunding({ caseData, committed, bands, programs, programState, kbProducts, kbState, applicationEnabled, selected, onToggle, onBackToLocation, onNext }: {
  caseData: CaseRecord; committed: Candidate | null; bands: FundingBandResult | null;
  programs: Program[]; programState: LocationState; kbProducts: KbProduct[]; kbState: LocationState;
  applicationEnabled: boolean; selected: { products: string[]; programs: string[] };
  onToggle: (kind: "products" | "programs", id: string) => void;
  onBackToLocation: () => void; onNext: () => void;
}) {
  if (!committed) return <NoCommitted onBackToLocation={onBackToLocation} />;
  const recommended = bands?.bands.find((line) => line.band === "RECOMMENDED") ?? null;
  const equityLine = bands?.bands.find((line) => line.band === "EQUITY_ONLY") ?? null;
  const gapKrw = recommended ? recommended.loan_krw : null;
  const pending = !bands || bands.status === "integration_pending";
  const partial = bands?.status === "partial";
  const chosen = selected.products.length + selected.programs.length;
  const catalogEmpty = kbState !== "loading" && programState !== "loading" && kbProducts.length === 0 && programs.length === 0;

  return <div className="kb-step">
    <PlanBadge committed={committed} onBack={onBackToLocation} />

    <section className="kb-gap-card">
      {/* 이 화면에서 가장 구체적인 숫자가 부족분이다. 그 숫자가 미검증 시연용 파라미터 위에 서
          있다면 숫자 옆에서 말해야 한다 — 값을 숨기는 대신 값의 성격을 밝히는 것이 부록 A
          불변조건 1을 지키는 방식이다. 파라미터가 전부 공시값이 되면 이 줄은 저절로 사라진다. */}
      {bands?.parameter_status === "DEMO" && <p className="kb-capacity-demo"><span className="demo-badge">시연용</span>미검증 시연용 제도 파라미터로 계산한 값입니다. 실제 심사 결과가 아닙니다.</p>}
      <dl>
        <div><dt>필요자금</dt><dd>{bands?.required_capital_krw === null || bands?.required_capital_krw === undefined ? "확인 필요" : formatKrw(bands.required_capital_krw)}</dd></div>
        {/* 자기자본선은 EQUITY_ONLY 밴드가 이미 들고 있는 값이다. 권장선에서 차입액을 빼는
            식을 화면에 만들지 않는다 — 산식은 백엔드에만 있어야 두 곳이 갈라지지 않는다. */}
        <div><dt>자기자본</dt><dd>{equityLine ? formatKrw(equityLine.ceiling_krw) : "확인 필요"}</dd></div>
      </dl>
      {pending
        ? <p className="kb-gap-pending"><Info aria-hidden="true" />{bands?.message || "조달 밴드를 아직 계산하지 못했습니다."}</p>
        /* 권장 조달선이 없으면 부족분을 모른다. compute_bands 는 늘 세 밴드를 다 돌려주고 밴드가 없는
           응답은 integration_pending 뿐이라 지금 이 가지에는 닿지 않는다. 그래도 0원으로 대신하지 않는다 —
           "부족분 0원"은 부족분이 없다는 없는 사실이 된다. 모르는 값은 이 화면의 다른 값들과 같이 확인 필요로 말한다. */
        : gapKrw === null
          ? <p className="kb-gap-pending"><Info aria-hidden="true" />권장 조달선을 읽지 못해 부족분은 확인 필요입니다.</p>
          : gapKrw === 0
            ? <p className="kb-gap-headline">추가 차입 없이 자기자본으로 가능합니다</p>
            : <p className="kb-gap-headline"><strong>부족분 {formatKrw(gapKrw)}</strong>을 무엇으로 메울까요?</p>}
      {/* "위 부족분"을 가리키므로 부족분을 실제로 찍었을 때만 단다. 위가 확인 필요면 가리킬 것이 없다. */}
      {partial && gapKrw !== null && <p className="kb-note"><Info aria-hidden="true" />필요자금은 평수·보증금이 있어야 계산합니다. 위 부족분은 권장 조달선 기준 차입액입니다.</p>}
      {pending && <p className="kb-note"><Info aria-hidden="true" />부족분을 계산하지 못해 아래 목록은 조건 대조만 했습니다. 금액 대조는 하지 않았습니다.</p>}
    </section>

    {catalogEmpty
      ? <div className="kb-empty compact"><Coins aria-hidden="true" />
          <strong>고를 수단이 없습니다</strong>
          <p>확인된 KB 공시와 공식 공고가 없어 아무것도 추천하지 않습니다. 문서에는 확정 조건과 계획 기준 후보만 담깁니다.</p></div>
      : <>
          <KbProductSection products={kbProducts} state={kbState} inputs={caseData.inputs} gapKrw={gapKrw}
            selection={{ ids: selected.products, onToggle: (id) => onToggle("products", id) }} />
          {programState === "loading" && <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />공식 공고를 확인하고 있습니다.</div>}
          {programs.length > 0 && <ProgramSection programs={programs} inputs={caseData.inputs}
            selection={{ ids: selected.programs, onToggle: (id) => onToggle("programs", id) }} />}
        </>}

    <p className="kb-note"><Info aria-hidden="true" />지원사업 endpoint 연동 후 조달선에 반영됩니다. 현재 밴드에는 지원금이 포함되지 않았습니다.</p>
    {!applicationEnabled && <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" /><span>실제 신청과 상담 자동 연결은 제공하지 않습니다. 고르는 것은 문서에 담는다는 뜻이며 신청이 아닙니다.</span></div>}

    <button className="kb-primary" onClick={onNext}>
      {chosen > 0 ? `고른 ${chosen}건으로 문서 만들기` : "선택 없이 서류로"} <ArrowRight aria-hidden="true" />
    </button>
  </div>;
}

/** ⑤ 서류. 미리보기 줄은 render_case_pdf 가 실제로 담는 섹션과 1:1 로 대응한다.
 *  대응이 깨지면 그것이 버그다 — 문서에 없는 것을 있다고 적는 화면은 만들지 않는다. */
export function PlanPaperwork({ caseData, committed, bands, products, programs, documents, docBusy, docNotice, confirmed, onConfirm, onPrepareDocument, onBackToFunding }: {
  caseData: CaseRecord; committed: Candidate | null; bands: FundingBandResult | null;
  products: KbProduct[]; programs: Program[];
  documents: Record<string, string>; docBusy: string; docNotice: string;
  confirmed: boolean; onConfirm: (value: boolean) => void;
  onPrepareDocument: (template: string) => void; onBackToFunding: () => void;
}) {
  const recommended = bands?.bands.find((line) => line.band === "RECOMMENDED") ?? null;
  const chosen = products.length + programs.length;
  // render_case_pdf 는 case.inputs 의 키를 하나도 빼지 않고 '사용자 확인값'에 적는다. 그러니
  // 이 줄도 하나를 빼면 안 된다 — 리드 문장의 "화면에 없는 값은 문서에도 없습니다"가 거짓이 된다.
  // committed_listing_id 만은 바로 아래 '계획 기준 후보' 줄이 이미 말하므로 되풀이하지 않는다.
  const inputs = caseData.inputs;
  // 조달 밴드가 시연용 가정값 위에 서 있으면 문서도 그 사실을 조달 요약에 적는다(funding_section_lines).
  // 숫자를 보여 주는 자리에서 같이 말해야 고지한 것이 된다.
  const assumed = bands?.provenance?.limitations.find((line) => line.includes("시연용 가정값")) ?? null;
  const rows: { label: string; value: string }[] = [
    { label: "확정 조건", value: `${inputs.district} · ${inputs.industry} · ${STAGE_LABELS[inputs.business_stage]} · ${TYPE_LABELS[inputs.startup_type]} · 우선순위 ${PRIORITY_LABELS[inputs.priority]} · 총예산 ${formatKrw(inputs.budget_krw)} · 자기자본 ${formatKrw(inputs.equity_krw)}` },
    // 케이스에 저장된 것만 문서에 담긴다. 다만 저장에 실패해도 이전에 저장해 둔 매물은 그대로 남아
    // 있고 listing_section_lines 는 그것을 그대로 싣는다 — "담기지 않는다"가 아니라 "다른 것이
    // 담길 수 있다"가 실제로 일어나는 일이다.
    { label: "계획 기준 후보", value: !committed ? "확정한 후보가 없습니다"
      : inputs.committed_listing_id === committed.id ? `${committed.name} (시연용 매물)`
      : `${committed.name} — 케이스에 저장하지 못했습니다. 문서에는 이 후보 대신 이전에 저장한 매물이 담길 수 있습니다` },
    { label: "조달 요약", value: recommended
      ? `권장 조달선 ${formatKrw(recommended.ceiling_krw)} · 차입 필요액 ${formatKrw(recommended.loan_krw)} · 월 상환 ${recommended.monthly_repayment_krw > 0 ? formatKrw(recommended.monthly_repayment_krw) : "0원"} · 넘어야 하는 일매출 ${formatKrw(recommended.target_daily_revenue_krw)}`
      : "조달 밴드를 계산하지 못해 이 문서에는 조달 요약이 없습니다" },
    // 문서는 이 고지를 조달 요약 안에 넣는다. 화면에서도 자리는 같지만 줄을 나눈다 — 경고문 자체가
    // '대출 만기·보증한도'처럼 가운뎃점을 품고 있어 위 줄에 이어 붙이면 금액 구분자와 뒤섞인다.
    ...(recommended && assumed ? [{ label: "조달 요약 가정", value: assumed }] : []),
    { label: "고른 조달 수단", value: chosen === 0 ? "고른 조달 수단이 없습니다"
      : [...products.map((product) => product.name), ...programs.map((program) => program.title)].join(" · ") },
    { label: "출처·기준일", value: "각 섹션 말미에 출처명과 기준일을 적습니다. 확인되지 않은 값은 '확인 필요'로 남습니다." },
    { label: "비보장 고지", value: "AI가 작성한 초안이며 결과를 보장하지 않습니다" }
  ];

  return <div className="kb-step">
    {committed && <PlanBadge committed={committed} onBack={onBackToFunding} />}
    <p className="kb-step-lead">아래가 문서에 담기는 전부입니다. 화면에 없는 값은 문서에도 없습니다.</p>

    <ul className="kb-doc-preview">{rows.map((row) => <li key={row.label}>
      <strong>{row.label}</strong><span>{row.value}</span>
    </li>)}</ul>

    <label className="kb-consent">
      <input type="checkbox" checked={confirmed} onChange={(event) => onConfirm(event.target.checked)} />
      <span>위 내용이 문서에 담기는 것을 확인했습니다</span>
    </label>

    <div className="kb-doc-actions">
      <button className="kb-primary" disabled={!confirmed || Boolean(docBusy)} onClick={() => onPrepareDocument("funding")}>
        {docBusy === "funding" ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : <FileDown aria-hidden="true" />}
        {documents.funding ? "초안 내려받기" : "초안 준비하기"}
      </button>
    </div>
    {docNotice && <p className="kb-inline-notice" role="status">{docNotice}</p>}

    <div className="kb-callout kb-callout-lock"><LockKeyhole aria-hidden="true" /><span>상담 자동 연결은 제공하지 않습니다. <strong>초안을 내려받아 지점 상담에 가져가시면 됩니다.</strong> 초안은 상담의 입력이며 승인을 보장하지 않습니다.</span></div>
    <p className="kb-note"><ShieldCheck aria-hidden="true" />문서는 비공개 저장소에 보관하며 현재 익명 세션에서만 내려받을 수 있습니다. 세션은 최대 24시간 유지됩니다.</p>
    <p className="kb-note"><FileText aria-hidden="true" />조달 수단을 더 고르거나 빼려면 <button className="kb-linklike" onClick={onBackToFunding}>조달 단계</button>로 돌아가면 됩니다.</p>
  </div>;
}
