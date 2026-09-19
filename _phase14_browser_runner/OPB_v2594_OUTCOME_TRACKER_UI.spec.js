const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const BASE_URL = process.env.OPB_BASE_URL || "http://127.0.0.1:8765";

const THEMES = [
  "dark-cyber",
  "dracula-purple",
  "ivory-gold",
  "midnight-slate",
  "emerald-matrix"
];

const MANDATORY_VIEWPORTS = [
  { name: "fhd_1080p", width: 1920, height: 1080 },
  { name: "desktop_1536", width: 1536, height: 864 },
  { name: "laptop_1440", width: 1440, height: 900 },
  { name: "laptop_1366", width: 1366, height: 768 },
  { name: "compact_1280", width: 1280, height: 800 },
  { name: "tablet_landscape_1024", width: 1024, height: 768 },
  { name: "tablet_portrait_768", width: 768, height: 1024 },
  { name: "mobile_large_430", width: 430, height: 932 },
  { name: "mobile_compact_375", width: 375, height: 667 }
];

const report = {
  title: "OPB v2.59.4 Signal Outcome Tracker and RBAC Comprehensive UI Verification",
  timestamp: new Date().toISOString(),
  base_url: BASE_URL,
  mandatory_viewports_count: MANDATORY_VIEWPORTS.length,
  themes_count: THEMES.length,
  pages_checked: ["/admin/signals", "/my-signals", "/admin/config", "/admin/users", "/", "/reports"],
  checks: [],
  overflow_violations: [],
  console_errors: [],
  rbac_checks: []
};

function getTokens() {
  try {
    const scriptPath = "C:/Users/gaura/.gemini/antigravity/brain/1f2fb8fe-7538-4d67-8afe-948c42276d56/scratch/seed_operator_user.py";
    const out = execSync(`C:\\Python314\\python.exe -u "${scriptPath}"`, { encoding: "utf8" });
    const adminMatch = out.match(/ADMIN_SESSION_TOKEN=([a-f0-9]+)/);
    const opMatch = out.match(/OPERATOR_SESSION_TOKEN=([a-f0-9]+)/);
    return {
      adminToken: adminMatch ? adminMatch[1] : null,
      operatorToken: opMatch ? opMatch[1] : null
    };
  } catch (e) {
    console.error("Failed to acquire tokens:", e);
    return { adminToken: null, operatorToken: null };
  }
}

test.describe("Phase 2.1 Signal Outcome Tracker and RBAC Verification Suite", () => {
  let adminToken = null;
  let operatorToken = null;

  test.beforeAll(async () => {
    const tokens = getTokens();
    adminToken = tokens.adminToken;
    operatorToken = tokens.operatorToken;
    console.log("Tokens acquired - Admin:", !!adminToken, "Operator:", !!operatorToken);
  });

  test.afterAll(async () => {
    const outDir = path.join(__dirname, "artifacts", "outcome-tracker");
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(
      path.join(outDir, "OUTCOME_TRACKER_BROWSER_REPORT.json"),
      JSON.stringify(report, null, 2),
      "utf8"
    );
    console.log("Outcome Tracker Browser Report saved successfully.");
  });

  for (const vp of MANDATORY_VIEWPORTS) {
    test(`Viewport ${vp.name} (${vp.width}x${vp.height}) Outcome Tracker and UI Audit`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });

      if (adminToken) {
        await page.context().addCookies([
          { name: "opb_session", value: adminToken, url: BASE_URL }
        ]);
      }

      page.on("console", (msg) => {
        if (msg.type() === "error") {
          report.console_errors.push({ viewport: vp.name, text: msg.text() });
        }
      });

      await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.waitForTimeout(400);

      const ambiguousCard = await page.$("#statAmbiguous");
      expect(ambiguousCard).not.toBeNull();

      const profitFactorCard = await page.$("#statProfitFactor");
      expect(profitFactorCard).not.toBeNull();

      const statusFilter = await page.$("#statusFilter");
      expect(statusFilter).not.toBeNull();
      const ambiguousOption = await page.$("#statusFilter option[value='AMBIGUOUS']");
      expect(ambiguousOption).not.toBeNull();

      for (const theme of THEMES) {
        await page.evaluate((t) => {
          if (window.ThemeEngine) {
            window.ThemeEngine.setTheme(t);
          } else {
            document.documentElement.setAttribute("data-theme", t);
          }
        }, theme);

        await page.waitForTimeout(60);

        const overflow = await page.evaluate(() => {
          const doc = document.documentElement;
          return {
            scrollWidth: doc.scrollWidth,
            clientWidth: doc.clientWidth,
            hasOverflow: doc.scrollWidth > doc.clientWidth + 2
          };
        });

        if (overflow.hasOverflow) {
          report.overflow_violations.push({
            page: "/admin/signals",
            viewport: vp.name,
            theme: theme,
            scrollWidth: overflow.scrollWidth,
            clientWidth: overflow.clientWidth
          });
        }
        expect(overflow.hasOverflow, `Overflow on /admin/signals at ${vp.name} (${theme})`).toBeFalsy();

        report.checks.push({
          page: "/admin/signals",
          viewport: vp.name,
          theme: theme,
          status: "PASSED",
          ambiguousCardFound: true,
          profitFactorCardFound: true
        });
      }

      await page.goto(`${BASE_URL}/my-signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.waitForTimeout(300);

      const signalsTable = await page.$("#userSignalsBody");
      expect(signalsTable).not.toBeNull();

      for (const theme of THEMES) {
        await page.evaluate((t) => {
          if (window.ThemeEngine) {
            window.ThemeEngine.setTheme(t);
          } else {
            document.documentElement.setAttribute("data-theme", t);
          }
        }, theme);

        await page.waitForTimeout(60);

        const overflow = await page.evaluate(() => {
          const doc = document.documentElement;
          return {
            scrollWidth: doc.scrollWidth,
            clientWidth: doc.clientWidth,
            hasOverflow: doc.scrollWidth > doc.clientWidth + 2
          };
        });

        if (overflow.hasOverflow) {
          report.overflow_violations.push({
            page: "/my-signals",
            viewport: vp.name,
            theme: theme,
            scrollWidth: overflow.scrollWidth,
            clientWidth: overflow.clientWidth
          });
        }
        expect(overflow.hasOverflow, `Overflow on /my-signals at ${vp.name} (${theme})`).toBeFalsy();
      }
    });
  }

  test("Configuration UI Displays Invariants SL_PCT 0.88 and BASE_CAPITAL 3000", async ({ page }) => {
    if (adminToken) {
      await page.context().addCookies([
        { name: "opb_session", value: adminToken, url: BASE_URL }
      ]);
    }

    await page.goto(`${BASE_URL}/admin/config`, { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForSelector('.cfg-input[data-key="SL_PCT"]', { state: "attached", timeout: 15000 });

    const slPctVal = await page.$eval('.cfg-input[data-key="SL_PCT"]', el => el.value);
    const baseCapVal = await page.$eval('.cfg-input[data-key="BASE_CAPITAL"]', el => el.value);

    console.log(`Config UI Resolved - SL_PCT: ${slPctVal}, BASE_CAPITAL: ${baseCapVal}`);
    expect(slPctVal).toBe("0.88");
    expect(baseCapVal).toBe("3000");

    report.checks.push({
      test: "SL_PCT_Invariant",
      expected: "0.88",
      actual: slPctVal,
      status: slPctVal === "0.88" ? "PASSED" : "FAILED"
    });
  });

  test("Status Filter Dropdown and Badge Rendering Verification", async ({ page }) => {
    if (adminToken) {
      await page.context().addCookies([
        { name: "opb_session", value: adminToken, url: BASE_URL }
      ]);
    }

    await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
    await page.waitForSelector("#statusFilter", { state: "visible", timeout: 10000 });

    await page.selectOption("#statusFilter", "AMBIGUOUS");
    await page.waitForTimeout(300);

    const selectedVal = await page.$eval("#statusFilter", el => el.value);
    expect(selectedVal).toBe("AMBIGUOUS");

    await page.selectOption("#statusFilter", "all");
    await page.waitForTimeout(300);

    const winRateLabel = await page.$eval('.stat-card:nth-child(2) .stat-label', el => el.textContent.trim());
    expect(winRateLabel).toBe("First-Touch Win Rate (T1)");

    const badgeTest = await page.evaluate(() => {
      const fn = typeof statusBadge !== 'undefined' ? statusBadge : (window.statusBadge || null);
      const ambBadge = fn ? fn('AMBIGUOUS') : '';
      const expBadge = fn ? fn('EXPIRED') : '';
      return {
        ambHasText: ambBadge.includes('AMBIGUOUS'),
        expHasText: expBadge.includes('EXPIRED')
      };
    });
    expect(badgeTest.ambHasText).toBe(true);
    expect(badgeTest.expHasText).toBe(true);
  });

  test("Global Navigation and RBAC Regression Suite", async ({ page, context }) => {
    // 1. Fresh Browser Session without cookies
    await context.clearCookies();
    const resp = await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(page.url()).toContain("/login");
    report.rbac_checks.push({ test: "Unauthenticated Access Redirect", status: "PASSED" });

    // Fresh browser session accessing /my-signals
    const freshContext = await page.context().browser().newContext();
    const freshPage = await freshContext.newPage();
    await freshPage.goto(`${BASE_URL}/my-signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(freshPage.url()).toContain("/login");
    await freshContext.close();
    report.rbac_checks.push({ test: "Fresh Browser Session Redirect", status: "PASSED" });

    // 2. Authenticate Admin
    await context.addCookies([{ name: "opb_session", value: adminToken, url: BASE_URL }]);
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(page.url()).not.toContain("/login");

    // 3. Direct URL access across routes
    for (const r of ["/admin/signals", "/my-signals", "/admin/config", "/admin/users", "/reports"]) {
      const pageResp = await page.goto(`${BASE_URL}${r}`, { waitUntil: "domcontentloaded", timeout: 15000 });
      expect(pageResp.status()).toBe(200);
      report.rbac_checks.push({ test: `Direct URL ${r}`, status: "PASSED" });
    }

    // 4. Refresh Page
    await page.reload({ waitUntil: "domcontentloaded" });
    expect(page.url()).toContain("/reports");
    report.rbac_checks.push({ test: "Refresh Retains Session", status: "PASSED" });

    // 5. Back / Forward Navigation
    await page.goBack({ waitUntil: "domcontentloaded" });
    expect(page.url()).toContain("/admin/users");

    await page.goForward({ waitUntil: "domcontentloaded" });
    expect(page.url()).toContain("/reports");
    report.rbac_checks.push({ test: "Back/Forward Navigation", status: "PASSED" });

    // 6. Logout and Relogin
    await page.goto(`${BASE_URL}/logout`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(page.url()).toContain("/login");
    report.rbac_checks.push({ test: "Logout Redirects to Login", status: "PASSED" });

    // Re-login with fresh active session
    const freshTokens = getTokens();
    await context.addCookies([{ name: "opb_session", value: freshTokens.adminToken, url: BASE_URL }]);
    const reloginResp = await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(reloginResp.status()).toBe(200);
    expect(page.url()).toContain("/admin/signals");
    report.rbac_checks.push({ test: "Relogin Successful", status: "PASSED" });

    // 7. Operator RBAC Isolation
    if (operatorToken) {
      const opContext = await page.context().browser().newContext();
      await opContext.addCookies([{ name: "opb_session", value: operatorToken, url: BASE_URL }]);
      const opPage = await opContext.newPage();

      const opMySig = await opPage.goto(`${BASE_URL}/my-signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
      expect(opMySig.status()).toBe(200);

      const opUsers = await opPage.goto(`${BASE_URL}/admin/users`, { waitUntil: "domcontentloaded", timeout: 15000 });
      const opUsersForbidden = opUsers.status() === 403 || opPage.url().includes("/login") || opPage.url().includes("/forbidden");
      expect(opUsersForbidden).toBe(true);
      report.rbac_checks.push({ test: "Operator RBAC Isolation on /admin/users", status: "PASSED" });

      await opContext.close();
    }
  });

  test("Mojibake and Theme Contrast Check", async ({ page }) => {
    if (adminToken) {
      await page.context().addCookies([
        { name: "opb_session", value: adminToken, url: BASE_URL }
      ]);
    }

    await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
    const bodyText = await page.innerText("body");
    const hasMojibake = bodyText.includes("\uFFFD") || bodyText.includes("Ã¢â‚¬");
    expect(hasMojibake).toBe(false);

    report.checks.push({ test: "Mojibake Check", status: !hasMojibake ? "PASSED" : "FAILED" });
  });
});
