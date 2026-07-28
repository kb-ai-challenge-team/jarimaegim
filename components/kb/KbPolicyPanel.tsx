"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleHelp, LoaderCircle, RefreshCw, ScrollText, Search, ShieldCheck } from "lucide-react";
import { PROGRAM_CATEGORY_LABELS } from "@/lib/constants";
import type { Program } from "@/lib/types";
import type { Jarimaegim } from "@/lib/use-jarimaegim";

type Filter = "ALL" | Program["category"];
const FILTERS: { id: Filter; label: string }[] = [
  { id: "ALL", label: "전체" }, { id: "GOVERNMENT", label: "정부지원" }, { id: "PRIVATE", label: "민간금융" }
];

/** Browses the official notices as source documents. Outbound links to the 원문 were removed on request, so a row states what it knows and defers the rest. */
export function KbPolicyPanel({ flow }: { flow: Jarimaegim }) {
  const [filter, setFilter] = useState<Filter>("ALL");
  const [query, setQuery] = useState("");
  const { catalog, catalogState, loadCatalog } = flow;

  useEffect(() => { if (catalogState === "idle") void loadCatalog(); }, [catalogState, loadCatalog]);

  const counts = useMemo(() => catalog.reduce<Record<string, number>>((acc, item) => { acc[item.category] = (acc[item.category] || 0) + 1; return acc; }, {}), [catalog]);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return catalog.filter((item) => (filter === "ALL" || item.category === filter)
      && (!needle || item.title.toLowerCase().includes(needle) || item.organization.toLowerCase().includes(needle)));
  }, [catalog, filter, query]);

  return <div className="kb-policy">
    <header className="kb-policy-head">
      <div><ScrollText aria-hidden="true" /><strong>정책 원문</strong></div>
      <p>공공 API에서 수집한 공고를 모았습니다. 승인 여부나 자격은 판단하지 않으며, 조건은 소관기관에서 직접 확인해야 합니다.</p>
    </header>

    <div className="kb-policy-search">
      <Search aria-hidden="true" />
      <label className="sr-only" htmlFor="kb-policy-query">공고 검색</label>
      <input id="kb-policy-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="공고명·기관으로 검색" />
    </div>

    <div className="kb-policy-filters">{FILTERS.map((item) => {
      const total = item.id === "ALL" ? catalog.length : (counts[item.id] || 0);
      return <button key={item.id} type="button" aria-pressed={filter === item.id} disabled={total === 0 && item.id !== "ALL"} onClick={() => setFilter(item.id)}>
        {item.label}<em>{total}</em>
      </button>;
    })}</div>

    <div className="kb-policy-body">
      {catalogState === "loading" && <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />공식 공고를 불러오고 있습니다.</div>}

      {catalogState !== "loading" && catalog.length === 0 && <div className="kb-empty">
        <ScrollText aria-hidden="true" />
        <strong>표시할 수 있는 공식 공고가 없습니다</strong>
        <p>검증된 공공 API endpoint와 키가 설정되기 전에는 공고를 만들어 표시하지 않습니다. 원문 URL이 확인되지 않은 항목도 공개하지 않습니다.</p>
        <button className="kb-ghost" onClick={() => void loadCatalog()}><RefreshCw aria-hidden="true" /> 다시 확인</button>
      </div>}

      {catalog.length > 0 && visible.length === 0 && <div className="kb-empty">
        <Search aria-hidden="true" />
        <strong>검색 결과가 없습니다</strong>
        <p>다른 공고명이나 기관명으로 찾아보세요.</p>
      </div>}

      {visible.length > 0 && <>
        <p className="kb-policy-count">{visible.length}건 · 수집 순서대로 표시하며 순위나 추천이 아닙니다.</p>
        <ul className="kb-program-list">{visible.map((program) => <li key={program.id}>
          <span className="kb-program-tag">{PROGRAM_CATEGORY_LABELS[program.category]}</span>
          <strong>{program.title}</strong>
          <small>{program.organization}{program.application_period ? ` · ${program.application_period}` : " · 기간 원문 확인"}</small>
          <div className="kb-unknown">{program.unknown_conditions.map((condition) => <span key={condition}><CircleHelp aria-hidden="true" />{condition}</span>)}</div>
          <div className="kb-policy-foot">
            <small>{program.source_as_of ? `수집 기준 ${program.source_as_of}` : "수집일 확인 필요"}</small>
            
          </div>
        </li>)}</ul>
      </>}
    </div>

    <p className="kb-note kb-policy-legal"><ShieldCheck aria-hidden="true" />기업마당·K-Startup·금융상품 한눈에의 공개 API를 그대로 옮긴 목록입니다. 신청과 심사는 각 기관 원문이 우선합니다.</p>
  </div>;
}
