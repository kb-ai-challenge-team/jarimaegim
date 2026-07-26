/** 시연용 매물 데이터의 대상 자치구. 설계 문서 §2 참조. */
export const TARGET_DISTRICTS = ["강남구", "마포구", "서초구", "성동구", "영등포구"];

/** 면적구간. 소규모 상가 임대 시장의 실제 구획과 맞춘 4구간. 설계 문서 §3 Stage 1. */
export const AREA_BANDS = [
  { key: "S", label: "~33㎡", min: 0, max: 33 },
  { key: "M", label: "33~66㎡", min: 33, max: 66 },
  { key: "L", label: "66~99㎡", min: 66, max: 99 },
  { key: "XL", label: "99㎡~", min: 99, max: Infinity },
];

/** 이보다 표본이 적은 구간은 상위 구간으로 병합한다. */
export const MIN_BAND_SAMPLES = 5;

/** 합성 재현성을 위한 고정 시드. 절대 바꾸지 않는다. */
export const SYNTHESIS_SEED = 20260727;

/** 구당 생성할 매물 수. */
export const LISTINGS_PER_DISTRICT = 55;

export function bandForArea(areaM2) {
  const band = AREA_BANDS.find((candidate) => areaM2 >= candidate.min && areaM2 < candidate.max);
  if (!band) throw new Error(`면적 ${areaM2}에 해당하는 구간이 없습니다`);
  return band;
}
