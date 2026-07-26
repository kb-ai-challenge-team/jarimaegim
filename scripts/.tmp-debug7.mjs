import { chromium } from "playwright-core";
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN });
const page = await (await browser.newContext()).newPage();
await page.goto("http://127.0.0.1:4173/privacy", { waitUntil: "load" });
await page.waitForTimeout(3000);
console.log(JSON.stringify(await page.evaluate(() => {
  const inline = [...document.querySelectorAll("script:not([src])")];
  return {
    inlineCount: inline.length,
    inlineParents: inline.map(s => s.parentElement?.tagName),
    inlineHeads: inline.map(s => s.textContent.slice(0, 60)),
    nextFType: typeof window.__next_f,
    nextFLen: window.__next_f?.length,
    bodyChildren: [...document.body.children].map(e => e.tagName + "." + (e.className||"").slice(0,20))
  };
})));
await browser.close();
