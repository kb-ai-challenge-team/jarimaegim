import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import {
  SafeUpdateError,
  buildUpdatedContents,
  keyFromEnvironment,
  updateEnvironmentFile,
  validateKey,
} from "./update-kakao-map-key.mjs";

const FIXTURE_KEY = "fixtureKakaoJsKey123";
const SCRIPT_PATH = fileURLToPath(new URL("./update-kakao-map-key.mjs", import.meta.url));
const SOURCE = [
  "SUPABASE_JWT_SECRET=fixture-supabase-secret",
  "SES_FROM_EMAIL=fixture@example.test",
  "FINLIFE_API_URL=https://fixture.example.test/api",
  "NEXT_PUBLIC_KAKAO_MAP_JS_KEY=oldFixtureKey",
  "UNCHANGED_SETTING=preserve-me",
  "",
].join("\n");

function assertCode(callback, code) {
  assert.throws(callback, error => error instanceof SafeUpdateError && error.code === code);
}

function cleanEnvironment(overrides = {}) {
  const environment = { ...process.env, ...overrides };
  delete environment.KAKAO_MAP_JS_KEY;
  delete environment.NEXT_PUBLIC_KAKAO_MAP_JS_KEY;
  return { ...environment, ...overrides };
}

test("replaces only the exact assignment and preserves unrelated bytes", () => {
  const updated = buildUpdatedContents(SOURCE, FIXTURE_KEY);
  const expected = SOURCE.replace("oldFixtureKey", FIXTURE_KEY);
  assert.equal(updated, expected);
  assert.equal(updated.replace(FIXTURE_KEY, "oldFixtureKey"), SOURCE);
});

test("rejects URL-shaped, missing, ambiguous, and duplicate input", () => {
  assertCode(() => validateKey("https://fixture.example.test/key"), "invalid_url");
  assertCode(() => validateKey(undefined), "missing_input");
  assertCode(
    () => keyFromEnvironment({ KAKAO_MAP_JS_KEY: "one", NEXT_PUBLIC_KAKAO_MAP_JS_KEY: "two" }),
    "ambiguous_input",
  );
  assertCode(() => buildUpdatedContents(`${SOURCE}NEXT_PUBLIC_KAKAO_MAP_JS_KEY=again\n`, FIXTURE_KEY), "duplicate_assignment");
});
test("updates atomically while preserving permissions", async t => {
  const directory = await fs.mkdtemp(join(tmpdir(), "kakao-map-key-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const filePath = join(directory, ".env");
  await fs.writeFile(filePath, SOURCE, { mode: 0o640 });

  const result = await updateEnvironmentFile(filePath, FIXTURE_KEY);

  assert.deepEqual(result, {
    updated: true,
    assignmentCount: 1,
    validShape: true,
    protectedSettingsUnchanged: true,
    permissionsPreserved: true,
  });
  assert.equal(await fs.readFile(filePath, "utf8"), SOURCE.replace("oldFixtureKey", FIXTURE_KEY));
  assert.equal((await fs.stat(filePath)).mode & 0o777, 0o640);
});

test("CLI output is redacted for successful and rejected values", async t => {
  const directory = await fs.mkdtemp(join(tmpdir(), "kakao-map-cli-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const filePath = join(directory, ".env");
  await fs.writeFile(filePath, SOURCE);

  const success = spawnSync(process.execPath, [SCRIPT_PATH, "--file", filePath], {
    encoding: "utf8",
    env: cleanEnvironment({ KAKAO_MAP_JS_KEY: FIXTURE_KEY }),
  });
  assert.equal(success.status, 0);
  assert.deepEqual(JSON.parse(success.stdout), {
    updated: true,
    assignmentCount: 1,
    validShape: true,
    protectedSettingsUnchanged: true,
    permissionsPreserved: true,
  });
  assert.doesNotMatch(`${success.stdout}${success.stderr}`, new RegExp(FIXTURE_KEY, "u"));

  const rejectedValue = "https://fixture.example.test/not-a-key";
  const failure = spawnSync(process.execPath, [SCRIPT_PATH, "--file", filePath], {
    encoding: "utf8",
    env: cleanEnvironment({ KAKAO_MAP_JS_KEY: rejectedValue }),
  });
  assert.equal(failure.status, 1);
  assert.match(failure.stderr, /must not be an HTTP or HTTPS URL/u);
  assert.doesNotMatch(`${failure.stdout}${failure.stderr}`, new RegExp(rejectedValue, "u"));
});

test("CLI reports missing non-interactive input without leaking environment values", () => {
  const result = spawnSync(process.execPath, [SCRIPT_PATH], {
    encoding: "utf8",
    env: cleanEnvironment(),
  });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /input is missing/u);
  assert.doesNotMatch(result.stderr, /KAKAO_MAP_JS_KEY=/u);
});