const CANDIDATES = [
  {
    id: "yeonnam",
    name: "연남 생활권",
    district: "마포구 연남동 · 도보 10분",
    evidence: "상권 위험 진단",
    evidenceClass: "risk",
    x: 35,
    y: 35,
    demand: "주말 유입 강함",
    budgetFit: "비용 확인 필요",
    positive: "여가 목적 유입과 대중교통 접근이 함께 관측됩니다.",
    risk: "동종 업종 밀도가 높아 메뉴·시간대 차별화 확인이 필요합니다.",
    conclusion: "유입 신호는 뚜렷하지만 경쟁 밀도가 높습니다. 임차 조건을 직접 확인한 뒤 계획 후보로 확정하세요.",
    axes: [
      ["수요", "유리", "good", "주말·저녁 생활인구 유입이 비교 생활권보다 높음"],
      ["경쟁", "주의", "caution", "동종 업종 밀도가 비교 생활권 상위권"],
      ["비용", "미확인", "unknown", "공식 임대 비용 자료가 충분하지 않아 직접 입력 필요"],
      ["접근성", "유리", "good", "철도역과 버스 정류장 보행 접근 양호"],
      ["지속성", "확인", "caution", "계절·주말 수요 편차를 운영계획에서 확인 필요"]
    ],
    positives: ["여가·주거 목적 방문이 함께 관측됨", "저녁 시간대 생활인구 흐름이 유지됨"],
    risks: ["동종 카페 밀집 구간 존재", "임차비는 공식 자료로 확인할 수 없음"]
  },
  {
    id: "mangwon",
    name: "망원 생활권",
    district: "마포구 망원동 · 도보 10분",
    evidence: "입지 환경 신호",
    evidenceClass: "context",
    x: 62,
    y: 57,
    demand: "생활 수요 안정",
    budgetFit: "직접 입력 필요",
    positive: "주거 배후와 반복 방문을 기대할 수 있는 생활권 신호가 있습니다.",
    risk: "시장·관광 유입과 일상 수요의 시간대 차이가 큽니다.",
    conclusion: "반복 방문에 유리한 생활권 신호가 있습니다. 다만 현재 공개자료만으로 개별 점포 결과를 판단할 수 없습니다.",
    axes: [
      ["수요", "안정", "good", "주거 배후의 평일 생활인구 흐름이 비교적 일정"],
      ["경쟁", "확인", "caution", "상권 경계에 따라 동종 업종 집계 차이 존재"],
      ["비용", "미확인", "unknown", "사용자 입력 전에는 예산 적합성을 계산하지 않음"],
      ["접근성", "보통", "good", "생활권 중심부 보행 접근이 확인됨"],
      ["지속성", "유리", "good", "주거 기반 반복 수요 신호가 관측됨"]
    ],
    positives: ["주거 기반 반복 수요", "평일과 주말의 수요원이 분산됨"],
    risks: ["세부 블록별 유동 차이", "개별 점포 이력 기반 분석은 제공하지 않음"]
  },
  {
    id: "hapjeong",
    name: "합정역 동측",
    district: "마포구 합정동 · 도보 10분",
    evidence: "상권 위험 진단",
    evidenceClass: "risk",
    x: 72,
    y: 30,
    demand: "환승 유입 관측",
    budgetFit: "비용 주의",
    positive: "환승과 업무·여가 이동이 겹치는 유입 신호가 있습니다.",
    risk: "고정비와 경쟁 수준을 함께 확인해야 하는 구간입니다.",
    conclusion: "접근성은 강점이지만 경쟁과 비용 부담이 함께 예상됩니다. 비교 후보의 기준일 차이를 먼저 확인하세요.",
    axes: [
      ["수요", "유리", "good", "환승 기반 유입 신호가 비교 생활권보다 높음"],
      ["경쟁", "주의", "caution", "카페·음식 업종 집적도가 높음"],
      ["비용", "주의", "caution", "공개 비용 신호는 있으나 실제 계약 조건 확인 필요"],
      ["접근성", "유리", "good", "철도 환승과 간선버스 접근 우수"],
      ["지속성", "확인", "caution", "업무·여가 수요 변화 영향 확인 필요"]
    ],
    positives: ["광역 대중교통 접근", "다양한 방문 목적이 겹침"],
    risks: ["높은 동종 경쟁 신호", "후보별 데이터 기준일 일부 차이"]
  }
];

const PROFILE_LABELS = {
  industry: value => value,
  area: value => value.replace("서울 ", ""),
  budget: value => `예산 ${formatMoney(value)}`,
  capital: value => `자기자본 ${formatMoney(value)}`,
  businessStage: value => value,
  startupType: value => `${value} 창업`
};

const state = {
  stage: "explore",
  analysisMode: "single",
  planTab: "cost",
  mobileView: "explore",
  copilotOpen: false,
  focused: "yeonnam",
  compared: new Set(["yeonnam", "mangwon"]),
  committed: null,
  pendingCommit: null,
  walking: 10,
  dirtyAnalysis: false,
  changeProposal: true,
  profile: {
    industry: "카페",
    area: "서울 마포구",
    budget: 12000,
    capital: 8000,
    businessStage: "예비 창업",
    startupType: "개인",
    goal: "안정성"
  },
  messages: [
    { role: "assistant", text: "마포구 카페 조건으로 생활권 3곳을 정리했습니다. 핀이나 목록을 한 번 선택하면 미리보기만 바뀌고, 비교 후보는 유지됩니다.", citation: true },
    { role: "assistant", text: "연남 생활권은 수요 신호와 경쟁 주의가 함께 보입니다. 보행 범위를 넓혀 인접 생활권까지 볼 수 있어요." }
  ],
  tasks: new Set(["source"])
};

const els = {
  app: document.getElementById("app"),
  canvas: document.getElementById("canvas"),
  canvasNav: document.getElementById("canvasNav"),
  contextChips: document.getElementById("contextChips"),
  caseTitle: document.getElementById("caseTitle"),
  saveState: document.getElementById("saveState"),
  compareTray: document.getElementById("compareTray"),
  copilotContext: document.getElementById("copilotContext"),
  workStatusLabel: document.getElementById("workStatusLabel"),
  workStatusSteps: document.getElementById("workStatusSteps"),
  messageList: document.getElementById("messageList"),
  changeProposal: document.getElementById("changeProposal"),
  quickActions: document.getElementById("quickActions"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  conditionDialog: document.getElementById("conditionDialog"),
  conditionForm: document.getElementById("conditionForm"),
  evidenceDialog: document.getElementById("evidenceDialog"),
  evidenceSubtitle: document.getElementById("evidenceSubtitle"),
  evidenceBody: document.getElementById("evidenceBody"),
  loginDialog: document.getElementById("loginDialog"),
  toast: document.getElementById("toast"),
  decisionTrace: document.getElementById("decisionTrace")
};

function escapeHTML(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function formatMoney(value) {
  const number = Number(value || 0);
  if (number >= 10000) return `${(number / 10000).toFixed(number % 10000 ? 1 : 0)}억 원`;
  return `${number.toLocaleString("ko-KR")}만 원`;
}

function candidateById(id) {
  return CANDIDATES.find(candidate => candidate.id === id) || CANDIDATES[0];
}

function render() {
  renderShell();
  renderContext();
  renderNav();
  renderCanvas();
  renderCompareTray();
  renderCopilot(false);
  renderMobileSwitcher();
}

function renderShell() {
  els.app.classList.toggle("copilot-collapsed", !state.copilotOpen);
  els.app.dataset.mobileView = state.mobileView;
  els.caseTitle.value = `${state.profile.area.replace("서울 ", "")} ${state.profile.industry} ${state.profile.businessStage === "예비 창업" ? "첫 창업" : "이전·확장"}`;
  document.querySelectorAll('[data-action="toggle-copilot"][aria-expanded]').forEach(button => button.setAttribute("aria-expanded", String(state.copilotOpen)));
  document.querySelectorAll("[data-rail-stage]").forEach(button => {
    if (button.dataset.railStage === state.stage) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function renderContext() {
  const entries = ["industry", "area", "budget", "capital", "businessStage", "startupType"];
  els.contextChips.innerHTML = entries.map(key => `<span class="context-chip" data-context-key="${key}">${escapeHTML(PROFILE_LABELS[key](state.profile[key]))}</span>`).join("") + `<span class="context-chip" data-context-key="walking">보행 ${state.walking}분</span>`;
}

function renderNav() {
  const tabs = [
    ["explore", "탐색"],
    ["analysis", "분석"],
    ["plan", "계획"],
    ["execution", "실행"]
  ];
  const status = state.dirtyAnalysis ? "조건 변경됨 · 분석 갱신 필요" : `후보 ${state.compared.size}곳 비교 중 · 근거 확인됨`;
  els.canvasNav.innerHTML = tabs.map(([id, label]) => `<button class="canvas-tab" type="button" data-action="go-stage" data-stage="${id}" ${state.stage === id ? 'aria-current="page"' : ""}>${label}</button>`).join("") + `<span class="canvas-status">${status}</span>`;
}

function renderCanvas() {
  const views = { explore: renderExplore, analysis: renderAnalysis, plan: renderPlan, execution: renderExecution };
  els.canvas.innerHTML = views[state.stage]();
}

function mapArtwork() {
  return `<div class="map-base"></div>
    <svg class="map-roads" viewBox="0 0 800 620" preserveAspectRatio="none" aria-hidden="true">
      <path class="river" d="M-40 510 C150 430 220 530 420 450 S670 350 860 410"/>
      <path d="M40 110 C220 180 280 100 450 180 S650 260 820 170"/>
      <path d="M160 -20 C200 140 130 280 260 410 S430 560 500 650"/>
      <path d="M600 -20 C520 120 570 250 490 360 S380 500 340 650"/>
      <path class="minor" d="M-20 250 C180 310 260 210 410 270 S650 340 840 290"/>
      <path class="minor" d="M20 50 L740 560"/><path class="minor" d="M740 40 L80 590"/>
    </svg>
    <span class="map-label" style="left:14%;top:19%">연남동</span><span class="map-label" style="right:13%;top:20%">합정동</span><span class="map-label" style="left:51%;bottom:17%">망원동</span>
    <span class="ambient-marker" style="left:49%;top:22%">서교 · 비교 가능</span>
    <span class="ambient-marker" style="left:84%;top:48%">상수 · 자료 확인</span>
    <span class="ambient-marker" style="left:48%;top:74%">성산 · 기준 다름</span>
    <span class="ambient-marker" style="left:22%;top:69%">신촌 · 자료 확인</span>
    <span class="ambient-marker" style="left:86%;top:73%">공덕 · 비교 가능</span>`;
}

function renderExplore() {
  const focused = candidateById(state.focused);
  return `<section class="explore-view" aria-labelledby="exploreTitle">
    <div class="candidate-list">
      <header class="list-heading"><div><span class="section-label">MAP RESULTS</span><h1 id="exploreTitle">조건에 맞는 생활권</h1><p>후보 선택은 미리보기만 바꾸며 비교 목록은 유지됩니다.</p></div><button class="filter-button" type="button" data-action="show-filter" aria-label="후보 필터">＋</button></header>
      <div class="active-filter"><span class="filter-pill">${escapeHTML(state.profile.goal)} 우선</span><span class="filter-pill">보행 ${state.walking}분</span><span class="filter-pill">근거 확인</span></div>
      ${CANDIDATES.map((candidate, index) => renderCandidateCard(candidate, index)).join("")}
    </div>
    <div class="map-panel" aria-label="마포구 생활권 후보 지도 모형">
      ${mapArtwork()}
      <div class="map-toolbar"><span class="map-note">공개데이터 <strong>2025 Q4 · 생활권 집계</strong></span><button class="map-research" type="button" data-action="research-area">이 영역에서 다시 찾기</button></div>
      ${CANDIDATES.map((candidate, index) => `<button class="map-pin ${state.focused === candidate.id ? "focused" : ""}" type="button" style="left:${candidate.x}%;top:${candidate.y}%" data-action="focus-candidate" data-id="${candidate.id}" aria-label="${escapeHTML(candidate.name)} 미리보기"><span>${index + 1} ${escapeHTML(candidate.name.replace(" 생활권", ""))}</span></button>`).join("")}
      <aside class="map-tool-rail" aria-label="지도 도구"><button type="button" data-action="show-filter"><span aria-hidden="true">☷</span>필터</button><button type="button" data-action="research-area"><span aria-hidden="true">◎</span>재검색</button><button type="button" data-action="open-evidence"><span aria-hidden="true">i</span>출처</button><button class="ai-tool" type="button" data-action="toggle-copilot"><span aria-hidden="true">AI</span>대화</button></aside>
      ${renderPreview(focused)}
    </div>
  </section>`;
}

function renderCandidateCard(candidate, index) {
  const compared = state.compared.has(candidate.id);
  return `<article class="candidate-card ${state.focused === candidate.id ? "focused" : ""}">
    <button class="candidate-focus" type="button" data-action="focus-candidate" data-id="${candidate.id}" aria-pressed="${state.focused === candidate.id}">
      <div class="candidate-top"><span class="rank">${index + 1}</span><span class="evidence-label ${candidate.evidenceClass === "context" ? "context" : ""}">${escapeHTML(candidate.evidence)}</span></div>
      <h2>${escapeHTML(candidate.name)}</h2><span class="district">${escapeHTML(candidate.district)}</span>
      <div class="signal-grid"><div class="signal"><span>수요 신호</span><strong>${escapeHTML(candidate.demand)}</strong></div><div class="signal"><span>예산 검토</span><strong>${escapeHTML(candidate.budgetFit)}</strong></div></div>
      <p class="reason"><span class="symbol">+</span>${escapeHTML(candidate.positive)}</p><p class="reason risk"><span class="symbol">!</span>${escapeHTML(candidate.risk)}</p>
    </button>
    <div class="candidate-actions"><button class="compare-toggle ${compared ? "on" : ""}" type="button" data-action="toggle-compare" data-id="${candidate.id}">${compared ? "비교에서 제거" : "비교에 추가"}</button><button class="detail-link" type="button" data-action="open-analysis" data-id="${candidate.id}">분석 보기 →</button></div>
  </article>`;
}

function renderPreview(candidate) {
  const compared = state.compared.has(candidate.id);
  const confirm = state.pendingCommit === candidate.id ? `<div class="commit-confirm"><p><strong>${escapeHTML(candidate.name)}</strong>을 비용·자금 계획의 기준으로 사용합니다. 비교 후보는 유지됩니다.</p><div class="proposal-actions"><button class="small-primary" type="button" data-action="confirm-commit" data-id="${candidate.id}">확정</button><button class="small-quiet" type="button" data-action="cancel-commit">취소</button></div></div>` : "";
  return `<aside class="candidate-preview" aria-label="선택 후보 미리보기"><div class="preview-head"><div><span class="section-label">FOCUSED CANDIDATE</span><h3>${escapeHTML(candidate.name)}</h3></div><span class="evidence-label ${candidate.evidenceClass === "context" ? "context" : ""}">${escapeHTML(candidate.evidence)}</span></div><p class="preview-copy">${escapeHTML(candidate.conclusion)}</p><div class="preview-actions"><button class="detail" type="button" data-action="open-analysis" data-id="${candidate.id}">분석 자세히</button><button class="compare" type="button" data-action="toggle-compare" data-id="${candidate.id}">${compared ? "비교 제거" : "비교 추가"}</button><button class="commit" type="button" data-action="request-commit" data-id="${candidate.id}">${state.committed === candidate.id ? "계획 기준으로 사용 중" : "이 후보로 계획하기"}</button></div>${confirm}</aside>`;
}

function renderAnalysis() {
  const candidate = candidateById(state.focused);
  if (state.analysisMode === "compare" && state.compared.size > 1) return renderComparison(candidate);
  return renderSingleAnalysis(candidate);
}

function renderSingleAnalysis(candidate) {
  return `<section class="content-view" aria-labelledby="analysisTitle">
    <header class="view-heading"><div><span class="section-label">EXPLAINABLE ANALYSIS</span><h1 id="analysisTitle">${escapeHTML(candidate.name)} 분석</h1><p>${escapeHTML(candidate.district)} · ${escapeHTML(state.profile.industry)} · ${state.dirtyAnalysis ? "조건 변경 후 갱신 필요" : "분석 최신"}</p></div><div class="heading-actions"><button class="quiet-button" type="button" data-action="go-stage" data-stage="explore">후보 다시 보기</button><button class="primary-button" type="button" data-action="request-commit" data-id="${candidate.id}">이 후보로 계획하기</button></div></header>
    ${state.dirtyAnalysis ? `<div class="comparison-warning" role="status">조건이 변경되어 이전 분석을 유지하고 있습니다. 새 분석을 요청하기 전까지 수치를 새로 만들지 않습니다. <button class="text-button" data-action="refresh-analysis">분석 다시 요청하기</button></div>` : ""}
    <div class="analysis-lead"><article class="conclusion-panel"><span class="evidence-label">${escapeHTML(candidate.evidence)}</span><h2>지금 알아야 할 결론</h2><p>${escapeHTML(candidate.conclusion)}</p><ul class="conclusion-list"><li>개별 점포 결과를 자동으로 만들지 않습니다.</li><li>비용은 사용자가 확인한 계약 조건으로만 확정합니다.</li></ul></article><article class="analysis-panel"><h2>다섯 가지 판단 근거</h2><p class="panel-note">관측 가능한 방향과 한계를 항목별로 표시합니다.</p>${candidate.axes.map(axis => `<div class="axis-row"><strong>${axis[0]}</strong><span class="axis-state ${axis[2]}">${axis[1]}</span><span class="axis-evidence">${escapeHTML(axis[3])}</span></div>`).join("")}<div class="provenance-bar">서울 상권분석 · 2025 Q4 · 생활권×업종 집계 <button type="button" data-action="open-evidence" data-id="${candidate.id}">근거 보기</button></div></article></div>
    <div class="insight-columns"><article class="section-panel"><h2>긍정 신호</h2><ul class="insight-list">${candidate.positives.map(item => `<li>${escapeHTML(item)}</li>`).join("")}</ul></article><article class="section-panel"><h2>주의·결측</h2><ul class="insight-list risk">${candidate.risks.map(item => `<li>${escapeHTML(item)}</li>`).join("")}</ul></article></div>
  </section>`;
}

function renderComparison() {
  const candidates = [...state.compared].map(candidateById);
  const metrics = ["수요", "경쟁", "비용", "접근성", "지속성"];
  return `<section class="content-view" aria-labelledby="comparisonTitle"><header class="view-heading"><div><span class="section-label">CANDIDATE COMPARISON</span><h1 id="comparisonTitle">${candidates.length}곳을 근거별로 비교합니다</h1><p>후보마다 데이터 수준과 기준이 다르면 먼저 표시합니다.</p></div><button class="quiet-button" type="button" data-action="go-stage" data-stage="explore">지도에서 조정</button></header><div class="comparison-stack"><div class="comparison-warning"><strong>비교 조건 일부가 다릅니다.</strong> 합정역 동측은 일부 지표의 검증 시점이 달라 막대 길이로 직접 비교하지 않습니다.</div>${metrics.map((metric, metricIndex) => `<section class="section-panel metric-section"><h3>${metric}</h3>${candidates.map(candidate => { const axis = candidate.axes[metricIndex]; return `<div class="metric-candidate"><strong>${escapeHTML(candidate.name)}</strong><span class="axis-state ${axis[2]}">${axis[1]} · 2025 Q4</span><span>${escapeHTML(axis[3])}</span></div>`; }).join("")}</section>`).join("")}</div></section>`;
}

function renderPlan() {
  const tabs = [["cost", "비용"], ["funding", "자금"], ["documents", "문서"]];
  return `<section class="content-view" aria-labelledby="planTitle"><header class="view-heading"><div><span class="section-label">PLAN WITH EVIDENCE</span><h1 id="planTitle">${state.committed ? escapeHTML(candidateById(state.committed).name) : "후보 미확정"} 계획</h1><p>${state.committed ? "확정한 후보를 기준으로 입력값과 공식자료를 분리합니다." : "탐색에서 계획 기준 후보를 먼저 확정해 주세요."}</p></div>${!state.committed ? `<button class="primary-button" type="button" data-action="go-stage" data-stage="explore">후보 선택하기</button>` : ""}</header><div class="local-tabs" role="tablist">${tabs.map(([id,label]) => `<button class="local-tab" type="button" role="tab" aria-selected="${state.planTab === id}" data-action="plan-tab" data-tab="${id}">${label}</button>`).join("")}</div>${renderPlanTab()}</section>`;
}

function renderPlanTab() {
  if (state.planTab === "funding") return renderFunding();
  if (state.planTab === "documents") return renderDocuments();
  const rows = [
    ["임차보증금", "직접 입력 필요", "사용자 입력", "user"],
    ["권리금", "확인할 수 없음", "확인 불가", ""],
    ["인테리어·설비", "범위 입력 필요", "추정범위", "estimate"],
    ["초기 재고·운영", "범위 입력 필요", "추정범위", "estimate"],
    ["안전예비비", "사용자가 결정", "사용자 입력", "user"]
  ];
  return `<div class="cost-layout"><article class="section-panel table-scroll"><table class="cost-table"><thead><tr><th>비용 항목</th><th>값 또는 범위</th><th>출처 유형</th><th>행동</th></tr></thead><tbody>${rows.map(row => `<tr><th>${row[0]}</th><td>${row[1]}</td><td><span class="source-tag ${row[3]}">${row[2]}</span></td><td><button class="text-button" type="button" data-action="edit-cost">입력</button></td></tr>`).join("")}</tbody></table></article><aside class="section-panel summary-block"><span class="section-label">USER INPUT</span><h2>현재 자금 조건</h2><dl><div><dt>총예산</dt><dd>${formatMoney(state.profile.budget)}</dd></div><div><dt>자기자본</dt><dd>${formatMoney(state.profile.capital)}</dd></div><div><dt>소요자금 차이</dt><dd>계산 대기</dd></div></dl><p>확인되지 않은 금액은 자동으로 생성하지 않습니다. 비용을 입력하면 최소~최대 범위와 전제를 유지해 계산합니다.</p></aside></div>`;
}

function renderFunding() {
  const programs = [
    ["정부지원", "K-Startup 창업지원 공고", "창업진흥원", "공고 확인 필요", "지역·사업단계 조건 확인 전", "https://www.k-startup.go.kr/web/contents/bizPbanc-ongoing.do"],
    ["정책자금", "소상공인 정책자금", "소상공인시장진흥공단", "조건 확인 필요", "업력·사업자등록 시점 미확인", "https://ols.semas.or.kr/"],
    ["지역보증", "서울신용보증재단 창업지원", "서울신용보증재단", "공고 확인 필요", "보증 심사와 자격은 별도 확인", "https://www.seoulshinbo.co.kr/" ]
  ];
  return `<div class="program-list">${programs.map(program => `<article class="program-row"><span class="program-type">${program[0]}</span><div><h3>${program[1]}</h3><p>${program[2]}</p></div><p><span class="status-tag">${program[3]}</span><br>${program[4]}</p><a class="external-link" href="${program[5]}" target="_blank" rel="noreferrer">공식 원문 열기 ↗</a></article>`).join("")}</div>`;
}

function renderDocuments() {
  return `<div class="document-empty"><div><div class="empty-symbol">PDF</div><h2>아직 만든 문서가 없습니다</h2><p>문서 종류와 포함 정보를 검토한 뒤 로그인하면 생성할 수 있습니다. 출처와 비보장 고지는 미리보기에서 먼저 확인합니다.</p><button class="primary-button" type="button" data-action="open-login">PDF 준비하기</button></div></div>`;
}

function renderExecution() {
  const tasks = [
    ["source", "공식 상권 데이터 기준일 확인", "서울 상권분석 원천과 2025 Q4 검증 시점", "확인됨"],
    ["lease", "후보지 임차 조건 직접 확인", "보증금·권리금·관리비를 계약 전 입력", "직접 확인"],
    ["notice", "공식 지원공고 원문 열기", "지역·사업단계·사업자등록 시점 확인", "D-day 확인"],
    ["plan", "카페 사업계획 초안 검토", "AI 초안과 사용자 확정 내용을 구분", "준비 필요"]
  ];
  const progress = Math.round((state.tasks.size / tasks.length) * 100);
  return `<section class="content-view" aria-labelledby="executionTitle"><header class="view-heading"><div><span class="section-label">ACTION CHECKLIST</span><h1 id="executionTitle">다음 행동을 하나씩 확인합니다</h1><p>시스템이 확인한 항목과 사용자가 완료한 항목을 구분합니다.</p></div></header><div class="execution-grid"><article class="section-panel"><div class="checklist">${tasks.map(task => `<button class="check-item ${state.tasks.has(task[0]) ? "done" : ""}" type="button" data-action="toggle-task" data-id="${task[0]}"><span class="check-box">✓</span><span class="check-copy"><strong>${task[1]}</strong><span>${task[2]}</span></span><span class="check-due">${task[3]}</span></button>`).join("")}</div></article><aside><article class="section-panel progress-card"><span class="section-label">YOUR PROGRESS</span><div class="progress-number">${progress}%</div><div class="progress-track"><i style="width:${progress}%"></i></div><p>${state.tasks.size}개 확인 · ${tasks.length - state.tasks.size}개 남음</p></article></aside></div></section>`;
}

function renderCompareTray() {
  const candidates = [...state.compared].map(candidateById);
  els.compareTray.classList.toggle("visible", candidates.length > 0 && state.stage === "explore");
  els.compareTray.innerHTML = `<div class="tray-label"><strong>비교 ${candidates.length}곳</strong><span>최대 3곳</span></div><div class="tray-items">${candidates.map(candidate => `<span class="tray-item">${escapeHTML(candidate.name)}<button type="button" data-action="toggle-compare" data-id="${candidate.id}" aria-label="${escapeHTML(candidate.name)} 비교에서 제거">×</button></span>`).join("")}</div><button class="tray-cta" type="button" data-action="open-comparison">${candidates.length}곳 비교 보기</button>`;
}

function renderCopilot(preserveScroll = true) {
  const contextNames = { explore: "후보 탐색", analysis: state.compared.size > 1 ? "후보 비교" : "입지 분석", plan: "비용·자금 계획", execution: "실행 체크리스트" };
  els.copilotContext.textContent = `현재: ${contextNames[state.stage]}`;
  els.workStatusLabel.textContent = state.dirtyAnalysis ? "분석 갱신 대기" : "근거 확인 완료";
  els.workStatusSteps.innerHTML = `<span class="status-step done"></span><span class="status-step done"></span><span class="status-step ${state.dirtyAnalysis ? "current" : "done"}"></span>`;
  const nearBottom = els.messageList.scrollHeight - els.messageList.scrollTop - els.messageList.clientHeight < 56;
  const oldTop = els.messageList.scrollTop;
  els.messageList.innerHTML = state.messages.map(message => `<div class="message ${message.role}"><div class="message-bubble">${escapeHTML(message.text).replaceAll("\n", "<br>")}${message.citation ? `<button class="message-citation" type="button" data-action="open-evidence" aria-label="근거 1 보기">[1]</button>` : ""}<span class="message-meta">${message.role === "assistant" ? "터닥터 AI" : "나"}</span></div></div>`).join("");
  if (preserveScroll && !nearBottom) els.messageList.scrollTop = oldTop;
  else els.messageList.scrollTop = els.messageList.scrollHeight;
  els.changeProposal.classList.toggle("hidden", !state.changeProposal);
  const actions = state.stage === "explore" ? [["비교 후보 설명", "ask-compare"], ["근거 수준 알려줘", "ask-evidence"], ["조건 수정", "open-conditions"]] : state.stage === "analysis" ? [["결측만 요약", "ask-missing"], ["지도에서 보기", "go-explore"], ["계획으로 이동", "go-plan"]] : [["다음 행동 요약", "ask-next"], ["공식 원문 보기", "go-funding"]];
  els.quickActions.innerHTML = actions.slice(0, 3).map(action => `<button class="quick-action" type="button" data-action="${action[1]}">${action[0]}</button>`).join("");
}

function renderMobileSwitcher() {
  document.querySelectorAll(".mobile-switcher button").forEach(button => button.setAttribute("aria-selected", String(button.dataset.view === state.mobileView)));
}

function focusCandidate(id) {
  state.focused = id;
  state.pendingCommit = null;
  renderCanvas();
  renderCompareTray();
}

function toggleCompare(id) {
  if (state.compared.has(id)) state.compared.delete(id);
  else if (state.compared.size < 3) state.compared.add(id);
  else {
    showToast("비교 후보는 최대 3곳입니다. 먼저 한 곳을 제거해 주세요.");
    return;
  }
  render();
}

function goStage(stage) {
  state.stage = stage;
  if (stage === "analysis") state.mobileView = "analysis";
  if (stage === "explore") state.mobileView = "explore";
  render();
  els.canvas.focus({ preventScroll: true });
}

function openAnalysis(id) {
  state.focused = id || state.focused;
  state.analysisMode = "single";
  goStage("analysis");
}

function requestCommit(id) {
  state.pendingCommit = id || state.focused;
  if (state.stage !== "explore") {
    state.focused = state.pendingCommit;
    state.stage = "explore";
  }
  render();
}

function confirmCommit(id) {
  const candidate = candidateById(id);
  state.committed = id;
  state.pendingCommit = null;
  state.stage = "plan";
  state.mobileView = "analysis";
  state.messages.push({ role: "assistant", text: `${candidate.name}을 계획 기준 후보로 확정했습니다. 비교 후보는 그대로 유지됩니다. 비용은 확인된 사용자 입력만 반영합니다.` });
  render();
  showToast(`${candidate.name}을 계획 기준으로 저장했습니다.`);
}

function applyChange() {
  const source = els.changeProposal;
  state.walking = 15;
  state.changeProposal = false;
  state.dirtyAnalysis = true;
  state.messages.push({ role: "assistant", text: "보행 범위를 15분으로 변경했습니다. 비교 후보는 유지했고, 이전 분석은 덮어쓰지 않았습니다." });
  render();
  const target = document.querySelector('[data-context-key="walking"]');
  if (target) {
    target.classList.add("updated");
    runDecisionTrace(source, target);
  }
  showToast("변경 1 적용 · 분석 갱신이 필요합니다.");
}

function runDecisionTrace(source, target) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || !source || !target) return;
  const a = source.getBoundingClientRect();
  const b = target.getBoundingClientRect();
  const x1 = a.left + a.width / 2;
  const y1 = a.top + a.height / 2;
  const x2 = b.left + b.width / 2;
  const y2 = b.top + b.height / 2;
  const distance = Math.hypot(x2 - x1, y2 - y1);
  const angle = Math.atan2(y2 - y1, x2 - x1) * 180 / Math.PI;
  Object.assign(els.decisionTrace.style, { left: `${x1}px`, top: `${y1}px`, width: `${distance}px`, transform: `rotate(${angle}deg)` });
  els.decisionTrace.classList.remove("running");
  requestAnimationFrame(() => els.decisionTrace.classList.add("running"));
  window.setTimeout(() => els.decisionTrace.classList.remove("running"), 650);
}

function refreshAnalysis() {
  state.dirtyAnalysis = false;
  state.messages.push({ role: "assistant", text: "변경된 보행 범위로 근거를 다시 확인했습니다. 비교 후보와 사용자가 입력한 조건은 유지했습니다." });
  render();
  showToast("분석 근거를 다시 확인했습니다.");
}

function openEvidence(id) {
  const candidate = candidateById(id || state.focused);
  els.evidenceSubtitle.textContent = `${candidate.name} · 서울 상권분석 · 2025 Q4`;
  els.evidenceBody.innerHTML = `<article class="evidence-item"><strong>원천과 공간 단위</strong><p>서울시 상권분석 공개자료를 생활권×업종 단위로 정리한 화면 예시입니다. 개별 점포 이력과 임대 계약 자료는 포함하지 않습니다.</p></article><article class="evidence-item"><strong>기준일과 검증 상태</strong><p>화면 기준일 2025 Q4 · 검증일 2026-07-19. 실제 서비스에서는 수집일·게시일·검증일을 분리합니다.</p></article><article class="evidence-item"><strong>표현 가능한 범위</strong><p>${escapeHTML(candidate.evidence)} 수준의 수요·경쟁·접근성 신호만 설명합니다. 개별 점포의 결과나 금융 승인, 매출을 보장하지 않습니다.</p></article>`;
  els.evidenceDialog.showModal();
}

function saveConditions(event) {
  event.preventDefault();
  const formData = new FormData(els.conditionForm);
  state.profile.industry = formData.get("industry").trim();
  state.profile.area = formData.get("area");
  state.profile.budget = Number(formData.get("budget"));
  state.profile.capital = Number(formData.get("capital"));
  state.profile.businessStage = formData.get("businessStage");
  state.profile.startupType = formData.get("startupType");
  state.dirtyAnalysis = true;
  state.committed = null;
  state.messages.push({ role: "assistant", text: "여섯 조건의 사용자 편집값을 반영했습니다. 기존 비교 후보는 유지하고 분석은 갱신 대기로 표시했습니다." });
  els.conditionDialog.close();
  render();
  showToast("조건을 저장했습니다. 분석 갱신이 필요합니다.");
}

function mobileView(view) {
  state.mobileView = view;
  if (view === "explore") state.stage = "explore";
  if (view === "analysis" && state.stage === "explore") state.stage = "analysis";
  if (view === "conversation") state.copilotOpen = true;
  render();
}

function processMessage(text) {
  state.messages.push({ role: "user", text });
  let reply = "현재 화면의 후보, 근거, 비용 입력 또는 공식 공고 확인에 대해 설명할 수 있습니다.";
  if (/비교|차이/.test(text)) reply = "연남은 유입과 경쟁이 함께 강하고, 망원은 생활 수요가 비교적 안정적입니다. 데이터 수준이 달라 단일 점수로 합치지 않았습니다.";
  else if (/근거|출처/.test(text)) reply = "현재 화면은 서울 상권분석의 생활권×업종 집계 예시를 사용합니다. 개별 점포 이력과 임대 계약 자료는 포함하지 않습니다.";
  else if (/비용|예산/.test(text)) reply = "총예산과 자기자본은 사용자 입력입니다. 보증금·권리금 등 확인되지 않은 비용은 자동 생성하지 않고 직접 입력을 기다립니다.";
  else if (/자금|지원/.test(text)) reply = "정부지원, 정책자금, 지역보증 순으로 공식 원문을 확인할 수 있습니다. 자격 또는 승인 결과를 단정하지 않습니다.";
  state.messages.push({ role: "assistant", text: reply, citation: /근거|출처/.test(text) });
  renderCopilot(true);
}

function showToast(message) {
  els.toast.textContent = message;
  els.toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.remove("visible"), 2200);
}

function handleAction(action, target, event) {
  const { id, stage, view, tab } = target.dataset;
  if (action === "focus-candidate") focusCandidate(id);
  else if (action === "toggle-compare") toggleCompare(id);
  else if (action === "open-analysis") openAnalysis(id);
  else if (action === "open-comparison") { state.analysisMode = "compare"; goStage("analysis"); }
  else if (action === "go-stage") goStage(stage);
  else if (action === "request-commit") requestCommit(id);
  else if (action === "confirm-commit") confirmCommit(id);
  else if (action === "cancel-commit") { state.pendingCommit = null; renderCanvas(); }
  else if (action === "plan-tab") { state.planTab = tab; renderCanvas(); }
  else if (action === "toggle-task") { state.tasks.has(id) ? state.tasks.delete(id) : state.tasks.add(id); renderCanvas(); }
  else if (action === "toggle-copilot") { state.copilotOpen = !state.copilotOpen; render(); }
  else if (action === "apply-change") applyChange();
  else if (action === "dismiss-change") { state.changeProposal = false; renderCopilot(); showToast("변경 제안을 취소했습니다."); }
  else if (action === "refresh-analysis") refreshAnalysis();
  else if (action === "open-evidence") openEvidence(id);
  else if (action === "close-evidence") els.evidenceDialog.close();
  else if (action === "open-conditions") els.conditionDialog.showModal();
  else if (action === "save-conditions") saveConditions(event);
  else if (action === "mobile-view") mobileView(view);
  else if (action === "open-login") els.loginDialog.showModal();
  else if (action === "close-login") els.loginDialog.close();
  else if (action === "mock-login") { els.loginDialog.close(); showToast("데모에서는 로그인을 전송하지 않습니다."); }
  else if (action === "research-area") showToast("비교 후보를 유지한 채 현재 영역을 다시 확인합니다.");
  else if (action === "show-filter") showToast("기본 필터: 분석 가능 · 예산 적합성 · 상권유형 · 보행범위");
  else if (action === "edit-cost") showToast("실서비스에서는 숫자·단위·출처를 함께 입력합니다.");
  else if (action === "ask-compare") processMessage("비교 후보의 차이를 설명해줘");
  else if (action === "ask-evidence") processMessage("근거 수준과 출처를 알려줘");
  else if (action === "ask-missing") processMessage("확인하지 못한 정보만 알려줘");
  else if (action === "go-explore") goStage("explore");
  else if (action === "go-plan") goStage("plan");
  else if (action === "ask-next") processMessage("다음 행동을 요약해줘");
  else if (action === "go-funding") { state.stage = "plan"; state.planTab = "funding"; render(); }
}

document.addEventListener("click", event => {
  const target = event.target.closest("[data-action]");
  if (target) handleAction(target.dataset.action, target, event);
});

document.getElementById("searchForm").addEventListener("submit", event => {
  event.preventDefault();
  const query = els.caseTitle.value.trim();
  if (!query) return;
  showToast(`“${query}” 조건으로 현재 지도를 확인합니다.`);
});

els.chatForm.addEventListener("submit", event => {
  event.preventDefault();
  const text = els.chatInput.value.trim();
  if (!text) return;
  els.chatInput.value = "";
  processMessage(text);
});

els.chatInput.addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});

els.evidenceDialog.addEventListener("click", event => {
  if (event.target === els.evidenceDialog) els.evidenceDialog.close();
});

window.addEventListener("resize", () => {
  if (window.innerWidth < 768 && state.mobileView !== "conversation") state.copilotOpen = false;
  renderShell();
});

window.__TER_DOCTOR_DEMO__ = {
  getState: () => ({ ...state, compared: [...state.compared], tasks: [...state.tasks] }),
  focusCandidate,
  toggleCompare,
  goStage,
  applyChange,
  refreshAnalysis
};

render();
