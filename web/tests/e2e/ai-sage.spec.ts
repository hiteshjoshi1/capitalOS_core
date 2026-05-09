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

  await page.route("**/ai-sage/chats/chat-1", async (route) => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    await route.fulfill({
      json: {
        id: "chat-1",
        title: "What does Munger say about his early days, as a lawyer as a kid, as an early investor?",
        created_at: "2026-05-01T10:00:00Z",
        updated_at: "2026-05-01T10:05:00Z",
        last_activity_at: "2026-05-01T10:00:00Z",
        pinned_at: null,
        metadata_json: null,
        messages: [
          {
            id: "user-1",
            role: "user",
            content: "What does Munger say about his early days?",
            status: "completed",
            created_at: "2026-05-01T10:00:00Z",
            evidence: [],
          },
          {
            id: "assistant-1",
            role: "assistant",
            content: "He emphasizes learning, discipline, and patience.",
            status: "completed",
            created_at: "2026-05-01T10:00:05Z",
            metadata_json: { mode: "concept", evidence_sufficient: true },
            evidence: [],
          },
        ],
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

test("opens a saved AI Sage chat with the thread anchored at the top of the pane", async ({ page }) => {
  await page.route("**/ai-sage/chats?limit=30&offset=0", async (route) => {
    await route.fulfill({
      json: {
        items: [
          {
            id: "chat-1",
            title: "What does Munger say about his early days, as a lawyer as a kid, as an early investor?",
            preview: "He emphasizes learning, discipline, and patience.",
            status: "answered",
            created_at: "2026-05-01T10:00:00Z",
            updated_at: "2026-05-01T10:05:00Z",
            last_activity_at: "2026-05-01T10:00:00Z",
            pinned_at: null,
          },
        ],
        total: 1,
        limit: 30,
        offset: 0,
      },
    });
  });

  await page.goto("/ai-sage/chats/chat-1");
  await expect(page.getByRole("heading", { name: /What does Munger say/i })).toBeVisible();

  const geometry = await page.evaluate(() => {
    const shell = document.querySelector(".appShellContent") as HTMLElement | null;
    const workspace = document.querySelector(".aiSageWorkspace") as HTMLElement | null;
    const mainPanel = document.querySelector(".aiSageMainPanelThread") as HTMLElement | null;
    const toolbar = document.querySelector(".aiSageChatToolbar") as HTMLElement | null;
    const transcript = document.querySelector(".aiSageTranscript") as HTMLElement | null;
    return {
      shellScrollTop: shell?.scrollTop ?? null,
      shellTop: shell?.getBoundingClientRect().top ?? null,
      workspaceTop: workspace?.getBoundingClientRect().top ?? null,
      workspaceHeight: workspace?.getBoundingClientRect().height ?? null,
      mainPanelTop: mainPanel?.getBoundingClientRect().top ?? null,
      mainPanelHeight: mainPanel?.getBoundingClientRect().height ?? null,
      toolbarTop: toolbar?.getBoundingClientRect().top ?? null,
      transcriptTop: transcript?.getBoundingClientRect().top ?? null,
      workspaceAlignItems: workspace ? getComputedStyle(workspace).alignItems : null,
      workspaceJustifyItems: workspace ? getComputedStyle(workspace).justifyItems : null,
      workspaceDisplay: workspace ? getComputedStyle(workspace).display : null,
      mainPanelAlignContent: mainPanel ? getComputedStyle(mainPanel).alignContent : null,
      mainPanelDisplay: mainPanel ? getComputedStyle(mainPanel).display : null,
      mainPanelGridRows: mainPanel ? getComputedStyle(mainPanel).gridTemplateRows : null,
      mainPanelAlignSelf: mainPanel ? getComputedStyle(mainPanel).alignSelf : null,
      mainPanelMarginTop: mainPanel ? getComputedStyle(mainPanel).marginTop : null,
      mainPanelPosition: mainPanel ? getComputedStyle(mainPanel).position : null,
    };
  });

  expect(geometry.shellScrollTop).toBe(0);
  expect(geometry.toolbarTop).not.toBeNull();
  expect(geometry.shellTop).not.toBeNull();
  expect((geometry.toolbarTop ?? 0) - (geometry.shellTop ?? 0)).toBeLessThan(140);
});
