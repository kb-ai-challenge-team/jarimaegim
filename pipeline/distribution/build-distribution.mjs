import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AREA_BANDS, MIN_BAND_SAMPLES, TARGET_DISTRICTS, bandForArea } from "../lib/constants.mjs";
import { quantileSet } from "../lib/quantile.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const OUTPUT = join(ROOT, "data", "rent-distribution.seoul.json");

/**
 * Reduce price samples to per-district area quantiles and per-band rent and
 * deposit-multiple quantiles. Bands below MIN_BAND_SAMPLES are folded into an
 * adjacent band and every fold is recorded in `merges`.
 */
export function buildDistribution(rows) {
  if (rows.length === 0) throw new Error("price sample is empty");
  for (const row of rows) {
    if (!Number.isFinite(row.monthly_rent_krw) || row.monthly_rent_krw <= 0) {
      throw new Error(`monthly_rent_krw must be greater than 0: ${row.monthly_rent_krw}`);
    }
    if (!Number.isFinite(row.deposit_krw) || row.deposit_krw < 0) {
      throw new Error(`deposit_krw must be zero or greater: ${row.deposit_krw}`);
    }
  }
  const districts = {};
  const merges = [];

  for (const district of new Set(rows.map((row) => row.sigungu))) {
    const districtRows = rows.filter((row) => row.sigungu === district);
    const grouped = new Map(AREA_BANDS.map((band) => [band.key, []]));
    for (const row of districtRows) grouped.get(bandForArea(row.area_m2).key).push(row);

    // Fold a small band into the next band down: XL into L, L into M, M into S.
    const order = [...AREA_BANDS].reverse();
    for (let index = 0; index < order.length - 1; index += 1) {
      const current = order[index], next = order[index + 1];
      const bucket = grouped.get(current.key);
      if (bucket.length > 0 && bucket.length < MIN_BAND_SAMPLES) {
        grouped.get(next.key).push(...bucket);
        grouped.set(current.key, []);
        merges.push({ district, from: current.key, into: next.key, moved: bucket.length });
      }
    }
    // If the smallest surviving band is still short, collapse the district into one band.
    const surviving = AREA_BANDS.filter((band) => grouped.get(band.key).length > 0);
    if (surviving.length > 0 && grouped.get(surviving[0].key).length < MIN_BAND_SAMPLES) {
      const all = surviving.flatMap((band) => grouped.get(band.key));
      for (const band of surviving) grouped.set(band.key, []);
      grouped.set(surviving[surviving.length - 1].key, all);
      for (const band of surviving.slice(0, -1)) {
        merges.push({ district, from: band.key, into: surviving[surviving.length - 1].key, moved: 0 });
      }
    }

    const bands = {};
    for (const band of AREA_BANDS) {
      const bucket = grouped.get(band.key);
      if (bucket.length === 0) continue;
      bands[band.key] = {
        label: band.label,
        n: bucket.length,
        monthly_rent_krw: quantileSet(bucket.map((row) => row.monthly_rent_krw)),
        deposit_multiple: quantileSet(bucket.map((row) => row.deposit_krw / row.monthly_rent_krw)),
      };
    }
    districts[district] = { area: quantileSet(districtRows.map((row) => row.area_m2)), bands };
  }
  return { districts, merges };
}

async function readPriceRows() {
  const rows = [];
  for (const district of TARGET_DISTRICTS) {
    const path = join(RAW_DIR, `prices.${district}.jsonl`);
    const text = await fs.readFile(path, "utf8");
    for (const line of text.trim().split("\n")) rows.push(JSON.parse(line));
  }
  return rows;
}

async function main() {
  const rows = await readPriceRows();
  const distribution = buildDistribution(rows);
  const payload = {
    generated_at: new Date().toISOString(),
    source: { kind: "one_time_crawl", note: "개별 매물 가격은 저장하지 않고 분위수만 남깁니다." },
    ...distribution,
  };
  await fs.mkdir(dirname(OUTPUT), { recursive: true });
  await fs.writeFile(OUTPUT, JSON.stringify(payload, null, 2) + "\n");
  console.log(`분포 산출 완료: ${OUTPUT} (표본 ${rows.length}건, 병합 ${distribution.merges.length}건)`);
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
