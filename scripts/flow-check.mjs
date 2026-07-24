import { chromium } from "playwright-core";

const base = process.env.BASE_URL || "http://127.0.0.1:4173";
const browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(`page:${error.message}`));
page.on("console", message => {
  if (message.type() === "error" && !message.text().startsWith("Failed to load resource:")) errors.push(`console:${message.text()}`);
});
page.on("response", response => {
  if (response.status() < 400) return;
  const expectedAuthGate = response.status() === 401 && response.url().includes("/api/v1/documents");
  if (!expectedAuthGate) errors.push(`http:${response.status()}:${response.url()}`);
});

await page.goto(base, { waitUntil: "networkidle" });
await page.getByRole("link", { name: "처음 창업을 준비해요" }).click();
await page.getByLabel("업종 필수").fill("카페");
const numericInputs = page.locator('input[type="number"]');
await numericInputs.nth(0).fill("100000000");
await numericInputs.nth(1).fill("70000000");
await page.getByRole("button", { name: "조건 검토하기" }).click();
await page.getByRole("button", { name: "이 조건으로 후보 찾기" }).click();
await page.waitForURL(/\/cases\/[0-9a-f-]+\/explore/);
await page.waitForSelector(".service-shell");
const workspaceUrl = page.url();
const onboarding = { url: workspaceUrl, title: await page.locator(".case-title strong").textContent(), integrationPending: await page.locator(".empty-state").isVisible() };

await page.getByRole("button", { name: "비용", exact: true }).first().click();
await page.waitForSelector(".cost-editor");
const costInputs = page.locator('.cost-row input[type="number"]');
for (let index = 0; index < await costInputs.count(); index += 1) {
  const input = costInputs.nth(index);
  await input.click();
  await input.pressSequentially(String(10000000 + index * 1000000));
  await input.press("Tab");
}
await page.waitForFunction(() => Array.from(document.querySelectorAll('.cost-row input[type="number"]')).every(input => input.value.length > 0));
const [costResponse] = await Promise.all([
  page.waitForResponse(response => response.url().includes("/api/v1/cost-plans") && response.request().method() === "POST"),
  page.getByRole("button", { name: "입력값으로 차이 계산" }).click()
]);
if (!costResponse.ok()) throw new Error(`비용 계산 API ${costResponse.status()}: ${await costResponse.text()}\n요청: ${costResponse.request().postData()}`);
await page.waitForFunction(() => {
  const summary = document.querySelector(".funding-summary");
  return summary && !summary.textContent?.includes("계산 전");
});
const costSummary = await page.locator(".funding-summary").textContent();
const cost = { calculated: costSummary.includes("소요자금 범위") && costSummary.includes("조달 차이") && !costSummary.includes("계산 전") };

await page.getByRole("button", { name: "자금", exact: true }).first().click();
await page.waitForSelector(".plan-page");
const funding = { emptySafeState: await page.getByText("표시할 수 있는 공식 공고가 없습니다").isVisible() };

await page.getByRole("button", { name: "계획" }).hover();
await page.getByRole("button", { name: "문서", exact: true }).click();
await page.getByRole("button", { name: "PDF 준비하기" }).first().click();
await page.waitForSelector(".toast");
const document = { authGate: (await page.locator(".toast").textContent()).includes("로그인") };

const chat = page.locator("#chat");
await chat.fill("공식 출처를 알려줘");
await page.locator(".chat-composer button").click();
await page.waitForFunction(() => document.querySelectorAll(".chat-message").length >= 3);
const copilot = { noKeyFallback: (await page.locator(".chat-message").last().textContent()).includes("키") };

const result = { onboarding, cost, funding, document, copilot, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (errors.length || !onboarding.integrationPending || !cost.calculated || !funding.emptySafeState || !document.authGate || !copilot.noKeyFallback) process.exitCode = 1;
