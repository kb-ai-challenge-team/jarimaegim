"use client";

import { useEffect, useMemo, useState } from "react";
import { CircleHelp, Landmark, LoaderCircle, RefreshCw, Search, ShieldCheck } from "lucide-react";
import type { KbProduct } from "@/lib/types";
import type { Jarimaegim } from "@/lib/use-jarimaegim";

type Filter = "ALL" | KbProduct["category"];
const FILTERS: { id: Filter; label: string }[] = [
  { id: "ALL", label: "전체" }, { id: "BUSINESS_LOAN", label: "개인사업자대출" }, { id: "CREDIT_LOAN", label: "개인신용대출" },
  { id: "MORTGAGE_LOAN", label: "주택담보대출" }, { id: "RENT_LOAN", label: "전세자금대출" },
  { id: "DEPOSIT", label: "정기예금" }, { id: "SAVING", label: "적금" }
];

function rateLabel(product: KbProduct) {
  if (product.rate_min === null && product.rate_max === null) return "공시 확인 필요";
  if (product.rate_min === product.rate_max) return `${product.rate_min}%`;
  return `${product.rate_min ?? "?"}~${product.rate_max ?? "?"}%`;
}

/** All KB국민은행 products the FSS discloses, grouped by product category. */
export function KbProductPanel({ flow }: { flow: Jarimaegim }) {
  const [filter, setFilter] = useState<Filter>("ALL");
  const [query, setQuery] = useState("");
  const { kbProducts, kbState, loadKbProducts } = flow;

  useEffect(() => { if (kbState === "idle") void loadKbProducts(); }, [kbState, loadKbProducts]);

  const counts = useMemo(() => kbProducts.reduce<Record<string, number>>((acc, item) => { acc[item.category] = (acc[item.category] || 0) + 1; return acc; }, {}), [kbProducts]);
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return kbProducts.filter((item) => (filter === "ALL" || item.category === filter) && (!needle || item.name.toLowerCase().includes(needle)));
  }, [kbProducts, filter, query]);
  const asOf = kbProducts[0]?.source_as_of;

  return <div className="kb-policy">
    <header className="kb-policy-head">
      <div><Landmark aria-hidden="true" /><strong>KB 금융상품</strong></div>
      <p>금융감독원 금융상품 통합 비교공시에서 KB국민은행 상품만 모았습니다. 금리는 기준월 공시 범위이며 실제 적용 금리가 아닙니다.</p>
    </header>

    <div className="kb-policy-search">
      <Search aria-hidden="true" />
      <label className="sr-only" htmlFor="kb-product-query">상품 검색</label>
      <input id="kb-product-query" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="상품명으로 검색" />
    </div>

    <div className="kb-policy-filters">{FILTERS.map((item) => {
      const total = item.id === "ALL" ? kbProducts.length : (counts[item.id] || 0);
      return <button key={item.id} type="button" aria-pressed={filter === item.id} disabled={total === 0 && item.id !== "ALL"} onClick={() => setFilter(item.id)}>
        {item.label}<em>{total}</em>
      </button>;
    })}</div>

    <div className="kb-policy-body">
      {kbState === "loading" && <div className="kb-loading"><LoaderCircle className="kb-spin" aria-hidden="true" />KB 금융상품 공시를 불러오고 있습니다.</div>}

      {kbState !== "loading" && kbProducts.length === 0 && <div className="kb-empty">
        <Landmark aria-hidden="true" />
        <strong>표시할 수 있는 KB 상품이 없습니다</strong>
        <p>공시 endpoint와 인증키가 설정되기 전에는 상품을 만들어 표시하지 않습니다.</p>
        <button className="kb-ghost" onClick={() => void loadKbProducts()}><RefreshCw aria-hidden="true" /> 다시 확인</button>
      </div>}

      {kbProducts.length > 0 && visible.length === 0 && <div className="kb-empty">
        <Search aria-hidden="true" /><strong>검색 결과가 없습니다</strong><p>다른 상품명으로 찾아보세요.</p>
      </div>}

      {visible.length > 0 && <>
        <p className="kb-policy-count">{visible.length}건 · 기준월 {asOf || "확인 필요"} · 공시 순서대로 표시하며 추천 순위가 아닙니다.</p>
        <ul className="kb-program-list">{visible.map((product) => <li key={product.id}>
          <span className="kb-program-tag">{product.category_label}</span>
          <div className="kb-product-top">
            <strong>{product.name}</strong>
            <span className="kb-product-rate">{rateLabel(product)}</span>
          </div>
          <small>{[product.rate_kind, product.loan_limit && `한도 ${product.loan_limit}`, product.join_way, product.rate_type].filter(Boolean).join(" · ")}</small>
          {product.repay_type && <small>상환 {product.repay_type}</small>}
          <div className="kb-unknown">{product.unknown_conditions.map((condition) => <span key={condition}><CircleHelp aria-hidden="true" />{condition}</span>)}</div>
          <div className="kb-policy-foot">
            <small>{product.organization}</small>
            
          </div>
        </li>)}</ul>
      </>}
    </div>

    <p className="kb-note kb-policy-legal"><ShieldCheck aria-hidden="true" />금융감독원 공시를 그대로 옮긴 목록입니다. 자격·한도·최종 금리는 KB국민은행에서 직접 확인해야 하며, 이 화면에서 신청은 제공하지 않습니다.</p>
  </div>;
}
