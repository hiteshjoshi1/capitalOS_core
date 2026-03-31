import type { Page } from "@playwright/test";

const E2E_TOKEN = "e2e-token";

export async function mockAuthenticatedSession(page: Page): Promise<void> {
  await page.addInitScript((token: string) => {
    window.localStorage.setItem("capitalos.accessToken", token);
  }, E2E_TOKEN);

  await page.route("**/auth/me", async (route) => {
    await route.fulfill({
      json: {
        id: 1,
        username: "e2e-user",
        display_name: "E2E User",
        email: null,
        is_admin: false,
      },
    });
  });

  await page.route("**/auth/logout", async (route) => {
    await route.fulfill({ json: { status: "ok" } });
  });
}
