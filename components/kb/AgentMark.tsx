/**
 * 자리매김 AI 마크 — 자리(핀)를 궤도가 감싸는 형태. 실행 중에는 궤도가 돌고, 결과가 나오면 멈춘다.
 * 상태를 색과 정지 여부로만 표현해 모션이 꺼진 환경에서도 의미가 사라지지 않는다.
 */
export function AgentMark({ state, size = 44 }: { state: "running" | "done" | "failed"; size?: number }) {
  return <svg className="kb-mark" data-state={state} width={size} height={size} viewBox="0 0 56 56" role="img" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="kbMarkCore" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#7b5cff" /><stop offset="55%" stopColor="#3d8bff" /><stop offset="100%" stopColor="#22c9d9" />
      </linearGradient>
      <linearGradient id="kbMarkDone" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#ffcc00" /><stop offset="100%" stopColor="#f0a500" />
      </linearGradient>
      <linearGradient id="kbMarkFail" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stopColor="#e05252" /><stop offset="100%" stopColor="#c82323" />
      </linearGradient>
      <radialGradient id="kbMarkGlow">
        <stop offset="40%" stopColor="currentColor" stopOpacity=".22" /><stop offset="100%" stopColor="currentColor" stopOpacity="0" />
      </radialGradient>
    </defs>
    <circle className="kb-mark-glow" cx="28" cy="28" r="27" fill="url(#kbMarkGlow)" />
    <circle className="kb-mark-ring kb-mark-ring-a" cx="28" cy="28" r="23" />
    <circle className="kb-mark-ring kb-mark-ring-b" cx="28" cy="28" r="17.5" />
    <g className="kb-mark-orbit"><circle className="kb-mark-sat" cx="28" cy="4.5" r="2.8" /></g>
    <g className="kb-mark-pin">
      <path d="M28 13.5c4.7 0 8.5 3.8 8.5 8.5 0 6.2-8.5 15-8.5 15s-8.5-8.8-8.5-15c0-4.7 3.8-8.5 8.5-8.5Z" />
      <circle cx="28" cy="21.8" r="3.1" fill="#fff" />
    </g>
  </svg>;
}
