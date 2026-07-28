import assert from "node:assert/strict";
import test from "node:test";
import { aggregate, buildBenchmarks, districtOf, median } from "./build-trade-area.mjs";

const geometry = [
  { TRDAR_CD: "1", TRDAR_CD_NM: "가상권", ADSTRD_CD: "11680600", ADSTRD_CD_NM: "대치1동", SIGNGU_CD_NM: "강남구" },
  { TRDAR_CD: "2", TRDAR_CD_NM: "나상권", ADSTRD_CD: "11680600", ADSTRD_CD_NM: "대치1동", SIGNGU_CD_NM: "강남구" },
];

test("자치구·행정동은 코드 기준으로 다수결 해석한다", () => {
  // 상권이 경계에 걸치면 원자료의 SIGNGU_CD_NM 에 이웃 구가 들어온다. 같은 행정동 코드에
  // 붙은 구 이름 중 더 많은 쪽을 택해 한 코드가 두 구로 갈라지지 않게 한다.
  const resolved = districtOf([
    ...geometry,
    { TRDAR_CD: "3", ADSTRD_CD: "11680600", ADSTRD_CD_NM: "대치1동", SIGNGU_CD_NM: "서초구" },
  ]);
  assert.equal(resolved.get("11680600").district, "강남구");
  assert.equal(resolved.get("11680600").admin_dong, "대치1동");
});

test("개폐업률은 상권별 비율의 평균이 아니라 합계끼리 나눈 값이다", () => {
  // 점포 2곳 중 1곳 폐업(50%)과 점포 98곳 중 1곳 폐업(약 1%). 비율을 평균하면 25.5%가
  // 되지만, 실제로는 100곳 중 2곳이 닫혔으므로 2%다.
  const stores = [
    { TRDAR_CD: "1", SVC_INDUTY_CD: "CS100010", SVC_INDUTY_CD_NM: "커피-음료", STOR_CO: 2, SIMILR_INDUTY_STOR_CO: 2, FRC_STOR_CO: 0, OPBIZ_STOR_CO: 0, CLSBIZ_STOR_CO: 1 },
    { TRDAR_CD: "2", SVC_INDUTY_CD: "CS100010", SVC_INDUTY_CD_NM: "커피-음료", STOR_CO: 98, SIMILR_INDUTY_STOR_CO: 98, FRC_STOR_CO: 0, OPBIZ_STOR_CO: 0, CLSBIZ_STOR_CO: 1 },
  ];
  const { dongs } = aggregate({ geometry, stores, sales: [], footfall: [] });
  assert.equal(dongs["11680600"].industries.CS100010.close_rate, 2);
  assert.equal(dongs["11680600"].industries.CS100010.store_count, 100);
});

test("점포당 매출의 분모는 매출이 확인된 상권의 점포만 센다", () => {
  const stores = [
    { TRDAR_CD: "1", SVC_INDUTY_CD: "CS100010", SVC_INDUTY_CD_NM: "커피-음료", STOR_CO: 10, SIMILR_INDUTY_STOR_CO: 10, FRC_STOR_CO: 0, OPBIZ_STOR_CO: 0, CLSBIZ_STOR_CO: 0 },
    { TRDAR_CD: "2", SVC_INDUTY_CD: "CS100010", SVC_INDUTY_CD_NM: "커피-음료", STOR_CO: 90, SIMILR_INDUTY_STOR_CO: 90, FRC_STOR_CO: 0, OPBIZ_STOR_CO: 0, CLSBIZ_STOR_CO: 0 },
  ];
  // 매출은 1번 상권만 확인된다. 분모가 100이면 점포당 1,000만원으로 낮아지지만
  // 실제로 근거가 있는 것은 10곳에 대한 1억이므로 1,000만원이 아니라 1,000만원 × 10 / 10 이다.
  const sales = [{ TRDAR_CD: "1", SVC_INDUTY_CD: "CS100010", THSMON_SELNG_AMT: 100_000_000, THSMON_SELNG_CO: 1000 }];
  const { dongs } = aggregate({ geometry, stores, sales, footfall: [] });
  const cafe = dongs["11680600"].industries.CS100010;
  assert.equal(cafe.sales_store_count, 10);
  assert.equal(cafe.sales_per_store_krw, 10_000_000);
  assert.equal(cafe.sales_trade_area_count, 1);
  assert.equal(cafe.trade_area_count, 2);
});

test("점포가 최소 기준에 못 미치는 업종은 싣지 않는다", () => {
  const stores = [
    { TRDAR_CD: "1", SVC_INDUTY_CD: "CS100010", SVC_INDUTY_CD_NM: "커피-음료", STOR_CO: 3, SIMILR_INDUTY_STOR_CO: 3, FRC_STOR_CO: 0, OPBIZ_STOR_CO: 0, CLSBIZ_STOR_CO: 1 },
  ];
  const { dongs } = aggregate({ geometry, stores, sales: [], footfall: [] });
  assert.deepEqual(dongs["11680600"].industries, {});
});

test("상권이 하나뿐인 행정동도 점포가 충분하면 판정 대상이다", () => {
  const stores = [
    { TRDAR_CD: "1", SVC_INDUTY_CD: "CS100010", SVC_INDUTY_CD_NM: "커피-음료", STOR_CO: 40, SIMILR_INDUTY_STOR_CO: 40, FRC_STOR_CO: 5, OPBIZ_STOR_CO: 2, CLSBIZ_STOR_CO: 2 },
  ];
  const { dongs } = aggregate({ geometry: [geometry[0]], stores, sales: [], footfall: [] });
  assert.equal(dongs["11680600"].industries.CS100010.store_count, 40);
  assert.equal(dongs["11680600"].industries.CS100010.close_rate, 5);
});

test("매출이 없으면 매출 관련 값만 비고 나머지는 남는다", () => {
  const stores = [
    { TRDAR_CD: "1", SVC_INDUTY_CD: "CS100010", SVC_INDUTY_CD_NM: "커피-음료", STOR_CO: 20, SIMILR_INDUTY_STOR_CO: 20, FRC_STOR_CO: 0, OPBIZ_STOR_CO: 1, CLSBIZ_STOR_CO: 1 },
  ];
  const { dongs } = aggregate({ geometry: [geometry[0]], stores, sales: [], footfall: [] });
  const cafe = dongs["11680600"].industries.CS100010;
  assert.equal(cafe.monthly_sales_krw, null);
  assert.equal(cafe.sales_per_store_krw, null);
  assert.equal(cafe.close_rate, 5);
});

test("유동인구는 행정동 안 상권들의 합이다", () => {
  const footfall = [
    { TRDAR_CD: "1", TOT_FLPOP_CO: 1000 },
    { TRDAR_CD: "2", TOT_FLPOP_CO: 2000 },
  ];
  const { dongs } = aggregate({ geometry, stores: [], sales: [], footfall });
  assert.equal(dongs["11680600"].footfall_monthly, 3000);
  assert.equal(dongs["11680600"].footfall_trade_areas, 2);
});

test("기준선은 평균이 아니라 중앙값이다", () => {
  assert.equal(median([1, 2, 3]), 2);
  assert.equal(median([1, 2, 3, 100]), 2.5);
  assert.equal(median([]), null);
});

test("업종 기준선은 표본 수를 함께 남긴다", () => {
  const dongs = {
    a: { footfall_monthly: 1000, industries: { CS100010: { sales_per_store_krw: 10, close_rate: 1, store_count: 10 } } },
    b: { footfall_monthly: 2000, industries: { CS100010: { sales_per_store_krw: 30, close_rate: 3, store_count: 20 } } },
  };
  const benchmarks = buildBenchmarks(dongs);
  assert.equal(benchmarks.CS100010.sales_per_store_krw_median, 20);
  assert.equal(benchmarks.CS100010.sales_dong_n, 2);
  assert.equal(benchmarks.CS100010.close_rate_median, 2);
});
