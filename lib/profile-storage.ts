import { DEFAULT_PROFILE } from "./constants";

export type Profile = typeof DEFAULT_PROFILE;

// 금융 프로필은 사용자의 성질이라 세션보다 오래 산다. 익명 세션(24시간)이 만료됐다고
// 자기자본을 다시 묻는 것은 사용자 입장에서 같은 질문의 반복이므로 브라우저에 남긴다.
// 서버로는 여전히 케이스를 만드는 순간에만 보내고, 여기서는 이 브라우저 밖으로 나가지 않는다.
const KEY = "jarimaegim.profile.v1";

// 서버(models.py CaseInput/FundingBandInput)와 같은 상한. 저장소는 사용자가 직접 고칠 수
// 있으므로 읽을 때마다 검증한다 — 저장된 값을 믿고 그대로 쓰면 조작된 값이 계산에 들어간다.
const MAX_KRW = 100_000_000_000;

function sane(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (value < 0 || value > MAX_KRW) return null;
  return Math.round(value);
}

/** 저장된 프로필. 없거나 한 항목이라도 형태가 어긋나면 null 을 돌려주고 처음부터 받는다. */
export function loadProfile(): Profile | null {
  if (typeof window === "undefined") return null;
  let raw: string | null = null;
  try { raw = window.localStorage.getItem(KEY); } catch { return null; }
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const source = parsed as Record<string, unknown>;
    const profile = {} as Profile;
    for (const key of Object.keys(DEFAULT_PROFILE) as (keyof Profile)[]) {
      const value = sane(source[key]);
      if (value === null) return null;
      profile[key] = value;
    }
    // 자기자본이 0이면 밴드를 계산할 수 없다. 확정된 적 없는 값이므로 복원하지 않는다.
    return profile.equity_krw > 0 ? profile : null;
  } catch { return null; }
}

/** 저장은 실패해도 흐름을 막지 않는다 — 시크릿 모드·저장소 차단에서는 그냥 세션 동안만 유지된다. */
export function saveProfile(profile: Profile): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(KEY, JSON.stringify(profile)); } catch { /* 저장 불가는 무시한다 */ }
}

export function clearProfile(): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(KEY); } catch { /* 삭제 불가는 무시한다 */ }
}
