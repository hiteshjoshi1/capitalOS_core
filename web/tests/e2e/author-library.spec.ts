import { expect, test } from "@playwright/test";

import { mockAuthenticatedSession } from "./helpers/auth";

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);

  await page.route("**/rag/library/authors/warren_buffett", async (route) => {
    await route.fulfill({
      json: {
        author: {
          id: "warren_buffett",
          name: "Warren Buffett",
          document_count: 2,
          source_count: 1,
          collections: ["Letters"],
          work_types: ["letter"],
          latest_document_at: "2026-05-01T00:00:00Z",
          photo_url: null,
          about_text: null,
        },
        grouping: {
          primary_field: "collection",
          secondary_field: "publication_year",
          available_fields: ["collection"],
        },
        groups: [
          {
            field: "collection",
            label: "Letters",
            value: "Letters",
            document_count: 2,
            documents: [],
            secondary_field: "publication_year",
            secondary_groups: [
              {
                field: "publication_year",
                label: "2005",
                value: "2005",
                document_count: 1,
                documents: [
                  {
                    id: "doc-2005",
                    source_id: "src-2005",
                    title: "Berkshire Hathaway Shareholder Letter 2005",
                    author_id: "warren_buffett",
                    author_name: "Warren Buffett",
                    published_at: "2005-12-31",
                    publication_year: 2005,
                    publication_label: "2005-12-31",
                    venue: "Berkshire Hathaway",
                    collection: "Letters",
                    canonical_work_id: "buffett-2005",
                    canonical_status: "canonical",
                    source_type: "pdf",
                    source_url: "https://www.berkshirehathaway.com/letters/2005ltr.pdf",
                    work_type: "letter",
                    source_section: "2005 Letter",
                    metadata: {},
                    char_count: 6400,
                    parent_document_id: null,
                    parent_title: null,
                    child_count: 0,
                  },
                ],
              },
              {
                field: "publication_year",
                label: "1987",
                value: "1987",
                document_count: 1,
                documents: [
                  {
                    id: "doc-1987",
                    source_id: "src-letters",
                    title: "1987 Shareholder Letter",
                    author_id: "warren_buffett",
                    author_name: "Warren Buffett",
                    published_at: null,
                    publication_year: 1987,
                    publication_label: "1987",
                    venue: "Annual Meeting",
                    collection: "Letters",
                    canonical_work_id: "letter-1987",
                    canonical_status: "canonical",
                    source_type: "html",
                    source_url: "https://example.com/1987-letter",
                    work_type: "letter",
                    source_section: "1987 Letter",
                    metadata: {},
                    char_count: 8000,
                    parent_document_id: null,
                    parent_title: null,
                    child_count: 0,
                  },
                ],
              },
            ],
          },
        ],
        documents: [],
      },
    });
  });

  await page.route("**/rag/library/documents/doc-1987", async (route) => {
    await route.fulfill({
      json: {
        id: "doc-1987",
        source_id: "src-letters",
        title: "1987 Shareholder Letter",
        author_id: "warren_buffett",
        author_name: "Warren Buffett",
        published_at: null,
        publication_year: 1987,
        publication_label: "1987",
        venue: "Annual Meeting",
        collection: "Letters",
        canonical_work_id: "letter-1987",
        canonical_status: "canonical",
        source_type: "html",
        source_url: "https://example.com/1987-letter",
        work_type: "letter",
        source_section: "1987 Letter",
        metadata: {},
        char_count: 8000,
        parent_document: null,
        child_documents: [],
        source_author_id: "warren_buffett",
        source_author_name: "Warren Buffett",
        source_status: "ingested",
        created_at: "2026-05-01T00:00:00Z",
      },
    });
  });
});

test("author library titles point directly to the original source", async ({ page }) => {
  await page.goto("/author-library/warren_buffett");

  const sourceLink = page.getByRole("link", { name: "Berkshire Hathaway Shareholder Letter 2005" });
  await expect(sourceLink).toHaveAttribute("href", "https://www.berkshirehathaway.com/letters/2005ltr.pdf");
  await expect(sourceLink).toHaveAttribute("target", "_blank");
  await expect(page.getByText("Each title opens the original letter or article source. CapitalOS no longer renders ingested content inside the library.")).toBeVisible();
});

test("direct document routes hand off to the original source instead of rendering stored content", async ({ page }) => {
  await page.goto("/author-library/warren_buffett/documents/doc-1987");

  await expect(page.getByTestId("author-library-source-only")).toBeVisible();
  await expect(page.getByRole("link", { name: /Open original source/i })).toHaveAttribute("href", "https://example.com/1987-letter");
  await expect(page.getByText("Author Library now hands this document off to its original source instead of rendering extracted content inside CapitalOS.")).toBeVisible();
  await expect(page.getByText("Fallback reader text.")).toHaveCount(0);
});
