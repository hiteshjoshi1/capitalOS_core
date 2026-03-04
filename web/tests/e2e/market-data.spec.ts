import { test, expect } from "@playwright/test";

test("navigates to market data page", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Market Data" }).click();
  await expect(page.getByRole("button", { name: "Refresh now" })).toBeVisible();
  await expect(page.getByText(/Latest by Exchange|API error/)).toBeVisible();
});
