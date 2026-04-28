import { test, expect } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);

  await page.route("**/ai-sage/query", async (route) => {
    await route.fulfill({
      json: {
        query: "What matters?",
        mode: "concept",
        best_passages: [
          {
            chunk_id: "chunk-1",
            author_id: "warren_buffett",
            author_name: "Warren Buffett",
            text: "A wonderful business can compound over time.",
            similarity: 0.91,
            metadata: { title: "Letter" },
          },
        ],
        author_views: [
          {
            author_id: "warren_buffett",
            author_name: "Warren Buffett",
            view: "Focus on business quality.",
            key_passages: ["A wonderful business can compound over time."],
          },
        ],
        synthesis: "Focus on business quality.",
        critique: "Durability still needs to be tested against industry change.",
        suggested_readings: [
          {
            author_id: "warren_buffett",
            author_name: "Warren Buffett",
            passage: "A wonderful business can compound over time.",
            source_url: "https://example.com/letter",
            reason: "Best matched passage for this concept.",
          },
        ],
        evidence_sufficient: true,
        weak_evidence_note: null,
      },
    });
  });
});

test("navigates to AI Sage and renders grounded query results", async ({ page }) => {
  await page.goto("/ai-sage");
  await expect(page.getByRole("heading", { name: "Hello E2E User" })).toBeVisible();
  await expect(page.getByText("What insights are we discovering today?")).toBeVisible();
  await page
    .getByPlaceholder(
      "Ask AI Sage anything about a business, thesis, risk, or mental model...",
    )
    .fill("What matters?");
  await page
    .getByPlaceholder(
      "Ask AI Sage anything about a business, thesis, risk, or mental model...",
    )
    .press("Enter");

  await expect(page.getByText("What matters?")).toBeVisible();
  await expect(page.getByText("Review the top ranked passages below.")).toBeVisible();
  await expect(page.getByText("Top Passages", { exact: true })).toBeVisible();
  await expect(page.getByText("Warren Buffett").first()).toBeVisible();
  await expect(page.getByText("Critique", { exact: true })).toBeVisible();
  await expect(page.getByText("Durability still needs to be tested against industry change.")).toBeVisible();
  await expect(page.getByText("Passage 1")).toBeVisible();
  await expect(page.getByText("Rank score 0.91")).toBeVisible();
  await expect(
    page
      .locator("article")
      .filter({ hasText: "Passage 1" })
      .getByText(/A wonderful business can compound/i),
  ).toBeVisible();
});
