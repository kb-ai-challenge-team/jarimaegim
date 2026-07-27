import assert from "node:assert/strict";
import test from "node:test";
import { createRng } from "../lib/rng.mjs";
import { buildListings, sampleArea } from "./build-listings.mjs";

const DISTRIBUTION = {
  districts: {
    "강남구": {
      area: { p10: 20, p25: 30, p50: 40, p75: 60, p90: 90, n: 50 },
      bands: {
        S: { label: "~33㎡", n: 15, monthly_rent_krw: { p10: 1_000_000, p25: 1_400_000, p50: 1_800_000, p75: 2_400_000, p90: 3_200_000, n: 15 }, deposit_multiple: { p10: 10, p25: 13, p50: 16, p75: 20, p90: 28, n: 15 } },
        M: { label: "33~66㎡", n: 20, monthly_rent_krw: { p10: 2_000_000, p25: 2_600_000, p50: 3_200_000, p75: 4_200_000, p90: 5_600_000, n: 20 }, deposit_multiple: { p10: 10, p25: 13, p50: 16, p75: 20, p90: 28, n: 20 } },
        L: { label: "66~99㎡", n: 15, monthly_rent_krw: { p10: 3_000_000, p25: 3_800_000, p50: 4_600_000, p75: 6_000_000, p90: 8_000_000, n: 15 }, deposit_multiple: { p10: 10, p25: 13, p50: 16, p75: 20, p90: 28, n: 15 } },
      },
    },
  },
};

function coords(count) {
  return Array.from({ length: count }, (_, index) => ({
    lat: 37.5 + index * 0.001, lng: 127.03 + index * 0.001,
    sido: "서울특별시", sigungu: "강남구", dong: "역삼동", floor: 1, area_m2: 40 + index,
  }));
}

test("요청한 수만큼 매물을 낸다", () => {
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 });
  assert.equal(listings.length, 55);
});

test("좌표가 모자라면 있는 만큼만 낸다", () => {
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(12) }, perDistrict: 55 });
  assert.equal(listings.length, 12);
});

test("모든 행에 DEMO_SYNTHETIC 라벨이 있다", () => {
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 });
  assert.ok(listings.every((listing) => listing.listing.listing_kind === "DEMO_SYNTHETIC"));
});

test("월세는 해당 구간의 P10~P90 안에 있다", () => {
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 });
  for (const listing of listings) {
    const band = Object.values(DISTRIBUTION.districts["강남구"].bands).find((entry) => entry.label === listing._band_label);
    assert.ok(listing.listing.monthly_rent_krw >= band.monthly_rent_krw.p10, `${listing.listing.monthly_rent_krw} >= ${band.monthly_rent_krw.p10}`);
    assert.ok(listing.listing.monthly_rent_krw <= band.monthly_rent_krw.p90, `${listing.listing.monthly_rent_krw} <= ${band.monthly_rent_krw.p90}`);
  }
});

test("어떤 행도 좌표가 원본에서 갖고 있던 면적을 그대로 쓰지 않는다", () => {
  const source = coords(60);
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": source }, perDistrict: 55 });
  const originalArea = new Map(source.map((record) => [`${record.lat},${record.lng}`, record.area_m2]));
  for (const listing of listings) {
    const key = `${listing.latitude},${listing.longitude}`;
    assert.notEqual(listing.listing.area_m2, originalArea.get(key), `${key} 의 면적이 원본과 같습니다`);
  }
});

test("좌표와 면적이 모두 충돌해도 재샘플링으로 벗어난다", () => {
  // Collapse the area distribution to a single point to force a collision.
  const pinned = { districts: { "강남구": { ...DISTRIBUTION.districts["강남구"], area: { p10: 40, p25: 40, p50: 40, p75: 40, p90: 40, n: 50 } } } };
  const source = [{ lat: 37.5, lng: 127.03, sido: "서울특별시", sigungu: "강남구", dong: "역삼동", floor: 1, area_m2: 40 }];
  const listings = buildListings({ distribution: pinned, coordsByDistrict: { "강남구": source }, perDistrict: 1 });
  assert.notEqual(listings[0].listing.area_m2, 40);
});

test("같은 시드로 두 번 돌리면 결과가 같다", () => {
  const input = { distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 };
  assert.deepEqual(buildListings(input), buildListings(input));
});

test("보증금은 월세보다 크고 백만원 단위로 반올림된다", () => {
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 });
  for (const listing of listings) {
    assert.ok(listing.listing.deposit_krw > listing.listing.monthly_rent_krw);
    assert.equal(listing.listing.deposit_krw % 1_000_000, 0);
  }
});

test("P90이 만원 배수가 아니어도 월세가 범위를 넘지 않는다", () => {
  const odd = { districts: { "강남구": { area: DISTRIBUTION.districts["강남구"].area, bands: {
    M: { label: "33~66㎡", n: 20,
         monthly_rent_krw: { p10: 1_003_000, p25: 1_207_000, p50: 1_411_000, p75: 1_615_000, p90: 1_819_000, n: 20 },
         deposit_multiple: { p10: 10, p25: 13, p50: 16, p75: 20, p90: 28, n: 20 } } } } } };
  const listings = buildListings({ distribution: odd, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 });
  for (const listing of listings) {
    assert.ok(listing.listing.monthly_rent_krw >= 1_003_000, `${listing.listing.monthly_rent_krw} >= 1003000`);
    assert.ok(listing.listing.monthly_rent_krw <= 1_819_000, `${listing.listing.monthly_rent_krw} <= 1819000`);
    assert.equal(listing.listing.monthly_rent_krw % 10_000, 0);
  }
});

test("월세는 만원 단위로 반올림된다", () => {
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 });
  assert.ok(listings.every((listing) => listing.listing.monthly_rent_krw % 10_000 === 0));
});

test("매물명은 행정동과 층으로 만들고 상호를 쓰지 않는다", () => {
  const listings = buildListings({ distribution: DISTRIBUTION, coordsByDistrict: { "강남구": coords(60) }, perDistrict: 55 });
  assert.ok(listings.every((listing) => /^역삼동 -?\d+층 상가$/.test(listing.name)));
});

test("sampleArea는 구 면적 분포의 P10~P90 안에 있다", () => {
  const rng = createRng(1);
  const area = DISTRIBUTION.districts["강남구"].area;
  for (let i = 0; i < 200; i += 1) {
    const value = sampleArea(area, rng, null);
    assert.ok(value >= area.p10 && value <= area.p90);
  }
});
