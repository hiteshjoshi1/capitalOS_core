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
  type AISageChatSearchResult,
  type AISageChatSummary,
  type AISageStreamEvent,
} from "../lib/api";

const EVIDENCE_CONTEXT_TARGET_CHARS = 1200;
const CHAT_ROW_TITLE_LIMIT = 50;

function readerRoute(authorId: string, documentId: string): string {
  return `/author-library/${encodeURIComponent(authorId)}/documents/${encodeURIComponent(documentId)}`;
}

function formatTimestamp(value: string): string {
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(dt);
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
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stickToBottomRef = useRef(true);

  const [query, setQuery] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchResults, setSearchResults] = useState<AISageChatSearchResult[]>([]);
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
      setActiveChat(null);
      setActiveChatError(null);
      return;
    }
    if (activeChat?.id === chatId) {
      return;
    }
    void loadChatDetail(chatId);
  }, [activeChat?.id, chatId, loadChatDetail]);

  useEffect(() => {
    const textarea = composerRef.current;
    if (textarea && !streaming) {
      textarea.focus();
    }
  }, [chatId, streaming]);

  useEffect(() => {
    const handleShortcut = (event: globalThis.KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    document.addEventListener("keydown", handleShortcut);
    return () => {
      document.removeEventListener("keydown", handleShortcut);
    };
  }, []);

  useEffect(() => {
    const closeMenus = () => setSidebarMenuChatId(null);
    document.addEventListener("click", closeMenus);
    return () => {
      document.removeEventListener("click", closeMenus);
    };
  }, []);

  useEffect(() => {
    if (!searchOpen || !searchQuery.trim()) {
      setSearchResults([]);
      return;
    }
    let active = true;
    setSearchLoading(true);
    void api.aiSageSearchChats(searchQuery)
      .then((response) => {
        if (active) setSearchResults(response.items);
      })
      .catch(() => {
        if (active) setSearchResults([]);
      })
      .finally(() => {
        if (active) setSearchLoading(false);
      });
    return () => {
      active = false;
    };
  }, [searchOpen, searchQuery]);

  useEffect(() => {
    const container = transcriptRef.current;
    if (!container) return;
    if (!stickToBottomRef.current) return;
    container.scrollTop = container.scrollHeight;
  }, [activeChat?.messages, streaming]);

  async function handleCreateChat(focusComposer = false): Promise<void> {
    const created = await api.aiSageCreateChat({});
    setActiveChat(created);
    setSidebarOpen(false);
    setSidebarMenuChatId(null);
    await loadChatList();
    navigate(`/ai-sage/chats/${created.id}`);
    if (focusComposer) {
      requestAnimationFrame(() => composerRef.current?.focus());
    }
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
      setActiveChat(null);
      navigate("/ai-sage");
    }
    await loadChatList();
  }

  async function handleRetry(messageId: string): Promise<void> {
    if (!activeChat) return;
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
    let targetChatId = activeChat?.id;
    if (!targetChatId) {
      const created = await api.aiSageCreateChat({});
      setActiveChat(created);
      targetChatId = created.id;
      navigate(`/ai-sage/chats/${created.id}`);
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setQuery("");

    try {
      await streamAiSageChatMessage(
        targetChatId,
        { content },
        (streamEvent) => {
          applyStreamEvent(streamEvent, targetChatId!);
        },
        { signal: controller.signal },
      );
      await loadChatList();
    } catch (error) {
      if (controller.signal.aborted) {
        setValidationError("Generation cancelled.");
      } else {
        setValidationError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
    }
  }

  function applyStreamEvent(streamEvent: AISageStreamEvent, targetChatId: string): void {
    if (streamEvent.type === "ack") {
      setActiveChat((current) => {
        const base = current && current.id === targetChatId ? current : {
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
      setActiveChat(streamEvent.chat);
      setValidationError(null);
      return;
    }

    setActiveChat((current) => {
      if (!current) return current;
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
  }, [activeChat, activeChatError, activeChatLoading, greetingName]);

  const showLanding = !activeChatLoading && !activeChatError && (!activeChat || activeChat.messages.length === 0);

  return (
    <PageShell title="" hideHeader headerActions={headerActions}>
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
            <button className="aiSageSidebarAction aiSageSidebarActionPrimary" type="button" onClick={() => void handleCreateChat(true)}>
              <SidebarActionIcon>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.12 2.12 0 1 1 3 3L7 19l-4 1 1-4Z" />
                </svg>
              </SidebarActionIcon>
              <span>New chat</span>
            </button>
            <button className="aiSageSidebarAction" type="button" onClick={() => setSearchOpen(true)}>
              <SidebarActionIcon>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="11" cy="11" r="7" />
                  <path d="m20 20-3.5-3.5" />
                </svg>
              </SidebarActionIcon>
              <span>Search chats</span>
            </button>
            <button className="aiSageSidebarAction" type="button" title="Coming soon">
              <SidebarActionIcon>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H11l2 2h5.5A2.5 2.5 0 0 1 21 9.5v7A2.5 2.5 0 0 1 18.5 19H5.5A2.5 2.5 0 0 1 3 16.5Z" />
                  <path d="M12 10v6" />
                  <path d="M9 13h6" />
                </svg>
              </SidebarActionIcon>
              <span>Projects</span>
            </button>
          </div>
          {chatListError ? <div className="aiSageErrorState">{chatListError}</div> : null}
          {chatsLoading ? <div className="muted">Loading chats…</div> : null}
          {!chatsLoading && chatSummaries.length === 0 ? <div className="aiSageEmptySidebar">No chats yet.</div> : null}
          <div className="aiSageSidebarList" aria-label="Saved chats">
            {chatSummaries.map((chat) => (
              <article
                key={chat.id}
                className={`aiSageChatListItem ${chatId === chat.id ? "aiSageChatListItemActive" : ""}`}
              >
                <button
                  type="button"
                  className="aiSageChatListButton"
                  onClick={() => {
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
        </aside>

        <div className="aiSageMainPanel">
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
              <div className="aiSageTranscript card" ref={transcriptRef} onScroll={handleTranscriptScroll}>
                {transcriptEmptyState}
                {activeChat?.messages.map((message) => (
                  <MessageBubble key={message.id} message={message} onRetry={handleRetry} onUseSuggestion={setQuery} />
                ))}
              </div>

              <form className="card aiSageComposer" onSubmit={(event) => void handleSendMessage(event)}>
                <textarea
                  ref={composerRef}
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

      {searchOpen ? (
        <div className="modalBackdrop" role="dialog" aria-modal="true" aria-label="Search AI Sage chats">
          <div className="modal aiSageSearchModal">
            <div className="aiSageSearchHeader">
              <div>
                <div className="cardTitle">Search chats</div>
                <div className="muted">Searches chat titles and message text for your account only.</div>
              </div>
              <button className="btn" type="button" onClick={() => setSearchOpen(false)}>
                Close
              </button>
            </div>
            <input
              autoFocus
              className="formInput"
              placeholder="Search chat history…"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
            />
            <div className="aiSageSearchResults">
              {searchLoading ? <div className="muted">Searching…</div> : null}
              {!searchLoading && searchQuery.trim() && searchResults.length === 0 ? (
                <div className="muted">No matches found.</div>
              ) : null}
              {searchResults.map((result) => (
                <button
                  key={`${result.chat_id}-${result.updated_at}`}
                  type="button"
                  className="aiSageSearchResult"
                  onClick={() => {
                    setSearchOpen(false);
                    setSidebarOpen(false);
                    navigate(`/ai-sage/chats/${result.chat_id}`);
                  }}
                >
                  <strong>{result.title}</strong>
                  <span className="muted">{result.snippet || "Open chat"}</span>
                  <span className="muted">{formatTimestamp(result.updated_at)}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

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
            <p className="aiSageMessageText">{message.content || "Thinking…"}</p>
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

            {message.evidence.length > 0 ? (
              <section className="aiSageEvidenceSection">
                <div className="aiSageSectionTitle">Evidence</div>
                <div className="aiSageEvidenceStack">
                  {message.evidence.map((evidence) => (
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
  const canOpenReader = Boolean(evidence.author_id && evidence.document_id);
  const [expanded, setExpanded] = useState(false);
  const contextText = normalizeEvidenceText(evidence.metadata_json?.context_text);
  const anchorText = normalizeEvidenceText(evidence.metadata_json?.anchor_text || evidence.snippet);
  const expandedContext = contextText ? buildEvidenceContextExcerpt(contextText, anchorText) : "";
  const previewText = evidence.snippet?.trim() || "Open citation";
  const canExpand = Boolean(expandedContext);

  return (
    <article className="aiSageEvidenceCard">
      <div className="aiSageEvidenceCardHeader">
        <div>
          <strong>{evidence.title || evidence.author_name || "Retrieved source"}</strong>
          <div className="muted">
            {evidence.author_name ? `${evidence.author_name} · ` : ""}
            {typeof evidence.ranking_score === "number" ? `Score ${evidence.ranking_score.toFixed(2)}` : evidence.score_type || "Reference"}
          </div>
        </div>
      </div>
      <button
        className="aiSageEvidencePreviewButton"
        type="button"
        onClick={() => setExpanded((current) => !current)}
        aria-expanded={expanded}
      >
        <p className="aiSageEvidenceText">{previewText}</p>
        {canExpand ? (
          <span className="muted aiSageEvidencePreviewHint">
            {expanded ? "Hide expanded context" : "Show expanded context"}
          </span>
        ) : null}
      </button>
      {expanded ? (
        <div className="aiSageEvidenceExpanded">
          {expandedContext ? (
            <>
              <div className="muted aiSageEvidenceContextLabel">Expanded context</div>
              <p className="aiSageEvidenceText">{renderEvidenceText(expandedContext, anchorText || previewText)}</p>
            </>
          ) : null}
          {canOpenReader ? (
            <div className="aiSageEvidenceActions">
              <Link className="btn aiSageEvidenceLink" to={readerRoute(evidence.author_id!, evidence.document_id!)}>
                Open document
              </Link>
            </div>
          ) : evidence.source_url ? (
            <div className="aiSageEvidenceActions">
              <a className="btn aiSageEvidenceLink" href={evidence.source_url} target="_blank" rel="noreferrer">
                Open source
              </a>
            </div>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
