import { test, expect } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);
});

test("navigates to market data page", async ({ page }) => {
  await page.goto("/market-data");
  // #320: refreshing is admin-only, so a non-admin gets a note instead of the button.
  await expect(page.getByText("Quotes refresh daily; an admin can refresh them now.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh all" })).toHaveCount(0);
  await expect(page.getByText(/Latest refresh status|Couldn't load market data/)).toBeVisible();
});

test("an admin gets Refresh all on the page (#320)", async ({ page }) => {
  await mockAuthenticatedSession(page, { admin: true });
  await page.goto("/market-data");
  await expect(page.getByRole("button", { name: "Refresh all" })).toBeVisible();
});
