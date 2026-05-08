import { expect, test } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);

  await page.route("**/ai-sage/chats?limit=30&offset=0", async (route) => {
    await route.fulfill({
      json: {
        items: [],
        total: 0,
        limit: 30,
        offset: 0,
      },
    });
  });

  await page.route("**/ai-sage/chats", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      json: {
        id: "chat-new",
        title: "New chat",
        created_at: "2026-05-01T10:00:00Z",
        updated_at: "2026-05-01T10:00:00Z",
        last_activity_at: "2026-05-01T10:00:00Z",
        pinned_at: null,
        metadata_json: null,
        messages: [],
      },
    });
  });

  await page.route("**/ai-sage/chats/chat-new/messages/stream", async (route) => {
    const body = [
      'event: ack',
      'data: {"chat_id":"chat-new","user_message":{"id":"user-1","role":"user","content":"What matters?","status":"completed","created_at":"2026-05-01T10:00:00Z","evidence":[]},"assistant_message_id":"assistant-1"}',
      "",
      'event: delta',
      'data: {"assistant_message_id":"assistant-1","delta":"Grounded "}',
      "",
      'event: delta',
      'data: {"assistant_message_id":"assistant-1","delta":"answer."}',
      "",
      'event: done',
      'data: {"chat":{"id":"chat-new","title":"What matters?","created_at":"2026-05-01T10:00:00Z","updated_at":"2026-05-01T10:00:05Z","last_activity_at":"2026-05-01T10:00:00Z","pinned_at":null,"metadata_json":null,"messages":[{"id":"user-1","role":"user","content":"What matters?","status":"completed","created_at":"2026-05-01T10:00:00Z","evidence":[]},{"id":"assistant-1","role":"assistant","content":"Grounded answer.","status":"completed","created_at":"2026-05-01T10:00:05Z","metadata_json":{"mode":"concept","evidence_sufficient":true},"evidence":[]}]},"user_message":{"id":"user-1","role":"user","content":"What matters?","status":"completed","created_at":"2026-05-01T10:00:00Z","evidence":[]},"assistant_message":{"id":"assistant-1","role":"assistant","content":"Grounded answer.","status":"completed","created_at":"2026-05-01T10:00:05Z","metadata_json":{"mode":"concept","evidence_sufficient":true},"evidence":[]}}',
      "",
    ].join("\n");

    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body,
      headers: {
        "cache-control": "no-cache",
      },
    });
  });

  await page.route("**/ai-sage/chats/chat-new", async (route) => {
    await route.fulfill({
      json: {
        id: "chat-new",
        title: "New chat",
        created_at: "2026-05-01T10:00:00Z",
        updated_at: "2026-05-01T10:00:00Z",
        last_activity_at: "2026-05-01T10:00:00Z",
        pinned_at: null,
        metadata_json: null,
        messages: [],
      },
    });
  });
});

test("creates a persistent AI Sage chat and streams the response", async ({ page }) => {
  await page.goto("/ai-sage");
  await expect(page.getByText("No chats yet.")).toBeVisible();

  const composer = page.getByPlaceholder("Ask AI Sage anything");
  await composer.fill("What matters?");
  await composer.press("Enter");

  await expect(page.getByText("What matters?")).toBeVisible();
  await expect(page.getByText("Grounded answer.")).toBeVisible();
});
