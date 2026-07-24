import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { promises as fs } from "node:fs";
import { emitKeypressEvents } from "node:readline";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const TARGET_KEY = "NEXT_PUBLIC_KAKAO_MAP_JS_KEY";
export const INPUT_ENV_NAMES = Object.freeze([
  "KAKAO_MAP_JS_KEY",
  TARGET_KEY,
]);
export const PROTECTED_SETTINGS = Object.freeze([
  "SUPABASE_JWT_SECRET",
  "SES_FROM_EMAIL",
  "FINLIFE_API_URL",
]);

const SAFE_MESSAGES = Object.freeze({
  ambiguous_assignment: "Update stopped: the map-key assignment is ambiguous.",
  ambiguous_input: "Update stopped: JavaScript key input is ambiguous.",
  duplicate_assignment: "Update stopped: duplicate map-key assignments were found.",
  file_access: "Update stopped: the environment file could not be safely accessed.",
  invalid_input: "Update stopped: JavaScript key input has an ambiguous shape.",
  invalid_url: "Update stopped: JavaScript key input must not be an HTTP or HTTPS URL.",
  missing_assignment: "Update stopped: the map-key assignment is missing.",
  missing_input: "Update stopped: JavaScript key input is missing.",
  protected_mismatch: "Update stopped: protected settings did not pass verification.",
  restore_failed: "Update stopped: verification failed and the original file could not be restored.",
  usage: "Usage: node scripts/update-kakao-map-key.mjs [--file <environment-file>]",
  verification_failed: "Update stopped: the environment update did not pass verification.",
});

export class SafeUpdateError extends Error {
  constructor(code) {
    super(SAFE_MESSAGES[code] ?? SAFE_MESSAGES.file_access);
    this.name = "SafeUpdateError";
    this.code = code;
  }
}
export function validateKey(value) {
  if (typeof value !== "string" || value.length === 0) {
    throw new SafeUpdateError("missing_input");
  }
  if (/^https?:\/\//iu.test(value.trim())) {
    throw new SafeUpdateError("invalid_url");
  }
  if (value !== value.trim() || /[\s\u0000\u007f"'#$\\]/u.test(value)) {
    throw new SafeUpdateError("invalid_input");
  }
  return true;
}

export function keyFromEnvironment(environment = process.env) {
  const sources = INPUT_ENV_NAMES.filter(
    name => typeof environment[name] === "string" && environment[name].length > 0,
  );
  if (sources.length > 1) throw new SafeUpdateError("ambiguous_input");
  return sources.length === 1 ? environment[sources[0]] : undefined;
}

function linesWithOffsets(text) {
  const lines = [];
  const pattern = /[^\r\n]*(?:\r\n|\r|\n|$)/gu;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match[0].length === 0) break;
    const body = match[0].replace(/(?:\r\n|\r|\n)$/u, "");
    lines.push({ raw: match[0], body, start: match.index });
  }
  return lines;
}

function locateAssignment(text) {
  const candidatePattern = /^\uFEFF?[ \t]*(?:export[ \t]+)?NEXT_PUBLIC_KAKAO_MAP_JS_KEY(?=[ \t=]|$)/u;
  const assignmentPattern = /^(\uFEFF?[ \t]*(?:export[ \t]+)?NEXT_PUBLIC_KAKAO_MAP_JS_KEY[ \t]*=[ \t]*)([^\r\n]*)$/u;
  const assignments = [];

  for (const line of linesWithOffsets(text)) {
    if (!candidatePattern.test(line.body)) continue;
    const match = assignmentPattern.exec(line.body);
    if (!match) throw new SafeUpdateError("ambiguous_assignment");
    assignments.push({
      valueStart: line.start + match[1].length,
      valueEnd: line.start + line.body.length,
    });
  }

  if (assignments.length === 0) throw new SafeUpdateError("missing_assignment");
  if (assignments.length > 1) throw new SafeUpdateError("duplicate_assignment");
  return assignments[0];
}
function protectedFingerprints(text) {
  const fingerprints = new Map(PROTECTED_SETTINGS.map(name => [name, []]));
  const protectedPattern = /^\uFEFF?[ \t]*(?:export[ \t]+)?(SUPABASE_JWT_SECRET|SES_FROM_EMAIL|FINLIFE_API_URL)[ \t]*=/u;

  for (const line of linesWithOffsets(text)) {
    const match = protectedPattern.exec(line.body);
    if (!match) continue;
    fingerprints.get(match[1]).push(createHash("sha256").update(line.raw, "utf8").digest());
  }
  return fingerprints;
}

function fingerprintsMatch(left, right) {
  return PROTECTED_SETTINGS.every(name => {
    const leftValues = left.get(name);
    const rightValues = right.get(name);
    return leftValues.length === rightValues.length
      && leftValues.every((value, index) => timingSafeEqual(value, rightValues[index]));
  });
}

export function buildUpdatedContents(source, key) {
  validateKey(key);
  const assignment = locateAssignment(source);
  const before = protectedFingerprints(source);
  const updated = `${source.slice(0, assignment.valueStart)}${key}${source.slice(assignment.valueEnd)}`;
  const after = protectedFingerprints(updated);
  if (!fingerprintsMatch(before, after)) throw new SafeUpdateError("protected_mismatch");

  const updatedAssignment = locateAssignment(updated);
  if (updated.slice(updatedAssignment.valueStart, updatedAssignment.valueEnd) !== key) {
    throw new SafeUpdateError("verification_failed");
  }
  return updated;
}

async function atomicReplace(filePath, contents, mode) {
  const temporaryPath = join(
    dirname(filePath),
    `.${basename(filePath)}.${process.pid}.${randomBytes(12).toString("hex")}.tmp`,
  );
  let handle;
  try {
    handle = await fs.open(temporaryPath, "wx", mode);
    await handle.chmod(mode);
    await handle.writeFile(contents);
    await handle.sync();
    await handle.close();
    handle = undefined;
    await fs.rename(temporaryPath, filePath);
  } finally {
    if (handle) await handle.close().catch(() => {});
    await fs.unlink(temporaryPath).catch(() => {});
  }
}
function decodeUtf8Exactly(contents) {
  const text = contents.toString("utf8");
  if (!Buffer.from(text, "utf8").equals(contents)) throw new SafeUpdateError("file_access");
  return text;
}

export async function updateEnvironmentFile(requestedPath, key) {
  validateKey(key);
  let filePath;
  let original;
  let fileStat;
  try {
    filePath = await fs.realpath(requestedPath);
    fileStat = await fs.stat(filePath);
    if (!fileStat.isFile()) throw new SafeUpdateError("file_access");
    original = await fs.readFile(filePath);
  } catch (error) {
    if (error instanceof SafeUpdateError) throw error;
    throw new SafeUpdateError("file_access");
  }

  const mode = fileStat.mode & 0o7777;
  const source = decodeUtf8Exactly(original);
  const beforeFingerprints = protectedFingerprints(source);
  const updatedText = buildUpdatedContents(source, key);
  const updated = Buffer.from(updatedText, "utf8");

  try {
    await atomicReplace(filePath, updated, mode);
    const [written, writtenStat] = await Promise.all([fs.readFile(filePath), fs.stat(filePath)]);
    const writtenText = decodeUtf8Exactly(written);
    const protectedSettingsUnchanged = fingerprintsMatch(
      beforeFingerprints,
      protectedFingerprints(writtenText),
    );
    const permissionsPreserved = (writtenStat.mode & 0o7777) === mode;
    const assignment = locateAssignment(writtenText);
    const assignmentValid = writtenText.slice(assignment.valueStart, assignment.valueEnd) === key;

    if (!written.equals(updated) || !protectedSettingsUnchanged || !permissionsPreserved || !assignmentValid) {
      throw new SafeUpdateError(
        protectedSettingsUnchanged ? "verification_failed" : "protected_mismatch",
      );
    }
    return {
      updated: true,
      assignmentCount: 1,
      validShape: true,
      protectedSettingsUnchanged: true,
      permissionsPreserved: true,
    };
  } catch (error) {
    try {
      await atomicReplace(filePath, original, mode);
    } catch {
      throw new SafeUpdateError("restore_failed");
    }
    if (error instanceof SafeUpdateError) throw error;
    throw new SafeUpdateError("file_access");
  }
}
export async function readKeyWithoutEcho({ input = process.stdin, output = process.stderr } = {}) {
  if (!input.isTTY || typeof input.setRawMode !== "function") {
    throw new SafeUpdateError("missing_input");
  }

  output.write("Kakao Maps JavaScript key: ");
  emitKeypressEvents(input);
  const wasRaw = Boolean(input.isRaw);
  input.setRawMode(true);
  input.resume();

  return new Promise((resolveInput, rejectInput) => {
    let value = "";
    const cleanup = () => {
      input.off("keypress", onKeypress);
      input.off("end", onEnd);
      input.off("error", onError);
      input.setRawMode(wasRaw);
      input.pause();
      output.write("\n");
    };
    const finish = (error) => {
      cleanup();
      if (error) rejectInput(error);
      else resolveInput(value);
    };
    const onEnd = () => finish(new SafeUpdateError("missing_input"));
    const onError = () => finish(new SafeUpdateError("missing_input"));
    const onKeypress = (text, key = {}) => {
      if (key.ctrl && key.name === "c") return finish(new SafeUpdateError("missing_input"));
      if (key.name === "return" || key.name === "enter") return finish();
      if (key.name === "backspace" || key.name === "delete") {
        value = Array.from(value).slice(0, -1).join("");
        return undefined;
      }
      if (!key.ctrl && !key.meta && text && !/[\u0000-\u001f\u007f]/u.test(text)) {
        value += text;
      }
      return undefined;
    };

    input.on("keypress", onKeypress);
    input.once("end", onEnd);
    input.once("error", onError);
  });
}

function environmentPathFromArguments(argumentsList) {
  if (argumentsList.length === 0) return resolve(".env");
  if (argumentsList.length === 1 && !argumentsList[0].startsWith("-")) {
    return resolve(argumentsList[0]);
  }
  if (argumentsList.length === 2 && argumentsList[0] === "--file") {
    return resolve(argumentsList[1]);
  }
  throw new SafeUpdateError("usage");
}

export async function main({
  argumentsList = process.argv.slice(2),
  environment = process.env,
} = {}) {
  try {
    const environmentPath = environmentPathFromArguments(argumentsList);
    const environmentKey = keyFromEnvironment(environment);
    const key = environmentKey ?? await readKeyWithoutEcho();
    const result = await updateEnvironmentFile(environmentPath, key);
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    const safeError = error instanceof SafeUpdateError
      ? error
      : new SafeUpdateError("file_access");
    process.stderr.write(`${safeError.message}\n`);
    process.exitCode = 1;
  }
}

const isDirectExecution = process.argv[1]
  && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isDirectExecution) await main();
