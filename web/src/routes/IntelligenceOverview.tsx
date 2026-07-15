import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import "../App.css";
import PageShell from "../components/PageShell";
import { api, type ResearchSummary } from "../lib/api";

function ingestionQueueValue(queue: ResearchSummary["ingestion_queue"]): string {
  if (queue.running_count > 0) return `${queue.running_count} running`;
  if (queue.queued_count > 0) return `${queue.queued_count} queued`;
  return "Idle";
}

export default function IntelligenceOverview() {
  const [summary, setSummary] = useState<ResearchSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadSummary = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await api.researchSummary();
        if (!cancelled) setSummary(response);
      } catch (err: unknown) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void loadSummary();
    return () => {
      cancelled = true;
    };
  }, []);

  const stats = [
    {
      key: "ai-sage",
      label: "AI Sage chats",
      value: loading ? "—" : String(summary?.ai_sage.chats_total ?? 0),
      meta: loading ? "" : `This month · ${summary?.ai_sage.chats_today ?? 0} today`,
    },
    {
      key: "author-corpus",
      label: "Author corpus",
      value: loading ? "—" : `${summary?.author_corpus.document_count ?? 0} docs`,
      meta: loading ? "" : `Across ${summary?.author_corpus.author_count ?? 0} authors`,
    },
    {
      key: "ingestion-queue",
      label: "Ingestion queue",
      value: loading || !summary ? "—" : ingestionQueueValue(summary.ingestion_queue),
      meta: loading
        ? ""
        : `${summary?.ingestion_queue.failed_count ?? 0} failed · last job ${summary?.ingestion_queue.last_job_at ?? "—"}`,
    },
    {
      key: "companies",
      label: "Companies tracked",
      value: "—",
      meta: "Structured dossiers coming soon",
    },
  ];

  const corpusRefreshedLabel = summary?.ingestion_queue.last_job_at
    ? `Corpus refreshed ${summary.ingestion_queue.last_job_at}`
    : null;

  return (
    <PageShell
      title="Research"
      subtitle="Move between AI guidance, author research, and future company workups from one section."
      headerActions={corpusRefreshedLabel ? <span className="researchPageMetaPill">{corpusRefreshedLabel}</span> : undefined}
    >
      <div className="dashboardWrap">
        {error ? <div className="card aiSageErrorState">{error}</div> : null}

        <section>
          <div className="grid researchStatGrid">
            {stats.map((stat) => (
              <article className="card researchStatCard" key={stat.key}>
                <p className="researchStatLabel">{stat.label}</p>
                <p className="researchStatValue">{stat.value}</p>
                <p className="muted researchStatMeta">{stat.meta}</p>
              </article>
            ))}
          </div>
        </section>

        <section>
          <div className="researchSectionHeader">
            <p className="researchSectionLabel">Sections</p>
            <h2 className="researchSectionHeading">Jump in</h2>
          </div>
          <div className="grid researchJumpGrid">
            <Link className="card researchJumpCard" to="/ai-sage">
              <p className="researchJumpEyebrow">AI Sage</p>
              <h3 className="researchJumpTitle">Query grounded business and investing context.</h3>
              <p className="muted researchJumpDescription">
                Ask questions across your corpus, then inspect ranked passages and linked evidence.
              </p>
              <span className="researchJumpCta">Open AI Sage →</span>
            </Link>

            <Link className="card researchJumpCard" to="/author-library">
              <p className="researchJumpEyebrow">Author Library</p>
              <h3 className="researchJumpTitle">Browse authors, documents, and curated passages.</h3>
              <p className="muted researchJumpDescription">
                Navigate the ingested corpus by author and collection, then hand off to the source.
              </p>
              <span className="researchJumpCta">Open Author Library →</span>
            </Link>

            <Link className="card researchJumpCard" to="/author-ingestion">
              <p className="researchJumpEyebrow">Author Ingestion</p>
              <h3 className="researchJumpTitle">Curate source discovery and ingestion for the library.</h3>
              <p className="muted researchJumpDescription">
                Add and validate sources, fan out logical documents, and monitor ingestion jobs.
              </p>
              <span className="researchJumpCta">Ingest author writings →</span>
            </Link>

            <div className="researchJumpCardDisabled researchJumpCard">
              <p className="researchJumpEyebrow">Companies</p>
              <h3 className="researchJumpTitle">Structured dossiers, coming soon.</h3>
              <p className="muted researchJumpDescription">
                The dedicated home for company snapshots and long-form research workflows.
              </p>
              <Link className="researchJumpCta" to="/companies">
                Preview →
              </Link>
            </div>
          </div>
        </section>
      </div>
    </PageShell>
  );
}
