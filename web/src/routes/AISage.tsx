import {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import "../App.css";
import PageShell from "../components/PageShell";
import { AuthContext } from "../context/AuthContext";
import {
  api,
  streamAiSageChatMessage,
  type AISageChatDetail,
  type AISageChatEvidence,
  type AISageChatMessage,
  type AISageChatSummary,
  type AISageStreamEvent,
} from "../lib/api";

const EVIDENCE_CONTEXT_TARGET_CHARS = 1200;
const CHAT_ROW_TITLE_LIMIT = 50;

const SUGGESTED_PROMPTS = [
  "What's Howard Marks' latest thinking on risk?",
  "Compare Buffett and Munger on moats",
  "Summarize this week's ingested filings",
  "What evidence do we have on payments consolidation?",
];

type PendingTurnIds = {
  userMessageId: string;
  assistantMessageId: string;
};

function readerRoute(authorId: string, documentId: string): string {
  return `/author-library/${encodeURIComponent(authorId)}/documents/${encodeURIComponent(documentId)}`;
}

type ChatGroupLabel = "Today" | "Previous 7 days" | "Older";

function chatGroupLabel(chat: AISageChatSummary, now: Date): ChatGroupLabel {
  const reference = new Date(chat.last_activity_at || chat.created_at);
  if (reference.toDateString() === now.toDateString()) return "Today";
  const dayMs = 24 * 60 * 60 * 1000;
  if (now.getTime() - reference.getTime() < 7 * dayMs) return "Previous 7 days";
  return "Older";
}

function normalizeEvidenceText(value: unknown): string {
  if (typeof value !== "string") return "";
  return value
    .replace(/\r/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
}

function compactChatTitle(title: string, maxChars = CHAT_ROW_TITLE_LIMIT): string {
  const normalized = title.trim();
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(1, maxChars)).trimEnd()}...`;
}

function trimEvidenceWindow(text: string, start: number, end: number): string {
  let sliceStart = Math.max(0, start);
  let sliceEnd = Math.min(text.length, end);

  if (sliceStart > 0) {
    const sentenceStart = Math.max(
      text.lastIndexOf("\n\n", sliceStart),
      text.lastIndexOf(". ", sliceStart),
      text.lastIndexOf("? ", sliceStart),
      text.lastIndexOf("! ", sliceStart),
    );
    if (sentenceStart >= 0) {
      sliceStart = sentenceStart + (text.slice(sentenceStart, sentenceStart + 2) === "\n\n" ? 2 : 1);
    }
  }

  if (sliceEnd < text.length) {
    const sentenceEndCandidates = [
      text.indexOf("\n\n", sliceEnd),
      text.indexOf(". ", sliceEnd),
      text.indexOf("? ", sliceEnd),
      text.indexOf("! ", sliceEnd),
    ].filter((value) => value >= 0);
    if (sentenceEndCandidates.length > 0) {
      sliceEnd = Math.min(...sentenceEndCandidates) + 1;
    }
  }

  const excerpt = text.slice(sliceStart, sliceEnd).trim();
  return `${sliceStart > 0 ? "… " : ""}${excerpt}${sliceEnd < text.length ? " …" : ""}`.trim();
}

function buildEvidenceContextExcerpt(contextText: string, anchorText: string): string {
  if (contextText.length <= EVIDENCE_CONTEXT_TARGET_CHARS) {
    return contextText;
  }

  const normalizedAnchor = normalizeEvidenceText(anchorText);
  const lowerContext = contextText.toLowerCase();
  const lowerAnchor = normalizedAnchor.toLowerCase();
  const anchorIndex = lowerAnchor ? lowerContext.indexOf(lowerAnchor) : -1;

  if (anchorIndex < 0) {
    return trimEvidenceWindow(contextText, 0, EVIDENCE_CONTEXT_TARGET_CHARS);
  }

  const before = Math.max(0, anchorIndex - 420);
  const after = Math.min(
    contextText.length,
    anchorIndex + normalizedAnchor.length + (EVIDENCE_CONTEXT_TARGET_CHARS - 520),
  );
  return trimEvidenceWindow(contextText, before, after);
}

function renderEvidenceText(text: string, highlight: string | null) {
  const normalizedHighlight = normalizeEvidenceText(highlight);
  if (!normalizedHighlight || normalizedHighlight.length < 12) {
    return text;
  }
  const lowerText = text.toLowerCase();
  const lowerHighlight = normalizedHighlight.toLowerCase();
  const index = lowerText.indexOf(lowerHighlight);
  if (index < 0) {
    return text;
  }
  const end = index + normalizedHighlight.length;
  return (
    <>
      {text.slice(0, index)}
      <mark className="aiSageEvidenceMark">{text.slice(index, end)}</mark>
      {text.slice(end)}
    </>
  );
}

function SidebarActionIcon({ children }: { children: ReactNode }) {
  return <span className="aiSageSidebarActionIcon" aria-hidden="true">{children}</span>;
}

export default function AISage() {
  const navigate = useNavigate();
  const { chatId } = useParams<{ chatId?: string }>();
  const { user } = useContext(AuthContext);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stickToBottomRef = useRef(true);
  const locallyCreatedChatIdRef = useRef<string | null>(null);

  const [query, setQuery] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarSearchQuery, setSidebarSearchQuery] = useState("");
  const [chatSummaries, setChatSummaries] = useState<AISageChatSummary[]>([]);
  const [chatsLoading, setChatsLoading] = useState(true);
  const [chatListError, setChatListError] = useState<string | null>(null);
  const [activeChat, setActiveChat] = useState<AISageChatDetail | null>(null);
  const [activeChatLoading, setActiveChatLoading] = useState(false);
  const [activeChatError, setActiveChatError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [sidebarMenuChatId, setSidebarMenuChatId] = useState<string | null>(null);

  const greetingName = user?.display_name?.trim() || user?.username?.trim() || "there";
  const headerActions = <button className="btn aiSageMobileChatsButton" type="button" onClick={() => setSidebarOpen(true)}>Chats</button>;

  const loadChatList = useCallback(async () => {
    setChatsLoading(true);
    setChatListError(null);
    try {
      const response = await api.aiSageChats();
      setChatSummaries(response.items);
    } catch (error) {
      setChatListError(error instanceof Error ? error.message : String(error));
    } finally {
      setChatsLoading(false);
    }
  }, []);

  const loadChatDetail = useCallback(async (targetChatId: string) => {
    setActiveChatLoading(true);
    setActiveChatError(null);
    try {
      const response = await api.aiSageGetChat(targetChatId);
      setActiveChat(response);
    } catch (error) {
      setActiveChat(null);
      setActiveChatError(error instanceof Error ? error.message : String(error));
    } finally {
      setActiveChatLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadChatList();
  }, [loadChatList]);

  useEffect(() => {
    if (!chatId) {
      if (locallyCreatedChatIdRef.current) {
        return;
      }
      locallyCreatedChatIdRef.current = null;
      setActiveChat(null);
      setActiveChatError(null);
      return;
    }
    if (activeChat?.id === chatId || locallyCreatedChatIdRef.current === chatId) {
      if (locallyCreatedChatIdRef.current === chatId) {
        locallyCreatedChatIdRef.current = null;
      }
      return;
    }
    void loadChatDetail(chatId);
  }, [activeChat?.id, chatId, loadChatDetail]);

  useEffect(() => {
    stickToBottomRef.current = false;
  }, [chatId]);

  useEffect(() => {
    const closeMenus = () => setSidebarMenuChatId(null);
    document.addEventListener("click", closeMenus);
    return () => {
      document.removeEventListener("click", closeMenus);
    };
  }, []);

  useEffect(() => {
    const container = transcriptRef.current;
    if (!container) return;
    if (!stickToBottomRef.current) return;
    container.scrollTop = container.scrollHeight;
  }, [activeChat?.messages, streaming]);

  async function handleCreateChat(): Promise<void> {
    const created = await api.aiSageCreateChat({});
    locallyCreatedChatIdRef.current = created.id;
    setActiveChat(created);
    setSidebarOpen(false);
    setSidebarMenuChatId(null);
    await loadChatList();
    navigate(`/ai-sage/chats/${created.id}`);
  }

  async function handleRenameChat(target: AISageChatSummary | AISageChatDetail): Promise<void> {
    const nextTitle = window.prompt("Rename chat", target.title);
    if (!nextTitle || nextTitle.trim() === target.title) return;
    const updated = await api.aiSageUpdateChat(target.id, { title: nextTitle.trim() });
    setActiveChat((current) => (current?.id === updated.id ? updated : current));
    await loadChatList();
  }

  async function handleDeleteChat(target: AISageChatSummary | AISageChatDetail): Promise<void> {
    if (!window.confirm(`Delete "${target.title}"? This will permanently remove the chat.`)) return;
    await api.aiSageDeleteChat(target.id);
    setSidebarOpen(false);
    setSidebarMenuChatId(null);
    if (chatId === target.id) {
      locallyCreatedChatIdRef.current = null;
      setActiveChat(null);
      navigate("/ai-sage");
    }
    await loadChatList();
  }

  async function handleRetry(messageId: string): Promise<void> {
    if (!activeChat) return;
    stickToBottomRef.current = true;
    const response = await api.aiSageRetryMessage(activeChat.id, messageId);
    setActiveChat(response.chat);
    await loadChatList();
  }

  function handleTranscriptScroll(): void {
    const container = transcriptRef.current;
    if (!container) return;
    const nearBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 80;
    stickToBottomRef.current = nearBottom;
  }

  async function handleSendMessage(event?: FormEvent<HTMLFormElement>): Promise<void> {
    event?.preventDefault();
    const content = query.trim();
    if (!content) {
      setValidationError("Enter a message before sending.");
      return;
    }

    setValidationError(null);
    setStreaming(true);
    setSidebarOpen(false);
    stickToBottomRef.current = true;
    let targetChatId = activeChat?.id;
    let targetChat = activeChat;
    let shouldNavigateAfterTurn = false;
    if (!targetChatId) {
      const created = await api.aiSageCreateChat({});
      locallyCreatedChatIdRef.current = created.id;
      targetChat = created;
      setActiveChat(created);
      targetChatId = created.id;
      shouldNavigateAfterTurn = true;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setQuery("");
    const pendingIds: PendingTurnIds = {
      userMessageId: `pending-user-${Date.now()}`,
      assistantMessageId: `pending-assistant-${Date.now()}`,
    };
    const pendingCreatedAt = new Date().toISOString();
    const pendingUserMessage: AISageChatMessage = {
      id: pendingIds.userMessageId,
      role: "user",
      content,
      status: "completed",
      created_at: pendingCreatedAt,
      evidence: [],
    };
    const pendingAssistantMessage: AISageChatMessage = {
      id: pendingIds.assistantMessageId,
      role: "assistant",
      content: "",
      status: "in_progress",
      created_at: pendingCreatedAt,
      evidence: [],
    };
    setActiveChat((current) => {
      const base = current ?? targetChat;
      if (!base || base.id !== targetChatId) return current;
      return {
        ...base,
        messages: [...base.messages, pendingUserMessage, pendingAssistantMessage],
      };
    });

    let streamCompletedWithChat = false;
    try {
      await streamAiSageChatMessage(
        targetChatId,
        { content },
        (streamEvent) => {
          if (streamEvent.type === "done") {
            streamCompletedWithChat = true;
          }
          applyStreamEvent(streamEvent, targetChatId!, pendingIds);
        },
        { signal: controller.signal },
      );
    } catch (error) {
      if (controller.signal.aborted) {
        setValidationError("Generation cancelled.");
      } else {
        setValidationError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      if (!controller.signal.aborted) {
        if (!streamCompletedWithChat) {
          const refreshed = await refreshChatAfterTurn(targetChatId);
          if (refreshed) {
            const latestAssistant = [...refreshed.messages].reverse().find((message) => message.role === "assistant");
            if (latestAssistant?.status === "completed") {
              setValidationError(null);
            }
          }
        }
        await loadChatList();
        if (shouldNavigateAfterTurn) {
          navigate(`/ai-sage/chats/${targetChatId}`);
        }
      }
      abortRef.current = null;
      setStreaming(false);
    }
  }

  async function refreshChatAfterTurn(targetChatId: string): Promise<AISageChatDetail | null> {
    try {
      const refreshed = await api.aiSageGetChat(targetChatId);
      setActiveChat((current) => {
        if (current && current.id !== targetChatId) return current;
        return refreshed;
      });
      return refreshed;
    } catch {
      return null;
    }
  }

  function applyStreamEvent(streamEvent: AISageStreamEvent, targetChatId: string, pendingIds?: PendingTurnIds): void {
    if (streamEvent.type === "ack") {
      setActiveChat((current) => {
        if (current && current.id !== targetChatId) return current;
        const base = current ?? {
          id: targetChatId,
          title: DEFAULT_CHAT_TITLE,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          last_activity_at: new Date().toISOString(),
          pinned_at: null,
          metadata_json: null,
          messages: [],
        };
        const assistantPlaceholder: AISageChatMessage = {
          id: streamEvent.assistant_message_id,
          role: "assistant",
          content: "",
          status: "in_progress",
          created_at: new Date().toISOString(),
          evidence: [],
        };
        const hasPersistedUser = base.messages.some((message) => message.id === streamEvent.user_message.id);
        const hasPersistedAssistant = base.messages.some((message) => message.id === streamEvent.assistant_message_id);
        if (hasPersistedUser && hasPersistedAssistant) {
          return base;
        }
        const hasPendingTurn = Boolean(pendingIds) && base.messages.some((message) => (
          message.id === pendingIds?.userMessageId || message.id === pendingIds?.assistantMessageId
        ));
        if (hasPendingTurn && pendingIds) {
          return {
            ...base,
            messages: base.messages.map((message) => {
              if (message.id === pendingIds.userMessageId) return streamEvent.user_message;
              if (message.id === pendingIds.assistantMessageId) return assistantPlaceholder;
              return message;
            }),
          };
        }
        return {
          ...base,
          messages: [...base.messages, streamEvent.user_message, assistantPlaceholder],
        };
      });
      return;
    }

    if (streamEvent.type === "delta") {
      setActiveChat((current) => {
        if (!current) return current;
        if (current.id !== targetChatId) return current;
        return {
          ...current,
          messages: current.messages.map((message) =>
            message.id === streamEvent.assistant_message_id
              ? { ...message, content: `${message.content}${streamEvent.delta}` }
              : message,
          ),
        };
      });
      return;
    }

    if (streamEvent.type === "done") {
      setActiveChat((current) => {
        if (current && current.id !== targetChatId) return current;
        return streamEvent.chat;
      });
      setValidationError(null);
      return;
    }

    setActiveChat((current) => {
      if (!current) return current;
      if (current.id !== targetChatId) return current;
      return {
        ...current,
        messages: current.messages.map((message) =>
          message.id === streamEvent.assistant_message.id ? streamEvent.assistant_message : message,
        ),
      };
    });
    setValidationError(streamEvent.error);
  }

  function abortStreaming(): void {
    abortRef.current?.abort();
  }

  function handleComposerKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSendMessage();
    }
  }

  const transcriptEmptyState = useMemo(() => {
    if (activeChatLoading) return <div className="card">Loading chat…</div>;
    if (activeChatError) return <div className="card aiSageErrorState">{activeChatError}</div>;
    if (activeChat && activeChat.messages.length > 0) return null;
    return null;
  }, [activeChat, activeChatError, activeChatLoading]);

  const showLanding = !activeChatLoading && !activeChatError && (!activeChat || activeChat.messages.length === 0);
  const mainPanelClassName = `aiSageMainPanel ${showLanding ? "aiSageMainPanelLanding" : "aiSageMainPanelThread"}`;

  const chatGroups = useMemo(() => {
    const query = sidebarSearchQuery.trim().toLowerCase();
    const filtered = query
      ? chatSummaries.filter((chat) => chat.title.toLowerCase().includes(query))
      : chatSummaries;
    const now = new Date();
    const order: ChatGroupLabel[] = ["Today", "Previous 7 days", "Older"];
    const buckets = new Map<ChatGroupLabel, AISageChatSummary[]>();
    for (const chat of filtered) {
      const label = chatGroupLabel(chat, now);
      const list = buckets.get(label) ?? [];
      list.push(chat);
      buckets.set(label, list);
    }
    return order
      .map((label) => ({ label, chats: buckets.get(label) ?? [] }))
      .filter((group) => group.chats.length > 0);
  }, [chatSummaries, sidebarSearchQuery]);

  return (
    <PageShell title="" hideHeader headerActions={headerActions} className="aiSagePageShell" fillHeight>
      <div className="aiSageWorkspace">
        <aside className={`card aiSageSidebar ${sidebarOpen ? "aiSageSidebarOpen" : ""}`}>
          <div className="aiSageSidebarHeader">
            <div>
              <div className="cardTitle">Recents</div>
            </div>
            <button className="btn aiSageSidebarClose" type="button" onClick={() => setSidebarOpen(false)}>
              Close
            </button>
          </div>
          <div className="aiSageSidebarTools">
            <button className="aiSageSidebarAction aiSageSidebarActionPrimary" type="button" onClick={() => void handleCreateChat()}>
              <SidebarActionIcon>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4Z" />
                </svg>
              </SidebarActionIcon>
              <span>New chat</span>
            </button>
            <div className="aiSageSidebarSearch">
              <SidebarActionIcon>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="7" />
                  <path d="m20 20-3.5-3.5" />
                </svg>
              </SidebarActionIcon>
              <input
                className="aiSageSidebarSearchInput"
                type="text"
                value={sidebarSearchQuery}
                onChange={(event) => setSidebarSearchQuery(event.target.value)}
                placeholder="Search chats"
                aria-label="Search chats"
              />
            </div>
          </div>
          {chatListError ? <div className="aiSageErrorState">{chatListError}</div> : null}
          {chatsLoading ? <div className="muted">Loading chats…</div> : null}
          {!chatsLoading && chatSummaries.length === 0 ? <div className="aiSageEmptySidebar">No chats yet.</div> : null}
          <div className="aiSageSidebarList" aria-label="Saved chats">
            {chatGroups.map((group) => (
              <div className="aiSageChatGroup" key={group.label}>
                <div className="aiSageChatGroupLabel">{group.label}</div>
                {group.chats.map((chat) => (
                  <article
                    key={chat.id}
                    className={`aiSageChatListItem ${chatId === chat.id ? "aiSageChatListItemActive" : ""}`}
                  >
                    <button
                      type="button"
                      className="aiSageChatListButton"
                      onClick={() => {
                        locallyCreatedChatIdRef.current = null;
                        setSidebarOpen(false);
                        setSidebarMenuChatId(null);
                        navigate(`/ai-sage/chats/${chat.id}`);
                      }}
                    >
                      <span className="aiSageChatListTitle" title={chat.title}>
                        {compactChatTitle(chat.title)}
                      </span>
                    </button>
                    <div className="aiSageChatRowMenu">
                      <button
                        className="aiSageChatMenuButton"
                        type="button"
                        aria-label={`More actions for ${chat.title}`}
                        aria-expanded={sidebarMenuChatId === chat.id}
                        onClick={(event) => {
                          event.stopPropagation();
                          setSidebarMenuChatId((current) => (current === chat.id ? null : chat.id));
                        }}
                      >
                        ...
                      </button>
                      {sidebarMenuChatId === chat.id ? (
                        <div className="aiSageChatMenuPanel" role="menu" onClick={(event) => event.stopPropagation()}>
                          <button className="aiSageChatMenuItem" type="button" role="menuitem" disabled title="Coming soon">
                            Share
                          </button>
                          <button className="aiSageChatMenuItem" type="button" role="menuitem" disabled title="Coming soon">
                            Pin
                          </button>
                          <button
                            className="aiSageChatMenuItem aiSageChatMenuItemDanger"
                            type="button"
                            role="menuitem"
                            onClick={() => void handleDeleteChat(chat)}
                          >
                            Delete
                          </button>
                        </div>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            ))}
            {!chatsLoading && chatSummaries.length > 0 && chatGroups.length === 0 ? (
              <div className="aiSageEmptySidebar">No chats match "{sidebarSearchQuery}".</div>
            ) : null}
          </div>
        </aside>

        <div className={mainPanelClassName}>
          {showLanding ? (
            <section className="aiSageLanding">
              <p className="aiSageLandingGreeting">Hello {greetingName}</p>
              <form className="aiSageLandingComposer" onSubmit={(event) => void handleSendMessage(event)}>
                <div className="aiSageLandingBar">
                  <input
                    className="aiSageLandingInput"
                    value={query}
                    placeholder="Ask AI Sage anything"
                    onChange={(event) => setQuery(event.target.value)}
                    disabled={streaming}
                  />
                  <button className="btn aiSageLandingSend" type="submit" disabled={streaming}>
                    {streaming ? "Thinking…" : "Send"}
                  </button>
                </div>
              </form>
              {validationError ? <div className="aiSageErrorState">{validationError}</div> : null}
              <div className="aiSagePromptChipRow aiSageLandingPromptRow">
                {SUGGESTED_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    className="btn aiSagePromptChip"
                    type="button"
                    onClick={() => setQuery(prompt)}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </section>
          ) : null}

          {activeChat && !showLanding ? (
            <div className="aiSageChatToolbar">
              <div>
                <h1 className="aiSageChatTitle">{activeChat.title}</h1>
              </div>
              <div className="aiSageToolbarActions">
                <button className="btn" type="button" onClick={() => void handleRenameChat(activeChat)}>
                  Rename
                </button>
                <button className="btn" type="button" onClick={() => void handleDeleteChat(activeChat)}>
                  Delete
                </button>
              </div>
            </div>
          ) : null}

          {!showLanding ? (
            <>
              <div
                key={activeChat?.id ?? "ai-sage-transcript"}
                className="aiSageTranscript card"
                data-testid="ai-sage-transcript"
                ref={transcriptRef}
                onScroll={handleTranscriptScroll}
              >
                {transcriptEmptyState}
                {activeChat?.messages.map((message) => (
                  <MessageBubble key={message.id} message={message} onRetry={handleRetry} onUseSuggestion={setQuery} />
                ))}
              </div>

              <form className="card aiSageComposer" onSubmit={(event) => void handleSendMessage(event)}>
                <textarea
                  className="formInput aiSageComposerInput"
                  rows={3}
                  value={query}
                  placeholder="Ask AI Sage anything"
                  onChange={(event) => setQuery(event.target.value)}
                  onKeyDown={handleComposerKeyDown}
                  disabled={streaming}
                />
                <div className="aiSageComposerFooter">
                  <div className="muted">Enter to send. Shift+Enter for newline.</div>
                  <div className="aiSageComposerButtons">
                    {streaming ? (
                      <button className="btn" type="button" onClick={abortStreaming}>
                        Cancel
                      </button>
                    ) : null}
                    <button className="btn" type="submit" disabled={streaming}>
                      {streaming ? "Streaming…" : "Send"}
                    </button>
                  </div>
                </div>
                {validationError ? <div className="aiSageErrorState">{validationError}</div> : null}
              </form>
            </>
          ) : null}
        </div>
      </div>

      {sidebarOpen ? <button className="aiSageSidebarBackdrop" type="button" onClick={() => setSidebarOpen(false)} aria-label="Close chats drawer" /> : null}
    </PageShell>
  );
}

const DEFAULT_CHAT_TITLE = "New chat";

function MessageBubble({
  message,
  onRetry,
  onUseSuggestion,
}: {
  message: AISageChatMessage;
  onRetry: (messageId: string) => Promise<void>;
  onUseSuggestion: (text: string) => void;
}) {
  if (message.role === "user") {
    return (
      <section className="aiSageMessageRow aiSageMessageRowUser">
        <article className="card aiSageMessageBubble aiSageMessageBubbleUser">
          <p className="aiSageMessageText">{message.content}</p>
        </article>
      </section>
    );
  }

  const metadata = message.metadata_json ?? {};
  const followUps = Array.isArray(metadata.follow_up_questions)
    ? metadata.follow_up_questions.filter((value): value is string => typeof value === "string")
    : [];
  const pushbackQuestions = Array.isArray(metadata.pushback_questions)
    ? metadata.pushback_questions.filter((value): value is string => typeof value === "string")
    : [];
  const missingInformation = Array.isArray(metadata.missing_information)
    ? metadata.missing_information.filter((value): value is string => typeof value === "string")
    : [];
  const keyFacts = Array.isArray(metadata.key_facts)
    ? metadata.key_facts.filter((value): value is string => typeof value === "string")
    : [];
  const visibleEvidence = dedupeEvidenceForDisplay(message.evidence);
  const visibleAssistantText = message.content || "Thinking…";
  const showAssistantText = visibleEvidence.length === 0 || message.status !== "completed";

  return (
    <section className="aiSageMessageRow aiSageMessageRowAssistant">
      <article className="card aiSageMessageBubble aiSageMessageBubbleAssistant">
        {message.status === "failed" ? (
          <div className="aiSageErrorState">
            <p className="aiSageMessageText">{message.error_message || "This turn failed."}</p>
            <button className="btn" type="button" onClick={() => void onRetry(message.id)}>
              Retry turn
            </button>
          </div>
        ) : (
          <>
            {showAssistantText ? <p className="aiSageMessageText">{visibleAssistantText}</p> : null}
            <details className="aiSageSecondaryPanel" open={message.status === "in_progress"}>
              <summary>Retrieval details</summary>
              <div className="aiSageSecondaryPanelBody">
                {metadata.mode ? <div className="muted">Mode: {String(metadata.mode)}</div> : null}
                {typeof metadata.evidence_sufficient === "boolean" ? (
                  <div className="muted">Grounding strength: {metadata.evidence_sufficient ? "sufficient" : "thin"}</div>
                ) : null}
                {typeof metadata.weak_evidence_note === "string" && metadata.weak_evidence_note ? (
                  <div className="muted">{metadata.weak_evidence_note}</div>
                ) : null}
                {typeof metadata.thesis_question === "string" && metadata.thesis_question ? (
                  <div className="muted">Thesis focus: {metadata.thesis_question}</div>
                ) : null}
              </div>
            </details>

            {pushbackQuestions.length > 0 ? <SimpleList title="Pushback questions" items={pushbackQuestions} /> : null}
            {missingInformation.length > 0 ? <SimpleList title="Missing information" items={missingInformation} /> : null}
            {keyFacts.length > 0 ? <SimpleList title="Key facts" items={keyFacts} /> : null}

            {visibleEvidence.length > 0 ? (
              <section className="aiSageEvidenceSection">
                <div className="aiSageSectionTitle">Evidence</div>
                <div className="aiSageEvidenceStack">
                  {visibleEvidence.map((evidence) => (
                    <EvidenceCard key={evidence.id} evidence={evidence} />
                  ))}
                </div>
              </section>
            ) : null}

            {followUps.length > 0 ? (
              <section className="aiSageFollowUps">
                <div className="aiSageSectionTitle">Suggested follow-ups</div>
                <div className="aiSagePromptChipRow">
                  {followUps.map((prompt) => (
                    <button key={prompt} className="btn aiSagePromptChip" type="button" onClick={() => onUseSuggestion(prompt)}>
                      {prompt}
                    </button>
                  ))}
                </div>
              </section>
            ) : null}
          </>
        )}
      </article>
    </section>
  );
}

function dedupeEvidenceForDisplay(evidenceRows: AISageChatEvidence[]): AISageChatEvidence[] {
  const deduped: AISageChatEvidence[] = [];
  const seenChunkIds = new Set<string>();
  const seenFingerprints: string[] = [];

  for (const evidence of evidenceRows) {
    if (evidence.chunk_id && seenChunkIds.has(evidence.chunk_id)) {
      continue;
    }
    const fingerprint = evidenceFingerprint(evidence);
    if (isDuplicateEvidenceFingerprint(fingerprint, seenFingerprints)) {
      continue;
    }
    deduped.push(evidence);
    if (evidence.chunk_id) {
      seenChunkIds.add(evidence.chunk_id);
    }
    if (fingerprint) {
      seenFingerprints.push(fingerprint);
    }
  }

  return deduped;
}

function evidenceFingerprint(evidence: AISageChatEvidence): string {
  return normalizeEvidenceText(
    evidence.snippet || evidence.metadata_json?.anchor_text || evidence.metadata_json?.context_text,
  )
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isDuplicateEvidenceFingerprint(candidate: string, existingValues: string[]): boolean {
  if (!candidate) return false;
  const candidateTokens = evidenceFingerprintTokens(candidate);
  for (const existing of existingValues) {
    if (!existing) continue;
    if (candidate === existing) return true;
    const [shorter, longer] = [candidate, existing].sort((left, right) => left.length - right.length);
    if (shorter.length >= 48 && longer.includes(shorter)) return true;
    if (candidateTokens.size < 5) continue;
    const existingTokens = evidenceFingerprintTokens(existing);
    const intersection = [...candidateTokens].filter((token) => existingTokens.has(token)).length;
    const containment = intersection / Math.max(1, Math.min(candidateTokens.size, existingTokens.size));
    const union = new Set([...candidateTokens, ...existingTokens]).size;
    const jaccard = intersection / Math.max(1, union);
    if (containment >= 0.92 && jaccard >= 0.78) return true;
  }
  return false;
}

function evidenceFingerprintTokens(value: string): Set<string> {
  return new Set(value.split(/\s+/).filter((token) => token.length >= 3));
}

function SimpleList({ title, items }: { title: string; items: string[] }) {
  return (
    <section className="aiSageListSection">
      <div className="aiSageSectionTitle">{title}</div>
      <ul className="aiSageBulletList">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function EvidenceCard({ evidence }: { evidence: AISageChatEvidence }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const contextText = normalizeEvidenceText(evidence.metadata_json?.context_text);
  const anchorText = normalizeEvidenceText(evidence.metadata_json?.anchor_text || evidence.snippet);
  const expandedContext = contextText ? buildEvidenceContextExcerpt(contextText, anchorText) : "";
  const previewText = evidence.snippet?.trim() || "Open citation";
  const canExpand = Boolean(expandedContext);
  const sourceUrl = normalizeEvidenceText(evidence.source_url);
  const readerUrl = evidence.author_id && evidence.document_id ? readerRoute(evidence.author_id, evidence.document_id) : null;
  const copyText = previewText;
  const scoreText = typeof evidence.ranking_score === "number"
    ? `Score ${evidence.ranking_score.toFixed(2)}`
    : evidence.score_type || "Reference";

  async function copyChunk() {
    if (!copyText) return;
    await navigator.clipboard?.writeText(copyText);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  }

  return (
    <article className="aiSageEvidenceCard">
      <div className="aiSageEvidenceChunk">
        <div className="aiSageEvidenceCardHeader">
          <div className="muted aiSageEvidenceContextLabel">Chunk</div>
          <div className="aiSageEvidenceInlineActions">
            <div className="muted aiSageEvidenceScore">{scoreText}</div>
            <button className="btn aiSageEvidenceCopyButton" type="button" onClick={() => void copyChunk()} aria-label="Copy chunk content">
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
        <p className="aiSageEvidenceText">{previewText}</p>
        {canExpand ? (
          <button
            className="aiSageEvidenceExpandButton"
            type="button"
            onClick={() => setExpanded((current) => !current)}
            aria-expanded={expanded}
          >
            {expanded ? "Hide expanded context" : "Show expanded context"}
          </button>
        ) : null}
      </div>
      {expanded ? (
        <div className="aiSageEvidenceExpanded">
          <div className="muted aiSageEvidenceContextLabel">Expanded context</div>
          <p className="aiSageEvidenceText">{renderEvidenceText(expandedContext, anchorText || previewText)}</p>
          {sourceUrl ? (
            <div className="aiSageEvidenceActions">
              <a className="btn aiSageEvidenceLink" href={sourceUrl} target="_blank" rel="noreferrer">
                Open source
              </a>
            </div>
          ) : readerUrl ? (
            <div className="aiSageEvidenceActions">
              <Link className="btn aiSageEvidenceLink" to={readerUrl}>Open document</Link>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
