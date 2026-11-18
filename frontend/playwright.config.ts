import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    ["json", { outputFile: "../artifacts/playwright.json" }],
  ],
  use: {
    baseURL: "http://localhost:3000",
    viewport: { width: 1536, height: 1024 },
    trace: "retain-on-failure",
  },
  outputDir: "../artifacts/browser",
});
