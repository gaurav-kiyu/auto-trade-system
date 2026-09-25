const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const BASE_URL = process.env.OPB_BASE_URL || "https://gaurav-cockpit.servegame.com";
const ADMIN_TOKEN = process.env.OPB_ADMIN_TOKEN || "215e07767882c0f057fe478d9a506e190057e20123bc4d4956112fff557f76d0";
const ADMIN_CSRF = process.env.OPB_ADMIN_CSRF || "206240aa568c9b8221823161bcfb7fcfe054b9eb515165f08da12ceb4e583114";

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

const PAGES_TO_AUDIT = [
  "/",
  "/profile",
  "/admin/signals",
  "/admin/users",
  "/admin/config",
  "/pricing-plans",
  "/reports",
  "/performance",
  "/options-chain",
  "/payoff-calculator",
  "/trade-journal",
  "/live-pnl",
  "/system-health",
  "/event-store",
  "/ab-tester",
  "/governance",
  "/capacity",
  "/metrics-trend",
  "/data-quality",
  "/observability",
  "/intelligence",
  "/security",
  "/admin/capabilities"
];

const auditResults = {
  timestamp: new Date().toISOString(),
  base_url: BASE_URL,
  total_pages: PAGES_TO_AUDIT.length,
  total_viewports: MANDATORY_VIEWPORTS.length,
  total_combinations: PAGES_TO_AUDIT.length * MANDATORY_VIEWPORTS.length,
  results: [],
  summary: {
    total_audits: 0,
    header_persistent_pass: 0,
    zero_overflow_pass: 0,
    table_horizontal_scroll_pass: 0,
    sticky_th_pass: 0,
    no_overlap_pass: 0,
    no_trap_pass: 0,
    total_tables_checked: 0
  }
};

test.describe("DEF-24 Exhaustive 23 Authenticated Pages × 9 Viewports Audit", () => {
  test.setTimeout(600000);

  test.afterAll(() => {
    const outDir = path.join(__dirname, "artifacts");
    fs.mkdirSync(outDir, { recursive: true });
    const outPath = path.join(outDir, "DEF24_PAGE_VIEWPORT_RESULTS.json");
    fs.writeFileSync(outPath, JSON.stringify(auditResults, null, 2), "utf8");
    console.log(`[SAVED] DEF-24 Page × Viewport results written to ${outPath}`);
  });

  for (const vp of MANDATORY_VIEWPORTS) {
    test(`Viewport ${vp.name} (${vp.width}x${vp.height}) - All 23 Authenticated Pages`, async ({ browser }) => {
      const parsed = new URL(BASE_URL);
      const context = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        ignoreHTTPSErrors: true
      });
      await context.addCookies([
        { name: "session_token", value: ADMIN_TOKEN, domain: parsed.hostname, path: "/" },
        { name: "opb_session", value: ADMIN_TOKEN, domain: parsed.hostname, path: "/" },
        { name: "opb_csrf", value: ADMIN_CSRF, domain: parsed.hostname, path: "/" }
      ]);

      const page = await context.newPage();

      for (const route of PAGES_TO_AUDIT) {
        const consoleErrors = [];
        page.on("console", (msg) => {
          if (msg.type() === "error") consoleErrors.push(msg.text());
        });

        const resp = await page.goto(`${BASE_URL}${route}`, {
          waitUntil: "domcontentloaded",
          timeout: 20000
        }).catch((e) => null);

        await page.waitForTimeout(300);

        const status = resp ? resp.status() : 0;
        expect(status).toBeLessThan(400);

        let domAudit = null;
        for (let attempt = 0; attempt < 2; attempt++) {
          try {
            domAudit = await page.evaluate(() => {
          const isMobile = window.innerWidth < 1024;
          const nav = document.querySelector(isMobile ? ".opb-mobile-appbar" : ".opb-desktop-nav");
          const docEl = document.documentElement;
          const bodyEl = document.body;
          const scrollW = Math.max(docEl.scrollWidth, bodyEl.scrollWidth);
          const clientW = Math.min(docEl.clientWidth, window.innerWidth);
          const overflowPixels = Math.max(0, scrollW - clientW);
          const hasHorizontalOverflow = overflowPixels > 1.5;

          // Header initial state
          let navPosition = "none";
          let navZIndex = "auto";
          let initialRect = null;
          if (nav) {
            const cs = window.getComputedStyle(nav);
            navPosition = cs.position;
            navZIndex = cs.zIndex;
            const r = nav.getBoundingClientRect();
            initialRect = { top: r.top, bottom: r.bottom, height: r.height, width: r.width };
          }

          // Test vertical scroll & header persistence
          const docHeight = Math.max(docEl.scrollHeight, bodyEl.scrollHeight);
          const winHeight = window.innerHeight;
          let isHeaderVisibleAfterScroll = true;
          let scrolledRect = null;

          if (docHeight > winHeight + 100) {
            window.scrollTo(0, 400);
            if (nav) {
              const r = nav.getBoundingClientRect();
              scrolledRect = { top: r.top, bottom: r.bottom, height: r.height, width: r.width };
              isHeaderVisibleAfterScroll = (r.bottom > 0 && r.top < window.innerHeight);
            }
            window.scrollTo(0, 0); // scroll back
          }

          // Tables audit
          const tables = Array.from(document.querySelectorAll("table"));
          const tableDetails = tables.map((t, idx) => {
            const parent = t.parentElement;
            const parentCs = window.getComputedStyle(parent);
            const ths = Array.from(t.querySelectorAll("thead th, th"));
            const firstTh = ths[0];
            let thPos = "static";
            let thBg = "transparent";
            if (firstTh) {
              const thCs = window.getComputedStyle(firstTh);
              thPos = thCs.position;
              thBg = thCs.backgroundColor;
            }

            const hasHorizontalScroll = (parentCs.overflowX === "auto" || parentCs.overflowX === "scroll" || t.offsetWidth <= parent.offsetWidth + 2);
            const isThSticky = (thPos === "sticky" || parentCs.overflowY === "auto" || parentCs.overflowY === "scroll");

            return {
              index: idx,
              tableWidth: t.offsetWidth,
              parentWidth: parent.offsetWidth,
              parentOverflowX: parentCs.overflowX,
              parentOverflowY: parentCs.overflowY,
              thPosition: thPos,
              thBackground: thBg,
              hasHorizontalScrollContainer: hasHorizontalScroll,
              isStickyTh: isThSticky
            };
          });

          // Check overlap with first content container
          const contentArea = document.querySelector(".card, .opb-card, main, .container, .dashboard-container, #app, .content");
          let hasContentOverlap = false;
          if (nav && contentArea) {
            const navR = nav.getBoundingClientRect();
            const contR = contentArea.getBoundingClientRect();
            // If content top is behind nav top without offset/padding
            if (navPosition === "fixed" && contR.top < navR.bottom) {
              hasContentOverlap = true;
            }
          }

          // Check double scroll trap (elements with height 100vh and nested overflow-y without scrollbar)
          const scrollTraps = Array.from(document.querySelectorAll("[style*='overflow'], div")).filter(el => {
            const cs = window.getComputedStyle(el);
            return (cs.overflowY === "hidden" && el.scrollHeight > el.clientHeight && el.clientHeight > 400 && el !== docEl && el !== bodyEl);
          }).length;

          return {
            navFound: !!nav,
            navPosition,
            navZIndex,
            initialRect,
            scrolledRect,
            isHeaderVisibleAfterScroll,
            scrollW,
            clientW,
            overflowPixels,
            hasHorizontalOverflow,
            tablesCount: tables.length,
            tableDetails,
            hasContentOverlap,
            scrollTrapsCount: scrollTraps,
            docHeight,
            winHeight
          };
        });
        break;
      } catch (evalErr) {
        if (attempt === 1) throw evalErr;
        await page.waitForTimeout(500);
      }
    }

        // Record entry
        const entry = {
          viewport: vp.name,
          width: vp.width,
          height: vp.height,
          route,
          status,
          header_persistent: domAudit.isHeaderVisibleAfterScroll,
          zero_overflow: !domAudit.hasHorizontalOverflow,
          overflow_pixels: domAudit.overflowPixels,
          tables_count: domAudit.tablesCount,
          tables_scroll_ok: domAudit.tableDetails.every(t => t.hasHorizontalScrollContainer),
          sticky_th_ok: domAudit.tableDetails.every(t => t.isStickyTh),
          no_overlap: !domAudit.hasContentOverlap,
          no_scroll_traps: domAudit.scrollTrapsCount === 0,
          details: domAudit
        };

        auditResults.results.push(entry);
        auditResults.summary.total_audits++;
        if (entry.header_persistent) auditResults.summary.header_persistent_pass++;
        if (entry.zero_overflow) auditResults.summary.zero_overflow_pass++;
        if (entry.tables_scroll_ok) auditResults.summary.table_horizontal_scroll_pass++;
        if (entry.sticky_th_ok) auditResults.summary.sticky_th_pass++;
        if (entry.no_overlap) auditResults.summary.no_overlap_pass++;
        if (entry.no_scroll_traps) auditResults.summary.no_trap_pass++;
        auditResults.summary.total_tables_checked += domAudit.tablesCount;

        console.log(`[${vp.name}] ${route.padEnd(22)} | Status: ${status} | HdrVisible: ${entry.header_persistent} | ZeroOverflow: ${entry.zero_overflow} (px: ${entry.overflow_pixels.toFixed(1)}) | Tables: ${domAudit.tablesCount}`);
      }

      await context.close();
    });
  }
});
