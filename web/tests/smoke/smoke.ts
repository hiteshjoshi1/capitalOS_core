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
