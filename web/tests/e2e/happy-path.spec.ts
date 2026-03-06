import { test, expect } from "@playwright/test";

test("happy path: dashboard to cash and market data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("CapitalOS — Dashboard")).toBeVisible();

  await page.getByRole("link", { name: "Cash" }).click();
  await expect(page.getByText("Cash Overview")).toBeVisible();

  await page.getByRole("link", { name: "Dashboard" }).click();
  await expect(page.getByText("CapitalOS — Dashboard")).toBeVisible();

  await page.getByRole("link", { name: "Market Data" }).click();
  await expect(page.getByRole("button", { name: "Refresh now" })).toBeVisible();
});
