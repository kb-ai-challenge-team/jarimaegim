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

// 금융이 입지보다 먼저 도는지는 화면이 아니라 호출 순서로 판정한다. 화면 배치는 바뀔 수 있어도 이 순서는 계약이다.
const callOrder = [];
page.on("request", request => {
  if (request.method() !== "POST") return;
  if (request.url().includes("/api/v1/funding-bands")) callOrder.push("bands");
  if (request.url().includes("/api/v1/locations/search")) callOrder.push("search");
});

const statusBody = await (await page.request.get(`${base}/api/v1/status`)).json();
const axes = { disabledCarryReason: Object.values(statusBody.axes).every(axis => axis.enabled || Boolean(axis.disabled_reason)) };
const subsidyConfigured = Boolean(statusBody.integrations.bizinfo || statusBody.integrations.kstartup);

await page.goto(`${base}/kb`, { waitUntil: "networkidle" });
await page.waitForSelector(".kb-ai-panel");
const panel = page.locator(".kb-ai-panel");

// 첫 진입 — 조건을 넣기 전에는 자치구 요약 핀만 떠 있어야 한다.
await page.waitForSelector(".kb-district-pin", { timeout: 30000 });
// 기대 개수는 API에서 유도한다. 커버리지가 늘 때마다 테스트를 고치지 않도록.
const coveredDistricts = (await (await page.request.get(`${base}/api/v1/listings/summary`)).json()).districts.map(entry => entry.district);
const overview = {
  pins: await page.locator(".kb-district-pin").count(),
  districts: await page.locator(".kb-district-pin strong").allInnerTexts(),
  markersBefore: await page.locator(".kb-marker").count(),
  expected: coveredDistricts.length,
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

// 스텝 0 — 금융 프로필. 마이데이터 게이트는 기본이 off 이고, 잠긴 사실을 숨기지 않아야 한다 (부록 A 불변조건 5).
const mydataOn = Boolean(statusBody.feature_flags.mydata);
const profile = {
  gateVisible: await panel.locator(".kb-gate-rail").isVisible(),
  mydataGated: mydataOn || await panel.getByRole("button", { name: "마이데이터 연결하고 자동 입력" }).isDisabled(),
  lockExplained: mydataOn || await panel.getByText("마이데이터 연동은 아직 열려 있지 않습니다").isVisible(),
  // 게이트가 닫혀 있어도 수동 어댑터가 같은 항목을 채워야 이후 흐름이 동일하다.
  manualAdapterFields: await panel.locator(".kb-profile-form .kb-field").count()
};

await panel.locator(".kb-profile-form input").nth(0).fill("100000000");
await panel.getByRole("button", { name: /확정하고 조건 입력으로/ }).click();

// 프로필은 익명 세션(24시간)보다 오래 산다. 세션 쿠키를 버리고 새로 들어와도 다시 묻지 않아야 한다.
await context.clearCookies();
await page.reload({ waitUntil: "networkidle" });
await panel.locator(".kb-gate").first().waitFor({ timeout: 15000 });
const persistence = {
  gateSkipped: await panel.locator(".kb-gate-rail").count() === 0,
  badgeCarriesEquity: (await panel.locator(".kb-gate").first().innerText()).includes("1억"),
  storageDisclosed: (await panel.locator(".kb-gate").first().innerText()).includes("이 브라우저에 저장됨"),
  // 지우는 수단이 없으면 저장해서는 안 된다.
  erasable: await (async () => {
    await panel.locator(".kb-gate-edit").first().click();
    await panel.getByRole("button", { name: /이 브라우저에 저장된 값 지우기/ }).waitFor({ timeout: 10000 });
    await panel.getByRole("button", { name: /이 브라우저에 저장된 값 지우기/ }).click();
    await page.reload({ waitUntil: "networkidle" });
    await panel.locator(".kb-gate-rail").waitFor({ timeout: 15000 });
    return await panel.locator(".kb-profile-form input").nth(0).inputValue() === "";
  })()
};

// 지웠으므로 처음부터 다시 확정한다.
await panel.locator(".kb-profile-form input").nth(0).fill("100000000");
await panel.getByRole("button", { name: /확정하고 조건 입력으로/ }).click();

// 조건 — 예시 문장으로 채우고 확인 화면으로
await panel.locator(".kb-examples button").first().click();
await panel.getByRole("button", { name: "조건으로 정리하기" }).click();
await panel.locator(".kb-condcard").waitFor();

const chipTexts = await panel.locator(".kb-chip").allInnerTexts();
const condition = {
  // 자기자본은 프로필이 들고 있으므로 조건 화면이 다시 묻지 않는다.
  equityCarried: chipTexts.some(text => text.includes("자기자본") && text.includes("금융 프로필")),
  profileBadgeShown: await panel.locator(".kb-gate").count() > 0,
  // 답이 후보를 바꾸는 항목만, 최대 3개까지만 묻는다.
  askCount: await panel.locator(".kb-askbox .kb-field").count()
};
if (condition.askCount > 0) await panel.locator(".kb-askbox input").first().fill("2500000");

const bandsResponsePromise = page.waitForResponse(r => r.url().includes("/api/v1/funding-bands") && r.request().method() === "POST");
await panel.getByRole("button", { name: "이 조건으로 입지 찾기" }).click();
const bandsResponse = await bandsResponsePromise;
const bandsBody = await bandsResponse.json();
const paramsRegistered = bandsBody.status !== "integration_pending";
const bands = {
  autoComputed: bandsResponse.ok(),
  paramsRegistered,
  // 파라미터가 없으면 추정하지 않고 사유를 돌려줘야 한다. 있으면 3중선이 나와야 한다.
  safeState: paramsRegistered
    ? bandsBody.bands.length === 3 && bandsBody.break_even !== null
    : bandsBody.bands.length === 0 && Boolean(bandsBody.message),
  // DS-09 미확보 — 밴드별 상권 수를 지어내지 않는다
  noInventedTradeAreaCount: bandsBody.bands.every(line => line.trade_area_count === null),
  // 필요자금 입력이 없으면 partial 이고, 그때 현금소진을 지어내면 안 된다.
  noInventedRunway: bandsBody.status !== "partial" || bandsBody.bands.every(line => line.runway_months === null)
};

await panel.locator(".kb-candidates, .kb-empty").first().waitFor({ timeout: 30000 });
const stepper = { labels: await panel.locator(".kb-stepper li").allInnerTexts() };

// 밴드는 후보를 보기 전에 이미 산출돼 있어야 한다 — 사용자를 금융 화면 앞에 세우지 않는다.
const flowOrder = {
  bandsBeforeSearch: callOrder.indexOf("bands") !== -1 && callOrder.indexOf("bands") < callOrder.indexOf("search"),
  // 조건 확정 직후 착지하는 단계는 입지다. 자금이 별도 스텝으로 돌아오면 재설계가 되돌아간 것이다.
  landsOnLocation: (await panel.locator('.kb-stepper li[data-state="current"]').innerText()).includes("입지"),
  bandSummaryInPlace: await panel.locator(".kb-band-banner").count() > 0
    || await panel.locator(".kb-step > .kb-note").filter({ hasText: "파라미터가 아직 등록되지" }).count() > 0
};

// 정밀하게 맞추기 — 임대 조건은 입지 화면을 떠나지 않고 그 자리에서 고친다.
await panel.getByRole("button", { name: /정밀하게 맞추기/ }).click();
await panel.locator(".kb-band-form").waitFor({ timeout: 15000 });
const tuneLabels = await panel.locator(".kb-band-form .kb-field > span").allInnerTexts();
const lease = {
  fieldsPresent: ["희망 평수", "임차보증금", "월세"].every(label => tuneLabels.some(text => text.includes(label))),
  // 프로필이 확정한 값은 여기서 다시 묻지 않는다.
  profileNotReasked: !tuneLabels.some(text => text.includes("기존 대출 잔액")),
  stillOnLocation: (await panel.locator('.kb-stepper li[data-state="current"]').innerText()).includes("입지"),
  // 내부 파라미터 키는 화면에 노출하지 않는다.
  noRawParamKeys: !(await panel.innerText()).includes("loan.")
};
const cost = { bandTableShown: paramsRegistered ? await panel.locator(".kb-band-table").isVisible() : true };
await panel.getByRole("button", { name: /정밀하게 맞추기/ }).click();

// 입지 — 근거는 목록을 벗어나지 않고 그 자리에서 펼쳐진다.
const candidateCount = await panel.locator(".kb-candidates li").count();
let evidenceInline = true;
if (candidateCount > 0) {
  await panel.getByRole("button", { name: /근거 펼치기/ }).first().click();
  await panel.locator(".kb-evidence .kb-verdict").first().waitFor({ timeout: 30000 });
  evidenceInline = await panel.locator(".kb-candidates li").count() >= candidateCount;
  await panel.locator(".kb-candidates li").first().getByRole("button", { name: "계획 기준으로 확정" }).click();
}
const demoBadges = await panel.locator(".kb-candidates .demo-badge").count();
const location = {
  rendered: true, candidateCount, demoBadges, evidenceInline,
  committable: candidateCount === 0 || (await panel.locator(".kb-candidates li").first().innerText()).includes("계획 기준")
};

// 처방 — 입지 다음 단계. 공고 조회 응답을 기다린다.
const programsResponse = page.waitForResponse(r => r.url().includes("/api/v1/programs?"), { timeout: 30000 }).catch(() => null);
await panel.locator(".kb-stepnav .kb-primary-sm").click();
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
// 처방에 뜬 상품은 전부 추천 근거를 달고 있어야 한다. 근거 없는 행이 하나라도 있으면
// 조건과 무관한 공시가 다시 새어 들어온 것이다.
const productRows = await panel.locator(".kb-products ul li").count();
let rowsWithReason = 0;
for (const row of await panel.locator(".kb-products ul li").all()) {
  if (await row.locator(".kb-match-reasons span").count() > 0) rowsWithReason += 1;
}
const recommendation = {
  productRows,
  everyRowHasReason: rowsWithReason === productRows,
  // "나머지 N건 보기"가 되살아나면 비추천 상품이 다시 화면에 들어온다.
  noBulkExpander: await panel.getByRole("button", { name: /나머지 \d+건 보기/ }).count() === 0
};

const prescription = {
  blocks: blocks.length,
  committedShown: candidateCount === 0 || await panel.locator(".kb-committed").count() > 0,
  documentCreated: Boolean(documentResponse && documentResponse.status() === 201),
  // 밴드 표는 입지 화면에서 이미 봤다. 처방에서 반복하지 않는다.
  noDuplicateBandTable: await panel.locator(".kb-band-table").count() === 0,
  // 상담 자동 연결은 게이트가 꺼져 있으므로 그 사실을 고지해야 한다 (부록 A 불변조건 5)
  consultationDisclosed: (await panel.locator(".kb-callout-lock").allInnerTexts()).some((t) => t.includes("상담 자동 연결은 제공하지 않습니다")),
  // 초안 설명은 render_case_pdf 가 실제로 담는 것만 말해야 한다. 문서에 없는 것을 약속하면 안 된다.
  documentCopyHonest: await (async () => {
    const notes = (await panel.locator(".kb-prescription-block").last().locator(".kb-note").allInnerTexts()).join(" ");
    const promisesProvenance = notes.includes("출처와 기준일") && !notes.includes("포함되지 않습니다");
    return notes.includes("확정한 조건") && notes.includes("포함되지 않습니다") && !promisesProvenance;
  })()
};

// 원문 이동은 최종 추천(처방)에서만 살아 있다. 정책·상품 탭에서는 제거되었으므로, 되살아나면
// 여기서 걸린다. 두 패널은 같은 .kb-policy 루트를 쓰므로 탭을 전환해 가며 따로 센다.
await page.getByRole("button", { name: "정책" }).click();
await page.waitForFunction(() => {
  const root = window.document.querySelector(".kb-policy-body");
  return Boolean(root) && !root.querySelector(".kb-loading");
}, null, { timeout: 30000 });
const policyTab = {
  rows: await page.locator(".kb-policy .kb-program-list li").count(),
  noOutboundLinks: await page.locator(".kb-policy a[href^='http']").count() === 0
};
await page.getByRole("button", { name: "상품" }).click();
await page.waitForFunction(() => {
  const root = window.document.querySelector(".kb-policy-body");
  return Boolean(root) && !root.querySelector(".kb-loading");
}, null, { timeout: 30000 });
const productTab = {
  rows: await page.locator(".kb-policy .kb-program-list li").count(),
  noOutboundLinks: await page.locator(".kb-policy a[href^='http']").count() === 0
};

const result = { stepper, overview, drilldown, returned, profile, persistence, condition, flowOrder, lease, bands, location, cost, funding, recommendation, prescription, policyTab, productTab, axes, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
const expected = ["조건", "입지", "처방"];
const stepperOk = stepper.labels.length === 3 && expected.every((label, index) => (stepper.labels[index] || "").includes(label));
if (errors.length || !stepperOk
  || !profile.gateVisible || !profile.mydataGated || !profile.lockExplained || profile.manualAdapterFields !== 3
  || !persistence.gateSkipped || !persistence.badgeCarriesEquity || !persistence.storageDisclosed || !persistence.erasable
  || !condition.equityCarried || !condition.profileBadgeShown || condition.askCount > 3
  || !flowOrder.bandsBeforeSearch || !flowOrder.landsOnLocation || !flowOrder.bandSummaryInPlace
  || !lease.fieldsPresent || !lease.profileNotReasked || !lease.stillOnLocation || !lease.noRawParamKeys
  || !bands.autoComputed || !bands.safeState || !bands.noInventedTradeAreaCount || !bands.noInventedRunway
  || !location.rendered || !location.evidenceInline || !cost.bandTableShown
  || !funding.safeState || !funding.subsidyGapDisclosed
  || !location.committable || (location.candidateCount > 0 && location.demoBadges === 0)
  || !recommendation.everyRowHasReason || !recommendation.noBulkExpander
  || prescription.blocks !== 3 || !prescription.committedShown || !prescription.noDuplicateBandTable
  || !prescription.documentCreated || !prescription.consultationDisclosed
  || !prescription.documentCopyHonest
  || !policyTab.noOutboundLinks || !productTab.noOutboundLinks
  || !axes.disabledCarryReason
  || overview.pins !== overview.expected || overview.markersBefore !== 0
  || drilldown.markers === 0 || drilldown.badges < 1 || !drilldown.pinsGone
  || returned.pins !== overview.expected) process.exitCode = 1;
