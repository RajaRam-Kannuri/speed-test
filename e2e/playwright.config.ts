import { defineConfig, devices } from "@playwright/test";

// End-to-end tests of the LorvenLax UI. They expect the full stack to be running:
// frontend (E2E_BASE_URL), API, worker, and the Acme CRM sample app (E2E_SAMPLE_URL).
// Locally: scripts/dev-services.sh start api worker sample web
export default defineConfig({
  testDir: "tests",
  timeout: 240_000,
  expect: { timeout: 15_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { open: "never" }], ["json", { outputFile: "test-results/results.json" }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
});
