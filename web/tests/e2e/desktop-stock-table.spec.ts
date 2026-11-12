import { test, expect } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";
import { FIXED_NOW, apiKey, loadFixture, settle } from "./helpers/pages";

// #418: at 1440px the Stocks holdings table fits its card with the default columns, including
// Dividends (#396), so nothing needs a sideways scroll. Same demo fixture as the #239 spec.
test.describe("desktop: Stocks holdings table fits at 1440px (#418)", () => {
  test.use({ viewport: { width: 1440, height: 900 } });
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
        return route.fulfill({ status: 404, json: { detail: `not in the fixture: ${key}` } });
      },
    );
    await mockAuthenticatedSession(page);
  });

  test("no sideways scroll, and Δ, P&L, % NW and Dividends are all in view", async ({ page }) => {
    await page.goto("/holdings");
    await settle(page);
    const wrap = page.locator(".stockHoldingsTableWrap");
    await expect(wrap).toBeVisible();
    const m = await wrap.evaluate((el) => ({ scroll: el.scrollWidth, client: el.clientWidth }));
    console.log(`table wrap: scrollWidth ${m.scroll}, clientWidth ${m.client}`);
    expect(m.scroll, `table is ${m.scroll}px in a ${m.client}px card`).toBeLessThanOrEqual(m.client);
    const wrapBox = await wrap.boundingBox();
    for (const name of [/^Δ vs/, /^Profit & Loss/, /^% NW/, /^Dividends/]) {
      const th = page.locator(".stockHoldingsTable thead th").filter({ hasText: name });
      await expect(th).toHaveCount(1);
      const box = await th.boundingBox();
      expect(box && wrapBox && box.x + box.width).toBeLessThanOrEqual((wrapBox?.x ?? 0) + (wrapBox?.width ?? 0) + 1);
    }
  });
});
