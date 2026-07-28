"use client";

import { useState } from "react";
import { Pencil, Quote } from "lucide-react";
import { PRIORITY_LABELS, SEOUL_DISTRICTS, STAGE_LABELS, TYPE_LABELS, formatKrw } from "@/lib/constants";
import type { CaseInput, ConditionKey } from "@/lib/types";
import type { Jarimaegim } from "@/lib/use-jarimaegim";

// `ConditionKey` 는 `lib/types.ts` 가 이미 갖고 있다. 여기서 다시 선언하면 같은 것을 두 곳에서
// 정의하게 되고, `ConditionInterpretResult.fields` 와 어긋나도 컴파일러가 못 잡는다.

const ROWS: { key: ConditionKey; label: string }[] = [
  { key: "industry", label: "업종" }, { key: "district", label: "자치구" },
  { key: "monthly_rent_krw", label: "희망 월세" }, { key: "business_stage", label: "사업단계" },
  { key: "startup_type", label: "창업형태" }, { key: "priority", label: "우선순위" }
];

/** 확인 화면이 아니라 상주 스트립이다. 확인 클릭을 없앤 대신, 무엇을 어떤 발화 조각에서
 *  읽었는지가 실행 중에도 화면에 남아야 한다. 값은 언제든 인라인으로 고칠 수 있고, 고치면
 *  영향받는 축이 다시 돈다(M4 전까지는 전체 재실행).
 *
 *  추출에 실패한 항목은 빈칸으로 두고 추측으로 채우지 않는다 — 빈칸이 보여야 사용자가
 *  자기가 말하지 않은 것을 알아본다. */
export function ConditionStrip({ flow, editable, onEdited }: {
  flow: Jarimaegim; editable: boolean; onEdited?: () => void;
}) {
  const { form, bandForm, proposal, edited, setField, setBandField } = flow;
  const [open, setOpen] = useState<ConditionKey | null>(null);

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
  const evidence = (key: ConditionKey): string | null =>
    edited.has(key) ? null : proposal?.fields[key]?.evidence ?? null;

  return <section className="kb-condstrip">
    <h3>이렇게 읽었습니다</h3>
    <ul className="kb-condrows">{ROWS.map((row) => <li key={row.key}>
      <span className="kb-condrow-label">{row.label}</span>
      <strong className="kb-condrow-value">{shown(row.key)}</strong>
      <small className="kb-condrow-source">{source(row.key)}</small>
      <span className="kb-condrow-evidence">{evidence(row.key)
        ? <><Quote aria-hidden="true" />{evidence(row.key)}</>
        : <em>—</em>}</span>
      {/* 편집 패널을 **닫을 때만** 재실행을 알린다. 타이핑 한 글자마다 실행이 돌면 안 된다. */}
      {editable && <button type="button" className="kb-condrow-edit" aria-label={`${row.label} 고치기`}
        onClick={() => { if (open === row.key) { setOpen(null); onEdited?.(); } else setOpen(row.key); }}>
        <Pencil aria-hidden="true" /></button>}
    </li>)}</ul>
    {open && editable && <div className="kb-condstrip-edit">
      {open === "industry" && <label className="kb-field"><span>업종</span>
        <input value={form.industry} onChange={(event) => setField("industry", event.target.value)} placeholder="예: 카페" /></label>}
      {open === "district" && <label className="kb-field"><span>자치구</span>
        <select value={form.district} onChange={(event) => setField("district", event.target.value)}>
          {SEOUL_DISTRICTS.map((district) => <option key={district} value={district}>{district}</option>)}</select></label>}
      {open === "monthly_rent_krw" && <label className="kb-field"><span>희망 월세</span>
        <input type="number" min="0" step="100000" inputMode="numeric" value={bandForm.monthly_rent_krw || ""}
          onChange={(event) => setBandField("monthly_rent_krw", Math.max(0, Number(event.target.value)))} placeholder="0" /></label>}
      {open === "business_stage" && <ChipRow label="사업단계" value={form.business_stage} options={STAGE_LABELS}
        onSelect={(value) => setField("business_stage", value as CaseInput["business_stage"])} />}
      {open === "startup_type" && <ChipRow label="창업형태" value={form.startup_type} options={TYPE_LABELS}
        onSelect={(value) => setField("startup_type", value as CaseInput["startup_type"])} />}
      {open === "priority" && <ChipRow label="우선순위" value={form.priority} options={PRIORITY_LABELS}
        onSelect={(value) => setField("priority", value as CaseInput["priority"])} />}
      <p className="kb-note">고치면 영향받는 분석을 다시 돌립니다.</p>
    </div>}
  </section>;
}

function ChipRow({ label, value, options, onSelect }: { label: string; value: string; options: Record<string, string>; onSelect: (value: string) => void }) {
  return <div className="kb-chiprow"><span>{label}</span><div>{Object.entries(options).map(([key, text]) =>
    <button key={key} type="button" aria-pressed={value === key} onClick={() => onSelect(key)}>{text}</button>)}</div></div>;
}
