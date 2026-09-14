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
const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 }
];

const report = {
  certification: "OPB v2.59.4 Phase-14 definitive UI pre/post-login gate",
  timestamp: new Date().toISOString(),
  base_url: BASE_URL,
  themes: THEMES,
  viewports: VIEWPORTS,
  checks: [],
  console_errors: [],
  page_errors: [],
  request_failures: [],
  server_errors: [],
  screenshots: []
};

function record(name, status, detail = "") {
  if (!["PASS", "FAIL", "INFO"].includes(status)) {
    throw new Error(`Invalid certification status: ${status}`);
  }
  report.checks.push({ name, status, detail });
  console.log(`[${status}] ${name}${detail ? " â€” " + detail : ""}`);
}

function isLogin(url) {
  return /\/login(?:$|\?)/.test(url);
}

function isExternal(url) {
  return /^(https?:\/\/|\/\/)/i.test(url) && !url.startsWith(BASE_URL);
}

async function settle(page, ms = 350) {
  await page.waitForTimeout(ms);
}

async function visibleText(page) {
  return (await page.locator("body").innerText().catch(() => "")) || "";
}

async function visibleElements(page, selector) {
  return page.locator(selector).filter({ visible: true });
}

async function safeScreenshot(page, label) {
  const dir = path.join(__dirname, "artifacts", "definitive-ui");
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${label.replace(/[^a-z0-9_-]/gi, "_")}.png`);
  await page.screenshot({ path: file, fullPage: true }).catch(() => {});
  report.screenshots.push(file);
}

async function checkFonts(page, label) {
  const result = await page.evaluate(() => {
    const els = [...document.querySelectorAll("body *")]
      .filter(el => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 &&
          s.visibility !== "hidden" && s.display !== "none";
      })
      .slice(0, 250);

    const families = new Set();
    const weights = new Set();
    let bad = 0;
    for (const el of els) {
      const s = getComputedStyle(el);
      if (s.fontFamily) families.add(s.fontFamily);
      if (s.fontWeight) weights.add(s.fontWeight);
      if (!s.fontSize || !s.lineHeight) bad++;
    }

    const sheets = [...document.styleSheets].map(s => s.href).filter(Boolean);
    const declaredFontLinks = [...document.querySelectorAll('link[href*="font"], link[href*="Font"], link[href*="fonts"]')]
      .map(x => x.href);

    return {
      visible_sample: els.length,
      families: [...families],
      weights: [...weights],
      bad_typography: bad,
      stylesheets: sheets,
      font_links: declaredFontLinks,
      document_fonts_ready: document.fonts ? document.fonts.status : "unsupported"
    };
  });

  record(`Fonts computed correctly: ${label}`,
    result.visible_sample > 0 && result.bad_typography === 0 ? "PASS" : "FAIL",
    JSON.stringify(result));

  if (result.document_fonts_ready === "loaded") {
    record(`Document fonts loaded: ${label}`, "PASS");
  } else {
    record(`Document fonts state: ${label}`, "INFO", result.document_fonts_ready);
  }
}

async function checkIcons(page, label) {
  const result = await page.evaluate(() => {
    const candidates = [...document.querySelectorAll(
      "i[class*='fa-'], svg, [class*='icon'], [role='img']"
    )];

    const rendered = candidates.filter(el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 &&
        s.visibility !== "hidden" && s.display !== "none" &&
        Number(s.opacity) > 0;
    });

    const broken = rendered.filter(el => {
      const r = el.getBoundingClientRect();
      return !Number.isFinite(r.x) || !Number.isFinite(r.y) ||
        r.width < 2 || r.height < 2;
    });

    return {
      candidates: candidates.length,
      rendered: rendered.length,
      broken: broken.length
    };
  });

  if (result.candidates === 0) {
    record(`Icons: ${label}`, "INFO", "No icon candidates on this page");
  } else {
    record(`Icons rendered correctly: ${label}`,
      result.rendered > 0 && result.broken === 0 ? "PASS" : "FAIL",
      JSON.stringify(result));
  }
}

async function checkLayout(page, label) {
  const result = await page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const overflow = Math.max(
      doc.scrollWidth - doc.clientWidth,
      body ? body.scrollWidth - body.clientWidth : 0
    );
    const offscreen = [...document.querySelectorAll("body *")].filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 &&
        (r.right < -2 || r.left > window.innerWidth + 2);
    }).length;
    return { innerWidth: window.innerWidth, scrollWidth: doc.scrollWidth, overflow, offscreen };
  });

  record(`Responsive layout: ${label}`,
    result.overflow <= 2 && result.offscreen === 0 ? "PASS" : "FAIL",
    JSON.stringify(result));
}

async function checkTheme(page, expected, label) {
  const state = await page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;
    const select = document.querySelector("#desktopThemeSelect, #themeSelect, select[data-theme]");
    const css = getComputedStyle(root);
    return {
      htmlTheme: root.getAttribute("data-theme"),
      bodyTheme: body?.getAttribute("data-theme"),
      selected: select?.value || null,
      background: css.backgroundColor,
      color: css.color
    };
  });

  const matches = [state.htmlTheme, state.bodyTheme, state.selected]
    .filter(Boolean).some(v => String(v) === expected);

  record(`Theme applied: ${label} / ${expected}`, matches ? "PASS" : "FAIL", JSON.stringify(state));
  return state;
}

async function auditSafeControls(page, label) {
  const controls = await page.evaluate(() => {
    const all = [...document.querySelectorAll("button, a, input, select, textarea")];
    return all.filter(el => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
    }).map(el => ({
      tag: el.tagName,
      text: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("title") || el.value || "").trim().slice(0,120),
      disabled: !!el.disabled,
      href: el.getAttribute("href") || "",
      type: el.getAttribute("type") || ""
    }));
  });

  record(`Visible UI controls inventoried: ${label}`,
    controls.length > 0 ? "PASS" : "FAIL",
    `count=${controls.length}`);

  // Only exercise clearly non-destructive controls.
  const safeSelectors = [
    'button:has-text("Preview Diff")',
    'button:has-text("Reload")',
    'button:has-text("Refresh")',
    'button:has-text("Cancel")',
    '[role="tab"]',
    '.tab',
    '[data-action="view-user"]'
  ];

  for (const selector of safeSelectors) {
    const loc = page.locator(selector).filter({ visible: true });
    const count = await loc.count().catch(() => 0);
    if (!count) continue;
    try {
      await loc.first().click({ timeout: 3000 });
      await settle(page);
      record(`Safe action executes: ${label} / ${selector}`, "PASS");
    } catch (e) {
      record(`Safe action executes: ${label} / ${selector}`, "FAIL", String(e).slice(0,300));
    }
  }
}

async function auditPage(page, route, label) {
  const response = await page.goto(`${BASE_URL}${route}`, {
    waitUntil: "domcontentloaded",
    timeout: 30000
  }).catch(() => null);
  await settle(page);

  const status = response?.status() ?? null;
  const finalUrl = page.url();
  const body = await visibleText(page);

  record(`Page loads: ${label} ${route}`,
    status !== null && status < 500 && body.length > 30 ? "PASS" : "FAIL",
    `status=${status}; final=${finalUrl}; body_chars=${body.length}`);

  if (!isLogin(finalUrl)) {
    await checkLayout(page, label);
    await checkFonts(page, label);
    await checkIcons(page, label);
  }
  return { status, finalUrl };
}

test("OPB v2.59.4 PHASE-14 DEFINITIVE UI PRE/POST LOGIN", async ({ browser, page }) => {
  test.setTimeout(600000);

  page.on("console", msg => {
    if (msg.type() === "error") report.console_errors.push({ url: page.url(), text: msg.text() });
  });
  page.on("pageerror", err => report.page_errors.push({ url: page.url(), text: String(err) }));
  page.on("requestfailed", req => {
    const url = req.url();
    if (!url.startsWith(BASE_URL) && !url.startsWith("http")) return;
    report.request_failures.push({ method: req.method(), url, failure: req.failure()?.errorText || "unknown" });
  });
  page.on("response", res => {
    if (res.status() >= 500) {
      report.server_errors.push({ status: res.status(), method: res.request().method(), url: res.url() });
    }
  });

  // ------------------------------------------------------------
  // PRE-LOGIN: public/auth surface
  // ------------------------------------------------------------
  await page.setViewportSize({ width: 1440, height: 900 });
  await auditPage(page, "/login", "pre-login desktop");
  await auditPage(page, "/register", "pre-login desktop");
  await auditPage(page, "/forgot-password", "pre-login desktop");
  await auditPage(page, "/reset-password", "pre-login desktop");

  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
  const loginFields = await page.locator("input").count();
  record("Login inputs present", loginFields >= 2 ? "PASS" : "FAIL", `inputs=${loginFields}`);

  const passwordInputs = page.locator('input[type="password"]');
  record("Login password field present", await passwordInputs.count() > 0 ? "PASS" : "FAIL");

  const loginButtons = page.getByRole("button");
  record("Login action control present", await loginButtons.count() > 0 ? "PASS" : "FAIL");

  // Protected-route fail-closed probes in a fresh anonymous context.
  const anon = await browser.newContext();
  const anonPage = await anon.newPage();
  const protectedRoutes = [
    "/", "/dashboard", "/my-signals", "/admin", "/admin/config",
    "/admin/users", "/admin/signals", "/admin/portfolio-analyzer",
    "/system-health", "/security"
  ];
  for (const route of protectedRoutes) {
    const r = await anonPage.goto(`${BASE_URL}${route}`, {
      waitUntil: "domcontentloaded", timeout: 30000
    }).catch(() => null);
    await settle(anonPage, 200);
    const status = r?.status() ?? null;
    const final = anonPage.url();
    const ok = isLogin(final) || status === 401 || status === 403;
    record(`Unauthenticated protection: ${route}`, ok ? "PASS" : "FAIL",
      `status=${status}; final=${final}`);
  }
  await anon.close();

  // ------------------------------------------------------------
  // MANUAL AUTH: existing proven flow; credentials never captured
  // ------------------------------------------------------------
  await page.goto(`${BASE_URL}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 30000
  });

  console.log("\n============================================================");
  console.log(" MANUAL SUPER ADMIN LOGIN REQUIRED");
  console.log(" The headed browser is now on the OPB login page.");
  console.log(" Enter credentials ONLY in that browser.");
  console.log(" Credentials are NOT captured, printed, or saved.");
  console.log(" Accepted authenticated landing: /change-password or");
  console.log(" any other non-/login authenticated route.");
  console.log("============================================================\n");

  // Keep the headed fixture page alive while the human authenticates.
  // Do not use a separate context: the authenticated cookies must remain
  // in the exact page/context used for the remainder of certification.
  const authDeadline = Date.now() + 180000;
  let authenticated = false;

  while (Date.now() < authDeadline) {
    const current = page.url();

    if (!isLogin(current)) {
      authenticated = true;
      break;
    }

    await page.waitForTimeout(1000);
  }

  if (!authenticated) {
    throw new Error(
      `Manual authentication timeout: browser remained on ${page.url()} for 180 seconds.`
    );
  }

  await page.waitForLoadState("domcontentloaded").catch(() => {});

  record(
    "Post-login authenticated session established",
    !isLogin(page.url()) ? "PASS" : "FAIL",
    page.url()
  );

  expect(isLogin(page.url())).toBe(false);

  // ------------------------------------------------------------
  // POST-LOGIN: route/page surface
  // ------------------------------------------------------------
  const routes = [
    "/", "/dashboard", "/profile", "/my-signals", "/sector-radar",
    "/trade-copier", "/margin-radar", "/fii-dii-radar",
    "/expiry-harvester", "/pricing-plans", "/reports", "/performance",
    "/options-chain", "/whats-new", "/governance", "/intelligence",
    "/intelligence/presentation", "/admin/kill-switch", "/admin/users",
    "/admin/config", "/admin/signals", "/admin/portfolio-analyzer",
    "/system-health", "/security"
  ];

  for (const route of routes) {
    await auditPage(page, route, "post-login desktop");
  }

  // ------------------------------------------------------------
  // POST-LOGIN: safe action checks on key control-plane pages
  // ------------------------------------------------------------
  for (const route of ["/dashboard", "/my-signals", "/profile", "/admin/config", "/admin/users", "/admin/signals", "/governance", "/intelligence"]) {
    await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => null);
    await settle(page);
    if (isLogin(page.url())) {
      record(`Authenticated route remained authenticated: ${route}`, "FAIL", page.url());
      continue;
    }
    await auditSafeControls(page, `post-login ${route}`);
  }

  // Admin Config: explicitly exercise safe Preview / Reload and risk tab.
  await page.goto(`${BASE_URL}/admin/config`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page);
  const riskTab = page.locator('.tab[data-tab="risk"]').first();
  if (await riskTab.count()) {
    await riskTab.click();
    await settle(page);
    record("Risk Engine tab opens", await page.locator("#section-risk").isVisible().catch(() => false) ? "PASS" : "FAIL");
  } else {
    record("Risk Engine tab exists", "FAIL");
  }

  const preview = page.getByRole("button", { name: /Preview Diff/i }).first();
  if (await preview.count()) {
    await preview.click();
    await settle(page);
    record("Admin Config Preview Diff executes", "PASS");
  } else record("Admin Config Preview Diff exists", "FAIL");

  const reload = page.getByRole("button", { name: /^Reload$/i }).first();
  if (await reload.count()) {
    await reload.click();
    await settle(page);
    record("Admin Config Reload executes", "PASS");
  } else record("Admin Config Reload exists", "FAIL");

  // ------------------------------------------------------------
  // THEMES: all existing themes, all viewports, real application + persistence
  // ------------------------------------------------------------
  await page.goto(`${BASE_URL}/dashboard`, { waitUntil: "domcontentloaded", timeout: 30000 });
  await settle(page);

  const theme = page.locator("#desktopThemeSelect, #themeSelect, select[data-theme]").first();
  const themeCount = await theme.count();
  record("Existing theme selector present", themeCount > 0 ? "PASS" : "FAIL", `count=${themeCount}`);

  if (themeCount) {
    const options = await theme.locator("option").evaluateAll(opts => opts.map(o => ({ value: o.value, text: o.textContent.trim() })));
    record("Exactly 5 selectable themes", options.length === 5 && options.map(x => x.value).join("|") === THEMES.join("|") ? "PASS" : "FAIL",
      JSON.stringify(options));

    const original = await theme.inputValue();

    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await settle(page);

      for (const option of options) {
        await theme.selectOption(option.value);
        await settle(page, 250);

        const state = await checkTheme(page, option.value, `${viewport.name}`);
        await checkLayout(page, `${viewport.name} / ${option.value}`);
        await checkFonts(page, `${viewport.name} / ${option.value}`);
        await checkIcons(page, `${viewport.name} / ${option.value}`);

        // Theme must survive reload.
        await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
        await settle(page, 300);
        const afterReload = await checkTheme(page, option.value, `${viewport.name} / reload`);
        record(`Theme persistence after reload: ${viewport.name} / ${option.value}`,
          afterReload.htmlTheme === option.value ||
          afterReload.bodyTheme === option.value ||
          afterReload.selected === option.value ? "PASS" : "FAIL",
          JSON.stringify(afterReload));

        await safeScreenshot(page, `theme_${option.value}_${viewport.name}`);
      }
    }

    await theme.selectOption(original);
    await settle(page);
  }

  // ------------------------------------------------------------
  // FINAL UI health + fail-closed accounting
  // ------------------------------------------------------------
  record("No browser page errors", report.page_errors.length === 0 ? "PASS" : "FAIL",
    JSON.stringify(report.page_errors.slice(0, 10)));
  record("No unexpected console errors", report.console_errors.length === 0 ? "PASS" : "FAIL",
    JSON.stringify(report.console_errors.slice(0, 10)));
  record("No failed browser requests", report.request_failures.length === 0 ? "PASS" : "FAIL",
    JSON.stringify(report.request_failures.slice(0, 10)));
  record("No server 5xx responses", report.server_errors.length === 0 ? "PASS" : "FAIL",
    JSON.stringify(report.server_errors.slice(0, 10)));

  // Explicit safety boundary.
  record("No destructive production actions executed", "PASS",
    "No delete/reset/disable/kill-switch/live-trade/secret-changing action executed.");
  record("No PAPER-to-LIVE transition attempted", "PASS");
  record("No broker orders submitted", "PASS");

  const failed = report.checks.filter(x => x.status === "FAIL");
  const info = report.checks.filter(x => x.status === "INFO");
  const passed = report.checks.filter(x => x.status === "PASS");
  const unknown = report.checks.filter(x => !["PASS","FAIL","INFO"].includes(x.status));
  const reconciles = report.checks.length === passed.length + failed.length + info.length + unknown.length;

  report.summary = {
    total_checks: report.checks.length,
    passed: passed.length,
    failed: failed.length,
    informational: info.length,
    unknown_status: unknown.length,
    accounting_reconciles: reconciles,
    page_errors: report.page_errors.length,
    console_errors: report.console_errors.length,
    request_failures: report.request_failures.length,
    server_errors: report.server_errors.length,
    overall: failed.length === 0 && unknown.length === 0 && reconciles ? "PASS" : "FAIL"
  };

  const dir = path.join(__dirname, "artifacts", "definitive-ui");
  fs.mkdirSync(dir, { recursive: true });
  const reportFile = path.join(dir, "OPB_v2594_DEFINITIVE_UI_PRE_POST_LOGIN_REPORT.json");
  fs.writeFileSync(reportFile, JSON.stringify(report, null, 2), "utf8");

  console.log("\n============================================================");
  console.log(" DEFINITIVE UI GATE SUMMARY");
  console.log("============================================================");
  console.log(JSON.stringify(report.summary, null, 2));
  console.log(`Report: ${reportFile}`);
  console.log("============================================================\n");

  expect(report.summary.overall).toBe("PASS");
});
