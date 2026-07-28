"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { DEFAULT_BAND_FORM, DEFAULT_CASE, DEFAULT_PROFILE, PYEONG_IN_M2, formatKrw } from "./constants";
import { clearProfile, loadProfile, saveProfile, type Profile } from "./profile-storage";
import type { AnalysisResult, BandLine, Candidate, CaseInput, CaseRecord, DistrictSummary, FundingBandResult, KbProduct, Program, StatusResponse } from "./types";

// 금융 프로필을 한 번 확정한 뒤 조건 → 입지 → 처방 세 단계로 간다. 프로필은 스텝이 아니라 진입 관문이고,
// 확정한 값은 케이스 생성·밴드 산출·재검색이 전부 다시 읽는다. 후보를 보기 전에 다시 금액을 묻지 않는다.
export type FlowStep = "profile" | "ask" | "confirm" | "recommend" | "prescribe";
export type BandForm = typeof DEFAULT_BAND_FORM;
export type { Profile } from "./profile-storage";
export type LocationState = "idle" | "loading" | "success" | "empty" | "integration_pending" | "error";
export interface ChatMessage { role: "assistant" | "user"; text: string; citation?: string }

export type TraceStatus = "idle" | "active" | "done" | "skipped" | "failed";
export interface TraceStep { id: string; label: string; detail: string; status: TraceStatus; note?: string; ms?: number }
export interface TraceRun { steps: TraceStep[]; state: "idle" | "running" | "done" | "failed"; totalMs: number | null }

const INTRO: ChatMessage = { role: "assistant", text: "어떤 업종으로, 서울 어디에 자리를 잡을지 알려주세요. 예산까지 함께 말씀해 주시면 공식 데이터로 확인 가능한 범위를 찾아드립니다." };
const EMPTY_TRACE: TraceRun = { steps: [], state: "idle", totalMs: null };
const HANDOFF_MS = 900;

/** The trace mirrors the real awaits in `start()` — one step per network boundary, nothing scripted. */
function planTrace(inputs: CaseInput, leg: "full" | "search"): TraceStep[] {
  const steps: TraceStep[] = [
    { id: "session", label: "익명 세션 확인", detail: "계정 없이 익명 세션으로 진행합니다. 조건은 최대 24시간만 보관합니다.", status: "idle" },
    { id: "case", label: "입력 조건 확정", detail: "서울 25개 자치구 범위인지 서버에서 검증하고 케이스로 저장합니다.", status: "idle" },
    { id: "bands", label: "조달 밴드 산출", detail: "자기자본과 임대 조건으로 자기자본선·권장 조달선·최대 조달선과 손익분기선을 계산합니다. 외부 데이터는 쓰지 않습니다.", status: "idle" },
    { id: "search", label: "시연용 매물 데이터 조회", detail: `시연용 매물 데이터 · 서울 ${inputs.district} · 보증금이 총예산 이하인 매물만 · 월세 낮은 순 최대 4곳. 업종은 후보 선별에 쓰이지 않습니다.`, status: "idle" },
    { id: "grade", label: "근거 등급·출처 정리", detail: "시연용 매물은 좌표만 확인된 상태라 모두 근거 C이며, 출처는 시연용 생성 데이터로 표시합니다. 없는 근거는 만들지 않습니다.", status: "idle" }
  ];
  return leg === "full" ? steps : steps.slice(3);
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
    bands: [], break_even: null, missing_params: gaps,
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
  const [parsedKeys, setParsedKeys] = useState<Set<keyof CaseInput>>(new Set());
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
  const [bandForm, setBandForm] = useState<BandForm>(DEFAULT_BAND_FORM);
  const [bands, setBands] = useState<FundingBandResult | null>(null);
  const [bandState, setBandState] = useState<LocationState>("idle");
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([INTRO]);
  const [busy, setBusy] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [error, setError] = useState("");
  const [trace, setTrace] = useState<TraceRun>(EMPTY_TRACE);
  const [traceOpen, setTraceOpen] = useState(false);
  const sessionReady = useRef<Promise<void> | null>(null);
  const traceMark = useRef<Record<string, number>>({});
  const traceOrigin = useRef(0);

  useEffect(() => { api.status().then(setStatus).catch(() => setStatus(null)); }, []);

  /** 브라우저에 남은 프로필을 복원한다. localStorage 는 서버에 없으므로 마운트 후에만 읽는다.
   *  복원되면 관문을 건너뛰고 조건부터 시작한다 — 같은 질문을 두 번 하지 않는 것이 저장의 목적이다. */
  useEffect(() => {
    const stored = loadProfile();
    if (!stored) return;
    setProfile(stored); setProfileConfirmed(true); setProfileRestored(true);
    setStep((current) => current === "profile" ? "ask" : current);
  }, []);

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

  const interpret = useCallback((text: string, patch: Partial<CaseInput>) => {
    setForm((prev) => ({ ...prev, ...patch }));
    setParsedKeys(new Set(Object.keys(patch) as (keyof CaseInput)[]));
    setMessages((prev) => [...prev, { role: "user", text }, { role: "assistant", text: "말씀하신 내용을 조건으로 정리했습니다. 확인 후 수정하고 시작해 주세요." }]);
    setStep("confirm");
  }, []);

  const setField = useCallback(<K extends keyof CaseInput>(key: K, value: CaseInput[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }));
    setParsedKeys((prev) => { const next = new Set(prev); next.delete(key); return next; });
  }, []);

  /** 모든 BandForm 값이 number 또는 number|null 이므로 단일 시그니처로 둔다.
   *  제네릭으로 두면 컴포넌트 prop 으로 넘길 때 반공변 위치에서 타입이 어긋난다. */
  const setBandField = useCallback((key: keyof BandForm, value: number | null) => {
    setBandForm((prev) => ({ ...prev, [key]: value } as BandForm));
  }, []);

  const setProfileField = useCallback((key: keyof Profile, value: number) => {
    setProfile((prev) => ({ ...prev, [key]: value }));
  }, []);

  /** 프로필 확정. 케이스·밴드·재검색이 계속 다시 읽고, 세션이 만료돼도 다시 묻지 않도록 브라우저에 남긴다. */
  const confirmProfile = useCallback(() => {
    saveProfile(profile);
    setProfileConfirmed(true); setProfileRestored(true); setStep("ask");
  }, [profile]);

  /** 저장된 프로필을 지운다. 지우면 관문으로 돌아가고, 다음 방문에도 복원되지 않는다. */
  const forgetProfile = useCallback(() => {
    clearProfile();
    setProfile(DEFAULT_PROFILE); setProfileConfirmed(false); setProfileRestored(false); setStep("profile");
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

  const start = useCallback(async () => {
    setError(""); setBusy("case"); setStep("recommend");
    const inputs: CaseInput = { ...form, equity_krw: profile.equity_krw, budget_krw: profile.equity_krw };
    beginTrace(planTrace(inputs, "full"));
    try {
      await ensureSession();
      settleStep("session", "done", "익명 세션 확인됨");
      const title = `${inputs.district} ${inputs.industry}`.trim() || "새 케이스";
      const created = await api.createCase(inputs, title);
      setCaseData(created);
      settleStep("case", "done", `케이스 저장됨 · 버전 ${created.version}`);
      const band = await runBands(created, bandForm, profile);
      const line = recommendedLine(band);
      settleStep("bands", band.status === "integration_pending" ? "skipped" : "done",
        line
          ? `권장 조달선 ${formatKrw(line.ceiling_krw)} · 목표 일매출 ${formatKrw(line.target_daily_revenue_krw)}`
          : band.message || "제도 파라미터 등록 대기");
      // 후보를 거르는 상한은 사용자가 스스로 좁힌 예산이 아니라 산출된 권장 조달선이다.
      // 밴드를 못 냈으면 자기자본선으로 남겨 둔다 — 넓히기 위해 추정하지 않는다.
      const record = line && line.ceiling_krw > created.inputs.budget_krw
        ? await api.updateCase(created.id, created.version, { budget_krw: line.ceiling_krw })
        : created;
      if (record !== created) setCaseData(record);
      await runSearch(record);
      await handoff();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "케이스를 만들지 못했습니다.";
      failTrace(message); setLocationState("error"); setError(message);
    } finally { setBusy(""); }
  }, [bandForm, beginTrace, ensureSession, failTrace, form, handoff, profile, runBands, runSearch, settleStep]);

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

  /** 계획 기준 후보. 처방 단계가 이 값을 소비한다.
   *
   *  후보를 확정하면 그 매물의 임대 조건을 필요자금 입력에 그대로 채운다. "이 후보로
   *  계획하기"를 눌러 놓고 보증금·월세·권리금을 다시 손으로 옮겨 적게 하는 것은 같은 값을
   *  두 번 묻는 것이다. 권리금은 가정값이므로 화면이 그렇게 표시하고, 사용자가 그 자리에서
   *  고칠 수 있다. 채운 뒤 밴드를 다시 계산해야 처방 단계가 확정 후보 기준 금액을 본다. */
  const commitCandidate = useCallback((candidateId: string | null) => {
    setCommitted(candidateId);
    setDocuments({}); setDocNotice("");
    if (!candidateId) return;
    const listing = candidates.find((candidate) => candidate.id === candidateId)?.listing;
    if (!listing || !caseData) return;
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
  }, [bandForm, candidates, caseData, profile, runBands]);

  /** 문서 초안. 백엔드가 PDF 를 만들고 익명 세션에서만 내려받을 수 있다. */
  const prepareDocument = useCallback(async (template: string) => {
    if (!caseData) return;
    setDocBusy(template); setDocNotice("");
    try {
      const record = await api.createDocument(caseData.id, template);
      setDocuments((prev) => ({ ...prev, [template]: record.document_id }));
      setDocNotice(record.message);
    } catch (err) {
      setDocNotice(err instanceof ApiError ? err.message : "문서를 준비하지 못했습니다.");
    } finally { setDocBusy(""); }
  }, [caseData]);

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

  useEffect(() => { if (step === "prescribe" && programState === "idle") void loadPrograms(); }, [step, programState, loadPrograms]);
  useEffect(() => { if (step === "prescribe" && kbState === "idle") void loadKbProducts(); }, [step, kbState, loadKbProducts]);

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

  const sendChat = useCallback(async (text: string) => {
    if (!text.trim() || chatBusy) return;
    setMessages((prev) => [...prev, { role: "user", text }]);
    setChatBusy(true);
    try {
      await ensureSession();
      if (!caseData) { setMessages((prev) => [...prev, { role: "assistant", text: "먼저 업종과 지역 조건을 확정해 주세요. 조건이 있어야 공식 근거를 붙여 답할 수 있습니다." }]); return; }
      const result = await api.chat(caseData.id, text);
      setMessages((prev) => [...prev, { role: "assistant", text: result.message, citation: result.citations[0]?.official_url }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "assistant", text: err instanceof ApiError ? err.message : "AI 연결을 확인하지 못했습니다. 저장된 근거는 계속 볼 수 있습니다." }]);
    } finally { setChatBusy(false); }
  }, [caseData, chatBusy, ensureSession]);

  /** 조건만 다시 받는다. 금융 프로필은 사용자의 성질이므로 조건을 바꾼다고 다시 묻지 않는다.
   *  프로필을 고치는 경로는 어느 화면에서나 상단 배지의 "수정" 하나뿐이다. */
  const restart = useCallback(() => {
    setStep("ask"); setForm(DEFAULT_CASE); setParsedKeys(new Set()); setCaseData(null);
    setCandidates([]); setLocationState("idle"); setFocused(null); setOverviewDistrict(null); setAnalysis({});
    setPrograms([]); setProgramState("idle"); setMessages([INTRO]); setError(""); setTrace(EMPTY_TRACE);
    setBandForm(DEFAULT_BAND_FORM); setBands(null); setBandState("idle");
    setCommitted(null); setDocuments({}); setDocBusy(""); setDocNotice(""); setTraceOpen(false);
  }, []);

  return {
    step, setStep, form, setField, parsedKeys, interpret, caseData, candidates, locationState, focused, setFocused,
    summary, overviewDistrict, selectOverviewDistrict, clearOverviewDistrict,
    profile, setProfileField, profileConfirmed, profileRestored, confirmProfile, forgetProfile, restart,
    bandForm, setBandField, bands, bandState, recomputeBands,
    committed, commitCandidate, documents, docBusy, docNotice, prepareDocument, downloadDocument,
    analysis, programs, programState, catalog, catalogState, kbProducts, kbState, status, messages, busy, chatBusy, error, setError, trace, traceOpen,
    start, retrySearch, runAnalysis, sendChat, loadCatalog, loadKbProducts, dismissTrace
  };
}

export type Jarimaegim = ReturnType<typeof useJarimaegim>;
