import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { TARGET_DISTRICTS } from "../lib/constants.mjs";
import { pickRawFields } from "../lib/raw-record.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const ENV_PATH = join(ROOT, ".env");

const KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json";
const PAGE_SIZE = 15;
const MAX_PAGE = 45;
const TARGET_PER_DISTRICT = 70;
const RATE_LIMIT_MS = 60;
// Kakao keyword search caps meta.pageable_count at 45 documents per exact query string,
// regardless of page/size — so more distinct phrasings, not more pages, is what surfaces more
// unique places. The four required variants alone left 마포구/성동구/영등포구 short of the
// 70-coordinate target, so a few more plausible storefront-search phrasings are added here.
const QUERY_SUFFIXES = ["상가", "근린생활시설", "점포", "상가건물", "부동산", "사무실", "매장", "상점", "빌딩"];

/** Minimal .env parser: KEY=VALUE lines, no quoting/escaping support. Never logs values. */
async function loadEnv(path) {
  const text = await fs.readFile(path, "utf8");
  const env = {};
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    env[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
  }
  return env;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Single Kakao keyword-search page. Throws on non-OK HTTP status without ever including the key. */
async function kakaoSearch(apiKey, params) {
  const url = new URL(KAKAO_URL);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
  const response = await fetch(url, { headers: { Authorization: `KakaoAK ${apiKey}` } });
  if (!response.ok) throw new Error(`Kakao keyword search failed: ${response.status} ${response.statusText}`);
  return response.json();
}

/** address_name looks like "서울 강남구 대치동 316"; token[2] is the dong/street. */
function extractDong(addressName) {
  const tokens = addressName.trim().split(/\s+/);
  const dong = tokens[2];
  if (!dong || !/(동|가|로)$/.test(dong)) return null;
  return dong;
}

/** address_name's district token (index 1) must match the district we queried for. Kakao keyword
 * search leaks results from neighbouring districts, so we discard anything that doesn't match. */
function extractDistrict(addressName) {
  const tokens = addressName.trim().split(/\s+/);
  return tokens[1] ?? null;
}

async function collectDistrict(apiKey, district) {
  const byKey = new Map();
  let rejected = 0;

  for (const suffix of QUERY_SUFFIXES) {
    if (byKey.size >= TARGET_PER_DISTRICT) break;
    const query = `${district} ${suffix}`;
    let page = 1;
    for (;;) {
      const data = await kakaoSearch(apiKey, { query, size: PAGE_SIZE, page });
      await sleep(RATE_LIMIT_MS);
      for (const doc of data.documents ?? []) {
        if (extractDistrict(doc.address_name) !== district) continue;
        const dong = extractDong(doc.address_name);
        if (!dong) continue;
        const lat = Number(doc.y);
        const lng = Number(doc.x);
        const key = `${lat.toFixed(6)},${lng.toFixed(6)}`;
        if (byKey.has(key)) continue;
        try {
          const record = pickRawFields({
            lat, lng,
            sido: "서울",
            sigungu: district,
            dong,
            // Kakao keyword search does not return a floor. 1 is a stated default, not measured data.
            floor: 1,
            // Kakao keyword search does not return an area either. 0.1 is a placeholder that exists
            // only to satisfy the raw-record whitelist and to seed Stage 3's resampling collision
            // guard (which compares against the coordinate's original area to avoid regenerating the
            // same value). It never carries into the generated listings.
            area_m2: 0.1,
          });
          byKey.set(key, record);
        } catch {
          rejected += 1;
        }
      }
      const isEnd = data.meta?.is_end !== false;
      if (isEnd || page >= MAX_PAGE || byKey.size >= TARGET_PER_DISTRICT) break;
      page += 1;
    }
  }

  return { records: [...byKey.values()], rejected };
}

async function main() {
  const env = await loadEnv(ENV_PATH);
  const apiKey = env.KAKAO_REST_API_KEY;
  if (!apiKey) throw new Error("KAKAO_REST_API_KEY is not set in .env");

  await fs.mkdir(RAW_DIR, { recursive: true });

  for (const district of TARGET_DISTRICTS) {
    const { records, rejected } = await collectDistrict(apiKey, district);
    const outPath = join(RAW_DIR, `coords.${district}.jsonl`);
    const body = records.map((record) => JSON.stringify(record)).join("\n") + (records.length ? "\n" : "");
    await fs.writeFile(outPath, body);
    const shortfall = records.length < TARGET_PER_DISTRICT ? ` SHORTFALL: below target of ${TARGET_PER_DISTRICT}` : "";
    console.log(`${district}: ${records.length} unique coordinates written, ${rejected} rejected by validation${shortfall}`);
  }
}

// process.argv[1] is a raw path (may contain spaces); pathToFileURL encodes it the same way
// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
