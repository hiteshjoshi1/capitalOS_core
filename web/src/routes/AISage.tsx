import { useState } from "react";
import "../App.css";
import PageShell from "../components/PageShell";
import { api } from "../lib/api";
import type {
  RagCompanyContextResult,
  RagEvidenceChunk,
  RagQueryResult,
  RagSelectedAuthor,
} from "../lib/api";

type Mode = "ask" | "retrieve" | "company_context";

type ModeConfig = {
  label: string;
  summary: string;
  purpose: string;
  queryPlaceholder: string;
  submitLabel: string;
  exampleQuery: string;
  exampleCompany?: string;
  resultTitle: string;
};

const MODE_CONFIG: Record<Mode, ModeConfig> = {
  ask: {
    label: "Ask",
    summary: "Best for a direct grounded answer with evidence attached.",
    purpose: "Use this when you want AI Sage to read the corpus, synthesize an answer, and show the supporting passages.",
    queryPlaceholder: "Ask a grounded question, for example: What does Warren Buffett emphasize about durable moats?",
    submitLabel: "Ask AI Sage",
    exampleQuery: "What does Warren Buffett emphasize when evaluating a durable moat and strong long-term economics?",
    resultTitle: "Grounded Answer",
  },
  retrieve: {
    label: "Retrieve",
    summary: "Best for research mode when you want the raw evidence pack first.",
    purpose: "Use this when you do not want synthesis yet and only want the highest-matching chunks and citations.",
    queryPlaceholder: "Retrieve source material, for example: scale economies shared Nick Sleep Costco Amazon",
    submitLabel: "Retrieve Evidence",
    exampleQuery: "What does Nick Sleep emphasize about scale economies shared and long-term business quality?",
    resultTitle: "Evidence Pack",
  },
  company_context: {
    label: "Company Context",
    summary: "Best for preparing a company analysis lens before deeper reasoning.",
    purpose: "Use this when you want the most relevant authors and evidence pack for a company-specific question.",
    queryPlaceholder: "Ask a company-specific question, for example: How should we think about moat, capital allocation, and holding quality?",
    submitLabel: "Build Company Context",
    exampleQuery: "How would Warren Buffett likely think about this company’s moat, capital allocation, and long-term holding quality?",
    exampleCompany: "Apple",
    resultTitle: "Company Context",
  },
};

const AUTHOR_EXAMPLES = [
  { label: "Buffett", value: "warren_buffett" },
  { label: "Nick Sleep", value: "nick_sleep" },
  { label: "Howard Marks", value: "howard_marks" },
  { label: "Clear", value: "" },
];

function resultSummary(
  mode: Mode,
  queryResult: RagQueryResult | null,
  companyResult: RagCompanyContextResult | null,
): string {
  if (mode === "company_context") {
    const authors = companyResult?.relevant_author_lenses.length ?? 0;
    const evidence = companyResult?.evidence_pack.length ?? 0;
    return `${authors} author lens${authors === 1 ? "" : "es"} · ${evidence} evidence chunk${evidence === 1 ? "" : "s"}`;
  }

  const authors = queryResult?.selected_authors.length ?? 0;
  const evidence = queryResult?.evidence_chunks.length ?? 0;
  return `${authors} selected author${authors === 1 ? "" : "s"} · ${evidence} evidence chunk${evidence === 1 ? "" : "s"}`;
}

export default function AISage() {
  const [mode, setMode] = useState<Mode>("ask");
  const [showGuide, setShowGuide] = useState(true);
  const [query, setQuery] = useState("");
  const [authorFilter, setAuthorFilter] = useState("");
  const [company, setCompany] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queryResult, setQueryResult] = useState<RagQueryResult | null>(null);
  const [companyResult, setCompanyResult] = useState<RagCompanyContextResult | null>(null);

  const config = MODE_CONFIG[mode];
  const selectedAuthors =
    queryResult?.selected_authors ?? companyResult?.relevant_author_lenses ?? [];
  const evidenceChunks =
    queryResult?.evidence_chunks ?? companyResult?.evidence_pack ?? [];
  const canSubmit =
    mode === "company_context"
      ? Boolean(company.trim() && query.trim())
      : Boolean(query.trim());

  async function handleSubmit() {
    if (!canSubmit) return;

    setError(null);
    setQueryResult(null);
    setCompanyResult(null);
    setLoading(true);

    try {
      if (mode === "company_context") {
        const result = await api.ragCompanyContext({
          company: company.trim(),
          question: query.trim(),
          top_k: 8,
        });
        setCompanyResult(result);
      } else if (mode === "ask") {
        const result = await api.ragQuery({
          query: query.trim(),
          top_k: 8,
          author_id: authorFilter || undefined,
        });
        setQueryResult(result);
      } else {
        const result = await api.ragRetrieve({
          query: query.trim(),
          top_k: 8,
          author_id: authorFilter || undefined,
        });
        setQueryResult(result);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  function handleModeChange(nextMode: Mode) {
    setMode(nextMode);
    setError(null);
    setQueryResult(null);
    setCompanyResult(null);
  }

  function fillExample(nextMode: Mode) {
    const nextConfig = MODE_CONFIG[nextMode];
    setMode(nextMode);
    setQuery(nextConfig.exampleQuery);
    setError(null);
    setQueryResult(null);
    setCompanyResult(null);
    if (nextMode === "company_context") {
      setCompany(nextConfig.exampleCompany ?? "");
      setAuthorFilter("");
    } else {
      setCompany("");
    }
  }

  return (
    <PageShell
      title="AI Sage"
      subtitle="Corpus-backed investment research with clearer workflows, not a debug form."
      headerActions={
        <>
          <button className="btn" type="button" onClick={() => setShowGuide((value) => !value)}>
            {showGuide ? "Hide Explain" : "Explain"}
          </button>
          <span className="pill">RAG Research</span>
          <span className="pill">Evidence First</span>
        </>
      }
    >
      <div className="wrap aiSagePage">
        {showGuide && (
          <section className="aiSageGuideGrid" aria-label="How to use AI Sage">
            <div className="card aiSageGuideCard">
              <div className="cardTitle">How To Use AI Sage</div>
              <div className="aiSageGuideText">
                <p>
                  AI Sage has three research modes. Pick the mode based on whether you want
                  an answer, raw evidence, or a company analysis setup.
                </p>
                <p>
                  The `Explain` button only shows or hides this guide. It does not call the
                  model or change your results.
                </p>
              </div>
            </div>
            {(["ask", "retrieve", "company_context"] as Mode[]).map((entryMode) => {
              const entry = MODE_CONFIG[entryMode];
              const selected = mode === entryMode;
              return (
                <button
                  key={entryMode}
                  type="button"
                  className={`card aiSageModeCard${selected ? " aiSageModeCardActive" : ""}`}
                  onClick={() => fillExample(entryMode)}
                >
                  <div className="cardTitle">{entry.label}</div>
                  <div className="aiSageModeSummary">{entry.summary}</div>
                  <p className="muted aiSageModeBody">{entry.purpose}</p>
                  <span className="aiSageModeExample">
                    Example: {entryMode === "company_context" ? `${entry.exampleCompany} · ` : ""}
                    {entry.exampleQuery}
                  </span>
                </button>
              );
            })}
          </section>
        )}

        <section className="aiSageWorkGrid">
          <div className="card aiSageControlCard">
            <div className="cardTitle">Research Flow</div>

            <div className="aiSageSegmented" role="tablist" aria-label="AI Sage mode">
              {(["ask", "retrieve", "company_context"] as Mode[]).map((entryMode) => (
                <button
                  key={entryMode}
                  type="button"
                  className={mode === entryMode ? "btn aiSageSegmentActive" : "btn"}
                  onClick={() => handleModeChange(entryMode)}
                >
                  {MODE_CONFIG[entryMode].label}
                </button>
              ))}
            </div>

            <div className="aiSageModeIntro">
              <strong>{config.label}</strong>
              <span className="muted">{config.summary}</span>
            </div>

            {mode === "company_context" ? (
              <label className="aiSageField">
                <span className="aiSageLabel">Company</span>
                <input
                  className="formInput"
                  placeholder="Company name, for example Apple"
                  value={company}
                  onChange={(event) => setCompany(event.target.value)}
                />
              </label>
            ) : null}

            <label className="aiSageField">
              <span className="aiSageLabel">
                {mode === "company_context" ? "Question" : "Query"}
              </span>
              <textarea
                className="formInput aiSageTextarea"
                rows={4}
                placeholder={config.queryPlaceholder}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </label>

            {mode !== "company_context" ? (
              <label className="aiSageField">
                <span className="aiSageLabel">Author Filter</span>
                <input
                  className="formInput"
                  placeholder="Optional author id, for example warren_buffett"
                  value={authorFilter}
                  onChange={(event) => setAuthorFilter(event.target.value)}
                />
                <div className="aiSageTokenRow" aria-label="Author presets">
                  {AUTHOR_EXAMPLES.map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      className="btn aiSageTokenBtn"
                      onClick={() => setAuthorFilter(preset.value)}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </label>
            ) : null}

            <div className="aiSageActionRow">
              <button
                className="btn btnLarge aiSagePrimaryAction"
                type="button"
                onClick={() => void handleSubmit()}
                disabled={loading || !canSubmit}
              >
                {loading ? "Running..." : config.submitLabel}
              </button>
              <button
                className="btn"
                type="button"
                onClick={() => fillExample(mode)}
                disabled={loading}
              >
                Use Example
              </button>
            </div>

            {error ? <div className="aiSageError">{error}</div> : null}
          </div>

          <div className="card aiSageResultSummaryCard">
            <div className="cardTitle">What These Buttons Do</div>
            <div className="aiSageButtonGuide">
              <div className="aiSageButtonGuideRow">
                <strong>Explain</strong>
                <span className="muted">Shows or hides the usage guide for AI Sage.</span>
              </div>
              <div className="aiSageButtonGuideRow">
                <strong>Ask</strong>
                <span className="muted">Retrieves evidence, then writes a grounded answer using that evidence.</span>
              </div>
              <div className="aiSageButtonGuideRow">
                <strong>Retrieve</strong>
                <span className="muted">Returns the strongest matching passages without synthesis.</span>
              </div>
              <div className="aiSageButtonGuideRow">
                <strong>Company Context</strong>
                <span className="muted">Builds an evidence pack and author lens set for a company-specific question.</span>
              </div>
            </div>

            <div className="aiSageSummaryStrip">
              <div className="aiSageSummaryMetric">
                <span className="muted">Active Mode</span>
                <strong>{config.label}</strong>
              </div>
              <div className="aiSageSummaryMetric">
                <span className="muted">Result Scope</span>
                <strong>{resultSummary(mode, queryResult, companyResult)}</strong>
              </div>
              <div className="aiSageSummaryMetric">
                <span className="muted">Evidence Status</span>
                <strong>
                  {mode === "company_context"
                    ? companyResult
                      ? companyResult.evidence_sufficient
                        ? "Grounded"
                        : "No Evidence"
                      : "Not Run"
                    : queryResult
                      ? queryResult.evidence_sufficient
                        ? "Grounded"
                        : "No Evidence"
                      : "Not Run"}
                </strong>
              </div>
            </div>
          </div>
        </section>

        {(queryResult?.answer || queryResult?.missing_information) && (
          <section className="card aiSageAnswerCard">
            <div className="cardTitle">{config.resultTitle}</div>
            {queryResult?.answer ? (
              <p className="aiSageAnswerText">{queryResult.answer}</p>
            ) : (
              <p className="muted">{queryResult?.missing_information}</p>
            )}
            {queryResult?.missing_information && queryResult.answer ? (
              <p className="muted aiSageNote">Gap: {queryResult.missing_information}</p>
            ) : null}
          </section>
        )}

        {selectedAuthors.length > 0 && (
          <section className="card">
            <div className="cardTitle">Selected Authors</div>
            <div className="aiSageAuthorGrid">
              {selectedAuthors.map((author: RagSelectedAuthor) => (
                <article key={author.author_id} className="aiSageAuthorCard">
                  <div className="aiSageAuthorHeader">
                    <strong>{author.name}</strong>
                    <span className="muted">Score {author.score.toFixed(2)}</span>
                  </div>
                  <p className="muted aiSageAuthorMeta">
                    {(author.domains ?? []).join(" · ")}
                  </p>
                  {author.worldview ? (
                    <p className="aiSageAuthorWorldview">{author.worldview}</p>
                  ) : null}
                  {author.key_maxims?.length ? (
                    <div className="aiSageTokenRow">
                      {author.key_maxims.slice(0, 3).map((maxim) => (
                        <span key={maxim} className="aiSagePill">
                          {maxim}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {author.match_reason?.length ? (
                    <p className="muted aiSageAuthorReasons">{author.match_reason.join(" · ")}</p>
                  ) : null}
                </article>
              ))}
            </div>
          </section>
        )}

        {evidenceChunks.length > 0 && (
          <section className="card">
            <div className="cardTitle">Evidence Chunks</div>
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
          </section>
        )}

        {!loading && !error && (queryResult || companyResult) && evidenceChunks.length === 0 && (
          <div className="card placeholderCard">
            <div className="cardTitle">No Evidence Found</div>
            <p className="muted">
              This run did not find matching corpus material. Try a narrower author filter,
              a different company, or ingest more source material first.
            </p>
          </div>
        )}
      </div>
    </PageShell>
  );
}
