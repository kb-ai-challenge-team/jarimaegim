"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { DEFAULT_CASE } from "./constants";
import type { AnalysisResult, Candidate, CaseInput, CaseRecord, CostItem, CostPlan, Program, StatusResponse } from "./types";

export type FlowStep = "ask" | "confirm" | "recommend" | "evidence" | "cost" | "funding";
export type LocationState = "idle" | "loading" | "success" | "empty" | "integration_pending" | "error";
export interface ChatMessage { role: "assistant" | "user"; text: string; citation?: string }

const INTRO: ChatMessage = { role: "assistant", text: "어떤 업종으로, 서울 어디에 자리를 잡을지 알려주세요. 예산까지 함께 말씀해 주시면 공식 데이터로 확인 가능한 범위를 찾아드립니다." };

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
  const [costPlan, setCostPlan] = useState<CostPlan | null>(null);
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([INTRO]);
  const [busy, setBusy] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [error, setError] = useState("");
  const sessionReady = useRef<Promise<void> | null>(null);

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

  const searchCandidates = useCallback(async (record: CaseRecord) => {
    setLocationState("loading"); setCandidates([]); setFocused(null);
    try {
      const result = await api.searchLocations(record.id, record.inputs);
      setCandidates(result.candidates);
      setLocationState(result.status);
      setFocused(result.candidates[0]?.id ?? null);
      if (result.message) setError(result.message);
    } catch (err) {
      setLocationState("error");
      setError(err instanceof ApiError ? err.message : "공식 위치 정보를 불러오지 못했습니다.");
    }
  }, []);

  const start = useCallback(async () => {
    setError(""); setBusy("case");
    try {
      await ensureSession();
      const title = `${form.district} ${form.industry}`.trim() || "새 케이스";
      const record = await api.createCase(form, title);
      setCaseData(record);
      setStep("recommend");
      await searchCandidates(record);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "케이스를 만들지 못했습니다.");
    } finally { setBusy(""); }
  }, [ensureSession, form, searchCandidates]);

  const retrySearch = useCallback(() => { if (caseData) void searchCandidates(caseData); }, [caseData, searchCandidates]);

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

  useEffect(() => { if (step === "funding" && programState === "idle") void loadPrograms(); }, [step, programState, loadPrograms]);

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
    setPrograms([]); setProgramState("idle"); setCostPlan(null); setMessages([INTRO]); setError("");
  }, []);

  return {
    step, setStep, form, setField, parsedKeys, interpret, caseData, candidates, locationState, focused, setFocused,
    analysis, programs, programState, catalog, catalogState, costPlan, status, messages, busy, chatBusy, error, setError,
    start, retrySearch, runAnalysis, saveCost, sendChat, loadCatalog, reset
  };
}

export type Jarimaegim = ReturnType<typeof useJarimaegim>;
