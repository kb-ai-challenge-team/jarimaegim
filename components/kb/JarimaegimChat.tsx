"use client";

import { useEffect, useRef, useState } from "react";
import { LoaderCircle, Send } from "lucide-react";
import type { Jarimaegim } from "@/lib/use-jarimaegim";

const QUICK = ["확인하지 못한 정보는?", "다음에 뭘 해야 해?", "근거 출처를 알려줘"];

/** Right-docked conversation column. Explains only — it can never mutate case conditions. */
export function JarimaegimChat({ flow }: { flow: Jarimaegim }) {
  const [text, setText] = useState("");
  const logRef = useRef<HTMLDivElement>(null);
  const history = flow.messages.slice(1);
  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [history.length, flow.chatBusy]);
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
        
      </div>)}
      {flow.chatBusy && <div className="kb-chat-message kb-chat-assistant kb-chat-pending"><LoaderCircle className="kb-spin" aria-hidden="true" /> 공식 근거를 확인하고 있습니다.</div>}
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
