import assert from "node:assert/strict";
import test from "node:test";
import { buildDistribution } from "./build-distribution.mjs";

function priceRows(count, { sigungu = "강남구", area = 40, rent = 1_800_000, deposit = 30_000_000 } = {}) {
  return Array.from({ length: count }, (_, index) => ({
    sigungu, area_m2: area + index, monthly_rent_krw: rent + index * 10_000, deposit_krw: deposit + index * 100_000,
  }));
}

test("구별 면적 분위수를 낸다", () => {
  const result = buildDistribution(priceRows(20));
  assert.ok(result.districts["강남구"].area.p50 > 0);
  assert.equal(result.districts["강남구"].area.n, 20);
});

test("면적구간별 월세 분위수를 낸다", () => {
  const result = buildDistribution(priceRows(20, { area: 34 }));
  const band = result.districts["강남구"].bands["M"];
  assert.ok(band.monthly_rent_krw.p10 <= band.monthly_rent_krw.p90);
  assert.equal(band.label, "33~66㎡");
});

test("보증금은 월세 배수로 저장한다", () => {
  const result = buildDistribution(priceRows(20, { area: 34, rent: 1_000_000, deposit: 20_000_000 }));
  const band = result.districts["강남구"].bands["M"];
  assert.ok(band.deposit_multiple.p50 > 1);
});

test("표본 5건 미만 구간은 상위 구간으로 병합한다", () => {
  const rows = [...priceRows(20, { area: 34 }), ...priceRows(3, { area: 100 })];
  const result = buildDistribution(rows);
  const bands = result.districts["강남구"].bands;
  assert.equal(bands["XL"], undefined);
  assert.ok(bands["L"] || bands["M"]);
  assert.ok(result.merges.some((entry) => entry.district === "강남구" && entry.from === "XL"));
});

test("모든 구간이 5건 미만이면 구 전체를 하나로 합친다", () => {
  const result = buildDistribution(priceRows(3, { area: 34 }));
  assert.equal(Object.keys(result.districts["강남구"].bands).length, 1);
});

test("가격 행이 없으면 거부한다", () => {
  assert.throws(() => buildDistribution([]), /empty/);
});

test("월세가 0인 행은 거부한다", () => {
  const rows = [...priceRows(20, { area: 34 }), { sigungu: "강남구", area_m2: 40, monthly_rent_krw: 0, deposit_krw: 10_000_000 }];
  assert.throws(() => buildDistribution(rows), /monthly_rent_krw/);
});
