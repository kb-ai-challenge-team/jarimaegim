"use client";

import Link from "next/link";
import {
  ArrowRight,
  Building2,
  Check,
  ChevronRight,
  Database,
  FileCheck2,
  MapPinned,
  Search,
  ShieldCheck,
  Sparkles,
  Store,
} from "lucide-react";

export function Landing() {
  return (
    <main id="main-content" className="home-page">
      <header className="home-header">
        <div className="home-header-inner">
          <Link href="/" className="home-brand" aria-label="자리매김 홈">
            <span className="brand-symbol" aria-hidden="true" />
            <span className="wordmark-partner">KB부동산 ×</span>
            <strong>자리매김</strong>
          </Link>
          <nav aria-label="보조 메뉴">
            <Link href="/privacy-policy" className="home-nav-link">서비스 원칙</Link>
          </nav>
        </div>
      </header>

      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero-copy">
          <p className="home-kicker"><span aria-hidden="true" /> KB부동산과 함께 보는 서울 창업 입지</p>
          <h1 id="home-title">창업할 곳,<br />느낌보다 <em>근거로</em> 고르세요.</h1>
          <p className="home-lead">업종과 자금 조건을 입력하면 후보 입지, 비용, 공개 지원정보와 실행 계획을 하나의 판단 흐름으로 정리합니다.</p>

          <div className="home-hero-actions" aria-label="시작 유형 선택">
            <Link href="/cases/new?mode=first" className="home-primary-action">
              <span className="home-action-icon" aria-hidden="true"><Store /></span>
              <span><small>별도 계정 없이 시작</small><strong>내 조건 입력하기</strong></span>
              <ArrowRight aria-hidden="true" />
            </Link>
            <Link href="/cases/new?mode=expand" className="home-secondary-action">
              <Building2 aria-hidden="true" />
              <span>이전·2호점 검토</span>
              <ChevronRight aria-hidden="true" />
            </Link>
          </div>

          <ul className="home-trust-list" aria-label="서비스 범위">
            <li><ShieldCheck /> 공개데이터 기반</li>
            <li><MapPinned /> 서울 25개 자치구</li>
            <li><Check /> 무료로 시작</li>
          </ul>
        </div>

        <aside className="home-decision-card" aria-label="자리매김 의사결정 흐름 미리보기">
          <header>
            <div><span>DECISION BRIEF</span><h2>창업 의사결정서</h2></div>
            <strong><i aria-hidden="true" /> 근거 확인 가능</strong>
          </header>

          <div className="home-case-strip" aria-label="예시 창업 조건">
            <span><small>업종</small><b>카페</b></span>
            <span><small>지역</small><b>마포구</b></span>
            <span><small>총예산</small><b>1억 원</b></span>
          </div>

          <ol className="home-decision-steps">
            <li className="active">
              <span className="home-step-number">01</span>
              <div><small>후보 탐색</small><strong>공식 위치 데이터로 찾기</strong><p>지도와 목록에서 같은 후보를 확인합니다.</p></div>
              <Search aria-hidden="true" />
            </li>
            <li>
              <span className="home-step-number">02</span>
              <div><small>범위 구분</small><strong>가능한 판단과 한계 나누기</strong><p>데이터가 없는 항목은 이유와 함께 표시합니다.</p></div>
              <FileCheck2 aria-hidden="true" />
            </li>
            <li>
              <span className="home-step-number">03</span>
              <div><small>실행 연결</small><strong>비용·공고·할 일 정리</strong><p>검토 결과를 다음 행동으로 이어갑니다.</p></div>
              <Sparkles aria-hidden="true" />
            </li>
          </ol>

          <footer>
            <span><Database /> 공공데이터 출처·기준일 표시</span>
            <small>SAMPLE / 서울 마포구</small>
          </footer>
        </aside>
      </section>

      <section className="home-proof-strip" aria-label="자리매김의 검증 기준">
        <div><strong>25</strong><span>서울 자치구 지원</span></div>
        <div><strong>출처</strong><span>판단 옆에서 바로 확인</span></div>
        <div><strong>원문</strong><span>공식 링크를 우선 연결</span></div>
        <div><strong>경계</strong><span>모르는 값은 임의 생성 안 함</span></div>
      </section>

      <section className="home-process" aria-labelledby="process-title">
        <header>
          <span className="home-section-label">판단이 만들어지는 순서</span>
          <h2 id="process-title">추천 한 줄보다,<br />결정의 과정을 남깁니다.</h2>
          <p>무엇을 입력했고, 어떤 근거를 봤으며, 다음에 무엇을 해야 하는지 한 화면에서 이어집니다.</p>
        </header>

        <div className="home-process-track">
          <article>
            <span className="home-process-icon"><Store /></span>
            <small>01 · 조건</small>
            <h3>내 상황부터 확정</h3>
            <p>업종, 지역, 예산과 사업단계를 직접 확인합니다.</p>
          </article>
          <i aria-hidden="true" />
          <article>
            <span className="home-process-icon"><Database /></span>
            <small>02 · 근거</small>
            <h3>공식 데이터 연결</h3>
            <p>후보마다 출처와 기준일, 분석 가능한 범위를 붙입니다.</p>
          </article>
          <i aria-hidden="true" />
          <article>
            <span className="home-process-icon"><FileCheck2 /></span>
            <small>03 · 실행</small>
            <h3>비교와 계획으로 이동</h3>
            <p>비용과 지원정보, 해야 할 일을 순서대로 정리합니다.</p>
          </article>
        </div>
      </section>

      <section className="home-guardrail" aria-labelledby="guardrail-title">
        <div className="home-guardrail-copy">
          <span className="home-guardrail-icon"><ShieldCheck /></span>
          <div>
            <span className="home-section-label">AI 사용 원칙</span>
            <h2 id="guardrail-title">AI가 판단을<br />대신하지 않습니다.</h2>
            <p>자리매김 AI는 조건을 정리하고 근거를 설명합니다. 중요한 값은 적용 전에 반드시 사용자가 확인합니다.</p>
          </div>
        </div>
        <dl className="home-guardrail-list">
          <div><dt>비용과 점수</dt><dd>임의로 만들지 않음</dd></div>
          <div><dt>지원사업</dt><dd>신청·승인을 단정하지 않음</dd></div>
          <div><dt>조건 변경</dt><dd>영향 범위를 먼저 안내</dd></div>
        </dl>
      </section>

      <section className="home-final-cta" aria-labelledby="final-cta-title">
        <div>
          <span className="home-section-label">첫 검토는 무료입니다</span>
          <h2 id="final-cta-title">내 조건으로 서울의 후보를 확인해 보세요.</h2>
          <p>별도 계정 없이 시작하며, 조건과 문서는 현재 브라우저에서 최대 24시간 이어볼 수 있습니다.</p>
        </div>
        <Link href="/cases/new?mode=first">내 조건 입력하기 <ArrowRight /></Link>
      </section>

      <footer className="home-footer">
        <div className="home-brand"><span className="brand-symbol" aria-hidden="true" /><span className="wordmark-partner">KB부동산 ×</span><strong>자리매김</strong></div>
        <p>공개데이터 기반 참고정보로 금융 승인, 매출 또는 지원사업 선정을 보장하지 않습니다.</p>
        <Link href="/privacy-policy">개인정보·서비스 원칙</Link>
      </footer>
    </main>
  );
}
