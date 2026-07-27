/** Target districts for the demo listing data. See design doc §2. */
export const TARGET_DISTRICTS = ["강남구", "마포구", "서초구", "성동구", "영등포구"];

/** Area bands. 4 bands matched to the real segmentation of the small commercial rental market. See design doc §3 Stage 1. */
export const AREA_BANDS = [
  { key: "S", label: "~33㎡", min: 0, max: 33 },
  { key: "M", label: "33~66㎡", min: 33, max: 66 },
  { key: "L", label: "66~99㎡", min: 66, max: 99 },
  { key: "XL", label: "99㎡~", min: 99, max: Infinity },
];

/** Bands with fewer samples than this are merged into the next larger band. */
export const MIN_BAND_SAMPLES = 5;

/** Fixed seed for reproducible synthesis. Never change this. */
export const SYNTHESIS_SEED = 20260727;

/** Number of listings to generate per district. */
export const LISTINGS_PER_DISTRICT = 55;

/**
 * Commercial deposits have no measured public source, so this is a declared
 * assumption, not data. Korean storefront leases conventionally set the deposit
 * at roughly ten to twenty times the monthly rent. Anything derived from this
 * must be labelled as assumed wherever it is shown.
 */
export const ASSUMED_DEPOSIT_MULTIPLE = { min: 10, max: 20 };

/**
 * Kakao Local does not return a floor, so every collected coordinate is treated as
 * ground floor. This is a declared assumption, not measured data, and it reaches the
 * generated listings verbatim - both the floor field and the display name.
 */
export const ASSUMED_FLOOR = 1;

/**
 * Maintenance fee has no measured source either. Korean storefront leases commonly
 * bill it at roughly eight percent of the monthly rent. Declared assumption.
 */
export const ASSUMED_MAINTENANCE_FEE_RATE = 0.08;

export function bandForArea(areaM2) {
  const band = AREA_BANDS.find((candidate) => areaM2 >= candidate.min && areaM2 < candidate.max);
  if (!band) throw new Error(`No band found for area ${areaM2}`);
  return band;
}
