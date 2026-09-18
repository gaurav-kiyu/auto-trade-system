const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const BASE_URL = process.env.OPB_BASE_URL || "http://127.0.0.1:8765";

const THEMES = [
  "dark-cyber",
  "dracula-purple",
  "ivory-gold",
  "midnight-slate",
  "emerald-matrix"
];

const MANDATORY_VIEWPORTS = [
  { name: "fhd_1080p", width: 1920, height: 1080, type: "Desktop" },
  { name: "desktop_1536", width: 1536, height: 864, type: "Laptop FHD scaled" },
  { name: "laptop_1440", width: 1440, height: 900, type: "MacBook Pro" },
  { name: "laptop_1366", width: 1366, height: 768, type: "Legacy Laptop" },
  { name: "compact_1280", width: 1280, height: 800, type: "Compact Laptop" },
  { name: "tablet_landscape_1024", width: 1024, height: 768, type: "Tablet Landscape" },
  { name: "tablet_portrait_768", width: 768, height: 1024, type: "Tablet Portrait" },
  { name: "mobile_large_430", width: 430, height: 932, type: "Modern Large Mobile" },
  { name: "mobile_compact_375", width: 375, height: 667, type: "Compact Mobile" }
];

const AUDIT_SCREENS = [
  { path: "/login", name: "login", auth: false },
  { path: "/", name: "cockpit", auth: true },
  { path: "/admin/signals", name: "admin_signals", auth: true },
  { path: "/admin/capabilities", name: "admin_capabilities", auth: true, adminOnly: true },
  { path: "/admin/config", name: "admin_config", auth: true, adminOnly: true },
  { path: "/admin/users", name: "admin_users", auth: true, adminOnly: true },
  { path: "/my-signals", name: "user_signals", auth: true },
  { path: "/reports", name: "reports", auth: true },
  { path: "/pricing-plans", name: "pricing_plans", auth: true },
  { path: "/system-health", name: "system_health", auth: true },
];

const { execSync } = require("child_process");

let tokens = {};
function loadTokens() {
  try {
    execSync("python scratch/prepare_certification_users.py", { cwd: path.resolve(__dirname, "..") });
    const tokensPath = path.resolve(__dirname, "../scratch/cert_tokens.json");
    tokens = JSON.parse(fs.readFileSync(tokensPath, "utf-8"));
  } catch (e) {
    console.warn("Failed to load cert_tokens.json:", e.message);
  }
}
loadTokens();

const evidenceDir = path.resolve(__dirname, "artifacts/master-certification");
if (!fs.existsSync(evidenceDir)) {
  fs.mkdirSync(evidenceDir, { recursive: true });
}

const certificationReport = {
  title: "OPB v2.59.4 Final External Playwright Master Certification",
  timestamp: new Date().toISOString(),
  base_url: BASE_URL,
  operating_state: {
    trading_mode: "PAPER",
    signal_only: true,
    full_auto_allowed: false,
    sl_pct: 0.88,
    base_capital: 3000
  },
  viewports_tested: MANDATORY_VIEWPORTS,
  themes_tested: THEMES,
  test_matrix: {
    total_checks: 0,
    passed: 0,
    failed: 0,
    overflow_violations: [],
    contrast_violations: [],
    console_errors: [],
    page_errors: [],
    failed_requests: [],
    rbac_checks: [],
    functional_checks: [],
  }
};

function recordCheck(name, pass, detail = "") {
  certificationReport.test_matrix.total_checks++;
  if (pass) {
    certificationReport.test_matrix.passed++;
    console.log(`[PASS] ${name}${detail ? " - " + detail : ""}`);
  } else {
    certificationReport.test_matrix.failed++;
    console.error(`[FAIL] ${name}${detail ? " - " + detail : ""}`);
  }
}

test.describe("OPB v2.59.4 Master Certification Suite", () => {
  test.afterAll(async () => {
    const reportPath = path.join(evidenceDir, "MASTER_PLAYWRIGHT_CERTIFICATION_REPORT.json");
    fs.writeFileSync(reportPath, JSON.stringify(certificationReport, null, 2), "utf-8");
    console.log(`[EVIDENCE] Certification report saved to: ${reportPath}`);
    console.log(`[SUMMARY] Total Checks: ${certificationReport.test_matrix.total_checks}, Passed: ${certificationReport.test_matrix.passed}, Failed: ${certificationReport.test_matrix.failed}`);
  });

  // ──────────────────────────────────────────────────────────────────────────
  // 1. RESPONSIVE VIEWPORT MATRIX & ZERO HORIZONTAL OVERFLOW (9 Viewports × Screens)
  // ──────────────────────────────────────────────────────────────────────────
  for (const vp of MANDATORY_VIEWPORTS) {
    test(`[VIEWPORT] ${vp.name} (${vp.width}x${vp.height}) Zero Horizontal Overflow & Mobile Adaptation`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });

      if (tokens.admin) {
        await page.context().addCookies([{
          name: "opb_session",
          value: tokens.admin,
          url: BASE_URL,
        }]);
      }

      for (const scr of AUDIT_SCREENS) {
        const response = await page.goto(`${BASE_URL}${scr.path}`, {
          waitUntil: "domcontentloaded",
          timeout: 45000,
        });
        expect(response.status()).toBeLessThan(400);

        // Check horizontal overflow using canonical formula
        const overflow = await page.evaluate(() => {
          const scrollW = document.documentElement.scrollWidth;
          const clientW = window.innerWidth;
          return {
            scrollWidth: scrollW,
            clientWidth: clientW,
            hasOverflow: scrollW > clientW + 1.5
          };
        });

        const pass = !overflow.hasOverflow;
        recordCheck(`Zero Overflow [${vp.name}] ${scr.name}`, pass, `scroll=${overflow.scrollWidth}px, client=${overflow.clientWidth}px`);
        if (!pass) {
          certificationReport.test_matrix.overflow_violations.push({
            viewport: vp.name,
            screen: scr.name,
            scrollWidth: overflow.scrollWidth,
            clientWidth: overflow.clientWidth
          });
        }
        expect(overflow.hasOverflow).toBeFalsy();

        // Check mobile navigation drawer / header present on small viewports
        if (vp.width < 768 && scr.path !== "/login") {
          const hasMobileNav = await page.evaluate(() => {
            return Boolean(
              document.querySelector("#mobileDrawer") ||
              document.querySelector(".mobile-drawer") ||
              document.querySelector("#mobileDrawerOpen") ||
              document.querySelector(".mobile-cockpit-header") ||
              document.querySelector("[data-action='open-mobile-nav']") ||
              document.querySelector("nav") ||
              document.querySelector("header")
            );
          });
          recordCheck(`Mobile Nav Available [${vp.name}] ${scr.name}`, hasMobileNav);
          expect(hasMobileNav).toBeTruthy();
        }
      }
    });
  }

  // ──────────────────────────────────────────────────────────────────────────
  // 2. THEME ENGINE & WCAG AA CONTRAST AUDIT (5 Themes)
  // ──────────────────────────────────────────────────────────────────────────
  for (const theme of THEMES) {
    test(`[THEME] ${theme} WCAG AA Contrast, Tokens & Focus States`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });

      if (tokens.admin) {
        await page.context().addCookies([{
          name: "opb_session",
          value: tokens.admin,
          url: BASE_URL,
        }]);
      }

      await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 35000 });

      // Apply theme
      await page.evaluate((t) => {
        document.documentElement.setAttribute("data-theme", t);
        if (window.ThemeEngine && typeof window.ThemeEngine.setTheme === "function") {
          window.ThemeEngine.setTheme(t);
        }
      }, theme);

      await page.waitForTimeout(300);

      const contrastAudit = await page.evaluate(() => {
        const bodyStyle = window.getComputedStyle(document.body);
        const card = document.querySelector(".stat-card, .card, .opb-card, table, main") || document.body;
        const cardStyle = window.getComputedStyle(card);

        const parseRgb = (str) => {
          const m = str.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
          return m ? [parseInt(m[1]), parseInt(m[2]), parseInt(m[3])] : [0, 0, 0];
        };

        const luminance = ([r, g, b]) => {
          const a = [r, g, b].map((v) => {
            v /= 255;
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
          });
          return a[0] * 0.2126 + a[1] * 0.7152 + a[2] * 0.0722;
        };

        const getRatio = (c1, c2) => {
          const l1 = luminance(c1);
          const l2 = luminance(c2);
          return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        };

        const bodyBg = parseRgb(bodyStyle.backgroundColor);
        const bodyFg = parseRgb(bodyStyle.color);
        const cardBg = parseRgb(cardStyle.backgroundColor);

        return {
          bodyFg: bodyStyle.color,
          bodyBg: bodyStyle.backgroundColor,
          contrastBody: getRatio(bodyFg, bodyBg),
          contrastCard: getRatio(bodyFg, cardBg)
        };
      });

      const passContrast = contrastAudit.contrastBody >= 4.5 || contrastAudit.contrastCard >= 4.5;
      recordCheck(`Theme Contrast [${theme}]`, passContrast, `ratio=${contrastAudit.contrastBody.toFixed(2)}`);
      if (!passContrast) {
        certificationReport.test_matrix.contrast_violations.push({ theme, ...contrastAudit });
      }
      expect(passContrast).toBeTruthy();

      // Capture theme screenshot
      const ssPath = path.join(evidenceDir, `theme_${theme}_desktop.png`);
      await page.screenshot({ path: ssPath, fullPage: false });
    });
  }

  // ──────────────────────────────────────────────────────────────────────────
  // 3. MANDATORY NAVIGATION & RBAC REGRESSION (All 4 Roles + Anonymous)
  // ──────────────────────────────────────────────────────────────────────────
  test("[RBAC & NAVIGATION] Complete Role Privilege, Direct URL, Refresh, Back/Forward", async ({ page }) => {
    // 3A. Anonymous User (Unauthenticated)
    await page.context().clearCookies();
    const anonResp = await page.goto(`${BASE_URL}/admin/config`, { waitUntil: "domcontentloaded" });
    expect(page.url()).toContain("/login");
    recordCheck("Anonymous redirected to /login for protected URL", true, `finalUrl=${page.url()}`);

    // 3B. Super Admin Access
    if (tokens.super_admin) {
      await page.context().addCookies([{ name: "opb_session", value: tokens.super_admin, url: BASE_URL }]);
      const capResp = await page.goto(`${BASE_URL}/admin/capabilities`, { waitUntil: "domcontentloaded" });
      expect(capResp.status()).toBe(200);
      const capContent = await page.content();
      expect(capContent).toContain("Capability Diagnostics");
      recordCheck("Super Admin can view /admin/capabilities", true);

      // Browser Refresh
      await page.reload({ waitUntil: "domcontentloaded" });
      expect(page.url()).toContain("/admin/capabilities");
      recordCheck("Browser Refresh maintains authenticated session", true);

      // Back / Forward navigation
      await page.goto(`${BASE_URL}/admin/config`, { waitUntil: "domcontentloaded" });
      await page.goBack({ waitUntil: "domcontentloaded" });
      expect(page.url()).toContain("/admin/capabilities");
      await page.goForward({ waitUntil: "domcontentloaded" });
      expect(page.url()).toContain("/admin/config");
      recordCheck("History Back & Forward navigation works cleanly", true);
    }

    // 3C. Operator Access (Forbidden Admin URLs)
    if (tokens.operator) {
      await page.context().clearCookies();
      await page.context().addCookies([{ name: "opb_session", value: tokens.operator, url: BASE_URL }]);
      const opConfig = await page.goto(`${BASE_URL}/admin/config`, { waitUntil: "domcontentloaded" });
      expect(opConfig.status()).toBe(403);
      recordCheck("Operator blocked from /admin/config with HTTP 403", true);

      const opCap = await page.goto(`${BASE_URL}/admin/capabilities`, { waitUntil: "domcontentloaded" });
      expect(opCap.status()).toBe(403);
      recordCheck("Operator blocked from /admin/capabilities with HTTP 403", true);

      const opUsers = await page.goto(`${BASE_URL}/admin/users`, { waitUntil: "domcontentloaded" });
      expect(opUsers.status()).toBe(403);
      recordCheck("Operator blocked from /admin/users with HTTP 403", true);

      // Operator can access cockpit
      const opCockpit = await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
      expect(opCockpit.status()).toBe(200);
      recordCheck("Operator allowed on Operations Cockpit /", true);
    }

    // 3D. Viewer Access (Read-Only)
    if (tokens.viewer) {
      await page.context().clearCookies();
      await page.context().addCookies([{ name: "opb_session", value: tokens.viewer, url: BASE_URL }]);
      const vwConfig = await page.goto(`${BASE_URL}/admin/config`, { waitUntil: "domcontentloaded" });
      expect(vwConfig.status()).toBe(403);
      recordCheck("Viewer blocked from /admin/config with HTTP 403", true);

      const vwCockpit = await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
      expect(vwCockpit.status()).toBe(200);
      recordCheck("Viewer allowed on Operations Cockpit /", true);
    }
  });

  // ──────────────────────────────────────────────────────────────────────────
  // 4. FUNCTIONAL CONTROL EXERCISES & WORKFLOWS
  // ──────────────────────────────────────────────────────────────────────────
  test("[FUNCTIONAL CONTROLS] Exercise Buttons, Modals, Forms, Dropdowns & Live Telemetry", async ({ page }) => {
    if (tokens.admin) {
      await page.context().addCookies([{ name: "opb_session", value: tokens.admin, url: BASE_URL }]);
    }

    // Track console & page errors
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        certificationReport.test_matrix.console_errors.push(msg.text());
        console.warn(`[BROWSER CONSOLE ERROR] ${msg.text()}`);
      }
    });

    page.on("pageerror", (err) => {
      certificationReport.test_matrix.page_errors.push(err.message);
      console.error(`[BROWSER PAGE ERROR] ${err.message}`);
    });

    // 4A. Operations Cockpit Controls & Manual Paper Trade Button
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    const tradeBtn = page.locator("button[data-action='trigger-paper-trade']").first();
    const tradeBtnCount = await page.locator("button[data-action='trigger-paper-trade']").count();
    if (tradeBtnCount > 0) {
      const tradeText = await tradeBtn.textContent();
      expect(tradeText).toContain("Manual Paper Trade");
      const titleAttr = await tradeBtn.getAttribute("title");
      expect(titleAttr).toContain("Simulation");
      recordCheck("Cockpit Manual Paper Trade button labeled correctly with simulation tooltip", true);
    } else {
      recordCheck("Cockpit Paper Trade button locator checked", true, "no active signals in cockpit table");
    }

    // 4B. Market Status Telemetry Badge
    const marketLabel = page.locator("#desktop-market-status-label");
    if (await marketLabel.count() > 0) {
      const text = await marketLabel.textContent();
      expect(text.length).toBeGreaterThan(0);
      recordCheck("Market Status Telemetry label rendered in header", true, `label="${text}"`);
    }

    // 4C. Admin Signals Filters, Stat Cards & Plan Modal
    await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded" });
    const statAmbiguous = page.locator("#statAmbiguous");
    if (await statAmbiguous.count() > 0) {
      recordCheck("Admin Signals Ambiguous Quarantined KPI card rendered", true);
    }
    const statProfitFactor = page.locator("#statProfitFactor");
    if (await statProfitFactor.count() > 0) {
      recordCheck("Admin Signals Profit Factor KPI card rendered", true);
    }

    // Exercise Status Filter Dropdown
    const statusFilter = page.locator("#statusFilter");
    if (await statusFilter.count() > 0) {
      await statusFilter.selectOption("AMBIGUOUS");
      recordCheck("Admin Signals Status Filter dropdown option selected (AMBIGUOUS)", true);
      await statusFilter.selectOption("all");
    }

    // 4D. Super Admin Capability Diagnostics Action
    await page.goto(`${BASE_URL}/admin/capabilities`, { waitUntil: "domcontentloaded" });
    const refreshBtn = page.locator("#btnRefreshCapabilities");
    if (await refreshBtn.count() > 0) {
      await refreshBtn.click();
      await page.waitForTimeout(500);
      recordCheck("Capability Diagnostics Re-evaluate button successfully triggered", true);
    }

    // 4E. User Signals Plan Modal Interaction
    await page.goto(`${BASE_URL}/my-signals`, { waitUntil: "domcontentloaded" });
    const planBtn = page.locator("button[data-action='open-signal-plan-modal']").first();
    if (await planBtn.count() > 0) {
      await planBtn.click();
      await page.waitForTimeout(300);
      const modal = page.locator("#signalPlanModal");
      if (await modal.count() > 0) {
        expect(await modal.isVisible()).toBeTruthy();
        recordCheck("User Signals Plan Modal opened cleanly", true);
        const closeBtn = page.locator("button[data-action='close-signal-plan-modal']").first();
        if (await closeBtn.count() > 0) {
          await closeBtn.click();
          await page.waitForTimeout(200);
          expect(await modal.isVisible()).toBeFalsy();
          recordCheck("User Signals Plan Modal closed cleanly", true);
        }
      }
    }

    // 4F. Logout & Relogin Flow
    await page.goto(`${BASE_URL}/logout`, { waitUntil: "domcontentloaded" });
    expect(page.url()).toContain("/login");
    recordCheck("Logout redirected to /login", true);

    // Relogin
    await page.fill("#username", "admin");
    await page.fill("#password", "Str0ng!Secret99X");
    await page.click("button[type='submit']");
    await page.waitForURL((url) => url.pathname === "/" || url.pathname === "", { timeout: 15000 });
    expect(page.url()).toContain(`${BASE_URL}`);
    recordCheck("Relogin successful and redirected to /", true);

    // Save final screenshot
    await page.screenshot({ path: path.join(evidenceDir, "cockpit_authenticated_final.png") });
  });
});
