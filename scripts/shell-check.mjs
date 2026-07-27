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

await page.goto(`${base}/kb`, { waitUntil: "networkidle" });
await page.waitForSelector(".kb-ai-panel");
const panel = page.locator(".kb-ai-panel");
const stepper = { labels: await panel.locator(".kb-stepper li").allTextContents() };

// 첫 진입 — 조건을 넣기 전에는 자치구 요약 핀만 떠 있어야 한다.
await page.waitForSelector(".kb-district-pin", { timeout: 30000 });
const overview = {
  pins: await page.locator(".kb-district-pin").count(),
  districts: await page.locator(".kb-district-pin strong").allInnerTexts(),
  markersBefore: await page.locator(".kb-marker").count(),
};

await page.locator(".kb-district-pin").first().click();
await page.waitForSelector(".kb-marker", { timeout: 30000 });
const drilldown = {
  markers: await page.locator(".kb-marker").count(),
  badges: await page.locator(".kb-marker-demo").count(),
  pinsGone: (await page.locator(".kb-district-pin").count()) === 0,
};
await page.getByRole("button", { name: "전체 자치구 보기" }).click();
await page.waitForSelector(".kb-district-pin", { timeout: 30000 });
const returned = { pins: await page.locator(".kb-district-pin").count() };

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

// 조건 확정 직후 착지하는 단계는 자금(밴드)이다. 금융이 입지보다 먼저 온다.
await panel.locator(".kb-band-form").waitFor({ timeout: 30000 });
const landedOnBands = (await panel.locator('.kb-stepper li[data-state="current"]').innerText()).includes("자금");
const cost = {
  landsFirst: landedOnBands,
  bandScreen: true,
  // 파라미터 미등록이면 누락 키가 화면에 보여야 한다 (부록 A 불변조건 1)
  pendingShown: paramsRegistered ? true : await panel.locator(".kb-missing-params li").count() > 0,
  bandTableShown: paramsRegistered ? await panel.locator(".kb-band-table").isVisible() : true
};

// 입지 — 자금 다음 단계. 후보가 있으면 계획 기준으로 확정한다.
await panel.locator(".kb-stepnav .kb-primary-sm").click();
await panel.locator(".kb-candidates, .kb-empty").first().waitFor({ timeout: 30000 });
const candidateCount = await panel.locator(".kb-candidates li").count();
if (candidateCount > 0) await panel.locator(".kb-candidates li").first().getByRole("button", { name: "계획 기준으로 확정" }).click();
const demoBadges = await panel.locator(".kb-candidates .demo-badge").count();
const location = { rendered: true, candidateCount, demoBadges, committable: candidateCount === 0 || (await panel.locator(".kb-candidates li").first().innerText()).includes("계획 기준") };

// 처방 — 근거를 지나 마지막 단계. 공고 조회 응답을 기다린다.
const programsResponse = page.waitForResponse(r => r.url().includes("/api/v1/programs?"), { timeout: 30000 }).catch(() => null);
for (let hop = 0; hop < 3; hop += 1) {
  if (await panel.locator(".kb-callout").first().isVisible().catch(() => false)) break;
  const next = panel.locator(".kb-stepnav .kb-primary-sm");
  if (await next.count() === 0) throw new Error("StepNav 다음 버튼을 찾지 못했습니다.");
  await next.click();
  await page.waitForTimeout(600);
}
await programsResponse;
await page.waitForFunction(() => {
  const root = window.document.querySelector(".kb-ai-panel");
  if (!root || root.querySelector(".kb-loading")) return false;
  return root.querySelectorAll(".kb-program-list li").length > 0
    || Array.from(root.querySelectorAll(".kb-empty strong")).some(el => el.textContent?.includes("공식 공고"));
}, null, { timeout: 30000 });
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

// 처방 — 제안서 6·7단계. 계획 기준 후보 · 레포트 · 문서 초안 세 블록.
const blocks = (await panel.locator(".kb-prescription-block h3").allInnerTexts()).map((t) => t.replace(/\s+/g, " ").trim());
const docResponse = page.waitForResponse((r) => r.url().includes("/api/v1/documents") && r.request().method() === "POST", { timeout: 30000 }).catch(() => null);
await panel.locator(".kb-doc-actions button").first().click();
const documentResponse = await docResponse;
await page.waitForTimeout(1200);
const prescription = {
  blocks: blocks.length,
  committedShown: candidateCount === 0 || await panel.locator(".kb-committed").count() > 0,
  documentCreated: Boolean(documentResponse && documentResponse.status() === 201),
  // 상담 자동 연결은 게이트가 꺼져 있으므로 그 사실을 고지해야 한다 (부록 A 불변조건 5)
  consultationDisclosed: (await panel.locator(".kb-callout-lock").allInnerTexts()).some((t) => t.includes("상담 자동 연결은 제공하지 않습니다")),
  // 초안 설명은 render_case_pdf 가 실제로 담는 것만 말해야 한다. 문서에 없는 것을 약속하면 안 된다.
  documentCopyHonest: await (async () => {
    const notes = (await panel.locator(".kb-prescription-block").last().locator(".kb-note").allInnerTexts()).join(" ");
    const promisesProvenance = notes.includes("출처와 기준일") && !notes.includes("포함되지 않습니다");
    return notes.includes("확정한 조건") && notes.includes("포함되지 않습니다") && !promisesProvenance;
  })()
};

const result = { stepper, overview, drilldown, returned, lease, bands, location, cost, funding, prescription, axes, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
const expected = ["조건", "자금", "입지", "근거", "처방"];
const stepperOk = expected.every((label, index) => (stepper.labels[index] || "").includes(label));
if (errors.length || !stepperOk || !lease.fieldsPresent || !bands.autoComputed || !bands.safeState
  || !bands.noInventedTradeAreaCount || !location.rendered || !cost.landsFirst || !cost.bandScreen || !cost.pendingShown
  || !cost.bandTableShown || !funding.safeState || !funding.subsidyGapDisclosed
  || !location.committable || (location.candidateCount > 0 && location.demoBadges === 0)
  || prescription.blocks !== 3 || !prescription.committedShown
  || !prescription.documentCreated || !prescription.consultationDisclosed
  || !prescription.documentCopyHonest
  || !axes.disabledCarryReason
  || overview.pins !== 5 || overview.markersBefore !== 0
  || drilldown.markers === 0 || drilldown.badges === 0 || !drilldown.pinsGone
  || returned.pins !== 5) process.exitCode = 1;
