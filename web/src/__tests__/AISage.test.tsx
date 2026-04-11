import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AISage from "../routes/AISage";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    ragQuery: vi.fn(),
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

  it("submits with Enter and renders the answer with hidden sources by default", async () => {
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

    const prompt = screen.getByPlaceholderText(
      /Ask AI Sage anything about a business/i,
    );

    await user.type(prompt, "What matters most?");
    await user.keyboard("{Enter}");

    expect(api.ragQuery).toHaveBeenCalledWith({
      query: "What matters most?",
      top_k: 8,
    });

    expect(await screen.findByText("Answer")).toBeInTheDocument();
    expect(screen.getByText("Your Question")).toBeInTheDocument();
    expect(screen.getByText("Focus on business quality and capital allocation.")).toBeInTheDocument();
    expect(screen.getByText("Relevant Author Perspectives")).toBeInTheDocument();
    expect(screen.getByText("Warren Buffett")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show Sources (1)" })).toBeInTheDocument();
    expect(screen.queryByText(/A wonderful business can compound/i)).not.toBeInTheDocument();
  });

  it("shows evidence only after the user requests it", async () => {
    vi.mocked(api.ragQuery).mockResolvedValue({
      query: "What matters most?",
      mode: "ask",
      selected_authors: [],
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

    await user.type(
      screen.getByPlaceholderText(/Ask AI Sage anything about a business/i),
      "What matters most?{enter}",
    );

    const showSources = await screen.findByRole("button", { name: "Show Sources (1)" });
    expect(screen.queryByText(/A wonderful business can compound/i)).not.toBeInTheDocument();

    await user.click(showSources);

    expect(screen.getByText(/A wonderful business can compound capital over time/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hide Sources" })).toBeInTheDocument();
  });

  it("fills the prompt from an example chip", async () => {
    const user = userEvent.setup();
    renderAISage();

    await user.click(screen.getByRole("button", { name: "Open starter prompts" }));
    await user.click(
      screen.getByRole("button", {
        name: /If Buffett and Nick Sleep were studying Tencent Music/i,
      }),
    );

    expect(screen.getByPlaceholderText(/Ask AI Sage anything about a business/i)).toHaveValue(
      "If Buffett and Nick Sleep were studying Tencent Music, what questions would they ask first?",
    );
  });
});
