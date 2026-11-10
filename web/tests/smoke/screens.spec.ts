import { test, expect } from "@playwright/test";
import { mockAuthenticatedSession } from "../e2e/helpers/auth";
import { FIXED_NOW, apiKey, loadFixture, settle } from "../e2e/helpers/pages";
import { SMOKE_ROUTES, VIEWPORTS, routeSlug } from "./smoke";

// #73 part 2: screenshot diffs. Every page at phone and desktop width, compared with the
// committed baseline in __screenshots__/. The data must not move, so the API answers come from
// the recorded demo fixture (tests/e2e/fixtures/demo-api.json) with the clock frozen at its
// recording time; only the page code under test changes. The browser runs in the pinned
// Playwright image, so fonts and anti-aliasing match on a Mac and in CI.
//
// A visual change fails with expected / actual / diff images (CI uploads them). If the change is
// intended: `make e2e-smoke-update`, look at the new PNGs, commit them with the change.
// An API call the fixture doesn't have fails too: re-record it (see mobile-no-overflow.spec.ts).

const fixture = loadFixture();
/** The current test's API calls the fixture couldn't answer (a worker runs one test at a time). */
let missing: string[] = [];

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.name} screenshots`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test.beforeEach(async ({ page, baseURL }) => {
      await page.clock.setFixedTime(FIXED_NOW);
      const origin = new URL(baseURL ?? "http://127.0.0.1:8080").origin;
      missing = [];
      await page.route(
        () => true,
        async (route) => {
          const key = apiKey(route.request(), origin);
          if (key === null) return route.fallback();
          const hit = route.request().method() === "GET" ? fixture[key] : undefined;
          if (hit) return route.fulfill({ status: hit.status, json: hit.body });
          missing.push(`${route.request().method()} ${key}`);
          return route.fulfill({ status: 404, json: { detail: `not in the demo fixture: ${key}` } });
        },
      );
      await mockAuthenticatedSession(page);
    });

    for (const route of SMOKE_ROUTES) {
      test(route, async ({ page }) => {
        await page.goto(route);
        await settle(page);
        await page.evaluate(() => document.fonts.ready);
        expect(missing, "API calls missing from tests/e2e/fixtures/demo-api.json: re-record it").toEqual([]);
        await expect(page).toHaveScreenshot(`${viewport.name}-${routeSlug(route)}.png`, { fullPage: true });
      });
    }
  });
}
