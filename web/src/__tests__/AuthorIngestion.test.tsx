import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AuthorIngestion from "../routes/AuthorIngestion";
import { api } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import { AuthContext } from "../context/AuthContext";
import type {
  RagAuthorIngestionEventPayload,
  RagIngestionActivity,
  RagIngestionJobRecord,
  RagSourceRecord,
  RealtimeEventEnvelope,
} from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    ragAuthors: vi.fn(),
    ragCreateAuthor: vi.fn(),
    ragIngestionActivity: vi.fn(),
    ragIngestUrls: vi.fn(),
    ragPreviewFanout: vi.fn(),
    ragRetryIngestion: vi.fn(),
  },
}));

vi.mock("../lib/realtime", () => ({
  subscribeToRealtimeTopic: vi.fn(),
}));

const MOCK_AUTHORS = [
  { id: "warren_buffett", name: "Warren Buffett", enabled: true, domains: [], expertise_tags: [], overall_weight: 1.0, role_type: null },
  { id: "charlie_munger", name: "Charlie Munger", enabled: true, domains: [], expertise_tags: [], overall_weight: 1.0, role_type: null },
];

const MOCK_SOURCES: RagSourceRecord[] = [
  {
    id: "src-1",
    author_id: "warren_buffett",
    author_name: "Warren Buffett",
    url: "https://example.com/article-1",
    source_type: "html",
    status: "ingested",
    hash: null,
    last_ingested_at: "2024-01-01T00:00:00",
    created_at: "2024-01-01T00:00:00",
  },
];

const MOCK_JOBS: RagIngestionJobRecord[] = [
  {
    id: "job-1",
    source_id: "src-1",
    batch_id: "batch-1",
    status: "done",
    failure_category: null,
    error: null,
    stats_json: {},
    started_at: "2024-01-01T00:00:00",
    finished_at: "2024-01-01T00:01:00",
    created_at: "2024-01-01T00:00:00",
  },
];

const MOCK_EVENTS: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>[] = [
  {
    id: "event-1",
    topic: "author-ingestion",
    event_name: "source_ingested",
    batch_id: "batch-1",
    author_id: "warren_buffett",
    source_id: "src-1",
    job_id: "job-1",
    status: "ingested",
    created_at: "2024-01-01T00:01:00",
    payload: {
      author: { id: "warren_buffett", name: "Warren Buffett" },
      batch: { id: "batch-1", status: "completed" },
      source: MOCK_SOURCES[0],
      job: MOCK_JOBS[0],
      failure_reason: null,
    },
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
    (api.ragIngestionActivity as ReturnType<typeof vi.fn>).mockResolvedValue({
      topic: "author-ingestion",
      sources: MOCK_SOURCES,
      jobs: MOCK_JOBS,
      events: MOCK_EVENTS,
    } satisfies RagIngestionActivity);
    (subscribeToRealtimeTopic as ReturnType<typeof vi.fn>).mockImplementation((_topic, handlers) => {
      handlers.onStatusChange?.("connected");
      return () => {};
    });
  });

  it("renders the page title with end-user language", () => {
    renderAuthorIngestion();
    expect(screen.getByText(/Author Ingestion/i)).toBeInTheDocument();
  });

  it("loads and shows author list", async () => {
    renderAuthorIngestion();
    await waitFor(() => {
      expect(api.ragAuthors).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect(screen.getByRole("combobox")).toBeInTheDocument();
    });
  });

  it("shows Select Author and Create Author tabs", () => {
    renderAuthorIngestion();
    expect(screen.getByText(/Select Author/i)).toBeInTheDocument();
    expect(screen.getByText(/Create Author/i)).toBeInTheDocument();
  });

  it("shows create author form when Create Author tab is clicked", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await user.click(screen.getByText(/Create Author/i));
    expect(screen.getByLabelText(/Author ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Display Name/i)).toBeInTheDocument();
  });

  it("shows URL input area with add button after selecting author", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /add another url/i })).toBeInTheDocument();
    });
  });

  it("can add multiple URL input rows", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await user.click(await screen.findByRole("button", { name: /add another url/i }));
    expect(screen.getAllByPlaceholderText(/https:\/\//i).length).toBeGreaterThanOrEqual(2);
  });

  it("loads the backend snapshot when an author is selected", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");

    await waitFor(() => {
      expect(api.ragIngestionActivity).toHaveBeenCalledWith("warren_buffett", 100);
    });
  });

  it("renders recent activity from the durable backend snapshot", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");

    expect(await screen.findByText(/Recent Activity/i)).toBeInTheDocument();
    expect(screen.getByText(/Source ingested/i)).toBeInTheDocument();
    expect(screen.getAllByText(/https:\/\/example.com\/article-1/i).length).toBeGreaterThan(0);
  });

  it("submits URLs and calls ragIngestUrls", async () => {
    const user = userEvent.setup();
    (api.ragIngestUrls as ReturnType<typeof vi.fn>).mockResolvedValue({
      author_id: "warren_buffett",
      registered: 1,
      requeued_existing: 0,
      skipped_duplicate: 0,
      jobs_queued: 1,
      sources: [{ ...MOCK_SOURCES[0], id: "src-new", status: "queued" }],
      job_ids: ["job-new-1"],
    });

    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await user.type(await screen.findByPlaceholderText(/https:\/\//i), "https://example.com/new-article");
    await user.click(screen.getByRole("button", { name: /start ingestion/i }));

    await waitFor(() => {
      expect(api.ragIngestUrls).toHaveBeenCalledWith(
        "warren_buffett",
        expect.objectContaining({
          urls: expect.arrayContaining(["https://example.com/new-article"]),
        }),
      );
    });
  });

  it("selective ingestion controls are hidden by default", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await waitFor(() => expect(screen.getByRole("button", { name: /add another url/i })).toBeInTheDocument());

    // The selective controls summary should exist but inputs should not be visible
    expect(screen.getByText(/advanced.*selective ingestion/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/start after heading/i)).not.toBeVisible();
  });

  it("fanout controls are hidden until compendium mode is enabled", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");

    expect(screen.getByLabelText(/compendium.*fanout/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /preview logical documents/i })).not.toBeInTheDocument();
  });

  it("previews logical documents from the advanced fanout workflow", async () => {
    const user = userEvent.setup();
    (api.ragPreviewFanout as ReturnType<typeof vi.fn>).mockResolvedValue({
      mode: "fanout",
      document_count: 1,
      documents: [
        {
          key: "essay-a",
          title: "Essay A",
          author_id: "warren_buffett",
          published_at: null,
          publication_year: 2024,
          venue: null,
          collection: "Letters",
          canonical_work_id: "essay-a",
          canonical_status: "canonical",
          dedupe_priority: 5,
          source_section: "Essay A",
          note_taker: null,
          work_type: "essay",
          parent_key: null,
          metadata: { topic: "moat" },
          selective_ingestion: { include_headings: ["Essay A"] },
        },
      ],
    });

    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await user.click(screen.getByLabelText(/compendium.*fanout/i));
    await user.clear(screen.getByLabelText(/logical key/i));
    await user.type(screen.getByLabelText(/logical key/i), "essay-a");
    await user.type(screen.getByLabelText(/^Title \*/i), "Essay A");
    await user.click(screen.getByRole("button", { name: /preview logical documents/i }));

    await waitFor(() => {
      expect(api.ragPreviewFanout).toHaveBeenCalledWith(
        expect.objectContaining({
          author_id: "warren_buffett",
          ingestion_config: expect.objectContaining({
            mode: "fanout",
            documents: [
              expect.objectContaining({
                key: "essay-a",
                title: "Essay A",
              }),
            ],
          }),
        }),
      );
    });

    expect(await screen.findByText(/Preview ready/i)).toBeInTheDocument();
    expect(screen.getByText("essay-a")).toBeInTheDocument();
  });

  it("shows fanout validation errors returned by the backend preview", async () => {
    const user = userEvent.setup();
    (api.ragPreviewFanout as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("unknown parent"));

    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await user.click(screen.getByLabelText(/compendium.*fanout/i));
    await user.clear(screen.getByLabelText(/logical key/i));
    await user.type(screen.getByLabelText(/logical key/i), "child");
    await user.type(screen.getByLabelText(/^Title \*/i), "Child");
    await user.click(screen.getByRole("button", { name: /preview logical documents/i }));

    expect(await screen.findByText(/unknown parent/i)).toBeInTheDocument();
  });

  it("selective ingestion controls are revealed after expanding advanced section", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await waitFor(() => expect(screen.getByText(/advanced.*selective ingestion/i)).toBeInTheDocument());

    // Click the summary to expand
    await user.click(screen.getByText(/advanced.*selective ingestion/i));

    await waitFor(() => {
      expect(screen.getByLabelText(/start after heading/i)).toBeVisible();
      expect(screen.getByLabelText(/stop before heading/i)).toBeVisible();
      expect(screen.getByLabelText(/include headings only/i)).toBeVisible();
      expect(screen.getByLabelText(/exclude sections/i)).toBeVisible();
    });
  });

  it("sends selective_ingestion payload when fields are filled", async () => {
    const user = userEvent.setup();
    (api.ragIngestUrls as ReturnType<typeof vi.fn>).mockResolvedValue({
      author_id: "warren_buffett",
      registered: 1,
      requeued_existing: 0,
      skipped_duplicate: 0,
      jobs_queued: 1,
      sources: [{ ...MOCK_SOURCES[0], id: "src-sel", status: "queued", selective_options: { start_after: "Intro", stop_before: null, include_headings: [], exclude_sections: [] } }],
      job_ids: ["job-sel-1"],
    });

    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await user.type(await screen.findByPlaceholderText(/https:\/\//i), "https://example.com/selective-article");

    // Expand selective options
    await user.click(screen.getByText(/advanced.*selective ingestion/i));
    await user.type(await screen.findByLabelText(/start after heading/i), "Intro");

    await user.click(screen.getByRole("button", { name: /start ingestion/i }));

    await waitFor(() => {
      expect(api.ragIngestUrls).toHaveBeenCalledWith(
        "warren_buffett",
        expect.objectContaining({
          selective_ingestion: expect.objectContaining({ start_after: "Intro" }),
        }),
      );
    });
  });

  it("does not send selective_ingestion when all fields are empty", async () => {
    const user = userEvent.setup();
    (api.ragIngestUrls as ReturnType<typeof vi.fn>).mockResolvedValue({
      author_id: "warren_buffett",
      registered: 1,
      requeued_existing: 0,
      skipped_duplicate: 0,
      jobs_queued: 1,
      sources: [{ ...MOCK_SOURCES[0], id: "src-nosel", status: "queued" }],
      job_ids: ["job-nosel-1"],
    });

    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await user.type(await screen.findByPlaceholderText(/https:\/\//i), "https://example.com/no-selective");
    await user.click(screen.getByRole("button", { name: /start ingestion/i }));

    await waitFor(() => {
      const call = (api.ragIngestUrls as ReturnType<typeof vi.fn>).mock.calls[0];
      expect(call[1].selective_ingestion).toBeNull();
    });
  });

  it("submits fanout definitions without raw JSON editing", async () => {
    const user = userEvent.setup();
    (api.ragIngestUrls as ReturnType<typeof vi.fn>).mockResolvedValue({
      author_id: "warren_buffett",
      registered: 1,
      requeued_existing: 0,
      skipped_duplicate: 0,
      jobs_queued: 1,
      sources: [{ ...MOCK_SOURCES[0], id: "src-fanout", status: "queued" }],
      job_ids: ["job-fanout-1"],
    });

    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await user.type(await screen.findByPlaceholderText(/https:\/\//i), "https://example.com/compendium");
    await user.click(screen.getByLabelText(/compendium.*fanout/i));
    await user.clear(screen.getByLabelText(/logical key/i));
    await user.type(screen.getByLabelText(/logical key/i), "essay-a");
    await user.type(screen.getByLabelText(/^Title \*/i), "Essay A");
    await user.type(screen.getByLabelText(/collection/i), "Collected Essays");
    await user.click(screen.getByRole("button", { name: /start ingestion/i }));

    await waitFor(() => {
      expect(api.ragIngestUrls).toHaveBeenCalledWith(
        "warren_buffett",
        expect.objectContaining({
          ingestion_config: expect.objectContaining({
            mode: "fanout",
            documents: [
              expect.objectContaining({
                key: "essay-a",
                title: "Essay A",
                collection: "Collected Essays",
              }),
            ],
          }),
        }),
      );
    });
  });

  it("shows create author form with required fields distinct from optional", async () => {
    const user = userEvent.setup();
    renderAuthorIngestion();
    await user.click(screen.getByText(/Create Author/i));
    expect(screen.getByLabelText(/Author ID/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Display Name/i)).toBeInTheDocument();
    expect(screen.getByText(/Advanced/i)).toBeInTheDocument();
  });

  it("calls ragCreateAuthor when create author form is submitted", async () => {
    const user = userEvent.setup();
    (api.ragCreateAuthor as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: "new_author",
      name: "New Author",
      enabled: true,
      domains: [],
      expertise_tags: [],
      overall_weight: 1.0,
      role_type: null,
    });

    renderAuthorIngestion();
    await user.click(screen.getByText(/Create Author/i));
    await user.type(screen.getByLabelText(/Author ID/i), "new_author");
    await user.type(screen.getByLabelText(/Display Name/i), "New Author");

    const createForm = screen.getByLabelText(/Create new author/i);
    await user.click(within(createForm).getByRole("button", { name: /create author/i }));

    await waitFor(() => {
      expect(api.ragCreateAuthor).toHaveBeenCalledWith(
        expect.objectContaining({ id: "new_author", name: "New Author" }),
      );
    });
  });

  it("subscribes to realtime updates instead of using polling timers", () => {
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    renderAuthorIngestion();

    expect(subscribeToRealtimeTopic).toHaveBeenCalledWith(
      "author-ingestion",
      expect.objectContaining({
        onEvent: expect.any(Function),
        onStatusChange: expect.any(Function),
      }),
    );
    expect(setIntervalSpy).not.toHaveBeenCalled();
    setIntervalSpy.mockRestore();
  });

  it("applies realtime source and job updates for the selected author", async () => {
    let realtimeHandlers: { onEvent?: (event: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>) => void } = {};
    (subscribeToRealtimeTopic as ReturnType<typeof vi.fn>).mockImplementation((_topic, handlers) => {
      realtimeHandlers = handlers;
      handlers.onStatusChange?.("connected");
      return () => {};
    });

    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");
    await screen.findByText(/Recent Activity/i);

    await act(async () => {
      realtimeHandlers.onEvent?.({
        id: "event-2",
        topic: "author-ingestion",
        event_name: "source_failed",
        batch_id: "batch-2",
        author_id: "warren_buffett",
        source_id: "src-1",
        job_id: "job-1",
        status: "failed",
        created_at: "2024-01-01T00:02:00",
        payload: {
          author: { id: "warren_buffett", name: "Warren Buffett" },
          batch: { id: "batch-2", status: "completed" },
          source: { ...MOCK_SOURCES[0], status: "failed" },
          job: { ...MOCK_JOBS[0], status: "failed", failure_category: "network_error", error: "timeout" },
          failure_reason: "timeout",
        },
      });
    });

    expect(await screen.findAllByText(/Failed/i)).not.toHaveLength(0);
    expect(screen.getByText(/timeout/i)).toBeInTheDocument();
  });

  it("renders logical-document outcomes from ingestion jobs", async () => {
    (api.ragIngestionActivity as ReturnType<typeof vi.fn>).mockResolvedValue({
      topic: "author-ingestion",
      sources: MOCK_SOURCES,
      jobs: [
        {
          ...MOCK_JOBS[0],
          stats_json: {
            documents: [
              { key: "essay-a", status: "created", author_id: "warren_buffett" },
              { key: "essay-b", status: "rejected", author_id: "warren_buffett", failure_category: "low_quality_extraction" },
            ],
          },
        },
      ],
      events: MOCK_EVENTS,
    } satisfies RagIngestionActivity);

    const user = userEvent.setup();
    renderAuthorIngestion();
    await waitFor(() => expect(api.ragAuthors).toHaveBeenCalled());
    await user.selectOptions(await screen.findByRole("combobox"), "warren_buffett");

    expect(await screen.findByText(/1 Created \/ 1 Rejected/i)).toBeInTheDocument();
    await user.click(screen.getByText(/View outcomes/i));
    expect(screen.getByText("essay-a")).toBeInTheDocument();
    expect(screen.getByText("essay-b")).toBeInTheDocument();
    expect(screen.getByText(/low_quality_extraction/i)).toBeInTheDocument();
  });
});
