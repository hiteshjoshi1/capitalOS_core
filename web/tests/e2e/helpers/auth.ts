import type { Page } from "@playwright/test";

const E2E_TOKEN = "e2e-test-token";

export async function mockAuthenticatedSession(page: Page): Promise<void> {
  // Mock /auth/refresh so AuthContext bootstrap succeeds without a real cookie.
  await page.route("**/auth/refresh", async (route) => {
    await route.fulfill({
      json: { access_token: E2E_TOKEN, token_type: "bearer", expires_in: 3600 },
    });
  });

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
