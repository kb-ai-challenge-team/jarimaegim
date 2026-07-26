"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { DEFAULT_BAND_FORM, DEFAULT_CASE, formatKrw } from "./constants";
import type { AnalysisResult, BandLine, Candidate, CaseInput, CaseRecord, CostItem, CostPlan, FundingBandResult, KbProduct, Program, StatusResponse } from "./types";

export type FlowStep = "ask" | "confirm" | "recommend" | "evidence" | "cost" | "funding";
export type BandForm = typeof DEFAULT_BAND_FORM;
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
    { id: "search", label: "공식 장소 데이터 조회", detail: `Kakao Local 장소 검색 · 질의어 "서울 ${inputs.district} ${inputs.industry}" · 정확도순 최대 12곳`, status: "idle" },
    { id: "grade", label: "근거 등급·출처 정리", detail: "후보마다 확인 가능한 근거 등급과 출처만 붙입니다. 없는 근거는 만들지 않습니다.", status: "idle" }
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

/** 밴드 계산에 필요한 임대 조건이 채워졌는지. 비면 서버를 부르지 않고 대기 상태로 둔다. */
function missingBandInputs(input: BandForm): string[] {
  const gaps: string[] = [];
  if (input.area_pyeong <= 0) gaps.push("희망 평수");
  if (input.deposit_krw <= 0) gaps.push("희망 보증금");
  if (input.monthly_rent_krw <= 0) gaps.push("희망 월세");
  return gaps;
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
  const [step, setStep] = useState<FlowStep>("ask");
  const [form, setForm] = useState<CaseInput>(DEFAULT_CASE);
  const [parsedKeys, setParsedKeys] = useState<Set<keyof CaseInput>>(new Set());
  const [caseData, setCaseData] = useState<CaseRecord | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [locationState, setLocationState] = useState<LocationState>("idle");
  const [focused, setFocused] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<Record<string, AnalysisResult>>({});
  const [programs, setPrograms] = useState<Program[]>([]);
  const [programState, setProgramState] = useState<LocationState>("idle");
  const [catalog, setCatalog] = useState<Program[]>([]);
  const [catalogState, setCatalogState] = useState<LocationState>("idle");
  const [kbProducts, setKbProducts] = useState<KbProduct[]>([]);
  const [kbState, setKbState] = useState<LocationState>("idle");
  const [costPlan, setCostPlan] = useState<CostPlan | null>(null);
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

  /** Shared 입지 조회 leg. Emits the search/grade steps and rethrows so the caller owns the failure. */
  const runSearch = useCallback(async (record: CaseRecord) => {
    setLocationState("loading"); setCandidates([]); setFocused(null);
    const result = await api.searchLocations(record.id, record.inputs);
    settleStep("search", "done", result.status === "success" ? `응답 ${result.candidates.length}건` : result.message || "조건에 맞는 공식 장소가 없습니다.");
    setCandidates(result.candidates);
    setLocationState(result.status);
    setFocused(result.candidates[0]?.id ?? null);
    if (result.message) setError(result.message);
    settleStep("grade", result.candidates.length > 0 ? "done" : "skipped", gradeNote(result.candidates));
  }, [settleStep]);

  /** 조달 밴드 산출. 후보와 무관하게 사용자 조건만으로 계산되므로 입지 조회보다 먼저 실행한다. */
  const runBands = useCallback(async (record: CaseRecord, input: BandForm) => {
    const gaps = missingBandInputs(input);
    if (gaps.length > 0) {
      const pending = inputPending(gaps);
      setBands(pending); setBandState("integration_pending");
      return pending;
    }
    setBandState("loading");
    const result = await api.fundingBands(record.id, {
      industry: record.inputs.industry, equity_krw: record.inputs.equity_krw, ...input
    });
    setBands(result);
    setBandState(result.status === "computed" ? "success" : "integration_pending");
    return result;
  }, []);

  const start = useCallback(async () => {
    setError(""); setBusy("case"); setStep("recommend");
    beginTrace(planTrace(form, "full"));
    try {
      await ensureSession();
      settleStep("session", "done", "익명 세션 확인됨");
      const title = `${form.district} ${form.industry}`.trim() || "새 케이스";
      const record = await api.createCase(form, title);
      setCaseData(record);
      settleStep("case", "done", `케이스 저장됨 · 버전 ${record.version}`);
      const band = await runBands(record, bandForm);
      const line = recommendedLine(band);
      settleStep("bands", band.status === "computed" ? "done" : "skipped",
        line && band.break_even
          ? `권장 조달선 ${formatKrw(line.ceiling_krw)} · 목표 일매출 ${formatKrw(band.break_even.target_daily_revenue_krw)}`
          : band.message || "제도 파라미터 등록 대기");
      await runSearch(record);
      await handoff();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "케이스를 만들지 못했습니다.";
      failTrace(message); setLocationState("error"); setError(message);
    } finally { setBusy(""); }
  }, [bandForm, beginTrace, ensureSession, failTrace, form, handoff, runBands, runSearch, settleStep]);

  const retrySearch = useCallback(async () => {
    if (!caseData || trace.state === "running") return;
    setError(""); beginTrace(planTrace(caseData.inputs, "search"));
    try { await runSearch(caseData); await handoff(); }
    catch (err) {
      const message = err instanceof ApiError ? err.message : "공식 위치 정보를 불러오지 못했습니다.";
      failTrace(message); setLocationState("error"); setError(message);
    }
  }, [beginTrace, caseData, failTrace, handoff, runSearch, trace.state]);

  const runAnalysis = useCallback(async (candidateId: string) => {
    setFocused(candidateId); setStep("evidence");
    if (analysis[candidateId] || !caseData) return;
    setBusy(`analysis:${candidateId}`);
    try {
      const result = await api.createAnalysis(caseData.id, candidateId);
      setAnalysis((prev) => ({ ...prev, [candidateId]: result }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "분석 결과를 만들지 못했습니다.");
    } finally { setBusy(""); }
  }, [analysis, caseData]);

  const saveCost = useCallback(async (items: CostItem[]) => {
    if (!caseData) return;
    setBusy("cost");
    try { setCostPlan(await api.createCostPlan(caseData.id, items)); }
    catch (err) { setError(err instanceof ApiError ? err.message : "비용을 계산하지 못했습니다."); }
    finally { setBusy(""); }
  }, [caseData]);

  /** 비용 단계에서 필요자금 내역을 고친 뒤 다시 계산한다. */
  const recomputeBands = useCallback(async () => {
    if (!caseData) return;
    setBusy("bands"); setError("");
    try { await runBands(caseData, bandForm); }
    catch (err) {
      setBandState("error");
      setError(err instanceof ApiError ? err.message : "조달 밴드를 계산하지 못했습니다.");
    } finally { setBusy(""); }
  }, [bandForm, caseData, runBands]);

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

  const reset = useCallback(() => {
    setStep("ask"); setForm(DEFAULT_CASE); setParsedKeys(new Set()); setCaseData(null);
    setCandidates([]); setLocationState("idle"); setFocused(null); setAnalysis({});
    setPrograms([]); setProgramState("idle"); setCostPlan(null); setMessages([INTRO]); setError(""); setTrace(EMPTY_TRACE);
    setBandForm(DEFAULT_BAND_FORM); setBands(null); setBandState("idle"); setTraceOpen(false);
  }, []);

  return {
    step, setStep, form, setField, parsedKeys, interpret, caseData, candidates, locationState, focused, setFocused,
    bandForm, setBandField, bands, bandState, recomputeBands,
    analysis, programs, programState, catalog, catalogState, kbProducts, kbState, costPlan, status, messages, busy, chatBusy, error, setError, trace, traceOpen,
    start, retrySearch, runAnalysis, saveCost, sendChat, loadCatalog, loadKbProducts, reset, dismissTrace
  };
}

export type Jarimaegim = ReturnType<typeof useJarimaegim>;
