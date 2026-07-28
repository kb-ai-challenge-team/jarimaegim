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
let programsWithConditions = 0;
for (const item of programItems) if (await item.locator(".condition-tags span").count() > 0) programsWithConditions += 1;
const funding = {
  programCount: programItems.length,
  // 원문 이동 기능은 제거되었다. 남은 요구는 "판정하지 않았음을 카드가 스스로 밝힌다"이다.
  safeState: programItems.length > 0
    ? programsWithConditions === programItems.length
    : await page.getByText("표시할 수 있는 공식 공고가 없습니다").isVisible().catch(() => false),
  // 제거된 기능이 되돌아오면 여기서 걸린다
  noOutboundLinks: await page.locator('.program-list a[href^="http"]').count() === 0
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
  const hasExcerpt = await item.locator("blockquote").count() > 0;
  const hasProvenance = await item.locator(".provenance").count() > 0;
  if (hasExcerpt && hasProvenance) retrievedWithEvidence += 1;
}
const searchText = await page.locator(".plan-page").innerText();
const search = {
  resultCount: retrievedItems.length,
  // 결과가 있으면 모두 발췌·출처를 갖춰야 하고, 없으면 이유를 밝힌 빈 상태여야 한다
  safeState: retrievedItems.length > 0
    ? retrievedWithEvidence === retrievedItems.length && searchText.includes("근거 등급 C")
    : await page.getByText("검색 결과가 없습니다").isVisible().catch(() => false),
  // 유사도 수치는 화면에 나오면 안 된다 (점수로 오해된다)
  hidesSimilarity: !/0\.\d{2}/.test(searchText),
  noOutboundLinks: await page.locator('.retrieved-list a[href^="http"]').count() === 0
};
if (retrievedItems.length > 0) await page.locator(".retrieved-list header button").click();

const caseId = workspaceUrl.match(/\/cases\/([0-9a-f-]{36})/)?.[1];
const bandsResponse = await page.request.post(`${base}/api/v1/funding-bands`, {
  data: { case_id: caseId, industry: "카페", area_pyeong: 15, deposit_krw: 100000000, monthly_rent_krw: 2500000,
          monthly_maintenance_krw: 300000, key_money_krw: 0, fitout_krw: null, equity_krw: 100000000,
          existing_debt_krw: 0, other_monthly_fixed_krw: 1000000 }
});
const bandsBody = await bandsResponse.json();
// 지켜야 하는 규칙은 "파라미터가 비면 추정하지 않는다"이지 "지금 파라미터가 비어 있다"가
// 아니다. 제도 파라미터를 등록하면 밴드가 나오는 것이 정상이고, 그때는 대신 그 값이 어떤
// 근거 위에 서 있는지를 반드시 밝혀야 한다. 두 경로 모두를 안전 상태로 인정한다.
const bandsPending = bandsBody.status === "integration_pending"
  && bandsBody.bands.length === 0 && bandsBody.missing_params.length > 0;
const bandsDisclosed = ["computed", "partial"].includes(bandsBody.status)
  && bandsBody.bands.length > 0
  && (bandsBody.provenance?.limitations ?? []).some((line) => line.includes("시연용 가정값"))
  && bandsBody.provenance?.confidence === "INSUFFICIENT";
const bands = { pendingSafeState: bandsPending || bandsDisclosed, status: bandsBody.status,
                disclosesAssumedBasis: bandsDisclosed };

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
const ipzitalkConfigured = Boolean(statusBody.integrations.ipzitalk);
const caseBefore = await (await page.request.get(`${base}/api/v1/cases/${caseId}`)).json();

const chat = page.locator("#chat");
await chat.fill("공식 출처를 알려줘");
// 패널이 실제로 스트리밍 엔드포인트(POST .../messages/stream)를 호출하는지 네트워크에서 직접 확인한다.
// 이걸 확인하지 않으면, 패널이 예전 단발성 api.chat()으로 조용히 되돌아가는 회귀가 벌어져도 아래의 다른
// 단언들은 그대로 통과해 버린다 — 이 단언이 없으면 그 회귀를 잡을 방법이 없다.
const streamResponsePromise = page.waitForResponse(response => response.request().method() === "POST" && /\/messages\/stream$/.test(new URL(response.url()).pathname), { timeout: 15000 }).catch(() => null);
await page.locator(".chat-composer button").click();
const streamResponse = await streamResponsePromise;
await page.waitForFunction(() => window.document.querySelectorAll(".chat-message").length >= 3);
// 진행 표시가 턴이 끝난 뒤에도 계속 도는 채로 남아있으면, 앱이 실제로 하고 있지 않은 일을 하고 있다고
// 보여주는 것이다 — 실행 중(running) 상태의 tool-activity 행도, 범용 진행 문구도 남아있으면 안 된다.
const progressCleared = await page.waitForFunction(() => !document.querySelector(".tool-progress") && document.querySelectorAll(".tool-activity-item:not(.ok):not(.error)").length === 0, null, { timeout: 10000 }).then(() => true).catch(() => false);
const reply = (await page.locator(".chat-message").last().textContent()) || "";
const citationItems = await page.locator(".citation-item").count();
const caseAfter = await (await page.request.get(`${base}/api/v1/cases/${caseId}`)).json();
const copilot = {
  aiConfigured,
  ipzitalkConfigured,
  // 키가 없으면 폴백 고지가, 있으면 실제 답변이 와야 한다. 둘 다 정상 상태다.
  safeState: aiConfigured ? reply.trim().length > 0 : reply.includes("키"),
  // 부록 A 불변조건 4 — 대화는 케이스 조건을 바꿀 수 없다. 키 유무와 무관하게 항상 성립해야 한다.
  caseUnchanged: caseAfter.version === caseBefore.version
    && JSON.stringify(caseAfter.inputs) === JSON.stringify(caseBefore.inputs),
  // 부록 A 불변조건 1 — ipzitalk 도구 연동이 없으면 인용은 도구 호출 결과에서 나올 수 없으므로 하나도
  // 렌더링되어서는 안 된다. 도구가 연동되어 있으면 실제 인용 유무는 이 스크립트의 관심사가 아니다.
  noFabricatedCitations: ipzitalkConfigured ? true : citationItems === 0,
  noOrphanedProgress: progressCleared,
  streamEndpointUsed: Boolean(streamResponse) && streamResponse.ok() && /event-stream/.test(streamResponse.headers()["content-type"] || "")
};

// KB 셸의 새 흐름 — 금융 프로필(스텝 0) → 조건 → 입지. 세션을 섞지 않도록 새 컨텍스트에서 돈다.
const kbContext = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const kb = await kbContext.newPage();
kb.on("pageerror", error => errors.push(`kb-page:${error.message}`));
await kb.goto(`${base}/kb`, { waitUntil: "networkidle" });

const gateVisible = await kb.locator(".kb-gate-rail").isVisible();
// 마이데이터는 게이트 off 가 기본이다. 잠긴 사실을 숨기지 않고 수동 입력이 같은 항목을 채워야 한다.
const mydataGate = {
  buttonDisabled: await kb.getByRole("button", { name: "마이데이터 연결하고 자동 입력" }).isDisabled(),
  lockExplained: await kb.getByText("마이데이터 연동은 아직 열려 있지 않습니다").isVisible(),
  manualAdapter: await kb.locator(".kb-profile-form input").count() === 3
};

await kb.locator(".kb-profile-form input").nth(0).fill("100000000");
await kb.getByRole("button", { name: /확정하고 조건 입력으로/ }).click();
await kb.locator(".kb-field-block textarea").fill("강남구에서 카페를 준비 중이에요");
await kb.getByRole("button", { name: /조건으로 정리하기/ }).click();
await kb.waitForSelector(".kb-condcard");

// 자기자본은 프로필이 이미 들고 있으므로 조건 화면이 다시 묻지 않는다. 남는 질문은 희망 월세 하나다.
const chips = await kb.locator(".kb-chip").allTextContents();
const conditionStep = {
  askCount: await kb.locator(".kb-askbox .kb-field").count(),
  equityCarried: chips.some(chip => chip.includes("자기자본") && chip.includes("금융 프로필")),
  // "준비 중이에요"의 "중"이 중구로 새지 않아야 한다.
  districtParsed: chips.some(chip => chip.includes("자치구") && chip.includes("강남구"))
};

await kb.locator(".kb-askbox input").first().fill("2500000");
await kb.getByRole("button", { name: "이 조건으로 입지 찾기" }).click();
await kb.waitForSelector(".kb-candidates li, .kb-empty", { timeout: 30000 });

const stepperLabels = await kb.locator(".kb-stepper li").allTextContents();
const bandBannerShown = await kb.locator(".kb-band-banner").count() > 0;
const kbFlow = {
  gateVisible,
  stepCount: stepperLabels.length,
  // 자금·근거가 별도 스텝으로 남아 있으면 재설계가 되돌아간 것이다.
  stepsAreThree: stepperLabels.length === 3 && !stepperLabels.some(label => label.includes("자금") || label.includes("근거")),
  candidates: await kb.locator(".kb-candidates li").count(),
  tuningInPlace: await kb.getByRole("button", { name: /정밀하게 맞추기/ }).count() > 0,
  // 제도 파라미터가 미등록이면 밴드를 지어내지 않고 사유를 밝혀야 한다.
  // 진행 오버레이에도 같은 문구가 남으므로 패널 본문 쪽 고지만 센다.
  bandSafeState: bandBannerShown || await kb.locator(".kb-step > .kb-note", { hasText: "파라미터가 아직 등록되지" }).count() > 0
};

// 근거는 목록을 벗어나지 않고 그 자리에서 펼쳐져야 한다.
if (kbFlow.candidates > 0) {
  await kb.getByRole("button", { name: /근거 펼치기/ }).first().click();
  await kb.waitForSelector(".kb-evidence .kb-verdict", { timeout: 20000 });
  kbFlow.evidenceInline = await kb.locator(".kb-evidence").count() > 0 && await kb.locator(".kb-candidates li").count() > 0;
} else {
  kbFlow.evidenceInline = true;
}

const result = { onboarding, listings, cost, funding, search, bands, axes, document: documentResult, copilot, kbFlow, mydataGate, conditionStep, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
if (errors.length || !listings.rows || !listings.badges || !cost.calculated || !funding.safeState || !funding.noOutboundLinks || !search.safeState || !search.hidesSimilarity || !search.noOutboundLinks || !bands.pendingSafeState || !axes.disabledCarryReason || !documentResult.sessionScoped || !copilot.safeState || !copilot.caseUnchanged || !copilot.noFabricatedCitations || !copilot.noOrphanedProgress || !copilot.streamEndpointUsed) process.exitCode = 1;
if (!kbFlow.gateVisible || !kbFlow.stepsAreThree || !kbFlow.tuningInPlace || !kbFlow.bandSafeState || !kbFlow.evidenceInline) process.exitCode = 1;
if (!mydataGate.buttonDisabled || !mydataGate.lockExplained || !mydataGate.manualAdapter) process.exitCode = 1;
if (conditionStep.askCount !== 1 || !conditionStep.equityCarried || !conditionStep.districtParsed) process.exitCode = 1;
