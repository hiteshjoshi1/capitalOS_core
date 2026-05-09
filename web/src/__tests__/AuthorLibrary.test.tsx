import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AuthorLibrary from "../routes/AuthorLibrary";
import { api } from "../lib/api";
import type { RagAuthorLibrary, RagLibraryAuthor, RagLibraryDocumentDetail } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    ragLibraryAuthors: vi.fn(),
    ragAuthorLibrary: vi.fn(),
    ragLibraryDocument: vi.fn(),
  },
}));

const AUTHORS: RagLibraryAuthor[] = [
  {
    id: "warren_buffett",
    name: "Warren Buffett",
    document_count: 3,
    source_count: 2,
    collections: ["Letters", "Essays"],
    work_types: ["essay", "letter"],
    latest_document_at: "2024-01-01T00:00:00Z",
    photo_url: "https://example.com/buffett.jpg",
    about_text: "Builder of Berkshire Hathaway and steward of a long-running corpus of letters and essays.",
  },
];

const LIBRARY: RagAuthorLibrary = {
  author: AUTHORS[0],
  grouping: {
    primary_field: "collection",
    secondary_field: "publication_year",
    available_fields: ["collection", "work_type"],
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
              metadata: { corpus_section: "Letters" },
              char_count: 420,
              parent_document_id: null,
              parent_title: null,
              child_count: 1,
            },
          ],
        },
        {
          field: "publication_year",
          label: "1988",
          value: "1988",
          document_count: 1,
          documents: [
            {
              id: "doc-1988",
              source_id: "src-letters",
              title: "1988 Shareholder Letter",
              author_id: "warren_buffett",
              author_name: "Warren Buffett",
              published_at: null,
              publication_year: 1988,
              publication_label: "1988",
              venue: "Annual Meeting",
              collection: "Letters",
              canonical_work_id: "letter-1988",
              canonical_status: "canonical",
              source_type: "html",
              source_url: "https://example.com/1988-letter",
              work_type: "letter",
              source_section: "1988 Letter",
              metadata: { corpus_section: "Letters" },
              char_count: 430,
              parent_document_id: null,
              parent_title: null,
              child_count: 0,
            },
          ],
        },
      ],
    },
    {
      field: "collection",
      label: "Essays",
      value: "Essays",
      document_count: 1,
      documents: [
        {
          id: "doc-essay",
          source_id: "src-essay",
          title: "Owner Earnings",
          author_id: "warren_buffett",
          author_name: "Warren Buffett",
          published_at: null,
          publication_year: 1986,
          publication_label: "1986",
          venue: null,
          collection: "Essays",
          canonical_work_id: null,
          canonical_status: "canonical",
          source_type: "pdf",
          source_url: "https://example.com/owner-earnings.pdf",
          work_type: "essay",
          source_section: "Owner Earnings",
          metadata: {},
          char_count: 315,
          parent_document_id: null,
          parent_title: null,
          child_count: 0,
        },
      ],
      secondary_field: null,
      secondary_groups: [],
    },
  ],
  documents: [],
};

const DOCUMENTS: Record<string, RagLibraryDocumentDetail> = {
  "doc-1987": {
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
    metadata: { corpus_section: "Letters" },
    clean_text: "Stored logical document text for the 1987 shareholder letter.",
    content_blocks: [
      {
        block_id: "blk-0000",
        type: "heading",
        order: 0,
        level: 2,
        text: "Capital Allocation Overview",
        items: null,
        table_markdown: null,
        table_rows: null,
        metadata: {},
      },
      {
        block_id: "blk-0001",
        type: "paragraph",
        order: 1,
        level: null,
        text: "Stored logical document text for the 1987 shareholder letter.",
        items: null,
        table_markdown: null,
        table_rows: null,
        metadata: { heading_context: "Capital Allocation Overview" },
      },
      {
        block_id: "blk-0002",
        type: "list",
        order: 2,
        level: null,
        text: null,
        items: ["Preserve cash flexibility", "Deploy capital selectively"],
        table_markdown: null,
        table_rows: null,
        metadata: { heading_context: "Capital Allocation Overview" },
      },
      {
        block_id: "blk-0003",
        type: "table",
        order: 3,
        level: null,
        text: null,
        items: null,
        table_markdown: "| Metric | Value |\n| --- | --- |\n| ROE | 15% |",
        table_rows: [["Metric", "Value"], ["ROE", "15%"]],
        metadata: { heading_context: "Capital Allocation Overview" },
      },
    ],
    char_count: 420,
    parent_document: null,
    child_documents: [
      {
        id: "doc-1987-notes",
        title: "1987 Shareholder Letter Notes",
        author_id: "warren_buffett",
        author_name: "Warren Buffett",
        publication_label: "1987",
        work_type: "notes",
        source_url: "https://example.com/1987-letter",
        relationship: "child",
      },
    ],
    source_author_id: "warren_buffett",
    source_author_name: "Warren Buffett",
    source_status: "ingested",
    created_at: "2024-01-01T00:00:00Z",
  },
  "doc-1987-notes": {
    id: "doc-1987-notes",
    source_id: "src-letters",
    title: "1987 Shareholder Letter Notes",
    author_id: "warren_buffett",
    author_name: "Warren Buffett",
    published_at: null,
    publication_year: 1987,
    publication_label: "1987",
    venue: null,
    collection: "Letters",
    canonical_work_id: null,
    canonical_status: null,
    source_type: "html",
    source_url: "https://example.com/1987-letter",
    work_type: "notes",
    source_section: "1987 Notes",
    metadata: {},
    clean_text: "Editorial notes linked from the main logical document.",
    content_blocks: null,
    char_count: 180,
    parent_document: {
      id: "doc-1987",
      title: "1987 Shareholder Letter",
      author_id: "warren_buffett",
      author_name: "Warren Buffett",
      publication_label: "1987",
      work_type: "letter",
      source_url: "https://example.com/1987-letter",
      relationship: "parent",
    },
    child_documents: [],
    source_author_id: "warren_buffett",
    source_author_name: "Warren Buffett",
    source_status: "ingested",
    created_at: "2024-01-01T00:00:00Z",
  },
};

function renderAuthorLibrary(initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/author-library" element={<AuthorLibrary />} />
        <Route path="/author-library/:authorId" element={<AuthorLibrary />} />
        <Route path="/author-library/:authorId/documents/:documentId" element={<AuthorLibrary />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthorLibrary", () => {
  beforeEach(() => {
    let fullscreenElement: Element | null = null;

    vi.clearAllMocks();
    vi.mocked(api.ragLibraryAuthors).mockResolvedValue(AUTHORS);
    vi.mocked(api.ragAuthorLibrary).mockResolvedValue(LIBRARY);
    vi.mocked(api.ragLibraryDocument).mockImplementation(async (documentId) => DOCUMENTS[documentId]);

    Object.defineProperty(document, "fullscreenElement", {
      configurable: true,
      get: () => fullscreenElement,
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: vi.fn(async () => {
        fullscreenElement = null;
        document.dispatchEvent(new Event("fullscreenchange"));
      }),
    });
    Object.defineProperty(HTMLDivElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn(async () => {
        fullscreenElement = document.querySelector(".authorLibraryReaderSurface");
        document.dispatchEvent(new Event("fullscreenchange"));
      }),
    });
  });

  it("renders an author gallery with compact clickable cards", async () => {
    renderAuthorLibrary("/author-library");

    expect(await screen.findByRole("heading", { name: "Author Library" })).toBeInTheDocument();
    expect(api.ragLibraryAuthors).toHaveBeenCalled();
    expect(await screen.findByRole("img", { name: "Photo of Warren Buffett" })).toHaveAttribute(
      "src",
      "https://example.com/buffett.jpg",
    );
    expect(screen.queryByText(/Berkshire Hathaway/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Warren Buffett" })).toHaveAttribute(
      "href",
      "/author-library/warren_buffett",
    );
  });

  it("renders grouped writings without document metadata on the author detail page", async () => {
    renderAuthorLibrary("/author-library/warren_buffett");

    expect((await screen.findAllByRole("heading", { name: "Warren Buffett" })).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(api.ragAuthorLibrary).toHaveBeenCalledWith("warren_buffett");
    });

    expect(await screen.findByText("Writings")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Letters" })).toBeInTheDocument();
    expect(screen.getByText("1987")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /1987 Shareholder Letter/i })).toHaveAttribute(
      "href",
      "/author-library/warren_buffett/documents/doc-1987",
    );
    expect(screen.getByRole("link", { name: /Owner Earnings/i })).toBeInTheDocument();
    expect(screen.queryByText(/Primary grouping/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/owner-earnings\.pdf/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("author-library-reader-text")).not.toBeInTheDocument();
  });

  it("opens the reader with a minimal header and supports fullscreen mode", async () => {
    const user = userEvent.setup();
    renderAuthorLibrary("/author-library/warren_buffett/documents/doc-1987");

    expect(await screen.findByTestId("author-library-reader-structured")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Capital Allocation Overview" })).toBeInTheDocument();
    expect(screen.getByText("Preserve cash flexibility")).toBeInTheDocument();
    expect(screen.getByTestId("author-library-table")).toBeInTheDocument();
    expect(screen.getByText("ROE")).toBeInTheDocument();
    expect(screen.getByText("15%")).toBeInTheDocument();
    expect(screen.queryByTestId("author-library-reader-text")).not.toBeInTheDocument();
    expect(screen.getByTestId("author-library-reader-structured")).toHaveTextContent(
      "Stored logical document text for the 1987 shareholder letter.",
    );
    expect(screen.getAllByText("Warren Buffett").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1987").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Open source/i })).toHaveAttribute(
      "href",
      "https://example.com/1987-letter",
    );
    expect(screen.queryByText(/Parent document/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Source provenance/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Stored:/i)).not.toBeInTheDocument();

    const readerSurface = screen.getByTestId("author-library-reader-surface");
    expect(readerSurface).not.toHaveClass("authorLibraryReaderSurfaceFullscreen");

    await user.click(screen.getByRole("button", { name: "Fullscreen" }));
    expect(HTMLDivElement.prototype.requestFullscreen).toHaveBeenCalled();
    expect(readerSurface).toHaveClass("authorLibraryReaderSurfaceFullscreen");

    await user.click(screen.getByRole("button", { name: "Exit fullscreen" }));
    expect(document.exitFullscreen).toHaveBeenCalled();
    expect(readerSurface).not.toHaveClass("authorLibraryReaderSurfaceFullscreen");
  });
});
