/**
 * Collected-field whitelist. Listing IDs, agency and business names, photos,
 * descriptions, source URLs and prices are absent by design, so they never reach disk.
 */
export const RAW_FIELDS = ["lat", "lng", "sido", "sigungu", "dong", "floor", "area_m2"];

/** Generous bounding box around Seoul, used to catch coordinate parsing mistakes. */
const SEOUL_BOUNDS = { minLat: 37.41, maxLat: 37.72, minLng: 126.76, maxLng: 127.19 };

function requireNumber(source, field) {
  const value = source[field];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${field} is not a finite number: ${JSON.stringify(value)}`);
  }
  return value;
}

function requireText(source, field) {
  const value = source[field];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${field} is empty`);
  }
  return value.trim();
}

/** Keep only whitelisted fields and validate them. Records that fail validation throw. */
export function pickRawFields(source) {
  const lat = requireNumber(source, "lat");
  const lng = requireNumber(source, "lng");
  if (lat < SEOUL_BOUNDS.minLat || lat > SEOUL_BOUNDS.maxLat || lng < SEOUL_BOUNDS.minLng || lng > SEOUL_BOUNDS.maxLng) {
    throw new Error(`coordinate is outside Seoul: ${lat}, ${lng}`);
  }
  const area = requireNumber(source, "area_m2");
  if (area <= 0) throw new Error(`area_m2 must be greater than 0: ${area}`);
  const floor = requireNumber(source, "floor");
  return {
    lat, lng,
    sido: requireText(source, "sido"),
    sigungu: requireText(source, "sigungu"),
    dong: requireText(source, "dong"),
    floor, area_m2: area,
  };
}
