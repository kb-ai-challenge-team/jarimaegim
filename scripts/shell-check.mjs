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
// 묻는 항목은 답을 입력하는 도중에 사라지면 안 된다. 값이 채워지는 순간 질문 목록에서 빠지면
// 자기 입력이 자기 필드를 언마운트한다 — 스피너 위로 버튼 한 번에 10만 원이 확정되고, 타이핑은
// 첫 글자만 남는다. .fill() 은 이벤트가 한 번이라 이 결함을 통과시키므로 한 글자씩 넣어 확인한다.
const rentField = panel.locator(".kb-askbox input[type=number]");
const rentAsked = await rentField.count() > 0;
const asking = { rentAsked, survivesStep: true, typed: "", survivesTyping: true };
if (rentAsked) {
  await rentField.press("ArrowUp"); // 네이티브 스피너 위로 버튼과 같은 경로
  asking.survivesStep = await rentField.count() > 0;
  if (asking.survivesStep) {
    await rentField.fill("");
    await rentField.pressSequentially("2500000");
    asking.typed = await rentField.inputValue().catch(() => "");
  }
  asking.survivesTyping = asking.typed === "2500000";
}
if (rentAsked && await rentField.count() > 0) await rentField.fill("2500000");

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

// ④ 조달 · ⑤ 서류 — 옛 "처방" 한 화면이 두 단계로 갈라졌다. 단계 잠금·화면 전환·동의 게이트 같은
// "도달했는가"는 flow-check 의 prescribe 블록이 이미 판정하므로 여기서는 되풀이하지 않고 두 화면의
// 내용만 본다 — 원문 링크, 상위 N 상한, 추천 근거, 게이트 고지, 그리고 실제 문서 생성(201).
// 번호 매긴 처방 블록 세 칸(.kb-prescription-block)을 세던 단언은 화면 자체가 사라졌으므로 폐기했다.
// 분리가 되돌아갔는지는 아래 두 가지가 대신 잡는다 — 스테퍼 라벨 네 칸(파일 끝 stepperOk), 그리고
// funding.noDocActions / paperwork.noSelectRows(고르기와 문서화가 한 화면으로 다시 합쳐지지 않았는가).
const OTHER_REGIONS = ["부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"];
const funding = { subsidyConfigured, reached: false };
const recommendation = {};
const paperwork = { reached: false };
// 후보를 확정해야 부족분이 서고, 부족분이 서야 조달 화면의 질문이 성립한다. 확정 전에는 다음이
// 잠겨 있으므로 후보가 0건인 환경에서는 두 화면 모두 도달할 수 없다 — 그때는 이 묶음을 판정하지 않는다.
if (candidateCount > 0) {
  // 확정이 목록에 반영되기 전에는 .kb-stepnav 의 다음이 잠겨 있다. 확정 표시가 뜬 뒤에 누른다.
  await panel.locator(".kb-candidate-actions .kb-primary-sm").first().waitFor({ timeout: 15000 });
  // 공시·공고는 이 화면에 들어선 뒤에 조회된다(use-jarimaegim 의 step==="funding" 효과).
  const programsResponse = page.waitForResponse(r => r.url().includes("/api/v1/programs?"), { timeout: 30000 }).catch(() => null);
  const kbProductsResponse = page.waitForResponse(r => r.url().includes("/api/v1/products/kb"), { timeout: 30000 }).catch(() => null);
  // 단계 이동 버튼은 .kb-stepnav 안에만 있다. 오른쪽 대화 칼럼의 추천 질문("다음에 뭘 해야 해?")도
  // 버튼이라 이름만으로 고르면 두 개가 잡힌다.
  await panel.locator(".kb-stepnav").getByRole("button", { name: /다음/ }).click();
  // 부족분 카드는 단계가 뜨는 순간 그려진다 — 어떤 fetch 도 기다리지 않는다.
  await panel.locator(".kb-gap-card").waitFor({ timeout: 20000 });
  funding.reached = true;
  await Promise.all([programsResponse, kbProductsResponse]);
  // 응답이 온 것과 목록이 그려진 것은 다르다. 두 로더가 모두 걷힐 때까지 기다린 뒤에 센다 —
  // 먼저 세면 3건짜리 목록을 0건으로 읽고 "빈 상태니까 통과"로 새어 나간다.
  await page.waitForFunction(() => {
    const step = window.document.querySelector(".kb-ai-panel .kb-step");
    return Boolean(step) && !step.querySelector(".kb-loading");
  }, null, { timeout: 40000 });

  // 조달에 뜬 상품은 전부 추천 근거를 달고 있어야 한다. 근거 없는 행이 하나라도 있으면
  // 조건과 무관한 공시가 다시 새어 들어온 것이다. 원문으로 갈 길도 행마다 있어야 한다.
  const productItems = await panel.locator(".kb-products ul li").all();
  let rowsWithReason = 0, rowsWithSource = 0;
  for (const row of productItems) {
    if (await row.locator(".kb-match-reasons span").count() > 0) rowsWithReason += 1;
    if (await row.locator('a[href^="http"]').count() > 0) rowsWithSource += 1;
  }
  // 공고도 같은 규칙을 받는다 — 근거를 달고, 다른 광역자치단체 공고는 아예 오르지 않는다.
  const programItems = await panel.locator(".kb-program-list li").all();
  let programRowsWithReason = 0, programRowsWithSource = 0;
  for (const row of programItems) {
    if (await row.locator(".kb-match-reasons span").count() > 0) programRowsWithReason += 1;
    if (await row.locator('a[href^="http"]').count() > 0) programRowsWithSource += 1;
  }
  const programTitles = await panel.locator(".kb-program-list li strong").allInnerTexts();
  Object.assign(recommendation, {
    productRows: productItems.length,
    everyRowHasReason: rowsWithReason === productItems.length,
    // "나머지 N건 보기"가 되살아나면 비추천 상품이 다시 화면에 들어온다.
    noBulkExpander: await panel.getByRole("button", { name: /나머지 \d+건 보기/ }).count() === 0,
    // 검토할 수 있는 분량을 넘기지 않는다. 넘긴다면 조용히 자른 것이 아니라 상한이 풀린 것이다.
    productsWithinTop: productItems.length <= 3,
    programRows: programItems.length,
    everyProgramHasReason: programRowsWithReason === programItems.length,
    programsWithinTop: programItems.length <= 3,
    // 서울 창업자가 받을 수 없는 공고가 조달 목록에 오르면 안 된다.
    noOtherRegionPrograms: programTitles.every((title) => title.includes("서울") || !OTHER_REGIONS.some((region) => title.includes(region)))
  });

  Object.assign(funding, {
    programCount: programItems.length,
    productCount: productItems.length,
    // 원문 이동은 조달 화면에서만 살아 있다(정책·상품 탭에서는 제거되었다 — 아래에서 따로 센다).
    // 목록에 오른 줄은 상품이든 공고든 예외 없이 공식 원문으로 갈 길을 달고 있어야 한다.
    everyRowHasSource: rowsWithSource === productItems.length && programRowsWithSource === programItems.length,
    // 무엇을 기준으로 한 부족분인지가 화면에 남아 있어야 한다. 옛 .kb-committed 자리다.
    planBadgeShown: await panel.locator(".kb-plan-badge").count() > 0,
    // 밴드 표는 입지 화면에서 이미 봤다. 조달에서 반복하지 않는다.
    noDuplicateBandTable: await panel.locator(".kb-band-table").count() === 0,
    // 지원금이 밴드에 반영되지 않았음을 고지한다
    subsidyGapDisclosed: (await panel.locator(".kb-note").allInnerTexts()).some(text => text.includes("지원사업 endpoint 연동 후")),
    // 고르는 것은 신청이 아니다 — 신청 게이트가 꺼져 있음을 이 화면이 스스로 밝혀야 한다 (부록 A 불변조건 5)
    applicationLockDisclosed: (await panel.locator(".kb-callout-lock").allInnerTexts()).some((t) => t.includes("고르는 것은 문서에 담는다는 뜻이며 신청이 아닙니다")),
    // 문서를 만드는 것은 ⑤ 서류의 일이다. 조달 화면에 초안 버튼이 되살아나면 두 단계가 다시 합쳐진 것이다.
    noDocActions: await panel.locator(".kb-doc-actions").count() === 0
      && await panel.getByRole("button", { name: /초안 준비하기|초안 내려받기/ }).count() === 0
  });

  // 고른 것이 문서에 그대로 실리는지 보려면 무엇을 골랐는지 알아야 한다. 체크박스의 접근성 이름이
  // "<상품명> 문서에 담기"이므로 뒤 문구를 떼면 이름이 남는다.
  const firstBox = panel.locator(".kb-select-row input[type=checkbox]").first();
  let chosenName = "";
  if (await firstBox.count() > 0) {
    chosenName = ((await firstBox.getAttribute("aria-label")) || "").replace(/\s*문서에 담기$/, "").trim();
    await firstBox.check();
  }
  const nextLabel = await panel.getByRole("button", { name: /문서 만들기|서류로/ }).innerText();
  // 체크가 실제로 선택으로 등록되는지는 버튼 라벨이 말한다. 등록되지 않으면 골라도 "선택 없이"로 남는다.
  funding.buttonCountsSelection = chosenName ? nextLabel.includes("고른 1건") : nextLabel.includes("선택 없이");

  await panel.getByRole("button", { name: /문서 만들기|서류로/ }).click();
  await panel.locator(".kb-doc-preview").waitFor({ timeout: 20000 });
  paperwork.reached = true;
  const previewText = await panel.locator(".kb-doc-preview").innerText();
  Object.assign(paperwork, {
    previewRows: await panel.locator(".kb-doc-preview li").count(),
    // 고르기는 ④ 의 일이다. 서류 화면에 체크박스가 되살아나면 두 단계가 다시 합쳐진 것이다.
    noSelectRows: await panel.locator(".kb-select-row").count() === 0,
    noDuplicateBandTable: await panel.locator(".kb-band-table").count() === 0,
    // 미리보기는 render_case_pdf 가 담는 것과 1:1 이어야 한다. 조달에서 고른 수단이 이름 그대로
    // 나타나지 않으면 화면이 문서가 아니라 상투 문구를 보여주고 있는 것이다 — 옛 documentCopyHonest 가
    // "약속한 것보다 문서가 적지 않은가"를 문구로 물었다면, 여기서는 실제 선택으로 되묻는다.
    previewMirrorsSelection: chosenName ? previewText.includes(chosenName) : previewText.includes("고른 조달 수단이 없습니다"),
    // 출처·기준일과 비보장 고지는 문서가 실제로 싣는 줄이다 (부록 A 불변조건 3).
    disclosesSourceAndNonGuarantee: previewText.includes("출처") && previewText.includes("기준일") && previewText.includes("보장하지 않습니다"),
    // 상담 자동 연결은 게이트가 꺼져 있으므로 그 사실을 고지해야 한다 (부록 A 불변조건 5)
    consultationDisclosed: (await panel.locator(".kb-callout-lock").allInnerTexts()).some((t) => t.includes("상담 자동 연결은 제공하지 않습니다"))
  });

  // 동의한 뒤 실제로 초안을 만든다. flow-check 는 버튼이 잠기고 풀리는 데까지만 보므로, 문서가
  // 정말 만들어지는지(201)를 확인하는 곳은 여기뿐이다.
  const docResponse = page.waitForResponse((r) => r.url().includes("/api/v1/documents") && r.request().method() === "POST", { timeout: 30000 }).catch(() => null);
  await panel.getByRole("checkbox", { name: "위 내용이 문서에 담기는 것을 확인했습니다" }).check();
  await panel.getByRole("button", { name: /초안 준비하기/ }).click();
  const documentResponse = await docResponse;
  paperwork.documentCreated = Boolean(documentResponse && documentResponse.status() === 201);
  await page.waitForTimeout(800);
}

// 원문 이동은 조달 화면(④)에서만 살아 있다. 정책·상품 탭에서는 제거되었으므로, 되살아나면
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

const result = { stepper, overview, drilldown, returned, profile, persistence, condition, asking, flowOrder, lease, bands, location, cost, funding, recommendation, paperwork, policyTab, productTab, axes, errors };
console.log(JSON.stringify(result, null, 2));
await browser.close();
// 처방 한 칸이 조달·서류 둘로 갈라졌다. 라벨을 순서대로 확인하므로 분리가 되돌아가면 여기서 걸린다.
const expected = ["조건", "입지", "조달", "서류"];
const stepperOk = stepper.labels.length === 4 && expected.every((label, index) => (stepper.labels[index] || "").includes(label));
if (errors.length || !stepperOk
  || !profile.gateVisible || !profile.mydataGated || !profile.lockExplained || profile.manualAdapterFields !== 3
  || !persistence.gateSkipped || !persistence.badgeCarriesEquity || !persistence.storageDisclosed || !persistence.erasable
  || !condition.equityCarried || !condition.profileBadgeShown || condition.askCount > 3
  || !asking.survivesStep || !asking.survivesTyping
  || !flowOrder.bandsBeforeSearch || !flowOrder.landsOnLocation || !flowOrder.bandSummaryInPlace
  || !lease.fieldsPresent || !lease.profileNotReasked || !lease.stillOnLocation || !lease.noRawParamKeys
  || !bands.autoComputed || !bands.safeState || !bands.noInventedTradeAreaCount || !bands.noInventedRunway
  || !location.rendered || !location.evidenceInline || !cost.bandTableShown
  || !location.committable || (location.candidateCount > 0 && location.demoBadges === 0)
  || !policyTab.noOutboundLinks || !productTab.noOutboundLinks
  || !axes.disabledCarryReason
  || overview.pins !== overview.expected || overview.markersBefore !== 0
  || drilldown.markers === 0 || drilldown.badges < 1 || !drilldown.pinsGone
  || returned.pins !== overview.expected) process.exitCode = 1;

// ④ 조달 · ⑤ 서류 는 후보를 확정해야 도달할 수 있다. 시연용 매물이 없는 환경에서는 두 화면이
// 존재하지 않으므로 판정하지 않는다 — 무키 환경에서도 통과해야 한다는 규칙이 이 게이트의 이유다.
if (location.candidateCount > 0 && (!funding.reached || !paperwork.reached
  || !recommendation.everyRowHasReason || !recommendation.noBulkExpander || !recommendation.productsWithinTop
  || !recommendation.everyProgramHasReason || !recommendation.programsWithinTop || !recommendation.noOtherRegionPrograms
  || !funding.planBadgeShown || !funding.everyRowHasSource || !funding.subsidyGapDisclosed
  || !funding.noDuplicateBandTable || !funding.applicationLockDisclosed || !funding.buttonCountsSelection
  // 고르기는 ④ 에만, 문서화는 ⑤ 에만 있어야 한다. 둘 중 하나라도 반대편에 나타나면 두 단계가 다시 합쳐진 것이다.
  || !funding.noDocActions || !paperwork.noSelectRows
  || !paperwork.noDuplicateBandTable || paperwork.previewRows < 4
  || !paperwork.previewMirrorsSelection || !paperwork.disclosesSourceAndNonGuarantee
  || !paperwork.consultationDisclosed || !paperwork.documentCreated)) process.exitCode = 1;
