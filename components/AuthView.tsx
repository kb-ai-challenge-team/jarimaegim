"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Database, Mail, ShieldCheck, Sparkles } from "lucide-react";
import { getSupabaseBrowserClient } from "@/lib/supabase";

export function AuthView({ callbackError = false }: { callbackError?: boolean }) {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function magicLink() {
    const supabase = getSupabaseBrowserClient();
    if (!supabase) { setMessage("Supabase 환경변수를 설정하면 이메일 로그인을 사용할 수 있습니다."); return; }
    setBusy(true);
    const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: `${location.origin}/auth/callback` } });
    setMessage(error ? error.message : "이메일로 로그인 링크를 보냈습니다. 받은편지함을 확인해 주세요.");
    setBusy(false);
  }

  async function kakao() {
    const supabase = getSupabaseBrowserClient();
    if (!supabase) { setMessage("Supabase와 Kakao OAuth 환경변수를 먼저 설정해 주세요."); return; }
    setBusy(true);
    const { error } = await supabase.auth.signInWithOAuth({ provider: "kakao", options: { redirectTo: `${location.origin}/auth/callback` } });
    if (error) setMessage(error.message);
    setBusy(false);
  }

  const status = message || (callbackError ? "로그인을 완료하지 못했습니다. 인증 설정을 확인한 뒤 다시 시도해 주세요." : "");

  return <main id="main-content" className="auth-page">
    <section className="auth-context" aria-label="로그인 후 이용할 수 있는 기능">
      <Link href="/" className="wordmark"><span className="brand-symbol"></span><span className="wordmark-partner">KB부동산 ×</span><strong>자리매김</strong></Link>
      <div className="auth-context-copy"><span className="eyebrow">결정을 안전하게 이어가기</span><h1>내 창업 케이스를<br/>한곳에서 관리하세요.</h1><p>로그인 전 분석은 그대로 유지됩니다. 계정에는 사용자가 선택한 케이스와 문서만 연결합니다.</p></div>
      <div className="auth-trust-list">
        <article><Database/><div><strong>케이스 이어보기</strong><p>탐색 조건과 비교 후보, 계획 진행 상태를 보관합니다.</p></div></article>
        <article><ShieldCheck/><div><strong>비공개 문서</strong><p>생성한 PDF는 만료되는 다운로드 주소로만 제공합니다.</p></div></article>
        <article><Sparkles/><div><strong>설명 가능한 AI</strong><p>AI가 만든 설명과 공식 근거를 분리해 표시합니다.</p></div></article>
      </div>
      <p className="auth-boundary">공개데이터 기반 참고정보 · 금융 승인과 매출을 보장하지 않습니다.</p>
    </section>

    <section className="auth-panel">
      <div className="auth-card">
        <Link href="/" className="back-link"><ArrowLeft/> 처음으로</Link>
        <div className="login-mark"></div>
        <span className="eyebrow">분석은 로그인 없이 가능</span>
        <h2>케이스를 계속 보관하세요.</h2>
        <p>현재 브라우저에서 진행한 조건을 이어서 사용하고 PDF와 알림을 이용할 수 있습니다.</p>
        <ul>
          <li><CheckCircle2/>현재 브라우저의 익명 케이스 유지</li>
          <li><CheckCircle2/>비공개 PDF 생성 및 다운로드</li>
          <li><CheckCircle2/>언제든 개인정보 삭제 요청</li>
        </ul>
        <label><span>이메일</span><div className="email-input"><Mail/><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com"/></div></label>
        <button className="primary-button wide" disabled={!email || busy} onClick={magicLink}>이메일로 로그인 링크 받기</button>
        <div className="or"><span>또는</span></div>
        <button className="kakao-button" disabled={busy} onClick={kakao}>Kakao 계정으로 계속하기</button>
        {status && <div className="inline-alert" role="status">{status}</div>}
        <small>로그인하면 개인정보 처리방침과 서비스 이용 고지에 동의하게 됩니다.</small>
      </div>
    </section>
  </main>;
}
