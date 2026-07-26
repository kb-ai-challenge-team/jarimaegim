import { chromium } from "playwright-core";
const base = "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
page.on("console", m => console.log("[c]", m.type(), m.text().slice(0,300)));
page.on("pageerror", e => console.log("[E]", e.stack?.slice(0,800) || e.message));
await page.goto(`${base}/privacy`, { waitUntil: "load" });
await page.waitForTimeout(4000);
const info = await page.evaluate(() => ({
  scripts: document.querySelectorAll("script[src]").length,
  hasNextF: Array.isArray(window.__next_f),
  nextFLen: window.__next_f?.length ?? null,
  devtools: Boolean(document.querySelector("nextjs-portal")),
  reactKeys: Object.keys(document.querySelector("main") || {}).filter(k => k.startsWith("__react")),
  buttonCount: document.querySelectorAll("button").length
}));
console.log("INFO", JSON.stringify(info));
await browser.close();
