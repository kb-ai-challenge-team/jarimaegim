/** 4,580,000 → "458만". The map pins and the candidate cards must agree, so this lives in one place. */
export function manwon(krw: number): string {
  return `${Math.round(krw / 10_000).toLocaleString("ko-KR")}만`;
}
