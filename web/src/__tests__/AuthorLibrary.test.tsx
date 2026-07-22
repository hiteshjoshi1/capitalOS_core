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
    ragFetchSourceFileObjectUrl: vi.fn(),
  },
}));

const AUTHORS: RagLibraryAuthor[] = [
  {
    id: "warren_buffett",
    name: "Warren Buffett",
    document_count: 3,
    source_count: 2,
    collections: ["Letters", "Drafts"],
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
              stored_file_url: null,
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
      ],
    },
    {
      field: "collection",
      label: "Drafts",
      value: "Drafts",
      document_count: 1,
      documents: [
        {
          id: "doc-no-source",
          source_id: "src-draft",
          title: "Working Notes",
          author_id: "warren_buffett",
          author_name: "Warren Buffett",
          published_at: null,
          publication_year: 1986,
          publication_label: "1986",
          venue: null,
          collection: "Drafts",
          canonical_work_id: null,
          canonical_status: "canonical",
          source_type: "text",
          source_url: null,
          stored_file_url: null,
          work_type: "notes",
          source_section: "Working Notes",
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
    stored_file_url: null,
    work_type: "letter",
    source_section: "1987 Letter",
    metadata: { corpus_section: "Letters" },
    char_count: 420,
    parent_document: null,
    child_documents: [],
    source_author_id: "warren_buffett",
    source_author_name: "Warren Buffett",
    source_status: "ingested",
    created_at: "2024-01-01T00:00:00Z",
  },
  "doc-no-source": {
    id: "doc-no-source",
    source_id: "src-draft",
    title: "Working Notes",
    author_id: "warren_buffett",
    author_name: "Warren Buffett",
    published_at: null,
    publication_year: 1986,
    publication_label: "1986",
    venue: null,
    collection: "Drafts",
    canonical_work_id: null,
    canonical_status: "canonical",
    source_type: "text",
    source_url: null,
    stored_file_url: null,
    work_type: "notes",
    source_section: "Working Notes",
    metadata: {},
    char_count: 315,
    parent_document: null,
    child_documents: [],
    source_author_id: "warren_buffett",
    source_author_name: "Warren Buffett",
    source_status: "ingested",
    created_at: "2024-01-01T00:00:00Z",
  },
  "doc-uploaded-pdf": {
    id: "doc-uploaded-pdf",
    source_id: "src-uploaded-pdf",
    title: "Opportunities and Expectations",
    author_id: "warren_buffett",
    author_name: "Warren Buffett",
    published_at: null,
    publication_year: 2005,
    publication_label: "2005",
    venue: null,
    collection: null,
    canonical_work_id: null,
    canonical_status: "canonical",
    source_type: "pdf",
    source_url: "https://www.morganstanley.com/consilient-observer.pdf",
    stored_file_url: "/rag/sources/src-uploaded-pdf/file",
    work_type: "essay",
    source_section: null,
    metadata: {},
    char_count: 900,
    parent_document: null,
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
    vi.clearAllMocks();
    vi.mocked(api.ragLibraryAuthors).mockResolvedValue(AUTHORS);
    vi.mocked(api.ragAuthorLibrary).mockResolvedValue(LIBRARY);
    vi.mocked(api.ragLibraryDocument).mockImplementation(async (documentId) => DOCUMENTS[documentId]);
  });

  it("renders an author gallery with compact clickable cards", async () => {
    renderAuthorLibrary("/author-library");

    expect(await screen.findByRole("heading", { name: "Author Library" })).toBeInTheDocument();
    expect(api.ragLibraryAuthors).toHaveBeenCalled();
    expect(await screen.findByRole("img", { name: "Photo of Warren Buffett" })).toHaveAttribute(
      "src",
      "https://example.com/buffett.jpg",
    );
    expect(screen.getByRole("link", { name: "Warren Buffett" })).toHaveAttribute(
      "href",
      "/author-library/warren_buffett",
    );
  });

  it("renders grouped writings as source links and falls back to the internal handoff route when needed", async () => {
    renderAuthorLibrary("/author-library/warren_buffett");

    expect((await screen.findAllByRole("heading", { name: "Warren Buffett" })).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(api.ragAuthorLibrary).toHaveBeenCalledWith("warren_buffett");
    });

    expect(await screen.findByText("Writings")).toBeInTheDocument();
    expect(screen.getByText("Each title opens the original letter or article source. CapitalOS no longer renders ingested content inside the library.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /1987 Shareholder Letter/i })).toHaveAttribute(
      "href",
      "https://example.com/1987-letter",
    );
    expect(screen.getByRole("link", { name: /1987 Shareholder Letter/i })).toHaveAttribute("target", "_blank");
    expect(screen.getByRole("link", { name: /Working Notes/i })).toHaveAttribute(
      "href",
      "/author-library/warren_buffett/documents/doc-no-source",
    );
  });

  it("uses a source-only handoff page on direct document routes", async () => {
    renderAuthorLibrary("/author-library/warren_buffett/documents/doc-1987");

    expect(await screen.findByTestId("author-library-source-only")).toBeInTheDocument();
    expect(api.ragLibraryDocument).toHaveBeenCalledWith("doc-1987");
    expect(api.ragAuthorLibrary).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /Open original source/i })).toHaveAttribute(
      "href",
      "https://example.com/1987-letter",
    );
    expect(screen.queryByText("Stored logical document text for the 1987 shareholder letter.")).not.toBeInTheDocument();
    expect(screen.getByText("Author Library now hands this document off to its original source instead of rendering extracted content inside CapitalOS.")).toBeInTheDocument();
  });

  it("explains when a source url is missing on the handoff page", async () => {
    renderAuthorLibrary("/author-library/warren_buffett/documents/doc-no-source");

    expect(await screen.findByTestId("author-library-source-only")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open source/i })).not.toBeInTheDocument();
    expect(screen.getByText("No source URL is stored for this document yet.")).toBeInTheDocument();
  });

  it("offers both the stored PDF and the original source link for manually-uploaded documents", async () => {
    vi.mocked(api.ragFetchSourceFileObjectUrl).mockResolvedValue("blob:mock-object-url");
    const windowOpenSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    renderAuthorLibrary("/author-library/warren_buffett/documents/doc-uploaded-pdf");

    expect(await screen.findByTestId("author-library-source-only")).toBeInTheDocument();
    const openPdfButton = screen.getByRole("button", { name: /Open PDF/i });
    expect(
      screen.getByRole("link", { name: /Open original source/i }),
    ).toHaveAttribute("href", "https://www.morganstanley.com/consilient-observer.pdf");

    const user = userEvent.setup();
    await user.click(openPdfButton);

    await waitFor(() => {
      expect(api.ragFetchSourceFileObjectUrl).toHaveBeenCalledWith("/rag/sources/src-uploaded-pdf/file");
    });
    expect(windowOpenSpy).toHaveBeenCalledWith("blob:mock-object-url", "_blank", "noopener,noreferrer");

    windowOpenSpy.mockRestore();
  });
});