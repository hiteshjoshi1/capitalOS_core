import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import IntelligenceOverview from "../routes/IntelligenceOverview";
import { api } from "../lib/api";
import type { ResearchSummary } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    researchSummary: vi.fn(),
  },
}));

const mockApi = vi.mocked(api, true);

const SUMMARY: ResearchSummary = {
  ai_sage: { chats_total: 34, chats_today: 12 },
  author_corpus: { author_count: 12, document_count: 182 },
  ingestion_queue: { running_count: 2, queued_count: 0, failed_count: 0, last_job_at: "6 minutes ago" },
};

function renderPage() {
  return render(
    <MemoryRouter>
      <IntelligenceOverview />
    </MemoryRouter>,
  );
}

describe("IntelligenceOverview (Research Overview)", () => {
  it("renders live stat cards and jump-in cards from the research summary", async () => {
    mockApi.researchSummary.mockResolvedValue(SUMMARY);
    renderPage();

    await waitFor(() => expect(screen.getByText("34")).toBeInTheDocument());

    expect(screen.getByText("AI Sage chats")).toBeInTheDocument();
    expect(screen.getByText("This month · 12 today")).toBeInTheDocument();
    expect(screen.getByText("182 docs")).toBeInTheDocument();
    expect(screen.getByText("Across 12 authors")).toBeInTheDocument();
    expect(screen.getByText("2 running")).toBeInTheDocument();
    expect(screen.getByText("0 failed · last job 6 minutes ago")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: /Open AI Sage/ })).toHaveAttribute("href", "/ai-sage");
    expect(screen.getByRole("link", { name: /Open Author Library/ })).toHaveAttribute("href", "/author-library");
    expect(screen.getByRole("link", { name: /Ingest author writings/ })).toHaveAttribute("href", "/author-ingestion");
    expect(screen.getByRole("link", { name: /Preview/ })).toHaveAttribute("href", "/companies");

    expect(screen.queryByText("Recent activity")).not.toBeInTheDocument();
  });

  it("shows 'Idle' and 'queued' states accurately instead of mislabeling everything as running", async () => {
    mockApi.researchSummary.mockResolvedValue({
      ...SUMMARY,
      ingestion_queue: { running_count: 0, queued_count: 3, failed_count: 1, last_job_at: "2 days ago" },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("3 queued")).toBeInTheDocument());

    mockApi.researchSummary.mockResolvedValue({
      ...SUMMARY,
      ingestion_queue: { running_count: 0, queued_count: 0, failed_count: 0, last_job_at: null },
    });
    renderPage();
    await waitFor(() => expect(screen.getAllByText("Idle").length).toBeGreaterThan(0));
  });
});
