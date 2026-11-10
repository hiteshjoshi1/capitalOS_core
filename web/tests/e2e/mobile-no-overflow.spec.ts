import { test, expect } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { mockAuthenticatedSession } from "./helpers/auth";
import { FIXED_NOW, FIXTURE_PATH, MAIN_ROUTES, apiKey, loadFixture, measure, settle, type Fixture } from "./helpers/pages";

// #239: no page may be wider than a 375px phone. Every main route is opened at 375px and
// must not scroll sideways. `html, body { overflow-x: hidden }` (App.css) clips the root,
// so document.documentElement.scrollWidth alone always reads 375. A row that is too wide
// shows up instead in body.scrollWidth (the top bar) or in #main-content's (the page: it
// is a scroll container), so all three are checked.
//
// The API answers come from fixtures/demo-api.json: GET responses recorded from the demo
// seed (`make db-seed-demo`, synthetic data only) with the clock fixed at FIXED_NOW, so the
// month the pages ask for matches the recording. A request not in the fixture gets a 404,
// never a real API.
//
// Re-record (after an API shape change, or when a page calls a new endpoint):
//   make e2e-smoke-record
// (#73: a throwaway stack with the demo seed, scripts/e2e-smoke.sh). Or against a worktree
// stack with demo data:
//   E2E_RECORD_FROM=http://localhost:<worktree web port> npx playwright test mobile-no-overflow
// That run logs in as demo/Test@1234, measures the same routes on live demo data, and rewrites
// the fixture.

const VIEWPORT = { width: 375, height: 812 };
// Routes, clock, fixture and the measuring live in helpers/pages.ts, shared with tests/smoke (#73).
const MOBILE_ROUTES = MAIN_ROUTES;
const RECORD_FROM = process.env.E2E_RECORD_FROM?.replace(/\/+$/, "");

test.describe("mobile: no page wider than 375px (#239)", () => {
  test.use({ viewport: VIEWPORT });

  if (RECORD_FROM) {
    test("record demo fixtures and measure live demo data", async ({ page }) => {
      test.setTimeout(240_000);
      const recorded: Fixture = {};
      const origin = new URL(RECORD_FROM).origin;
      page.on("response", async (response) => {
        const request = response.request();
        if (request.method() !== "GET") return;
        const key = apiKey(request, origin);
        // Session calls are mocked (helpers/auth.ts); /auth/preferences is page data, so it's kept.
        if (!key || /^\/auth\/(refresh|login|logout|me)\b/.test(key)) return;
        try {
          recorded[key] = { status: response.status(), body: await response.json() };
        } catch {
          // Not JSON (e.g. a CSV download): not needed for layout.
        }
      });
      await page.clock.setFixedTime(FIXED_NOW);
      await page.goto(`${RECORD_FROM}/login`);
      await page.getByLabel("Username").fill("demo");
      await page.getByLabel("Password").fill("Test@1234");
      await page.getByRole("button", { name: "Sign In" }).click();
      await page.waitForURL(/\/wealth/);
      const failures: string[] = [];
      for (const route of MOBILE_ROUTES) {
        await page.goto(`${RECORD_FROM}${route}`);
        await settle(page);
        const m = await measure(page);
        console.log(`${route}: ${m.widest}px`);
        if (m.widest > m.vw) failures.push(`${route}: ${m.widest}px > ${m.vw}px — ${m.offenders.join(", ")}`);
      }
      // The screenshot diffs (tests/smoke, #73) also open every page at desktop width, which
      // can ask for more (e.g. sidebar counts): record those answers too.
      await page.setViewportSize({ width: 1440, height: 900 });
      for (const route of MOBILE_ROUTES) {
        await page.goto(`${RECORD_FROM}${route}`);
        await settle(page);
      }
      const sorted = Object.fromEntries(Object.entries(recorded).sort(([a], [b]) => a.localeCompare(b)));
      writeFileSync(FIXTURE_PATH, `${JSON.stringify(sorted, null, 1)}\n`);
      expect(failures).toEqual([]);
    });
    return;
  }

  const fixture = loadFixture();

  test.beforeEach(async ({ page, baseURL }) => {
    await page.clock.setFixedTime(FIXED_NOW);
    const origin = new URL(baseURL ?? "http://127.0.0.1:4173").origin;
    await page.route(
      () => true,
      async (route) => {
        const key = apiKey(route.request(), origin);
        if (key === null) return route.fallback();
        const hit = route.request().method() === "GET" ? fixture[key] : undefined;
        if (hit) return route.fulfill({ status: hit.status, json: hit.body });
        return route.fulfill({ status: 404, json: { detail: `not in the #239 fixture: ${key}` } });
      },
    );
    // Registered after the catch-all, so these win for /auth/*.
    await mockAuthenticatedSession(page);
  });

  for (const route of MOBILE_ROUTES) {
    test(`${route} fits 375px`, async ({ page }) => {
      await page.goto(route);
      await settle(page);
      const m = await measure(page);
      expect(m.widest, `${route} is ${m.widest}px wide: ${m.offenders.join(", ")}`).toBeLessThanOrEqual(m.vw);
    });
  }

  test("the header keeps the account menu on screen and the month pill in the page", async ({ page }) => {
    await page.goto("/holdings");
    await settle(page);
    const account = page.locator(".appShellUserPill");
    await expect(account).toBeVisible();
    const box = await account.boundingBox();
    expect(box && box.x + box.width).toBeLessThanOrEqual(VIEWPORT.width);
    await expect(page.getByLabel("Month", { exact: true })).toHaveCount(1);
    await expect(page.locator(".appShellTopbar").getByLabel("Month", { exact: true })).toHaveCount(0);
  });

  test("the Overview shows the Liabilities card and the bottom nav says Flow", async ({ page }) => {
    await page.goto("/wealth");
    await settle(page);
    const liabilities = page.locator(".coSignalCard", { hasText: "LIABILITIES" });
    await liabilities.scrollIntoViewIfNeeded();
    await expect(liabilities).toBeVisible();
    const box = await liabilities.boundingBox();
    expect(box && box.x + box.width).toBeLessThanOrEqual(VIEWPORT.width);
    const nav = page.getByRole("navigation", { name: "Mobile navigation" });
    await expect(nav.getByRole("link", { name: "Flow" })).toHaveAttribute("href", "/cash-flow");
  });
});
