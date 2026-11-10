import { expect, type Page, type Request } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Shared by the mocked layout checks (mobile-no-overflow, #239), the full-stack smoke and the
// screenshot diffs (tests/smoke, #73).

/** Every main page. A page added to the navigation must be added here (tests/smoke checks). */
export const MAIN_ROUTES = [
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
  "/operations/sources",
  "/add",
  "/platforms",
  "/add?what=wallet",
  "/market-data",
  "/alerts",
  "/settings",
];

/** The browser clock the demo fixture was recorded at (tests/e2e/fixtures/demo-api.json). */
export const FIXED_NOW = new Date("2026-11-06T12:00:00+08:00");

const here = dirname(fileURLToPath(import.meta.url));
export const FIXTURE_PATH = resolve(here, "../fixtures/demo-api.json");

export type Fixture = Record<string, { status: number; body: unknown }>;

export function loadFixture(): Fixture {
  return JSON.parse(readFileSync(FIXTURE_PATH, "utf8")) as Fixture;
}

/** The API key of a request (path + query, without the /api prefix), or null when it is not
 *  an API call (the app's own modules, fonts). */
export function apiKey(request: Request, pageOrigin: string): string | null {
  const url = new URL(request.url());
  if (isFontHost(url.hostname)) return null;
  if (url.origin === pageOrigin) {
    if (!url.pathname.startsWith("/api/")) return null;
    return `${url.pathname.slice(4)}${url.search}`;
  }
  return `${url.pathname}${url.search}`;
}

/** Google Fonts (index.html, index.css): not the app, so never an app failure. */
export function isFontHost(hostname: string): boolean {
  return hostname.endsWith("googleapis.com") || hostname.endsWith("gstatic.com");
}

/** How wide the page really is: document, body (the top bar) and #main-content (the page,
 *  a scroll container), plus the elements sticking out, so a failure says where to look. */
export async function measure(page: Page) {
  return page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const main = document.getElementById("main-content");
    const widest = Math.max(
      document.documentElement.scrollWidth,
      document.body.scrollWidth,
      main ? main.scrollWidth : 0,
    );
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

/** Wait until the page has loaded its data and the "Loading…" cards are gone. */
export async function settle(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => undefined);
  await expect(page.getByRole("status").filter({ hasText: /^Loading…$/ })).toHaveCount(0, { timeout: 10_000 });
  await page.waitForTimeout(200);
}
