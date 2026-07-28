import { SEOUL_DISTRICTS } from "./constants";
import type { CaseInput, Program } from "./types";

/**
 * Ranks public support notices against the confirmed case.
 *
 * Like `kb-match`, this is a text overlap between what the user entered and what the notice says —
 * never an eligibility judgement. The catalog endpoint returns the whole country's notices, so the
 * prescription would otherwise show 전북 마을기업 and 해외 박람회 to a 마포구 카페.
 *
 * Two rules do the work:
 *   1. 다른 광역자치단체가 제목·기관에 명시되면 제외한다. 서울 창업자가 받을 수 없는 공고다.
 *   2. 가점이 하나도 없으면 표시하지 않는다. "관련 있다고 말할 근거가 없다"는 뜻이므로,
 *      추천이 아니라 목록 나열이 된다.
 * 전국 단위 공고는 지역 표시가 없으므로 1에 걸리지 않고 2에서만 판정된다.
 */
export interface ProgramMatch { program: Program; reasons: string[]; score: number }

/** 서울을 제외한 16개 광역자치단체. 표기 흔들림(전남광주·전북특별자치도)을 흡수하려고 어간으로 둔다. */
const OTHER_REGIONS = [
  "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
  "충북", "충남", "전북", "전남", "경북", "경남", "제주", "충청", "전라", "경상"
];

const SEOUL = /서울/;
const STARTUP = /창업|소상공인|소호|자영업|점포|상가|개업/;
const FUNDING = /자금|융자|보증|이차보전|대출|지원금|보조금/;
const RENT = /임차|임대료|월세|보증금/;

/** 서울 25개 자치구 중 케이스의 자치구가 제목·기관에 직접 나오는지. */
function mentionsDistrict(text: string, district: string) {
  if (!district) return false;
  const stem = district.replace(/구$/, "");
  return text.includes(district) || (stem.length >= 2 && text.includes(stem));
}

/** 다른 광역자치단체가 명시됐는지. 서울이 함께 적혀 있으면 광역 공동 공고로 보고 제외하지 않는다. */
export function belongsToAnotherRegion(text: string) {
  if (SEOUL.test(text)) return false;
  return OTHER_REGIONS.some((region) => text.includes(region));
}

/** 다른 자치구 전용 공고인지. "종로구 중소기업육성기금"은 서울 공고지만 강남구 창업자는 받을 수 없다.
 *  어간이 아니라 전체 이름으로만 판정한다 — "중구"의 어간 "중"은 흔한 말에 걸린다. */
export function belongsToAnotherDistrict(text: string, district: string) {
  const named = SEOUL_DISTRICTS.filter((item) => text.includes(item));
  return named.length > 0 && !named.includes(district as (typeof SEOUL_DISTRICTS)[number]);
}

export function matchPrograms(programs: Program[], inputs: CaseInput): ProgramMatch[] {
  const matches: ProgramMatch[] = [];
  for (const program of programs) {
    const text = `${program.title} ${program.organization}`;
    if (belongsToAnotherRegion(text)) continue;
    if (belongsToAnotherDistrict(text, inputs.district)) continue;

    const reasons: string[] = [];
    let score = 0;
    const add = (reason: string, weight: number) => { reasons.push(reason); score += weight; };

    if (mentionsDistrict(text, inputs.district)) add(`${inputs.district} 명시`, 4);
    else if (SEOUL.test(text)) add("서울 대상", 3);
    if (inputs.industry.trim() && text.includes(inputs.industry.trim())) add(`업종 ${inputs.industry}`, 3);
    if (STARTUP.test(text)) add("창업·소상공인 대상", 2);
    // 조달선을 밀어올리는 자금 수단은 이 화면의 주제 자체다.
    if (FUNDING.test(text)) add("자금·보증 지원", 2);
    if (RENT.test(text)) add("임차 비용 지원", 2);

    if (reasons.length === 0) continue;
    matches.push({ program, reasons, score });
  }

  return matches.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.program.title.localeCompare(b.program.title, "ko-KR");
  });
}
