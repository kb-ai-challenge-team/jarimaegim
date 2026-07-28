import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { MIN_INDUSTRY_STORES, TRADE_AREA_QUARTER, TRADE_AREA_SPATIAL_UNIT } from "../lib/trade-area-constants.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const OUTPUT = join(ROOT, "data", "trade-area.seoul.json");

const num = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

/** 자치구는 행정동 코드 앞 5자리로 정한다. 데이터셋의 SIGNGU_CD_NM 은 상권이 경계에
 *  걸치면 이웃 구 이름이 들어오는 경우가 있어(예: 서초구 행에 도곡1동) 이름을 믿지 않는다. */
export function districtOf(geometryRows) {
  const byDongCode = new Map();
  for (const row of geometryRows) {
    const code = String(row.ADSTRD_CD);
    const bucket = byDongCode.get(code) ?? { names: new Map(), districts: new Map() };
    bucket.names.set(row.ADSTRD_CD_NM, (bucket.names.get(row.ADSTRD_CD_NM) ?? 0) + 1);
    bucket.districts.set(row.SIGNGU_CD_NM, (bucket.districts.get(row.SIGNGU_CD_NM) ?? 0) + 1);
    byDongCode.set(code, bucket);
  }
  const resolved = new Map();
  for (const [code, bucket] of byDongCode) {
    const top = (entries) => [...entries].sort((a, b) => b[1] - a[1])[0][0];
    resolved.set(code, { admin_dong: top(bucket.names), district: top(bucket.districts) });
  }
  return resolved;
}

/**
 * 상권 → 행정동 매핑. 상권 코드 하나는 행정동 하나에 속한다.
 */
function tradeAreaToDong(geometryRows) {
  const map = new Map();
  for (const row of geometryRows) map.set(String(row.TRDAR_CD), String(row.ADSTRD_CD));
  return map;
}

/**
 * 행정동 × 업종 집계.
 *
 * 비율은 절대 평균하지 않는다. 개업률·폐업률은 행정동 안 상권들의 개업·폐업 점포 수 합계를
 * 점포 수 합계로 나눠 다시 구한다. 점포당 매출도 마찬가지로 합계끼리 나눈다.
 * 매출 데이터셋은 점포 데이터셋보다 훨씬 성기므로(21,188행 대 75,972행), 매출을 확인한
 * 상권 수를 따로 세어 둔다. 매출이 없으면 그 축만 비운다.
 */
export function aggregate({ geometry, stores, sales, footfall }) {
  const dongOf = tradeAreaToDong(geometry);
  const dongMeta = districtOf(geometry);
  const industryNames = {};

  const salesByKey = new Map();
  for (const row of sales) {
    salesByKey.set(`${row.TRDAR_CD}|${row.SVC_INDUTY_CD}`, row);
  }

  const dongs = new Map();
  const ensure = (dongCode) => {
    if (!dongs.has(dongCode)) {
      const meta = dongMeta.get(dongCode) ?? { admin_dong: null, district: null };
      dongs.set(dongCode, {
        district: meta.district, admin_dong: meta.admin_dong,
        trade_areas: new Set(), footfall_monthly: 0, footfall_trade_areas: 0, industries: new Map(),
      });
    }
    return dongs.get(dongCode);
  };

  for (const row of footfall) {
    const dongCode = dongOf.get(String(row.TRDAR_CD));
    if (!dongCode) continue;
    const entry = ensure(dongCode);
    entry.footfall_monthly += num(row.TOT_FLPOP_CO);
    entry.footfall_trade_areas += 1;
  }

  for (const row of stores) {
    const dongCode = dongOf.get(String(row.TRDAR_CD));
    if (!dongCode) continue;
    const entry = ensure(dongCode);
    entry.trade_areas.add(String(row.TRDAR_CD));
    industryNames[row.SVC_INDUTY_CD] = row.SVC_INDUTY_CD_NM;

    const key = row.SVC_INDUTY_CD;
    const bucket = entry.industries.get(key) ?? {
      store_count: 0, similar_store_count: 0, franchise_store_count: 0,
      opened_store_count: 0, closed_store_count: 0,
      trade_area_count: 0, sales_trade_area_count: 0, sales_store_count: 0,
      monthly_sales_krw: 0, monthly_sales_count: 0,
    };
    bucket.store_count += num(row.STOR_CO);
    bucket.similar_store_count += num(row.SIMILR_INDUTY_STOR_CO);
    bucket.franchise_store_count += num(row.FRC_STOR_CO);
    bucket.opened_store_count += num(row.OPBIZ_STOR_CO);
    bucket.closed_store_count += num(row.CLSBIZ_STOR_CO);
    bucket.trade_area_count += 1;

    const salesRow = salesByKey.get(`${row.TRDAR_CD}|${row.SVC_INDUTY_CD}`);
    if (salesRow) {
      bucket.sales_trade_area_count += 1;
      bucket.monthly_sales_krw += num(salesRow.THSMON_SELNG_AMT);
      bucket.monthly_sales_count += num(salesRow.THSMON_SELNG_CO);
      // 점포당 매출의 분모. 매출이 확인된 상권의 점포만 더한다. 행정동 전체 점포 수로 나누면
      // 매출을 확인하지 못한 상권의 점포가 분모에만 들어가 점포당 매출이 실제보다 낮게 나온다.
      bucket.sales_store_count += num(row.STOR_CO);
    }
    entry.industries.set(key, bucket);
  }

  const output = {};
  for (const [dongCode, entry] of dongs) {
    const industries = {};
    for (const [code, bucket] of entry.industries) {
      if (bucket.store_count < MIN_INDUSTRY_STORES) continue;
      const stores = bucket.store_count;
      industries[code] = {
        store_count: stores,
        similar_store_count: bucket.similar_store_count,
        franchise_store_count: bucket.franchise_store_count,
        opened_store_count: bucket.opened_store_count,
        closed_store_count: bucket.closed_store_count,
        // 합계끼리 나눈 값이다. 상권별 비율의 평균이 아니다.
        open_rate: stores > 0 ? Number(((bucket.opened_store_count / stores) * 100).toFixed(2)) : null,
        close_rate: stores > 0 ? Number(((bucket.closed_store_count / stores) * 100).toFixed(2)) : null,
        monthly_sales_krw: bucket.sales_trade_area_count > 0 ? Math.round(bucket.monthly_sales_krw) : null,
        monthly_sales_count: bucket.sales_trade_area_count > 0 ? Math.round(bucket.monthly_sales_count) : null,
        // 분자와 분모가 같은 모집단이다 — 매출이 확인된 상권의 매출 합계를 그 상권들의
        // 점포 수 합계로 나눈다. 몇 개 상권을 근거로 했는지는 아래 두 필드가 밝힌다.
        sales_per_store_krw: bucket.sales_store_count > 0
          ? Math.round(bucket.monthly_sales_krw / bucket.sales_store_count) : null,
        sales_store_count: bucket.sales_store_count,
        trade_area_count: bucket.trade_area_count,
        sales_trade_area_count: bucket.sales_trade_area_count,
      };
    }
    output[dongCode] = {
      district: entry.district, admin_dong: entry.admin_dong,
      trade_area_count: entry.trade_areas.size,
      footfall_monthly: entry.footfall_trade_areas > 0 ? Math.round(entry.footfall_monthly) : null,
      footfall_trade_areas: entry.footfall_trade_areas,
      industries,
    };
  }
  return { dongs: output, industryNames };
}

/** 중앙값. 서울 전체에서 이 행정동이 어디쯤인지 말하려면 기준선이 필요하다. */
export function median(values) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/**
 * 업종별 서울 기준선. 행정동 단위 값들의 중앙값이며, 평균이 아니다.
 * 한두 개의 거대 상권이 기준선을 끌어올리면 모든 동네가 "평균 이하"가 된다.
 */
export function buildBenchmarks(dongs) {
  const collected = new Map();
  for (const entry of Object.values(dongs)) {
    for (const [code, industry] of Object.entries(entry.industries)) {
      const bucket = collected.get(code) ?? { salesPerStore: [], closeRate: [], storeCount: [], footfallPerStore: [] };
      if (industry.sales_per_store_krw !== null) bucket.salesPerStore.push(industry.sales_per_store_krw);
      if (industry.close_rate !== null) bucket.closeRate.push(industry.close_rate);
      if (industry.store_count > 0) bucket.storeCount.push(industry.store_count);
      if (entry.footfall_monthly && industry.store_count > 0) bucket.footfallPerStore.push(entry.footfall_monthly / industry.store_count);
      collected.set(code, bucket);
    }
  }
  const benchmarks = {};
  for (const [code, bucket] of collected) {
    benchmarks[code] = {
      sales_per_store_krw_median: bucket.salesPerStore.length > 0 ? Math.round(median(bucket.salesPerStore)) : null,
      sales_dong_n: bucket.salesPerStore.length,
      close_rate_median: bucket.closeRate.length > 0 ? Number(median(bucket.closeRate).toFixed(2)) : null,
      close_rate_dong_n: bucket.closeRate.length,
      store_count_median: bucket.storeCount.length > 0 ? Math.round(median(bucket.storeCount)) : null,
      footfall_per_store_median: bucket.footfallPerStore.length > 0 ? Math.round(median(bucket.footfallPerStore)) : null,
      footfall_dong_n: bucket.footfallPerStore.length,
    };
  }
  return benchmarks;
}

async function readJsonl(name) {
  const text = await fs.readFile(join(RAW_DIR, name), "utf8");
  return text.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line));
}

async function main() {
  const [geometry, stores, sales, footfall] = await Promise.all([
    readJsonl("trade-area.geometry.jsonl"), readJsonl("trade-area.stores.jsonl"),
    readJsonl("trade-area.sales.jsonl"), readJsonl("trade-area.footfall.jsonl"),
  ]);
  const { dongs, industryNames } = aggregate({ geometry, stores, sales, footfall });
  const benchmarks = buildBenchmarks(dongs);

  const payload = {
    generated_at: new Date().toISOString(),
    quarter: TRADE_AREA_QUARTER,
    source_name: "서울시 우리마을가게 상권분석서비스",
    source_org: "서울특별시 (서울 열린데이터광장)",
    datasets: ["TbgisTrdarRelm(상권영역)", "VwsmTrdarStorQq(점포)", "VwsmTrdarSelngQq(추정매출)", "VwsmTrdarFlpopQq(길단위인구)"],
    spatial_unit: TRADE_AREA_SPATIAL_UNIT,
    method: "상권을 행정동으로 묶어 합계를 낸 뒤, 개업률·폐업률·점포당 매출은 상권별 비율의 평균이 아니라 합계끼리 나눠 다시 구했습니다.",
    limitations: [
      "상권 경계 안의 집계이며 개별 점포의 실적이 아닙니다.",
      "추정매출은 카드 매출 기반 추정치이고 상권·업종 조합의 일부에만 제공됩니다.",
      "행정동 단위 집계이므로 같은 동 안에서도 위치에 따라 실제 여건은 다릅니다.",
      "개별 점포의 생존·폐업 확률이 아니며 그렇게 읽을 수 없습니다.",
    ],
    industry_names: industryNames,
    benchmarks,
    dongs,
  };
  await fs.mkdir(dirname(OUTPUT), { recursive: true });
  // 들여쓰기 없이 쓴다. 행정동 399개 × 업종 100종이라 포맷팅만으로 3MB 넘게 붙고,
  // 사람이 직접 고칠 파일이 아니라 파이프라인이 다시 만드는 산출물이다.
  await fs.writeFile(OUTPUT, JSON.stringify(payload) + "\n");
  const industryTotal = Object.values(dongs).reduce((sum, entry) => sum + Object.keys(entry.industries).length, 0);
  console.log(`상권 프로파일 생성: ${OUTPUT}`);
  console.log(`  행정동 ${Object.keys(dongs).length}개 · 행정동×업종 ${industryTotal}건 · 업종 ${Object.keys(industryNames).length}종`);
}

// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
