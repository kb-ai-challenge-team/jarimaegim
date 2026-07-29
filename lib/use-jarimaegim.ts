"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { DEFAULT_BAND_FORM, DEFAULT_CASE, DEFAULT_PROFILE, PRIORITY_LABELS, PYEONG_IN_M2, formatKrw } from "./constants";
import { clearProfile, loadProfile, saveProfile, type Profile } from "./profile-storage";
import type { AgentProgress, AnalysisResult, BandLine, PrescribeResult, Candidate, CaseInput, CaseRecord, ChatToolActivity, Citation, ConditionInterpretResult, DistrictSummary, FundingBandResult, FundingCapacityResult, KbProduct, Program, StatusResponse } from "./types";

// 금융 프로필은 관문이 아니라 1단계다. 자기자본을 입력한 사용자는 그 자리에서 조달 여력을
// 돌려받고 단계를 끝낸다(capacity). 조건은 그다음 단계이며 금융 입력을 일절 받지 않는다.
// 최대 조달선은 프로필만으로 나오고 권장 조달선만 업종·월세를 요구한다 — 이 경계가 단계를 가른다.
// 옛 처방은 조달·서류로 갈라졌고 그 경계도 데이터가 정한다 — 부족분은 후보를 확정해야 확정되고,
// 조달에서 고른 수단은 서류가 만드는 문서의 내용을 바꾼다.
export type FlowStep = "profile" | "capacity" | "ask" | "confirm" | "recommend" | "funding" | "paperwork";
export type BandForm = typeof DEFAULT_BAND_FORM;
export type { Profile } from "./profile-storage";
export type LocationState = "idle" | "loading" | "success" | "empty" | "integration_pending" | "error";
/** `citations` 는 이번 턴에 실제로 호출된 도구가 돌려준 원천 목록이다 — 단발성 `api.chat` 시절에는
 *  항상 비어 있어 첫 항목의 URL 하나만 들고 있었지만, 스트리밍 경로는 도구마다 원천을 붙여 보내므로
 *  전부 보존한다. `images` 는 get_location_map_image 가 만든 data URL(검증은 lib/api.ts 가 한다). */
export interface ChatMessage { role: "assistant" | "user"; text: string; citations?: Citation[]; images?: string[] }

export type TraceStatus = "idle" | "active" | "done" | "skipped" | "failed";
export interface TraceStep { id: string; label: string; detail: string; status: TraceStatus; note?: string; ms?: number }
export interface TraceRun { steps: TraceStep[]; state: "idle" | "running" | "done" | "failed"; totalMs: number | null }

const INTRO: ChatMessage = { role: "assistant", text: "어떤 업종으로, 서울 어디에 자리를 잡을지 알려주세요. 예산까지 함께 말씀해 주시면 공식 데이터로 확인 가능한 범위를 찾아드립니다." };
const EMPTY_TRACE: TraceRun = { steps: [], state: "idle", totalMs: null };
const HANDOFF_MS = 900;

/** 실행 한 줄 = 축 하나. 순서는 백엔드가 이벤트를 내보내는 순서와 같아야 한다 —
 *  `settleStep` 이 정착한 줄의 다음 줄을 활성으로 올리기 때문이다.
 *
 *  개수를 문구로 적지 않는다. 축이 늘 때마다 화면과 서버가 어긋나므로, "N단계"는 이 배열의
 *  길이에서 나온다(`AgentRunOverlay` 가 `trace.steps.length` 를 쓴다).
 *
 *  마지막 줄의 id 가 에이전트 키가 아니라 `grade` 인 것은 의도적이다. AgentRunOverlay 가 완료
 *  문구를 `steps.find(step => step.id === "grade")` 의 note 에서 읽는다. 메인 에이전트가 내는
 *  것이 실제로 종합 요약이므로 이 자리에 놓는 것이 내용상으로도 맞다. */
const AGENT_ROWS: { id: string; label: string; detail: string }[] = [
  { id: "condition.location", label: "입지 조건 확정", detail: "업종·자치구·자기자본만 되묻고, 희망 월세·평수·보증금은 없어도 진행합니다. 없으면 그 수치만 유보합니다." },
  { id: "condition.finance", label: "금융 프로필 확정", detail: "자기자본·기존부채·월고정지출. 마이데이터는 꺼져 있고 수동 입력이 같은 스키마를 채웁니다." },
  { id: "finance.band", label: "조달 밴드 산출", detail: "자기자본선·권장 조달선·최대 조달선과 손익분기선. 커널이라 모델이 끼지 않습니다." },
  { id: "finance.stress", label: "창업 금융 스트레스 테스트", detail: "매출 −20%/−30%·금리 +1%p 세 시나리오를 항상 전부 돌립니다." },
  { id: "finance.kb_products", label: "금융상품", detail: "금융감독원 공시의 개인사업자대출 금리를 정책자금 금리와 나란히 놓습니다. 한도가 문장이라 조합은 계산하지 않습니다." },
  { id: "finance.subsidy", label: "정부지원", detail: "기업마당·K-Startup 공고. 지원 규모가 구조화 필드로 오지 않아 조달선 상향은 반영하지 않습니다." },
  { id: "location.demand", label: "수요", detail: "유동·상주·직장인구와 배후 구매력. 서울시 상권분석 집계이므로 근거 B입니다." },
  { id: "location.competition", label: "경쟁", detail: "동종 점포밀도와 신규·폐업 추세. 상권 단위 집계입니다." },
  { id: "location.viability", label: "매출", detail: "목표매출을 상권 동종 매출 분포에 대입해 어디쯤인지 봅니다. 후보를 떨어뜨릴 수 있는 유일한 축입니다." },
  { id: "location.survival", label: "생존이력", detail: "18/24개월 영업유지율. 인허가 이력 코호트가 있어야 하는 유일한 근거 A 경로입니다." },
  { id: "location.access", label: "접근성", detail: "역·버스·주요 시설과의 인접 관계. 좌표계 실측 전에는 거리·소요시간을 만들지 않습니다." },
  { id: "timing.policy", label: "시점", detail: "재개발·교통·주택공급·공사 일정. 원천이 없으면 시점을 권하지 않고 판단을 유보합니다. 후보 순위와 탈락에 관여하지 않습니다." },
  { id: "grade", label: "종합", detail: "축이 낸 수치를 모아 카드로 정리합니다. 여기서 새로 계산하거나 설명을 지어내지 않습니다." },
];
/** 백엔드가 준 문구를 그대로 옮긴다. 없을 때만 상태를 사람 말로 바꾼다.
 *
 *  조달 밴드는 예외적으로 수치를 적는다 — 그 줄이 낸 결론이 문장이 아니라 금액이기 때문이다.
 *  단 그 금액은 이 에이전트가 이벤트에 실어 보낸 값을 **형식만 바꿔** 적는 것이고, 여기서
 *  더하거나 고르거나 다시 계산하지 않는다. */
function noteFor(agent: AgentProgress): string | undefined {
  if (agent.key === "finance.band" && agent.status === "ok") {
    const quoted = bandNote(agent.data);
    if (quoted) return quoted;
  }
  if (agent.message) return agent.message;
  if (agent.status === "integration_pending") return "연동 대기";
  if (agent.status === "withheld") return "판단 유보";
  return undefined;
}

/** 에이전트가 낸 권장 조달선 한 줄만 꺼내 읽는다. 없으면 아무것도 적지 않는다. */
function bandNote(data: Record<string, unknown> | undefined): string | undefined {
  const bands = Array.isArray(data?.bands) ? (data.bands as Record<string, unknown>[]) : null;
  const line = bands?.find((item) => item.band === "RECOMMENDED");
  if (typeof line?.ceiling_krw !== "number" || typeof line?.target_daily_revenue_krw !== "number") return undefined;
  return `권장 조달선 ${formatKrw(line.ceiling_krw)} · 목표 일매출 ${formatKrw(line.target_daily_revenue_krw)}`;
}

/** 전체 실행은 축마다 한 줄이고, 재조회는 매물 조회 leg 만 다시 돈다. */
function planTrace(inputs: CaseInput, leg: "full" | "search"): TraceStep[] {
  // 전체 실행의 줄은 백엔드의 축 선언이 그대로다. 재조회는 매물 조회 leg 만 다시 도므로
  // 두 줄로 남고, 그 문구는 상권 프로파일이 켜진 뒤의 사실을 따른다 — 이제 후보는 근거 B 로도 나온다.
  if (leg === "full") return AGENT_ROWS.map((row) => ({ ...row, status: "idle" as const }));
  return [
    { id: "search", label: "시연용 매물 데이터 조회", detail: `시연용 매물 데이터 · 서울 ${inputs.district} · 보증금이 총예산 이하인 매물만 · ${inputs.industry} 업종의 서울시 상권분석 집계와 '${PRIORITY_LABELS[inputs.priority]}' 우선순위로 정렬 · 최대 4곳.`, status: "idle" },
    { id: "grade", label: "근거 등급·출처 정리", detail: "상권 통계를 확인한 후보는 근거 B(상권 위험 진단), 확인하지 못한 후보는 근거 C로 남습니다. 개별 이력이 없으므로 근거 A는 나오지 않습니다.", status: "idle" }
  ];
}

function gradeNote(candidates: Candidate[]) {
  if (candidates.length === 0) return "등급을 매길 후보가 없습니다.";
  const tally = new Map<string, number>();
  for (const candidate of candidates) tally.set(candidate.evidence_grade, (tally.get(candidate.evidence_grade) ?? 0) + 1);
  return `${candidates.length}곳 · ${[...tally].map(([grade, count]) => `근거 ${grade} ${count}곳`).join(" · ")}`;
}

/** 권장 조달선. 밴드는 항상 자기자본선·권장·최대 순서로 오지만 순서에 의존하지 않는다. */
export function recommendedLine(result: FundingBandResult | null): BandLine | null {
  return result?.bands.find((line) => line.band === "RECOMMENDED") ?? null;
}

/** 밴드를 아예 낼 수 없게 만드는 입력만 센다.
 *  권장 조달선은 월 고정지출에서 나오므로 희망 월세 하나면 세 밴드와 손익분기선이 모두 계산된다.
 *  평수·보증금은 필요자금(→현금소진)에만 관여하므로 서버가 partial 로 부분 산출한다. */
function missingBandInputs(input: BandForm): string[] {
  return input.monthly_rent_krw > 0 ? [] : ["희망 월세"];
}

function inputPending(gaps: string[]): FundingBandResult {
  return {
    status: "integration_pending", required_capital_krw: null, required_capital_band: null,
    bands: [], break_even: null, parameter_status: "VERIFIED", unverified_params: [], missing_params: gaps,
    message: `${gaps.join(" · ")}을 입력하면 조달 밴드를 계산합니다. 입력 전에는 값을 추정하지 않습니다.`, provenance: null
  };
}

/** Owns the whole 자리매김 flow so the panel renders it and the map visualises it from one source. */
export function useJarimaegim() {
  const [step, setStep] = useState<FlowStep>("profile");
  const [profile, setProfile] = useState<Profile>(DEFAULT_PROFILE);
  const [profileConfirmed, setProfileConfirmed] = useState(false);
  // 저장된 값을 복원했는지. 화면이 "이 브라우저에 저장됨"을 말하려면 이 사실을 알아야 한다.
  const [profileRestored, setProfileRestored] = useState(false);
  const [form, setForm] = useState<CaseInput>(DEFAULT_CASE);
  // 출처 라벨과 인용의 원본. 필드별로 "무엇에서 그렇게 읽었는지"를 화면이 말할 수 있어야 한다.
  const [proposal, setProposal] = useState<ConditionInterpretResult | null>(null);
  // '다시 말할게요'로 돌아갔을 때 입력했던 문장을 복원한다.
  const [interpretText, setInterpretText] = useState("");
  // 사용자가 직접 고친 필드. 출처 라벨이 제안보다 우선한다.
  const [edited, setEdited] = useState<Set<string>>(new Set());
  const [capacity, setCapacity] = useState<FundingCapacityResult | null>(null);
  const [capacityState, setCapacityState] = useState<LocationState>("idle");
  const [caseData, setCaseData] = useState<CaseRecord | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [locationState, setLocationState] = useState<LocationState>("idle");
  const [focused, setFocused] = useState<string | null>(null);
  const [summary, setSummary] = useState<DistrictSummary[]>([]);
  const [overviewDistrict, setOverviewDistrict] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Record<string, AnalysisResult>>({});
  const [programs, setPrograms] = useState<Program[]>([]);
  const [programState, setProgramState] = useState<LocationState>("idle");
  const [catalog, setCatalog] = useState<Program[]>([]);
  const [catalogState, setCatalogState] = useState<LocationState>("idle");
  const [kbProducts, setKbProducts] = useState<KbProduct[]>([]);
  const [kbState, setKbState] = useState<LocationState>("idle");
  const [committed, setCommitted] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Record<string, string>>({});
  const [docBusy, setDocBusy] = useState("");
  const [docNotice, setDocNotice] = useState("");
  // 화면에 보인 순서를 그대로 들고 있는다. 문서의 나열 순서가 화면과 같아야 대조가 된다.
  const [selected, setSelected] = useState<{ products: string[]; programs: string[] }>({ products: [], programs: [] });
  const [docConfirmed, setDocConfirmed] = useState(false);
  const [bandForm, setBandForm] = useState<BandForm>(DEFAULT_BAND_FORM);
  const [bands, setBands] = useState<FundingBandResult | null>(null);
  const [bandState, setBandState] = useState<LocationState>("idle");
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([INTRO]);
  const [busy, setBusy] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  /** 이번 턴에 진행 중인 도구 호출. 턴이 끝나면 비운다 — 완료된 근거는 메시지의 citations 가 들고 있다. */
  const [chatTools, setChatTools] = useState<ChatToolActivity[]>([]);
  const [error, setError] = useState("");
  const [trace, setTrace] = useState<TraceRun>(EMPTY_TRACE);
  const [traceOpen, setTraceOpen] = useState(false);
  /** 조건을 만든 발화. condition.location 이 실행 중에도 이것을 읽어 아직 비어 있는 항목을 채운다. */
  const [utterance, setUtterance] = useState("");
  const sessionReady = useRef<Promise<void> | null>(null);
  const chatAbort = useRef<AbortController | null>(null);
  const traceMark = useRef<Record<string, number>>({});
  const traceOrigin = useRef(0);
  // 마지막으로 누른 후보와 지금 살아 있는 케이스. 저장이 늦게 도착했을 때 그 응답이 아직
  // 유효한지 판단하는 기준이다. 둘 다 렌더 사이에 읽어야 하므로 상태가 아니라 ref 다.
  const commitIntent = useRef<string | null>(null);
  const activeCaseId = useRef<string | null>(null);

  /** 케이스가 바뀌는 유일한 통로. 상태와 activeCaseId 를 함께 옮겨 둘이 어긋나지 않게 한다.
   *  setCaseData 를 직접 부르면 ref 가 뒤처지고, 뒤처진 ref 는 늦게 온 응답을 막지 못한다. */
  const applyCase = useCallback((record: CaseRecord | null) => {
    activeCaseId.current = record?.id ?? null;
    setCaseData(record);
  }, []);

  useEffect(() => { api.status().then(setStatus).catch(() => setStatus(null)); }, []);
  // 언마운트 시 열려 있던 SSE 연결을 끊는다. 끊지 않으면 화면이 사라진 뒤에도 스트림이 계속 읽히고,
  // 그 턴의 setState 가 마운트되지 않은 컴포넌트로 날아간다.
  useEffect(() => () => { chatAbort.current?.abort(); }, []);

  // Landing overview. A failure leaves the map empty rather than breaking the shell —
  // the summary is orientation, not something the flow depends on.
  useEffect(() => { api.getListingSummary().then((result) => setSummary(result.districts)).catch(() => setSummary([])); }, []);

  /** Anonymous session is minted lazily; an existing cookie answers 409 and is reused as-is. */
  const ensureSession = useCallback(() => {
    if (!sessionReady.current) {
      sessionReady.current = api.createAnonymousSession().then(() => undefined).catch((err) => {
        if (err instanceof ApiError && (err.status === 409 || err.code === "SESSION_EXISTS")) return;
        sessionReady.current = null;
        throw err;
      });
    }
    return sessionReady.current;
  }, []);


  /** 직접 입력으로 시작. 서버를 거치지 않고 빈 제안으로 확인 화면에 들어간다. */
  const startManual = useCallback(() => {
    setProposal(null); setEdited(new Set()); setInterpretText(""); setStep("confirm");
  }, []);

  const setField = useCallback(<K extends keyof CaseInput>(key: K, value: CaseInput[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setEdited((prev) => new Set(prev).add(key as string));
  }, []);

  /** 모든 BandForm 값이 number 또는 number|null 이므로 단일 시그니처로 둔다.
   *  제네릭으로 두면 컴포넌트 prop 으로 넘길 때 반공변 위치에서 타입이 어긋난다. */
  const setBandField = useCallback((key: keyof BandForm, value: number | null) => {
    setBandForm((prev) => ({ ...prev, [key]: value } as BandForm));
    setEdited((prev) => new Set(prev).add(key as string));
  }, []);

  const setProfileField = useCallback((key: keyof Profile, value: number) => {
    setProfile((prev) => ({ ...prev, [key]: value }));
  }, []);

  const toggleFunding = useCallback((kind: "products" | "programs", id: string) => {
    setSelected((prev) => {
      const list = prev[kind];
      return { ...prev, [kind]: list.includes(id) ? list.filter((item) => item !== id) : [...list, id] };
    });
  }, []);

  /** 조달 여력. 케이스 이전이라 프로필만 보낸다. 실패해도 조건으로 가는 길은 막지 않는다. */
  const loadCapacity = useCallback(async (financial: Profile) => {
    setCapacityState("loading");
    try {
      await ensureSession();
      const result = await api.fundingCapacity(financial.equity_krw, financial.existing_debt_krw);
      setCapacity(result);
      setCapacityState(result.status === "computed" ? "success" : "integration_pending");
    } catch { setCapacity(null); setCapacityState("error"); }
  }, [ensureSession]);

  /** 브라우저에 남은 프로필을 복원한다. localStorage 는 서버에 없으므로 마운트 후에만 읽는다.
   *  복원되면 관문을 건너뛰고 조달 여력부터 보여준다 — 같은 질문을 두 번 하지 않는 것이 저장의 목적이다. */
  useEffect(() => {
    const stored = loadProfile();
    if (!stored) return;
    setProfile(stored); setProfileConfirmed(true); setProfileRestored(true);
    setStep((current) => current === "profile" ? "capacity" : current);
    void loadCapacity(stored);
  }, [loadCapacity]);

  /** 프로필 확정. 여기서 끝내지 않고 조달 여력까지 돌려준 뒤에야 1단계가 완결된다. */
  const confirmProfile = useCallback(() => {
    saveProfile(profile);
    setProfileConfirmed(true); setProfileRestored(true); setStep("capacity");
    void loadCapacity(profile);
  }, [loadCapacity, profile]);

  /** 저장된 프로필을 지운다. 지우면 관문으로 돌아가고, 다음 방문에도 복원되지 않는다. */
  const forgetProfile = useCallback(() => {
    clearProfile();
    setProfile(DEFAULT_PROFILE); setProfileConfirmed(false); setProfileRestored(false); setStep("profile");
    setCapacity(null); setCapacityState("idle");
  }, []);

  const beginTrace = useCallback((steps: TraceStep[]) => {
    const now = performance.now();
    traceOrigin.current = now; traceMark.current = { [steps[0].id]: now };
    setTrace({ steps: steps.map((step, index) => index === 0 ? { ...step, status: "active" } : step), state: "running", totalMs: null });
    setTraceOpen(true);
  }, []);

  const dismissTrace = useCallback(() => setTraceOpen(false), []);

  /** Purely presentational dwell so the finished run is readable before the overlay hands off to 입지. */
  const handoff = useCallback(async () => {
    await new Promise((resolve) => setTimeout(resolve, HANDOFF_MS));
    setTraceOpen(false);
  }, []);

  /** Settles the named step with its measured duration and promotes the next one. */
  const settleStep = useCallback((id: string, status: "done" | "skipped", note?: string) => setTrace((prev) => {
    const index = prev.steps.findIndex((step) => step.id === id);
    if (index < 0 || prev.state !== "running") return prev;
    const now = performance.now();
    const steps = prev.steps.map((step, position) => position === index ? { ...step, status, note, ms: Math.round(now - (traceMark.current[id] ?? now)) } : step);
    const next = steps[index + 1];
    if (next) { steps[index + 1] = { ...next, status: "active" }; traceMark.current[next.id] = now; }
    return { steps, state: next ? "running" : "done", totalMs: next ? null : Math.round(now - traceOrigin.current) };
  }), []);

  /** Failure stops the run where it actually stopped — later steps are marked as not run, never silently green. */
  const failTrace = useCallback((message: string) => setTrace((prev) => {
    if (prev.state !== "running") return prev;
    const index = prev.steps.findIndex((step) => step.status === "active");
    const now = performance.now();
    return {
      steps: prev.steps.map((step, position) => position === index ? { ...step, status: "failed" as const, note: message, ms: Math.round(now - (traceMark.current[step.id] ?? now)) }
        : position > index ? { ...step, status: "skipped" as const, note: "앞 단계가 끝나지 않아 진행하지 않았습니다." } : step),
      state: "failed", totalMs: Math.round(now - traceOrigin.current)
    };
  }), []);

  /** Shared 입지 조회 leg. Emits the search/grade steps and rethrows so the caller owns the failure.
   *  Single funnel for condition-driven population — clearing overviewDistrict here (rather than in
   *  each caller) keeps a stale district label from surviving into a real AI search result. */
  const runSearch = useCallback(async (record: CaseRecord) => {
    setOverviewDistrict(null); setLocationState("loading"); setCandidates([]); setFocused(null);
    const result = await api.searchLocations(record.id, record.inputs);
    settleStep("search", "done", result.status === "success" ? `응답 ${result.candidates.length}건` : result.message || "조건에 맞는 시연용 매물이 없습니다.");
    setCandidates(result.candidates);
    setLocationState(result.status);
    setFocused(result.candidates[0]?.id ?? null);
    if (result.message) setError(result.message);
    settleStep("grade", result.candidates.length > 0 ? "done" : "skipped", gradeNote(result.candidates));
  }, [settleStep]);

  /** Expand one district's listings from the overview. No case exists yet, so this uses the public route. */
  const selectOverviewDistrict = useCallback(async (district: string) => {
    setOverviewDistrict(district);
    setLocationState("loading");
    try {
      const result = await api.getListings(district, 15);
      setCandidates(result.candidates);
      setLocationState(result.status);
      setFocused(result.candidates[0]?.id ?? null);
    } catch { setLocationState("error"); }
  }, []);

  const clearOverviewDistrict = useCallback(() => {
    setOverviewDistrict(null); setCandidates([]); setFocused(null); setLocationState("idle");
  }, []);

  /** 조달 밴드 산출. 후보와 무관하게 사용자 조건만으로 계산되므로 입지 조회보다 먼저 실행한다.
   *  자기자본·기존부채·월 고정지출은 케이스가 아니라 금융 프로필에서 온다. */
  const runBands = useCallback(async (record: CaseRecord, input: BandForm, financial: Profile) => {
    const gaps = missingBandInputs(input);
    if (gaps.length > 0) {
      const pending = inputPending(gaps);
      setBands(pending); setBandState("integration_pending");
      return pending;
    }
    setBandState("loading");
    const result = await api.fundingBands(record.id, { industry: record.inputs.industry, ...input, ...financial });
    setBands(result);
    // partial 은 밴드를 낸 상태다. 대기로 취급하면 낼 수 있는 값까지 화면에서 사라진다.
    setBandState(result.status === "integration_pending" ? "integration_pending" : "success");
    return result;
  }, []);

  /** 실행에 실제로 쓰이는 조건. 자기자본·총예산은 폼이 아니라 금융 프로필에서 온다.
   *  화면이 `form` 을 직접 읽으면 관문에서 1억을 확정해도 실행 화면에는 자기자본 0원이
   *  찍힌다 — 같은 병합을 두 곳에서 하지 않도록 여기서 한 번만 만든다. */
  const runInputs = useMemo<CaseInput>(
    () => ({ ...form, equity_krw: profile.equity_krw, budget_krw: profile.equity_krw }),
    [form, profile.equity_krw]);

  /** 실행. `patch` 는 방금 읽어 아직 `form` 에 반영되지 않은 값이다.
   *
   *  `form` 은 `setForm` 직후에도 이전 값이다. 자동 진행은 발화에서 방금 읽은 업종으로 곧바로
   *  시작해야 하므로 상태 반영을 기다리지 않고 패치를 직접 받는다 — 기다리면 업종이 빈 채로
   *  케이스가 만들어진다. */
  const startWith = useCallback(async (patch: Partial<CaseInput>, bandPatch: Partial<BandForm> = {}) => {
    setError(""); setBusy("case"); setStep("recommend");
    const inputs: CaseInput = { ...form, ...patch, equity_krw: profile.equity_krw, budget_krw: profile.equity_krw };
    // 임대 조건도 같은 이유로 패치를 직접 받는다. 발화에서 읽은 월세를 `setBandForm` 으로만
    // 넘기면 이 실행은 반영 전 값(0원)을 보내고, 손익분기가 유보로 빠진다.
    const terms: BandForm = { ...bandForm, ...bandPatch };
    beginTrace(planTrace(inputs, "full"));
    try {
      await ensureSession();
      const title = `${inputs.district} ${inputs.industry}`.trim() || "새 케이스";
      const created = await api.createCase(inputs, title);
      // 케이스 쓰기는 applyCase 한 곳으로 모은다 — activeCaseId 와 caseData 가 어긋나면
      // 늦게 도착한 저장 응답이 이미 버린 케이스를 되살린다.
      applyCase(created);

      // 실행 순서는 이제 백엔드의 메인 에이전트가 가진다. 여기서는 도착한 판정을 줄에 옮길 뿐,
      // 어느 팀이 먼저인지도 어디서 멈추는지도 클라이언트가 정하지 않는다.
      const settled = new Set<string>();
      const rowId = (key: string) => (key === "main.integrate" ? "grade" : key);
      let outcome: PrescribeResult | null = null;
      let mainOutcome: AgentProgress | null = null;
      await api.prescribeStream(created.id, {
        monthly_rent_krw: terms.monthly_rent_krw, monthly_maintenance_krw: terms.monthly_maintenance_krw,
        key_money_krw: terms.key_money_krw, area_pyeong: terms.area_pyeong || null,
        deposit_krw: terms.deposit_krw || null, fitout_krw: terms.fitout_krw || null,
        existing_debt_krw: profile.existing_debt_krw, other_monthly_fixed_krw: profile.other_monthly_fixed_krw,
        // 운영형태는 화면이 묻지 않는다. 발화에 있으면 처방 때 condition.location 이 읽는다.
        utterance,
      }, {
        onRunStart: () => {},
        onAxisStart: () => {},
        onAgentEnd: (agent) => {
          // 메인 통합은 마지막 줄이다. 여기서 바로 정착시키면 트레이스가 done 으로 넘어가고,
          // 그 뒤에 오는 정리 루프가 전부 무시되어 중간 줄이 "진행 중"인 채로 남는다.
          // 실측으로 확인된 동작이라 순서를 onDone 에 맡긴다.
          if (agent.key === "main.integrate") { mainOutcome = agent; return; }
          settled.add(rowId(agent.key));
          // 상태를 여기서 다시 판정하지 않는다. 판정에 성공한 것만 done 이고, 나머지는 왜 그런지를
          // note 로 그대로 옮긴다 — 원천이 없다는 사실이 실패로 보이면 안 된다.
          settleStep(rowId(agent.key), agent.status === "ok" ? "done" : "skipped", noteFor(agent));
        },
        onDone: (result) => {
          outcome = result;
          // 멈춘 실행에서는 뒤쪽 에이전트에게 순서가 오지 않아 이벤트가 없다. 남은 줄을 선언 순서대로
          // 닫아야 마지막 줄이 마지막에 정착하며 트레이스가 done 으로 넘어간다.
          for (const row of AGENT_ROWS) {
            if (settled.has(row.id)) continue;
            if (row.id === "grade") {
              const main = mainOutcome;
              settleStep("grade", main && main.status === "ok" ? "done" : "skipped",
                main ? noteFor(main) : "실행이 끝나지 않아 종합하지 못했습니다.");
            } else {
              settleStep(row.id, "skipped", "앞 단계에서 멈춰 순서가 오지 않았습니다.");
            }
          }
        },
      });

      // 밴드 산출물은 조달 화면이 통째로 쓰므로 기존 경로를 그대로 유지한다. 같은 compute_bands 를
      // 부르므로 두 경로가 다른 답을 낼 수는 없다. 페이로드 통합은 별도 변경으로 다룬다.
      const band = await runBands(created, terms, profile);
      const line = recommendedLine(band);
      const ceiling = (outcome as PrescribeResult | null)?.summary?.recommended_ceiling_krw ?? line?.ceiling_krw ?? null;
      // 후보를 거르는 상한은 사용자가 스스로 좁힌 예산이 아니라 산출된 권장 조달선이다.
      // 희망 월세가 없으면 권장 조달선도 없다 — 그때는 케이스 예산을 그대로 둔다.
      const record = ceiling && ceiling > created.inputs.budget_krw
        ? await api.updateCase(created.id, created.version, { budget_krw: ceiling })
        : created;
      if (record !== created) applyCase(record);
      await runSearch(record);
      await handoff();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "케이스를 만들지 못했습니다.";
      failTrace(message); setLocationState("error"); setError(message);
    } finally { setBusy(""); }
  }, [applyCase, bandForm, beginTrace, ensureSession, failTrace, form, handoff, profile, runBands, runSearch, settleStep, utterance]);

  const start = useCallback(() => startWith({}), [startWith]);

  /** 조건을 고치면 영향받는 분석을 다시 돌린다. 부분 무효화는 M5 의 몫이고, 그전까지는
   *  전체를 다시 돈다 — 낡은 판정을 새 조건 옆에 남겨 두는 것보다 낫다.
   *
   *  케이스가 없으면(조건 화면에서 고치는 중) 아무것도 하지 않는다. 아직 돌린 것이 없으므로
   *  다시 돌릴 것도 없다. */
  const rerun = useCallback(() => {
    if (!caseData || trace.state === "running") return;
    void startWith({});
  }, [caseData, startWith, trace.state]);

  /** 발화를 서버 제안으로 바꾼다. 차단 항목(업종)이 채워지면 확인을 기다리지 않고 그대로 시작한다. */
  const interpret = useCallback(async (text: string) => {
    setBusy("interpret"); setError(""); setInterpretText(text);
    // 발화 원문을 남긴다. 처방 실행의 condition.location 이 아직 비어 있는 항목을
    // 이 원문에서 읽고, 그때도 원문에 그대로 있는 조각만 통과한다.
    setUtterance(text);
    try {
      await ensureSession();
      const result = await api.interpretConditions(text);
      setProposal(result); setEdited(new Set());
      const patch: Partial<CaseInput> = {};
      const field = result.fields;
      if (typeof field.industry.value === "string") patch.industry = field.industry.value;
      if (typeof field.district.value === "string") patch.district = field.district.value;
      if (typeof field.business_stage.value === "string") patch.business_stage = field.business_stage.value as CaseInput["business_stage"];
      if (typeof field.startup_type.value === "string") patch.startup_type = field.startup_type.value as CaseInput["startup_type"];
      if (typeof field.priority.value === "string") patch.priority = field.priority.value as CaseInput["priority"];
      setForm((prev) => ({ ...prev, ...patch }));
      const rent = field.monthly_rent_krw.value;
      const bandPatch: Partial<BandForm> = {};
      if (typeof rent === "number" && rent > 0) { bandPatch.monthly_rent_krw = rent; setBandForm((prev) => ({ ...prev, monthly_rent_krw: rent })); }
      setMessages((prev) => [...prev, { role: "user", text }, { role: "assistant", text: result.message }]);
      // 차단 항목(업종)이 발화에서 채워졌으면 확인을 기다리지 않고 그대로 진행한다. 자치구는
      // 기본값이 있고 자기자본은 프로필 단계가 이미 확정했으므로 여기서 볼 것은 업종뿐이다.
      // 확인을 없앤 대신 조건 스트립이 실행 화면에 상주하며 무엇을 어떻게 읽었는지 계속 보여준다.
      const industry = typeof field.industry.value === "string" ? field.industry.value.trim() : "";
      if (industry) { void startWith({ ...patch, industry }, bandPatch); return; }
      setStep("confirm");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "조건을 정리하지 못했습니다. 아래에서 직접 골라 주세요.");
      setProposal(null); setStep("confirm");
    } finally { setBusy(""); }
  }, [ensureSession, startWith]);

  const retrySearch = useCallback(async () => {
    if (!caseData || trace.state === "running") return;
    setError(""); beginTrace(planTrace(caseData.inputs, "search"));
    try { await runSearch(caseData); await handoff(); }
    catch (err) {
      const message = err instanceof ApiError ? err.message : "공식 위치 정보를 불러오지 못했습니다.";
      failTrace(message); setLocationState("error"); setError(message);
    }
  }, [beginTrace, caseData, failTrace, handoff, runSearch, trace.state]);

  /** 근거는 후보 목록 안에서 펼쳐진다. 스텝을 옮기지 않으므로 목록 맥락을 잃지 않는다. */
  const runAnalysis = useCallback(async (candidateId: string) => {
    setFocused(candidateId);
    if (analysis[candidateId] || !caseData) return;
    setBusy(`analysis:${candidateId}`);
    try {
      const result = await api.createAnalysis(caseData.id, candidateId);
      setAnalysis((prev) => ({ ...prev, [candidateId]: result }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "분석 결과를 만들지 못했습니다.");
    } finally { setBusy(""); }
  }, [analysis, caseData]);

  /** 입지 화면의 "정밀하게 맞추기"에서 필요자금 내역을 고친 뒤 그 자리에서 다시 계산한다. */
  const recomputeBands = useCallback(async () => {
    if (!caseData) return;
    setBusy("bands"); setError("");
    try { await runBands(caseData, bandForm, profile); }
    catch (err) {
      setBandState("error");
      setError(err instanceof ApiError ? err.message : "조달 밴드를 계산하지 못했습니다.");
    } finally { setBusy(""); }
  }, [bandForm, caseData, profile, runBands]);

  /** 확정 후보를 케이스에 남긴다. 남겨야 PDF 의 매물 섹션과 대화의 상권 맥락이 산다.
   *  저장이 실패해도 방금 한 확정을 되돌리지 않는다 — 사용자가 누른 것을 서버 사정으로
   *  취소해서는 안 된다.
   *
   *  후보를 비교하다 A → B 로 빠르게 바꾸면 두 PATCH 가 같은 버전을 들고 나가 한쪽이 409 로
   *  밀린다. 밀린 쪽이 마지막 클릭이면 화면은 B 인데 서버에는 A 가 남아, PDF 의 계획 기준
   *  후보와 조달 요약이 서로 다른 매물을 가리키게 된다. 그래서 409 는 케이스를 다시 읽어
   *  최신 버전으로 한 번만 재시도한다 — 재시도는 한 번뿐이고, 두 번째 409 는 포기한다.
   *
   *  응답을 반영하기 전에 매번 의도와 케이스를 함께 확인한다. 후보 id 만으로는 모자란다 —
   *  시연용 매물 id 는 세션마다 새로 나지 않고 데이터셋 행에 고정돼 있어(backend/app/listings.py),
   *  조건을 다시 입력해 만든 새 케이스에서 같은 매물을 고르면 후보 id 가 글자까지 같다.
   *  그때 먼저 떠난 케이스의 응답이 도착하면 id·버전·조건이 전부 다른 레코드가 살아 있는
   *  세션으로 들어앉는다. 케이스가 바뀌었으면 그 응답은 버린다. */
  const persistCommit = useCallback(async (record: CaseRecord, candidateId: string | null) => {
    const patch = { committed_listing_id: candidateId };
    const stillCurrent = () => activeCaseId.current === record.id && commitIntent.current === candidateId;
    try {
      const saved = await api.updateCase(record.id, record.version, patch);
      if (stillCurrent()) applyCase(saved);
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 409 || !stillCurrent()) return;
      try {
        const fresh = await api.getCase(record.id);
        if (!stillCurrent()) return;
        const saved = await api.updateCase(fresh.id, fresh.version, patch);
        if (stillCurrent()) applyCase(saved);
      } catch { return; }
    }
  }, [applyCase]);

  /** 계획 기준 후보. 처방 단계가 이 값을 소비한다.
   *
   *  후보를 확정하면 그 매물의 임대 조건을 필요자금 입력에 그대로 채운다. "이 후보로
   *  계획하기"를 눌러 놓고 보증금·월세·권리금을 다시 손으로 옮겨 적게 하는 것은 같은 값을
   *  두 번 묻는 것이다. 권리금은 가정값이므로 화면이 그렇게 표시하고, 사용자가 그 자리에서
   *  고칠 수 있다. 채운 뒤 밴드를 다시 계산해야 처방 단계가 확정 후보 기준 금액을 본다. */

  const commitCandidate = useCallback((candidateId: string | null) => {
    setCommitted(candidateId);
    // 후보가 바뀌면 부족분이 바뀐다. 그 부족분으로 고른 수단은 근거를 잃으므로 함께 비운다.
    setDocuments({}); setDocNotice(""); setSelected({ products: [], programs: [] }); setDocConfirmed(false);
    if (!caseData) return;
    commitIntent.current = candidateId;
    void persistCommit(caseData, candidateId);
    if (!candidateId) return;
    const listing = candidates.find((candidate) => candidate.id === candidateId)?.listing;
    if (!listing) return;
    const next: BandForm = {
      ...bandForm,
      area_pyeong: Number((listing.area_m2 / PYEONG_IN_M2).toFixed(1)),
      deposit_krw: listing.deposit_krw,
      monthly_rent_krw: listing.monthly_rent_krw,
      monthly_maintenance_krw: listing.maintenance_fee_krw ?? 0,
      key_money_krw: listing.key_money_krw ?? 0
    };
    setBandForm(next);
    void runBands(caseData, next, profile).catch(() => setBandState("error"));
  }, [bandForm, candidates, caseData, persistCommit, profile, runBands]);

  /** 문서 초안. 백엔드가 PDF 를 만들고 익명 세션에서만 내려받을 수 있다.
   *  선택은 id 로만 보내고 표시 문자열은 서버가 카탈로그에서 되찾는다. 금액은 서버가
   *  같은 산식으로 다시 계산하므로 여기서 계산한 값을 보내지 않는다. */
  const prepareDocument = useCallback(async (template: string) => {
    if (!caseData || !docConfirmed) return;
    setDocBusy(template); setDocNotice("");
    try {
      const record = await api.createDocument(caseData.id, template, {
        confirmed: docConfirmed,
        selected_product_ids: selected.products,
        selected_program_ids: selected.programs,
        // 밴드를 낼 수 없는 입력이면 아예 보내지 않는다. 판단은 밴드 산출과 같은 술어를 쓴다.
        funding_input: missingBandInputs(bandForm).length === 0
          ? { industry: caseData.inputs.industry, ...bandForm, ...profile }
          : null
      });
      setDocuments((prev) => ({ ...prev, [template]: record.document_id }));
      setDocNotice(record.message);
    } catch (err) {
      setDocNotice(err instanceof ApiError ? err.message : "문서를 준비하지 못했습니다.");
    } finally { setDocBusy(""); }
  }, [bandForm, caseData, docConfirmed, profile, selected]);

  const downloadDocument = useCallback(async (template: string) => {
    const id = documents[template];
    if (!id) { await prepareDocument(template); return; }
    setDocBusy(template);
    try {
      const blob = await api.downloadDocument(id);
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url; link.download = `jarimaegim-${template}.pdf`; link.click();
      URL.revokeObjectURL(url);
      setDocNotice("PDF 다운로드를 시작했습니다. 현재 익명 세션에서만 내려받을 수 있습니다.");
    } catch (err) {
      setDocNotice(err instanceof ApiError ? err.message : "PDF를 내려받지 못했습니다.");
    } finally { setDocBusy(""); }
  }, [documents, prepareDocument]);

  const loadPrograms = useCallback(async () => {
    if (!caseData || programState === "loading") return;
    setProgramState("loading");
    try {
      const result = await api.getPrograms(caseData.id);
      setPrograms(result.items);
      setProgramState(result.items.length > 0 ? "success" : "integration_pending");
    } catch (err) {
      setProgramState("error");
      setError(err instanceof ApiError ? err.message : "공식 공고를 불러오지 못했습니다.");
    }
  }, [caseData, programState]);

  /** KB 개인사업자대출 공시 — same official notices path, no case required. */
  const loadKbProducts = useCallback(async () => {
    setKbState("loading");
    try {
      await ensureSession();
      const result = await api.getKbProducts();
      setKbProducts(result.items);
      setKbState(result.items.length > 0 ? "success" : "integration_pending");
    } catch {
      setKbState("error");
    }
  }, [ensureSession]);

  useEffect(() => { if (step === "funding" && programState === "idle") void loadPrograms(); }, [step, programState, loadPrograms]);
  useEffect(() => { if (step === "funding" && kbState === "idle") void loadKbProducts(); }, [step, kbState, loadKbProducts]);

  /** The 정책 tab reads the same official notices without needing a case. */
  const loadCatalog = useCallback(async () => {
    setCatalogState((current) => current === "loading" ? current : "loading");
    try {
      await ensureSession();
      const result = await api.getProgramCatalog();
      setCatalog(result.items);
      setCatalogState(result.items.length > 0 ? "success" : "integration_pending");
    } catch (err) {
      setCatalogState("error");
      setError(err instanceof ApiError ? err.message : "공식 공고를 불러오지 못했습니다.");
    }
  }, [ensureSession]);

  /** 스트리밍 경로(`POST /messages/stream`)만 쓴다. 단발성 `api.chat` 은 도구가 붙지 않아
   *  케이스 요약 밖의 어떤 것도 조회하지 못하므로, 이 화면에서 청약공고·실거래·주변시설을 물으면
   *  "조회할 수 없다"는 답만 돌아왔다. Workspace 와 같은 경로를 쓰게 해 두 화면의 대화가 갈라지지
   *  않게 한다 — scripts/flow-check.mjs 가 지키는 회귀도 같은 것이다. */
  const sendChat = useCallback(async (text: string) => {
    if (!text.trim() || chatBusy) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setChatBusy(true);
    setChatTools([]);
    chatAbort.current?.abort();
    const controller = new AbortController();
    chatAbort.current = controller;
    // 앞선 턴이 늦게 도착해 지금 턴의 화면을 덮어쓰지 못하게 하는 기준. 상태가 아니라 ref 를 읽는
    // 이유는 commitIntent/activeCaseId 와 같다 — 렌더 사이에 판단해야 하기 때문이다.
    const isCurrent = () => chatAbort.current === controller;
    // 이번 턴의 지도 이미지. tool_end 는 언제나 done 보다 먼저 도착하므로(lib/api.ts 의 chatStream)
    // 지역 배열로 충분하다. chatTools 는 턴 끝에 비우므로 이미지를 거기에 둘 수 없다.
    const turnImages: string[] = [];
    try {
      await ensureSession();
      if (!caseData) { setMessages((prev) => [...prev, { role: "assistant", text: "먼저 업종과 지역 조건을 확정해 주세요. 조건이 있어야 공식 근거를 붙여 답할 수 있습니다." }]); return; }
      await api.chatStream(caseData.id, text, {
        onToolStart: (activity) => { if (isCurrent()) setChatTools((prev) => [...prev, activity]); },
        onToolEnd: (activity) => {
          if (!isCurrent()) return;
          if (activity.display?.image_url) turnImages.push(activity.display.image_url);
          // label 은 tool_end 에 실려 오지 않는다 — 같은 call_id 의 tool_start 가 남긴 것을 지킨다.
          setChatTools((prev) => prev.map((item) => item.call_id === activity.call_id ? { ...item, status: activity.status, summary: activity.summary } : item));
        },
        onDelta: () => {}, // delta 는 done.message 와 같은 본문이다. 두 번 그리지 않도록 done 에서만 그린다.
        onDone: (result) => { if (isCurrent()) setMessages((prev) => [...prev, { role: "assistant", text: result.message, citations: result.citations, images: turnImages.length ? turnImages : undefined }]); },
      }, controller.signal);
    } catch (err) {
      if (!isCurrent()) return;
      if (err instanceof Error && err.name === "AbortError") return;
      setMessages((prev) => [...prev, { role: "assistant", text: err instanceof ApiError ? err.message : "AI 연결을 확인하지 못했습니다. 저장된 근거는 계속 볼 수 있습니다." }]);
    } finally { if (isCurrent()) { setChatBusy(false); setChatTools([]); chatAbort.current = null; } }
  }, [caseData, chatBusy, ensureSession]);

  /** 조건만 다시 받는다. 금융 프로필은 사용자의 성질이므로 조건을 바꾼다고 다시 묻지 않는다.
   *  프로필을 고치는 경로는 어느 화면에서나 상단 배지의 "수정" 하나뿐이다. */
  const restart = useCallback(() => {
    // applyCase(null) 로 비워야 activeCaseId 도 함께 풀린다. 떠난 케이스로 날아간 저장은
    // 새 케이스에서 같은 후보를 다시 골라도 케이스 검사에 걸려 버려진다.
    setStep("ask"); setForm(DEFAULT_CASE); setProposal(null); setInterpretText(""); setEdited(new Set());
    applyCase(null); commitIntent.current = null;
    setCandidates([]); setLocationState("idle"); setFocused(null); setOverviewDistrict(null); setAnalysis({});
    setPrograms([]); setProgramState("idle"); setMessages([INTRO]); setError(""); setTrace(EMPTY_TRACE);
    setBandForm(DEFAULT_BAND_FORM); setBands(null); setBandState("idle");
    setCommitted(null); setDocuments({}); setDocBusy(""); setDocNotice(""); setTraceOpen(false);
    setSelected({ products: [], programs: [] }); setDocConfirmed(false);
  }, [applyCase]);

  return {
    step, setStep, form, runInputs, setField, proposal, interpretText, edited, interpret, startManual, caseData, candidates, locationState, focused, setFocused,
    summary, overviewDistrict, selectOverviewDistrict, clearOverviewDistrict,
    capacity, capacityState, loadCapacity,
    profile, setProfileField, profileConfirmed, profileRestored, confirmProfile, forgetProfile, restart,
    bandForm, setBandField, bands, bandState, recomputeBands,
    committed, commitCandidate, documents, docBusy, docNotice, prepareDocument, downloadDocument,
    selected, toggleFunding, docConfirmed, setDocConfirmed,
    analysis, programs, programState, catalog, catalogState, kbProducts, kbState, status, messages, busy, chatBusy, chatTools, error, setError, trace, traceOpen,
    start, startWith, rerun, retrySearch, runAnalysis, sendChat, loadCatalog, loadKbProducts, dismissTrace
  };
}

export type Jarimaegim = ReturnType<typeof useJarimaegim>;
