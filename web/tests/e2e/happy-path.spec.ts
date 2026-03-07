import { test, expect } from "@playwright/test";

test("happy path: dashboard to cash and market data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("CapitalOS Dashboard")).toBeVisible();

  await page.goto("/cash");
  await expect(page.getByText("Cash Overview")).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("CapitalOS Dashboard")).toBeVisible();

  await page.goto("/market-data");
  await expect(page.getByRole("button", { name: "Refresh now" })).toBeVisible();
});
