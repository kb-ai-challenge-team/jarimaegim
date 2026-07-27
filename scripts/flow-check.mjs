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
  // 로그인이 제거되고 익명 세션으로 문서를 만들 수 있게 되었으므로 /documents 의 401 은 더 이상 정상이 아니다.
  errors.push(`http:${response.status()}:${response.url()}`);
});

// 랜딩(/)은 KB 셸로 교체되었으므로 조건 입력 흐름의 실제 진입점인 /start에서 시작한다.
await page.goto(`${base}/start`, { waitUntil: "networkidle" });
await page.getByRole("link", { name: "처음 창업 조건 입력" }).click();
await page.getByLabel("업종 필수").fill("카페");
// 시연용 매물이 존재하는 다섯 개 자치구 중 하나를 골라야 후보 목록을 실제로 검증할 수 있다. 기본값(종로구)은 커버 대상이 아니다.
await page.getByLabel(/지역/).selectOption("강남구");
const numericInputs = page.locator('input[type="number"]');
await numericInputs.nth(0).fill("100000000");
await numericInputs.nth(1).fill("70000000");
await page.getByRole("button", { name: "조건 검토하기" }).click();
await page.getByRole("button", { name: "이 조건으로 후보 찾기" }).click();
await page.waitForURL(/\/cases\/[0-9a-f-]+\/explore/);
await page.waitForSelector(".service-shell");
const workspaceUrl = page.url();
const onboarding = { url: workspaceUrl, title: await page.locator(".case-title strong").textContent() };
await page.waitForSelector(".candidate-row, .empty-state");
const listings = { rows: await page.locator(".candidate-row").count(), badges: await page.locator(".candidate-row .demo-badge").count() };

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

// 공고 조회 응답을 기다린 뒤에 판정한다. 즉시 검사하면 fetch 전의 빈 상태를 보고 통과해 버린다.
const programsResponse = page.waitForResponse(r => r.url().includes("/api/v1/programs?"), { timeout: 30000 }).catch(() => null);
await page.getByRole("button", { name: "자금", exact: true }).first().click();
await page.waitForSelector(".plan-page");
await programsResponse;
await page.waitForFunction(() => Boolean(window.document.querySelector(".program-list article, .full-empty")), null, { timeout: 30000 });
const programItems = await page.locator(".program-list article").all();
let programsWithSource = 0;
for (const item of programItems) if (await item.locator('a[href^="http"]').count() > 0) programsWithSource += 1;
const funding = {
  programCount: programItems.length,
  // 공고가 있으면 모두 공식 원문 링크를 가져야 하고, 없으면 빈 상태가 보여야 한다
  safeState: programItems.length > 0
    ? programsWithSource === programItems.length
    : await page.getByText("표시할 수 있는 공식 공고가 없습니다").isVisible().catch(() => false)
};

// 의미 검색. 키 없는 머신에서는 integration_pending 이 정상이므로 "결과가 나온다"를 단언하지
// 않는다. 검색창이 있고, 제출해도 에러 없이 정해진 상태 중 하나로 착지하는지까지만 본다.
await page.getByPlaceholder("예: 임차료 지원, 청년 창업 보증").fill("임차료 지원");
await page.locator("form.policy-search button[type=submit]").click();
await page.waitForFunction(
  () => Boolean(window.document.querySelector(".retrieved-list article, .full-empty h1, .inline-alert.error")),
  null, { timeout: 40000 });
const retrievedItems = await page.locator(".retrieved-list article").all();
let retrievedWithEvidence = 0;
for (const item of retrievedItems) {
  const hasSource = await item.locator('a[href^="http"]').count() > 0;
  const hasExcerpt = await item.locator("blockquote").count() > 0;
  const hasProvenance = await item.locator(".provenance").count() > 0;
  if (hasSource && hasExcerpt && hasProvenance) retrievedWithEvidence += 1;
}
const searchText = await page.locator(".plan-page").innerText();
const search = {
  resultCount: retrievedItems.length,
  // 결과가 있으면 모두 원문·발췌·출처를 갖춰야 하고, 없으면 이유를 밝힌 빈 상태여야 한다
  safeState: retrievedItems.length > 0
    ? retrievedWithEvidence === retrievedItems.length && searchText.includes("근거 등급 C")
    : await page.getByText("검색 결과가 없습니다").isVisible().catch(() => false),
  // 유사도 수치는 화면에 나오면 안 된다 (점수로 오해된다)
  hidesSimilarity: !/0\.\d{2}/.test(searchText)
};
if (retrievedItems.length > 0) await page.locator(".retrieved-list header button").click();

const caseId = workspaceUrl.match(/\/cases\/([0-9a-f-]{36})/)?.[1];
const bandsResponse = await page.request.post(`${base}/api/v1/funding-bands`, {
  data: { case_id: caseId, industry: "카페", area_pyeong: 15, deposit_krw: 100000000, monthly_rent_krw: 2500000,
          monthly_maintenance_krw: 300000, key_money_krw: 0, fitout_krw: null, equity_krw: 100000000,
          existing_debt_krw: 0, other_monthly_fixed_krw: 1000000 }
});
const bandsBody = await bandsResponse.json();
const bands = { pendingSafeState: bandsBody.status === "integration_pending" && bandsBody.bands.length === 0 && bandsBody.missing_params.length > 0 };

const statusBody = await (await page.request.get(`${base}/api/v1/status`)).json();
const axes = { disabledCarryReason: Object.values(statusBody.axes).every(axis => axis.enabled || Boolean(axis.disabled_reason)) };

await page.getByRole("button", { name: "계획" }).hover();
await page.getByRole("button", { name: "문서", exact: true }).click();
await page.getByRole("button", { name: "PDF 준비하기" }).first().click();
// 이전 단계의 토스트가 남아 있을 수 있으므로 요소 존재가 아니라 문서 응답 문구를 기다린다.
await page.waitForFunction(() => {
  const toast = window.document.querySelector(".toast");
  return Boolean(toast?.textContent?.includes("PDF"));
}, null, { timeout: 15000 });
// 로그인은 제거되었다. 지켜야 하는 규칙은 "문서가 익명 세션에 비공개로 생성된다"는 것이다.
const documentToast = (await page.locator(".toast").textContent()) || "";
const documentResult = { sessionScoped: documentToast.includes("익명 세션") };

const aiConfigured = Boolean(statusBody.integrations.openai);
const caseBefore = await (await page.request.get(`${base}/api/v1/cases/${caseId}`)).json();

const chat = page.locator("#chat");
await chat.fill("공식 출처를 알려줘");
await page.locator(".chat-composer button").click();
await page.waitForFunction(() => window.document.querySelectorAll(".chat-message").length >= 3);
const reply = (await page.locator(".chat-message").last().textContent()) || "";
const caseAfter = await (await page.request.get(`${base}/api/v1/cases/${caseId}`)).json();
const copilot = {
  aiConfigured,
  // 키가 없으면 폴백 고지가, 있으면 실제 답변이 와야 한다. 둘 다 정상 상태다.
  safeState: aiConfigured ? reply.trim().length > 0 : reply.includes("키"),
  // 부록 A 불변조건 4 — 대화는 케이스 조건을 바꿀 수 없다. 키 유무와 무관하게 항상 성립해야 한다.
  caseUnchanged: caseAfter.version === caseBefore.version
    && JSON.stringify(caseAfter.inputs) === JSON.stringify(caseBefore.inputs)
};

const result = { onboarding, listings, cost, funding, search, bands, axes, document: documentResult, copilot, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (errors.length || !listings.rows || !listings.badges || !cost.calculated || !funding.safeState || !search.safeState || !search.hidesSimilarity || !bands.pendingSafeState || !axes.disabledCarryReason || !documentResult.sessionScoped || !copilot.safeState || !copilot.caseUnchanged) process.exitCode = 1;
