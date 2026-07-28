import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { loadEnv, sleep } from "../lib/open-api.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const ENV_PATH = join(ROOT, ".env");
// 입력은 pipeline/raw/coords.*.jsonl 이 아니라 합성 결과물이다. raw 는 gitignore 대상이라
// 이 저장소에는 최초 5개 구의 좌표만 남아 있는 반면, 매물 파일에는 19개 구가 모두 있다.
// 행정동을 붙여야 하는 대상은 실제로 서비스에 나가는 매물이므로 그쪽을 읽는다.
const LISTINGS_PATH = join(ROOT, "data", "listings.seoul.json");

const KAKAO_URL = "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json";
const RATE_LIMIT_MS = 60;

/**
 * Stage 0c — 좌표 → 행정동.
 *
 * 상권분석 데이터셋은 상권 중심좌표를 EPSG:5181 계열 TM 으로 준다. 매물 좌표는 WGS84 라
 * 그대로는 만나지 않는다. 좌표계를 변환해 최근접 상권을 붙일 수도 있지만, 상권영역
 * 데이터셋이 주는 것은 중심점과 면적뿐이고 폴리곤이 없다. 중심점 거리로 소속을 정하면
 * 근거가 없는 정밀함이 생긴다.
 *
 * 대신 양쪽이 모두 문자열로 갖고 있는 행정동으로 조인한다. 상권영역은 ADSTRD_CD_NM 을
 * 주고, 매물 좌표는 Kakao 역지오코딩이 행정동(region_type "H")을 준다. 변환도 근사도
 * 없는 정확한 조인이고, 대신 공간 단위가 개별 상권이 아니라 행정동이 된다. 그 사실은
 * provenance 의 spatial_unit 에 그대로 적힌다.
 */
export function extractAdminDong(documents) {
  const admin = (documents ?? []).find((doc) => doc.region_type === "H");
  if (!admin) return null;
  return {
    district: admin.region_2depth_name || null,
    admin_dong: admin.region_3depth_name || null,
    admin_dong_code: admin.code || null,
  };
}

async function resolveDong(apiKey, lat, lng) {
  const url = new URL(KAKAO_URL);
  url.searchParams.set("x", String(lng));
  url.searchParams.set("y", String(lat));
  const response = await fetch(url, { headers: { Authorization: `KakaoAK ${apiKey}` } });
  if (!response.ok) throw new Error(`Kakao coord2regioncode 실패: ${response.status} ${response.statusText}`);
  return extractAdminDong((await response.json()).documents);
}

async function readListingCoords() {
  const payload = JSON.parse(await fs.readFile(LISTINGS_PATH, "utf8"));
  return (payload.listings ?? []).map((listing) => ({
    lat: listing.latitude, lng: listing.longitude, sigungu: listing.district,
  }));
}

async function main() {
  const env = await loadEnv(ENV_PATH);
  const apiKey = env.KAKAO_REST_API_KEY;
  if (!apiKey) throw new Error("KAKAO_REST_API_KEY is not set in .env");

  const coords = await readListingCoords();
  // 같은 좌표가 여러 번 나오면 한 번만 묻는다. 좌표는 6자리로 고정해 매물 합성 단계가
  // 쓰는 키와 같은 형태로 맞춘다.
  const unique = new Map();
  for (const record of coords) unique.set(`${record.lat.toFixed(6)},${record.lng.toFixed(6)}`, record);

  const resolved = [];
  let missing = 0;
  let index = 0;
  for (const [key, record] of unique) {
    index += 1;
    const region = await resolveDong(apiKey, record.lat, record.lng);
    await sleep(RATE_LIMIT_MS);
    if (!region?.admin_dong) { missing += 1; continue; }
    if (region.district !== record.sigungu) {
      // 좌표가 실제로는 다른 구에 있다는 뜻이다. 조용히 고치면 자치구별 건수가 어긋나므로
      // 버리고 세어 둔다.
      missing += 1;
      continue;
    }
    resolved.push({ key, lat: record.lat, lng: record.lng, district: region.district, admin_dong: region.admin_dong, admin_dong_code: region.admin_dong_code });
    if (index % 100 === 0) process.stdout.write(`\r  ${index}/${unique.size}`.padEnd(30));
  }
  process.stdout.write("\n");

  const outPath = join(RAW_DIR, "listing-dong.jsonl");
  await fs.writeFile(outPath, resolved.map((row) => JSON.stringify(row)).join("\n") + (resolved.length ? "\n" : ""));
  console.log(`행정동 확인: ${resolved.length}건 → ${outPath} (미확인 ${missing}건)`);
  if (resolved.length === 0) throw new Error("행정동을 하나도 확인하지 못했습니다");
}

// import.meta.url is encoded, so the comparison works even though the repo path itself has a space.
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
