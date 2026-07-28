import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { fetchAll, loadEnv, pickFields } from "../lib/open-api.mjs";
import { OPEN_API_PAGE, OPEN_API_RATE_LIMIT_MS, TRADE_AREA_DATASETS, TRADE_AREA_QUARTER } from "../lib/trade-area-constants.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const ENV_PATH = join(ROOT, ".env");

/**
 * Stage 0b — 서울시 상권분석서비스 수집.
 *
 * 네 데이터셋을 그대로 받아 화이트리스트 필드만 jsonl 로 남긴다. 집계·판정은 하지 않는다.
 * 수집과 가공을 한 스크립트에 두면 어느 숫자가 원본이고 어느 숫자가 파생인지 알 수 없다.
 */
export async function collectTradeArea(key, { onLog = () => {} } = {}) {
  const collected = {};
  for (const [name, spec] of Object.entries(TRADE_AREA_DATASETS)) {
    const filters = spec.quarterly ? [TRADE_AREA_QUARTER] : [];
    const { rows, total } = await fetchAll(key, spec.dataset, {
      filters, page: OPEN_API_PAGE, rateLimitMs: OPEN_API_RATE_LIMIT_MS,
      onProgress: (done, expected) => onLog(`  ${spec.dataset}: ${done}/${expected}`),
    });
    if (rows.length !== total) {
      throw new Error(`${spec.dataset} 수신 건수(${rows.length})가 총건수(${total})와 다릅니다`);
    }
    collected[name] = rows.map((row) => pickFields(row, spec.fields));
  }
  return collected;
}

async function main() {
  const env = await loadEnv(ENV_PATH);
  const key = env.SEOUL_OPEN_DATA_KEY;
  if (!key) throw new Error("SEOUL_OPEN_DATA_KEY is not set in .env");

  await fs.mkdir(RAW_DIR, { recursive: true });
  console.log(`서울 상권분석 수집 시작 (기준 분기 ${TRADE_AREA_QUARTER})`);
  const collected = await collectTradeArea(key, { onLog: (line) => process.stdout.write(`\r${line.padEnd(60)}`) });
  process.stdout.write("\n");

  for (const [name, rows] of Object.entries(collected)) {
    const outPath = join(RAW_DIR, `trade-area.${name}.jsonl`);
    await fs.writeFile(outPath, rows.map((row) => JSON.stringify(row)).join("\n") + (rows.length ? "\n" : ""));
    console.log(`${name}: ${rows.length}건 → ${outPath}`);
  }
}

// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
