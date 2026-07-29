"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, Check, LoaderCircle, Send } from "lucide-react";
import type { Jarimaegim } from "@/lib/use-jarimaegim";
import type { ChatToolActivity } from "@/lib/types";
import { formatCollectedAt } from "@/lib/constants";

const QUICK = ["확인하지 못한 정보는?", "다음에 뭘 해야 해?", "근거 출처를 알려줘"];

/** Workspace.tsx 의 toolStatusKind 와 같은 접기 규칙. 도구가 돌려주는 상태 어휘(chat_tools.py 의
 *  TOOL_STATUSES)는 여덟 가지지만 줄 하나가 져야 할 몫은 "아직인가 / 끝났는가 / 실패했는가" 뿐이고,
 *  나머지 구분은 답변 본문이 설명한다. `empty` 를 실패로 보내지 않는 것이 요점이다 — 찾아봤는데
 *  없더라는 것은 확인에 성공한 결과지 조회 실패가 아니다(chat_tools.py 의 empty vs error 주석). */
function toolStatusKind(status: ChatToolActivity["status"]): "running" | "ok" | "error" {
  if (status === "running") return "running";
  return status === "ok" || status === "empty" ? "ok" : "error";
}

/** Right-docked conversation column. Explains only — it can never mutate case conditions. */
export function JarimaegimChat({ flow }: { flow: Jarimaegim }) {
  const [text, setText] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const history = flow.messages.slice(1);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [history.length, flow.chatBusy, flow.chatTools.length]);
  const send = (event: React.FormEvent) => { event.preventDefault(); const value = text.trim(); if (!value) return; setText(""); void flow.sendChat(value); };

  return <aside className="kb-chat-rail" aria-label="자리매김 AI 대화">
    <header>
      <span className="kb-ai-dot" aria-hidden="true" />
      <div><strong>대화</strong><small>{flow.status?.integrations.openai ? "AI 설명 연결됨" : "AI 키 연결 대기"}</small></div>
    </header>
    <div className="kb-chat-log" ref={logRef} role="log" aria-live="polite">
      <div className="kb-chat-message kb-chat-assistant"><p>{flow.messages[0].text}</p></div>
      {history.map((message, index) => <div key={index} className={`kb-chat-message kb-chat-${message.role}`}>
        <p>{message.text}</p>
        {message.images && message.images.length > 0 && <div className="kb-chat-images">{message.images.map((src, i) => <img key={i} className="kb-chat-map" src={src} alt="지도 미리보기" loading="lazy" />)}</div>}
        {message.citations && message.citations.length > 0 && <ul className="kb-chat-citations">{message.citations.map((citation, i) => <li key={i}><span className="kb-chat-citation-source">{citation.source_name}</span><span className="kb-chat-citation-title">{citation.title}</span><span className="kb-chat-citation-date">{formatCollectedAt(citation.collected_at)}</span></li>)}</ul>}
      </div>)}
      {flow.chatBusy && (flow.chatTools.length > 0
        // aria-live="off": 바깥 로그가 이미 polite 다. 도구 줄은 한 턴에 최대 12개까지 갱신되므로
        // 여기서 또 읽어주면 정작 읽어야 할 답변이 그 안에 묻힌다.
        ? <ul className="kb-chat-tools" aria-live="off">{flow.chatTools.map((activity) => {
            const kind = toolStatusKind(activity.status);
            return <li key={activity.call_id} className={`kb-chat-tool ${kind}`}>
              {kind === "running" ? <LoaderCircle className="kb-spin" aria-hidden="true" /> : kind === "ok" ? <Check aria-hidden="true" /> : <AlertCircle aria-hidden="true" />}
              <span>{activity.label}</span>
              {activity.summary && <small>{activity.summary}</small>}
            </li>;
          })}</ul>
        : <div className="kb-chat-message kb-chat-assistant kb-chat-pending"><LoaderCircle className="kb-spin" aria-hidden="true" /> 공식 근거를 확인하고 있습니다.</div>)}
    </div>
    <div className="kb-chat-quick">{QUICK.map((prompt) => <button key={prompt} type="button" onClick={() => setText(prompt)}>{prompt}</button>)}</div>
    <form onSubmit={send}>
      <label className="sr-only" htmlFor="kb-chat-input">자리매김 AI에게 질문하기</label>
      <input id="kb-chat-input" value={text} onChange={(event) => setText(event.target.value)} placeholder="후보나 근거에 대해 물어보세요" />
      <button disabled={!text.trim() || flow.chatBusy} aria-label="보내기"><Send aria-hidden="true" /></button>
    </form>
    <small className="kb-chat-guard">AI는 설명만 합니다. 조건과 계산값은 바꾸지 않습니다.</small>
  </aside>;
}
