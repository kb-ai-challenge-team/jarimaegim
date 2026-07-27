import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { AREA_BANDS, ASSUMED_DEPOSIT_MULTIPLE, LISTINGS_PER_DISTRICT, SYNTHESIS_SEED, TARGET_DISTRICTS, bandForArea } from "../lib/constants.mjs";
import { sampleFromQuantiles } from "../lib/quantile.mjs";
import { createRng, shuffle } from "../lib/rng.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const DISTRIBUTION_PATH = join(ROOT, "data", "rent-distribution.seoul.json");
const OUTPUT = join(ROOT, "data", "listings.seoul.json");

const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
const roundTo = (value, unit) => Math.round(value / unit) * unit;

/**
 * Rounds to a multiple of unit without letting the result fall outside [low, high].
 * Clamping then rounding could push the result past the upper bound, so the bounds
 * themselves are narrowed to unit first.
 * If the range is narrower than unit, it snaps to the lower bound (real rent bands are
 * in the millions of won, so this case doesn't come up).
 */
function roundWithin(value, unit, low, high) {
  const lowUnit = Math.ceil(low / unit) * unit;
  const highUnit = Math.floor(high / unit) * unit;
  if (lowUnit > highUnit) return lowUnit;
  return clamp(roundTo(value, unit), lowUnit, highUnit);
}

/**
 * Draws an area from the district's area distribution.
 * Redraws if the result equals forbidden (the area that coordinate originally had).
 * This is the 1:1 correspondence block from design doc §2.1.
 */
export function sampleArea(areaSet, rng, forbidden) {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const drawn = Number(clamp(sampleFromQuantiles(areaSet, rng), areaSet.p10, areaSet.p90).toFixed(1));
    if (forbidden === null || drawn !== forbidden) return drawn;
  }
  // Extreme case where the distribution is collapsed to a single point. Nudge by the minimum unit to force the collision to break.
  const nudged = Number((clamp(forbidden + 0.1, areaSet.p10, areaSet.p90 + 0.1)).toFixed(1));
  return nudged === forbidden ? Number((forbidden + 0.1).toFixed(1)) : nudged;
}

/** Picks the band closest to the requested one among those actually present in the distribution. */
function resolveBand(bands, areaM2) {
  const preferred = bandForArea(areaM2).key;
  if (bands[preferred]) return bands[preferred];
  const order = AREA_BANDS.map((band) => band.key);
  const start = order.indexOf(preferred);
  for (let distance = 1; distance < order.length; distance += 1) {
    const lower = bands[order[start - distance]];
    if (lower) return lower;
    const higher = bands[order[start + distance]];
    if (higher) return higher;
  }
  throw new Error("사용 가능한 면적구간이 없습니다");
}

export function buildListings({ distribution, coordsByDistrict, perDistrict }) {
  const rng = createRng(SYNTHESIS_SEED);
  const listings = [];
  for (const district of Object.keys(coordsByDistrict)) {
    const profile = distribution.districts[district];
    if (!profile) throw new Error(`${district}의 분포가 없습니다`);
    const pool = shuffle(coordsByDistrict[district], rng).slice(0, perDistrict);
    pool.forEach((record, index) => {
      const areaM2 = sampleArea(profile.area, rng, record.area_m2);
      const band = resolveBand(profile.bands, areaM2);
      const rentRaw = sampleFromQuantiles(band.monthly_rent_krw, rng);
      const monthlyRent = roundWithin(rentRaw, 10_000, band.monthly_rent_krw.p10, band.monthly_rent_krw.p90);
      const multiple = ASSUMED_DEPOSIT_MULTIPLE.min + rng() * (ASSUMED_DEPOSIT_MULTIPLE.max - ASSUMED_DEPOSIT_MULTIPLE.min);
      const deposit = Math.max(roundTo(monthlyRent * multiple, 1_000_000), 1_000_000);
      listings.push({
        id: `demo-${district}-${String(index + 1).padStart(4, "0")}`,
        name: `${record.dong} ${record.floor}층 상가`,
        address: `서울 ${district} ${record.dong}`,
        district,
        latitude: record.lat,
        longitude: record.lng,
        _band_label: band.label,
        listing: {
          listing_kind: "DEMO_SYNTHETIC",
          deposit_krw: deposit,
          monthly_rent_krw: monthlyRent,
          maintenance_fee_krw: roundTo(monthlyRent * 0.08, 10_000),
          area_m2: areaM2,
          floor: record.floor,
        },
      });
    });
  }
  return listings;
}

async function readCoords() {
  const byDistrict = {};
  for (const district of TARGET_DISTRICTS) {
    const text = await fs.readFile(join(RAW_DIR, `coords.${district}.jsonl`), "utf8");
    byDistrict[district] = text.trim().split("\n").map((line) => JSON.parse(line));
  }
  return byDistrict;
}

async function main() {
  const distribution = JSON.parse(await fs.readFile(DISTRIBUTION_PATH, "utf8"));
  const listings = buildListings({
    distribution, coordsByDistrict: await readCoords(), perDistrict: LISTINGS_PER_DISTRICT,
  });
  const payload = {
    generated_at: new Date().toISOString(),
    seed: SYNTHESIS_SEED,
    listing_kind: "DEMO_SYNTHETIC",
    notice: "시연용 생성 데이터입니다. 실제 임대 매물이 아니며 계약 대상이 아닙니다.",
    method: "위치는 실제 상가 좌표이나 면적·보증금·월세는 시세 분포에서 독립 샘플링한 값입니다.",
    deposit_basis: "보증금은 실측이 아니라 월세의 10~20배라는 관행 배수를 가정해 산출한 값입니다.",
    listings: listings.map(({ _band_label, ...rest }) => rest),
  };
  await fs.mkdir(dirname(OUTPUT), { recursive: true });
  await fs.writeFile(OUTPUT, JSON.stringify(payload, null, 2) + "\n");
  console.log(`매물 합성 완료: ${OUTPUT} (${listings.length}건)`);
}

// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
