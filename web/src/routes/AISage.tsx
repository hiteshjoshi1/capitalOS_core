import { useContext, useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import "../App.css";
import PageShell from "../components/PageShell";
import { AuthContext } from "../context/AuthContext";
import { api } from "../lib/api";
import type {
  ConceptAuthorView,
  ConceptQueryResult,
  ConceptSuggestedReading,
  RagEvidenceChunk,
  ThesisLiveSource,
  UpdatedThesisView,
} from "../lib/api";

const EXAMPLE_PROMPTS = [
  "What makes a good business?",
  "How should I think about moat, scale economies shared, or network effects?",
  "If Buffett and Nick Sleep were studying Tencent Music, what questions would they ask first?",
  "Here is my thesis on Spotify: the platform moat is durable. Pressure test it.",
  "What would Munger worry about in a streaming business with high content costs?",
];

type ConversationTurn = {
  id: string;
  query: string;
  loading: boolean;
  error: string | null;
  result: ConceptQueryResult | null;
  showSources: boolean;
};

function createTurnId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function AISage() {
  const { user } = useContext(AuthContext);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [showPromptMenu, setShowPromptMenu] = useState(false);
  const greetingName = user?.display_name?.trim() || user?.username?.trim() || "there";
  const hasTurns = turns.length > 0;

  const canSubmit = Boolean(query.trim()) && !loading;

  async function submitQuery(submittedQuery: string) {
    const turnId = createTurnId();

    setLoading(true);
    setShowPromptMenu(false);
    setTurns((current) => [
      ...current,
      {
        id: turnId,
        query: submittedQuery,
        loading: true,
        error: null,
        result: null,
        showSources: false,
      },
    ]);

    try {
      const nextResult = await api.aiSageQuery({
        query: submittedQuery,
        top_k: 12,
      });
      setTurns((current) =>
        current.map((turn) =>
          turn.id === turnId
            ? { ...turn, loading: false, result: nextResult }
            : turn,
        ),
      );
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setTurns((current) =>
        current.map((turn) =>
          turn.id === turnId
            ? { ...turn, loading: false, error: message }
            : turn,
        ),
      );
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!canSubmit) return;

    const submittedQuery = query.trim();
    setQuery("");
    await submitQuery(submittedQuery);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSubmit();
    }
  }

  function applyPrompt(prompt: string) {
    setQuery(prompt);
    setShowPromptMenu(false);
  }

  function toggleSources(turnId: string) {
    setTurns((current) =>
      current.map((turn) =>
        turn.id === turnId
          ? { ...turn, showSources: !turn.showSources }
          : turn,
      ),
    );
  }

  return (
    <PageShell
      title=""
      hideHeader
    >
      <div className={`wrap aiSagePage aiSageChatPage ${hasTurns ? "aiSagePageActive" : "aiSagePageEmpty"}`}>
        {!hasTurns ? (
          <section className="aiSageHero" aria-label="AI Sage welcome">
            <h1 className="aiSageHeroTitle">Hello {greetingName}</h1>
            <p className="aiSageHeroSubtitle">What insights are we discovering today?</p>
          </section>
        ) : null}

        <section className="aiSageTimeline" aria-live="polite">
          {turns.map((turn) => (
            <section key={turn.id} className="aiSageTurn">
              <section className="card aiSageBubbleCard aiSageUserBubble">
                <p className="aiSagePromptEcho">{turn.query}</p>
              </section>

              {turn.loading ? (
                <section className="card aiSageBubbleCard aiSageAssistantBubble">
                  <div className="aiSageThinking" role="status" aria-live="polite">
                    <div className="aiSageThinkingDots" aria-hidden="true">
                      <span className="aiSageThinkingDot" />
                      <span className="aiSageThinkingDot" />
                      <span className="aiSageThinkingDot" />
                    </div>
                    <p className="muted aiSageAnswerText">Working through your question...</p>
                  </div>
                </section>
              ) : null}

              {turn.error ? (
                <section className="card aiSageBubbleCard aiSageAssistantBubble">
                  <div className="cardTitle">Request Error</div>
                  <div className="aiSageError">{turn.error}</div>
                </section>
              ) : null}

              {turn.result ? (
                <AssistantTurn
                  turn={turn}
                  onToggleSources={() => toggleSources(turn.id)}
                />
              ) : null}
            </section>
          ))}
        </section>

        <section className={`aiSageComposerDock ${hasTurns ? "aiSageComposerDockThread" : "aiSageComposerDockHero"}`}>
          {showPromptMenu ? (
            <div className="card aiSagePromptMenu" aria-label="Starter prompts">
              <div className="cardTitle">Starter Prompts</div>
              <div className="aiSagePromptMenuList">
                {EXAMPLE_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    className="btn aiSageExampleBtn"
                    onClick={() => applyPrompt(prompt)}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <form className="card aiSageComposerBar" onSubmit={(event) => void handleSubmit(event)}>
            <button
              type="button"
              className="btn aiSageComposerPlus"
              aria-label="Open starter prompts"
              aria-expanded={showPromptMenu}
              onClick={() => setShowPromptMenu((value) => !value)}
            >
              +
            </button>

            <textarea
              className="formInput aiSagePromptInput aiSagePromptInputCompact"
              rows={1}
              value={query}
              placeholder="Ask AI Sage anything about a business, thesis, risk, or mental model..."
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleKeyDown}
            />

            <button
              type="submit"
              className="btn aiSageComposerSend"
              aria-label="Send query"
              disabled={!canSubmit}
            >
              {loading ? "..." : "Send"}
            </button>
          </form>

          <div className="aiSageComposerHint muted">
            Enter to send. Shift+Enter for a new line.
          </div>
        </section>
      </div>
    </PageShell>
  );
}

function AssistantTurn({
  turn,
  onToggleSources,
}: {
  turn: ConversationTurn;
  onToggleSources: () => void;
}) {
  const result = turn.result;
  if (!result) return null;

  const isThesisMode = result.mode === "thesis";
  const bestPassages = result.best_passages ?? [];
  const authorViews = result.author_views ?? [];
  const suggestedReadings = result.suggested_readings ?? [];
  const liveSourcesRaw = result.live_sources ?? [];
  const pushbackQuestions = result.pushback_questions ?? [];
  const missingInformation = result.missing_information ?? [];
  const keyFacts = result.key_facts ?? [];
  const followUpQuestions = result.follow_up_questions ?? [];
  const updatedThesisView = result.updated_thesis_view ?? null;

  const answerText =
    result.synthesis ??
    result.weak_evidence_note ??
    "AI Sage could not ground a useful answer from the current corpus.";

  return (
    <section className="card aiSageBubbleCard aiSageAssistantBubble">
      {/* Lead answer — synthesis or weak evidence note */}
      <p className="aiSageAnswerLead">{answerText}</p>

      {result.weak_evidence_note && result.synthesis ? (
        <p className="muted aiSageNote">{result.weak_evidence_note}</p>
      ) : null}

      {/* ── Thesis mode sections ─────────────────────────────────────── */}

      {isThesisMode && result.thesis_question ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Thesis / Question</div>
          <p className="aiSageAnswerText">{result.thesis_question}</p>
        </section>
      ) : null}

      {isThesisMode && pushbackQuestions.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Key Pushback Questions</div>
          <ol className="aiSageQuestionList">
            {pushbackQuestions.map((q, i) => (
              <li key={i} className="aiSageQuestionItem">{q}</li>
            ))}
          </ol>
        </section>
      ) : null}

      {isThesisMode && missingInformation.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Missing Information</div>
          <ul className="aiSageQuestionList">
            {missingInformation.map((m, i) => (
              <li key={i} className="aiSageQuestionItem">{m}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {isThesisMode && keyFacts.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Key Facts</div>
          <ul className="aiSageQuestionList">
            {keyFacts.map((f, i) => (
              <li key={i} className="aiSageQuestionItem">{f}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* ── Author views (shared between concept and thesis mode) ─────── */}

      {authorViews.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">{isThesisMode ? "Author Views" : "Perspectives"}</div>
          <div className="aiSageAuthorViewList">
            {authorViews.map((av: ConceptAuthorView) => (
              <article key={av.author_id} className="aiSageAuthorViewCard">
                <div className="aiSageAuthorViewHeader">
                  <strong>{av.author_name}</strong>
                </div>
                <p className="aiSageAuthorViewText">{av.view}</p>
                {av.key_passages.length > 0 ? (
                  <div className="aiSageKeyPassages">
                    {av.key_passages.map((passage, index) => (
                      <blockquote key={index} className="aiSageKeyPassage">
                        {passage.length > 260 ? `${passage.slice(0, 260)}...` : passage}
                      </blockquote>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {/* ── Synthesis (shared) ────────────────────────────────────────── */}

      {/* ── Critique (shared) ────────────────────────────────────────── */}
      {result.critique ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Critique</div>
          <p className="aiSageAnswerText">{result.critique}</p>
        </section>
      ) : null}

      {/* ── Updated thesis view (thesis mode only) ───────────────────── */}
      {isThesisMode && updatedThesisView ? (
        <section className="aiSageResponseSection" data-testid="updated-thesis-view">
          <div className="aiSageSectionTitle">Updated Thesis View</div>
          {updatedThesisView.stronger.length > 0 ? (
            <div className="aiSageThesisGroup">
              <div className="aiSageThesisGroupLabel aiSageThesisStronger">Looks Stronger</div>
              <ul className="aiSageQuestionList">
                {(updatedThesisView as UpdatedThesisView).stronger.map((s, i) => (
                  <li key={i} className="aiSageQuestionItem">{s}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {updatedThesisView.weaker.length > 0 ? (
            <div className="aiSageThesisGroup">
              <div className="aiSageThesisGroupLabel aiSageThesisWeaker">Looks Weaker</div>
              <ul className="aiSageQuestionList">
                {(updatedThesisView as UpdatedThesisView).weaker.map((w, i) => (
                  <li key={i} className="aiSageQuestionItem">{w}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {updatedThesisView.unresolved.length > 0 ? (
            <div className="aiSageThesisGroup">
              <div className="aiSageThesisGroupLabel aiSageThesisUnresolved">Still Unresolved</div>
              <ul className="aiSageQuestionList">
                {(updatedThesisView as UpdatedThesisView).unresolved.map((u, i) => (
                  <li key={i} className="aiSageQuestionItem">{u}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      {/* ── Follow-up questions (thesis mode — NOT auto-researched) ──── */}
      {isThesisMode && followUpQuestions.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Follow-up Questions to Explore</div>
          <p className="muted aiSageNote">
            These questions were surfaced during analysis. Ask AI Sage any of them to continue.
          </p>
          <ol className="aiSageQuestionList">
            {followUpQuestions.map((q, i) => (
              <li key={i} className="aiSageQuestionItem">{q}</li>
            ))}
          </ol>
        </section>
      ) : null}

      {/* ── Suggested readings (concept mode) ───────────────────────── */}
      {!isThesisMode && suggestedReadings.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Suggested Readings</div>
          <div className="aiSageSuggestedReadingList">
            {suggestedReadings.map((sr: ConceptSuggestedReading, index: number) => (
              <article key={index} className="aiSageSuggestedReadingCard">
                <div className="aiSageSuggestedReadingHeader">
                  <strong>{sr.author_name}</strong>
                  <span className="muted aiSageSuggestedReadingReason">{sr.reason}</span>
                </div>
                <p className="aiSageEvidenceText">
                  {sr.passage.length > 400 ? `${sr.passage.slice(0, 400)}...` : sr.passage}
                </p>
                {sr.source_url ? (
                  <div className="muted aiSageEvidenceMeta">{sr.source_url}</div>
                ) : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {/* ── Sources (collapsible) ─────────────────────────────────────── */}
      {bestPassages.length > 0 || liveSourcesRaw.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSourcesHeader">
            <div>
              <div className="aiSageSectionTitle">Sources</div>
              <p className="muted aiSageSourcesHint">
                {isThesisMode
                  ? "Corpus passages and live research used in this analysis."
                  : "Open to inspect the passages behind the answer."}
              </p>
            </div>
            <button
              type="button"
              className="btn"
              onClick={onToggleSources}
            >
              {turn.showSources
                ? "Hide Sources"
                : `Show Sources (${bestPassages.length + liveSourcesRaw.length})`}
            </button>
          </div>

          {turn.showSources ? (
            <div className="aiSageEvidenceList">
              {/* Corpus evidence — thinker corpus */}
              {bestPassages.map((chunk: RagEvidenceChunk, index: number) => (
                (() => {
                  const contextText =
                    typeof chunk.metadata.context_text === "string"
                      ? chunk.metadata.context_text
                      : null;
                  const rerankerScore =
                    typeof chunk.metadata.reranker_score === "number"
                      ? chunk.metadata.reranker_score
                      : null;
                  return (
                    <article key={chunk.chunk_id} className="aiSageEvidenceCard">
                      <div className="aiSageEvidenceHeader">
                        <div>
                          <strong>{chunk.author_name}</strong>
                          <span className="muted aiSageEvidenceRank">Passage {index + 1}</span>
                          <span className="aiSagePill aiSagePillCorpus">Thinker Corpus</span>
                          {rerankerScore !== null ? <span className="aiSagePill">Reranked</span> : null}
                        </div>
                        <span className="aiSagePill">
                          {(chunk.similarity * 100).toFixed(1)}% relevance
                        </span>
                      </div>
                      <p className="aiSageEvidenceText">
                        {chunk.text.length > 520 ? `${chunk.text.slice(0, 520)}...` : chunk.text}
                      </p>
                      {contextText && contextText !== chunk.text ? (
                        <details>
                          <summary>Show surrounding context</summary>
                          <p className="aiSageEvidenceText">
                            {contextText.length > 1200 ? `${contextText.slice(0, 1200)}...` : contextText}
                          </p>
                        </details>
                      ) : null}
                      <div className="muted aiSageEvidenceMeta">
                        {chunk.metadata.source_url ? String(chunk.metadata.source_url) : "Source unavailable"}
                        {chunk.metadata.published_at ? ` · ${String(chunk.metadata.published_at)}` : ""}
                      </div>
                    </article>
                  );
                })()
              ))}

              {/* Live sources — web / filings */}
              {liveSourcesRaw.map((src: ThesisLiveSource, index: number) => (
                <article key={index} className="aiSageEvidenceCard">
                  <div className="aiSageEvidenceHeader">
                    <div>
                      <strong>{src.title}</strong>
                      <span className="aiSagePill aiSagePillLive">
                        {src.source_type === "filing" ? "SEC Filing" : src.source_type === "transcript" ? "Transcript" : "Web"}
                      </span>
                    </div>
                  </div>
                  <p className="aiSageEvidenceText">{src.snippet}</p>
                  <div className="muted aiSageEvidenceMeta">{src.url}</div>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
