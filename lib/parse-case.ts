import { SEOUL_DISTRICTS } from "./constants";
import type { CaseInput } from "./types";

// Reads a free-form Korean sentence into case conditions. Every field it fills is shown back to the
// user for confirmation before a case is created — nothing here is applied silently.

const INDUSTRY_HINTS: [RegExp, string][] = [
  [/카페|커피|coffee/i, "카페"], [/베이커리|빵집|제과/, "제과점"], [/치킨/, "치킨전문점"], [/분식/, "분식점"],
  [/술집|주점|호프|이자카야|와인바/, "주점"], [/편의점/, "편의점"], [/미용실|헤어|미용/, "미용실"],
  [/네일|속눈썹/, "네일샵"], [/학원|공부방|교습소/, "학원"], [/세탁/, "세탁소"], [/피시방|PC방/i, "PC방"],
  [/무인|셀프\s*빨래/, "무인점포"], [/음식점|식당|밥집|한식|중식|일식|양식/, "일반음식점"]
];
const UNITS: Record<string, number> = { 억: 100_000_000, 천만: 10_000_000, 백만: 1_000_000, 만: 10_000 };
const EQUITY_HINT = /(자기\s*자본|자본금|보유|모아둔|모은|가진|가지고|여유|현금)/;
const AMOUNT = /(\d+(?:[.,]\d+)?)\s*(억|천만|백만|만)\s*원?/g;

function toKrw(value: string, unit: string) { return Math.round(Number(value.replace(/,/g, "")) * (UNITS[unit] ?? 1)); }

/** Returns only the fields the sentence actually mentioned, so the caller can highlight what changed. */
export function parseCaseText(text: string): Partial<CaseInput> {
  const patch: Partial<CaseInput> = {};
  // 전체 이름을 먼저 찾고, 없을 때만 "마포에서"처럼 구를 뗀 어간을 본다. 어간이 한 글자인 중구는
  // "준비 중이에요"의 "중"에 걸려 자치구를 통째로 잘못 채우므로 어간 검색에서 제외한다.
  const district = SEOUL_DISTRICTS.find((item) => text.includes(item))
    ?? SEOUL_DISTRICTS.find((item) => { const stem = item.replace(/구$/, ""); return stem.length >= 2 && text.includes(stem); });
  if (district) patch.district = district;

  const industry = INDUSTRY_HINTS.find(([pattern]) => pattern.test(text));
  if (industry) patch.industry = industry[1];
  else {
    const named = text.match(/([가-힣A-Za-z]{2,10})\s*(?:을|를|)\s*(?:창업|개업|오픈|차리|열려|열고|준비)/);
    if (named?.[1]) patch.industry = named[1];
  }

  for (const match of text.matchAll(AMOUNT)) {
    const amount = toKrw(match[1], match[2]);
    if (!Number.isFinite(amount) || amount <= 0) continue;
    const lead = text.slice(Math.max(0, (match.index ?? 0) - 14), match.index ?? 0);
    if (EQUITY_HINT.test(lead)) patch.equity_krw = amount;
    else if (patch.budget_krw === undefined) patch.budget_krw = amount;
    else if (patch.equity_krw === undefined) patch.equity_krw = amount;
  }

  if (/이전|옮기|이사/.test(text)) patch.business_stage = "RELOCATING";
  else if (/2호점|두\s*번째|분점|추가\s*매장/.test(text)) patch.business_stage = "SECOND_STORE";
  else if (/처음|첫\s*가게|초보|신규/.test(text)) patch.business_stage = "PRE_OPEN";

  if (/프랜차이즈|가맹/.test(text)) patch.startup_type = "FRANCHISE";
  else if (/개인\s*창업|독립|자체\s*브랜드/.test(text)) patch.startup_type = "INDEPENDENT";

  if (/안정|오래|버티|리스크|위험/.test(text)) patch.priority = "STABILITY";
  else if (/유동인구|손님|수요|매출/.test(text)) patch.priority = "DEMAND";
  else if (/저렴|싼|비용|임대료|월세\s*낮/.test(text)) patch.priority = "COST";
  else if (/성장|확장|뜨는|상권\s*발전/.test(text)) patch.priority = "GROWTH";

  return patch;
}
