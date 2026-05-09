import { expect, test } from "@playwright/test";
import { mockAuthenticatedSession } from "./helpers/auth";

const LONG_BLOCKS = [
  {
    block_id: "heading-1",
    type: "heading",
    order: 0,
    level: 2,
    text: "Capital Allocation",
    items: null,
    table_markdown: null,
    table_rows: null,
    metadata: {},
  },
  ...Array.from({ length: 50 }, (_, index) => ({
    block_id: `paragraph-${index}`,
    type: "paragraph",
    order: index + 1,
    level: null,
    text: `Paragraph ${index + 1}. Buffett discusses disciplined capital allocation, manager quality, and durable economics in a long-form reader layout that should scroll in fullscreen mode without pinning the document awkwardly to the left.`,
    items: null,
    table_markdown: null,
    table_rows: null,
    metadata: {},
  })),
];

test.beforeEach(async ({ page }) => {
  await mockAuthenticatedSession(page);

  await page.addInitScript(() => {
    const state = window as unknown as { __fullscreenElement?: Element | null };
    state.__fullscreenElement = null;

    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get() {
        return state.__fullscreenElement ?? null;
      },
    });

    Element.prototype.requestFullscreen = async function requestFullscreen() {
      state.__fullscreenElement = this;
      document.dispatchEvent(new Event("fullscreenchange"));
    };

    document.exitFullscreen = async () => {
      state.__fullscreenElement = null;
      document.dispatchEvent(new Event("fullscreenchange"));
    };
  });

  await page.route("**/rag/library/authors/warren_buffett", async (route) => {
    await route.fulfill({
      json: {
        author: {
          id: "warren_buffett",
          name: "Warren Buffett",
          document_count: 1,
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
        groups: [],
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
        clean_text: "Fallback reader text.",
        content_blocks: LONG_BLOCKS,
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

test("fullscreen author reader remains scrollable", async ({ page }) => {
  await page.goto("/author-library/warren_buffett/documents/doc-1987");
  await expect(page.getByRole("heading", { name: "Capital Allocation" })).toBeVisible();

  await page.getByRole("button", { name: "Fullscreen" }).click();

  const readerSurface = page.getByTestId("author-library-reader-surface");
  await expect(readerSurface).toHaveClass(/authorLibraryReaderSurfaceFullscreen/);

  const scrollState = await readerSurface.evaluate((element) => {
    const node = element as HTMLDivElement;
    const before = node.scrollTop;
    node.scrollTo({ top: node.scrollHeight });
    return {
      before,
      after: node.scrollTop,
      scrollHeight: node.scrollHeight,
      clientHeight: node.clientHeight,
      overflowY: window.getComputedStyle(node).overflowY,
    };
  });

  expect(scrollState.overflowY).toBe("auto");
  expect(scrollState.scrollHeight).toBeGreaterThan(scrollState.clientHeight);
  expect(scrollState.after).toBeGreaterThan(scrollState.before);
});
