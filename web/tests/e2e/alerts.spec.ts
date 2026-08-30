import { test, expect, type Page } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

async function mockAlertsApis(page: Page, uploadReminders: object[] = []) {
  // Legacy endpoints — still available for compatibility
  await page.route("**/alerts/upload-reminders/count", async (route) => {
    await route.fulfill({ json: { count: uploadReminders.length } });
  });
  await page.route("**/alerts/upload-reminders", async (route) => {
    await route.fulfill({ json: uploadReminders });
  });
  // New unified endpoint used by the Alerts page
  await page.route("**/alerts/notifications", async (route) => {
    await route.fulfill({
      json: {
        upload_reminders: uploadReminders,
        total_count: uploadReminders.length,
      },
    });
  });
}

const MOCK_ALERTS = [
  {
    account_id: 1,
    account_name: "DBS Savings",
    platform: "DBS",
    account_type: "BANK",
    last_upload_date: "2025-11-01",
    last_transaction_date: "2025-10-31",
    days_since_upload: 45,
    message: "Upload the latest statement for DBS Savings (DBS). Last upload was 2025-11-01 and last transaction tracked was 2025-10-31.",
  },
  {
    account_id: 2,
    account_name: "IBKR Brokerage",
    platform: "IBKR",
    account_type: "BROKER",
    last_upload_date: "2025-10-15",
    last_transaction_date: null,
    days_since_upload: 62,
    message: "Upload the latest statement for IBKR Brokerage (IBKR). Last upload was 2025-10-15.",
  },
];

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);
});

test("navigates to /alerts and shows alert cards", async ({ page }) => {
  await mockAlertsApis(page, MOCK_ALERTS);
  await page.goto("/alerts");

  await expect(page.getByRole("heading", { level: 1, name: "Alerts" })).toBeVisible();
  await expect(page.getByLabel("Upload reminders")).toBeVisible();

  await expect(page.getByText("DBS Savings", { exact: true })).toBeVisible();
  await expect(page.getByText("IBKR Brokerage", { exact: true })).toBeVisible();
  await expect(page.getByText(/45 days/)).toBeVisible();
  await expect(page.getByText(/62 days/)).toBeVisible();
});

test("shows empty state when no alerts", async ({ page }) => {
  await mockAlertsApis(page, []);
  await page.goto("/alerts");

  await expect(page.getByRole("heading", { level: 1, name: "Alerts" })).toBeVisible();
  await expect(page.getByLabel("No alerts")).toBeVisible();
  await expect(page.getByText(/All accounts are up to date/i)).toBeVisible();
});

test("alert cards contain links to ingest page", async ({ page }) => {
  await mockAlertsApis(page, MOCK_ALERTS);
  await page.goto("/alerts");

  const ingestLinks = page.getByRole("link", { name: /Go to Ingest/i });
  await expect(ingestLinks.first()).toBeVisible();
  await expect(ingestLinks.first()).toHaveAttribute("href", "/ingest?account_id=1");
});
