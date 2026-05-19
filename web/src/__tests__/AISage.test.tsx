import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import AISage from "../routes/AISage";
import { AuthContext } from "../context/AuthContext";
import {
  api,
  streamAiSageChatMessage,
  type AISageChatDetail,
  type AISageChatMessage,
  type AISageChatSummary,
} from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    aiSageChats: vi.fn(),
    aiSageCreateChat: vi.fn(),
    aiSageGetChat: vi.fn(),
    aiSageUpdateChat: vi.fn(),
    aiSageDeleteChat: vi.fn(),
    aiSageSearchChats: vi.fn(),
    aiSageRetryMessage: vi.fn(),
  },
  streamAiSageChatMessage: vi.fn(),
}));

const CHAT_SUMMARY: AISageChatSummary = {
  id: "chat-1",
  title: "Moat review",
  preview: "Grounded passages from Warren Buffett:",
  status: "answered",
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:05:00Z",
  last_activity_at: "2026-05-01T10:04:00Z",
  pinned_at: null,
};

const CHAT_DETAIL: AISageChatDetail = {
  id: "chat-1",
  title: "Moat review",
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:05:00Z",
  last_activity_at: "2026-05-01T10:04:00Z",
  pinned_at: null,
  metadata_json: null,
  messages: [
    {
      id: "user-1",
      role: "user",
      content: "Explain moat",
      status: "completed",
      created_at: "2026-05-01T10:00:00Z",
      evidence: [],
    },
    {
      id: "assistant-1",
      role: "assistant",
      content: "Grounded passages from Warren Buffett:\n- Durable competitive advantages compound over time.",
      status: "completed",
      created_at: "2026-05-01T10:00:05Z",
      metadata_json: {
        mode: "concept",
        evidence_sufficient: true,
        follow_up_questions: ["Compare that with Nick Sleep"],
      },
      evidence: [
        {
          id: "evidence-1",
          chunk_id: "chunk-1",
          document_id: "doc-1",
          author_id: "warren_buffett",
          author_name: "Warren Buffett",
          title: "1996 Letter",
          snippet: "A wonderful business can compound.",
          source_url: "https://example.com",
          similarity: 0.9,
          ranking_score: 0.91,
          score_type: "reranked",
          metadata_json: {
            context_text:
              "A wonderful business can compound for decades when management protects pricing power and allocates capital rationally. Durable competitive advantages compound over time.",
            anchor_text: "Durable competitive advantages compound over time.",
          },
        },
      ],
    },
  ] satisfies AISageChatMessage[],
};

const CHAT_DETAIL_TWO: AISageChatDetail = {
  id: "chat-2",
  title: "Second thread",
  created_at: "2026-05-02T10:00:00Z",
  updated_at: "2026-05-02T10:05:00Z",
  last_activity_at: "2026-05-02T10:04:00Z",
  pinned_at: null,
  metadata_json: null,
  messages: [
    {
      id: "user-2",
      role: "user",
      content: "Second prompt",
      status: "completed",
      created_at: "2026-05-02T10:00:00Z",
      evidence: [],
    },
  ] satisfies AISageChatMessage[],
};

let clipboardWriteText: ReturnType<typeof vi.fn>;

function installClipboardMock() {
  clipboardWriteText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: clipboardWriteText,
    },
  });
}

function renderAISage(initialEntries = ["/ai-sage"]) {
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
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/ai-sage" element={<AISage />} />
          <Route path="/ai-sage/chats/:chatId" element={<AISage />} />
        </Routes>
      </MemoryRouter>
    </AuthContext.Provider>,
  );
}

describe("AISage workspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    installClipboardMock();
    vi.mocked(api.aiSageChats).mockResolvedValue({ items: [], total: 0, limit: 30, offset: 0 });
    vi.mocked(api.aiSageCreateChat).mockResolvedValue({
      id: "chat-new",
      title: "New chat",
      created_at: "2026-05-01T10:00:00Z",
      updated_at: "2026-05-01T10:00:00Z",
      last_activity_at: "2026-05-01T10:00:00Z",
      pinned_at: null,
      metadata_json: null,
      messages: [],
    });
    vi.mocked(api.aiSageGetChat).mockResolvedValue({
      id: "chat-new",
      title: "New chat",
      created_at: "2026-05-01T10:00:00Z",
      updated_at: "2026-05-01T10:00:00Z",
      last_activity_at: "2026-05-01T10:00:00Z",
      pinned_at: null,
      metadata_json: null,
      messages: [],
    });
    vi.mocked(api.aiSageSearchChats).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(api.aiSageUpdateChat).mockResolvedValue(CHAT_DETAIL);
    vi.mocked(api.aiSageDeleteChat).mockResolvedValue({ status: "deleted" });
    vi.mocked(api.aiSageRetryMessage).mockResolvedValue({
      chat: CHAT_DETAIL,
      user_message: CHAT_DETAIL.messages[0],
      assistant_message: CHAT_DETAIL.messages[1],
    });
  });

  it("shows the empty persistent workspace and mobile chats button", async () => {
    renderAISage();
    expect(await screen.findByText("No chats yet.")).toBeInTheDocument();
    expect(screen.getByText("Hello Hitesh")).toBeInTheDocument();
    expect(document.querySelector(".aiSageMainPanelLanding")).not.toBeNull();
    expect(screen.getByRole("button", { name: "New chat" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Search chats" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Projects" })).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask AI Sage anything")).toBeInTheDocument();
    expect(screen.queryByText("Saved for one year from your last user message.")).not.toBeInTheDocument();
    expect(screen.queryByText("Build a persistent research thread and keep every answer grounded to evidence.")).not.toBeInTheDocument();
  });

  it("loads a deep-linked chat and renders saved transcript evidence", async () => {
    vi.mocked(api.aiSageChats).mockResolvedValue({ items: [CHAT_SUMMARY], total: 1, limit: 30, offset: 0 });
    vi.mocked(api.aiSageGetChat).mockResolvedValue(CHAT_DETAIL);
    const user = userEvent.setup();
    installClipboardMock();

    renderAISage(["/ai-sage/chats/chat-1"]);

    expect(await screen.findByRole("heading", { name: "Moat review" })).toBeInTheDocument();
    expect(document.querySelector(".aiSageMainPanelThread")).not.toBeNull();
    expect(screen.getByText("Explain moat")).toBeInTheDocument();
    expect(screen.queryByText(/Grounded passages from Warren Buffett:/)).not.toBeInTheDocument();
    expect(screen.queryByText("1996 Letter")).not.toBeInTheDocument();
    expect(screen.queryByText(/Warren Buffett ·/)).not.toBeInTheDocument();
    expect(screen.getByText("Score 0.91")).toBeInTheDocument();
    expect(screen.getByText("A wonderful business can compound.")).toBeInTheDocument();
    expect(screen.queryByText(/^Expanded context$/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open source" })).not.toBeInTheDocument();
    await user.click(screen.getByText("A wonderful business can compound."));
    expect(screen.queryByText(/^Expanded context$/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show expanded context" }));
    expect(screen.getByText(/^Expanded context$/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute("href", "https://example.com");
    expect(screen.queryByTestId("ai-sage-evidence-expanded-link")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Copy chunk content" }));
    expect(clipboardWriteText).toHaveBeenCalledWith("A wonderful business can compound.");
    expect(screen.getByRole("button", { name: "Compare that with Nick Sleep" })).toBeInTheDocument();
  });

  it("hides duplicate evidence rows when rendering a saved chat", async () => {
    vi.mocked(api.aiSageChats).mockResolvedValue({ items: [CHAT_SUMMARY], total: 1, limit: 30, offset: 0 });
    vi.mocked(api.aiSageGetChat).mockResolvedValue({
      ...CHAT_DETAIL,
      messages: [
        CHAT_DETAIL.messages[0],
        {
          ...CHAT_DETAIL.messages[1],
          evidence: [
            CHAT_DETAIL.messages[1].evidence[0],
            {
              ...CHAT_DETAIL.messages[1].evidence[0],
              id: "evidence-duplicate",
              chunk_id: "chunk-duplicate",
              snippet: "A wonderful business can compound.",
            },
            {
              ...CHAT_DETAIL.messages[1].evidence[0],
              id: "evidence-distinct",
              chunk_id: "chunk-distinct",
              snippet: "Inversion helps investors reason backward from what can go wrong.",
              metadata_json: {
                context_text: "Inversion helps investors reason backward from what can go wrong.",
                anchor_text: "Inversion helps investors reason backward from what can go wrong.",
              },
            },
          ],
        },
      ],
    });

    renderAISage(["/ai-sage/chats/chat-1"]);

    expect(await screen.findByRole("heading", { name: "Moat review" })).toBeInTheDocument();
    expect(screen.getAllByText("A wonderful business can compound.")).toHaveLength(1);
    expect(screen.getByText("Inversion helps investors reason backward from what can go wrong.")).toBeInTheDocument();
  });

  it("remounts the transcript when switching saved chats so the next thread opens from the top", async () => {
    vi.mocked(api.aiSageChats).mockResolvedValue({
      items: [
        CHAT_SUMMARY,
        {
          ...CHAT_SUMMARY,
          id: "chat-2",
          title: "Second thread",
          updated_at: "2026-05-02T10:05:00Z",
          last_activity_at: "2026-05-02T10:04:00Z",
        },
      ],
      total: 2,
      limit: 30,
      offset: 0,
    });
    vi.mocked(api.aiSageGetChat).mockImplementation(async (chatId: string) => (
      chatId === "chat-2" ? CHAT_DETAIL_TWO : CHAT_DETAIL
    ));
    const user = userEvent.setup();

    renderAISage(["/ai-sage/chats/chat-1"]);

    await screen.findByRole("heading", { name: "Moat review" });
    const firstTranscript = screen.getByTestId("ai-sage-transcript");
    firstTranscript.scrollTop = 240;

    await user.click(screen.getByRole("button", { name: "Second thread" }));

    expect(await screen.findByRole("heading", { name: "Second thread" })).toBeInTheDocument();
    const secondTranscript = screen.getByTestId("ai-sage-transcript");
    expect(secondTranscript).not.toBe(firstTranscript);
    expect(screen.getByText("Second prompt")).toBeInTheDocument();
  });

  it("creates a new chat and streams the assistant response incrementally", async () => {
    const streamedUser: AISageChatMessage = {
      id: "user-2",
      role: "user",
      content: "What matters?",
      status: "completed",
      created_at: "2026-05-01T10:00:00Z",
      evidence: [],
    };
    const streamedAssistant: AISageChatMessage = {
      id: "assistant-2",
      role: "assistant",
      content: "Grounded answer.",
      status: "completed",
      created_at: "2026-05-01T10:00:05Z",
      metadata_json: { mode: "concept", evidence_sufficient: true },
      evidence: [],
    };
    const streamedChat: AISageChatDetail = {
      ...CHAT_DETAIL,
      id: "chat-new",
      title: "What matters?",
      messages: [streamedUser, streamedAssistant],
    };
    vi.mocked(api.aiSageGetChat).mockResolvedValue(streamedChat);
    vi.mocked(streamAiSageChatMessage).mockImplementation(async (_chatId, _payload, onEvent) => {
      onEvent({
        type: "ack",
        chat_id: "chat-new",
        user_message: streamedUser,
        assistant_message_id: "assistant-2",
      });
      onEvent({ type: "delta", assistant_message_id: "assistant-2", delta: "Grounded " });
      onEvent({ type: "delta", assistant_message_id: "assistant-2", delta: "answer." });
      onEvent({
        type: "done",
        chat: streamedChat,
        user_message: streamedUser,
        assistant_message: streamedAssistant,
      });
    });

    const user = userEvent.setup();
    renderAISage();

    await user.type(screen.getByPlaceholderText("Ask AI Sage anything"), "What matters?{Enter}");

    expect(api.aiSageCreateChat).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(api.aiSageGetChat).toHaveBeenCalledWith("chat-new");
    });
    expect(await screen.findByText("Grounded answer.")).toBeInTheDocument();
  });

  it("shows the first submitted turn immediately while the initial stream is still pending", async () => {
    let releaseStream = () => {};
    vi.mocked(streamAiSageChatMessage).mockImplementation(
      () => new Promise<void>((resolve) => {
        releaseStream = resolve;
      }),
    );

    const user = userEvent.setup();
    renderAISage();

    await user.type(screen.getByPlaceholderText("Ask AI Sage anything"), "What matters?{Enter}");

    expect(await screen.findByText("What matters?")).toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(screen.queryByText("Hello Hitesh")).not.toBeInTheDocument();

    releaseStream();
  });

  it("refreshes the persisted chat after a first streamed turn even without a done event", async () => {
    const streamedUser: AISageChatMessage = {
      id: "user-2",
      role: "user",
      content: "What matters?",
      status: "completed",
      created_at: "2026-05-01T10:00:00Z",
      evidence: [],
    };
    const persistedAssistant: AISageChatMessage = {
      id: "assistant-2",
      role: "assistant",
      content: "Persisted answer.",
      status: "completed",
      created_at: "2026-05-01T10:00:05Z",
      metadata_json: { mode: "concept", evidence_sufficient: true },
      evidence: [],
    };
    vi.mocked(api.aiSageGetChat).mockResolvedValue({
      ...CHAT_DETAIL,
      id: "chat-new",
      title: "What matters?",
      messages: [streamedUser, persistedAssistant],
    });
    vi.mocked(streamAiSageChatMessage).mockImplementation(async (_chatId, _payload, onEvent) => {
      onEvent({
        type: "ack",
        chat_id: "chat-new",
        user_message: streamedUser,
        assistant_message_id: "assistant-2",
      });
    });

    const user = userEvent.setup();
    renderAISage();

    await user.type(screen.getByPlaceholderText("Ask AI Sage anything"), "What matters?{Enter}");

    expect(await screen.findByText("Persisted answer.")).toBeInTheDocument();
    expect(api.aiSageGetChat).toHaveBeenCalledWith("chat-new");
  });

  it("supports renaming from the toolbar and deleting from the compact sidebar row", async () => {
    vi.mocked(api.aiSageChats).mockResolvedValue({ items: [CHAT_SUMMARY], total: 1, limit: 30, offset: 0 });
    vi.mocked(api.aiSageGetChat).mockResolvedValue(CHAT_DETAIL);
    vi.spyOn(window, "prompt").mockReturnValue("Renamed chat");
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    renderAISage(["/ai-sage/chats/chat-1"]);

    await screen.findByRole("heading", { name: "Moat review" });
    expect(screen.queryByText(CHAT_SUMMARY.status)).not.toBeInTheDocument();
    expect(screen.queryByText(CHAT_SUMMARY.preview!)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(api.aiSageUpdateChat).toHaveBeenCalledWith("chat-1", { title: "Renamed chat" });

    await user.click(screen.getByRole("button", { name: "More actions for Moat review" }));
    expect(screen.getByRole("menuitem", { name: "Share" })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: "Pin" })).toBeDisabled();
    await user.click(screen.getByRole("menuitem", { name: "Delete" }));
    expect(api.aiSageDeleteChat).toHaveBeenCalledWith("chat-1");
  });

  it("shows a failed turn and retries it", async () => {
    vi.mocked(api.aiSageChats).mockResolvedValue({ items: [CHAT_SUMMARY], total: 1, limit: 30, offset: 0 });
    const failedAssistant: AISageChatMessage = {
      id: "assistant-failed",
      role: "assistant",
      content: "",
      status: "failed",
      created_at: "2026-05-01T10:00:05Z",
      error_message: "Synthetic failure",
      metadata_json: { source_user_message_id: "user-1" },
      evidence: [],
    };
    vi.mocked(api.aiSageGetChat).mockResolvedValue({
      ...CHAT_DETAIL,
      messages: [CHAT_DETAIL.messages[0], failedAssistant],
    });

    const user = userEvent.setup();
    renderAISage(["/ai-sage/chats/chat-1"]);

    expect(await screen.findByText("Synthetic failure")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry turn" }));
    await waitFor(() => {
      expect(api.aiSageRetryMessage).toHaveBeenCalledWith("chat-1", "assistant-failed");
    });
  });
});
