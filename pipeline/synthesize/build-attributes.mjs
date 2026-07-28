import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  ASSUMED_ATTRIBUTES_NOTICE, ASSUMED_AVAILABLE_IN_DAYS, ASSUMED_BUILT_YEAR, ASSUMED_CORNER_SHARE,
  ASSUMED_ELEVATOR_SHARE, ASSUMED_EXCLUSIVE_RATIO, ASSUMED_FLOORS_TOTAL, ASSUMED_FRONTAGE,
  ASSUMED_KEY_MONEY, ASSUMED_PARKING_SLOTS, ATTRIBUTE_BASE_DATE, ATTRIBUTE_SEED,
} from "../lib/attribute-constants.mjs";
import { createRng } from "../lib/rng.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const LISTINGS_PATH = join(ROOT, "data", "listings.seoul.json");

const lerp = (rng, { min, max }) => min + rng() * (max - min);
const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
const roundTo = (value, unit) => Math.round(value / unit) * unit;

/**
 * 매물 id 로부터 고정 시드를 만든다.
 *
 * 매물 하나의 속성이 그 매물의 id 에만 의존해야, 매물을 추가하거나 순서를 바꿔도 기존
 * 매물의 속성이 따라 바뀌지 않는다. 배열 순서로 rng 를 흘리면 그 성질이 깨진다.
 */
export function seedFor(id) {
  let hash = ATTRIBUTE_SEED;
  for (let index = 0; index < id.length; index += 1) hash = (Math.imul(hash, 31) + id.charCodeAt(index)) | 0;
  return hash >>> 0;
}

/** 가중 추첨. 항목은 [값, 가중치]. */
export function weightedPick(entries, rng) {
  const total = entries.reduce((sum, [, weight]) => sum + weight, 0);
  let target = rng() * total;
  for (const [value, weight] of entries) {
    target -= weight;
    if (target <= 0) return value;
  }
  return entries[entries.length - 1][0];
}

function addDays(isoDate, days) {
  const date = new Date(`${isoDate}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/**
 * 매물 하나의 부가 속성. 전부 가정값이다 — `pipeline/lib/attribute-constants.mjs` 참조.
 *
 * 임대 조건(보증금·월세·관리비·면적·층)은 건드리지 않는다. 그 값들은 서울교통공사 실측
 * 분포에서 나온 것이고, 여기서 덮으면 어느 숫자가 어디서 왔는지 알 수 없게 된다.
 */
export function attributesFor(listing) {
  const rng = createRng(seedFor(listing.id));
  const terms = listing.listing;

  // 권리금. 일부는 무권리다.
  const keyMoney = rng() < ASSUMED_KEY_MONEY.zeroShare
    ? 0
    : Math.max(1_000_000, roundTo(terms.monthly_rent_krw * lerp(rng, ASSUMED_KEY_MONEY.multiple), 1_000_000));

  const exclusiveArea = Number((terms.area_m2 * lerp(rng, ASSUMED_EXCLUSIVE_RATIO)).toFixed(1));
  const builtYear = Math.round(lerp(rng, ASSUMED_BUILT_YEAR));
  const parkingSlots = weightedPick(ASSUMED_PARKING_SLOTS, rng);
  const corner = rng() < ASSUMED_CORNER_SHARE;
  const elevator = rng() < ASSUMED_ELEVATOR_SHARE;
  const floorsTotal = Math.max(terms.floor, Math.round(lerp(rng, ASSUMED_FLOORS_TOTAL)));
  const frontage = Number(clamp(
    Math.sqrt(terms.area_m2) * lerp(rng, ASSUMED_FRONTAGE.coefficient),
    ASSUMED_FRONTAGE.min, ASSUMED_FRONTAGE.max,
  ).toFixed(1));
  const availableFrom = addDays(ATTRIBUTE_BASE_DATE, Math.round(lerp(rng, ASSUMED_AVAILABLE_IN_DAYS)));

  return {
    key_money_krw: keyMoney,
    exclusive_area_m2: exclusiveArea,
    built_year: builtYear,
    parking_slots: parkingSlots,
    corner,
    elevator,
    floors_total: floorsTotal,
    frontage_m: frontage,
    available_from: availableFrom,
  };
}

export function attachAttributes(listings) {
  return listings.map((listing) => ({
    ...listing,
    listing: { ...listing.listing, ...attributesFor(listing) },
  }));
}

async function main() {
  const payload = JSON.parse(await fs.readFile(LISTINGS_PATH, "utf8"));
  const listings = attachAttributes(payload.listings ?? []);
  const next = {
    ...payload,
    // 기존 `assumed` 문구는 보증금·관리비·층만 다룬다. 새 가정을 같은 자리에 붙여
    // 화면과 PDF 가 한 문장으로 전부 고지하게 한다.
    assumed_attributes: ASSUMED_ATTRIBUTES_NOTICE,
    listings,
  };
  await fs.writeFile(LISTINGS_PATH, JSON.stringify(next, null, 2) + "\n");

  const withKeyMoney = listings.filter((listing) => listing.listing.key_money_krw > 0).length;
  console.log(`부가 속성 부착: ${listings.length}건 → ${LISTINGS_PATH}`);
  console.log(`  권리금 있음 ${withKeyMoney}건 · 무권리 ${listings.length - withKeyMoney}건`);
}

// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
