import { promises as fs } from "node:fs";

/** Minimal .env parser: KEY=VALUE lines, no quoting/escaping support. Never logs values. */
export async function loadEnv(path) {
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

export function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * 서울 열린데이터광장 OpenAPI 는 인증키를 URL 경로에 넣는다. 오류 메시지에 URL 을 그대로
 * 실으면 키가 로그로 새므로, 실패를 던질 때는 항상 키를 지운 형태만 남긴다.
 */
function redact(url, key) {
  return url.replace(key, "<key>");
}

/**
 * 응답 한 페이지. 열린데이터광장은 HTTP 200 에 오류 코드를 담아 주므로 상태코드만으로는
 * 성공을 판정할 수 없다. RESULT.CODE 가 INFO-000 인지까지 확인한다.
 */
export async function fetchPage(key, dataset, start, end, filters = []) {
  const suffix = filters.length > 0 ? `${filters.join("/")}/` : "";
  const url = `http://openapi.seoul.go.kr:8088/${key}/json/${dataset}/${start}/${end}/${suffix}`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${dataset} 요청 실패: ${response.status} ${response.statusText} (${redact(url, key)})`);
  const payload = await response.json();
  const body = payload[dataset];
  if (!body) {
    const result = payload.RESULT ?? {};
    throw new Error(`${dataset} 응답에 본문이 없습니다: ${result.CODE ?? "?"} ${result.MESSAGE ?? ""}`);
  }
  const code = body.RESULT?.CODE;
  // INFO-200 은 "해당하는 데이터가 없습니다" 다. 마지막 페이지 다음을 요청하면 나오므로
  // 오류가 아니라 정상 종료 신호로 다룬다.
  if (code === "INFO-200") return { rows: [], total: body.list_total_count ?? 0 };
  if (code !== "INFO-000") throw new Error(`${dataset} 조회 오류: ${code} ${body.RESULT?.MESSAGE ?? ""}`);
  return { rows: body.row ?? [], total: body.list_total_count ?? 0 };
}

/** 화이트리스트에 있는 필드만 남긴다. 없는 필드는 키 자체를 만들지 않는다. */
export function pickFields(row, fields) {
  const picked = {};
  for (const field of fields) {
    if (row[field] !== undefined && row[field] !== null) picked[field] = row[field];
  }
  return picked;
}

/**
 * 데이터셋 전체를 페이지 단위로 받는다. 총건수를 먼저 읽고 그 수만큼만 요청하되,
 * 빈 페이지가 오면 거기서 멈춘다. 총건수와 실제 수신 건수가 다르면 호출자가 판단하도록
 * 둘 다 반환한다.
 */
export async function fetchAll(key, dataset, { filters = [], page = 1000, rateLimitMs = 120, onProgress } = {}) {
  const rows = [];
  let total = null;
  for (let start = 1; total === null || start <= total; start += page) {
    const result = await fetchPage(key, dataset, start, start + page - 1, filters);
    if (total === null) total = result.total;
    if (result.rows.length === 0) break;
    rows.push(...result.rows);
    onProgress?.(rows.length, total);
    if (rateLimitMs > 0) await sleep(rateLimitMs);
  }
  return { rows, total: total ?? 0 };
}
