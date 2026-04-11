import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AISage from "../routes/AISage";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    ragRetrieve: vi.fn(),
    ragQuery: vi.fn(),
    ragCompanyContext: vi.fn(),
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

describe("AISage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("submits ask mode and renders answer, selected authors, and evidence", async () => {
    vi.mocked(api.ragQuery).mockResolvedValue({
      query: "What matters most?",
      mode: "ask",
      selected_authors: [
        {
          author_id: "warren_buffett",
          name: "Warren Buffett",
          score: 4.5,
          domains: ["investing"],
          expertise_tags: ["capital_allocation"],
          match_reason: ["domain_match:investing"],
          worldview: "Focus on quality and returns on capital.",
          key_maxims: ["Stay within competence"],
        },
      ],
      evidence_chunks: [
        {
          chunk_id: "chunk-1",
          author_id: "warren_buffett",
          author_name: "Warren Buffett",
          text: "A wonderful business can compound capital over time.",
          similarity: 0.91,
          metadata: { title: "Letter" },
        },
      ],
      answer: "Focus on business quality and capital allocation.",
      missing_information: null,
      evidence_sufficient: true,
    });

    const user = userEvent.setup();
    renderAISage();

    await user.clear(
      screen.getByPlaceholderText(
        "Ask a grounded question, for example: What does Warren Buffett emphasize about durable moats?",
      ),
    );
    await user.type(
      screen.getByPlaceholderText(
        "Ask a grounded question, for example: What does Warren Buffett emphasize about durable moats?",
      ),
      "What matters most?",
    );
    await user.click(screen.getByRole("button", { name: "Ask AI Sage" }));

    expect(api.ragQuery).toHaveBeenCalledWith({
      query: "What matters most?",
      top_k: 8,
      author_id: undefined,
    });
    expect(await screen.findByText("Grounded Answer")).toBeInTheDocument();
    expect(screen.getAllByText("Warren Buffett")).toHaveLength(2);
    expect(screen.getByText("Focus on business quality and capital allocation.")).toBeInTheDocument();
    expect(screen.getByText(/A wonderful business can compound capital/i)).toBeInTheDocument();
  });

  it("submits company context mode and renders relevant author lenses", async () => {
    vi.mocked(api.ragCompanyContext).mockResolvedValue({
      company: "Amazon",
      question: "Which lenses matter?",
      relevant_author_lenses: [
        {
          author_id: "nick_sleep",
          name: "Nick Sleep",
          score: 3.7,
          domains: ["investing"],
          expertise_tags: ["customer_focus"],
          match_reason: ["tag_match:customer_focus"],
          worldview: "Customer obsession compounds over long periods.",
          key_maxims: ["Scale through trust"],
        },
      ],
      evidence_pack: [],
      evidence_sufficient: false,
    });

    const user = userEvent.setup();
    renderAISage();

    await user.click(screen.getByRole("button", { name: "Company Context" }));
    await user.type(screen.getByPlaceholderText("Company name, for example Apple"), "Amazon");
    await user.type(
      screen.getByPlaceholderText(
        "Ask a company-specific question, for example: How should we think about moat, capital allocation, and holding quality?",
      ),
      "Which lenses matter?",
    );
    await user.click(screen.getByRole("button", { name: "Build Company Context" }));

    expect(api.ragCompanyContext).toHaveBeenCalledWith({
      company: "Amazon",
      question: "Which lenses matter?",
      top_k: 8,
    });
    expect(await screen.findByText("Nick Sleep")).toBeInTheDocument();
    expect(screen.getByText(/No Evidence Found/i)).toBeInTheDocument();
  });
});
