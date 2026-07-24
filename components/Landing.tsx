"use client";

import Link from "next/link";
import { ArrowRight, Building2, Check, ChevronRight, Map, MessageSquareText, MoveRight, ShieldCheck, Store } from "lucide-react";

export function Landing() {
  return (
    <main id="main-content" className="landing">
      <header className="landing-header">
        <Link href="/" className="wordmark" aria-label="터닥터 홈"><span className="brand-symbol" aria-hidden="true">터</span><span className="wordmark-partner">KB부동산 ×</span><strong>터닥터</strong></Link>
        <nav aria-label="보조 메뉴"><Link href="/privacy-policy">서비스 원칙</Link><Link href="/auth" className="header-login">로그인</Link></nav>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow"><span className="pulse-dot" /> 서울 창업 의사결정 워크스페이스</span>
          <h1>좋아 보이는 곳보다,<br/><em>설명할 수 있는 곳</em>에서 시작하세요.</h1>
          <p className="hero-lead">업종과 자금 조건을 한 번 입력하면 입지 탐색부터 비용, 공개 지원정보, 실행 체크리스트까지 하나의 근거 흐름으로 이어집니다.</p>
          <div className="journey-choice" aria-label="시작 유형 선택">
            <Link href="/cases/new?mode=first" className="journey-card primary-choice">
              <span className="choice-icon"><Store size={22}/></span>
              <span><small>처음 시작한다면</small><strong>처음 창업을 준비해요</strong></span><ArrowRight aria-hidden="true"/>
            </Link>
            <Link href="/cases/new?mode=expand" className="journey-card">
              <span className="choice-icon"><Building2 size={22}/></span>
              <span><small>운영 경험이 있다면</small><strong>이전하거나 매장을 추가해요</strong></span><ArrowRight aria-hidden="true"/>
            </Link>
          </div>
          <p className="boundary-copy"><ShieldCheck size={16}/> 공개데이터 기반 참고정보 · 금융 승인이나 매출을 보장하지 않음 · 무료</p>
        </div>

        <div className="hero-canvas" aria-label="터닥터 서비스 흐름 미리보기">
          <div className="canvas-top"><span>창업 조건</span><span className="live-label">근거 확인 중</span></div>
          <div className="condition-line"><span>카페</span><span>마포구</span><span>예산 미입력</span></div>
          <div className="decision-path">
            <div className="path-stop active"><span>1</span><div><small>탐색</small><strong>공식 위치 데이터로 후보 찾기</strong></div></div>
            <MoveRight className="path-arrow" aria-hidden="true"/>
            <div className="path-stop"><span>2</span><div><small>분석</small><strong>가능한 범위와 한계 구분</strong></div></div>
            <MoveRight className="path-arrow" aria-hidden="true"/>
            <div className="path-stop"><span>3</span><div><small>실행</small><strong>비용·공고·할 일 연결</strong></div></div>
          </div>
          <div className="canvas-preview-grid">
            <article><Map/><small>입지 후보</small><strong>지도와 목록을 함께</strong><p>지도를 불러오지 못해도 같은 후보를 목록에서 계속 검토합니다.</p></article>
            <article><MessageSquareText/><small>터닥터 AI</small><strong>계산보다 설명에 집중</strong><p>AI가 조건을 바꾸기 전 변경 내용과 영향 범위를 먼저 보여줍니다.</p></article>
          </div>
          <div className="trace-demo" aria-hidden="true"><span>조건</span><i/><span>근거</span><i/><span>실행</span></div>
        </div>
      </section>

      <section className="landing-proof" aria-labelledby="proof-title">
        <div><span className="eyebrow">작동 원칙</span><h2 id="proof-title">숫자가 없으면, 없는 이유까지 보여줍니다.</h2></div>
        <ul>
          <li><Check/><span><strong>서울 25개 자치구</strong>업종에 따라 분석 가능한 수준을 구분합니다.</span></li>
          <li><Check/><span><strong>출처와 기준일</strong>모든 판단 옆에서 바로 확인할 수 있습니다.</span></li>
          <li><Check/><span><strong>공식 원문 우선</strong>지원정보는 신청·승인을 단정하지 않습니다.</span></li>
        </ul>
        <Link href="/cases/new?mode=first" className="text-cta">내 조건으로 시작하기 <ChevronRight/></Link>
      </section>
    </main>
  );
}
