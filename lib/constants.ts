import type { CaseInput } from "./types";

export const SEOUL_DISTRICTS = [
  "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구",
  "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구",
  "관악구", "서초구", "강남구", "송파구", "강동구"
] as const;

export const DEFAULT_CASE: CaseInput = {
  industry: "",
  district: "마포구",
  budget_krw: 0,
  equity_krw: 0,
  business_stage: "PRE_OPEN",
  startup_type: "UNDECIDED",
  priority: "STABILITY"
};

/** 금융 프로필. 후보의 성질이 아니라 사용자의 성질이므로 케이스 조건과 분리해 한 번만 확정한다.
 *  마이데이터가 열리면 같은 스키마를 자동으로 채운다 — 게이트가 닫혀 있으면 수동 입력이 채운다. */
export const DEFAULT_PROFILE = {
  equity_krw: 0,
  existing_debt_krw: 0,
  other_monthly_fixed_krw: 0
};

/** 임대 조건. 월세만 밴드를 바꾸고, 나머지는 필요자금(→현금소진)에만 관여한다.
 *  null 은 "아직 모른다"이고 0 과 다르다 — null 이면 계산하지 않고, 0 이면 0 으로 계산한다. */
export const DEFAULT_BAND_FORM = {
  area_pyeong: null as number | null,
  deposit_krw: null as number | null,
  monthly_rent_krw: 0,
  monthly_maintenance_krw: 0,
  key_money_krw: 0,
  fitout_krw: null as number | null
};

export const STAGE_LABELS = {
  PRE_OPEN: "처음 창업",
  RELOCATING: "운영 중 이전",
  SECOND_STORE: "2호점 준비"
} as const;

export const TYPE_LABELS = {
  INDEPENDENT: "개인 창업",
  FRANCHISE: "프랜차이즈",
  UNDECIDED: "아직 미정"
} as const;

export const PRIORITY_LABELS = {
  STABILITY: "안정성",
  DEMAND: "수요",
  COST: "비용",
  GROWTH: "성장"
} as const;

export const EVIDENCE_BADGES = {
  A: "근거 A",
  B: "근거 B",
  C: "근거 C",
  U: "근거 U"
} as const;

export const PROGRAM_CATEGORY_LABELS = {
  GOVERNMENT: "정부지원",
  POLICY_FUND: "정책자금",
  GUARANTEE: "지역보증",
  PRIVATE: "민간금융"
} as const;

export const EVIDENCE_LABELS = {
  A: "개별 이력 기반 생존 진단",
  B: "상권 위험 진단",
  C: "입지 환경 신호",
  U: "현재 조건으로 분석 불가"
} as const;

export const SIGNAL_LABELS: Record<string, string> = {
  demand: "수요",
  competition: "경쟁",
  cost: "비용",
  access: "접근성",
  continuity: "지속성"
};

export function formatKrw(value: number) {
  if (!Number.isFinite(value)) return "—";
  if (value >= 100_000_000) return `${(value / 100_000_000).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}억 원`;
  if (value >= 10_000) return `${Math.round(value / 10_000).toLocaleString("ko-KR")}만 원`;
  return `${value.toLocaleString("ko-KR")}원`;
}

// backend/app/chat_tools.py's citation()/collected_at is `datetime.now(UTC).isoformat()` -- raw
// ISO-8601 with microseconds and a UTC offset, unreadable as-is. Renders as a KST calendar date
// (not a timestamp): this value marks when a lookup was collected, and a user doesn't need
// minute-level precision for that -- but Korean users do read dates in KST, so rendering the raw
// UTC instant's date risks the displayed day being off by one near midnight. Never throws and
// never invents a date: a missing, empty, or unparseable value falls back to the same "미수집"
// register already used where this field has no value.
export function formatCollectedAt(value?: string | null) {
  if (!value) return "미수집";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "미수집";
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "long", day: "numeric", timeZone: "Asia/Seoul" }).format(parsed);
}
