import { test, expect } from "@playwright/test";

test("navigates to market data page", async ({ page }) => {
  await page.goto("/market-data");
  await expect(page.getByRole("button", { name: "Refresh now" })).toBeVisible();
  await expect(page.getByText(/Latest by Exchange|API error/)).toBeVisible();
});
