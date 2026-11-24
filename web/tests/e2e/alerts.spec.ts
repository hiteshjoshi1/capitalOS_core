import { test, expect, type Page } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

// #317: the header bell reads the Data Hub inbox (#316). #475 (V3): the Alerts page was a third
// copy of that list; /alerts now opens the Data Hub Inbox.
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

test("/alerts opens the Data Hub Inbox, keeping the query string", async ({ page }) => {
  await mockInbox(page, ITEMS);
  await page.goto("/alerts?month=2026-11");
  await expect(page).toHaveURL(/\/operations\?month=2026-11$/);
  await expect(page.getByRole("heading", { level: 1, name: "Alerts" })).toHaveCount(0);
  const list = page.locator("ul.inboxList");
  await expect(list.getByText("DBS Multiplier: 20 days overdue")).toBeVisible();
  await expect(list.getByText("IBKR: file format not recognised")).toBeVisible();
  // The bell shows the same count.
  await expect(page.getByLabel("2 items need you")).toBeVisible();
});
