import { test, expect, type Page, type Request } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mockAuthenticatedSession } from "./helpers/auth";

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
// Re-record (after an API shape change) against a worktree stack with demo data:
//   E2E_RECORD_FROM=http://localhost:<worktree web port> npx playwright test mobile-no-overflow
// That run logs in as demo/Test@1234 on that stack, measures the same routes on live demo
// data, and rewrites the fixture.

const VIEWPORT = { width: 375, height: 812 };
const FIXED_NOW = new Date("2026-11-06T12:00:00+08:00");

const MOBILE_ROUTES = [
  "/wealth",
  "/holdings",
  "/crypto/holdings",
  "/cash",
  "/dividends",
  "/risk",
  "/wealth/history",
  "/cash-flow",
  "/cash-flow/income",
  "/cash-flow/expenses",
  "/cash-flow/map-transactions",
  "/liabilities",
  "/operations",
  "/ingest",
  "/accounts/new",
  "/platforms",
  "/crypto",
  "/market-data",
  "/alerts",
  "/settings",
];

const here = dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = resolve(here, "fixtures/demo-api.json");
const RECORD_FROM = process.env.E2E_RECORD_FROM?.replace(/\/+$/, "");

type Fixture = Record<string, { status: number; body: unknown }>;

/** The API key of a request (path + query, without the dev proxy's /api prefix), or null
 *  when it is not an API call (the app's own modules, fonts). */
function apiKey(request: Request, pageOrigin: string): string | null {
  const url = new URL(request.url());
  if (url.hostname.endsWith("googleapis.com") || url.hostname.endsWith("gstatic.com")) return null;
  if (url.origin === pageOrigin) {
    if (!url.pathname.startsWith("/api/")) return null;
    return `${url.pathname.slice(4)}${url.search}`;
  }
  return `${url.pathname}${url.search}`;
}

async function measure(page: Page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const main = document.getElementById("main-content");
    const widest = Math.max(
      document.documentElement.scrollWidth,
      document.body.scrollWidth,
      main ? main.scrollWidth : 0,
    );
    // Name the elements that stick out, so a failure says where to look.
    const offenders: string[] = [];
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 || rect.right <= vw + 0.5) continue;
      let clipped = false;
      // A sideways scroller inside the page (a table, a chip rail) is fine; #main-content
      // itself scrolling sideways is not, so the walk stops there.
      for (let p = el.parentElement; p && p !== document.body && p !== main; p = p.parentElement) {
        if (getComputedStyle(p).overflowX !== "visible" && p.getBoundingClientRect().right <= vw + 0.5) {
          clipped = true;
          break;
        }
      }
      if (!clipped) {
        const cls = typeof el.className === "string" ? el.className.split(" ").filter(Boolean).slice(0, 2).join(".") : "";
        offenders.push(`${el.tagName.toLowerCase()}${cls ? `.${cls}` : ""} (right ${Math.round(rect.right)}px)`);
      }
    }
    return { vw, widest, offenders: offenders.slice(0, 6) };
  });
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  // Loading cards are replaced by content; give the last render a moment.
  await expect(page.getByRole("status").filter({ hasText: /^Loading…$/ })).toHaveCount(0, { timeout: 10_000 });
  await page.waitForTimeout(200);
}

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
        if (!key || key.startsWith("/auth/")) return;
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
      const sorted = Object.fromEntries(Object.entries(recorded).sort(([a], [b]) => a.localeCompare(b)));
      writeFileSync(FIXTURE_PATH, `${JSON.stringify(sorted, null, 1)}\n`);
      expect(failures).toEqual([]);
    });
    return;
  }

  const fixture = JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as Fixture;

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
