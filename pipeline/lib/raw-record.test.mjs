import assert from "node:assert/strict";
import test from "node:test";
import { RAW_FIELDS, pickRawFields } from "./raw-record.mjs";

const VALID = { lat: 37.5006, lng: 127.0364, sido: "서울특별시", sigungu: "강남구", dong: "역삼동", floor: 1, area_m2: 33.1 };

test("화이트리스트는 일곱 필드다", () => {
  assert.deepEqual(RAW_FIELDS, ["lat", "lng", "sido", "sigungu", "dong", "floor", "area_m2"]);
});

test("정상 레코드를 그대로 통과시킨다", () => {
  assert.deepEqual(pickRawFields(VALID), VALID);
});

test("화이트리스트 밖 필드를 전부 떨어뜨린다", () => {
  const polluted = { ...VALID, articleNo: "2512345678", realtorName: "OO공인중개사", price: 3000, imageUrl: "https://example.test/a.jpg", description: "역세권 1층" };
  const result = pickRawFields(polluted);
  assert.deepEqual(Object.keys(result).sort(), [...RAW_FIELDS].sort());
  assert.equal(result.articleNo, undefined);
  assert.equal(result.price, undefined);
});

test("좌표가 없으면 거부한다", () => {
  assert.throws(() => pickRawFields({ ...VALID, lat: undefined }), /lat/);
});

test("좌표가 숫자가 아니면 거부한다", () => {
  assert.throws(() => pickRawFields({ ...VALID, lng: "127.0364" }), /lng/);
});

test("면적이 0 이하면 거부한다", () => {
  assert.throws(() => pickRawFields({ ...VALID, area_m2: 0 }), /area_m2/);
});

test("서울 밖 좌표는 거부한다", () => {
  assert.throws(() => pickRawFields({ ...VALID, lat: 35.1796 }), /Seoul/);
});
