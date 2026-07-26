"use client";

import Link from "next/link";
import { ArrowRight, Coins, Info, MapPinned, ShieldCheck } from "lucide-react";

const HIGHLIGHTS = [
  { icon: MapPinned, title: "조건에 맞는 입지 추천", copy: "업종·자치구·예산을 말하면 공식 장소 데이터에서 후보를 찾아 지도에 표시합니다." },
  { icon: ShieldCheck, title: "근거 수준을 먼저 밝힘", copy: "A/B/C/U 근거 등급과 출처·기준일을 결과마다 함께 보여줍니다." },
  { icon: Coins, title: "자금조달까지 연결", copy: "입력한 비용으로 조달 차이를 계산하고 공식 공고 원문으로 이어집니다." }
];

export function KbIntroPanel({ onOpenAi }: { onOpenAi: () => void }) {
  return <div className="kb-today">
    <div className="kb-today-date"><strong>서울 창업 입지</strong><span>KB부동산 데모</span></div>
    <button className="kb-ai-cta" onClick={onOpenAi}>
      <span className="kb-ai-badge" aria-hidden="true">AI</span>
      <span className="kb-ai-cta-body">
        <strong>자리매김 AI로 자리 찾기</strong>
        <small>내 상황에 맞는 창업 입지와 자금조달 경로를 확인해 보세요.</small>
      </span>
      <ArrowRight aria-hidden="true" />
    </button>
    <ul className="kb-highlights">{HIGHLIGHTS.map(({ icon: Icon, title, copy }) => <li key={title}>
      <Icon aria-hidden="true" /><div><strong>{title}</strong><p>{copy}</p></div>
    </li>)}</ul>
    <div className="kb-scope">
      <Info aria-hidden="true" />
      <div>
        <strong>이 화면의 범위</strong>
        <p>KB부동산 UI를 참고해 만든 데모입니다. 매물·시세·분양 등 KB 서비스 데이터는 연동되어 있지 않아 표시하지 않으며, 자리매김 AI 기능만 실제로 동작합니다.</p>
      </div>
    </div>
    <p className="kb-legal">공개데이터 기반 참고정보 · 금융 승인과 매출을 보장하지 않습니다 · <Link href="/privacy">데이터 관리</Link></p>
  </div>;
}
