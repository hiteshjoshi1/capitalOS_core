import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AISage from "../routes/AISage";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    aiSageQuery: vi.fn(),
  },
}));

function renderAISage() {
  return render(
    <MemoryRouter initialEntries={["/ai-sage"]}>
      <Routes>
        <Route path="/ai-sage" element={<AISage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const MOCK_CONCEPT_RESULT = {
  query: "What makes a good business?",
  best_passages: [
    {
      chunk_id: "chunk-1",
      author_id: "warren_buffett",
      author_name: "Warren Buffett",
      text: "A wonderful business can compound capital over time.",
      similarity: 0.91,
      metadata: { title: "Letter", source_url: "https://example.com/letters" },
    },
    {
      chunk_id: "chunk-2",
      author_id: "nick_sleep",
      author_name: "Nick Sleep",
      text: "Businesses that share scale benefits with customers build durable advantages.",
      similarity: 0.85,
      metadata: { title: "Nomad Letters" },
    },
  ],
  author_views: [
    {
      author_id: "warren_buffett",
      author_name: "Warren Buffett",
      view: "A good business earns high returns on capital with durable competitive advantage.",
      key_passages: ["A wonderful business can compound capital over time."],
    },
    {
      author_id: "nick_sleep",
      author_name: "Nick Sleep",
      view: "A good business is a destination — customers return because value compounds on their behalf.",
      key_passages: ["Businesses that share scale benefits with customers build durable advantages."],
    },
  ],
  synthesis: "Both authors agree that a good business earns high returns over a long horizon, but Buffett focuses on competitive moat while Sleep emphasises customer-aligned compounding.",
  critique: "These views may underweight the role of execution and management quality in sustaining advantage.",
  suggested_readings: [
    {
      author_id: "warren_buffett",
      author_name: "Warren Buffett",
      passage: "A wonderful business can compound capital over time.",
      source_url: "https://example.com/letters",
      reason: "Top-matched passage from Warren Buffett for this concept.",
    },
  ],
  evidence_sufficient: true,
  weak_evidence_note: null,
};

describe("AISage Concept Mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders welcome state before any query", () => {
    renderAISage();
    expect(screen.getByText("Start Here")).toBeInTheDocument();
  });

  it("submits with Enter and calls aiSageQuery", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    const input = screen.getByPlaceholderText(/Ask AI Sage anything/i);
    await user.type(input, "What makes a good business?");
    await user.keyboard("{Enter}");

    expect(api.aiSageQuery).toHaveBeenCalledWith({
      query: "What makes a good business?",
      top_k: 12,
    });
  });

  it("submits with the send button", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    const input = screen.getByPlaceholderText(/Ask AI Sage anything/i);
    await user.type(input, "How should I think about network effects?");
    await user.click(screen.getByRole("button", { name: /Send query/i }));

    expect(api.aiSageQuery).toHaveBeenCalledWith({
      query: "How should I think about network effects?",
      top_k: 12,
    });
  });

  it("renders question echo after submit", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(await screen.findByText("What makes a good business?")).toBeInTheDocument();
    expect(
      screen.getByText(/Both authors agree that a good business/i),
    ).toBeInTheDocument();
  });

  it("does not render repeated author metadata cards", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    await screen.findByText("Perspectives");
    expect(screen.queryByText("Relevant Authors")).not.toBeInTheDocument();
    expect(screen.queryByText("Score 4.50")).not.toBeInTheDocument();
    expect(screen.queryByText("Stay within competence")).not.toBeInTheDocument();
  });

  it("renders distinct author perspectives inside the assistant answer", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(await screen.findByText("Perspectives")).toBeInTheDocument();
    expect(
      screen.getByText(/A good business earns high returns on capital/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/A good business is a destination/i),
    ).toBeInTheDocument();
  });

  it("renders the synthesis as the lead assistant answer", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(
      await screen.findByText(/Both authors agree that a good business/i),
    ).toBeInTheDocument();
  });

  it("renders critique section", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(await screen.findByText("Critique")).toBeInTheDocument();
    expect(
      screen.getByText(/These views may underweight/i),
    ).toBeInTheDocument();
  });

  it("renders suggested readings section", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(await screen.findByText("Suggested Readings")).toBeInTheDocument();
  });

  it("hides passages by default and shows them on demand", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    const showSources = await screen.findByRole("button", { name: /Show Sources/i });

    // Evidence text should not appear in the sources panel (hidden), though it may
    // appear in key_passages within author views. Confirm the source panel toggle works.
    expect(screen.queryByText(/Passage 1/i)).not.toBeInTheDocument();

    await user.click(showSources);

    // After clicking, the evidence panel opens and shows passage labels
    expect(screen.getByText("Passage 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide Sources" })).toBeInTheDocument();
  });

  it("shows weak evidence note when corpus is insufficient", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue({
      ...MOCK_CONCEPT_RESULT,
      evidence_sufficient: false,
      weak_evidence_note:
        "The author corpus does not contain passages strongly relevant to this question.",
      author_views: [],
      synthesis: null,
      critique: null,
      suggested_readings: [],
      best_passages: [],
    });

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "obscure question{Enter}",
    );

    expect(
      await screen.findByText(/does not contain passages strongly relevant/i),
    ).toBeInTheDocument();
  });

  it("shows no strong answer card when evidence and views are absent", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue({
      ...MOCK_CONCEPT_RESULT,
      evidence_sufficient: false,
      weak_evidence_note: "Corpus is thin.",
      author_views: [],
      synthesis: null,
      critique: null,
      suggested_readings: [],
      best_passages: [],
    });

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "obscure question{Enter}",
    );

    expect(await screen.findByText("Corpus is thin.")).toBeInTheDocument();
  });

  it("keeps prior question and answer turns in the thread", async () => {
    vi.mocked(api.aiSageQuery)
      .mockResolvedValueOnce(MOCK_CONCEPT_RESULT)
      .mockResolvedValueOnce({
        ...MOCK_CONCEPT_RESULT,
        query: "How should I think about network effects?",
        synthesis: "Network effects matter when they reinforce user value and lower customer acquisition costs over time.",
      });

    const user = userEvent.setup();
    renderAISage();

    const input = screen.getByPlaceholderText(/Ask AI Sage anything/i);
    await user.type(input, "What makes a good business?{Enter}");
    await screen.findByText(/Both authors agree that a good business/i);

    await user.type(screen.getByPlaceholderText(/Ask AI Sage anything/i), "How should I think about network effects?{Enter}");
    await screen.findByText(/Network effects matter when they reinforce user value/i);

    expect(screen.getByText("What makes a good business?")).toBeInTheDocument();
    expect(screen.getByText("How should I think about network effects?")).toBeInTheDocument();
  });

  it("fills the prompt from a starter prompt chip", async () => {
    const user = userEvent.setup();
    renderAISage();

    await user.click(screen.getByRole("button", { name: "Open starter prompts" }));
    await user.click(
      screen.getByRole("button", {
        name: /What makes a good business/i,
      }),
    );

    expect(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
    ).toHaveValue("What makes a good business?");
  });

  it("does not expose internal mode fields in the UI", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    await screen.findByText("What makes a good business?");

    // No internal mode selector or RAG jargon visible
    expect(screen.queryByText(/retrieve/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/RAG research/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/company context/i)).not.toBeInTheDocument();
  });
});
