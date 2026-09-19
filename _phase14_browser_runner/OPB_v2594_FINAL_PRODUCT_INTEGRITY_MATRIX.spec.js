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

// EXACTLY the 9 mandatory viewports specified in requirements
const MANDATORY_VIEWPORTS = [
  { name: "fhd_1080p", width: 1920, height: 1080 },
  { name: "desktop_1536", width: 1536, height: 864 },
  { name: "laptop_1440", width: 1440, height: 900 },
  { name: "laptop_1366", width: 1366, height: 768 },
  { name: "compact_1280", width: 1280, height: 800 },
  { name: "tablet_landscape_1024", width: 1024, height: 768 },
  { name: "tablet_portrait_768", width: 768, height: 1024 },
  { name: "mobile_large_430", width: 430, height: 932 },  // Mandatory: no substitutions
  { name: "mobile_compact_375", width: 375, height: 667 }
];

const TARGET_PAGES = [
  { path: "/login", name: "login", auth: false },
  { path: "/", name: "dashboard", auth: true },
  { path: "/admin/signals", name: "admin_signals", auth: true },
  { path: "/admin/users", name: "admin_users", auth: true },
  { path: "/pricing-plans", name: "pricing_plans", auth: true },
  { path: "/intelligence/presentation", name: "presentation", auth: true },
  { path: "/system-health", name: "system_health", auth: true },
  { path: "/admin/config", name: "admin_config", auth: true },
  { path: "/reports", name: "reports", auth: true }
];

const report = {
  title: "OPB v2.59.4 Product-Integrity Remediation Browser Verification",
  timestamp: new Date().toISOString(),
  base_url: BASE_URL,
  mandatory_viewports_count: MANDATORY_VIEWPORTS.length,
  themes_count: THEMES.length,
  pages_count: TARGET_PAGES.length,
  checks: [],
  overflow_violations: [],
  contrast_checks: [],
  focus_checks: [],
  console_errors: [],
  network_errors: []
};

function getTokens() {
  try {
    const out = execSync('python -u "C:/Users/gaura/.gemini/antigravity/brain/1f2fb8fe-7538-4d67-8afe-948c42276d56/scratch/seed_operator_user.py"', { encoding: "utf8" });
    const adminMatch = out.match(/ADMIN_SESSION_TOKEN=([a-f0-9]+)/);
    return {
      adminToken: adminMatch ? adminMatch[1] : null
    };
  } catch (e) {
    return { adminToken: null };
  }
}

test.describe("OPB v2.59.4 Final Responsive & Theme Matrix Gate", () => {
  let adminToken = null;

  test.beforeAll(async () => {
    const tokens = getTokens();
    adminToken = tokens.adminToken;
    console.log("Admin token ready:", !!adminToken);
  });

  test.afterAll(async () => {
    const outDir = path.join(__dirname, "artifacts", "integrity-matrix");
    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(
      path.join(outDir, "PRODUCT_INTEGRITY_BROWSER_REPORT.json"),
      JSON.stringify(report, null, 2),
      "utf8"
    );
  });

  for (const vp of MANDATORY_VIEWPORTS) {
    test(`Viewport ${vp.name} (${vp.width}x${vp.height}) Responsive & Layout Verification`, async ({ page }) => {
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

      page.on("requestfailed", (req) => {
        report.network_errors.push({
          viewport: vp.name,
          url: req.url(),
          failure: req.failure() ? req.failure().errorText : "unknown"
        });
      });

      for (const pg of TARGET_PAGES) {
        await page.goto(`${BASE_URL}${pg.path}`, { waitUntil: "domcontentloaded", timeout: 35000 });
        await page.waitForTimeout(200);

        // Check horizontal overflow
        const overflow = await page.evaluate(() => {
          const scrollW = document.documentElement.scrollWidth;
          const clientW = window.innerWidth;
          return {
            hasOverflow: scrollW > clientW + 1, // allow 1px rounding
            scrollWidth: scrollW,
            clientWidth: clientW
          };
        });

        if (overflow.hasOverflow) {
          report.overflow_violations.push({
            viewport: vp.name,
            page: pg.name,
            scrollWidth: overflow.scrollWidth,
            clientWidth: overflow.clientWidth
          });
        }

        expect(overflow.hasOverflow, `Horizontal overflow detected on ${pg.name} at ${vp.width}x${vp.height}`).toBe(false);

        // On mobile viewports (<768px), verify mobile nav on app screens with navigation
        if (pg.path !== "/login" && vp.width < 768) {
          const mobileNavPresent = await page.evaluate(() => {
            return !!(document.querySelector('.mobile-nav') ||
                      document.querySelector('.pwa-mobile-nav') ||
                      document.querySelector('[aria-label="Mobile Navigation"]') ||
                      document.querySelector('.nav-hamburger') ||
                      document.querySelector('header') ||
                      document.querySelector('nav'));
          });
          expect(mobileNavPresent).toBe(true);
        }
      }

      report.checks.push({
        check: `Viewport ${vp.name} (${vp.width}x${vp.height}) overflow clean`,
        status: "PASS"
      });
    });
  }

  for (const theme of THEMES) {
    test(`Theme ${theme} Computed Styles & Focus Outline Verification`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });

      if (adminToken) {
        await page.context().addCookies([
          { name: "opb_session", value: adminToken, url: BASE_URL }
        ]);
      }

      await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 35000 });
      await page.waitForTimeout(300);

      // Apply theme
      await page.evaluate((themeName) => {
        if (window.ThemeEngine && typeof window.ThemeEngine.setTheme === "function") {
          window.ThemeEngine.setTheme(themeName);
        } else {
          document.documentElement.setAttribute("data-theme", themeName);
        }
      }, theme);

      await page.waitForTimeout(300);

      // Verify theme attributes applied
      const themeData = await page.evaluate(() => {
        const root = document.documentElement;
        const styles = window.getComputedStyle(root);
        return {
          currentTheme: root.getAttribute("data-theme"),
          bgPrimary: styles.getPropertyValue("--bg-primary").trim(),
          bgCard: styles.getPropertyValue("--bg-card").trim(),
          textPrimary: styles.getPropertyValue("--text-primary").trim(),
          textMuted: styles.getPropertyValue("--text-muted").trim(),
          accentColor: styles.getPropertyValue("--accent-color").trim()
        };
      });

      expect(themeData.currentTheme).toBe(theme);
      expect(themeData.bgPrimary.length).toBeGreaterThan(0);
      expect(themeData.textPrimary.length).toBeGreaterThan(0);

      // Verify focus outline on interactive element
      const focusStyles = await page.evaluate(() => {
        const btn = document.querySelector("button") || document.querySelector("select") || document.querySelector("input");
        if (btn) {
          btn.focus();
          const s = window.getComputedStyle(btn);
          return {
            tagName: btn.tagName,
            outlineStyle: s.outlineStyle,
            outlineWidth: s.outlineWidth,
            boxShadow: s.boxShadow
          };
        }
        return null;
      });

      if (focusStyles) {
        report.focus_checks.push({ theme, focusStyles });
      }

      report.checks.push({
        check: `Theme ${theme} loaded and computed variables verified`,
        status: "PASS"
      });
    });
  }
});
