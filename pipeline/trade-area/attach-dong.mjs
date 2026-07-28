import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const LISTINGS_PATH = join(ROOT, "data", "listings.seoul.json");

/** 좌표 키. Stage 0c 가 쓴 것과 같은 형식이어야 조인이 성립한다. */
const coordKey = (lat, lng) => `${Number(lat).toFixed(6)},${Number(lng).toFixed(6)}`;

/**
 * 매물에 행정동을 붙인다.
 *
 * 매물 자체는 바뀌지 않는다 — 임대조건도 좌표도 그대로다. 상권 데이터와 만날 수 있는
 * 조인 키(행정동 코드)만 얹는다. 확인하지 못한 좌표는 키를 null 로 두고, 백엔드가 그
 * 매물에 대해서는 상권 축을 판정하지 않는다. 비어 있는 것을 채우지 않는 것이 요점이다.
 */
export function attachDong(listings, dongByCoord) {
  let attached = 0;
  const next = listings.map((listing) => {
    const region = dongByCoord.get(coordKey(listing.latitude, listing.longitude));
    if (!region) return { ...listing, admin_dong: null, admin_dong_code: null };
    attached += 1;
    return { ...listing, admin_dong: region.admin_dong, admin_dong_code: String(region.admin_dong_code).slice(0, 8) };
  });
  return { listings: next, attached };
}

async function main() {
  const payload = JSON.parse(await fs.readFile(LISTINGS_PATH, "utf8"));
  const text = await fs.readFile(join(RAW_DIR, "listing-dong.jsonl"), "utf8");
  const dongByCoord = new Map();
  for (const line of text.trim().split("\n").filter(Boolean)) {
    const row = JSON.parse(line);
    dongByCoord.set(coordKey(row.lat, row.lng), row);
  }

  const { listings, attached } = attachDong(payload.listings ?? [], dongByCoord);
  const next = {
    ...payload,
    admin_dong_source: "Kakao Local 좌표→행정동 변환(coord2regioncode). 상권분석 데이터와 조인하기 위한 키입니다.",
    admin_dong_code_note: "서울시 상권분석서비스의 ADSTRD_CD 와 같은 8자리 행정동 코드입니다.",
    listings,
  };
  await fs.writeFile(LISTINGS_PATH, JSON.stringify(next, null, 2) + "\n");
  console.log(`행정동 부착: ${attached}/${listings.length}건 → ${LISTINGS_PATH}`);
  if (attached === 0) throw new Error("행정동을 붙인 매물이 하나도 없습니다 — 좌표 키가 어긋났습니다");
}

// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
