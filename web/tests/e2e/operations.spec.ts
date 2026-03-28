import { test, expect, type Page } from "@playwright/test";

type Platform = {
  id: number;
  code: string;
  name: string;
  platform_type: string;
  country: string;
  website: string | null;
};

async function mockDashboardApis(page: Page) {
  await page.route("http://localhost:8000/dashboard/bootstrap**", async (route) => {
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
  await page.route("http://localhost:8000/spending/summary**", async (route) => {
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
}

async function mockOperationsApis(page: Page) {
  let platforms: Platform[] = [
    {
      id: 1,
      code: "IBKR",
      name: "Interactive Brokers",
      platform_type: "BROKER",
      country: "US",
      website: null,
    },
  ];

  await page.route("http://localhost:8000/alerts/upload-reminders/count", async (route) => {
    await route.fulfill({ json: { count: 0 } });
  });
  await page.route("http://localhost:8000/accounts/options", async (route) => {
    await route.fulfill({
      json: {
        account_types: ["BANK", "BROKER"],
        currencies: ["SGD", "USD"],
        countries: ["SG", "US"],
        currency_pattern: "^[A-Z]{3}$",
      },
    });
  });
  await page.route("http://localhost:8000/currencies", async (route) => {
    await route.fulfill({
      json: [
        { id: 1, code: "SGD", name: "Singapore Dollar", country: "Singapore" },
        { id: 2, code: "USD", name: "U.S. Dollar", country: "United States" },
      ],
    });
  });
  await page.route("http://localhost:8000/platforms/options", async (route) => {
    await route.fulfill({
      json: {
        platform_types: ["BANK", "BROKER"],
        countries: ["SG", "US"],
        country_pattern: "^[A-Z]{2,3}$",
      },
    });
  });
  await page.route("http://localhost:8000/platforms", async (route) => {
    if (route.request().method().toUpperCase() === "POST") {
      const payload = route.request().postDataJSON() as {
        code: string;
        name: string;
        platform_type: string;
        country: string;
        website?: string | null;
      };
      const created: Platform = {
        id: platforms.length + 1,
        code: payload.code.toUpperCase(),
        name: payload.name,
        platform_type: payload.platform_type,
        country: payload.country.toUpperCase(),
        website: payload.website ?? null,
      };
      platforms = [...platforms, created];
      await route.fulfill({ json: created });
      return;
    }
    await route.fulfill({ json: platforms });
  });
}

test("Operations nav includes Add Account and Platforms", async ({ page }) => {
  await mockDashboardApis(page);
  await mockOperationsApis(page);

  await page.goto("/");
  await page.getByRole("button", { name: /Operations/i }).click();
  await expect(page.getByRole("link", { name: "Add Account" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Platforms" })).toBeVisible();

  await page.getByRole("link", { name: "Add Account" }).click();
  await expect(page).toHaveURL(/\/accounts\/new$/);
  await expect(page.getByRole("heading", { level: 1, name: "Add Account" })).toBeVisible();

  await page.getByRole("link", { name: "Platforms" }).click();
  await expect(page).toHaveURL(/\/platforms$/);
  await expect(page.getByRole("heading", { level: 1, name: "Platforms" })).toBeVisible();
});

test("Platforms page creates and shows a new platform", async ({ page }) => {
  await mockOperationsApis(page);
  await page.goto("/platforms");

  await page.getByLabel("Platform Code").fill("dbs");
  await page.getByLabel("Platform Name").fill("DBS Bank");
  await page.getByLabel("Platform Type").selectOption("BANK");
  await page.getByLabel("Platform Country").selectOption("SG");
  await page.getByLabel("Platform Website").fill("https://www.dbs.com");
  await page.getByRole("button", { name: "Save platform" }).click();

  await expect(page.getByRole("status")).toContainText("Platform saved.");
  const createdRow = page.locator("tbody tr").filter({ hasText: "DBS Bank" });
  await expect(createdRow).toContainText("DBS");
  await expect(createdRow).toContainText("DBS Bank");
});
