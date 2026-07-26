import { chromium } from "playwright-core";

const base = process.env.BASE_URL || "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(`page:${error.message}`));
page.on("console", message => {
  if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) errors.push(`console:${message.text()}`);
});
page.on("response", response => { if (response.status() >= 400 && response.url().includes("/api/v1/")) errors.push(`http:${response.status()}:${response.url()}`); });

const statusBody = await (await page.request.get(`${base}/api/v1/status`)).json();
const axes = { disabledCarryReason: Object.values(statusBody.axes).every(axis => axis.enabled || Boolean(axis.disabled_reason)) };
const subsidyConfigured = Boolean(statusBody.integrations.bizinfo || statusBody.integrations.kstartup);

await page.goto(base, { waitUntil: "networkidle" });
await page.waitForSelector(".kb-ai-panel");
const panel = page.locator(".kb-ai-panel");
const stepper = { labels: await panel.locator(".kb-stepper li").allTextContents() };

// 상황 — 예시 문장으로 조건을 채우고 확인 단계로
await panel.locator(".kb-examples button").first().click();
await panel.getByRole("button", { name: "조건으로 정리하기" }).click();
await panel.locator(".kb-form").waitFor();
const confirmLabels = await panel.locator(".kb-form .kb-field > span").allInnerTexts();
const lease = { fieldsPresent: ["희망 평수", "희망 보증금", "희망 월세"].every(label => confirmLabels.some(text => text.includes(label))) };

const fields = panel.locator('.kb-form .kb-field input[type="number"]');
await fields.nth(2).fill("15");         // 희망 평수
await fields.nth(3).fill("100000000");  // 희망 보증금
await fields.nth(4).fill("2500000");    // 희망 월세

const bandsResponsePromise = page.waitForResponse(r => r.url().includes("/api/v1/funding-bands") && r.request().method() === "POST");
await panel.getByRole("button", { name: "이 조건으로 입지 찾기" }).click();
const bandsResponse = await bandsResponsePromise;
const bandsBody = await bandsResponse.json();
const paramsRegistered = bandsBody.status === "computed";
const bands = {
  autoComputed: bandsResponse.ok(),
  paramsRegistered,
  // 파라미터가 없으면 추정하지 않고 누락 목록을 돌려줘야 한다. 있으면 3중선이 나와야 한다.
  safeState: paramsRegistered
    ? bandsBody.bands.length === 3 && bandsBody.break_even !== null
    : bandsBody.bands.length === 0 && bandsBody.missing_params.length > 0 && Boolean(bandsBody.message),
  // DS-09 미확보 — 밴드별 상권 수를 지어내지 않는다
  noInventedTradeAreaCount: bandsBody.bands.every(line => line.trade_area_count === null)
};

await panel.locator(".kb-candidates, .kb-empty").first().waitFor({ timeout: 30000 });
const location = { rendered: true };

// StepNav 의 다음 버튼을 밴드 화면이 나올 때까지 누른다 (입지 → 근거 → 비용)
for (let hop = 0; hop < 4; hop += 1) {
  if (await panel.locator(".kb-band-form").isVisible().catch(() => false)) break;
  const next = panel.locator(".kb-stepnav .kb-primary-sm");
  if (await next.count() === 0) throw new Error("StepNav 다음 버튼을 찾지 못했습니다.");
  await next.click();
  await page.waitForTimeout(500);
}
await panel.locator(".kb-band-form").waitFor({ timeout: 15000 });
const cost = {
  bandScreen: true,
  // 파라미터 미등록이면 누락 키가 화면에 보여야 한다 (부록 A 불변조건 1)
  pendingShown: paramsRegistered ? true : await panel.locator(".kb-missing-params li").count() > 0,
  bandTableShown: paramsRegistered ? await panel.locator(".kb-band-table").isVisible() : true
};

// 자금
const next = panel.locator(".kb-stepnav .kb-primary-sm");
if (await next.count() > 0) { await next.click(); }
await panel.locator(".kb-callout").first().waitFor({ timeout: 15000 });
await page.waitForTimeout(5000);
const programItems = await panel.locator(".kb-program-list li").all();
let withSource = 0;
for (const item of programItems) if (await item.locator('a[href^="http"]').count() > 0) withSource += 1;
const funding = {
  subsidyConfigured,
  programCount: programItems.length,
  // 공고가 있으면 모두 공식 원문 링크를 가져야 하고, 없으면 빈 상태가 보여야 한다
  safeState: programItems.length > 0
    ? withSource === programItems.length
    : await panel.getByText("표시할 수 있는 공식 공고가 없습니다").isVisible().catch(() => false),
  // 지원금이 밴드에 반영되지 않았음을 고지한다
  subsidyGapDisclosed: (await panel.locator(".kb-note").allInnerTexts()).some(text => text.includes("지원사업 endpoint 연동 후"))
};

const result = { stepper, lease, bands, location, cost, funding, axes, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
const expected = ["상황", "입지", "근거", "비용", "자금"];
const stepperOk = expected.every((label, index) => (stepper.labels[index] || "").includes(label));
if (errors.length || !stepperOk || !lease.fieldsPresent || !bands.autoComputed || !bands.safeState
  || !bands.noInventedTradeAreaCount || !location.rendered || !cost.bandScreen || !cost.pendingShown
  || !cost.bandTableShown || !funding.safeState || !funding.subsidyGapDisclosed
  || !axes.disabledCarryReason) process.exitCode = 1;
