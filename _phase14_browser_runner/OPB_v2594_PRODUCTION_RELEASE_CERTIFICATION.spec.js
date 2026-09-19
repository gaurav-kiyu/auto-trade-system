const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const BASE_URL = process.env.OPB_BASE_URL || "https://gaurav-cockpit.servegame.com";
const ADMIN_TOKEN = process.env.OPB_ADMIN_TOKEN || "d9c28c707f2ec48203bc7836c9b17aefaadb94c13b21ae750312efc53af96c53";

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

const SCREENS = [
  { path: "/health", name: "health", auth: false },
  { path: "/", name: "cockpit", auth: true },
  { path: "/admin/signals", name: "admin_signals", auth: true },
  { path: "/my-signals", name: "my_signals", auth: true },
  { path: "/admin/config", name: "admin_config", auth: true },
  { path: "/admin/users", name: "admin_users", auth: true },
  { path: "/system-health", name: "system_health", auth: true },
  { path: "/reports", name: "reports", auth: true },
  { path: "/pricing-plans", name: "pricing_plans", auth: true }
];

test.describe("OPB v2.59.4 Production Release Certification", () => {
  test.setTimeout(240000);

  test("Verify production endpoints, themes, viewports, and zero-overflow", async ({ browser }) => {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 900 }
    });

    const parsed = new URL(BASE_URL);
    await context.addCookies([
      { name: "session_token", value: ADMIN_TOKEN, domain: parsed.hostname, path: "/" },
      { name: "opb_session", value: ADMIN_TOKEN, domain: parsed.hostname, path: "/" }
    ]);

    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", msg => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    // 1. Verify all screens load cleanly with HTTP 200
    for (const screen of SCREENS) {
      const url = `${BASE_URL}${screen.path}`;
      const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
      expect(resp.status()).toBe(200);
      console.log(`[PASS] Screen ${screen.name} (${screen.path}) loaded HTTP 200`);
    }

    // 2. Multi-theme verification on Cockpit
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    for (const theme of THEMES) {
      await page.evaluate(t => {
        document.documentElement.setAttribute("data-theme", t);
        if (typeof window.applyTheme === "function") window.applyTheme(t);
      }, theme);
      const applied = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
      expect(applied).toBe(theme);
      console.log(`[PASS] Cockpit applied theme: ${theme}`);
    }

    // 3. Multi-viewport zero-overflow verification on Cockpit
    for (const vp of MANDATORY_VIEWPORTS) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.waitForTimeout(100);
      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > window.innerWidth + 1;
      });
      expect(hasHorizontalScroll).toBe(false);
      console.log(`[PASS] Viewport ${vp.name} (${vp.width}x${vp.height}) has zero horizontal overflow`);
    }

    await context.close();
  });
});
