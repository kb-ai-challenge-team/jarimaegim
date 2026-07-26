# 시연용 매물 데이터 파이프라인 (Stage 0~3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 강남·마포·서초·성동·영등포 5개 구의 시연용 임대 매물 250~300건을 담은 `data/listings.seoul.json`을 재현 가능하게 생성한다.

**Architecture:** `pipeline/` 아래 4단계가 파일로만 통신한다. Stage 0이 좌표를 수집하고(1회성), Stage 1이 가격 분위수만 집계하고, Stage 2가 공공데이터로 그 분위수를 검증하고, Stage 3이 분위수에서 샘플링해 매물을 합성한다. 순수 함수(분위수 계산, 시드 RNG, 필드 화이트리스트)를 먼저 TDD로 만들고 그 위에 각 스테이지를 얹는다.

**Tech Stack:** Node 24 (ESM, `node --test`), Python 3.12 (pytest, backend/.venv), playwright-core 1.61

**설계 문서:** `docs/superpowers/specs/2026-07-27-listing-data-pipeline-design.md`

**범위 밖:** Stage 4(Supabase 적재), 백엔드 `ListingService`, 프론트엔드 변경. 이 계획은 `data/listings.seoul.json` 생성까지만 다룬다.

---

## File Structure

| 파일 | 책임 |
| --- | --- |
| `pipeline/README.md` | 1회 실행 정책, 스테이지별 실행법 |
| `pipeline/lib/constants.mjs` | 대상 5개 구, 면적구간 4개, 시드, 최소 표본 수 |
| `pipeline/lib/quantile.mjs` | 분위수 계산 + 분위수에서 역변환 샘플링 (순수) |
| `pipeline/lib/rng.mjs` | 시드 고정 PRNG, 셔플 (순수) |
| `pipeline/lib/raw-record.mjs` | 수집 필드 화이트리스트 강제 (순수) |
| `pipeline/crawl/collect-coords.mjs` | Stage 0 — Playwright 좌표 수집 |
| `pipeline/distribution/build-distribution.mjs` | Stage 1 — 분위수 집계 |
| `pipeline/verify/fetch_subway_rents.py` | Stage 2a — 서울교통공사 CSV 다운로드 |
| `pipeline/verify/cross_check.py` | Stage 2b — 교차검증 게이트 (순수 비교 함수 포함) |
| `pipeline/synthesize/build-listings.mjs` | Stage 3 — 매물 합성 |
| `pipeline/raw/` | 원본 (gitignore) |
| `data/rent-distribution.seoul.json` | Stage 1 산출물 (커밋) |
| `data/rent-distribution.verification.md` | Stage 2 산출물 (커밋) |
| `data/listings.seoul.json` | Stage 3 산출물 (커밋) |

테스트는 각 소스 옆에 `*.test.mjs`로 둔다 (`scripts/check-kakao-sdk.test.mjs` 관례와 동일). Python 테스트는 `backend/tests/` 관례를 따르되 파이프라인 전용이므로 `pipeline/verify/test_cross_check.py`에 둔다.

---

## Task 1: 파이프라인 뼈대와 공유 상수

**Files:**
- Create: `pipeline/lib/constants.mjs`
- Create: `pipeline/README.md`
- Modify: `.gitignore`
- Modify: `package.json`

- [ ] **Step 1: 상수 모듈 작성**

`pipeline/lib/constants.mjs`:

```js
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
  if (!band) throw new Error(`면적 ${areaM2}에 해당하는 구간이 없습니다`);
  return band;
}
```

- [ ] **Step 2: README 작성**

`pipeline/README.md`:

```markdown
# 시연용 매물 데이터 파이프라인

설계 문서: `docs/superpowers/specs/2026-07-27-listing-data-pipeline-design.md`

## 실행 정책

**Stage 0(좌표 수집)은 1회성이다.** 이미 실행이 끝났다면 다시 돌리지 않는다.
상시 크롤링 파이프라인으로 확장하지 않는다. 재실행이 필요한 경우
`pipeline/raw/`를 지우고 실행 확인 프롬프트에 명시적으로 동의해야 한다.

## 스테이지

| 단계 | 명령 | 입력 | 출력 |
| --- | --- | --- | --- |
| 0 수집 | `npm run pipeline:crawl` | (외부) | `pipeline/raw/coords.<구>.jsonl` |
| 1 분포 | `npm run pipeline:build` | `pipeline/raw/` | `data/rent-distribution.seoul.json` |
| 2 검증 | `npm run pipeline:verify` | Stage 1 산출물 | `data/rent-distribution.verification.md` |
| 3 합성 | `npm run pipeline:build` | Stage 1 산출물 | `data/listings.seoul.json` |

Stage 2는 게이트다. 실패하면 Stage 3 결과를 신뢰하지 않는다.

## 수집 필드 화이트리스트

Stage 0은 `lat, lng, sido, sigungu, dong, floor, area_m2` 일곱 필드만 저장한다.
매물번호·중개사·상호·사진·설명문·원본 URL·가격은 파서가 읽지 않는다.
`pipeline/lib/raw-record.mjs`가 이를 강제한다.
```

- [ ] **Step 3: gitignore에 원본 디렉터리 추가**

`.gitignore`의 `scripts/.tmp-*` 줄 아래에 추가:

```
pipeline/raw/
```

- [ ] **Step 4: npm 스크립트 추가**

`package.json`의 `"check:shell"` 줄 아래에 추가:

```json
    "pipeline:crawl": "node pipeline/crawl/collect-coords.mjs",
    "pipeline:build": "node pipeline/distribution/build-distribution.mjs && node pipeline/synthesize/build-listings.mjs",
    "pipeline:verify": "backend/.venv/bin/python pipeline/verify/cross_check.py",
    "test:pipeline": "node --test pipeline/lib/*.test.mjs pipeline/distribution/*.test.mjs pipeline/synthesize/*.test.mjs",
```

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/constants.mjs pipeline/README.md .gitignore package.json
git commit -m "chore: scaffold the listing data pipeline"
```

---

## Task 2: 분위수 계산과 역변환 샘플링

**Files:**
- Create: `pipeline/lib/quantile.mjs`
- Test: `pipeline/lib/quantile.test.mjs`

- [ ] **Step 1: 실패하는 테스트 작성**

`pipeline/lib/quantile.test.mjs`:

```js
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
```

- [ ] **Step 2: 실패 확인**

Run: `node --test pipeline/lib/quantile.test.mjs`
Expected: FAIL — `Cannot find module ... quantile.mjs`

- [ ] **Step 3: 구현**

`pipeline/lib/quantile.mjs`:

```js
/** Quantile knots used for inverse-transform sampling. Restricting to P10-P90 keeps tail outliers out of the result. */
export const QUANTILE_KNOTS = [0.1, 0.25, 0.5, 0.75, 0.9];

/** Linear-interpolated p-quantile of an already-sorted numeric array. */
export function quantile(sorted, p) {
  if (sorted.length === 0) throw new Error("quantile requires at least one value");
  if (p <= 0) return sorted[0];
  if (p >= 1) return sorted[sorted.length - 1];
  const position = (sorted.length - 1) * p;
  const lower = Math.floor(position);
  const upper = Math.ceil(position);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

/** Reduce an unsorted sample to the P10-P90 knots plus the sample size. */
export function quantileSet(values) {
  for (const value of values) {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error(`quantileSet requires finite numbers, received ${value}`);
    }
  }
  const sorted = [...values].sort((a, b) => a - b);
  const [p10, p25, p50, p75, p90] = QUANTILE_KNOTS.map((knot) => quantile(sorted, knot));
  return { p10, p25, p50, p75, p90, n: sorted.length };
}

/**
 * Inverse-transform sampling over the piecewise-linear CDF the knots describe.
 * Given rng() in [0,1], the result always lands within [p10, p90].
 */
export function sampleFromQuantiles(set, rng) {
  const values = [set.p10, set.p25, set.p50, set.p75, set.p90];
  for (let index = 0; index < values.length; index += 1) {
    if (!Number.isFinite(values[index])) throw new Error(`quantile knot ${QUANTILE_KNOTS[index]} is not finite: ${values[index]}`);
    if (index > 0 && values[index] < values[index - 1]) throw new Error("quantile knots must be non-decreasing");
  }
  const clamp = (value) => Math.min(Math.max(value, set.p10), set.p90);
  const span = QUANTILE_KNOTS[QUANTILE_KNOTS.length - 1] - QUANTILE_KNOTS[0];
  const u = QUANTILE_KNOTS[0] + rng() * span;
  for (let index = 1; index < QUANTILE_KNOTS.length; index += 1) {
    if (u <= QUANTILE_KNOTS[index]) {
      const width = QUANTILE_KNOTS[index] - QUANTILE_KNOTS[index - 1];
      const ratio = width === 0 ? 0 : (u - QUANTILE_KNOTS[index - 1]) / width;
      return clamp(values[index - 1] + (values[index] - values[index - 1]) * ratio);
    }
  }
  return clamp(values[values.length - 1]);
}
```

- [ ] **Step 4: 통과 확인**

Run: `node --test pipeline/lib/quantile.test.mjs`
Expected: PASS, 13 tests

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/quantile.mjs pipeline/lib/quantile.test.mjs
git commit -m "feat(pipeline): add quantile aggregation and inverse-transform sampling"
```

---

## Task 3: 시드 고정 RNG와 셔플

**Files:**
- Create: `pipeline/lib/rng.mjs`
- Test: `pipeline/lib/rng.test.mjs`

- [ ] **Step 1: 실패하는 테스트 작성**

`pipeline/lib/rng.test.mjs`:

```js
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
```

- [ ] **Step 2: 실패 확인**

Run: `node --test pipeline/lib/rng.test.mjs`
Expected: FAIL — `Cannot find module ... rng.mjs`

- [ ] **Step 3: 구현**

`pipeline/lib/rng.mjs`:

```js
/**
 * mulberry32. A PRNG fully determined by a single seed, so pipeline runs are reproducible.
 * Not for cryptographic use — only for generating demo data.
 */
export function createRng(seed) {
  let state = seed >>> 0;
  return function next() {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Fisher-Yates. Leaves the original array untouched and returns a new one. */
export function shuffle(items, rng) {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(rng() * (index + 1));
    [result[index], result[swap]] = [result[swap], result[index]];
  }
  return result;
}
```

- [ ] **Step 4: 통과 확인**

Run: `node --test pipeline/lib/rng.test.mjs`
Expected: PASS, 7 tests

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/rng.mjs pipeline/lib/rng.test.mjs
git commit -m "feat(pipeline): add a seeded rng and shuffle"
```

---

## Task 4: 수집 필드 화이트리스트

설계 문서 §2.1의 첫 번째 장치다. 크롤러가 무엇을 담든 이 함수를 통과한 것만 디스크에 남는다.

**Files:**
- Create: `pipeline/lib/raw-record.mjs`
- Test: `pipeline/lib/raw-record.test.mjs`

- [ ] **Step 1: 실패하는 테스트 작성**

`pipeline/lib/raw-record.test.mjs`:

```js
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
  assert.throws(() => pickRawFields({ ...VALID, lat: 35.1796 }), /서울/);
});
```

- [ ] **Step 2: 실패 확인**

Run: `node --test pipeline/lib/raw-record.test.mjs`
Expected: FAIL — `Cannot find module ... raw-record.mjs`

- [ ] **Step 3: 구현**

`pipeline/lib/raw-record.mjs`:

```js
/**
 * Collection field whitelist from design doc §2.1.
 * Listing number, broker, business name, photos, description, source URL, and price are
 * not in here, so they never land on disk.
 */
export const RAW_FIELDS = ["lat", "lng", "sido", "sigungu", "dong", "floor", "area_m2"];

/** A generous bounding box around Seoul's administrative area. Used to catch coordinate-parsing mistakes. */
const SEOUL_BOUNDS = { minLat: 37.41, maxLat: 37.72, minLng: 126.76, maxLng: 127.19 };

function requireNumber(source, field) {
  const value = source[field];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${field}가 유한한 숫자가 아닙니다: ${JSON.stringify(value)}`);
  }
  return value;
}

function requireText(source, field) {
  const value = source[field];
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${field}가 비어 있습니다`);
  }
  return value.trim();
}

/** Picks and validates only whitelisted fields. Records that fail validation throw. */
export function pickRawFields(source) {
  const lat = requireNumber(source, "lat");
  const lng = requireNumber(source, "lng");
  if (lat < SEOUL_BOUNDS.minLat || lat > SEOUL_BOUNDS.maxLat || lng < SEOUL_BOUNDS.minLng || lng > SEOUL_BOUNDS.maxLng) {
    throw new Error(`좌표가 서울 경계 밖입니다: ${lat}, ${lng}`);
  }
  const area = requireNumber(source, "area_m2");
  if (area <= 0) throw new Error(`area_m2는 0보다 커야 합니다: ${area}`);
  const floor = requireNumber(source, "floor");
  return {
    lat, lng,
    sido: requireText(source, "sido"),
    sigungu: requireText(source, "sigungu"),
    dong: requireText(source, "dong"),
    floor, area_m2: area,
  };
}
```

- [ ] **Step 4: 통과 확인**

Run: `node --test pipeline/lib/raw-record.test.mjs`
Expected: PASS, 7 tests

- [ ] **Step 5: 커밋**

```bash
git add pipeline/lib/raw-record.mjs pipeline/lib/raw-record.test.mjs
git commit -m "feat(pipeline): enforce the raw field whitelist"
```

---

## Task 5: Stage 0 좌표 수집기

**이 태스크는 외부 사이트에 실제로 접속한다.** 실행 전 사용자에게 확인받는다. 1회만 실행한다.

크롤러는 DOM 셀렉터가 아니라 **네트워크 응답을 가로채는 방식**을 쓴다. `new.land.naver.com`은 SPA라서 목록을 내부 JSON API로 받아오고, 그 응답을 잡는 편이 DOM 파싱보다 훨씬 안정적이다. 응답 스키마는 지금 알 수 없으므로 Step 2가 관찰 단계다.

**Files:**
- Create: `pipeline/crawl/collect-coords.mjs`

- [ ] **Step 1: 스켈레톤 작성 (관찰 모드)**

`pipeline/crawl/collect-coords.mjs`:

```js
import { createInterface } from "node:readline/promises";
import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { TARGET_DISTRICTS } from "../lib/constants.mjs";
import { pickRawFields } from "../lib/raw-record.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const RAW_DIR = join(ROOT, "raw");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

/** Design doc appendix: empirically verified deep-link parameters. a=SG (commercial), b=B2 (monthly rent), e=RETAIL */
const DISTRICT_CENTERS = {
  "강남구": { lat: 37.5172, lng: 127.0473 },
  "마포구": { lat: 37.5637, lng: 126.9084 },
  "서초구": { lat: 37.4837, lng: 127.0324 },
  "성동구": { lat: 37.5634, lng: 127.0369 },
  "영등포구": { lat: 37.5264, lng: 126.8962 },
};

function districtUrl(district) {
  const center = DISTRICT_CENTERS[district];
  return `https://new.land.naver.com/offices?ms=${center.lat},${center.lng},15&a=SG&b=B2&e=RETAIL`;
}

async function confirmOneShot() {
  if (process.env.PIPELINE_CRAWL_CONFIRM === "yes") return;
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const answer = await rl.question(
    "Stage 0은 1회성 수집입니다. 이미 pipeline/raw/에 결과가 있다면 중단하세요.\n계속하려면 'yes'를 입력하세요: ",
  );
  rl.close();
  if (answer.trim() !== "yes") { console.log("중단했습니다."); process.exit(0); }
}

/** Observation mode: dumps one raw listing-list response to inspect its schema. */
async function observe() {
  const browser = await chromium.launch({ executablePath: CHROME, headless: false });
  const page = await browser.newPage();
  const samples = [];
  page.on("response", async (response) => {
    const url = response.url();
    if (!url.includes("/api/articles")) return;
    try { samples.push({ url, body: await response.json() }); } catch { /* Ignore non-JSON responses */ }
  });
  await page.goto(districtUrl("강남구"), { waitUntil: "networkidle" });
  await fs.mkdir(RAW_DIR, { recursive: true });
  await fs.writeFile(join(RAW_DIR, "observed-schema.json"), JSON.stringify(samples.slice(0, 2), null, 2));
  await browser.close();
  console.log(`관찰 응답 ${samples.length}건을 pipeline/raw/observed-schema.json에 기록했습니다.`);
}

if (process.argv[2] === "observe") { await observe(); }
```

- [ ] **Step 2: 관찰 실행 — 응답 스키마 확인**

Run: `node pipeline/crawl/collect-coords.mjs observe`

Expected: 브라우저가 열리고 `pipeline/raw/observed-schema.json`이 생성된다.

그 파일을 읽어 매물 배열의 경로와 좌표·면적·층 필드 이름을 확인한다. 확인한 내용을 다음 형태로 이 계획 파일에 기록한 뒤 Step 3으로 간다:

```
매물 배열 경로: body.<경로>
좌표 필드: <이름> / <이름>
면적 필드: <이름>
층 필드: <이름>
법정동 필드: <이름>
월세 필드: <이름>   (단위도 함께 기록 — 만원인지 원인지)
보증금 필드: <이름> (단위도 함께 기록)
```

**응답을 잡지 못했을 때의 대체 경로:** `/api/articles`가 안 잡히면 `page.on("response")` 필터를 `url.includes("land.naver.com/api")`로 넓혀 다시 관찰한다. 그래도 못 잡으면 이 태스크를 중단하고 사용자에게 보고한다. 추측한 셀렉터로 진행하지 않는다.

- [ ] **Step 3: 수집 구현**

두 종류의 파일을 쓴다. 이유는 두 데이터의 수명이 다르기 때문이다.

- `coords.<구>.jsonl` — 화이트리스트를 통과한 좌표. Stage 3까지 살아남는다.
- `prices.<구>.jsonl` — 가격 표본. Stage 1의 분위수 집계에만 쓰이고 **개별값은 결과물에 남지 않는다.** 그래서 화이트리스트(디스크에 오래 남는 좌표를 지키는 장치)와 별도 경로다. 둘 다 `pipeline/raw/`라 gitignore 대상이다.

Step 2에서 확인한 필드 이름으로 아래 코드의 `<...>` 자리를 채운다. 이것이 Step 2 결과로 대체되는 유일한 지점이다.

`pipeline/crawl/collect-coords.mjs`의 `observe()` 아래에 추가:

```js
/** Maps the response schema observed in Step 2 into a whitelisted record. */
function toRawRecord(article, district) {
  return pickRawFields({
    lat: Number(article.<좌표필드_위도>),
    lng: Number(article.<좌표필드_경도>),
    sido: "서울특별시",
    sigungu: district,
    dong: String(article.<법정동필드>),
    floor: Number(String(article.<층필드>).replace(/[^0-9-]/g, "")),
    area_m2: Number(article.<면적필드>),
  });
}

/**
 * Price samples. If Step 2 confirms the unit is 10k-won, set UNIT to 10000.
 * Getting this unit wrong makes Stage 2 cross-check fail by a 100x ratio, so it's caught there.
 */
const PRICE_UNIT = 10000;

function toPriceRow(article, district) {
  const rent = Number(article.<월세필드>) * PRICE_UNIT;
  const deposit = Number(article.<보증금필드>) * PRICE_UNIT;
  const area = Number(article.<면적필드>);
  if (!Number.isFinite(rent) || !Number.isFinite(deposit) || !Number.isFinite(area)) return null;
  if (rent <= 0 || deposit <= 0 || area <= 0) return null;
  return { sigungu: district, area_m2: area, monthly_rent_krw: rent, deposit_krw: deposit };
}

async function collectDistrict(page, district) {
  const coords = new Map();
  const prices = [];
  page.on("response", async (response) => {
    if (!response.url().includes("/api/articles")) return;
    let body;
    try { body = await response.json(); } catch { return; }
    for (const article of body.<매물배열경로> ?? []) {
      try {
        const record = toRawRecord(article, district);
        coords.set(`${record.lat},${record.lng},${record.area_m2},${record.floor}`, record);
      } catch { continue; } // Drop records that fail whitelist validation
      const price = toPriceRow(article, district);
      if (price) prices.push(price);
    }
  });
  await page.goto(districtUrl(district), { waitUntil: "networkidle" });
  // Scroll the listing panel to the end to load additional pages.
  for (let round = 0; round < 12 && coords.size < 120; round += 1) {
    await page.mouse.wheel(0, 4000);
    await page.waitForTimeout(1200);
  }
  return { records: [...coords.values()], prices };
}

async function writeJsonl(path, rows) {
  await fs.writeFile(path, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
}

async function collect() {
  await confirmOneShot();
  await fs.mkdir(RAW_DIR, { recursive: true });
  const browser = await chromium.launch({ executablePath: CHROME, headless: false });
  for (const district of TARGET_DISTRICTS) {
    const page = await browser.newPage();
    const { records, prices } = await collectDistrict(page, district);
    await page.close();
    await writeJsonl(join(RAW_DIR, `coords.${district}.jsonl`), records);
    await writeJsonl(join(RAW_DIR, `prices.${district}.jsonl`), prices);
    console.log(`${district}: 좌표 ${records.length}건, 가격 ${prices.length}건`);
    await new Promise((resolve) => setTimeout(resolve, 5000)); // Pause between districts
  }
  await browser.close();
}

if (process.argv[2] !== "observe") { await collect(); }
```

기존 `if (process.argv[2] === "observe") { await observe(); }` 줄은 삭제하고 위 두 분기로 대체한다.

- [ ] **Step 4: 수집 실행**

Run: `npm run pipeline:crawl`

Expected: 5개 구 각각 `coords.<구>.jsonl`과 `prices.<구>.jsonl` 생성, 구당 좌표 40건 이상.

40건 미만인 구가 있으면 스크롤 라운드를 늘려 그 구만 다시 돌린다.

- [ ] **Step 5: 화이트리스트 준수 확인**

Run:

```bash
node -e '
const fs=require("node:fs");
const files=fs.readdirSync("pipeline/raw").filter(f=>f.startsWith("coords."));
const allowed=["lat","lng","sido","sigungu","dong","floor","area_m2"].sort().join(",");
let total=0;
for(const f of files){
  for(const line of fs.readFileSync("pipeline/raw/"+f,"utf8").trim().split("\n")){
    const keys=Object.keys(JSON.parse(line)).sort().join(",");
    if(keys!==allowed) throw new Error(f+" 에 화이트리스트 밖 필드: "+keys);
    total++;
  }
}
console.log("OK", files.length, "개 구,", total, "건");
'
```

Expected: `OK 5 개 구, <250 이상> 건`

- [ ] **Step 6: 커밋 (수집기만, 원본은 gitignore)**

```bash
git add pipeline/crawl/collect-coords.mjs
git status --short   # pipeline/raw/ 가 목록에 없어야 한다
git commit -m "feat(pipeline): add the one-shot coordinate collector"
```

---

## Task 6: Stage 1 분포 집계

**Files:**
- Create: `pipeline/distribution/build-distribution.mjs`
- Test: `pipeline/distribution/build-distribution.test.mjs`

입력은 Task 5가 쓴 `pipeline/raw/prices.<구>.jsonl` (`{ sigungu, area_m2, monthly_rent_krw, deposit_krw }`)이다. 이 태스크는 그 표본에서 분위수만 뽑고 개별 가격은 버린다.

- [ ] **Step 1: 실패하는 테스트 작성**

`pipeline/distribution/build-distribution.test.mjs`:

```js
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
  assert.throws(() => buildDistribution([]), /가격 표본/);
});
```

- [ ] **Step 2: 실패 확인**

Run: `node --test pipeline/distribution/build-distribution.test.mjs`
Expected: FAIL — `Cannot find module ... build-distribution.mjs`

- [ ] **Step 3: 구현**

`pipeline/distribution/build-distribution.mjs`:

```js
import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AREA_BANDS, MIN_BAND_SAMPLES, TARGET_DISTRICTS, bandForArea } from "../lib/constants.mjs";
import { quantileSet } from "../lib/quantile.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const OUTPUT = join(ROOT, "data", "rent-distribution.seoul.json");

/**
 * Produces per-district area quantiles and per-band rent/deposit-multiple quantiles from price samples.
 * Bands with fewer samples than MIN_BAND_SAMPLES are merged into the adjacent band, recorded in merges.
 */
export function buildDistribution(rows) {
  if (rows.length === 0) throw new Error("가격 표본이 비어 있습니다");
  const districts = {};
  const merges = [];

  for (const district of new Set(rows.map((row) => row.sigungu))) {
    const districtRows = rows.filter((row) => row.sigungu === district);
    const grouped = new Map(AREA_BANDS.map((band) => [band.key, []]));
    for (const row of districtRows) grouped.get(bandForArea(row.area_m2).key).push(row);

    // Fold small bands into the next-lower adjacent band, in order XL → L → M → S.
    const order = [...AREA_BANDS].reverse();
    for (let index = 0; index < order.length - 1; index += 1) {
      const current = order[index], next = order[index + 1];
      const bucket = grouped.get(current.key);
      if (bucket.length > 0 && bucket.length < MIN_BAND_SAMPLES) {
        grouped.get(next.key).push(...bucket);
        grouped.set(current.key, []);
        merges.push({ district, from: current.key, into: next.key, moved: bucket.length });
      }
    }
    // If the smallest remaining band is still under the threshold after folding, merge the whole district into one.
    const surviving = AREA_BANDS.filter((band) => grouped.get(band.key).length > 0);
    if (surviving.length > 0 && grouped.get(surviving[0].key).length < MIN_BAND_SAMPLES) {
      const all = surviving.flatMap((band) => grouped.get(band.key));
      for (const band of surviving) grouped.set(band.key, []);
      grouped.set(surviving[surviving.length - 1].key, all);
      for (const band of surviving.slice(0, -1)) {
        merges.push({ district, from: band.key, into: surviving[surviving.length - 1].key, moved: 0 });
      }
    }

    const bands = {};
    for (const band of AREA_BANDS) {
      const bucket = grouped.get(band.key);
      if (bucket.length === 0) continue;
      bands[band.key] = {
        label: band.label,
        n: bucket.length,
        monthly_rent_krw: quantileSet(bucket.map((row) => row.monthly_rent_krw)),
        deposit_multiple: quantileSet(bucket.map((row) => row.deposit_krw / row.monthly_rent_krw)),
      };
    }
    districts[district] = { area: quantileSet(districtRows.map((row) => row.area_m2)), bands };
  }
  return { districts, merges };
}

async function readPriceRows() {
  const rows = [];
  for (const district of TARGET_DISTRICTS) {
    const path = join(RAW_DIR, `prices.${district}.jsonl`);
    const text = await fs.readFile(path, "utf8");
    for (const line of text.trim().split("\n")) rows.push(JSON.parse(line));
  }
  return rows;
}

async function main() {
  const rows = await readPriceRows();
  const distribution = buildDistribution(rows);
  const payload = {
    generated_at: new Date().toISOString(),
    source: { kind: "one_time_crawl", note: "개별 매물 가격은 저장하지 않고 분위수만 남깁니다." },
    ...distribution,
  };
  await fs.mkdir(dirname(OUTPUT), { recursive: true });
  await fs.writeFile(OUTPUT, JSON.stringify(payload, null, 2) + "\n");
  console.log(`분포 산출 완료: ${OUTPUT} (표본 ${rows.length}건, 병합 ${distribution.merges.length}건)`);
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
```

- [ ] **Step 4: 통과 확인**

Run: `node --test pipeline/distribution/build-distribution.test.mjs`
Expected: PASS, 6 tests

- [ ] **Step 5: 실제 분포 생성**

Run: `node pipeline/distribution/build-distribution.mjs`
Expected: `분포 산출 완료: .../data/rent-distribution.seoul.json (표본 250 이상건, 병합 N건)`

- [ ] **Step 6: 커밋**

```bash
git add pipeline/distribution/ data/rent-distribution.seoul.json
git commit -m "feat(pipeline): aggregate rent quantiles by district and area band"
```

---

## Task 7: Stage 2 공공데이터 교차검증 게이트

**Files:**
- Create: `pipeline/verify/fetch_subway_rents.py`
- Create: `pipeline/verify/cross_check.py`
- Test: `pipeline/verify/test_cross_check.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`pipeline/verify/test_cross_check.py`:

```python
import pytest

from cross_check import BASELINE_KRW_PER_M2, RATIO_MAX, RATIO_MIN, evaluate_district, summarize


def band(p50: float) -> dict:
    return {"label": "33~66㎡", "n": 20,
            "monthly_rent_krw": {"p10": p50 * 0.5, "p25": p50 * 0.8, "p50": p50, "p75": p50 * 1.3, "p90": p50 * 2.0, "n": 20},
            "deposit_multiple": {"p10": 10, "p25": 14, "p50": 16, "p75": 20, "p90": 30, "n": 20}}


def district(p50_rent: float, area_p50: float = 50.0) -> dict:
    return {"area": {"p10": 30, "p25": 40, "p50": area_p50, "p75": 60, "p90": 80, "n": 20},
            "bands": {"M": band(p50_rent)}}


def test_baseline_is_the_measured_subway_median():
    assert BASELINE_KRW_PER_M2 == 98770


def test_ratio_window_matches_the_design():
    assert (RATIO_MIN, RATIO_MAX) == (0.5, 3.0)


def test_a_plausible_district_passes():
    # 50㎡ × 98,770 won/㎡ ≈ 4.94M won. Ratio should be exactly 1.0
    result = evaluate_district("강남구", district(4_938_500))
    assert result["ok"] is True
    assert result["ratio"] == pytest.approx(1.0, abs=0.01)


def test_an_order_of_magnitude_error_fails():
    result = evaluate_district("강남구", district(49_385_000))
    assert result["ok"] is False
    assert result["ratio"] > RATIO_MAX


def test_a_far_too_cheap_district_fails():
    result = evaluate_district("강남구", district(1_000_000))
    assert result["ok"] is False
    assert result["ratio"] < RATIO_MIN


def test_summarize_fails_when_any_district_fails():
    districts = {"강남구": district(4_938_500), "마포구": district(49_385_000)}
    report = summarize(districts)
    assert report["ok"] is False
    assert len(report["results"]) == 2


def test_summarize_passes_when_all_districts_pass():
    districts = {"강남구": district(4_938_500), "마포구": district(3_000_000)}
    assert summarize(districts)["ok"] is True
```

- [ ] **Step 2: 실패 확인**

Run: `cd pipeline/verify && ../../backend/.venv/bin/python -m pytest test_cross_check.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cross_check'`

- [ ] **Step 3: 구현**

`pipeline/verify/cross_check.py`:

```python
"""Stage 2 — a gate that checks the crawled distribution against a public-data baseline.

The baseline is the median monthly rent per m² from Seoul Metro's underground
shopping-arcade rental data (OA-12927, as of 2025-12-31). Underground arcades and
ground-floor storefronts have different market rates, so the tolerance is set wide.
This gate is a safety net for order-of-magnitude errors, not a guarantee that the
market rate itself is accurate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASELINE_KRW_PER_M2 = 98_770
RATIO_MIN = 0.5
RATIO_MAX = 3.0

ROOT = Path(__file__).resolve().parents[2]
DISTRIBUTION_PATH = ROOT / "data" / "rent-distribution.seoul.json"
REPORT_PATH = ROOT / "data" / "rent-distribution.verification.md"


def evaluate_district(name: str, payload: dict) -> dict:
    """Compares a district's representative rent per m² against the baseline."""
    area_p50 = payload["area"]["p50"]
    bands = payload["bands"]
    largest = max(bands.values(), key=lambda band: band["n"])
    rent_p50 = largest["monthly_rent_krw"]["p50"]
    per_m2 = rent_p50 / area_p50
    ratio = per_m2 / BASELINE_KRW_PER_M2
    return {
        "district": name, "area_p50": area_p50, "rent_p50": rent_p50,
        "per_m2": per_m2, "ratio": ratio, "band_label": largest["label"], "n": largest["n"],
        "ok": RATIO_MIN <= ratio <= RATIO_MAX,
    }


def summarize(districts: dict) -> dict:
    results = [evaluate_district(name, payload) for name, payload in districts.items()]
    return {"ok": all(result["ok"] for result in results), "results": results}


def render_report(report: dict, merges: list) -> str:
    lines = [
        "# 시세 분포 교차검증 리포트", "",
        f"기준선: 서울교통공사 지하상가 임대정보 ㎡당 월임대료 중앙값 {BASELINE_KRW_PER_M2:,}원 (기준일 2025-12-31)",
        f"허용 범위: {RATIO_MIN}× ~ {RATIO_MAX}×", "",
        "지하상가와 지상 1층 상가는 시세대가 다르므로 범위를 넓게 잡았다.",
        "이 게이트는 자릿수 오류를 잡는 안전망이며 시세의 정확성을 보증하지 않는다.", "",
        "| 자치구 | 대표 구간 | 표본 | 면적 P50 | 월세 P50 | ㎡당 | 배수 | 판정 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in report["results"]:
        lines.append(
            f"| {result['district']} | {result['band_label']} | {result['n']} | "
            f"{result['area_p50']:.1f}㎡ | {result['rent_p50']:,.0f}원 | {result['per_m2']:,.0f}원 | "
            f"{result['ratio']:.2f}× | {'통과' if result['ok'] else '실패'} |"
        )
    lines += ["", f"**전체 판정: {'통과' if report['ok'] else '실패'}**", ""]
    if merges:
        lines += ["## 병합된 면적구간", "", "표본 5건 미만이라 상위 구간으로 접은 구간이다.", ""]
        lines += [f"- {entry['district']}: {entry['from']} → {entry['into']} ({entry['moved']}건)" for entry in merges]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    payload = json.loads(DISTRIBUTION_PATH.read_text(encoding="utf-8"))
    report = summarize(payload["districts"])
    REPORT_PATH.write_text(render_report(report, payload.get("merges", [])), encoding="utf-8")
    for result in report["results"]:
        mark = "OK  " if result["ok"] else "FAIL"
        print(f"{mark} {result['district']}: {result['per_m2']:,.0f}원/㎡ ({result['ratio']:.2f}×)")
    print(f"\n리포트: {REPORT_PATH}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 통과 확인**

Run: `cd pipeline/verify && ../../backend/.venv/bin/python -m pytest test_cross_check.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: 기준선 출처 스크립트 작성**

기준선 98,770원은 이미 실측된 값이지만, 출처를 재현할 수 있어야 한다.

`pipeline/verify/fetch_subway_rents.py`:

```python
"""Downloads Seoul Metro's underground shopping-arcade rental data (OA-12927) CSV and
computes the median monthly rent per m².

It's file data rather than an Open API, so it's fetched via a POST form request.
The encoding is EUC-KR. Run this only when cross_check.BASELINE_KRW_PER_M2 needs updating.
"""
from __future__ import annotations

import csv
import io
import statistics
from pathlib import Path

import httpx

URL = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do"
FORM = {"infId": "OA-12927", "seq": "14", "infSeq": "1"}
CACHE = Path(__file__).resolve().parents[1] / "raw" / "subway-rents.csv"


def download() -> str:
    response = httpx.post(URL, data=FORM, timeout=60.0)
    response.raise_for_status()
    text = response.content.decode("euc-kr", errors="replace")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(text, encoding="utf-8")
    return text


def median_per_m2(text: str) -> float:
    values = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            area = float(row["면적㎡"])
            rent = float(row["월임대료"])
        except (KeyError, TypeError, ValueError):
            continue
        if area > 0 and rent > 0:
            values.append(rent / area)
    if not values:
        raise SystemExit("월임대료와 면적이 모두 있는 행을 찾지 못했습니다. 컬럼명을 확인하세요.")
    return statistics.median(values)


if __name__ == "__main__":
    text = CACHE.read_text(encoding="utf-8") if CACHE.exists() else download()
    print(f"표본 기준 ㎡당 월임대료 중앙값: {median_per_m2(text):,.0f}원")
```

- [ ] **Step 6: 기준선 재현 확인**

Run: `backend/.venv/bin/python pipeline/verify/fetch_subway_rents.py`
Expected: `표본 기준 ㎡당 월임대료 중앙값: 98,770원` (± 반올림 오차)

값이 크게 다르면 `cross_check.BASELINE_KRW_PER_M2`와 `test_cross_check.py::test_baseline_is_the_measured_subway_median`을 새 값으로 갱신하고 그 사실을 커밋 메시지에 적는다.

- [ ] **Step 7: 게이트 실행**

Run: `npm run pipeline:verify`
Expected: 5개 구 모두 `OK`, 종료 코드 0, `data/rent-distribution.verification.md` 생성.

`FAIL`이 나오면 **Task 8로 넘어가지 않는다.** 리포트의 배수를 보고 Stage 1 가격 단위(만원↔원 변환)를 먼저 의심한다.

- [ ] **Step 8: 커밋**

```bash
git add pipeline/verify/ data/rent-distribution.verification.md
git commit -m "feat(pipeline): gate the rent distribution against public data"
```

---

## Task 8: Stage 3 매물 합성

설계 문서 §2.1의 두 번째 장치(1:1 대응 차단)가 여기서 구현된다. 좌표를 셔플하고 면적을 독립 샘플링하며, 좌표가 원본에서 갖고 있던 면적과 같은 값이 나오면 재샘플링한다.

**Files:**
- Create: `pipeline/synthesize/build-listings.mjs`
- Test: `pipeline/synthesize/build-listings.test.mjs`

- [ ] **Step 1: 실패하는 테스트 작성**

`pipeline/synthesize/build-listings.test.mjs`:

```js
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
```

- [ ] **Step 2: 실패 확인**

Run: `node --test pipeline/synthesize/build-listings.test.mjs`
Expected: FAIL — `Cannot find module ... build-listings.mjs`

- [ ] **Step 3: 구현**

`pipeline/synthesize/build-listings.mjs`:

```js
import { promises as fs } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { AREA_BANDS, LISTINGS_PER_DISTRICT, SYNTHESIS_SEED, TARGET_DISTRICTS, bandForArea } from "../lib/constants.mjs";
import { sampleFromQuantiles } from "../lib/quantile.mjs";
import { createRng, shuffle } from "../lib/rng.mjs";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const RAW_DIR = join(ROOT, "pipeline", "raw");
const DISTRIBUTION_PATH = join(ROOT, "data", "rent-distribution.seoul.json");
const OUTPUT = join(ROOT, "data", "listings.seoul.json");

const clamp = (value, low, high) => Math.min(Math.max(value, low), high);
const roundTo = (value, unit) => Math.round(value / unit) * unit;

/**
 * Rounds to a multiple of unit without letting the result fall outside [low, high].
 * Clamping then rounding could push the result past the upper bound, so the bounds
 * themselves are narrowed to unit first.
 * If the range is narrower than unit, it snaps to the lower bound (real rent bands are
 * in the millions of won, so this case doesn't come up).
 */
function roundWithin(value, unit, low, high) {
  const lowUnit = Math.ceil(low / unit) * unit;
  const highUnit = Math.floor(high / unit) * unit;
  if (lowUnit > highUnit) return lowUnit;
  return clamp(roundTo(value, unit), lowUnit, highUnit);
}

/**
 * Draws an area from the district's area distribution.
 * Redraws if the result equals forbidden (the area that coordinate originally had).
 * This is the 1:1 correspondence block from design doc §2.1.
 */
export function sampleArea(areaSet, rng, forbidden) {
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const drawn = Number(clamp(sampleFromQuantiles(areaSet, rng), areaSet.p10, areaSet.p90).toFixed(1));
    if (forbidden === null || drawn !== forbidden) return drawn;
  }
  // Extreme case where the distribution is collapsed to a single point. Nudge by the minimum unit to force the collision to break.
  const nudged = Number((clamp(forbidden + 0.1, areaSet.p10, areaSet.p90 + 0.1)).toFixed(1));
  return nudged === forbidden ? Number((forbidden + 0.1).toFixed(1)) : nudged;
}

/** Picks the band closest to the requested one among those actually present in the distribution. */
function resolveBand(bands, areaM2) {
  const preferred = bandForArea(areaM2).key;
  if (bands[preferred]) return bands[preferred];
  const order = AREA_BANDS.map((band) => band.key);
  const start = order.indexOf(preferred);
  for (let distance = 1; distance < order.length; distance += 1) {
    const lower = bands[order[start - distance]];
    if (lower) return lower;
    const higher = bands[order[start + distance]];
    if (higher) return higher;
  }
  throw new Error("사용 가능한 면적구간이 없습니다");
}

export function buildListings({ distribution, coordsByDistrict, perDistrict }) {
  const rng = createRng(SYNTHESIS_SEED);
  const listings = [];
  for (const district of Object.keys(coordsByDistrict)) {
    const profile = distribution.districts[district];
    if (!profile) throw new Error(`${district}의 분포가 없습니다`);
    const pool = shuffle(coordsByDistrict[district], rng).slice(0, perDistrict);
    pool.forEach((record, index) => {
      const areaM2 = sampleArea(profile.area, rng, record.area_m2);
      const band = resolveBand(profile.bands, areaM2);
      const rentRaw = sampleFromQuantiles(band.monthly_rent_krw, rng);
      const monthlyRent = roundWithin(rentRaw, 10_000, band.monthly_rent_krw.p10, band.monthly_rent_krw.p90);
      const multiple = sampleFromQuantiles(band.deposit_multiple, rng);
      const deposit = Math.max(roundTo(monthlyRent * multiple, 1_000_000), 1_000_000);
      listings.push({
        id: `demo-${district}-${String(index + 1).padStart(4, "0")}`,
        name: `${record.dong} ${record.floor}층 상가`,
        address: `서울 ${district} ${record.dong}`,
        district,
        latitude: record.lat,
        longitude: record.lng,
        _band_label: band.label,
        listing: {
          listing_kind: "DEMO_SYNTHETIC",
          deposit_krw: deposit,
          monthly_rent_krw: monthlyRent,
          maintenance_fee_krw: roundTo(monthlyRent * 0.08, 10_000),
          area_m2: areaM2,
          floor: record.floor,
        },
      });
    });
  }
  return listings;
}

async function readCoords() {
  const byDistrict = {};
  for (const district of TARGET_DISTRICTS) {
    const text = await fs.readFile(join(RAW_DIR, `coords.${district}.jsonl`), "utf8");
    byDistrict[district] = text.trim().split("\n").map((line) => JSON.parse(line));
  }
  return byDistrict;
}

async function main() {
  const distribution = JSON.parse(await fs.readFile(DISTRIBUTION_PATH, "utf8"));
  const listings = buildListings({
    distribution, coordsByDistrict: await readCoords(), perDistrict: LISTINGS_PER_DISTRICT,
  });
  const payload = {
    generated_at: new Date().toISOString(),
    seed: SYNTHESIS_SEED,
    listing_kind: "DEMO_SYNTHETIC",
    notice: "시연용 생성 데이터입니다. 실제 임대 매물이 아니며 계약 대상이 아닙니다.",
    method: "위치는 실제 상가 좌표이나 면적·보증금·월세는 시세 분포에서 독립 샘플링한 값입니다.",
    listings: listings.map(({ _band_label, ...rest }) => rest),
  };
  await fs.mkdir(dirname(OUTPUT), { recursive: true });
  await fs.writeFile(OUTPUT, JSON.stringify(payload, null, 2) + "\n");
  console.log(`매물 합성 완료: ${OUTPUT} (${listings.length}건)`);
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
```

- [ ] **Step 4: 통과 확인**

Run: `node --test pipeline/synthesize/build-listings.test.mjs`
Expected: PASS, 12 tests

- [ ] **Step 5: 실제 합성 실행**

Run: `node pipeline/synthesize/build-listings.mjs`
Expected: `매물 합성 완료: .../data/listings.seoul.json (275건)`

- [ ] **Step 6: 재현성 확인**

`generated_at`은 실행마다 바뀌므로 파일 전체 해시가 아니라 `listings` 배열만 비교한다.

```bash
node -e 'process.stdout.write(JSON.stringify(require("./data/listings.seoul.json").listings))' | shasum -a 256 > /tmp/listings-body-1
node pipeline/synthesize/build-listings.mjs
node -e 'process.stdout.write(JSON.stringify(require("./data/listings.seoul.json").listings))' | shasum -a 256 | diff - /tmp/listings-body-1 && echo "재현성 OK"
```

Expected: `재현성 OK`

다르면 합성 경로 어딘가에서 `Date.now()`나 시드 없는 `Math.random()`을 쓰고 있는 것이다.

- [ ] **Step 7: 커밋**

```bash
git add pipeline/synthesize/ data/listings.seoul.json
git commit -m "feat(pipeline): synthesize labelled demo listings from the rent distribution"
```

---

## Task 9: 전체 파이프라인 검증

**Files:**
- Modify: `pipeline/README.md`

- [ ] **Step 1: 전체 테스트 실행**

Run: `npm run test:pipeline`
Expected: PASS — quantile 13 + rng 7 + raw-record 7 + distribution 6 + synthesize 12 = 45 tests

- [ ] **Step 2: 파이썬 테스트 실행**

Run: `cd pipeline/verify && ../../backend/.venv/bin/python -m pytest test_cross_check.py -v`
Expected: PASS, 7 tests

- [ ] **Step 3: 기존 게이트가 안 깨졌는지 확인**

Run: `npm run lint && npm run typecheck && npm run api:check && npm run api:test`
Expected: 모두 통과. 파이프라인은 `app/`·`backend/app/`을 건드리지 않았으므로 변화가 없어야 한다.

- [ ] **Step 4: 산출물 육안 검증**

Run:

```bash
node -e '
const data = require("./data/listings.seoul.json");
const byDistrict = {};
for (const listing of data.listings) {
  const bucket = byDistrict[listing.district] ??= { count: 0, rents: [] };
  bucket.count += 1;
  bucket.rents.push(listing.listing.monthly_rent_krw);
}
for (const [district, bucket] of Object.entries(byDistrict)) {
  bucket.rents.sort((a, b) => a - b);
  const median = bucket.rents[Math.floor(bucket.rents.length / 2)];
  console.log(district, bucket.count + "건", "월세 중앙값", median.toLocaleString() + "원");
}
console.log("라벨 누락:", data.listings.filter((l) => l.listing.listing_kind !== "DEMO_SYNTHETIC").length);
'
```

Expected: 5개 구 각 55건, 월세 중앙값이 구별로 200만~600만원대, 라벨 누락 0.

중앙값이 상식 밖이면 Stage 1의 단위 변환을 다시 본다.

- [ ] **Step 5: README에 실행 결과 기록**

`pipeline/README.md` 끝에 추가:

```markdown
## 실행 이력

- 2026-07-27 Stage 0 수집 완료. 재실행하지 않는다.
- 산출물: `data/rent-distribution.seoul.json`, `data/rent-distribution.verification.md`, `data/listings.seoul.json`
```

- [ ] **Step 6: 커밋**

```bash
git add pipeline/README.md
git commit -m "docs(pipeline): record the one-shot collection run"
```

---

## 완료 조건

- `data/listings.seoul.json`에 5개 구 × 55건 = 275건이 있고 모든 행에 `listing_kind: "DEMO_SYNTHETIC"`이 있다
- `npm run pipeline:verify`가 종료 코드 0으로 통과한다
- `npm run test:pipeline`이 45개 테스트를 통과한다
- `pipeline/raw/`가 git에 올라가지 않았다
- 어떤 결과 행도 좌표가 원본에서 갖고 있던 면적을 그대로 쓰지 않는다 (테스트로 고정)

## 다음 단계

Stage 4(Supabase 적재)와 백엔드·프론트엔드 연동은 별도 계획으로 작성한다. 설계 문서 §4~§6이 그 범위다.
