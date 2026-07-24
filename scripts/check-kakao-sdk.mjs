import { constants as fsConstants, promises as fs } from "node:fs";
import { extname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright-core";

export const ALLOWED_ORIGINS = Object.freeze([
  "http://127.0.0.1:4173",
  "http://jarimaegim.duckdns.org",
  "https://jarimaegim.duckdns.org",
]);

const INPUT_ENV_NAMES = Object.freeze([
  "KAKAO_MAP_JS_KEY",
  "NEXT_PUBLIC_KAKAO_MAP_JS_KEY",
]);
const SDK_ENDPOINT = Object.freeze({
  protocol: "https:",
  hostname: "dapi.kakao.com",
  pathname: "/v2/maps/sdk.js",
});
const ASSET_EXTENSIONS = new Set([".css", ".js", ".json", ".map", ".txt"]);
const SAFE_CATEGORIES = new Set([
  "build_mismatch",
  "build_unavailable",
  "invalid_input",
  "invalid_origin",
  "network",
  "sdk_init",
  "unauthorized_origin",
  "usage",
]);

class SafeCheckError extends Error {
  constructor(category) {
    super(category);
    this.name = "SafeCheckError";
    this.category = SAFE_CATEGORIES.has(category) ? category : "invalid_input";
  }
}

export function sanitizeText(value, secrets = []) {
  let sanitized = String(value ?? "");
  for (const secret of secrets) {
    if (typeof secret === "string" && secret.length > 0) sanitized = sanitized.replaceAll(secret, "[redacted]");
  }
  return sanitized
    .replace(/\?[^\s"'`}>]*/gu, "")
    .replace(/\b(?:KAKAO_MAP_JS_KEY|NEXT_PUBLIC_KAKAO_MAP_JS_KEY)\s*=\s*[^\s,;]*/giu, "[redacted]")
    .replace(/\b[0-9a-f]{64}\b/giu, "[redacted]");
}
export function validateKey(value) {
  if (typeof value !== "string" || value.length === 0) throw new SafeCheckError("invalid_input");
  if (value !== value.trim() || /^https?:\/\//iu.test(value) || /[\s\u0000\u007f"'#$\\]/u.test(value)) {
    throw new SafeCheckError("invalid_input");
  }
  return value;
}

export function keyFromEnvironment(environment = process.env) {
  const values = INPUT_ENV_NAMES
    .filter(name => typeof environment[name] === "string" && environment[name].length > 0)
    .map(name => environment[name]);
  if (values.length !== 1) throw new SafeCheckError("invalid_input");
  return validateKey(values[0]);
}

export function validateOrigin(value) {
  if (typeof value !== "string" || value.length === 0) throw new SafeCheckError("invalid_origin");
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new SafeCheckError("invalid_origin");
  }
  const isBareOrigin = parsed.username === ""
    && parsed.password === ""
    && parsed.pathname === "/"
    && parsed.search === ""
    && parsed.hash === "";
  if (!isBareOrigin || !ALLOWED_ORIGINS.includes(parsed.origin)) {
    throw new SafeCheckError("invalid_origin");
  }
  return parsed.origin;
}

function isSdkUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === SDK_ENDPOINT.protocol
      && parsed.hostname === SDK_ENDPOINT.hostname
      && parsed.pathname === SDK_ENDPOINT.pathname;
  } catch {
    return false;
  }
}

async function findBrowserExecutable(environment = process.env) {
  const configured = environment.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH;
  if (typeof configured === "string" && configured.length > 0) return configured;

  const candidates = process.platform === "darwin"
    ? ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    : process.platform === "win32"
      ? [
          join(environment.PROGRAMFILES ?? "", "Google/Chrome/Application/chrome.exe"),
          join(environment["PROGRAMFILES(X86)"] ?? "", "Google/Chrome/Application/chrome.exe"),
        ]
      : ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"];
  for (const candidate of candidates) {
    if (!candidate) continue;
    try {
      await fs.access(candidate, fsConstants.X_OK);
      return candidate;
    } catch {
      // Continue without exposing candidate paths.
    }
  }
  return undefined;
}
async function launchBrowser({ environment, executablePath } = {}) {
  const selectedExecutable = executablePath ?? await findBrowserExecutable(environment);
  const options = { headless: true };
  if (selectedExecutable) options.executablePath = selectedExecutable;
  return chromium.launch(options);
}

async function indicatesUnauthorized(response) {
  if (!response) return false;
  if (response.status() === 401 || response.status() === 403) return true;
  if (!response.ok()) return false;
  try {
    const body = await response.text();
    return /(?:unauthorized|forbidden|unregistered|not[ -]?registered|invalid).{0,80}(?:domain|origin|site)/iu.test(body)
      || /(?:domain|origin|site).{0,80}(?:unauthorized|forbidden|unregistered|not[ -]?registered|invalid)/iu.test(body);
  } catch {
    return false;
  }
}

export async function runSdkCheck({
  origin,
  key,
  environment = process.env,
  executablePath,
  timeoutMs = 15_000,
} = {}) {
  const allowedOrigin = validateOrigin(origin);
  const approvedKey = validateKey(key ?? keyFromEnvironment(environment));
  const result = { origin: allowedOrigin, sdkResponseOk: false, namespaceReady: false };
  let browser;
  let sdkResponse;
  let sdkRequestFailed = false;

  try {
    browser = await launchBrowser({ environment, executablePath });
    const context = await browser.newContext();
    const page = await context.newPage();
    page.setDefaultTimeout(timeoutMs);
    await page.goto(allowedOrigin, { waitUntil: "domcontentloaded", timeout: timeoutMs });

    page.on("response", response => {
      if (isSdkUrl(response.url())) sdkResponse = response;
    });
    page.on("requestfailed", request => {
      if (isSdkUrl(request.url())) sdkRequestFailed = true;
    });

    result.namespaceReady = await page.evaluate(
      ({ sdkKey, timeout }) => new Promise((resolveNamespace) => {
        let settled = false;
        const timer = window.setTimeout(() => finish(false), timeout);
        const finish = (ready) => {
          if (settled) return;
          settled = true;
          window.clearTimeout(timer);
          resolveNamespace(Boolean(ready));
        };
        const script = document.createElement("script");
        const sdkUrl = new URL("https://dapi.kakao.com/v2/maps/sdk.js");
        sdkUrl.searchParams.set("appkey", sdkKey);
        sdkUrl.searchParams.set("autoload", "false");
        script.src = sdkUrl.href;
        script.async = true;
        script.onerror = () => finish(false);
        script.onload = () => {
          if (!window.kakao?.maps?.load) return finish(false);
          window.kakao.maps.load(() => finish(Boolean(window.kakao?.maps)));
        };
        document.head.appendChild(script);
      }),
      { sdkKey: approvedKey, timeout: timeoutMs },
    );
    result.sdkResponseOk = Boolean(sdkResponse?.ok());

    if (!result.sdkResponseOk || !result.namespaceReady) {
      result.failureCategory = await indicatesUnauthorized(sdkResponse)
        ? "unauthorized_origin"
        : result.sdkResponseOk && !sdkRequestFailed
          ? "sdk_init"
          : "network";
    }
    return result;
  } catch {
    return { ...result, failureCategory: "network" };
  } finally {
    await browser?.close().catch(() => {});
  }
}
async function assetFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...await assetFiles(path));
    else if (entry.isFile() && ASSET_EXTENSIONS.has(extname(entry.name).toLowerCase())) files.push(path);
  }
  return files;
}

export async function checkBuildAssets({
  key,
  environment = process.env,
  assetsDirectory = resolve(".next/static"),
} = {}) {
  const approvedKey = validateKey(key ?? keyFromEnvironment(environment));
  const needle = Buffer.from(approvedKey, "utf8");
  try {
    for (const file of await assetFiles(resolve(assetsDirectory))) {
      if ((await fs.readFile(file)).includes(needle)) return true;
    }
    return false;
  } catch {
    throw new SafeCheckError("build_unavailable");
  }
}

function parseArguments(argumentsList) {
  const [command, ...options] = argumentsList;
  if (command !== "sdk" && command !== "assets") throw new SafeCheckError("usage");
  let origin;
  let assetsDirectory;
  for (let index = 0; index < options.length; index += 2) {
    const flag = options[index];
    const value = options[index + 1];
    if (!value) throw new SafeCheckError("usage");
    if (command === "sdk" && flag === "--origin") origin = value;
    else if (command === "assets" && flag === "--dir") assetsDirectory = resolve(value);
    else throw new SafeCheckError("usage");
  }
  if (command === "sdk" && !origin) throw new SafeCheckError("usage");
  return { command, origin, assetsDirectory };
}

function writeResult(result, output = process.stdout) {
  output.write(`${JSON.stringify(result)}\n`);
}

export async function main({
  argumentsList = process.argv.slice(2),
  environment = process.env,
  key,
  output = process.stdout,
} = {}) {
  try {
    const request = parseArguments(argumentsList);
    if (request.command === "sdk") {
      const result = await runSdkCheck({ origin: request.origin, key, environment });
      writeResult(result, output);
      if (!result.sdkResponseOk || !result.namespaceReady) process.exitCode = 1;
      return result;
    }

    const embeddedKeyPresent = await checkBuildAssets({
      key,
      environment,
      assetsDirectory: request.assetsDirectory,
    });
    const result = embeddedKeyPresent
      ? { embeddedKeyPresent: true }
      : { embeddedKeyPresent: false, failureCategory: "build_mismatch" };
    writeResult(result, output);
    if (!embeddedKeyPresent) process.exitCode = 1;
    return result;
  } catch (error) {
    const failureCategory = error instanceof SafeCheckError ? error.category : "invalid_input";
    const result = { failureCategory };
    writeResult(result, output);
    process.exitCode = 1;
    return result;
  }
}

const isDirectExecution = process.argv[1]
  && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isDirectExecution) await main();
