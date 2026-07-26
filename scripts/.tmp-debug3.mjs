import { chromium } from "playwright-core";
const base = "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
page.on("pageerror", e => console.log("pageerror:", e.message.slice(0,400)));
page.on("request", r => { if (r.url().includes("/api/v1")) console.log("req:", r.method(), r.url().replace(base,"")); });
page.on("response", async r => { if (r.url().includes("/api/v1")) console.log("res:", r.status(), r.url().replace(base,"")); });
await context.request.post(base + "/api/v1/sessions/anonymous", { data: { retention_notice_accepted: true } });
const created = await context.request.post(base + "/api/v1/cases", { data: { title: "t", inputs: { industry: "카페", district: "마포구", budget_krw: 100000000, equity_krw: 70000000, business_stage: "PRE_OPEN", startup_type: "INDEPENDENT", priority: "STABILITY" } } });
const record = await created.json();
await page.goto(`${base}/cases/${record.id}/explore`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(8000);
const probe = await page.evaluate(async () => {
  const reactRoot = Boolean(document.querySelector("main")?.__reactFiber$ || Object.keys(document.querySelector("main")||{}).some(k=>k.startsWith("__react")));
  let fetchStatus = "n/a";
  try { const r = await fetch("/api/v1/status", { credentials: "include" }); fetchStatus = r.status; } catch (e) { fetchStatus = "err:" + e.message; }
  return { reactRoot, fetchStatus, html: document.querySelector("main")?.className };
});
console.log("probe", JSON.stringify(probe));
await browser.close();
