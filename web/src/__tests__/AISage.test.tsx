import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AISage from "../routes/AISage";
import { api } from "../lib/api";
import { AuthContext } from "../context/AuthContext";

vi.mock("../lib/api", () => ({
  api: {
    aiSageQuery: vi.fn(),
  },
}));

function renderAISage() {
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
      <MemoryRouter initialEntries={["/ai-sage"]}>
        <Routes>
          <Route path="/ai-sage" element={<AISage />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
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
      ranking_score: 0.91,
      metadata: {
        document_id: "doc-buffett",
        title: "Letter",
        source_url: "https://example.com/letters",
        context_text:
          "A wonderful business can compound capital over time. It also benefits from durable customer demand and disciplined capital allocation.",
        reranker_score: 0.77,
      },
    },
    {
      chunk_id: "chunk-2",
      author_id: "nick_sleep",
      author_name: "Nick Sleep",
      text: "Businesses that share scale benefits with customers build durable advantages.",
      similarity: 0.85,
      ranking_score: 0.85,
      metadata: {
        document_id: "doc-sleep",
        title: "Nomad Letters",
      },
    },
  ],
  critique: "These views may underweight the role of execution and management quality in sustaining advantage.",
  evidence_sufficient: true,
  weak_evidence_note: null,
};

describe("AISage Concept Mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders personalized greeting before any query", () => {
    renderAISage();
    expect(screen.getByRole("heading", { name: "Hello Hitesh" })).toBeInTheDocument();
    expect(screen.getByText("What insights are we discovering today?")).toBeInTheDocument();
    expect(screen.queryByText("Start Here")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AI Sage" })).not.toBeInTheDocument();
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

  it("shows a waiting state while the answer is loading", async () => {
    let resolveQuery: (value: typeof MOCK_CONCEPT_RESULT) => void = () => {
      throw new Error("resolveQuery not assigned");
    };
    vi.mocked(api.aiSageQuery).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveQuery = resolve;
        }),
    );

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(screen.getByRole("status")).toHaveTextContent("Working through your question...");

    resolveQuery(MOCK_CONCEPT_RESULT);

    expect(
      await screen.findByText(/Review the top ranked passages below/i),
    ).toBeInTheDocument();
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
      screen.getByText(/Review the top ranked passages below/i),
    ).toBeInTheDocument();
  });

  it("does not render old perspective scaffolding", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    await screen.findByText("Top Passages");
    expect(screen.queryByText("Relevant Authors")).not.toBeInTheDocument();
    expect(screen.queryByText("Perspectives")).not.toBeInTheDocument();
    expect(screen.queryByText("Score 4.50")).not.toBeInTheDocument();
    expect(screen.queryByText("Stay within competence")).not.toBeInTheDocument();
  });

  it("renders compact guidance as the lead assistant answer", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(
      await screen.findByText(/Review the top ranked passages below/i),
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

  it("renders top passages instead of heuristic suggested readings", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    expect(await screen.findByText("Top Passages")).toBeInTheDocument();
    expect(screen.queryByText("Suggested Readings")).not.toBeInTheDocument();
    expect(screen.getByText("Passage 1")).toBeInTheDocument();
    expect(screen.getByText("Passage 2")).toBeInTheDocument();
    expect(screen.getByText("Rank score 0.91")).toBeInTheDocument();
    expect(screen.getByText("Reranked")).toBeInTheDocument();
  });

  it("shows read more links for all ranked passages and optional surrounding context", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_CONCEPT_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    await screen.findByText("Top Passages");
    expect(screen.getByText("Show surrounding context")).toBeInTheDocument();
    const readMoreLinks = screen.getAllByRole("link", { name: "Read more" });
    expect(readMoreLinks).toHaveLength(2);
    expect(readMoreLinks[0]).toHaveAttribute(
      "href",
      "/author-library/warren_buffett/documents/doc-buffett",
    );
    expect(readMoreLinks[1]).toHaveAttribute(
      "href",
      "/author-library/nick_sleep/documents/doc-sleep",
    );
  });

  it("expands from top 5 to top 10 ranked passages when configured", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue({
      ...MOCK_CONCEPT_RESULT,
      best_passages: Array.from({ length: 7 }, (_, index) => ({
        chunk_id: `chunk-${index + 1}`,
        author_id: "charlie_munger",
        author_name: "Charlie Munger",
        text: `Passage text ${index + 1}`,
        similarity: 0.99 - index * 0.01,
        ranking_score: 100 - index,
        metadata: {
          document_id: `doc-${index + 1}`,
          source_url: `https://example.com/${index + 1}`,
        },
      })),
    });

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    await screen.findByText("Top Passages");
    expect(screen.queryByText("Passage 6")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Top 7" }));

    expect(screen.getByText("Passage 6")).toBeInTheDocument();
    expect(screen.getByText("Passage 7")).toBeInTheDocument();
  });

  it("shows weak evidence note when corpus is insufficient", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue({
      ...MOCK_CONCEPT_RESULT,
      evidence_sufficient: false,
      weak_evidence_note:
        "The author corpus does not contain passages strongly relevant to this question.",
      critique: null,
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
      critique: null,
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
        weak_evidence_note: "Network effects matter when they reinforce user value and lower customer acquisition costs over time.",
      });

    const user = userEvent.setup();
    renderAISage();

    const input = screen.getByPlaceholderText(/Ask AI Sage anything/i);
    await user.type(input, "What makes a good business?{Enter}");
    await screen.findByText(/Review the top ranked passages below/i);

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

const MOCK_THESIS_RESULT = {
  query: "Here is my thesis on Tencent Music. Pressure test it.",
  mode: "thesis" as const,
  best_passages: [
    {
      chunk_id: "chunk-1",
      author_id: "warren_buffett",
      author_name: "Warren Buffett",
      text: "A wonderful business can compound capital over time.",
      similarity: 0.88,
      metadata: { title: "Letter", source_url: "https://example.com/letters" },
    },
  ],
  critique: "The thesis may overestimate the durability of the moat given rising competition from short-video platforms for music consumption.",
  evidence_sufficient: true,
  weak_evidence_note: null,
  thesis_question: "Is Tencent Music's moat durable enough to support a long-term investment thesis?",
  pushback_questions: [
    "How does Tencent Music's licensing cost structure compare to its international peers?",
    "What is the risk that short-video platforms disintermediate music discovery?",
    "How has ARPU trended versus subscriber growth — is monetisation improving or diluting?",
  ],
  missing_information: [
    "Recent earnings transcript commentary on licensing renewal costs",
    "Competitive share data vs Douyin/TikTok for music engagement",
  ],
  key_facts: [
    "Tencent Music reported 88M paying subscribers in the most recent quarter.",
    "Gross margins have expanded from 27% to 34% over three years.",
  ],
  updated_thesis_view: {
    stronger: ["Platform scale and brand recognition remain durable."],
    weaker: ["Licensing cost inflation could compress future margins."],
    unresolved: ["Whether short-video platform competition materially erodes music engagement."],
  },
  live_sources: [
    {
      url: "https://sec.gov/tme-20f",
      title: "Tencent Music 20-F Filing",
      snippet: "Paid subscribers grew 14% year-over-year.",
      source_type: "filing" as const,
    },
    {
      url: "https://example.com/article",
      title: "Streaming Competition Analysis",
      snippet: "Short-video platforms are capturing more music discovery.",
      source_type: "web" as const,
    },
  ],
  follow_up_questions: [
    "What does management say about social entertainment revenue declining?",
    "How is Tencent Music adapting to the short-video threat?",
  ],
};

describe("AISage Thesis Mode", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders thesis question section", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(
      await screen.findByText("Thesis / Question"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Is Tencent Music's moat durable/i),
    ).toBeInTheDocument();
  });

  it("renders key pushback questions", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(await screen.findByText("Key Pushback Questions")).toBeInTheDocument();
    expect(screen.getByText(/licensing cost structure/i)).toBeInTheDocument();
    expect(screen.getByText(/short-video platforms disintermediate/i)).toBeInTheDocument();
  });

  it("renders missing information section", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(await screen.findByText("Missing Information")).toBeInTheDocument();
    expect(screen.getByText(/licensing renewal costs/i)).toBeInTheDocument();
  });

  it("renders key facts section", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(await screen.findByText("Key Facts")).toBeInTheDocument();
    expect(screen.getByText(/88M paying subscribers/i)).toBeInTheDocument();
  });

  it("renders critique section in thesis mode", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(await screen.findByText("Critique")).toBeInTheDocument();
    expect(screen.getAllByText(/short-video platforms/i).length).toBeGreaterThan(0);
  });

  it("renders updated thesis view with stronger/weaker/unresolved", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(await screen.findByText("Updated Thesis View")).toBeInTheDocument();
    expect(screen.getByText("Looks Stronger")).toBeInTheDocument();
    expect(screen.getByText("Looks Weaker")).toBeInTheDocument();
    expect(screen.getByText("Still Unresolved")).toBeInTheDocument();
    expect(screen.getByText(/Platform scale and brand recognition/i)).toBeInTheDocument();
    expect(screen.getByText(/Licensing cost inflation/i)).toBeInTheDocument();
  });

  it("renders follow-up questions as a list (not auto-researched)", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(await screen.findByText("Follow-up Questions to Explore")).toBeInTheDocument();
    expect(screen.getByText(/social entertainment revenue declining/i)).toBeInTheDocument();
    // The follow-up questions are shown but not auto-submitted
    expect(api.aiSageQuery).toHaveBeenCalledTimes(1);
  });

  it("shows live sources in the collapsible additional sources panel", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    const showSources = await screen.findByRole("button", { name: /Show Additional Sources/i });
    await user.click(showSources);

    // Live sources are visible after expanding
    expect(screen.getByText("Tencent Music 20-F Filing")).toBeInTheDocument();
    expect(screen.getByText("SEC Filing")).toBeInTheDocument();
    // Corpus passages remain visible in the main ranked list
    expect(screen.getByText("Thinker Corpus")).toBeInTheDocument();
  });

  it("distinguishes corpus sources from live research sources in the UI", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    const showSources = await screen.findByRole("button", { name: /Show Additional Sources/i });
    await user.click(showSources);

    // Corpus pill
    expect(screen.getByText("Thinker Corpus")).toBeInTheDocument();
    // Live source type pill
    expect(screen.getByText("SEC Filing")).toBeInTheDocument();
  });

  it("does not render thesis sections in concept mode", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue({
      ...MOCK_CONCEPT_RESULT,
      mode: "concept",
      thesis_question: null,
      pushback_questions: [],
      missing_information: [],
      key_facts: [],
      updated_thesis_view: null,
      live_sources: [],
      follow_up_questions: [],
    });

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "What makes a good business?{Enter}",
    );

    await screen.findByText(/Review the top ranked passages below/i);

    expect(screen.queryByText("Key Pushback Questions")).not.toBeInTheDocument();
    expect(screen.queryByText("Missing Information")).not.toBeInTheDocument();
    expect(screen.queryByText("Updated Thesis View")).not.toBeInTheDocument();
    expect(screen.queryByText("Follow-up Questions to Explore")).not.toBeInTheDocument();
  });

  it("shows compact guidance as the lead answer in thesis mode", async () => {
    vi.mocked(api.aiSageQuery).mockResolvedValue(MOCK_THESIS_RESULT);

    const user = userEvent.setup();
    renderAISage();

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything/i),
      "Here is my thesis on Tencent Music. Pressure test it.{Enter}",
    );

    expect(
      await screen.findByText(/Review the pressure test, ranked passages, and supporting sources below/i),
    ).toBeInTheDocument();
  });
});
