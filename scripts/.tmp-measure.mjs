import { chromium } from "playwright-core";

const base = "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_BIN });

const viewports = [
  { name: "desktop-1440x900", width: 1440, height: 900 },
  { name: "laptop-1440x780", width: 1440, height: 780 },
  { name: "laptop-1280x720", width: 1280, height: 720 },
  { name: "short-1280x640", width: 1280, height: 640 },
  { name: "mobile-390x844", width: 390, height: 844 }
];

const out = [];
for (const viewport of viewports) {
  const context = await browser.newContext({ viewport: { width: viewport.width, height: viewport.height } });
  const page = await context.newPage();
  await context.request.post(base + "/api/v1/sessions/anonymous", { data: { retention_notice_accepted: true } });
  const created = await context.request.post(base + "/api/v1/cases", {
    data: { title: "마포구 카페 처음 창업", inputs: { industry: "카페", district: "마포구", budget_krw: 100000000, equity_krw: 70000000, business_stage: "PRE_OPEN", startup_type: "INDEPENDENT", priority: "STABILITY" } }
  });
  const record = await created.json();
  await page.goto(`${base}/cases/${record.id}/explore`, { waitUntil: "networkidle" });
  await page.waitForSelector(".service-shell");
  await page.waitForTimeout(1500);

  const geometry = await page.evaluate(() => {
    const rect = (sel) => { const el = document.querySelector(sel); if (!el) return null; const r = el.getBoundingClientRect(); return { top: Math.round(r.top), bottom: Math.round(r.bottom), height: Math.round(r.height), width: Math.round(r.width) }; };
    const scroll = document.querySelector(".canvas-scroll");
    const preview = document.querySelector(".candidate-preview");
    const mapPane = document.querySelector(".map-pane");
    return {
      viewportH: window.innerHeight,
      canvasScroll: rect(".canvas-scroll"),
      canvasScrollScrollH: scroll ? scroll.scrollHeight : null,
      canvasScrollClientH: scroll ? scroll.clientHeight : null,
      exploreLayout: rect(".explore-layout"),
      mapPane: rect(".map-pane"),
      mapPaneOverflow: mapPane ? getComputedStyle(mapPane).overflow : null,
      compareTray: rect(".compare-tray"),
      compareTrayPos: document.querySelector(".compare-tray") ? getComputedStyle(document.querySelector(".compare-tray")).position : null,
      preview: rect(".candidate-preview"),
      previewActions: rect(".preview-actions"),
      previewVisible: preview && scroll ? (preview.getBoundingClientRect().bottom <= scroll.getBoundingClientRect().bottom + 0.5) : null,
      candidateCount: document.querySelectorAll(".candidate-row").length
    };
  });
  out.push({ viewport: viewport.name, ...geometry });
  await page.screenshot({ path: `/private/tmp/claude-501/-Users-jiwon-Desktop-KB-AI-Challenge/f0bd162d-d910-4612-a967-0734fb49f9db/scratchpad/${viewport.name}.png` });
  await context.close();
}
await browser.close();
console.log(JSON.stringify(out, null, 2));
