import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [["list"], ["json", { outputFile: "../reports/_card_visibility.json" }]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    headless: true,
    trace: "off",
    screenshot: "off",
  },
  // Vite is already expected to be running on :5173 (DoR harness).
});
