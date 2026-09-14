const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: ".",
  timeout: 600000,
  use: {
    baseURL: process.env.OPB_BASE_URL || "http://127.0.0.1:8765",
    headless: false,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure"
  },
  workers: 1
});
