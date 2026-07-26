import assert from "node:assert/strict";
import test from "node:test";
import { quantile, quantileSet, sampleFromQuantiles, QUANTILE_KNOTS } from "./quantile.mjs";

test("quantile은 정렬된 배열의 중앙값을 낸다", () => {
  assert.equal(quantile([1, 2, 3, 4, 5], 0.5), 3);
});

test("quantile은 knot 사이를 선형 보간한다", () => {
  assert.equal(quantile([0, 10], 0.5), 5);
  assert.equal(quantile([0, 10], 0.25), 2.5);
});

test("quantile은 양 끝을 clamp한다", () => {
  assert.equal(quantile([4, 8], 0), 4);
  assert.equal(quantile([4, 8], 1), 8);
});

test("quantile은 빈 배열을 거부한다", () => {
  assert.throws(() => quantile([], 0.5), /at least one/);
});

test("quantileSet은 P10~P90 다섯 개를 낸다", () => {
  const set = quantileSet([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]);
  assert.deepEqual(Object.keys(set), ["p10", "p25", "p50", "p75", "p90", "n"]);
  assert.equal(set.n, 10);
  assert.equal(set.p50, 55);
});

test("quantileSet은 입력 배열을 정렬하지 않고 복사해서 쓴다", () => {
  const input = [30, 10, 20];
  quantileSet(input);
  assert.deepEqual(input, [30, 10, 20]);
});

test("sampleFromQuantiles는 항상 P10~P90 안에 있다", () => {
  const set = { p10: 100, p25: 150, p50: 200, p75: 300, p90: 500, n: 40 };
  let cursor = 0;
  const values = [0, 0.001, 0.25, 0.5, 0.75, 0.999, 1];
  const rng = () => values[cursor++ % values.length];
  for (let i = 0; i < values.length; i += 1) {
    const drawn = sampleFromQuantiles(set, rng);
    assert.ok(drawn >= set.p10, `${drawn} >= ${set.p10}`);
    assert.ok(drawn <= set.p90, `${drawn} <= ${set.p90}`);
  }
});

test("sampleFromQuantiles는 u=0에서 P10, u=1에서 P90을 낸다", () => {
  const set = { p10: 100, p25: 150, p50: 200, p75: 300, p90: 500, n: 40 };
  assert.equal(sampleFromQuantiles(set, () => 0), 100);
  assert.equal(sampleFromQuantiles(set, () => 1), 500);
});

test("QUANTILE_KNOTS는 P10부터 P90까지 오름차순이다", () => {
  assert.deepEqual(QUANTILE_KNOTS, [0.1, 0.25, 0.5, 0.75, 0.9]);
});

test("quantileSet은 NaN을 거부한다", () => {
  assert.throws(() => quantileSet([5, 2, NaN, 9]), /finite/);
});

test("quantileSet은 Infinity를 거부한다", () => {
  assert.throws(() => quantileSet([1, 2, Infinity]), /finite/);
});

test("sampleFromQuantiles는 비단조 분위수 집합을 거부한다", () => {
  assert.throws(() => sampleFromQuantiles({ p10: 100, p25: 50, p50: 200, p75: 300, p90: 500, n: 5 }, () => 0.1), /non-decreasing/);
});

test("sampleFromQuantiles는 모든 knot이 같으면 그 값을 낸다", () => {
  const flat = { p10: 42, p25: 42, p50: 42, p75: 42, p90: 42, n: 9 };
  for (const u of [0, 0.3, 0.7, 1]) assert.equal(sampleFromQuantiles(flat, () => u), 42);
});
