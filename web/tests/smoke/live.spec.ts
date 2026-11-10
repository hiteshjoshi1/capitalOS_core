import { test, expect, type Page } from "@playwright/test";
import { isFontHost, measure, settle } from "../e2e/helpers/pages";
import { SMOKE_ROUTES, VIEWPORTS, routeSlug } from "./smoke";

// #73 part 1: the real app on demo data. A throwaway Postgres + API + the production web
// container (scripts/e2e-smoke.sh) with the demo seed; sign in as demo and open every page at
// phone and desktop width. A page fails on: an uncaught page error, a console error, an API
// answer of 4xx/5xx, a "Couldn't load" panel, a "Loading…" that never ends, or sideways scroll.
// Each page's screenshot is attached to the report (CI uploads it) for a look, not compared:
// the demo seed is dated from today, so its numbers move. screens.spec.ts does the comparing.
//
// One test per size, pages in turn: a refresh token rotates on every page load, so one signed-in
// browser walks the pages; expect.soft reports every failing page, not just the first.

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("demo");
  await page.getByLabel("Password").fill("Test@1234");
  await page.getByRole("button", { name: "Sign In" }).click();
  // Fail fast with the page's message (e.g. "Server error") instead of the test timeout.
  await page.waitForURL(/\/wealth/, { timeout: 20_000 }).catch(async () => {
    throw new Error(`sign-in failed: ${(await page.locator("main, body").first().innerText()).replace(/\s+/g, " ").slice(0, 200)}`);
  });
}

for (const viewport of VIEWPORTS) {
  test(`every page works on live demo data at ${viewport.name} width`, async ({ page }, testInfo) => {
    test.setTimeout(240_000);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });

    let problems: string[] = [];
    page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
    page.on("console", (message) => {
      if (message.type() !== "error") return;
      const url = message.location().url;
      if (url && isFontHost(new URL(url).hostname)) return;
      // The browser logs every failed request too; those are reported once, below, with the URL.
      if (/^Failed to load resource/.test(message.text())) return;
      problems.push(`console error: ${message.text()}`);
    });
    page.on("response", (response) => {
      const url = new URL(response.url());
      if (!url.pathname.startsWith("/api/") || response.status() < 400) return;
      problems.push(`API ${response.status()}: ${response.request().method()} ${url.pathname}${url.search}`);
    });

    await signIn(page);
    await settle(page);

    for (const route of SMOKE_ROUTES) {
      await test.step(route, async () => {
        problems = [];
        await page.goto(route);
        await settle(page).catch((error: Error) => problems.push(`never finished loading: ${error.message.split("\n")[0]}`));
        const failedPanels = await page.locator(".loadError").allInnerTexts();
        for (const text of failedPanels) problems.push(`"Couldn't load" panel: ${text.replace(/\s+/g, " ").slice(0, 160)}`);
        const m = await measure(page);
        if (m.widest > m.vw) problems.push(`${m.widest}px wide in a ${m.vw}px window: ${m.offenders.join(", ")}`);
        await testInfo.attach(`${viewport.name}-${routeSlug(route)}`, {
          body: await page.screenshot({ fullPage: true }),
          contentType: "image/png",
        });
        expect.soft(problems, `${route} at ${viewport.width}px`).toEqual([]);
      });
    }
  });
}
