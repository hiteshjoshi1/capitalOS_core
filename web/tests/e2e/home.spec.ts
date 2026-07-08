import { test, expect, type Page } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

async function mockDashboardApis(page: Page) {
  await page.route("**/health", async (route) => {
    await route.fulfill({ json: { status: "ok" } });
  });
  await page.route("**/dashboard/bootstrap**", async (route) => {
    await route.fulfill({
      json: {
        as_of_month: "2026-02",
        base_currency: "SGD",
        snapshot_day: 6,
        net_worth_as_of: "2026-02-06T00:00:00+00:00",
        net_worth: {
          total: 742180,
          cash: 118400,
          stocks_funds: 512300,
          crypto: 136900,
          liabilities: 0,
        },
        stock_exposure_total: 512300,
        crypto_exposure_total: 136900,
        cash_percent: 15.95,
      },
    });
  });
  await page.route("**/dashboard/summary**", async (route) => {
    await route.fulfill({
      json: {
        as_of_month: "2026-02",
        base_currency: "SGD",
        snapshot_day: 6,
        net_worth_as_of: "2026-02-06T00:00:00+00:00",
        net_worth_change: {
          vs_prev_month: {
            abs: 10000,
            pct: 0.1,
            current_as_of: "2026-02-06T00:00:00+00:00",
            compare_as_of: "2026-01-06T00:00:00+00:00",
            compare_month: "2026-01",
          },
          vs_prev_year: {
            abs: 50000,
            pct: 0.5,
            current_as_of: "2026-02-06T00:00:00+00:00",
            compare_as_of: "2025-02-06T00:00:00+00:00",
            compare_month: "2025-02",
          },
        },
        net_worth: {
          total: 742180,
          cash: 118400,
          stocks_funds: 512300,
          crypto: 136900,
          liabilities: 0,
        },
        geography: [
          { country: "US", value: 700000, percent: 70 },
          { country: "SG", value: 300000, percent: 30 },
        ],
        cash_flow: { income: 8200, expenses: 5300, net: 2900, savings_rate: 0.35 },
        top_holdings: [
          { asset_id: 1, symbol: "TSLA", asset_class: "STOCK", value: 180000, percent_of_networth: 24.25 },
          { asset_id: 2, symbol: "AAPL", asset_class: "STOCK", value: 150000, percent_of_networth: 20.21 },
          { asset_id: 3, symbol: "NVDA", asset_class: "STOCK", value: 120000, percent_of_networth: 16.17 },
          { asset_id: 4, symbol: "MSFT", asset_class: "STOCK", value: 90000, percent_of_networth: 12.13 },
          { asset_id: 5, symbol: "USD", asset_class: "CASH", value: 60000, percent_of_networth: 8.08 },
        ],
        cash_balances: [
          { currency: "USD", value: 60000 },
          { currency: "SGD", value: 58400 },
        ],
      },
    });
  });
  await page.route("**/dashboard/platform-allocation**", async (route) => {
    await route.fulfill({
      json: {
        as_of: "2026-02-06T00:00:00+00:00",
        total: 100000,
        items: [
          { platform: "IBKR", platform_type: "BROKER", country: "US", value: 70000, percent: 70 },
          { platform: "DBS", platform_type: "BANK", country: "SG", value: 30000, percent: 30 },
        ],
      },
    });
  });
  await page.route("**/dashboard/stock-exposure**", async (route) => {
    await route.fulfill({
      json: {
        as_of: "2026-02-06T00:00:00+00:00",
        base_currency: "SGD",
        total: 90000,
        by_country: [],
        by_platform: [],
      },
    });
  });
  await page.route("**/dashboard/geography-exposure**", async (route) => {
    await route.fulfill({
      json: {
        as_of: "2026-02-06T00:00:00+00:00",
        base_currency: "SGD",
        total: 742180,
        slices: [
          { geo: "US", value: 410000, percent: 55.24 },
          { geo: "SG", value: 280000, percent: 37.73 },
          { geo: "HK", value: 52180, percent: 7.03 },
        ],
      },
    });
  });
  await page.route("**/spending/summary**", async (route) => {
    await route.fulfill({
      json: {
        month: "2026-02",
        base_currency: "SGD",
        income_total: 12480,
        expense_total: 8710,
        net: 3770,
        savings_rate: 0.3,
        income_categories: [],
        expense_categories: [],
      },
    });
  });
  await page.route("**/spending/credit-cards**", async (route) => {
    await route.fulfill({
      json: {
        month: "2026-02",
        base_currency: "SGD",
        total_spend: 2990,
        cards: [],
      },
    });
  });
  await page.route("**/crypto/summary**", async (route) => {
    await route.fulfill({
      json: {
        total_crypto_usd: 8400,
        total_crypto_base: 8400,
        base_currency: "SGD",
        eth: { balance: 1.2, value_usd: 8000, value_base: 8000 },
        sol: { balance: 10, value_usd: 400, value_base: 400 },
        top5_holdings: [],
        top_holdings: [],
        last_refreshed_at: "2026-02-06T00:00:00+00:00",
        is_stale: false,
        refresh_triggered: false,
      },
    });
  });
}

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);
});

test("loads dashboard shell", async ({ page }) => {
  await mockDashboardApis(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/wealth$/);
  await expect(page.getByRole("heading", { level: 1, name: "Wealth Overview" })).toBeVisible();
  await page.getByRole("link", { name: "Data Hub" }).click();
  await expect(page).toHaveURL(/\/operations$/);
  await expect(page.getByRole("link", { name: /^Import Statements$/ }).last()).toBeVisible();
  await expect(page.getByRole("link", { name: /^Refresh Stock Quotes$/ }).last()).toBeVisible();
});

test("navigates to cash overview", async ({ page }) => {
  await page.goto("/cash");
  await expect(page.getByRole("heading", { level: 1, name: "Cash Overview" })).toBeVisible();
});

test("navigates via wealth section tabs", async ({ page }) => {
  await mockDashboardApis(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/wealth$/);
  await expect(page.getByRole("link", { name: "Stocks" })).toBeVisible();

  await page.getByRole("link", { name: "Stocks" }).click();
  await expect(page).toHaveURL(/\/holdings$/);

  await page.goto("/wealth");
  await page.getByRole("link", { name: "Crypto" }).click();
  await expect(page).toHaveURL(/\/crypto\/holdings$/);

  await page.waitForLoadState("domcontentloaded");
  await page.goto("/wealth", { waitUntil: "domcontentloaded" });
  await expect(page).toHaveURL(/\/wealth$/);
  await page.getByRole("link", { name: "Cash", exact: true }).click();
  await expect(page).toHaveURL(/\/cash$/);
});

test("persists theme toggle across reload", async ({ page }) => {
  await mockDashboardApis(page);
  await page.goto("/");
  await page.goto("/settings");
  await page.getByRole("button", { name: "Switch to Light Mode" }).click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect
    .poll(async () => page.evaluate(() => window.localStorage.getItem("capitalos.theme")))
    .toBe("light");

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("loads dashboard shell on mobile breakpoint", async ({ page }) => {
  await mockDashboardApis(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Wealth Overview" })).toBeVisible();
  const mobileDateBadge = page.getByRole("button", { name: /Change month or currency/ });
  await expect(mobileDateBadge).toBeVisible();

  await mobileDateBadge.click();
  await expect(page.locator(".coHeroMobileControls").getByLabel("Month")).toBeVisible();
});
