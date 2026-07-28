import { SEOUL_DISTRICTS } from "./constants";
import type { CaseInput, Program } from "./types";

/**
 * Ranks public support notices against the confirmed case.
 *
 * Like `kb-match`, this is a text overlap between what the user entered and what the notice says —
 * never an eligibility judgement. The catalog endpoint returns the whole country's notices, so the
 * prescription would otherwise show 전북 마을기업 and 해외 박람회 to a 마포구 카페.
 *
 * 본문을 한 덩어리로 훑지 않는다. 그렇게 하면 "소상공인"이라는 낱말이 어디에 한 번 스치기만 해도
 * 부산 투자경진대회에 "소상공인 대상"이 붙는다. 본문은 `지원분야 금융 지원대상 소상공인` 처럼
 * 라벨-값 구조를 갖고 있으므로 필드를 뽑아 그 값으로 판정한다.
 *
 * 원천이 라벨을 주지 않으면 그 축은 없는 것으로 두고 다른 축으로만 판정한다 — 추정하지 않는다.
 */
export interface ProgramMatch { program: Program; reasons: string[]; score: number }

/** 서울을 제외한 광역자치단체. 표기 흔들림(전남광주·전북특별자치도)을 흡수하려고 어간으로 둔다. */
const OTHER_REGIONS = [
  "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
  "충북", "충남", "전북", "전남", "경북", "경남", "제주", "충청", "전라", "경상"
];

const SEOUL = /서울/;
const NATIONWIDE = /전국/;
const RENT = /임차|임대료|월세|보증금/;

/** 추천이라 부를 최소치. 지역 하나 또는 넓은 대상 하나만 걸린 공고는 여기서 떨어진다. */
const MIN_SCORE = 4;

// 본문 라벨. 값의 끝을 찾으려면 "다음 라벨이 어디서 시작하는가"를 알아야 한다.
const LABELS = ["소관", "수행", "지원분야", "지원지역", "지원대상", "신청대상", "신청방법", "지원내용"];

/**
 * 점포를 여는 사람에게 실제로 쓸모 있는 지원분야만 남긴다.
 * 수출·기술·인력·판로처럼 다른 종류의 기업을 향한 분야는 제외한다 — 카페 창업자가
 * 검토할 이유가 없고, 남겨 두면 상위 3건을 그런 공고가 차지한다.
 */
const FIELD_WEIGHTS: { pattern: RegExp; label: string; weight: number }[] = [
  { pattern: /금융/, label: "금융 지원", weight: 4 },
  { pattern: /창업/, label: "창업 지원", weight: 3 },
  { pattern: /시설|공간|보육/, label: "시설·공간 지원", weight: 3 },
  { pattern: /경영|내수/, label: "경영·내수 지원", weight: 1 }
];

/** 지원대상. 소상공인이 가장 강하고, 중소기업은 넓은 범주라 약하게만 센다. */
const TARGET_WEIGHTS: { pattern: RegExp; label: string; weight: number }[] = [
  { pattern: /소상공인|자영업|소공인/, label: "소상공인 대상", weight: 4 },
  { pattern: /창업벤처|창업기업|예비창업/, label: "창업기업 대상", weight: 2 },
  { pattern: /중소기업/, label: "중소기업 대상", weight: 1 }
];

/** 라벨 뒤부터 다음 라벨 앞까지의 값. 라벨이 없으면 null 이고, 그 축은 판정에서 빠진다. */
export function bodyField(body: string, label: string): string | null {
  const others = LABELS.filter((item) => item !== label).join("|");
  const match = new RegExp(`(?:^|\\s)${label}\\s+([\\s\\S]*?)(?=\\s(?:${others})\\s|$)`).exec(body);
  const value = match?.[1]?.trim();
  return value ? value : null;
}

export type RegionVerdict = "seoul" | "nationwide" | "other" | "unknown";

/**
 * 이 공고가 서울 창업자에게 열려 있는지.
 * `regions` 가 있으면 그것만 본다 — 원천이 지역을 말해 준 이상 글자 대조로 뒤집지 않는다.
 */
export function regionVerdict(regions: string[] | null | undefined, text: string): RegionVerdict {
  const declared = (regions ?? []).filter((item) => item && item.trim());
  if (declared.length > 0) {
    if (declared.some((item) => SEOUL.test(item))) return "seoul";
    if (declared.some((item) => NATIONWIDE.test(item))) return "nationwide";
    return "other";
  }
  if (SEOUL.test(text)) return "seoul";
  if (NATIONWIDE.test(text)) return "nationwide";
  if (OTHER_REGIONS.some((region) => text.includes(region))) return "other";
  return "unknown";
}

/** 다른 자치구 전용 공고인지. "종로구 중소기업육성기금"은 서울 공고지만 강남구 창업자는 받을 수 없다.
 *  어간이 아니라 전체 이름으로만 판정한다 — "중구"의 어간 "중"은 흔한 말에 걸린다. */
export function belongsToAnotherDistrict(text: string, district: string) {
  const named = SEOUL_DISTRICTS.filter((item) => text.includes(item));
  return named.length > 0 && !named.includes(district as (typeof SEOUL_DISTRICTS)[number]);
}

export function matchPrograms(programs: Program[], inputs: CaseInput): ProgramMatch[] {
  const matches: ProgramMatch[] = [];
  const industry = inputs.industry.trim();

  for (const program of programs) {
    const body = program.match_text ?? "";
    const heading = `${program.title} ${program.organization}`;
    const verdict = regionVerdict(program.regions, `${heading} ${body}`);
    if (verdict === "other") continue;
    if (belongsToAnotherDistrict(heading, inputs.district)) continue;

    // 지원분야가 있는데 쓸모 있는 분야가 아니면 여기서 끝난다. 수출·기술 공고가 상위를 차지하던 원인이다.
    const area = bodyField(body, "지원분야");
    const areaHit = area ? FIELD_WEIGHTS.find((item) => item.pattern.test(area)) : null;
    if (area && !areaHit) continue;

    const reasons: string[] = [];
    let score = 0;
    const add = (reason: string, weight: number) => { reasons.push(reason); score += weight; };

    if (heading.includes(inputs.district)) add(`${inputs.district} 대상`, 4);
    else if (verdict === "seoul") add("서울 대상", 3);
    else if (verdict === "nationwide") add("전국 대상", 1);

    if (areaHit) add(areaHit.label, areaHit.weight);

    const target = bodyField(body, "지원대상") ?? bodyField(body, "신청대상");
    const targetHit = target ? TARGET_WEIGHTS.find((item) => item.pattern.test(target)) : null;
    if (targetHit) add(targetHit.label, targetHit.weight);

    if (industry && `${heading} ${body}`.includes(industry)) add(`업종 ${industry}`, 3);
    if (RENT.test(heading)) add("임차 비용 지원", 2);

    // 근거가 하나 붙었다고 추천은 아니다. 자리를 채우려고 약한 것을 끌어올리면
    // "상위 3건"이라는 말이 "그나마 나은 3건"이 된다. 문턱을 못 넘으면 빈 상태로 둔다.
    if (score < MIN_SCORE) continue;
    matches.push({ program, reasons, score });
  }

  return matches.sort((a, b) => {
    if (b.score !== a.score) return b.score - a.score;
    return a.program.title.localeCompare(b.program.title, "ko-KR");
  });
}
