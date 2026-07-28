import { chromium } from "playwright-core";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:4173";
const out = new URL("../artifacts/visual/", import.meta.url);
const outputPath = (name) => fileURLToPath(new URL(name, out));
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" });
const viewports = [{ name: "mobile-320", width: 320, height: 568 }, { name: "mobile-390", width: 390, height: 844 }, { name: "tablet", width: 768, height: 1024 }, { name: "desktop-1280", width: 1280, height: 720 }, { name: "desktop-1440", width: 1440, height: 900 }];
// /auth was deleted with the login flow (there are no accounts, only anonymous sessions),
// so checking it only ever measured the 404 page.
const publicRoutes = ["/", "/kb", "/cases/new?mode=first", "/privacy"];
const results = [];
for (const viewport of viewports) {
  const context = await browser.newContext({ viewport });
  const consoleErrors = [];
  const pageErrors = [];
  const page = await context.newPage();
  page.on("console", message => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", error => pageErrors.push(error.message));
  // 콘솔은 "어떤 리소스가 500"까지만 말한다. 어느 요청이었는지를 남겨 두지 않으면 실패를 재현하는
  // 데만 몇 번의 전체 실행이 든다 — 상태 코드와 URL을 같이 적어 둔다.
  const failedRequests = [];
  page.on("response", response => { if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`); });
  for (const route of publicRoutes) {
    await page.goto(base + route, { waitUntil: "networkidle" });
    const geometry = await page.evaluate(() => ({
      title: document.title,
      viewportWidth: document.documentElement.clientWidth,
      documentWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth,
      h1: document.querySelector("h1")?.textContent?.trim() || "",
      main: Boolean(document.querySelector("main")),
      horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
    }));
    const slug = route === "/" ? "landing" : route.split("?")[0].replaceAll("/", "-").replace(/^-/, "");
    await page.screenshot({ path: outputPath(`${viewport.name}-${slug}.png`), fullPage: true });
    results.push({ viewport: viewport.name, route, ...geometry });
  }
  // KB 흐름의 ④ 조달 · ⑤ 서류. 시연용 매물이 없으면 도달할 수 없으므로 건너뛴 사실을 남긴다 —
  // 조용히 지나가면 "찍었다"로 읽힌다.
  const kbSteps = { viewport: viewport.name, route: "/kb", funding: false, paperwork: false, skipped: null };
  try {
    await page.goto(base + "/kb", { waitUntil: "networkidle" });
    await page.locator(".kb-profile-form input").nth(0).fill("100000000");
    await page.getByRole("button", { name: /확정하고 조건 입력으로/ }).click();
    await page.locator(".kb-field-block textarea").fill("강남구에서 카페를 준비 중이에요");
    await page.getByRole("button", { name: /조건으로 정리하기/ }).click();
    await page.locator(".kb-askbox input").first().fill("2500000");
    await page.getByRole("button", { name: "이 조건으로 입지 찾기" }).click();
    await page.waitForSelector(".kb-candidates li, .kb-empty", { timeout: 30000 });
    if (await page.locator(".kb-candidates li").count() === 0) {
      kbSteps.skipped = "시연용 매물 없음";
    } else {
      await page.getByRole("button", { name: "계획 기준으로 확정" }).first().click();
      await page.waitForSelector(".kb-candidate-actions .kb-primary-sm");
      // 단계 이동 버튼은 .kb-stepnav 안에만 있다. 대화 칼럼의 추천 질문도 버튼이라 이름만으로 고르면 두 개가 잡힌다.
      await page.locator(".kb-stepnav").getByRole("button", { name: /다음/ }).click();
      // 조달 화면은 들어서면서 공시·공고를 조회한다. 첫 렌더에는 빈 상태가 한 프레임 스쳐 가므로
      // 빈 상태를 대기 조건에 같이 넣으면 즉시 통과해 그 찰나를 찍는다 — 고를 수 있는 입력이
      // 나타나기를 기다리고, 정말 빈 환경일 때만 시간 초과 후 빈 상태를 찍는다.
      // 부족분 카드는 조회를 기다리지 않고 즉시 그려진다. 네트워크를 기다리는 것은 그 아래 목록이다.
      await page.waitForSelector(".kb-gap-card", { timeout: 20000 });
      await page.waitForSelector(".kb-select-row input[type=checkbox]", { timeout: 30000 }).catch(() => null);
      // 셸이 100vh 라 패널은 .kb-ai-scroll 안에서만 스크롤된다. 좁은 화면에서는 이 안쪽 스크롤이
      // 대화 쪽에 머물러 있어 fullPage 로 찍어도 단계 본문이 프레임 밖에 남는다(측정값 y≈-1700px).
      // 찍기 전에 본문을 안쪽 뷰포트로 끌어와야 "찍었다"가 실제로 그 화면을 뜻한다.
      await page.locator(".kb-gap-card").scrollIntoViewIfNeeded();
      await page.screenshot({ path: outputPath(`${viewport.name}-kb-funding.png`), fullPage: true });
      kbSteps.funding = true;
      kbSteps.fundingSelectable = await page.locator(".kb-select-row input[type=checkbox]").count();
      kbSteps.horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      // 단계 본문이 실제로 몇 px 안에서 보이는지. 좁은 화면에서 이 값이 본문 높이에 비해 터무니없이
      // 작으면 스크린샷은 찍혀도 사람이 볼 수 있는 화면은 아니다 — 수치로 남겨 두어야 드러난다.
      kbSteps.panelViewport = await page.evaluate(() => {
        const el = document.querySelector(".kb-ai-scroll");
        return el ? { clientH: el.clientHeight, scrollH: el.scrollHeight } : null;
      });
      await page.getByRole("button", { name: /문서 만들기|서류로/ }).click();
      await page.waitForSelector(".kb-doc-preview");
      await page.locator(".kb-doc-preview").scrollIntoViewIfNeeded();
      await page.screenshot({ path: outputPath(`${viewport.name}-kb-paperwork.png`), fullPage: true });
      kbSteps.paperwork = true;
    }
  } catch (error) {
    kbSteps.skipped = String(error?.message ?? error).replace(/\x1b\[\d+m/g, "").split("\n")[0].trim();
  }
  results.push(kbSteps);

  await context.request.post(base + "/api/v1/sessions/anonymous", { data: { retention_notice_accepted: true } });
  const created = await context.request.post(base + "/api/v1/cases", { data: { title: "마포구 카페 처음 창업", inputs: { industry: "카페", district: "마포구", budget_krw: 100000000, equity_krw: 70000000, business_stage: "PRE_OPEN", startup_type: "INDEPENDENT", priority: "STABILITY" } } });
  const record = await created.json();
  await page.goto(`${base}/cases/${record.id}/explore`, { waitUntil: "networkidle" });
  await page.waitForSelector(".service-shell");
  const workspaceGeometry = await page.evaluate(() => ({
    viewportWidth: document.documentElement.clientWidth,
    documentWidth: document.documentElement.scrollWidth,
    horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    shellHeight: document.querySelector(".service-shell")?.getBoundingClientRect().height || 0,
    viewportHeight: window.innerHeight,
    emptyStateVisible: Boolean(document.querySelector(".empty-state")),
    mobileSwitcherVisible: getComputedStyle(document.querySelector(".mobile-switcher")).display !== "none"
  }));
  await page.screenshot({ path: outputPath(`${viewport.name}-workspace.png`), fullPage: true });
  results.push({ viewport: viewport.name, route: "/cases/:id/explore", ...workspaceGeometry, consoleErrors: [...consoleErrors], pageErrors: [...pageErrors], failedRequests: [...failedRequests] });
  await context.close();
}
await browser.close();
await writeFile(new URL("report.json", out), JSON.stringify(results, null, 2));
// 건너뛴 사실을 적어 두기만 하면 셀렉터가 바뀌어도 초록으로 끝난다 — 기록은 남되 통과해서는 안 된다.
// 다만 시연용 매물이 없어 도달하지 못한 것은 정상 경로이므로 그 하나만 통과시킨다(무키 환경 보장).
const LEGITIMATE_SKIP = "시연용 매물 없음";
const failures = results.filter(item => item.horizontalOverflow || item.main === false || item.consoleErrors?.length || item.pageErrors?.length || (item.skipped && item.skipped !== LEGITIMATE_SKIP) || (item.route.includes(":id") && Math.abs(item.shellHeight - item.viewportHeight) > 2));
console.log(JSON.stringify({ checked: results.length, failures, report: outputPath("report.json") }, null, 2));
process.exitCode = failures.length ? 1 : 0;
