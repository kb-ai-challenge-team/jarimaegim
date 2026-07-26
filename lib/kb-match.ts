import type { CaseInput, KbProduct } from "./types";

/**
 * Ranks KB products against the confirmed case conditions.
 *
 * This is a text overlap between what the user entered and what the FSS disclosure says — never an
 * eligibility or approval judgement. Rules stay in code (not the model) so every surfaced reason is
 * reproducible, and each match carries the reason that produced it so the UI can show its working.
 *
 * Deliberately NOT matched: products gated on KB's own assessment (e.g. 우수상권·우수기술기업 우대),
 * because our location evidence is grade C and cannot stand in for the bank's criteria.
 */
export interface KbMatch { product: KbProduct; reasons: string[]; score: number }

/** Case-specific overlaps outrank blanket ones, so a franchise case ranks 프랜차이즈 above generic 소호. */
const WEIGHTS: Record<string, number> = { specific: 3, gap: 2, generic: 1 };

const MEDICAL = /의료|병원|약국|치과|한의원|동물병원|의원/;
const BANK_ASSESSED = /우수상권|우수기술|우량|미래성장|유망분야|사회적경제|동반성장|상생|수출|산업단지|지식산업센터/;

/** Upper bound of a disclosed 한도 string such as "1억원~5억원" or "5억원 초과". Null when not disclosed. */
export function parseLimitKrw(limit: string | null | undefined): number | null {
  if (!limit) return null;
  const parts = [...limit.matchAll(/(\d+(?:\.\d+)?)\s*(억|천만|백만|만)\s*원?/g)]
    .map((match) => Number(match[1]) * ({ 억: 100_000_000, 천만: 10_000_000, 백만: 1_000_000, 만: 10_000 }[match[2]] ?? 1));
  if (parts.length === 0) return null;
  const upper = Math.max(...parts);
  return /초과|이상/.test(limit) ? Number.POSITIVE_INFINITY : upper;
}

export function matchKbProducts(products: KbProduct[], inputs: CaseInput, gapKrw: number | null): KbMatch[] {
  const matches: KbMatch[] = [];
  for (const product of products) {
    if (product.category !== "BUSINESS_LOAN") continue;
    const reasons: string[] = [];
    const name = product.name;
    let score = 0;
    const add = (reason: string, weight: number) => { reasons.push(reason); score += weight; };

    if (inputs.startup_type === "FRANCHISE" && /프랜차이즈/.test(name)) add("창업형태 프랜차이즈", WEIGHTS.specific);
    if (MEDICAL.test(inputs.industry) && /메디칼/.test(name)) add(`업종 ${inputs.industry}`, WEIGHTS.specific);
    const limit = parseLimitKrw(product.loan_limit);
    if (gapKrw !== null && gapKrw > 0 && limit !== null && limit >= gapKrw) add("조달 차이가 공시 한도 이내", WEIGHTS.gap);
    if (/소상공인|소호|사장님/.test(name)) add("소상공인·소호 대상", WEIGHTS.generic);
    if (/인터넷|스마트폰/.test(product.join_way || "")) add("비대면 가입 가능", WEIGHTS.generic);

    // Bank-assessed products only surface alongside another match, never on their own.
    if (reasons.length === 0) continue;
    if (BANK_ASSESSED.test(name) && reasons.length < 2) continue;
    matches.push({ product, reasons, score });
  }

  return matches.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    const rateA = a.product.rate_min ?? Number.POSITIVE_INFINITY;
    const rateB = b.product.rate_min ?? Number.POSITIVE_INFINITY;
    if (rateA !== rateB) return rateA - rateB;
    return a.product.name.localeCompare(b.product.name, "ko-KR");
  });
}
