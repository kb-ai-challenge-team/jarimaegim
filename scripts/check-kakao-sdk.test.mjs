import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  checkBuildAssets,
  keyFromEnvironment,
  main,
  runSdkCheck,
  sanitizeText,
  validateKey,
  validateOrigin,
} from "./check-kakao-sdk.mjs";

const FIXTURE_KEY = "fixtureKakaoSdkKey456";

function captureOutput() {
  let value = "";
  return {
    output: { write(chunk) { value += String(chunk); } },
    read: () => value,
  };
}

async function withoutExitCode(callback) {
  const previous = process.exitCode;
  process.exitCode = undefined;
  try {
    return await callback();
  } finally {
    process.exitCode = previous;
  }
}

test("sanitizer removes secrets, query strings, assignments, and digests", () => {
  const digest = "a".repeat(64);
  const source = [
    `https://fixture.example.test/sdk.js?appkey=${FIXTURE_KEY}&autoload=false`,
    `NEXT_PUBLIC_KAKAO_MAP_JS_KEY=${FIXTURE_KEY}`,
    `KAKAO_MAP_JS_KEY=${FIXTURE_KEY}`,
    digest,
  ].join(" ");
  const sanitized = sanitizeText(source, [FIXTURE_KEY]);

  for (const forbidden of [FIXTURE_KEY, "?appkey=", "autoload=false", digest, "NEXT_PUBLIC_KAKAO_MAP_JS_KEY="]) {
    assert.equal(sanitized.includes(forbidden), false);
  }
  assert.match(sanitized, /\[redacted\]/u);
});

test("validates keys, environment cardinality, and bare allow-listed origins", async () => {
  assert.equal(validateKey(FIXTURE_KEY), FIXTURE_KEY);
  assert.equal(keyFromEnvironment({ KAKAO_MAP_JS_KEY: FIXTURE_KEY }), FIXTURE_KEY);
  assert.equal(validateOrigin("http://127.0.0.1:4173"), "http://127.0.0.1:4173");
  assert.throws(() => keyFromEnvironment({}), error => error.category === "invalid_input");
  assert.throws(
    () => keyFromEnvironment({ KAKAO_MAP_JS_KEY: "one", NEXT_PUBLIC_KAKAO_MAP_JS_KEY: "two" }),
    error => error.category === "invalid_input",
  );
  assert.throws(() => validateOrigin("http://127.0.0.1:4173/path?secret=value"), error => error.category === "invalid_origin");
  await assert.rejects(
    runSdkCheck({ origin: "https://not-allowed.example.test", key: FIXTURE_KEY }),
    error => error.category === "invalid_origin",
  );
});
test("asset checks return booleans without exposing the fixture key", async t => {
  const directory = await fs.mkdtemp(join(tmpdir(), "kakao-assets-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  await fs.writeFile(join(directory, "app.js"), `window.__fixture = "${FIXTURE_KEY}";`);
  await fs.writeFile(join(directory, "ignored.bin"), FIXTURE_KEY);

  assert.equal(await checkBuildAssets({ key: FIXTURE_KEY, assetsDirectory: directory }), true);
  assert.equal(await checkBuildAssets({ key: "differentFixtureKey", assetsDirectory: directory }), false);
});

test("normal and mismatch CLI result shapes contain only safe fields", async t => {
  const directory = await fs.mkdtemp(join(tmpdir(), "kakao-main-assets-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  await fs.writeFile(join(directory, "app.js"), FIXTURE_KEY);

  const successOutput = captureOutput();
  const success = await withoutExitCode(() => main({
    argumentsList: ["assets", "--dir", directory],
    key: FIXTURE_KEY,
    output: successOutput.output,
  }));
  assert.deepEqual(success, { embeddedKeyPresent: true });
  assert.deepEqual(JSON.parse(successOutput.read()), success);
  assert.equal(successOutput.read().includes(FIXTURE_KEY), false);

  const mismatchOutput = captureOutput();
  const mismatch = await withoutExitCode(() => main({
    argumentsList: ["assets", "--dir", directory],
    key: "missingFixtureKey",
    output: mismatchOutput.output,
  }));
  assert.deepEqual(mismatch, { embeddedKeyPresent: false, failureCategory: "build_mismatch" });
  assert.deepEqual(JSON.parse(mismatchOutput.read()), mismatch);
  assert.equal(mismatchOutput.read().includes("missingFixtureKey"), false);
});

test("error output is a sanitized category-only result", async () => {
  const output = captureOutput();
  const unsafeKey = "https://fixture.example.test/sdk.js?appkey=fixtureSecret";
  const result = await withoutExitCode(() => main({
    argumentsList: ["assets", "--dir", "unused?query=fixtureSecret"],
    key: unsafeKey,
    output: output.output,
  }));

  assert.deepEqual(result, { failureCategory: "invalid_input" });
  assert.deepEqual(JSON.parse(output.read()), result);
  for (const forbidden of [unsafeKey, "?", "fixtureSecret", "KAKAO_MAP_JS_KEY="]) {
    assert.equal(output.read().includes(forbidden), false);
  }
});