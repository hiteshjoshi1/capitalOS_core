import { test, expect } from "@playwright/test";

test("loads dashboard shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("CapitalOS — Dashboard")).toBeVisible();
});
