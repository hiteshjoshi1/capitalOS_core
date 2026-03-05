import { test, expect } from "@playwright/test";

test("loads dashboard shell", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("CapitalOS — Dashboard")).toBeVisible();
});

test("navigates to cash overview", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Cash" }).click();
  await expect(page.getByText("Cash Overview")).toBeVisible();
});
