import { test, expect, type Page } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

const CARDS = [
  {
    account_id: 1,
    account_name: "Amex Platinum",
    card_name: "Amex Platinum",
    issuer: "Amex",
    spend: 40820,
    transaction_count: 22,
    available_limit: null,
    available_limit_as_of: null,
    statement_day: 15,
    due_day: 22,
    due_date: "2026-07-22",
  },
  {
    account_id: 2,
    account_name: "DBS Credit Card",
    card_name: "DBS Credit Card",
    issuer: "DBS",
    spend: 8202,
    transaction_count: 18,
    available_limit: 59739.44,
    available_limit_as_of: "2026-07-04T00:00:00+00:00",
    statement_day: 20,
    due_day: 25,
    due_date: "2026-07-25",
  },
];

function transactionsFor(accountId: number | null) {
  const all = [
    {
      account_id: 1,
      account_name: "Amex Platinum",
      card_name: "Amex Platinum",
      issuer: "Amex",
      ts: "2026-07-08T00:00:00+00:00",
      description: "Singapore Airlines",
      amount: -12640,
      type: "EXPENSE",
      category: "Travel",
      resolved_category: "Travel",
      category_source: "parser",
      merchant_counterparty: "SIA",
      notes: null,
    },
    {
      account_id: 2,
      account_name: "DBS Credit Card",
      card_name: "DBS Credit Card",
      issuer: "DBS",
      ts: "2026-07-12T00:00:00+00:00",
      description: "DBS Annual Membership Fee",
      amount: -196.2,
      type: "FEE",
      category: "Fees",
      resolved_category: "Fees",
      category_source: "parser",
      merchant_counterparty: "DBS",
      notes: null,
    },
  ];
  return accountId == null ? all : all.filter((t) => t.account_id === accountId);
}

async function mockLiabilitiesApis(page: Page) {
  await page.route("**/accounts", async (route) => {
    await route.fulfill({ json: [] });
  });
  await page.route("**/spending/credit-card-analytics**", async (route) => {
    const url = new URL(route.request().url());
    const accountIdParam = url.searchParams.get("account_id");
    const accountId = accountIdParam != null ? Number(accountIdParam) : null;
    const scopedTransactions = transactionsFor(accountId);
    const charges = scopedTransactions.filter((t) => t.type !== "EXPENSE");
    const card = accountId != null ? CARDS.find((c) => c.account_id === accountId) : null;
    const totalSpend = card ? card.spend : CARDS.reduce((sum, c) => sum + c.spend, 0);

    await route.fulfill({
      json: {
        month: "2026-07",
        base_currency: "SGD",
        months: 12,
        account_id: accountId,
        total_spend: totalSpend,
        transaction_count: card ? card.transaction_count : CARDS.reduce((sum, c) => sum + c.transaction_count, 0),
        purchase_spend: totalSpend - charges.reduce((sum, t) => sum + Math.abs(t.amount), 0),
        prior_month: "2026-06",
        prior_month_spend: 29742,
        cards: CARDS,
        charges,
        charge_total: charges.reduce((sum, t) => sum + Math.abs(t.amount), 0),
        categories: [
          { label: "Travel", amount: 18420, percent: 0.346 },
          { label: "Shopping", amount: 12380, percent: 0.232 },
        ],
        trend: Array.from({ length: 12 }, (_, i) => ({
          month: `2025-${String(8 + i).padStart(2, "0")}`.slice(0, 7),
          spend: 25000 + i * 1500,
        })),
        transactions: scopedTransactions,
        recurring_payments: [
          {
            account_id: 1,
            account_name: "Amex Platinum",
            card_name: "Amex Platinum",
            issuer: "Amex",
            merchant_counterparty: "Netflix",
            months_present: 3,
            current_month_amount: 22,
          },
        ].filter((r) => accountId == null || r.account_id === accountId),
      },
    });
  });
}

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);
  await mockLiabilitiesApis(page);
});

test("desktop: opens Liabilities, filters by card, and sees a charge warning", async ({ page }) => {
  await page.goto("/liabilities");
  await expect(page.getByRole("heading", { level: 1, name: "Liabilities" })).toBeVisible();

  // Hero shows the all-cards total and a visible fee/interest/tax attention banner.
  await expect(page.locator(".coHeroValue")).toHaveText("S$ 49,022");
  await expect(page.getByText(/card charge.*need attention/)).toBeVisible();

  // Recurring charges and notable charges both survive the merge into this page.
  await expect(page.getByText("Recurring charges")).toBeVisible();
  await expect(page.getByText("Netflix")).toBeVisible();
  await expect(page.getByText("Notable charges")).toBeVisible();
  await expect(page.getByText("Singapore Airlines")).toBeVisible();

  // No loans linked in this fixture -> placeholder banner, not a fabricated balance.
  await expect(page.getByText("No loans linked")).toBeVisible();

  // Selecting a single card updates hero, trend meta, and the transaction ledger together.
  await page.getByRole("button", { name: "DBS Credit Card" }).click();
  await expect(page.getByRole("button", { name: "DBS Credit Card" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".coHeroValue")).toHaveText("S$ 8,202");

  const table = page.getByRole("table");
  await expect(table.getByRole("row")).toHaveCount(2); // header + 1 DBS transaction
  await expect(table.getByText("DBS Annual Membership Fee")).toBeVisible();
  await expect(table.getByText("Singapore Airlines")).toHaveCount(0);
});

test("mobile: Liabilities page loads with bottom nav and a scrollable card filter", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/liabilities");

  await expect(page.getByRole("heading", { level: 1, name: "Liabilities" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Mobile navigation" })).toBeVisible();

  const allCardsPill = page.getByRole("button", { name: "All cards" });
  await expect(allCardsPill).toBeVisible();
  await expect(allCardsPill).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("button", { name: "Amex Platinum" }).click();
  await expect(page.getByRole("button", { name: "Amex Platinum" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".coHeroValue")).toHaveText("S$ 40,820");
});
