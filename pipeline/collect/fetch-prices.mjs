import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { TARGET_DISTRICTS } from "../lib/constants.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const ENV_PATH = join(ROOT, ".env");
const CSV_CACHE = join(RAW_DIR, "subway-rents.csv");
const STATION_DISTRICT_CACHE = join(RAW_DIR, "station-districts.json");

const DOWNLOAD_URL = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do";
const DOWNLOAD_FORM = { infId: "OA-12927", seq: "14", infSeq: "1" };
const KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json";
const RATE_LIMIT_MS = 60;
const TARGET_DISTRICT_SET = new Set(TARGET_DISTRICTS);

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

/** Download the Seoul Metro underground arcade dataset (OA-12927). This is file data, not an Open
 * API, fetched via POST form; the response body is EUC-KR encoded. */
async function downloadCsv() {
  const response = await fetch(DOWNLOAD_URL, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams(DOWNLOAD_FORM).toString(),
  });
  if (!response.ok) throw new Error(`subway rent dataset download failed: ${response.status} ${response.statusText}`);
  return new TextDecoder("euc-kr").decode(Buffer.from(await response.arrayBuffer()));
}

async function loadCsv() {
  try {
    return await fs.readFile(CSV_CACHE, "utf8");
  } catch {
    const text = await downloadCsv();
    await fs.mkdir(RAW_DIR, { recursive: true });
    await fs.writeFile(CSV_CACHE, text, "utf8");
    return text;
  }
}

/** Tiny CSV parser sufficient for this dataset: no quoted fields containing commas are present in
 * the verified header/columns we read (station name, area, rent). */
function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
  const header = lines[0].split(",");
  const rows = [];
  for (const line of lines.slice(1)) {
    const cells = line.split(",");
    const row = {};
    header.forEach((name, index) => { row[name] = cells[index]; });
    rows.push(row);
  }
  return rows;
}

/** Keep rows where both area and rent parse to positive numbers. */
function usableRows(rows) {
  const usable = [];
  for (const row of rows) {
    const area = Number(row["면적(제곱미터)"]);
    const rent = Number(row["월임대료"]);
    if (Number.isFinite(area) && area > 0 && Number.isFinite(rent) && rent > 0) {
      usable.push({ station: row["역명"], area_m2: area, monthly_rent_krw: rent });
    }
  }
  return usable;
}

/** The dataset writes line numbers in parentheses after the station name, e.g. "서울(1)역". */
function normalizeStationName(name) {
  return name.replace(/\(\d+\)/g, "").trim();
}

async function kakaoStationDistrict(apiKey, station) {
  const url = new URL(KAKAO_URL);
  url.searchParams.set("query", station);
  url.searchParams.set("category_group_code", "SW8");
  url.searchParams.set("size", "1");
  const response = await fetch(url, { headers: { Authorization: `KakaoAK ${apiKey}` } });
  if (!response.ok) throw new Error(`Kakao keyword search failed: ${response.status} ${response.statusText}`);
  const data = await response.json();
  const doc = data.documents?.[0];
  if (!doc) return null;
  const tokens = doc.address_name.trim().split(/\s+/);
  return tokens[1] ?? null;
}

async function loadStationDistrictCache() {
  try {
    return JSON.parse(await fs.readFile(STATION_DISTRICT_CACHE, "utf8"));
  } catch {
    return {};
  }
}

async function buildStationDistrictMap(apiKey, stations) {
  const cache = await loadStationDistrictCache();
  let changed = false;
  for (const station of stations) {
    if (station in cache) continue;
    const district = await kakaoStationDistrict(apiKey, station);
    await sleep(RATE_LIMIT_MS);
    cache[station] = district;
    changed = true;
  }
  if (changed) {
    await fs.mkdir(RAW_DIR, { recursive: true });
    await fs.writeFile(STATION_DISTRICT_CACHE, JSON.stringify(cache, null, 2) + "\n");
  }
  return cache;
}

async function main() {
  const env = await loadEnv(ENV_PATH);
  const apiKey = env.KAKAO_REST_API_KEY;
  if (!apiKey) throw new Error("KAKAO_REST_API_KEY is not set in .env");

  const csvText = await loadCsv();
  const rows = parseCsv(csvText);
  const usable = usableRows(rows);
  console.log(`csv rows: ${rows.length} total, ${usable.length} usable`);

  const stationNames = [...new Set(usable.map((row) => normalizeStationName(row.station)))];
  const stationDistrict = await buildStationDistrictMap(apiKey, stationNames);
  console.log(`stations geocoded: ${stationNames.length} distinct`);

  const byDistrict = new Map(TARGET_DISTRICTS.map((district) => [district, []]));
  for (const row of usable) {
    const district = stationDistrict[normalizeStationName(row.station)];
    if (!district || !TARGET_DISTRICT_SET.has(district)) continue;
    byDistrict.get(district).push({ sigungu: district, area_m2: row.area_m2, monthly_rent_krw: row.monthly_rent_krw });
  }

  await fs.mkdir(RAW_DIR, { recursive: true });
  for (const district of TARGET_DISTRICTS) {
    const records = byDistrict.get(district);
    const outPath = join(RAW_DIR, `prices.${district}.jsonl`);
    // No deposit field: the dataset has none, and the market deposit-multiple used downstream is a
    // declared assumption held elsewhere as a constant, not a measured value. Mixing an assumed
    // number into this file would make measured and assumed figures indistinguishable later.
    const body = records.map((record) => JSON.stringify(record)).join("\n") + (records.length ? "\n" : "");
    await fs.writeFile(outPath, body);
    console.log(`${district}: ${records.length}`);
  }
}

// process.argv[1] is a raw path (may contain spaces); pathToFileURL encodes it the same way
// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
