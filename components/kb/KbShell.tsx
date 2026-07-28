"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, ChevronDown, Landmark, Locate, Minus, Plus, ScrollText, Search, SlidersHorizontal, Star, X } from "lucide-react";
import { useJarimaegim } from "@/lib/use-jarimaegim";
import { AgentRunOverlay } from "./AgentRunOverlay";
import { JarimaegimChat } from "./JarimaegimChat";
import { JarimaegimPanel } from "./JarimaegimPanel";
import { KbMap } from "./KbMap";
import { KbPolicyPanel } from "./KbPolicyPanel";
import { KbProductPanel } from "./KbProductPanel";

const FILTERS = ["아파트 +2", "매매 · 전세 · 월세", "가격", "면적"];
type View = "ai" | "policy" | "product";

export function KbShell() {
  const flow = useJarimaegim();
  const [view, setView] = useState<View>("ai");
  const [panelOpen, setPanelOpen] = useState(true);
  const [chatOpen, setChatOpen] = useState(true);
  const [toast, setToast] = useState("");
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aiActive = view === "ai";
  const chatVisible = aiActive && chatOpen;

  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 2600);
  }, []);
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);
  const outOfScope = useCallback((label: string) => notify(`${label}은(는) 이 데모의 범위가 아닙니다. 자리매김 AI 기능만 동작합니다.`), [notify]);

  /** KB-native GNB behaviour: tapping the active menu collapses the panel, tapping another switches it. */
  const selectView = useCallback((next: View) => {
    if (next === view) { setPanelOpen((open) => !open); return; }
    setView(next); setPanelOpen(true);
  }, [view]);

  const toggleChat = useCallback(() => {
    if (!aiActive) { setView("ai"); setChatOpen(true); return; }
    setChatOpen((open) => !open);
  }, [aiActive]);

  return <div className="kb-app" data-ai={aiActive ? "open" : "closed"} data-panel={panelOpen ? "open" : "closed"} data-chat={chatVisible ? "open" : "closed"}>
    <nav className="kb-gnb" aria-label="주요 메뉴">
      <span className="kb-logo" aria-label="KB 자리매김">KB</span>
      <button type="button" className="kb-gnb-ai" aria-current={aiActive && panelOpen ? "page" : undefined} aria-expanded={aiActive && panelOpen} onClick={() => selectView("ai")}>
        <span className="kb-ai-badge" aria-hidden="true">AI</span><span>자리매김</span>
      </button>
      <button type="button" aria-current={view === "policy" && panelOpen ? "page" : undefined} aria-expanded={view === "policy" && panelOpen} onClick={() => selectView("policy")}>
        <ScrollText aria-hidden="true" /><span>정책</span>
      </button>
      <button type="button" aria-current={view === "product" && panelOpen ? "page" : undefined} aria-expanded={view === "product" && panelOpen} onClick={() => selectView("product")}>
        <Landmark aria-hidden="true" /><span>상품</span>
      </button>
    </nav>

    {panelOpen && <div className="kb-panel">
      <div className="kb-search">
        <Search aria-hidden="true" />
        <input placeholder="지역, 단지, 학교명을 검색해 보세요" aria-label="KB부동산 검색" onFocus={() => outOfScope("통합 검색")} readOnly />
        <button className="kb-icon-button" aria-label="알림" onClick={() => outOfScope("알림")}><Bell aria-hidden="true" /></button>
      </div>
      {aiActive && <JarimaegimPanel flow={flow} onClose={() => setPanelOpen(false)} />}
      {view === "policy" && <KbPolicyPanel flow={flow} />}
      {view === "product" && <KbProductPanel flow={flow} />}
      {/* 자기자본은 form 이 아니라 금융 프로필이 소유한다. form.equity_krw 는 0 으로 남으므로
          start() 가 케이스에 싣는 값과 같은 출처에서 읽어 칩에 넘긴다. */}
      {aiActive && flow.traceOpen && <AgentRunOverlay trace={flow.trace} inputs={{ ...flow.form, equity_krw: flow.profile.equity_krw }} onRetry={flow.retrySearch} onDismiss={flow.dismissTrace}
        onEditConditions={() => { flow.dismissTrace(); flow.setStep("confirm"); }} />}
    </div>}

    <main className="kb-stage" id="main-content">
      <KbMap candidates={aiActive ? flow.candidates : []} summary={aiActive ? flow.summary : []} focused={flow.focused} onFocus={flow.setFocused} onSelectDistrict={flow.selectOverviewDistrict} aiActive={aiActive} />

      <div className="kb-filters">
        <button className="kb-filter-icon" aria-label="필터 설정" onClick={() => outOfScope("필터")}><SlidersHorizontal aria-hidden="true" /></button>
        <button className="kb-filter-icon" aria-label="관심 목록" onClick={() => outOfScope("관심 목록")}><Star aria-hidden="true" /></button>
        {FILTERS.map((filter) => <button key={filter} className="kb-filter" onClick={() => outOfScope(filter)}>{filter} <ChevronDown aria-hidden="true" /></button>)}
      </div>

      <div className="kb-map-controls">
        <button aria-label="현재 위치" onClick={() => outOfScope("현재 위치")}><Locate aria-hidden="true" /></button>
        <button aria-label="확대" onClick={() => outOfScope("지도 확대 버튼")}><Plus aria-hidden="true" /></button>
        <button aria-label="축소" onClick={() => outOfScope("지도 축소 버튼")}><Minus aria-hidden="true" /></button>
      </div>

      {flow.candidates.length === 0 && flow.summary.length > 0 && flow.trace.state !== "running" && <div className="kb-stage-notice"><strong>시연용 매물 데이터입니다</strong><p>실제 임대 매물이 아니며 계약 대상이 아닙니다. 지도의 자치구를 누르면 그 구의 매물을 볼 수 있고, 왼쪽 <em>자리매김</em>에서 조건을 입력하면 조건에 맞는 매물만 남습니다.</p></div>}
      {flow.candidates.length === 0 && flow.summary.length === 0 && flow.trace.state !== "running" && <div className="kb-stage-notice"><strong>매물 데이터를 불러오지 못했습니다</strong><p>연결을 확인한 뒤 새로고침해 주세요. 값을 만들어 채우지 않습니다.</p></div>}
      {flow.overviewDistrict && flow.candidates.length > 0 && <div className="kb-stage-notice compact"><strong>{flow.overviewDistrict} 시연용 매물 {flow.candidates.length}곳</strong><button type="button" className="kb-ghost" onClick={flow.clearOverviewDistrict}>전체 자치구 보기</button></div>}
    </main>

    {chatVisible && <JarimaegimChat flow={flow} />}

    <button type="button" className="kb-fab" aria-expanded={chatVisible} aria-label={chatVisible ? "자리매김 AI 대화 닫기" : "자리매김 AI 대화 열기"} onClick={toggleChat}>
      {chatVisible ? <X aria-hidden="true" /> : <><span className="kb-fab-badge" aria-hidden="true">AI</span><span className="kb-fab-label">대화</span></>}
    </button>

    {toast && <div className="kb-toast" role="status">{toast}</div>}
  </div>;
}
