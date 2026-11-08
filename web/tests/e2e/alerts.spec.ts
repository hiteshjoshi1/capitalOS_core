import { test, expect, type Page } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

// #317: Alerts and the header bell read the Data Hub inbox (#316).
async function mockInbox(page: Page, items: object[] = []) {
  await page.route("**/operations/inbox", async (route) => {
    await route.fulfill({
      json: { as_of: "2026-11-08", count: items.length, items, all_good: [], recent_activity: [] },
    });
  });
}

const ITEMS = [
  {
    id: "source:account:1",
    kind: "source_overdue",
    severity: "high",
    title: "DBS Multiplier: 20 days overdue",
    detail: "Last data 2026-10-01",
    action: { label: "Upload", route: "/ingest", params: { account_id: "1" }, run: null, admin_only: false },
    source: null,
  },
  {
    id: "import:4",
    kind: "unknown_format",
    severity: "medium",
    title: "IBKR: file format not recognised",
    detail: "odd.csv",
    action: { label: "Fix format", route: "/ingest", params: { job: "4" }, run: null, admin_only: false },
    source: null,
  },
];

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);
});

test("navigates to /alerts and shows the inbox items", async ({ page }) => {
  await mockInbox(page, ITEMS);
  await page.goto("/alerts");
  await expect(page.getByRole("heading", { level: 1, name: "Alerts" })).toBeVisible();
  const list = page.getByRole("list", { name: "Alerts" });
  await expect(list.getByText("DBS Multiplier: 20 days overdue")).toBeVisible();
  await expect(list.getByText("IBKR: file format not recognised")).toBeVisible();
  // The bell shows the same count.
  await expect(page.getByLabel("2 items need you")).toBeVisible();
});

test("shows the empty state when nothing needs you", async ({ page }) => {
  await mockInbox(page, []);
  await page.goto("/alerts");
  await expect(page.getByText("Nothing needs you. Everything is up to date.")).toBeVisible();
  await expect(page.getByLabel("Nothing needs you")).toBeVisible();
});

test("alert items link to their fix", async ({ page }) => {
  await mockInbox(page, ITEMS);
  await page.goto("/alerts");
  const list = page.getByRole("list", { name: "Alerts" });
  await expect(list.getByRole("link", { name: "Upload" })).toHaveAttribute("href", "/ingest?account_id=1");
  await expect(list.getByRole("link", { name: "Fix format" })).toHaveAttribute("href", "/ingest?job=4");
});
