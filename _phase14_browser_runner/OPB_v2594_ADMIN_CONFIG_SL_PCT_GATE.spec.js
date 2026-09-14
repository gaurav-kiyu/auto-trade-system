const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");
const { execSync } = require("child_process");

const BASE_URL = process.env.OPB_BASE_URL || "http://127.0.0.1:8765";

const report = {
  certification: "OPB v2.59.4 Admin Config SL_PCT End-to-End Mutation Gate",
  timestamp: new Date().toISOString(),
  base_url: BASE_URL,
  checks: [],
  console_errors: [],
  page_errors: [],
  request_failures: [],
  server_errors: [],
  client_http_errors: [],
  screenshots: []
};

function record(name, status, detail = "") {
  if (!["PASS", "FAIL", "INFO"].includes(status)) {
    throw new Error(`Invalid certification status: ${status}`);
  }
  report.checks.push({ name, status, detail });
  console.log(`[${status}] ${name}${detail ? " — " + detail : ""}`);
}

function readPersistedConfig() {
  const configPath = path.resolve(__dirname, "..", "json", "config.json");
  const raw = fs.readFileSync(configPath, "utf8");
  return JSON.parse(raw);
}

async function settle(page, ms = 300) {
  await page.waitForTimeout(ms);
}

test("OPB v2.59.4 Admin UI end-to-end configuration mutation - SL_PCT", async ({ browser, page, context }) => {
  test.setTimeout(180000);

  const unexpectedPages = [];
  context.on("page", newPage => {
    unexpectedPages.push(newPage);
  });

  page.on("console", msg => {
    if (msg.type() === "error") {
      report.console_errors.push({
        url: page.url(),
        type: msg.type(),
        text: msg.text(),
        location: msg.location()
      });
    }
  });

  page.on("pageerror", err => {
    report.page_errors.push({
      url: page.url(),
      text: String(err),
      name: err?.name || "",
      stack: err?.stack || ""
    });
  });

  page.on("requestfailed", req => {
    const url = req.url();
    if (!url.startsWith(BASE_URL) && !url.startsWith("http")) return;
    report.request_failures.push({
      url: page.url(),
      method: req.method(),
      request_url: url,
      resource_type: req.resourceType(),
      failure: req.failure()?.errorText || "unknown"
    });
  });

  page.on("response", res => {
    const status = res.status();
    if (status >= 500) {
      report.server_errors.push({
        page_url: page.url(),
        status,
        method: res.request().method(),
        resource_type: res.request().resourceType(),
        url: res.url()
      });
    } else if (status >= 400) {
      report.client_http_errors.push({
        page_url: page.url(),
        status,
        method: res.request().method(),
        resource_type: res.request().resourceType(),
        url: res.url()
      });
    }
  });

  // 1. Authenticate using the existing safe local mechanism
  let envToken = process.env.OPB_SESSION_TOKEN;
  if (!envToken) {
    try {
      const pyScript = "import os, sys; sys.path.insert(0, '..'); from core.auth.handler import AuthHandler; a = AuthHandler(db_path='../db/auth.db'); user = a.get_user('admin'); t = a.create_session(user); print('SESSION_TOKEN=' + t.token)";
      const out = execSync(`python -c "${pyScript}"`, { encoding: "utf8" });
      const m = out.match(/SESSION_TOKEN=([a-f0-9]+)/);
      if (m) envToken = m[1];
    } catch (e) {
      console.warn("Failed to generate local admin session token:", e);
    }
  }

  expect(envToken).toBeTruthy();
  await context.addCookies([
    {
      name: "opb_session",
      value: envToken,
      domain: "127.0.0.1",
      path: "/"
    }
  ]);
  record("Safe local authentication session established", "PASS", `token_prefix=${envToken.slice(0, 8)}...`);

  // 2. Open /admin/config
  const response = await page.goto(`${BASE_URL}/admin/config`, {
    waitUntil: "domcontentloaded",
    timeout: 30000
  });
  await settle(page, 500);

  expect(response).not.toBeNull();
  expect(response.status()).toBe(200);
  expect(page.url()).toBe(`${BASE_URL}/admin/config`);
  record("Admin config page loaded", "PASS", `status=${response.status()}; url=${page.url()}`);

  // Wait for dynamic config rendering
  await page.waitForSelector("#config-execution .config-item", { timeout: 15000 });
  record("Dynamic configuration categories rendered", "PASS");

  // 3. Switch to Risk Engine tab
  const riskTab = page.locator('.tab[data-tab="risk"]');
  await expect(riskTab).toBeVisible({ timeout: 5000 });
  await riskTab.click();
  await settle(page, 200);

  const riskSection = page.locator("#section-risk");
  await expect(riskSection).toHaveClass(/active/);
  record("Switched to Risk Engine tab", "PASS", "tab[data-tab='risk'] clicked; #section-risk active");

  // 4. Locate the actual dynamic SL_PCT cfg-input
  const slInput = page.locator('input.cfg-input[data-key="SL_PCT"]');
  await expect(slInput).toBeVisible({ timeout: 10000 });

  const inputKey = await slInput.getAttribute("data-key");
  const inputType = await slInput.getAttribute("data-type");
  expect(inputKey).toBe("SL_PCT");
  expect(inputType).toBe("number");
  record("Dynamic SL_PCT cfg-input located", "PASS", `data-key=${inputKey}; data-type=${inputType}`);

  // 5. Record its original value
  const initialInputValueStr = await slInput.inputValue();
  const initialInputValue = parseFloat(initialInputValueStr);
  const diskBefore = readPersistedConfig();
  const initialDiskValue = parseFloat(diskBefore.SL_PCT);

  expect(Number.isFinite(initialInputValue)).toBe(true);
  expect(initialInputValue).toBeGreaterThan(0);
  expect(initialInputValue).toBeLessThan(1.0);
  expect(initialInputValue).toBeCloseTo(initialDiskValue, 4);
  record("Original SL_PCT value recorded", "PASS", `ui_value=${initialInputValue}; disk_value=${initialDiskValue}`);

  // 6. Attempt an invalid value such as 1.5
  await slInput.fill("1.5");
  await slInput.dispatchEvent("input");
  await slInput.dispatchEvent("change");
  record("Set invalid SL_PCT value 1.5", "PASS");

  // Set up response listener for /api/config/validate
  const invalidValidatePromise = page.waitForResponse(
    res => res.url().includes("/api/config/validate") && res.request().method() === "POST",
    { timeout: 10000 }
  );

  let applyCalledDuringInvalid = false;
  const applyListener = req => {
    if (req.url().includes("/api/config/apply") && req.method() === "POST") {
      applyCalledDuringInvalid = true;
    }
  };
  page.on("request", applyListener);

  // 7. Invoke the real Save Changes flow
  const saveBtn = page.locator("#saveConfigBtn");
  await expect(saveBtn).toBeVisible();
  await saveBtn.click();

  const invalidValidateRes = await invalidValidatePromise;
  expect(invalidValidateRes.status()).toBe(200);
  const invalidValidateData = await invalidValidateRes.json();

  // 8. Assert validation is rejected
  expect(invalidValidateData.valid).toBe(false);
  expect(Array.isArray(invalidValidateData.errors)).toBe(true);
  expect(invalidValidateData.errors.length).toBeGreaterThan(0);

  const errorMessages = invalidValidateData.errors.map(e => (typeof e === "string" ? e : e.message || JSON.stringify(e)));
  const slErrorFound = errorMessages.some(m => m.includes("SL_PCT") || m.includes("must be in (0, 1)"));
  expect(slErrorFound).toBe(true);
  record("Validation rejected invalid SL_PCT 1.5", "PASS", `errors=${errorMessages.join("; ")}`);

  // Assert /api/config/apply was never invoked
  await settle(page, 500);
  page.off("request", applyListener);
  expect(applyCalledDuringInvalid).toBe(false);
  record("Apply endpoint blocked on validation failure", "PASS", "applyCalled=false");

  // 9. Assert the error is rendered inside the current OPB page as toast/inline/modal, NOT a new window/tab/page
  const errorToast = page.locator("#toastContainer .toast.error");
  await expect(errorToast.first()).toBeVisible({ timeout: 5000 });
  const toastText = await errorToast.first().innerText();
  expect(toastText).toContain("Validation failed");
  expect(toastText).toMatch(/SL_PCT/);
  record("Error rendered inside current page in toast container", "PASS", `toast=${toastText}`);

  // Assert NO navigation away and NO new window/tab
  expect(page.url()).toBe(`${BASE_URL}/admin/config`);
  expect(unexpectedPages.length).toBe(0);
  const bodyText = await page.locator("body").innerText();
  expect(bodyText).toContain("Configuration Cockpit");
  record("No unexpected navigation or external window/tab opened", "PASS", `current_url=${page.url()}; new_pages=${unexpectedPages.length}`);

  // 10. Assert the persisted configuration was NOT changed
  const diskAfterInvalid = readPersistedConfig();
  expect(parseFloat(diskAfterInvalid.SL_PCT)).toBeCloseTo(initialDiskValue, 4);
  record("Persisted configuration unchanged after rejection", "PASS", `persisted_SL_PCT=${diskAfterInvalid.SL_PCT}`);

  // 11. Set a valid test value within canonical range
  // Original is 0.90; test valid value is 0.88 (implied RR = 2.5 >= MIN_NET_RR 1.5)
  const controlledValidValue = Math.abs(initialDiskValue - 0.88) < 0.001 ? 0.85 : 0.88;
  await slInput.fill(String(controlledValidValue));
  await slInput.dispatchEvent("input");
  await slInput.dispatchEvent("change");
  record("Set valid test SL_PCT value within canonical range", "PASS", `test_value=${controlledValidValue}`);

  // Set up listeners for both /api/config/validate and /api/config/apply
  const validValidatePromise = page.waitForResponse(
    res => res.url().includes("/api/config/validate") && res.request().method() === "POST",
    { timeout: 10000 }
  );
  const validApplyPromise = page.waitForResponse(
    res => res.url().includes("/api/config/apply") && res.request().method() === "POST",
    { timeout: 10000 }
  );

  // 12. Execute real Save Changes
  await saveBtn.click();

  // 13. Assert /api/config/validate succeeds
  const validValidateRes = await validValidatePromise;
  expect(validValidateRes.status()).toBe(200);
  const validValidateData = await validValidateRes.json();
  expect(validValidateData.valid).toBe(true);
  expect(validValidateData.errors.length).toBe(0);
  record("Valid configuration validated successfully", "PASS", `valid=true; warnings=${validValidateData.warnings?.length || 0}`);

  // 14. Assert /api/config/apply succeeds
  const validApplyRes = await validApplyPromise;
  expect(validApplyRes.status()).toBe(200);
  const validApplyData = await validApplyRes.json();
  expect(validApplyData.success).toBe(true);
  expect(validApplyData.applied_keys).toContain("SL_PCT");
  record("Valid configuration applied successfully", "PASS", `applied_keys=${validApplyData.applied_keys.join(",")}`);

  // Assert success toast rendered
  const successToast = page.locator("#toastContainer .toast.success");
  await expect(successToast.first()).toBeVisible({ timeout: 5000 });
  record("Success toast rendered", "PASS", await successToast.first().innerText());

  // Verify disk has controlledValidValue
  const diskAfterApply = readPersistedConfig();
  expect(parseFloat(diskAfterApply.SL_PCT)).toBeCloseTo(controlledValidValue, 4);
  record("Persisted configuration updated on disk", "PASS", `persisted_SL_PCT=${diskAfterApply.SL_PCT}`);

  // 15. Execute Reload
  const reloadBtn = page.locator("#reloadBtn");
  await expect(reloadBtn).toBeVisible();

  const reloadPromise = page.waitForResponse(
    res => res.url().endsWith("/api/config") && res.request().method() === "GET",
    { timeout: 10000 }
  );
  await reloadBtn.click();
  const reloadRes = await reloadPromise;
  expect(reloadRes.status()).toBe(200);
  await settle(page, 500);

  // Switch back to risk tab if reload reset active tab
  await riskTab.click();
  await settle(page, 200);

  // 16. Assert the same value is loaded from canonical persisted configuration
  const reloadedInput = page.locator('input.cfg-input[data-key="SL_PCT"]');
  await expect(reloadedInput).toBeVisible({ timeout: 5000 });
  const reloadedVal = parseFloat(await reloadedInput.inputValue());
  expect(reloadedVal).toBeCloseTo(controlledValidValue, 4);
  record("Reload confirmed persisted value re-rendered in UI", "PASS", `reloaded_ui_val=${reloadedVal}`);

  // 17. Restore the exact original SL_PCT value through the same UI save/apply path
  await reloadedInput.fill(String(initialDiskValue));
  await reloadedInput.dispatchEvent("input");
  await reloadedInput.dispatchEvent("change");

  const restoreValidatePromise = page.waitForResponse(
    res => res.url().includes("/api/config/validate") && res.request().method() === "POST",
    { timeout: 10000 }
  );
  const restoreApplyPromise = page.waitForResponse(
    res => res.url().includes("/api/config/apply") && res.request().method() === "POST",
    { timeout: 10000 }
  );

  await saveBtn.click();
  const restoreValidateRes = await restoreValidatePromise;
  expect(restoreValidateRes.status()).toBe(200);
  const restoreValidateData = await restoreValidateRes.json();
  expect(restoreValidateData.valid).toBe(true);

  const restoreApplyRes = await restoreApplyPromise;
  expect(restoreApplyRes.status()).toBe(200);
  const restoreApplyData = await restoreApplyRes.json();
  expect(restoreApplyData.success).toBe(true);
  record("Original SL_PCT value restored via Save Changes", "PASS", `restored_value=${initialDiskValue}`);

  // 18. Reload again and assert the original value is restored
  const finalReloadPromise = page.waitForResponse(
    res => res.url().endsWith("/api/config") && res.request().method() === "GET",
    { timeout: 10000 }
  );
  await reloadBtn.click();
  await finalReloadPromise;
  await settle(page, 500);

  await riskTab.click();
  await settle(page, 200);

  const finalInput = page.locator('input.cfg-input[data-key="SL_PCT"]');
  const finalVal = parseFloat(await finalInput.inputValue());
  expect(finalVal).toBeCloseTo(initialDiskValue, 4);

  const finalDisk = readPersistedConfig();
  expect(parseFloat(finalDisk.SL_PCT)).toBeCloseTo(initialDiskValue, 4);
  record("Final reload verified original value fully restored on disk and in UI", "PASS", `final_ui=${finalVal}; final_disk=${finalDisk.SL_PCT}`);

  // Assert captured runtime health
  expect(report.page_errors.length).toBe(0);
  expect(report.server_errors.length).toBe(0);
  expect(unexpectedPages.length).toBe(0);
  record("Zero runtime page errors or server errors captured", "PASS");

  // Save report artifact
  const artifactsDir = path.join(__dirname, "artifacts", "definitive-ui");
  fs.mkdirSync(artifactsDir, { recursive: true });
  const reportPath = path.join(artifactsDir, "OPB_v2594_ADMIN_CONFIG_SL_PCT_REPORT.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2), "utf8");
  console.log(`Report written to: ${reportPath}`);
});
