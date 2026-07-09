import { test, expect } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);
});

test("navigates to market data page", async ({ page }) => {
  await page.goto("/market-data");
  await expect(page.getByRole("button", { name: "Refresh all quotes" })).toBeVisible();
  await expect(page.getByText(/Latest refresh status|API error/)).toBeVisible();
});
