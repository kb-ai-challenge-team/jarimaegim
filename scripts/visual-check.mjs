import { chromium } from "playwright-core";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:4173";
const out = new URL("../artifacts/visual/", import.meta.url);
const outputPath = (name) => fileURLToPath(new URL(name, out));
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const viewports = [{ name: "mobile-320", width: 320, height: 568 }, { name: "mobile-390", width: 390, height: 844 }, { name: "tablet", width: 768, height: 1024 }, { name: "desktop-1280", width: 1280, height: 720 }, { name: "desktop-1440", width: 1440, height: 900 }];
const publicRoutes = ["/", "/kb", "/cases/new?mode=first", "/auth", "/privacy"];
const results = [];
for (const viewport of viewports) {
  const context = await browser.newContext({ viewport });
  const consoleErrors = [];
  const pageErrors = [];
  const page = await context.newPage();
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", error => pageErrors.push(error.message));
  for (const route of publicRoutes) {
    await page.goto(base + route, { waitUntil: "networkidle" });
    const geometry = await page.evaluate(() => ({
      title: document.title,
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      h1: document.querySelector("h1")?.textContent?.trim() || "",
      main: Boolean(document.querySelector("main")),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
    }));
    const slug = route === "/" ? "landing" : route.split("?")[0].replaceAll("/", "-").replace(/^-/, "");
    await page.screenshot({ path: outputPath(`${viewport.name}-${slug}.png`), fullPage: true });
    results.push({ viewport: viewport.name, route, ...geometry });
  }
  await context.request.post(base + "/api/v1/sessions/anonymous", { data: { retention_notice_accepted: true } });
  const created = await context.request.post(base + "/api/v1/cases", { data: { title: "마포구 카페 처음 창업", inputs: { industry: "카페", district: "마포구", budget_krw: 100000000, equity_krw: 70000000, business_stage: "PRE_OPEN", startup_type: "INDEPENDENT", priority: "STABILITY" } } });
  const record = await created.json();
  await page.goto(`${base}/cases/${record.id}/explore`, { waitUntil: "networkidle" });
  await page.waitForSelector(".service-shell");
  const workspaceGeometry = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    shellHeight: document.querySelector(".service-shell")?.getBoundingClientRect().height || 0,
    viewportHeight: window.innerHeight,
    emptyStateVisible: Boolean(document.querySelector(".empty-state")),
    mobileSwitcherVisible: getComputedStyle(document.querySelector(".mobile-switcher")).display !== "none"
  }));
  await page.screenshot({ path: outputPath(`${viewport.name}-workspace.png`), fullPage: true });
  results.push({ viewport: viewport.name, route: "/cases/:id/explore", ...workspaceGeometry, consoleErrors: [...consoleErrors], pageErrors: [...pageErrors] });
  await context.close();
}
await browser.close();
await writeFile(new URL("report.json", out), JSON.stringify(results, null, 2));
const failures = results.filter(item => item.horizontalOverflow || item.main === false || item.consoleErrors?.length || item.pageErrors?.length || (item.route.includes(":id") && Math.abs(item.shellHeight - item.viewportHeight) > 2));
console.log(JSON.stringify({ checked: results.length, failures, report: outputPath("report.json") }, null, 2));
process.exitCode = failures.length ? 1 : 0;
