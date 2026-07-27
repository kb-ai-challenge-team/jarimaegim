"use client";

import Image from "next/image";
import Link from "next/link";
import {
  ArrowRight,
  Building2,
  Check,
  ChevronRight,
  Database,
  FileCheck2,
  LayoutDashboard,
  MapPinned,
  ShieldCheck,
  Store,
} from "lucide-react";

import { BrandLockup } from "@/components/BrandLockup";

export function Landing() {
  return (
    <main id="main-content" className="home-page">
      <header className="home-header">
        <div className="home-header-inner">
          <BrandLockup href="/" />
          <nav aria-label="보조 메뉴">
            <Link href="/kb" className="home-nav-link">연동 화면</Link>
            <Link href="/privacy-policy" className="home-nav-link">서비스 원칙</Link>
          </nav>
        </div>
      </header>

      <section className="home-hero" aria-labelledby="home-title">
        <div className="home-hero-copy">
          <BrandLockup size="lg" tagline />
          <h1 id="home-title">창업할 곳,<br />느낌보다 <em>근거로</em> 고르세요.</h1>
          <p className="home-lead">업종과 자금 조건을 입력하면 후보 입지, 비용, 공개 지원정보와 실행 계획을 하나의 판단 흐름으로 정리합니다.</p>

          <div className="home-hero-actions" aria-label="시작 유형 선택">
            <Link href="/kb" className="home-primary-action">
              <span className="home-action-icon" aria-hidden="true"><Store /></span>
              <span><small>별도 계정 없이 시작</small><strong>내 조건 입력하기</strong></span>
              <ArrowRight aria-hidden="true" />
            </Link>
            <Link href="/kb" className="home-secondary-action">
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

        {/* 손으로 그린 목업이 아니라 scripts/capture-hero-shot.mjs 가 실제 흐름을 돌려 캡처한 화면이다. */}
        <aside className="home-service-shot">
          <figure>
            <div className="home-shot-chrome" aria-hidden="true"><i /><i /><i /><span>자리매김 · 입지 추천</span></div>
            <Image src="/landing/service-screen.webp" width={1600} height={1000} priority sizes="(max-width:1099px) 92vw, 56vw" alt="자리매김이 KB부동산 화면 안에서 마포구 카페 조건에 맞는 후보 상가를 지도 마커와 목록으로 함께 보여주고, 후보마다 근거 등급과 출처를 붙인 실제 서비스 화면" />
            <figcaption>실제 서비스 화면입니다. 표시된 매물은 시연용 데이터이며 실제 임대 매물이 아닙니다.</figcaption>
          </figure>
          <ul className="home-shot-notes" aria-label="화면에서 확인할 수 있는 것">
            <li><ShieldCheck aria-hidden="true" /> 후보마다 근거 등급</li>
            <li><Database aria-hidden="true" /> 출처·기준일 표시</li>
          </ul>
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

      <section className="home-kb-demo" aria-labelledby="kb-demo-title">
        <div>
          <span className="home-section-label">화면 연동 시연</span>
          <h2 id="kb-demo-title">부동산 탐색 화면에서<br />이어서 검토합니다.</h2>
          <p>매물을 보던 화면 안에서 자리매김을 열어 조건과 근거를 확인하는 흐름을 시연합니다. 실제 제휴나 데이터 연동을 나타내지 않으며, 공개데이터로 확인할 수 있는 범위만 표시합니다.</p>
        </div>
        <Link href="/kb"><LayoutDashboard aria-hidden="true" /> 연동 화면 보기 <ArrowRight aria-hidden="true" /></Link>
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
        <Link href="/kb">내 조건 입력하기 <ArrowRight /></Link>
      </section>

      <footer className="home-footer">
        <BrandLockup />
        <p>공개데이터 기반 참고정보로 금융 승인, 매출 또는 지원사업 선정을 보장하지 않습니다.</p>
        <Link href="/privacy-policy">개인정보·서비스 원칙</Link>
      </footer>
    </main>
  );
}
