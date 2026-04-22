import { useEffect, useRef, useState } from "react";
import "../App.css";
import PageShell from "../components/PageShell";
import { api } from "../lib/api";
import type {
  IngestUrlsBatchResult,
  RagAuthor,
  RagAuthorCreate,
  RagIngestionJobRecord,
  RagSourceRecord,
} from "../lib/api";

type AuthorMode = "select" | "create";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  fetched: "Fetched",
  ingested: "Ingested",
  failed: "Failed",
  queued: "Queued",
  running: "Running",
  done: "Done",
};

const ACTIVE_JOB_STATUSES = new Set(["queued", "running", "pending"]);

function statusBadgeClass(status: string): string {
  if (status === "ingested" || status === "done") return "statusBadge statusBadgeDone";
  if (status === "failed") return "statusBadge statusBadgeFailed";
  if (status === "running" || status === "fetched") return "statusBadge statusBadgeRunning";
  return "statusBadge statusBadgePending";
}

function formatDatetime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function AuthorIngestion() {
  // Author selection/creation
  const [authorMode, setAuthorMode] = useState<AuthorMode>("select");
  const [authors, setAuthors] = useState<RagAuthor[]>([]);
  const [authorsLoading, setAuthorsLoading] = useState(false);
  const [selectedAuthorId, setSelectedAuthorId] = useState<string>("");

  // Create author form
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newEnabled, setNewEnabled] = useState(true);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [newDomains, setNewDomains] = useState("");
  const [newTags, setNewTags] = useState("");
  const [newWeight, setNewWeight] = useState("1.0");
  const [newRoleType, setNewRoleType] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [createLoading, setCreateLoading] = useState(false);

  // URL ingestion
  const [urls, setUrls] = useState<string[]>([""]);
  const [sourceType, setSourceType] = useState("html");
  const [ingestLoading, setIngestLoading] = useState(false);
  const [ingestResult, setIngestResult] = useState<IngestUrlsBatchResult | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);

  // Status views
  const [sources, setSources] = useState<RagSourceRecord[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [jobs, setJobs] = useState<RagIngestionJobRecord[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [retryingSourceId, setRetryingSourceId] = useState<string | null>(null);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Load author list on mount
  useEffect(() => {
    setAuthorsLoading(true);
    api
      .ragAuthors()
      .then((data) => setAuthors(data))
      .catch(() => {})
      .finally(() => setAuthorsLoading(false));
  }, []);

  // Load sources and jobs when author is selected
  useEffect(() => {
    if (!selectedAuthorId) {
      setSources([]);
      setJobs([]);
      return;
    }
    loadSourcesAndJobs(selectedAuthorId);
  }, [selectedAuthorId]);

  // Poll while active jobs exist
  useEffect(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    const hasActive = jobs.some((j) => ACTIVE_JOB_STATUSES.has(j.status));
    if (hasActive && selectedAuthorId) {
      pollIntervalRef.current = setInterval(() => {
        loadSourcesAndJobs(selectedAuthorId);
      }, 5000);
    }
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [jobs, selectedAuthorId]);

  function loadSourcesAndJobs(authorId: string) {
    setSourcesLoading(true);
    api
      .ragSources(authorId)
      .then((data) => setSources(data))
      .catch(() => {})
      .finally(() => setSourcesLoading(false));

    setJobsLoading(true);
    api
      .ragIngestionJobs({ author_id: authorId, limit: 100 })
      .then((data) => setJobs(data))
      .catch(() => {})
      .finally(() => setJobsLoading(false));
  }

  async function handleCreateAuthor() {
    setCreateError(null);
    if (!newId.trim() || !newName.trim()) {
      setCreateError("Author ID and Name are required.");
      return;
    }
    const payload: RagAuthorCreate = {
      id: newId.trim(),
      name: newName.trim(),
      enabled: newEnabled,
      domains: newDomains ? newDomains.split(",").map((d) => d.trim()).filter(Boolean) : [],
      expertise_tags: newTags ? newTags.split(",").map((t) => t.trim()).filter(Boolean) : [],
      overall_weight: parseFloat(newWeight) || 1.0,
      role_type: newRoleType.trim() || null,
    };
    setCreateLoading(true);
    try {
      const created = await api.ragCreateAuthor(payload);
      setAuthors((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedAuthorId(created.id);
      setAuthorMode("select");
      // Reset form
      setNewId("");
      setNewName("");
      setNewEnabled(true);
      setNewDomains("");
      setNewTags("");
      setNewWeight("1.0");
      setNewRoleType("");
      setShowAdvanced(false);
    } catch (e: unknown) {
      setCreateError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreateLoading(false);
    }
  }

  async function handleIngestUrls() {
    if (!selectedAuthorId) return;
    const validUrls = urls.map((u) => u.trim()).filter(Boolean);
    if (!validUrls.length) {
      setIngestError("Add at least one URL before submitting.");
      return;
    }
    setIngestError(null);
    setIngestResult(null);
    setIngestLoading(true);
    try {
      const result = await api.ragIngestUrls(selectedAuthorId, { urls: validUrls, source_type: sourceType });
      setIngestResult(result);
      setUrls([""]);
      // Refresh status tables
      loadSourcesAndJobs(selectedAuthorId);
    } catch (e: unknown) {
      setIngestError(e instanceof Error ? e.message : String(e));
    } finally {
      setIngestLoading(false);
    }
  }

  async function handleRetry(sourceId: string) {
    setRetryingSourceId(sourceId);
    try {
      await api.ragRetryIngestion(sourceId);
      if (selectedAuthorId) loadSourcesAndJobs(selectedAuthorId);
    } catch {
      // Errors are surfaced via job status table on next poll
    } finally {
      setRetryingSourceId(null);
    }
  }

  function addUrlRow() {
    setUrls((prev) => [...prev, ""]);
  }

  function removeUrlRow(index: number) {
    setUrls((prev) => prev.filter((_, i) => i !== index));
  }

  function updateUrl(index: number, value: string) {
    setUrls((prev) => prev.map((u, i) => (i === index ? value : u)));
  }

  const selectedAuthor = authors.find((a) => a.id === selectedAuthorId) ?? null;

  return (
    <PageShell title="Author Ingestion">
      <div className="wrap">
        {/* ── Author Selection / Creation ─────────────────────── */}
        <section className="card" aria-label="Author selection">
          <h2 className="cardTitle">Author</h2>
          <div className="formRow">
            <label className="formLabel">Mode</label>
            <div className="segmentedControl">
              <button
                type="button"
                className={`btn${authorMode === "select" ? " btnPrimary" : ""}`}
                onClick={() => setAuthorMode("select")}
              >
                Select Author
              </button>
              <button
                type="button"
                className={`btn${authorMode === "create" ? " btnPrimary" : ""}`}
                onClick={() => setAuthorMode("create")}
              >
                Create Author
              </button>
            </div>
          </div>

          {authorMode === "select" && (
            <div className="formRow">
              <label className="formLabel" htmlFor="authorSelect">
                Author
              </label>
              {authorsLoading ? (
                <span className="muted">Loading authors...</span>
              ) : (
                <select
                  id="authorSelect"
                  className="formInput"
                  value={selectedAuthorId}
                  onChange={(e) => setSelectedAuthorId(e.target.value)}
                >
                  <option value="">— Select an author —</option>
                  {authors.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({a.id}){a.enabled ? "" : " [disabled]"}
                    </option>
                  ))}
                </select>
              )}
            </div>
          )}

          {authorMode === "create" && (
            <div className="formSection" aria-label="Create new author">
              <p className="muted" style={{ marginBottom: "12px" }}>
                Required fields
              </p>
              <div className="formRow">
                <label className="formLabel" htmlFor="newAuthorId">
                  Author ID / Slug <span className="required">*</span>
                </label>
                <input
                  id="newAuthorId"
                  className="formInput"
                  type="text"
                  placeholder="e.g. warren_buffett"
                  value={newId}
                  onChange={(e) => setNewId(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ""))}
                />
                <span className="formHint">Lowercase letters, numbers, underscores, hyphens only.</span>
              </div>
              <div className="formRow">
                <label className="formLabel" htmlFor="newAuthorName">
                  Display Name <span className="required">*</span>
                </label>
                <input
                  id="newAuthorName"
                  className="formInput"
                  type="text"
                  placeholder="e.g. Warren Buffett"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
              </div>
              <div className="formRow">
                <label className="formLabel" htmlFor="newAuthorEnabled">
                  Enabled
                </label>
                <input
                  id="newAuthorEnabled"
                  type="checkbox"
                  checked={newEnabled}
                  onChange={(e) => setNewEnabled(e.target.checked)}
                />
              </div>

              <details open={showAdvanced} onToggle={(e) => setShowAdvanced((e.target as HTMLDetailsElement).open)}>
                <summary className="formLabel" style={{ cursor: "pointer", marginBottom: "8px" }}>
                  Advanced metadata (optional)
                </summary>
                <div className="formRow">
                  <label className="formLabel" htmlFor="newDomains">
                    Domains
                  </label>
                  <input
                    id="newDomains"
                    className="formInput"
                    type="text"
                    placeholder="investing, business (comma-separated)"
                    value={newDomains}
                    onChange={(e) => setNewDomains(e.target.value)}
                  />
                </div>
                <div className="formRow">
                  <label className="formLabel" htmlFor="newTags">
                    Expertise Tags
                  </label>
                  <input
                    id="newTags"
                    className="formInput"
                    type="text"
                    placeholder="value, moat (comma-separated)"
                    value={newTags}
                    onChange={(e) => setNewTags(e.target.value)}
                  />
                </div>
                <div className="formRow">
                  <label className="formLabel" htmlFor="newWeight">
                    Overall Weight
                  </label>
                  <input
                    id="newWeight"
                    className="formInput"
                    type="number"
                    min="0"
                    step="0.1"
                    value={newWeight}
                    onChange={(e) => setNewWeight(e.target.value)}
                  />
                </div>
                <div className="formRow">
                  <label className="formLabel" htmlFor="newRoleType">
                    Role Type
                  </label>
                  <input
                    id="newRoleType"
                    className="formInput"
                    type="text"
                    placeholder="investor, analyst, founder..."
                    value={newRoleType}
                    onChange={(e) => setNewRoleType(e.target.value)}
                  />
                </div>
              </details>

              {createError && <div className="error formRow">{createError}</div>}
              <div className="formRow">
                <button
                  type="button"
                  className="btn btnPrimary"
                  disabled={createLoading}
                  onClick={() => void handleCreateAuthor()}
                >
                  {createLoading ? "Creating..." : "Create Author"}
                </button>
              </div>
            </div>
          )}
        </section>

        {/* ── URL Entry (only when author is selected) ────────── */}
        {selectedAuthorId && (
          <section className="card" aria-label="URL ingestion">
            <h2 className="cardTitle">
              Add URLs for{" "}
              <span className="highlight">{selectedAuthor?.name ?? selectedAuthorId}</span>
            </h2>
            <p className="muted">
              Enter one or more URLs. Ingestion runs in the background — one URL at a time.
            </p>

            <div className="urlInputList">
              {urls.map((url, index) => (
                <div key={index} className="urlInputRow">
                  <input
                    className="formInput urlInput"
                    type="url"
                    placeholder="https://example.com/article"
                    value={url}
                    onChange={(e) => updateUrl(index, e.target.value)}
                    aria-label={`URL ${index + 1}`}
                  />
                  {urls.length > 1 && (
                    <button
                      type="button"
                      className="btn btnDanger urlRemoveBtn"
                      aria-label={`Remove URL ${index + 1}`}
                      onClick={() => removeUrlRow(index)}
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
              <button type="button" className="btn" onClick={addUrlRow} aria-label="Add another URL">
                + Add URL
              </button>
            </div>

            <div className="formRow" style={{ marginTop: "12px" }}>
              <label className="formLabel" htmlFor="sourceType">
                Source Type
              </label>
              <select
                id="sourceType"
                className="formInput"
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value)}
              >
                <option value="html">HTML</option>
                <option value="pdf">PDF</option>
                <option value="text">Plain Text</option>
              </select>
            </div>

            {ingestError && <div className="error formRow">{ingestError}</div>}
            {ingestResult && (
              <div className="successBanner formRow">
                ✓ Registered {ingestResult.registered} URLs
                {ingestResult.skipped_duplicate > 0 && `, skipped ${ingestResult.skipped_duplicate} duplicate(s)`}.
                {ingestResult.jobs_queued > 0 && ` ${ingestResult.jobs_queued} job(s) queued for background ingestion.`}
              </div>
            )}

            <div className="formRow">
              <button
                type="button"
                className="btn btnPrimary"
                disabled={ingestLoading}
                onClick={() => void handleIngestUrls()}
              >
                {ingestLoading ? "Submitting..." : "Submit & Start Ingestion"}
              </button>
            </div>
          </section>
        )}

        {/* ── Source Status ───────────────────────────────────── */}
        {selectedAuthorId && (
          <section className="card" aria-label="Source status">
            <div className="cardTitleRow">
              <h2 className="cardTitle">Sources</h2>
              <button
                type="button"
                className="btn"
                onClick={() => loadSourcesAndJobs(selectedAuthorId)}
              >
                Refresh
              </button>
            </div>
            {sourcesLoading ? (
              <div className="muted">Loading sources...</div>
            ) : sources.length === 0 ? (
              <div className="muted">No sources registered for this author yet.</div>
            ) : (
              <div className="tableWrap">
                <table className="dataTable">
                  <thead>
                    <tr>
                      <th>URL</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Last Ingested</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sources.map((source) => (
                      <tr key={source.id}>
                        <td className="urlCell">
                          {source.url ? (
                            <a href={source.url} target="_blank" rel="noopener noreferrer" className="urlLink">
                              {source.url.length > 60 ? `${source.url.slice(0, 60)}…` : source.url}
                            </a>
                          ) : (
                            <span className="muted">manual</span>
                          )}
                        </td>
                        <td>{source.source_type}</td>
                        <td>
                          <span className={statusBadgeClass(source.status)}>
                            {STATUS_LABELS[source.status] ?? source.status}
                          </span>
                        </td>
                        <td className="muted">{formatDatetime(source.last_ingested_at)}</td>
                        <td>
                          {source.status === "failed" && source.url && (
                            <button
                              type="button"
                              className="btn btnSmall"
                              disabled={retryingSourceId === source.id}
                              onClick={() => void handleRetry(source.id)}
                            >
                              {retryingSourceId === source.id ? "Retrying…" : "Retry"}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {/* ── Job Status ──────────────────────────────────────── */}
        {selectedAuthorId && (
          <section className="card" aria-label="Ingestion job status">
            <h2 className="cardTitle">Ingestion Jobs</h2>
            {jobs.some((j) => ACTIVE_JOB_STATUSES.has(j.status)) && (
              <p className="muted" style={{ marginBottom: "8px" }}>
                ⟳ Active jobs — auto-refreshing every 5 seconds.
              </p>
            )}
            {jobsLoading ? (
              <div className="muted">Loading jobs...</div>
            ) : jobs.length === 0 ? (
              <div className="muted">No ingestion jobs for this author yet.</div>
            ) : (
              <div className="tableWrap">
                <table className="dataTable">
                  <thead>
                    <tr>
                      <th>Job ID</th>
                      <th>Source</th>
                      <th>Status</th>
                      <th>Started</th>
                      <th>Finished</th>
                      <th>Failure Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => {
                      const linkedSource = sources.find((s) => s.id === job.source_id);
                      return (
                        <tr key={job.id}>
                          <td className="muted monospace">{job.id.slice(0, 8)}…</td>
                          <td className="urlCell">
                            {linkedSource?.url ? (
                              <span title={linkedSource.url}>
                                {linkedSource.url.length > 40
                                  ? `${linkedSource.url.slice(0, 40)}…`
                                  : linkedSource.url}
                              </span>
                            ) : (
                              <span className="muted">{job.source_id.slice(0, 8)}…</span>
                            )}
                          </td>
                          <td>
                            <span className={statusBadgeClass(job.status)}>
                              {STATUS_LABELS[job.status] ?? job.status}
                            </span>
                          </td>
                          <td className="muted">{formatDatetime(job.started_at)}</td>
                          <td className="muted">{formatDatetime(job.finished_at)}</td>
                          <td className="error">
                            {job.failure_category ?? (job.error ? job.error.slice(0, 80) : null)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}
      </div>
    </PageShell>
  );
}
