import { useState } from "react";
import type { KeyboardEvent } from "react";
import "../App.css";
import PageShell from "../components/PageShell";
import { api } from "../lib/api";
import type { RagEvidenceChunk, RagQueryResult, RagSelectedAuthor } from "../lib/api";

const EXAMPLE_PROMPTS = [
  "If Buffett and Nick Sleep were studying Tencent Music, what questions would they ask first?",
  "What does Warren Buffett emphasize when evaluating a durable moat and strong long-term economics?",
  "What does Nick Sleep emphasize about scale economies shared and long-term business quality?",
];

export default function AISage() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RagQueryResult | null>(null);
  const [showSources, setShowSources] = useState(false);
  const [showPromptMenu, setShowPromptMenu] = useState(false);

  const canSubmit = Boolean(query.trim()) && !loading;
  const selectedAuthors = result?.selected_authors ?? [];
  const evidenceChunks = result?.evidence_chunks ?? [];

  async function handleSubmit() {
    if (!canSubmit) return;

    setLoading(true);
    setError(null);
    setShowSources(false);
    setShowPromptMenu(false);

    try {
      const nextResult = await api.ragQuery({
        query: query.trim(),
        top_k: 8,
      });
      setResult(nextResult);
    } catch (e: unknown) {
      setResult(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSubmit();
    }
  }

  function applyPrompt(prompt: string) {
    setQuery(prompt);
    setError(null);
    setShowPromptMenu(false);
  }

  return (
    <PageShell
      title="AI Sage"
      subtitle="One question in. Relevant author context, answer, and evidence at the top."
    >
      <div className="wrap aiSagePage aiSageChatPage">
        <section className="aiSageTimeline" aria-live="polite">
          {!loading && !error && !result ? (
            <section className="card aiSageWelcomeCard">
              <div className="cardTitle">Start Here</div>
              <p className="aiSageAnswerText">
                Ask an investing or company question. AI Sage will decide whether the author corpus is relevant and surface the best context first.
              </p>
              <p className="muted aiSageNote">
                Use the <strong>+</strong> in the composer for starter prompts.
              </p>
            </section>
          ) : null}

          {loading ? (
            <section className="card aiSageBubbleCard">
              <div className="cardTitle">Working</div>
              <p className="muted">
                AI Sage is checking the corpus and assembling the most relevant author context for this question.
              </p>
            </section>
          ) : null}

          {error ? (
            <section className="card aiSageBubbleCard">
              <div className="cardTitle">Request Error</div>
              <div className="aiSageError">{error}</div>
            </section>
          ) : null}

          {result ? (
            <section className="card aiSageBubbleCard">
              <div className="cardTitle">Your Question</div>
              <p className="aiSagePromptEcho">{result.query || query.trim()}</p>
            </section>
          ) : null}

          {result?.answer ? (
            <section className="card aiSageAnswerCard aiSageBubbleCard">
              <div className="cardTitle">Answer</div>
              <p className="aiSageAnswerText">{result.answer}</p>
              {result.missing_information ? (
                <p className="muted aiSageNote">Gap: {result.missing_information}</p>
              ) : null}
            </section>
          ) : null}

          {!loading && !error && result && !result.answer ? (
            <section className="card aiSageBubbleCard">
              <div className="cardTitle">No Strong Answer Yet</div>
              <p className="muted">
                {result.missing_information ?? "AI Sage could not ground a useful answer from the current corpus."}
              </p>
            </section>
          ) : null}

          {selectedAuthors.length > 0 ? (
            <section className="card aiSageBubbleCard">
              <div className="cardTitle">Relevant Author Perspectives</div>
              <div className="aiSageAuthorGrid">
                {selectedAuthors.map((author: RagSelectedAuthor) => (
                  <article key={author.author_id} className="aiSageAuthorCard">
                    <div className="aiSageAuthorHeader">
                      <strong>{author.name}</strong>
                      <span className="muted">Score {author.score.toFixed(2)}</span>
                    </div>
                    {author.worldview ? (
                      <p className="aiSageAuthorWorldview">{author.worldview}</p>
                    ) : (
                      <p className="muted aiSageAuthorWorldview">
                        AI Sage selected this author because their corpus appears relevant to your question.
                      </p>
                    )}
                    {author.key_maxims?.length ? (
                      <div className="aiSageTokenRow">
                        {author.key_maxims.slice(0, 3).map((maxim) => (
                          <span key={maxim} className="aiSagePill">
                            {maxim}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            </section>
          ) : null}

          {evidenceChunks.length > 0 ? (
            <section className="card aiSageBubbleCard">
              <div className="aiSageSourcesHeader">
                <div>
                  <div className="cardTitle">Inspect Sources</div>
                  <p className="muted aiSageSourcesHint">
                    Hidden by default. Open this only if you want to inspect the passages behind the answer.
                  </p>
                </div>
                <button
                  type="button"
                  className="btn"
                  onClick={() => setShowSources((value) => !value)}
                >
                  {showSources ? "Hide Sources" : `Show Sources (${evidenceChunks.length})`}
                </button>
              </div>

              {showSources ? (
                <div className="aiSageEvidenceList">
                  {evidenceChunks.map((chunk: RagEvidenceChunk, index: number) => (
                    <article key={chunk.chunk_id} className="aiSageEvidenceCard">
                      <div className="aiSageEvidenceHeader">
                        <div>
                          <strong>{chunk.author_name}</strong>
                          <span className="muted aiSageEvidenceRank">Chunk {index + 1}</span>
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

          <div className="card aiSageComposerBar">
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
          </div>

          <div className="aiSageComposerHint muted">
            Enter to send. Shift+Enter for a new line.
          </div>
        </section>
      </div>
    </PageShell>
  );
}
