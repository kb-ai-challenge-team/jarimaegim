import Link from "next/link";
import { ArrowRight, Bot, Database, ShieldCheck } from "lucide-react";

export default function StartPage() {
  return <main id="main-content" className="simple-page start-page">
    <header className="simple-header"><Link className="brand" href="/"><span className="brand-mark" aria-hidden="true">터</span>터닥터</Link><Link className="text-link" href="/auth">로그인</Link></header>
    <section className="start-notice"><p className="eyebrow">시작하기 전에</p><h1>무엇을 저장하고,<br/>무엇을 결정하지 않는지 알려드릴게요.</h1><p className="page-lead">로그인 없이 시작할 수 있습니다. 입력한 조건은 분석을 이어가기 위해 승인된 기간 동안 임시 보관되며, 결과는 창업과 금융 결정을 대신하지 않습니다.</p>
      <div className="start-rules"><article><Bot aria-hidden="true"/><h2>AI는 설명과 제안만 합니다</h2><p>조건 변경은 적용 전에 보여드리고, 비용과 분석 수치는 검증된 API 결과만 사용합니다.</p></article><article><Database aria-hidden="true"/><h2>출처와 기준일을 함께 봅니다</h2><p>공개자료의 공간단위·신뢰도·결측을 결과 바로 아래에서 확인할 수 있습니다.</p></article><article><ShieldCheck aria-hidden="true"/><h2>승인과 매출을 보장하지 않습니다</h2><p>지원정보는 공개 조건의 사전 검토이며 공식기관의 원문과 심사가 우선합니다.</p></article></div>
      <div className="start-actions"><Link className="button primary" href="/cases/new?mode=first">처음 창업 조건 입력 <ArrowRight aria-hidden="true"/></Link><Link className="button secondary" href="/cases/new?mode=expand">이전·추가 매장 조건 입력</Link></div><p className="global-notice">공개데이터 기반 참고정보 · 금융 승인과 매출을 보장하지 않습니다 · 무료</p>
    </section>
  </main>;
}
