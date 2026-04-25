import { useCallback, useEffect, useRef, useState } from "react";
import "../App.css";
import PageShell from "../components/PageShell";
import { api } from "../lib/api";
import { subscribeToRealtimeTopic } from "../lib/realtime";
import type {
  IngestUrlsBatchResult,
  RagAuthor,
  RagAuthorCreate,
  RagAuthorIngestionEventPayload,
  RagIngestionActivity,
  RagIngestionJobRecord,
  RagSourceRecord,
  RealtimeEventEnvelope,
  SelectiveIngestionOptions,
} from "../lib/api";

type AuthorMode = "select" | "create";
type RealtimeStatus = "connecting" | "connected" | "disconnected";

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  queued: "Queued",
  running: "Running",
  ingested: "Ingested",
  failed: "Failed",
  done: "Done",
  submitted: "Submitted",
  completed: "Completed",
};

const EVENT_LABELS: Record<string, string> = {
  batch_submitted: "Batch submitted",
  source_queued: "Source queued",
  source_running: "Source running",
  source_ingested: "Source ingested",
  source_failed: "Source failed",
  batch_completed: "Batch completed",
};

function statusBadgeClass(status: string): string {
  if (status === "ingested" || status === "done" || status === "completed") return "statusBadge statusBadgeDone";
  if (status === "failed") return "statusBadge statusBadgeFailed";
  if (status === "running") return "statusBadge statusBadgeRunning";
  return "statusBadge statusBadgePending";
}

function formatDatetime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function sortByCreatedAtDesc<T extends { created_at?: string | null }>(items: T[]): T[] {
  return [...items].sort((left, right) => {
    const leftTime = left.created_at ? new Date(left.created_at).getTime() : 0;
    const rightTime = right.created_at ? new Date(right.created_at).getTime() : 0;
    return rightTime - leftTime;
  });
}

function upsertById<T extends { id: string }>(items: T[], nextItem: T): T[] {
  const existingIndex = items.findIndex((item) => item.id === nextItem.id);
  if (existingIndex === -1) {
    return [nextItem, ...items];
  }
  return items.map((item) => (item.id === nextItem.id ? nextItem : item));
}

export default function AuthorIngestion() {
  const [authorMode, setAuthorMode] = useState<AuthorMode>("select");
  const [authors, setAuthors] = useState<RagAuthor[]>([]);
  const [authorsLoading, setAuthorsLoading] = useState(false);
  const [selectedAuthorId, setSelectedAuthorId] = useState<string>("");

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

  const [urls, setUrls] = useState<string[]>([""]);
  const [sourceType, setSourceType] = useState("html");
  const [ingestLoading, setIngestLoading] = useState(false);
  const [ingestResult, setIngestResult] = useState<IngestUrlsBatchResult | null>(null);
  const [ingestError, setIngestError] = useState<string | null>(null);

  // Selective ingestion controls (hidden by default behind advanced toggle)
  const [showSelectiveOptions, setShowSelectiveOptions] = useState(false);
  const [selStartAfter, setSelStartAfter] = useState("");
  const [selStopBefore, setSelStopBefore] = useState("");
  const [selIncludeHeadings, setSelIncludeHeadings] = useState("");
  const [selExcludeSections, setSelExcludeSections] = useState("");

  const [sources, setSources] = useState<RagSourceRecord[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [jobs, setJobs] = useState<RagIngestionJobRecord[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [events, setEvents] = useState<RealtimeEventEnvelope<RagAuthorIngestionEventPayload>[]>([]);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [retryingSourceId, setRetryingSourceId] = useState<string | null>(null);
  const [realtimeStatus, setRealtimeStatus] = useState<RealtimeStatus>("disconnected");

  const selectedAuthorIdRef = useRef<string>("");

  useEffect(() => {
    selectedAuthorIdRef.current = selectedAuthorId;
  }, [selectedAuthorId]);

  useEffect(() => {
    setAuthorsLoading(true);
    api
      .ragAuthors()
      .then((data) => setAuthors(data))
      .catch(() => {})
      .finally(() => setAuthorsLoading(false));
  }, []);

  useEffect(() => {
    const unsubscribe = subscribeToRealtimeTopic<RagAuthorIngestionEventPayload>("author-ingestion", {
      onStatusChange: setRealtimeStatus,
      onEvent: (event) => {
        const currentAuthorId = selectedAuthorIdRef.current;
        const eventAuthorId = event.payload.author?.id ?? event.author_id ?? null;
        if (!currentAuthorId || eventAuthorId !== currentAuthorId) {
          return;
        }
        if (event.payload.source) {
          setSources((prev) => upsertById(prev, event.payload.source as RagSourceRecord));
        }
        if (event.payload.job) {
          setJobs((prev) => sortByCreatedAtDesc(upsertById(prev, event.payload.job as RagIngestionJobRecord)));
        }
        setEvents((prev) => sortByCreatedAtDesc(upsertById(prev, event)).slice(0, 50));
      },
    });
    return () => {
      unsubscribe();
    };
  }, []);

  function applyActivity(activity: RagIngestionActivity) {
    setSources(activity.sources);
    setJobs(sortByCreatedAtDesc(activity.jobs));
    setEvents(sortByCreatedAtDesc(activity.events).slice(0, 50));
  }

  const loadActivity = useCallback(async (authorId: string) => {
    setActivityError(null);
    setSourcesLoading(true);
    setJobsLoading(true);
    try {
      const activity = await api.ragIngestionActivity(authorId, 100);
      applyActivity(activity);
    } catch (e: unknown) {
      setActivityError(e instanceof Error ? e.message : String(e));
    } finally {
      setSourcesLoading(false);
      setJobsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedAuthorId) {
      setSources([]);
      setJobs([]);
      setEvents([]);
      setActivityError(null);
      return;
    }
    void loadActivity(selectedAuthorId);
  }, [loadActivity, selectedAuthorId]);

  function realtimeStatusMessage(): string {
    if (realtimeStatus === "connected") return "Live updates connected.";
    if (realtimeStatus === "connecting") return "Connecting live updates…";
    return "Live updates unavailable. Showing the latest backend snapshot.";
  }

  function eventSummary(event: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>): string {
    const sourceUrl = event.payload.source?.url;
    if (sourceUrl) {
      return sourceUrl.length > 60 ? `${sourceUrl.slice(0, 60)}…` : sourceUrl;
    }
    const authorName = event.payload.author?.name;
    if (authorName) {
      return authorName;
    }
    const batchId = event.payload.batch?.id ?? event.batch_id ?? null;
    return batchId ? `Batch ${batchId.slice(0, 8)}…` : event.event_name;
  }

  function eventFailureReason(event: RealtimeEventEnvelope<RagAuthorIngestionEventPayload>): string {
    return event.payload.failure_reason ?? event.payload.job?.failure_category ?? event.payload.job?.error ?? "—";
  }

  async function refreshSelectedAuthorActivity() {
    if (!selectedAuthorId) return;
    await loadActivity(selectedAuthorId);
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

    // Build selective_ingestion only when the user has filled in at least one field
    let selectiveIngestion: SelectiveIngestionOptions | null = null;
    const hasSel =
      selStartAfter.trim() ||
      selStopBefore.trim() ||
      selIncludeHeadings.trim() ||
      selExcludeSections.trim();
    if (hasSel) {
      selectiveIngestion = {
        start_after: selStartAfter.trim() || null,
        stop_before: selStopBefore.trim() || null,
        include_headings: selIncludeHeadings
          ? selIncludeHeadings.split(",").map((h) => h.trim()).filter(Boolean)
          : [],
        exclude_sections: selExcludeSections
          ? selExcludeSections.split(",").map((s) => s.trim()).filter(Boolean)
          : [],
      };
    }

    try {
      const result = await api.ragIngestUrls(selectedAuthorId, {
        urls: validUrls,
        source_type: sourceType,
        selective_ingestion: selectiveIngestion,
      });
      setIngestResult(result);
      setUrls([""]);
      await refreshSelectedAuthorActivity();
    } catch (e: unknown) {
      setIngestError(e instanceof Error ? e.message : String(e));
    } finally {
      setIngestLoading(false);
    }
  }

  async function handleRetry(sourceId: string) {
    setRetryingSourceId(sourceId);
    setActivityError(null);
    try {
      await api.ragRetryIngestion(sourceId);
      await refreshSelectedAuthorActivity();
    } catch (e: unknown) {
      setActivityError(e instanceof Error ? e.message : String(e));
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
    setUrls((prev) => prev.map((url, itemIndex) => (itemIndex === index ? value : url)));
  }

  const selectedAuthor = authors.find((author) => author.id === selectedAuthorId) ?? null;

  return (
    <PageShell title="Author Ingestion">
      <div className="wrap">
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
                  {authors.map((author) => (
                    <option key={author.id} value={author.id}>
                      {author.name} ({author.id}){author.enabled ? "" : " [disabled]"}
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

        {selectedAuthorId && (
          <section className="card" aria-label="URL ingestion">
            <h2 className="cardTitle">
              Add URLs for <span className="highlight">{selectedAuthor?.name ?? selectedAuthorId}</span>
            </h2>
            <p className="muted">Enter one or more URLs. Ingestion runs in the background — one URL at a time.</p>

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

            <details
              open={showSelectiveOptions}
              onToggle={(e) => setShowSelectiveOptions((e.target as HTMLDetailsElement).open)}
              aria-label="Selective ingestion options"
            >
              <summary className="formLabel" style={{ cursor: "pointer", marginBottom: "8px" }}>
                Advanced: selective ingestion (optional)
              </summary>
              <p className="muted" style={{ marginBottom: "8px" }}>
                Limit which sections of the source are ingested. Matching is case-insensitive substring.
                Leave all fields empty to ingest the full source.
              </p>
              <div className="formRow">
                <label className="formLabel" htmlFor="selStartAfter">
                  Start after heading
                </label>
                <input
                  id="selStartAfter"
                  className="formInput"
                  type="text"
                  placeholder="e.g. Introduction"
                  value={selStartAfter}
                  onChange={(e) => setSelStartAfter(e.target.value)}
                />
                <span className="formHint">Begin ingesting after the first heading that contains this text.</span>
              </div>
              <div className="formRow">
                <label className="formLabel" htmlFor="selStopBefore">
                  Stop before heading
                </label>
                <input
                  id="selStopBefore"
                  className="formInput"
                  type="text"
                  placeholder="e.g. Appendix"
                  value={selStopBefore}
                  onChange={(e) => setSelStopBefore(e.target.value)}
                />
                <span className="formHint">Stop ingesting when a heading contains this text.</span>
              </div>
              <div className="formRow">
                <label className="formLabel" htmlFor="selIncludeHeadings">
                  Include headings only
                </label>
                <input
                  id="selIncludeHeadings"
                  className="formInput"
                  type="text"
                  placeholder="Portfolio, Risk (comma-separated)"
                  value={selIncludeHeadings}
                  onChange={(e) => setSelIncludeHeadings(e.target.value)}
                />
                <span className="formHint">Only include sections whose heading matches any of these (comma-separated).</span>
              </div>
              <div className="formRow">
                <label className="formLabel" htmlFor="selExcludeSections">
                  Exclude sections
                </label>
                <input
                  id="selExcludeSections"
                  className="formInput"
                  type="text"
                  placeholder="Notes, Disclaimer (comma-separated)"
                  value={selExcludeSections}
                  onChange={(e) => setSelExcludeSections(e.target.value)}
                />
                <span className="formHint">Remove sections whose heading matches any of these (comma-separated).</span>
              </div>
            </details>

            {ingestError && <div className="error formRow">{ingestError}</div>}
            {ingestResult && (
              <div className="successBanner formRow">
                ✓ Registered {ingestResult.registered} URL{ingestResult.registered === 1 ? "" : "s"}
                {ingestResult.requeued_existing ? `, re-queued ${ingestResult.requeued_existing} existing URL${ingestResult.requeued_existing === 1 ? "" : "s"}` : ""}
                {ingestResult.skipped_duplicate > 0 && `, skipped ${ingestResult.skipped_duplicate} already queued/running duplicate(s)`}.
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

        {selectedAuthorId && (
          <section className="card" aria-label="Source status">
            <div className="cardTitleRow">
              <h2 className="cardTitle">Sources</h2>
              <button type="button" className="btn" onClick={() => void refreshSelectedAuthorActivity()}>
                Refresh
              </button>
            </div>
            <p className="muted" style={{ marginBottom: "8px" }}>
              {realtimeStatusMessage()}
            </p>
            {activityError && <div className="error formRow">{activityError}</div>}
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

        {selectedAuthorId && (
          <section className="card" aria-label="Ingestion job status">
            <h2 className="cardTitle">Ingestion Jobs</h2>
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
                      const linkedSource = sources.find((source) => source.id === job.source_id);
                      return (
                        <tr key={job.id}>
                          <td className="muted monospace">{job.id.slice(0, 8)}…</td>
                          <td className="urlCell">
                            {linkedSource?.url ? (
                              <span title={linkedSource.url}>
                                {linkedSource.url.length > 40 ? `${linkedSource.url.slice(0, 40)}…` : linkedSource.url}
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
                            {job.failure_category ?? (job.error ? job.error.slice(0, 80) : "—")}
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

        {selectedAuthorId && (
          <section className="card" aria-label="Ingestion activity">
            <h2 className="cardTitle">Recent Activity</h2>
            {events.length === 0 ? (
              <div className="muted">No ingestion activity for this author yet.</div>
            ) : (
              <div className="tableWrap">
                <table className="dataTable">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Event</th>
                      <th>Item</th>
                      <th>Status</th>
                      <th>Failure Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((event) => (
                      <tr key={event.id}>
                        <td className="muted">{formatDatetime(event.created_at)}</td>
                        <td>{EVENT_LABELS[event.event_name] ?? event.event_name}</td>
                        <td className="urlCell">{eventSummary(event)}</td>
                        <td>
                          <span className={statusBadgeClass(event.status ?? "pending")}>
                            {STATUS_LABELS[event.status ?? "pending"] ?? event.status ?? "Pending"}
                          </span>
                        </td>
                        <td className="error">{eventFailureReason(event)}</td>
                      </tr>
                    ))}
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
