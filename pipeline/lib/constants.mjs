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

export function bandForArea(areaM2) {
  const band = AREA_BANDS.find((candidate) => areaM2 >= candidate.min && areaM2 < candidate.max);
  if (!band) throw new Error(`No band found for area ${areaM2}`);
  return band;
}
