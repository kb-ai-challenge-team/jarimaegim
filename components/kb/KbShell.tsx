"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell, Building2, CalendarDays, ChevronDown, Gavel, Home, Layers, LayoutGrid, Locate, MapPin, Menu, MessageSquare, Minus, Plus, Ruler, ScrollText, Search, SlidersHorizontal, Star, TrendingUp, UserRound } from "lucide-react";
import { useJarimaegim } from "@/lib/use-jarimaegim";
import { JarimaegimPanel } from "./JarimaegimPanel";
import { KbMap } from "./KbMap";
import { KbTodayPanel } from "./KbTodayPanel";

const GNB = [
  { id: "home", label: "우리집", icon: UserRound }, { id: "map", label: "지도", icon: Layers },
  { id: "today", label: "오늘", icon: CalendarDays }, { id: "sale", label: "분양", icon: Building2 },
  { id: "community", label: "커뮤니티", icon: MessageSquare }, { id: "menu", label: "메뉴", icon: Menu }
];
const FILTERS = ["아파트 +2", "매매 · 전세 · 월세", "가격", "면적"];
const TOOLS = [
  { id: "listing", label: "매물", icon: Home }, { id: "complex", label: "단지", icon: Building2 },
  { id: "location", label: "입지", icon: MapPin }, { id: "agency", label: "중개", icon: LayoutGrid },
  { id: "auction", label: "경매\n공매", icon: Gavel }, { id: "policy", label: "정책", icon: ScrollText },
  { id: "tools", label: "지도\n도구", icon: Ruler }, { id: "price", label: "시세\n평균", icon: TrendingUp }
];

export function KbShell() {
  const flow = useJarimaegim();
  const [aiOpen, setAiOpen] = useState(false);
  const [toast, setToast] = useState("");
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const notify = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 2600);
  }, []);
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);
  const outOfScope = useCallback((label: string) => notify(`${label.replace("\n", " ")}은(는) 이 데모의 범위가 아닙니다. 자리매김 AI 기능만 동작합니다.`), [notify]);

  return <div className="kb-app" data-ai={aiOpen ? "open" : "closed"}>
    <nav className="kb-gnb" aria-label="KB부동산 주요 메뉴">
      <span className="kb-logo" aria-label="KB부동산">KB</span>
      {GNB.map(({ id, label, icon: Icon }) => <button key={id} type="button" aria-current={id === "today" ? "page" : undefined} onClick={() => id !== "today" && outOfScope(label)}>
        <Icon aria-hidden="true" /><span>{label}</span>
      </button>)}
    </nav>

    <div className="kb-panel">
      <div className="kb-search">
        <Search aria-hidden="true" />
        <input placeholder="지역, 단지, 학교명을 검색해 보세요" aria-label="KB부동산 검색" onFocus={() => outOfScope("통합 검색")} readOnly />
        <button className="kb-search-ai" onClick={() => setAiOpen(true)} aria-label="자리매김 AI 열기"><span className="kb-ai-badge" aria-hidden="true">AI</span></button>
        <button className="kb-icon-button" aria-label="알림" onClick={() => outOfScope("알림")}><Bell aria-hidden="true" /></button>
      </div>
      {aiOpen ? <JarimaegimPanel flow={flow} onClose={() => setAiOpen(false)} /> : <KbTodayPanel onOpenAi={() => setAiOpen(true)} />}
    </div>

    <main className="kb-stage" id="main-content">
      <KbMap candidates={aiOpen ? flow.candidates : []} focused={flow.focused} onFocus={flow.setFocused} aiActive={aiOpen} />

      <div className="kb-filters">
        <button className="kb-filter-icon" aria-label="필터 설정" onClick={() => outOfScope("필터")}><SlidersHorizontal aria-hidden="true" /></button>
        <button className="kb-filter-icon" aria-label="관심 목록" onClick={() => outOfScope("관심 목록")}><Star aria-hidden="true" /></button>
        {FILTERS.map((filter) => <button key={filter} className="kb-filter" onClick={() => outOfScope(filter)}>{filter} <ChevronDown aria-hidden="true" /></button>)}
      </div>

      <div className="kb-tools" role="toolbar" aria-label="지도 도구">
        {TOOLS.map(({ id, label, icon: Icon }) => <button key={id} type="button" onClick={() => outOfScope(label)}>
          <Icon aria-hidden="true" /><span>{label}</span>
        </button>)}
        <button type="button" className="kb-tool-ai" aria-pressed={aiOpen} onClick={() => setAiOpen(!aiOpen)}>
          <span className="kb-ai-badge" aria-hidden="true">AI</span><span>자리매김</span>
        </button>
      </div>

      <div className="kb-map-controls">
        <button aria-label="현재 위치" onClick={() => outOfScope("현재 위치")}><Locate aria-hidden="true" /></button>
        <button aria-label="확대" onClick={() => outOfScope("지도 확대 버튼")}><Plus aria-hidden="true" /></button>
        <button aria-label="축소" onClick={() => outOfScope("지도 축소 버튼")}><Minus aria-hidden="true" /></button>
      </div>

      {!aiOpen && <div className="kb-stage-notice"><strong>매물·시세 데이터는 표시하지 않습니다</strong><p>KB부동산 API가 연동되지 않아 값을 만들어 채우지 않습니다. 우측 <em>자리매김 AI</em>를 눌러 창업 입지 추천을 확인해 보세요.</p></div>}
    </main>

    {toast && <div className="kb-toast" role="status">{toast}</div>}
  </div>;
}
