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

  it("renders an author gallery with metadata-rich cards", async () => {
    renderAuthorLibrary("/author-library");

    expect(await screen.findByRole("heading", { name: "Author Library" })).toBeInTheDocument();
    expect(api.ragLibraryAuthors).toHaveBeenCalled();
    expect(await screen.findByRole("img", { name: "Photo of Warren Buffett" })).toHaveAttribute(
      "src",
      "https://example.com/buffett.jpg",
    );
    expect(screen.getByText(/Berkshire Hathaway/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse Warren Buffett's library" })).toHaveAttribute(
      "href",
      "/author-library/warren_buffett",
    );
  });

  it("renders grouped child links and document metadata on the author detail page", async () => {
    renderAuthorLibrary("/author-library/warren_buffett");

    expect((await screen.findAllByRole("heading", { name: "Warren Buffett" })).length).toBeGreaterThan(0);
    await waitFor(() => {
      expect(api.ragAuthorLibrary).toHaveBeenCalledWith("warren_buffett");
    });

    expect(await screen.findByRole("heading", { name: "Letters" })).toBeInTheDocument();
    expect(screen.getByText("Publication Year: 1987")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /1987 Shareholder Letter/i })).toHaveAttribute(
      "href",
      "/author-library/warren_buffett/documents/doc-1987",
    );
    expect(screen.getByRole("link", { name: /Owner Earnings/i })).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.textContent === "Primary grouping: Collection")).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => element?.textContent === "Source: https://example.com/owner-earnings.pdf"),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("author-library-reader-text")).not.toBeInTheDocument();
  });

  it("opens the reader, supports fullscreen mode, and follows related document links", async () => {
    const user = userEvent.setup();
    renderAuthorLibrary("/author-library/warren_buffett/documents/doc-1987");

    expect(await screen.findByTestId("author-library-reader-text")).toHaveTextContent(
      "Stored logical document text for the 1987 shareholder letter.",
    );
    expect(screen.getByRole("link", { name: /Open provenance link/i })).toHaveAttribute(
      "href",
      "https://example.com/1987-letter",
    );

    await user.click(screen.getByRole("button", { name: "Fullscreen" }));
    expect(HTMLDivElement.prototype.requestFullscreen).toHaveBeenCalled();

    await user.click(screen.getByRole("link", { name: /1987 Shareholder Letter Notes/i }));
    await waitFor(() => {
      expect(api.ragLibraryDocument).toHaveBeenCalledWith("doc-1987-notes");
    });

    expect(await screen.findByTestId("author-library-reader-text")).toHaveTextContent(
      "Editorial notes linked from the main logical document.",
    );
    expect(screen.getByText("Parent document")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Exit fullscreen" }));
    expect(document.exitFullscreen).toHaveBeenCalled();
  });
});
