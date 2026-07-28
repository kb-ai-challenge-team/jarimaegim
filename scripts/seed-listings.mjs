import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SEED = join(ROOT, "data", "listings.seoul.json");

/** 가정값 열. backend/app/listings.py 의 ASSUMED_COLUMNS 와 같아야 한다. */
const ASSUMED_COLUMNS = ["key_money_krw", "exclusive_area_m2", "built_year", "parking_slots",
                         "corner", "elevator", "floors_total", "frontage_m", "available_from"];

/** Minimal .env reader; the repo has no dotenv dependency. Values are never logged. */
async function env(name) {
  let text;
  try { text = await fs.readFile(join(ROOT, ".env"), "utf8"); } catch { return ""; }
  const line = text.split("\n").find((entry) => entry.startsWith(`${name}=`));
  return line ? line.slice(name.length + 1).trim() : "";
}

function toRow(entry) {
  return {
    id: entry.id, district: entry.district, name: entry.name, address: entry.address,
    latitude: entry.latitude, longitude: entry.longitude,
    listing_kind: entry.listing.listing_kind, deposit_krw: entry.listing.deposit_krw,
    monthly_rent_krw: entry.listing.monthly_rent_krw, maintenance_fee_krw: entry.listing.maintenance_fee_krw,
    area_m2: entry.listing.area_m2, floor: entry.listing.floor,
    // 상권분석 데이터와 만나는 유일한 조인 키. 없는 매물은 null 로 두고 상권 축만 꺼진다.
    admin_dong: entry.admin_dong ?? null, admin_dong_code: entry.admin_dong_code ?? null,
    // 가정값 열. backend/app/listings.py 의 ASSUMED_COLUMNS 와 같은 목록이어야 한다.
    ...Object.fromEntries(ASSUMED_COLUMNS.map((key) => [key, entry.listing[key] ?? null])),
  };
}

async function main() {
  const url = await env("SUPABASE_URL");
  const key = await env("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) {
    console.log("SUPABASE_URL 또는 SUPABASE_SERVICE_ROLE_KEY가 없어 적재를 건너뜁니다. 백엔드는 시드 JSON을 그대로 읽습니다.");
    return;
  }
  const payload = JSON.parse(await fs.readFile(SEED, "utf8"));
  const rows = payload.listings.map(toRow);
  const unlabelled = rows.filter((row) => row.listing_kind !== "DEMO_SYNTHETIC");
  if (unlabelled.length > 0) throw new Error(`라벨 없는 행 ${unlabelled.length}건이 있어 적재를 중단합니다.`);

  const response = await fetch(`${url}/rest/v1/listings`, {
    method: "POST",
    headers: {
      apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json",
      Prefer: "resolution=merge-duplicates,return=minimal",
    },
    body: JSON.stringify(rows),
  });
  if (!response.ok) throw new Error(`적재 실패 ${response.status}: ${await response.text()}`);
  console.log(`매물 ${rows.length}건 적재 완료.`);
}

export { toRow };

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
