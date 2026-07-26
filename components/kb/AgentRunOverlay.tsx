"use client";

import { useEffect, type CSSProperties } from "react";
import { Check, LoaderCircle, Minus, RefreshCw, ShieldCheck, TriangleAlert, X } from "lucide-react";
import { formatKrw } from "@/lib/constants";
import type { CaseInput } from "@/lib/types";
import type { TraceRun, TraceStatus } from "@/lib/use-jarimaegim";
import { AgentMark } from "./AgentMark";

const STATUS_TEXT: Record<TraceStatus, string> = { idle: "대기", active: "진행 중", done: "완료", skipped: "미진행", failed: "중단" };

/** Sub-100ms segments are reported as a bound, not a fake precise number. */
function formatMs(ms: number | null | undefined) {
  if (typeof ms !== "number") return "";
  return ms < 100 ? "0.1초 미만" : `${(ms / 1000).toFixed(1)}초`;
}

/**
 * The 상황 → 입지 handoff screen. Covers the workspace while the agent runs, then clears to reveal 입지.
 * Every row is a real await in `useJarimaegim.start()` and every duration is measured, so the screen
 * never narrates work the app did not actually do.
 */
export function AgentRunOverlay({ trace, inputs, onRetry, onDismiss, onEditConditions }: {
  trace: TraceRun; inputs: CaseInput; onRetry: () => void; onDismiss: () => void; onEditConditions: () => void;
}) {
  const failed = trace.state === "failed";
  useEffect(() => {
    if (!failed) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") onDismiss(); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [failed, onDismiss]);
  if (trace.steps.length === 0) return null;

  const running = trace.state === "running";
  const active = trace.steps.find((step) => step.status === "active");
  const settled = trace.steps.filter((step) => step.status !== "idle" && step.status !== "active").length;
  const found = trace.steps.find((step) => step.id === "grade");
  const heading = running ? "자리매김 AI가 입지를 확인하고 있습니다" : failed ? "확인이 중간에 멈췄습니다" : "확인을 마쳤습니다";
  const lead = running ? `공식 데이터로 확인 가능한 범위만 찾습니다. ${trace.steps.length}단계 중 ${settled + 1}단계 진행 중입니다.`
    : failed ? "어느 단계에서 멈췄는지 아래에 그대로 남겨 두었습니다."
    : `${found?.note ?? ""} · 총 ${formatMs(trace.totalMs)}`;
  const live = running ? `${trace.steps.length}단계 중 ${settled + 1}단계, ${active?.label ?? ""} 진행 중입니다.`
    : failed ? `확인이 중단되었습니다. ${trace.steps.find((step) => step.status === "failed")?.note ?? ""}`
    : `확인을 마쳤습니다. ${found?.note ?? ""}`;

  return <div className="kb-run" data-state={trace.state} role="dialog" aria-modal="true" aria-labelledby="kb-run-heading" aria-busy={running}>
    <div className="kb-run-card">
      <header className="kb-run-head">
        <AgentMark state={running ? "running" : failed ? "failed" : "done"} size={46} />
        <div>
          <small>자리매김 AI · 입지 확인</small>
          <strong id="kb-run-heading" key={heading}>{heading}</strong>
        </div>
        {failed && <button type="button" className="kb-icon-button" onClick={onDismiss} aria-label="분석 화면 닫기"><X aria-hidden="true" /></button>}
      </header>

      <ul className="kb-run-terms">
        {[inputs.district, inputs.industry.trim() || "업종 미입력", `총예산 ${formatKrw(inputs.budget_krw)}`].map((term, index) =>
          <li key={term} style={{ "--i": index } as CSSProperties}>{term}</li>)}
      </ul>

      <p className="kb-run-lead">{lead}</p>
      <div className="kb-run-bar" role="presentation"><span style={{ width: `${Math.round((settled / trace.steps.length) * 100)}%` }} /></div>
      <p className="sr-only" role="status" aria-live="polite">{live}</p>

      <ol className="kb-run-steps">
        {trace.steps.map((step, index) => <li key={step.id} data-status={step.status} style={{ "--i": index } as CSSProperties}>
          <span className="kb-run-dot" aria-hidden="true">
            {step.status === "active" ? <LoaderCircle className="kb-spin" /> : step.status === "done" ? <Check />
              : step.status === "failed" ? <TriangleAlert /> : step.status === "skipped" ? <Minus /> : null}
          </span>
          <span className="kb-run-body">
            <strong>{step.label}<em>{STATUS_TEXT[step.status]}</em></strong>
            <small>{step.note ?? step.detail}</small>
          </span>
          {typeof step.ms === "number" && <span className="kb-run-ms">{formatMs(step.ms)}</span>}
        </li>)}
      </ol>

      {failed && <div className="kb-run-actions">
        <button type="button" className="kb-primary kb-primary-sm" onClick={onRetry}><RefreshCw aria-hidden="true" /> 다시 시도</button>
        <button type="button" className="kb-ghost" onClick={onEditConditions}>조건 고치기</button>
      </div>}

      <p className="kb-run-foot"><ShieldCheck aria-hidden="true" />표시한 단계와 시간은 실제 호출을 측정한 값입니다. 연결되지 않은 데이터는 단계에 넣지 않습니다.</p>
    </div>
  </div>;
}
