import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AuthorIngestion from "../routes/AuthorIngestion";
import { api } from "../lib/api";
import { AuthContext } from "../context/AuthContext";

vi.mock("../lib/api", () => ({
  api: {
    ragAuthors: vi.fn(),
    ragCreateAuthor: vi.fn(),
    ragSources: vi.fn(),
    ragIngestUrls: vi.fn(),
    ragIngestionJobs: vi.fn(),
    ragRetryIngestion: vi.fn(),
  },
}));

const MOCK_AUTHORS = [
  { id: "warren_buffett", name: "Warren Buffett", enabled: true, domains: [], expertise_tags: [], overall_weight: 1.0, role_type: null },
  { id: "charlie_munger", name: "Charlie Munger", enabled: true, domains: [], expertise_tags: [], overall_weight: 1.0, role_type: null },
];

const MOCK_SOURCES = [
  {
    id: "src-1",
    author_id: "warren_buffett",
    url: "https://example.com/article-1",
    source_type: "html",
    status: "ingested",
    hash: null,
    last_ingested_at: "2024-01-01T00:00:00",
    created_at: "2024-01-01T00:00:00",
  },
];

const MOCK_JOBS = [
  {
    id: "job-1",
    source_id: "src-1",
    status: "done",
    failure_category: null,
    error: null,
    stats_json: {},
    started_at: "2024-01-01T00:00:00",
    finished_at: "2024-01-01T00:01:00",
    created_at: "2024-01-01T00:00:00",
  },
];

function renderAuthorIngestion() {
  return render(
    <AuthContext.Provider
      value={{
        user: {
          id: 1,
          username: "demo",
          display_name: "Hitesh",
          email: null,
          is_admin: false,
        },
        loading: false,
        login: async () => {},
        signup: async () => {},
        logout: async () => {},
      }}
    >
      <MemoryRouter initialEntries={["/author-ingestion"]}>
        <Routes>
          <Route path="/author-ingestion" element={<AuthorIngestion />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("AuthorIngestion page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (api.ragAuthors as ReturnType<typeof vi.fn>).mockResolvedValue(MOCK_AUTHORS);
    (api.ragSources as ReturnType<typeof vi.fn>).mockResolvedValue(MOCK_SOURCES);
    (api.ragIngestionJobs as ReturnType<typeof vi.fn>).mockResolvedValue(MOCK_JOBS);
  });

  it("renders the page title with end-user language", async () => {
    renderAuthorIngestion();
    expect(screen.getByText(/Author Ingestion/i)).toBeInTheDocument();
  });

  it("loads and shows author list", async () => {
    renderAuthorIngestion();
    await waitFor(() => {
      expect(api.ragAuthors).toHaveBeenCalled();
    });
    // After authors load, the select dropdown should have options
    await waitFor(() => {
      expect(screen.getByRole("combobox")).toBeInTheDocument();
    });
  });

  it("shows Select Author and Create Author tabs", async () => {
    renderAuthorIngestion();
    expect(screen.getByText(/Select Author/i)).toBeInTheDocument();
    expect(screen.getByText(/Create Author/i)).toBeInTheDocument();
  });

  it("shows create author form when Create Author tab is clicked", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    const createTab = screen.getByText(/Create Author/i);
    await user.click(createTab);
    expect(screen.getByLabelText(/Author ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Display Name/i)).toBeInTheDocument();
  });

  it("shows URL input area with add button after selecting author", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    const select = await screen.findByRole("combobox");
    await user.selectOptions(select, "warren_buffett");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /add another url/i })).toBeInTheDocument();
    });
  });

  it("can add multiple URL input rows", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    const select = await screen.findByRole("combobox");
    await user.selectOptions(select, "warren_buffett");
    const addBtn = await screen.findByRole("button", { name: /add another url/i });
    await user.click(addBtn);
    const inputs = screen.getAllByPlaceholderText(/https:\/\//i);
    expect(inputs.length).toBeGreaterThanOrEqual(2);
  });

  it("shows sources table when author is selected", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();

    await waitFor(() => {
      expect(api.ragAuthors).toHaveBeenCalled();
    });

    const select = await screen.findByRole("combobox");
    await user.selectOptions(select, "warren_buffett");

    await waitFor(() => {
      expect(api.ragSources).toHaveBeenCalledWith("warren_buffett");
    });
  });

  it("shows job status table when author is selected", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();

    await waitFor(() => {
      expect(api.ragAuthors).toHaveBeenCalled();
    });

    const select = await screen.findByRole("combobox");
    await user.selectOptions(select, "warren_buffett");

    await waitFor(() => {
      expect(api.ragIngestionJobs).toHaveBeenCalledWith(
        expect.objectContaining({ author_id: "warren_buffett" }),
      );
    });
  });

  it("submits URLs and calls ragIngestUrls", async () => {
    const user = userEvent.setup();
    const mockResult = {
      author_id: "warren_buffett",
      registered: 1,
      skipped_duplicate: 0,
      jobs_queued: 1,
      sources: [MOCK_SOURCES[0]],
      job_ids: ["job-new-1"],
    };
    (api.ragIngestUrls as ReturnType<typeof vi.fn>).mockResolvedValue(mockResult);

    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());

    const select = await screen.findByRole("combobox");
    await user.selectOptions(select, "warren_buffett");

    const urlInput = await screen.findByPlaceholderText(/https:\/\//i);
    await user.type(urlInput, "https://example.com/new-article");

    const submitBtn = screen.getByRole("button", { name: /start ingestion/i });
    await user.click(submitBtn);

    await waitFor(() => {
      expect(api.ragIngestUrls).toHaveBeenCalledWith(
        "warren_buffett",
        expect.objectContaining({
          urls: expect.arrayContaining(["https://example.com/new-article"]),
        }),
      );
    });
  });

  it("shows create author form with required fields distinct from optional", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    const createTab = screen.getByText(/Create Author/i);
    await user.click(createTab);
    // Required fields should be visible
    expect(screen.getByLabelText(/Author ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Display Name/i)).toBeInTheDocument();
    // Advanced section should exist but optional
    expect(screen.getByText(/Advanced/i)).toBeInTheDocument();
  });

  it("calls ragCreateAuthor when create author form is submitted", async () => {
    const user = userEvent.setup();
    const newAuthor = {
      id: "new_author",
      name: "New Author",
      enabled: true,
      domains: [],
      expertise_tags: [],
      overall_weight: 1.0,
      role_type: null,
    };
    (api.ragCreateAuthor as ReturnType<typeof vi.fn>).mockResolvedValue(newAuthor);

    renderAuthorIngestion();
    const createTab = screen.getByText(/Create Author/i);
    await user.click(createTab);

    await user.type(screen.getByLabelText(/Author ID/i), "new_author");
    await user.type(screen.getByLabelText(/Display Name/i), "New Author");

    const createForm = screen.getByLabelText(/Create new author/i);
    const submitCreateBtn = within(createForm).getByRole("button", { name: /create author/i });
    await user.click(submitCreateBtn);

    await waitFor(() => {
      expect(api.ragCreateAuthor).toHaveBeenCalledWith(
        expect.objectContaining({ id: "new_author", name: "New Author" }),
      );
    });
  });
});
