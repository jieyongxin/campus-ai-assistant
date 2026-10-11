/**
 * 无头浏览器验收：打开聊天页 → 点推荐问题 → 截图 → 收集控制台报错。
 *
 *   node scripts/ui_check.js [http://127.0.0.1:8000]
 *
 * 需要 playwright 与本机 Chrome/Edge。可用 PW_MODULES 指定 node_modules 目录。
 */
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");

const BASE = process.argv[2] || "http://127.0.0.1:8000";
const OUT = path.join(__dirname, "..", "docs");

const MODULE_DIRS = [
  process.env.PW_MODULES,
  path.join(
    process.env.USERPROFILE || "",
    ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
  ),
].filter(Boolean);

const BROWSERS = [
  process.env.CHROME_PATH,
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
].filter(Boolean);

function loadPlaywright() {
  for (const dir of MODULE_DIRS) {
    try {
      return createRequire(path.join(dir, "noop.js"))("playwright");
    } catch (e) {
      /* 继续尝试下一个目录 */
    }
  }
  try {
    return require("playwright");
  } catch (e) {
    throw new Error("找不到 playwright，请设置 PW_MODULES 或先 npm i playwright");
  }
}

(async () => {
  const { chromium } = loadPlaywright();
  fs.mkdirSync(OUT, { recursive: true });
  const exe = BROWSERS.find((p) => p && fs.existsSync(p));
  const browser = await chromium.launch(exe ? { executablePath: exe } : {});
  const page = await browser.newPage({
    viewport: { width: 1080, height: 800 },
    deviceScaleFactor: 2,
  });

  const problems = [];
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  page.on("console", (m) => {
    if (m.type() === "error") problems.push("console: " + m.text());
  });
  page.on("requestfailed", (r) => problems.push("requestfailed: " + r.url()));

  await page.goto(BASE + "/", { waitUntil: "networkidle", timeout: 40000 });
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(OUT, "shot-1-welcome.png") });

  const chips = await page.$$(".chip");
  if (chips.length) {
    await chips[0].click();
    await page.waitForTimeout(9000);
  }
  await page.screenshot({ path: path.join(OUT, "shot-2-answer.png") });

  // 手机端布局（挂件在手机上被大量使用）
  const mobile = await browser.newPage({
    viewport: { width: 390, height: 780 },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  const mobileProblems = [];
  mobile.on("pageerror", (e) => mobileProblems.push("pageerror: " + e.message));
  mobile.on("console", (m) => {
    if (m.type() === "error") mobileProblems.push("console: " + m.text());
  });
  await mobile.goto(BASE + "/", { waitUntil: "networkidle", timeout: 40000 });
  await mobile.waitForTimeout(800);
  await mobile.screenshot({ path: path.join(OUT, "shot-3-mobile.png") });
  const overflow = await mobile.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth
  );
  await mobile.close();

  const report = {
    title: await page.title(),
    header: await page.textContent("#schoolName"),
    status: await page.textContent("#statusText"),
    quickQuestions: chips.length,
    messages: await page.$$eval(".msg", (els) =>
      els.map((e) => e.className + " | " + e.innerText.replace(/\n/g, " / ").slice(0, 160))
    ),
    sources: await page.$$eval(".src", (els) => els.map((e) => e.textContent.trim())),
    feedbackButtons: await page.$$eval(".fb button", (els) => els.map((e) => e.textContent)),
    mobileHorizontalOverflowPx: overflow,
    mobileProblems,
    problems,
    screenshots: [
      path.join(OUT, "shot-1-welcome.png"),
      path.join(OUT, "shot-2-answer.png"),
      path.join(OUT, "shot-3-mobile.png"),
    ],
  };
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
})().catch((e) => {
  console.error("UI 检查失败：" + e.message);
  process.exit(1);
});
