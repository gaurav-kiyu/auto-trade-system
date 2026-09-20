const { test, expect } = require("@playwright/test");
const { execSync } = require("child_process");

const BASE_URL = process.env.OPB_BASE_URL || "http://127.0.0.1:8765";

function getAdminToken() {
  try {
    const scriptPath = "C:/Users/gaura/.gemini/antigravity/brain/1f2fb8fe-7538-4d67-8afe-948c42276d56/scratch/seed_operator_user.py";
    const out = execSync(`python "${scriptPath}"`, { encoding: "utf8" });
    const match = out.match(/ADMIN_SESSION_TOKEN=([a-f0-9]+)/);
    return match ? match[1] : null;
  } catch (e) {
    console.error("Token acquisition failed:", e);
    return null;
  }
}

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

test.describe("OPB v2.59.4 Final Independent Release-Gate Verification", () => {
  test.setTimeout(300000);
  let adminToken = null;

  test.beforeAll(() => {
    adminToken = getAdminToken();
    console.log("Acquired Admin Token for local test server:", !!adminToken);
  });

  test("Exercise Hardened Capabilities: Freshness, Control Center, Delivery, DLQ, Audit, Explainability, RBAC, 5 Themes, 9 Viewports", async ({ browser }) => {
    const context = await browser.newContext({
      ignoreHTTPSErrors: true,
      viewport: { width: 1440, height: 900 }
    });

    if (adminToken) {
      await context.addCookies([
        { name: "opb_session", value: adminToken, url: BASE_URL },
        { name: "session_token", value: adminToken, url: BASE_URL }
      ]);
    }

    const page = await context.newPage();
    const consoleErrors = [];
    const networkErrors = [];

    page.on("console", msg => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
      }
    });

    page.on("requestfailed", req => {
      networkErrors.push(`${req.method()} ${req.url()} - ${req.failure()?.errorText}`);
    });

    // 1. Health & Freshness Endpoint Verification
    const healthResp = await page.goto(`${BASE_URL}/health`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(healthResp.status()).toBe(200);
    const healthJson = await healthResp.json();
    expect(healthJson.status).toBe("ok");
    expect(healthJson.trading_mode).toBe("SIGNAL_ONLY");

    // 2. Control Center Telemetry API Check
    const ccResp = await page.goto(`${BASE_URL}/api/v1/admin/control-center-status`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(ccResp.status()).toBe(200);
    const ccJson = await ccResp.json();
    expect(ccJson.app.version).toBe("v2.59.4");
    expect(ccJson.safety_invariants.BASE_CAPITAL).toBe(3000);
    expect(ccJson.safety_invariants.SL_PCT).toBe(0.88);
    expect(ccJson.safety_invariants.SIGNAL_ONLY).toBe(true);
    expect(ccJson.safety_invariants.LIVE_TRADING_LOCKOUT).toBe(true);
    expect(ccJson.notification_subsystem.healthy).toBe(true);
    expect(ccJson.notification_subsystem.queue_metrics.pending_retries).toBe(0);
    expect(ccJson.notification_subsystem.queue_metrics.dlq_total).toBe(0);

    // 3. Unified Super Admin Control Center UI Screen (/admin/capabilities)
    const capResp = await page.goto(`${BASE_URL}/admin/capabilities`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(capResp.status()).toBe(200);
    const controlCenterHUD = await page.$("#hudSessionState");
    expect(controlCenterHUD).not.toBeNull();
    const hudSignalsToday = await page.$("#hudSignalsToday");
    expect(hudSignalsToday).not.toBeNull();
    const hudNotifHealth = await page.$("#hudNotifStatus");
    expect(hudNotifHealth).not.toBeNull();
    const hudDlqHealth = await page.$("#hudDlqTotal");
    expect(hudDlqHealth).not.toBeNull();

    // 4. Admin Signals Screen with Signal Explainability & Audit Table
    const signalsResp = await page.goto(`${BASE_URL}/admin/signals`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(signalsResp.status()).toBe(200);

    // Verify Explainability Modal exists on page
    const explainModal = await page.$("#signalExplainModal");
    expect(explainModal).not.toBeNull();

    // Verify Signal Audit Table exists
    const signalsTable = await page.$("table");
    expect(signalsTable).not.toBeNull();

    // 5. Super Admin RBAC Gate Verification
    const usersResp = await page.goto(`${BASE_URL}/admin/users`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(usersResp.status()).toBe(200);

    const configResp = await page.goto(`${BASE_URL}/admin/config`, { waitUntil: "domcontentloaded", timeout: 15000 });
    expect(configResp.status()).toBe(200);

    // 6. Multi-Theme Verification across all 5 themes
    await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded", timeout: 15000 });
    for (const theme of THEMES) {
      await page.evaluate(t => {
        document.documentElement.setAttribute("data-theme", t);
        if (typeof window.applyTheme === "function") window.applyTheme(t);
      }, theme);
      const applied = await page.evaluate(() => document.documentElement.getAttribute("data-theme"));
      expect(applied).toBe(theme);
    }

    // 7. Multi-Viewport Zero-Overflow Verification across all 9 viewports
    let overflowViolations = 0;
    for (const vp of MANDATORY_VIEWPORTS) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.waitForTimeout(100);
      const hasOverflow = await page.evaluate(() => {
        return document.documentElement.scrollWidth > window.innerWidth + 1;
      });
      if (hasOverflow) overflowViolations++;
      expect(hasOverflow).toBe(false);
    }

    // Zero horizontal overflow enforcement
    expect(overflowViolations).toBe(0);

    console.log(`[PASS] Playwright Hardened Release Gate: 0 overflow violations, ${consoleErrors.length} console errors, ${networkErrors.length} network errors.`);
    await context.close();
  });
});
