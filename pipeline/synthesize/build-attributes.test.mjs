import assert from "node:assert/strict";
import test from "node:test";
import { ASSUMED_FRONTAGE } from "../lib/attribute-constants.mjs";
import { attachAttributes, attributesFor, seedFor, weightedPick } from "./build-attributes.mjs";
import { createRng } from "../lib/rng.mjs";

const listing = (id, overrides = {}) => ({
  id, name: "테스트 상가", district: "강남구",
  listing: {
    listing_kind: "DEMO_SYNTHETIC", deposit_krw: 30_000_000, monthly_rent_krw: 2_000_000,
    maintenance_fee_krw: 160_000, area_m2: 50, floor: 1, ...overrides,
  },
});

test("같은 매물은 언제나 같은 속성을 얻는다", () => {
  assert.deepEqual(attributesFor(listing("demo-강남구-0001")), attributesFor(listing("demo-강남구-0001")));
});

test("속성은 배열 순서가 아니라 매물 id 에만 의존한다", () => {
  // 앞에 매물을 끼워 넣어도 기존 매물의 속성이 바뀌면 안 된다.
  const before = attachAttributes([listing("demo-강남구-0002")])[0].listing;
  const after = attachAttributes([listing("demo-강남구-0009"), listing("demo-강남구-0002")])[1].listing;
  assert.deepEqual(before, after);
});

test("다른 매물은 서로 다른 속성을 얻는다", () => {
  const a = attributesFor(listing("demo-강남구-0001"));
  const b = attributesFor(listing("demo-마포구-0031"));
  assert.notDeepEqual(a, b);
});

test("실측에서 온 임대 조건은 덮어쓰지 않는다", () => {
  const [result] = attachAttributes([listing("demo-강남구-0001")]);
  assert.equal(result.listing.monthly_rent_krw, 2_000_000);
  assert.equal(result.listing.area_m2, 50);
  assert.equal(result.listing.deposit_krw, 30_000_000);
  assert.equal(result.listing.floor, 1);
});

test("전용면적은 계약면적을 넘지 않는다", () => {
  for (let index = 1; index <= 300; index += 1) {
    const source = listing(`demo-강남구-${String(index).padStart(4, "0")}`);
    const { exclusive_area_m2 } = attributesFor(source);
    assert.ok(exclusive_area_m2 > 0 && exclusive_area_m2 <= source.listing.area_m2,
      `전용 ${exclusive_area_m2} > 계약 ${source.listing.area_m2}`);
  }
});

test("총층수는 매물의 층보다 작을 수 없다", () => {
  for (let index = 1; index <= 300; index += 1) {
    const source = listing(`demo-중구-${String(index).padStart(4, "0")}`, { floor: 1 });
    assert.ok(attributesFor(source).floors_total >= source.listing.floor);
  }
});

test("높은 층 매물도 총층수 규칙을 지킨다", () => {
  const source = listing("demo-중구-0007", { floor: 15 });
  assert.ok(attributesFor(source).floors_total >= 15);
});

test("전면 폭은 선언한 범위 안에 있다", () => {
  for (const area of [5, 20, 60, 200, 900]) {
    const { frontage_m } = attributesFor(listing(`demo-강남구-a${area}`, { area_m2: area }));
    assert.ok(frontage_m >= ASSUMED_FRONTAGE.min && frontage_m <= ASSUMED_FRONTAGE.max, `${area}㎡ → ${frontage_m}m`);
  }
});

test("무권리 매물이 존재하고 권리금은 음수가 아니다", () => {
  const values = [];
  for (let index = 1; index <= 400; index += 1) {
    values.push(attributesFor(listing(`demo-강남구-${String(index).padStart(4, "0")}`)).key_money_krw);
  }
  assert.ok(values.every((value) => value >= 0));
  assert.ok(values.some((value) => value === 0), "무권리 매물이 하나도 없습니다");
  assert.ok(values.some((value) => value > 0), "권리금 있는 매물이 하나도 없습니다");
});

test("입주가능일은 ISO 날짜다", () => {
  assert.match(attributesFor(listing("demo-강남구-0001")).available_from, /^\d{4}-\d{2}-\d{2}$/);
});

test("가중 추첨은 가중치를 따른다", () => {
  const rng = createRng(1);
  const counts = { a: 0, b: 0 };
  for (let index = 0; index < 2000; index += 1) counts[weightedPick([["a", 9], ["b", 1]], rng)] += 1;
  assert.ok(counts.a > counts.b * 4, `a=${counts.a} b=${counts.b}`);
});

test("시드는 id 문자열에서만 나온다", () => {
  assert.equal(seedFor("demo-강남구-0001"), seedFor("demo-강남구-0001"));
  assert.notEqual(seedFor("demo-강남구-0001"), seedFor("demo-강남구-0002"));
});
