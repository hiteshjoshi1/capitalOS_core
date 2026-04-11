import { test, expect } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);

  await page.route("**/rag/query", async (route) => {
    await route.fulfill({
      json: {
        query: "What matters?",
        mode: "ask",
        selected_authors: [
          {
            author_id: "warren_buffett",
            name: "Warren Buffett",
            score: 4.5,
            domains: ["investing"],
            expertise_tags: ["capital_allocation"],
            match_reason: ["domain_match:investing"],
            worldview: "Focus on quality and capital allocation.",
            key_maxims: ["Stay within competence"],
          },
        ],
        evidence_chunks: [
          {
            chunk_id: "chunk-1",
            author_id: "warren_buffett",
            author_name: "Warren Buffett",
            text: "A wonderful business can compound over time.",
            similarity: 0.91,
            metadata: { title: "Letter" },
          },
        ],
        answer: "Focus on business quality.",
        missing_information: null,
        evidence_sufficient: true,
      },
    });
  });
});

test("navigates to AI Sage and renders grounded query results", async ({ page }) => {
  await page.goto("/ai-sage");
  await expect(page.getByRole("heading", { name: "AI Sage" })).toBeVisible();
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

  await expect(page.getByText("Your Question")).toBeVisible();
  await expect(page.getByText("Relevant Author Perspectives")).toBeVisible();
  await expect(page.getByText("Warren Buffett").first()).toBeVisible();
  await expect(page.getByText("Answer")).toBeVisible();
  await expect(page.getByText("Focus on business quality.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Show Sources (1)" })).toBeVisible();
  await expect(page.getByText(/A wonderful business can compound/i)).toHaveCount(0);

  await page.getByRole("button", { name: "Show Sources (1)" }).click();
  await expect(page.getByText(/A wonderful business can compound/i)).toBeVisible();
});
