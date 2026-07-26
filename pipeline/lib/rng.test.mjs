import assert from "node:assert/strict";
import test from "node:test";
import { createRng, shuffle } from "./rng.mjs";

test("같은 시드는 같은 수열을 낸다", () => {
  const first = createRng(20260727);
  const second = createRng(20260727);
  const left = Array.from({ length: 20 }, () => first());
  const right = Array.from({ length: 20 }, () => second());
  assert.deepEqual(left, right);
});

test("다른 시드는 다른 수열을 낸다", () => {
  const first = createRng(1);
  const second = createRng(2);
  assert.notDeepEqual(
    Array.from({ length: 20 }, () => first()),
    Array.from({ length: 20 }, () => second()),
  );
});

test("난수는 0 이상 1 미만이다", () => {
  const rng = createRng(7);
  for (let i = 0; i < 1000; i += 1) {
    const value = rng();
    assert.ok(value >= 0 && value < 1, `${value} out of range`);
  }
});

test("shuffle은 원본 배열을 바꾸지 않는다", () => {
  const input = [1, 2, 3, 4, 5];
  shuffle(input, createRng(1));
  assert.deepEqual(input, [1, 2, 3, 4, 5]);
});

test("shuffle은 같은 원소를 모두 보존한다", () => {
  const input = Array.from({ length: 50 }, (_, index) => index);
  const result = shuffle(input, createRng(3));
  assert.deepEqual([...result].sort((a, b) => a - b), input);
});

test("shuffle은 시드가 같으면 같은 순서를 낸다", () => {
  const input = Array.from({ length: 50 }, (_, index) => index);
  assert.deepEqual(shuffle(input, createRng(9)), shuffle(input, createRng(9)));
});

test("shuffle은 순서를 실제로 바꾼다", () => {
  const input = Array.from({ length: 50 }, (_, index) => index);
  assert.notDeepEqual(shuffle(input, createRng(9)), input);
});
