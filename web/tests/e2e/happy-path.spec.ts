import { test, expect } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);
});

test("happy path: dashboard to cash and market data", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("CapitalOS Dashboard")).toBeVisible();

  await page.goto("/cash");
  await expect(page.getByRole("heading", { level: 1, name: "Cash Overview" })).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("CapitalOS Dashboard")).toBeVisible();

  await page.goto("/market-data");
  await expect(page.getByRole("button", { name: "Refresh now" })).toBeVisible();
});
