import type { Page } from "@playwright/test";
import { MAIN_ROUTES } from "../e2e/helpers/pages";

// What the smoke run (#73) opens, and at which sizes.

/** The main pages, minus the two that only redirect (/dividends → /income, /platforms →
 *  /settings/admin), plus their targets. routes.spec.ts checks the navigation against it. */
export const SMOKE_ROUTES = [
  ...MAIN_ROUTES.filter((route) => route !== "/dividends" && route !== "/platforms"),
  "/income",
  "/settings/admin",
];

export const VIEWPORTS = [
  { name: "phone", width: 375, height: 812 },
  { name: "desktop", width: 1440, height: 900 },
] as const;

/** "/cash-flow/map-transactions" → "cash-flow-map-transactions"; "/add?what=wallet" → "add-what-wallet". */
export function routeSlug(route: string): string {
  return route.replace(/^\//, "").replace(/[^a-z0-9]+/gi, "-").replace(/-+$/, "") || "root";
}

/** Wait until the page has kept the same size for 500ms (a late badge or status line can still
 *  change it after the data has loaded), so a screenshot isn't taken mid-change. */
export async function waitForStableSize(page: Page): Promise<void> {
  await page.evaluate(() => {
    delete (window as unknown as { __smokeSize?: string }).__smokeSize;
  });
  await page.waitForFunction(
    () => {
      const w = window as unknown as { __smokeSize?: string; __smokeSince?: number };
      const size = `${document.documentElement.scrollWidth}x${document.documentElement.scrollHeight}`;
      if (w.__smokeSize !== size) {
        w.__smokeSize = size;
        w.__smokeSince = performance.now();
        return false;
      }
      return performance.now() - (w.__smokeSince ?? 0) >= 500;
    },
    undefined,
    { polling: 100, timeout: 10_000 },
  );
}
