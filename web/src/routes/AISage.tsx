import { useState } from "react";
import type { FormEvent, KeyboardEvent } from "react";
import "../App.css";
import PageShell from "../components/PageShell";
import { api } from "../lib/api";
import type {
  ConceptAuthorView,
  ConceptQueryResult,
  ConceptSuggestedReading,
  RagEvidenceChunk,
} from "../lib/api";

const EXAMPLE_PROMPTS = [
  "What makes a good business?",
  "How should I think about moat, scale economies shared, or network effects?",
  "If Buffett and Nick Sleep were studying Tencent Music, what questions would they ask first?",
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
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [showPromptMenu, setShowPromptMenu] = useState(false);

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
      title="AI Sage"
      subtitle="Ask a concept question. Get a grounded answer, differentiated perspectives, and a critique."
    >
      <div className="wrap aiSagePage aiSageChatPage">
        <section className="aiSageTimeline" aria-live="polite">
          {!turns.length ? (
            <section className="card aiSageWelcomeCard">
              <div className="cardTitle">Start Here</div>
              <p className="aiSageAnswerText">
                Ask a concept question about business, investing, or mental models.
                AI Sage will answer directly, then show the supporting perspectives and source material.
              </p>
              <p className="muted aiSageNote">
                Use the <strong>+</strong> in the composer for starter prompts.
              </p>
            </section>
          ) : null}

          {turns.map((turn) => (
            <section key={turn.id} className="aiSageTurn">
              <section className="card aiSageBubbleCard aiSageUserBubble">
                <p className="aiSagePromptEcho">{turn.query}</p>
              </section>

              {turn.loading ? (
                <section className="card aiSageBubbleCard aiSageAssistantBubble">
                  <p className="muted aiSageAnswerText">
                    AI Sage is selecting relevant authors, retrieving corpus passages, and assembling an answer.
                  </p>
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

        <section className="aiSageComposerDock">
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

  const bestPassages = result.best_passages ?? [];
  const authorViews = result.author_views ?? [];
  const suggestedReadings = result.suggested_readings ?? [];
  const answerText =
    result.synthesis ??
    result.weak_evidence_note ??
    "AI Sage could not ground a useful answer from the current corpus.";

  return (
    <section className="card aiSageBubbleCard aiSageAssistantBubble">
      <p className="aiSageAnswerLead">{answerText}</p>

      {result.weak_evidence_note && result.synthesis ? (
        <p className="muted aiSageNote">{result.weak_evidence_note}</p>
      ) : null}

      {authorViews.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Perspectives</div>
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

      {result.critique ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSectionTitle">Critique</div>
          <p className="aiSageAnswerText">{result.critique}</p>
        </section>
      ) : null}

      {suggestedReadings.length > 0 ? (
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

      {bestPassages.length > 0 ? (
        <section className="aiSageResponseSection">
          <div className="aiSageSourcesHeader">
            <div>
              <div className="aiSageSectionTitle">Sources</div>
              <p className="muted aiSageSourcesHint">
                Open to inspect the passages behind the answer.
              </p>
            </div>
            <button
              type="button"
              className="btn"
              onClick={onToggleSources}
            >
              {turn.showSources ? "Hide Sources" : `Show Sources (${bestPassages.length})`}
            </button>
          </div>

          {turn.showSources ? (
            <div className="aiSageEvidenceList">
              {bestPassages.map((chunk: RagEvidenceChunk, index: number) => (
                <article key={chunk.chunk_id} className="aiSageEvidenceCard">
                  <div className="aiSageEvidenceHeader">
                    <div>
                      <strong>{chunk.author_name}</strong>
                      <span className="muted aiSageEvidenceRank">Passage {index + 1}</span>
                    </div>
                    <span className="aiSagePill">
                      {(chunk.similarity * 100).toFixed(1)}% match
                    </span>
                  </div>
                  <p className="aiSageEvidenceText">
                    {chunk.text.length > 520 ? `${chunk.text.slice(0, 520)}...` : chunk.text}
                  </p>
                  <div className="muted aiSageEvidenceMeta">
                    {chunk.metadata.source_url ? String(chunk.metadata.source_url) : "Source unavailable"}
                    {chunk.metadata.published_at ? ` · ${String(chunk.metadata.published_at)}` : ""}
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}
    </section>
  );
}
