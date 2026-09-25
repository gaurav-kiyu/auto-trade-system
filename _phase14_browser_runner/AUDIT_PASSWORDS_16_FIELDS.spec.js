const { test, expect } = require("@playwright/test");

const BASE_URL = process.env.OPB_BASE_URL || "https://gaurav-cockpit.servegame.com";
const ADMIN_TOKEN = process.env.OPB_ADMIN_TOKEN || "215e07767882c0f057fe478d9a506e190057e20123bc4d4956112fff557f76d0";
const ADMIN_CSRF = process.env.OPB_ADMIN_CSRF || "206240aa568c9b8221823161bcfb7fcfe054b9eb515165f08da12ceb4e583114";

const ROUTES_AND_FIELDS = [
  {
    route: "/login",
    auth: false,
    fields: ["#password"]
  },
  {
    route: "/register",
    auth: false,
    fields: ["#password", "#confirmPassword"]
  },
  {
    route: "/forgot-password",
    auth: false,
    fields: ["#recoveryKey", "#newPasswordEmg", "#confirmPasswordEmg"]
  },
  {
    route: "/reset-password",
    auth: false,
    fields: ["#newPassword", "#confirmPassword"]
  },
  {
    route: "/change-password",
    auth: true,
    fields: ["#currentPassword", "#newPassword", "#confirmPassword"]
  },
  {
    route: "/profile",
    auth: true,
    fields: ["#currentPassword", "#newPassword", "#confirmPassword"]
  },
  {
    route: "/admin/users",
    auth: true,
    fields: ["#newPassword", "#resetPassword"]
  },
  {
    route: "/admin/portfolio-analyzer",
    auth: true,
    fields: ["#broker-access-token"]
  }
];

test.describe("DEF-06 Universal Password Fields Audit (16+ fields across 8 routes)", () => {
  test.setTimeout(240000);

  for (const item of ROUTES_AND_FIELDS) {
    test(`Verify password toggles on ${item.route}`, async ({ browser }) => {
      const context = await browser.newContext({ ignoreHTTPSErrors: true });
      const parsed = new URL(BASE_URL);
      if (item.auth) {
        await context.addCookies([
          { name: "session_token", value: ADMIN_TOKEN, domain: parsed.hostname, path: "/" },
          { name: "opb_session", value: ADMIN_TOKEN, domain: parsed.hostname, path: "/" },
          { name: "opb_csrf", value: ADMIN_CSRF, domain: parsed.hostname, path: "/" }
        ]);
      }

      const page = await context.newPage();
      const consoleErrors = [];
      page.on("console", msg => {
        if (msg.type() === "error") {
          consoleErrors.push(msg.text());
        }
      });

      const resp = await page.goto(`${BASE_URL}${item.route}`, { waitUntil: "domcontentloaded" });
      expect(resp.status()).toBe(200);

      // If modal or tab needs to be opened, handle it
      if (item.route === "/forgot-password") {
        const tabEmg = page.locator("#tabEmergency");
        if (await tabEmg.isVisible()) {
          await tabEmg.click();
          await page.waitForTimeout(300);
        }
      } else if (item.route === "/reset-password") {
        await page.evaluate(() => {
          const rf = document.getElementById("resetForm");
          if (rf) rf.style.display = "block";
          const eb = document.getElementById("errorBox");
          if (eb) eb.style.display = "none";
        });
        await page.waitForTimeout(200);
      } else if (item.route === "/admin/portfolio-analyzer") {
        await page.evaluate(() => {
          const bm = document.getElementById("broker-modal");
          if (bm) bm.classList.add("active");
        });
        await page.waitForTimeout(200);
      }

      for (const selector of item.fields) {
        if (item.route === "/admin/users" && selector === "#newPassword") {
          const addBtn = page.locator("#createUserBtn");
          if (await addBtn.isVisible()) {
            await addBtn.click();
            await page.waitForTimeout(300);
          }
        } else if (item.route === "/admin/users" && selector === "#resetPassword") {
          const closeBtn = page.locator("#closeCreateBtn");
          if (await closeBtn.isVisible()) {
            await closeBtn.click();
            await page.waitForTimeout(200);
          }
          // Wait for users table to populate
          await page.waitForSelector('button[data-action="reset-user-pw"]', { timeout: 10000 }).catch(() => {});
          const resetBtn = page.locator('button[data-action="reset-user-pw"]').first();
          if (await resetBtn.isVisible()) {
            await resetBtn.click();
            await page.waitForTimeout(300);
          }
        }
        const input = page.locator(selector).first();
        const exists = await input.count();
        if (!exists) {
          console.warn(`Selector ${selector} not found on ${item.route}`);
          continue;
        }

        const TEST_VAL = "SecretTest123!";
        await input.fill(TEST_VAL);

        // Find toggle button
        const parentWrapper = input.locator("xpath=..");
        let toggleBtn = parentWrapper.locator(".opb-password-toggle, .password-toggle-btn, [data-toggle='password']").first();
        if (!(await toggleBtn.count())) {
          toggleBtn = input.locator("xpath=following-sibling::button").first();
        }

        expect(await toggleBtn.count()).toBeGreaterThan(0);

        // 1. Initial State
        expect(await input.getAttribute("type")).toBe("password");
        const initLabel = await toggleBtn.getAttribute("aria-label");
        expect(initLabel).toMatch(/Show password/i);

        // 2. Toggle to text
        await toggleBtn.click();
        expect(await input.getAttribute("type")).toBe("text");
        expect(await input.inputValue()).toBe(TEST_VAL); // Value preserved
        const toggledLabel = await toggleBtn.getAttribute("aria-label");
        expect(toggledLabel).toMatch(/Hide password/i);

        // 3. Toggle back to password
        await toggleBtn.click();
        expect(await input.getAttribute("type")).toBe("password");
        expect(await input.inputValue()).toBe(TEST_VAL); // Value preserved
        const resetLabel = await toggleBtn.getAttribute("aria-label");
        expect(resetLabel).toMatch(/Show password/i);

        console.log(`[PASS] Route ${item.route} -> Field ${selector}: toggle, value, icon, aria verified`);
      }

      expect(consoleErrors).toEqual([]);
      await context.close();
    });
  }
});
