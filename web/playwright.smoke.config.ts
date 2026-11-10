import { defineConfig, devices } from "@playwright/test";

// Full-stack smoke and screenshot diffs (#73). Run through scripts/e2e-smoke.sh (`make e2e-smoke`,
// `make e2e-smoke-update`), which starts a throwaway Postgres + API + web container with the demo
// seed and runs this inside the pinned Playwright image (tools/Dockerfile), so screenshots render
// the same on a Mac and in CI. Not part of `make e2e` (playwright.config.ts, mocked specs only).
export default defineConfig({
  testDir: "./tests/smoke",
  outputDir: "./test-results/smoke",
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",
  timeout: 60_000,
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report/smoke", open: "never" }]],
  expect: {
    toHaveScreenshot: {
      // Anti-aliasing noise only; a moved card, a changed label or a broken chart is far more.
      maxDiffPixelRatio: 0.002,
      animations: "disabled",
      caret: "hide",
      scale: "css",
    },
  },
  use: {
    ...devices["Desktop Chrome"],
    // nginx in the web container (docker-compose.smoke.yml), over IPv4 (it doesn't listen on ::1);
    // it answers only Host localhost / 127.0.0.1 / *.ts.net.
    baseURL: process.env.SMOKE_BASE_URL ?? "http://127.0.0.1:8080",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "live", testMatch: /live\.spec\.ts$/ },
    { name: "screens", testMatch: /screens\.spec\.ts$/ },
    { name: "routes", testMatch: /routes\.spec\.ts$/ },
    // `make e2e-smoke-record` only (E2E_RECORD_FROM set): re-record the demo API fixture.
    { name: "record", testDir: "./tests/e2e", testMatch: /mobile-no-overflow\.spec\.ts$/ },
  ],
});
