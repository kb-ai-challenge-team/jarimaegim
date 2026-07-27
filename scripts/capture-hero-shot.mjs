// 랜딩 히어로에 들어가는 "실제 서비스 화면"을 만든다.
//
// 히어로 이미지는 손으로 그린 목업이 아니라 진짜 화면이어야 한다(부록 A 1 — 없는 것을
// 지어내지 않는다). 그래서 shell-check 와 같은 흐름을 실제로 끝까지 몰아서 입지 추천이
// 표시된 상태를 캡처한다. UI 가 바뀌면 이 스크립트를 다시 돌려 에셋을 갱신한다.
//
//   node scripts/capture-hero-shot.mjs
//
// 산출물: public/landing/service-screen.png (원본 · 2x)
// 압축은 scripts/optimize-hero-shot.py 가 이어받는다.
import { chromium } from "playwright-core";
import { mkdir } from "node:fs/promises";

const base = process.env.BASE_URL || "http://127.0.0.1:4173";
const out = "public/landing";
await mkdir(out, { recursive: true });

const browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });

await page.goto(`${base}/kb`, { waitUntil: "networkidle" });
await page.waitForSelector(".kb-ai-panel");
const panel = page.locator(".kb-ai-panel");

// 상황 → 조건
await panel.locator(".kb-examples button").first().click();
await panel.getByRole("button", { name: "조건으로 정리하기" }).click();
await panel.locator(".kb-form").waitFor();
const fields = panel.locator('.kb-form .kb-field input[type="number"]');
await fields.nth(2).fill("15");
await fields.nth(3).fill("100000000");
await fields.nth(4).fill("2500000");

// 조건 → 자금(밴드) → 입지
await panel.getByRole("button", { name: "이 조건으로 입지 찾기" }).click();
await panel.locator(".kb-band-form").waitFor({ timeout: 30000 });
await panel.locator(".kb-stepnav .kb-primary-sm").click();
await panel.locator(".kb-candidates, .kb-empty").first().waitFor({ timeout: 30000 });

const candidateCount = await panel.locator(".kb-candidates li").count();
if (candidateCount === 0) { await browser.close(); throw new Error("후보가 0건이라 히어로에 쓸 화면이 없습니다. 백엔드 데이터를 확인하세요."); }

// 지도가 후보로 다시 그려지고 타일이 붙을 때까지 기다린다.
await page.waitForLoadState("networkidle");
await new Promise(resolve => setTimeout(resolve, 3000));

// 후보 목록을 맨 위로 올린다. 스크롤이 걸린 채 찍히면 카드가 중간에서 잘린다.
await panel.locator(".kb-candidates").first().evaluate(node => {
  for (let el = node; el; el = el.parentElement) if (el.scrollHeight > el.clientHeight) el.scrollTop = 0;
});

// dev 오버레이는 제품이 아니다. 캡처에서만 숨긴다.
await page.addStyleTag({ content: "nextjs-portal,[data-nextjs-toast],[data-nextjs-dev-tools-button]{display:none!important}" });
await new Promise(resolve => setTimeout(resolve, 800));

await page.screenshot({ path: `${out}/service-screen.png` });
console.log(JSON.stringify({ candidateCount, viewport: "1440x900@2x", path: `${out}/service-screen.png` }, null, 2));
await browser.close();
