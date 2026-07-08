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
  RagFanoutPreview,
  RagIngestionActivity,
  RagIngestionConfigInput,
  RagIngestionJobRecord,
  RagLogicalDocumentConfigInput,
  RagSourceRecord,
  RealtimeEventEnvelope,
  SelectiveIngestionOptions,
} from "../lib/api";

type AuthorMode = "select" | "create";
type RealtimeStatus = "connecting" | "connected" | "disconnected";

type MetadataEntry = {
  id: string;
  key: string;
  value: string;
};

type FanoutDocumentDraft = {
  id: string;
  key: string;
  title: string;
  authorId: string;
  publishedAt: string;
  publicationYear: string;
  venue: string;
  collection: string;
  canonicalWorkId: string;
  canonicalStatus: string;
  dedupePriority: string;
  sourceSection: string;
  noteTaker: string;
  workType: string;
  parentKey: string;
  selectiveStartAfter: string;
  selectiveStopBefore: string;
  selectiveIncludeHeadings: string;
  selectiveExcludeSections: string;
  metadataEntries: MetadataEntry[];
  canonicalMetadataEntries: MetadataEntry[];
};

type LogicalDocumentOutcome = {
  key: string;
  status: string;
  title: string | null;
  authorId: string | null;
  sourceSection: string | null;
  parentKey: string | null;
  failureCategory: string | null;
  error: string | null;
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  queued: "Queued",
  running: "Running",
  ingested: "Ingested",
  failed: "Failed",
  done: "Done",
  submitted: "Submitted",
  completed: "Completed",
  created: "Created",
  rejected: "Rejected",
  skipped: "Skipped",
};

const EVENT_LABELS: Record<string, string> = {
  batch_submitted: "Batch submitted",
  source_queued: "Source queued",
  source_running: "Source running",
  source_ingested: "Source ingested",
  source_failed: "Source failed",
  batch_completed: "Batch completed",
};

let documentCounter = 0;
let metadataCounter = 0;

function nextId(prefix: string): string {
  if (prefix === "doc") {
    documentCounter += 1;
    return `${prefix}-${documentCounter}`;
  }
  metadataCounter += 1;
  return `${prefix}-${metadataCounter}`;
}

function createMetadataEntry(): MetadataEntry {
  return { id: nextId("meta"), key: "", value: "" };
}

function createFanoutDocumentDraft(index: number): FanoutDocumentDraft {
  return {
    id: nextId("doc"),
    key: `document-${index}`,
    title: "",
    authorId: "",
    publishedAt: "",
    publicationYear: "",
    venue: "",
    collection: "",
    canonicalWorkId: "",
    canonicalStatus: "",
    dedupePriority: "",
    sourceSection: "",
    noteTaker: "",
    workType: "",
    parentKey: "",
    selectiveStartAfter: "",
    selectiveStopBefore: "",
    selectiveIncludeHeadings: "",
    selectiveExcludeSections: "",
    metadataEntries: [createMetadataEntry()],
    canonicalMetadataEntries: [createMetadataEntry()],
  };
}

function statusBadgeClass(status: string): string {
  if (status === "ingested" || status === "done" || status === "completed" || status === "created") {
    return "statusBadge statusBadgeDone";
  }
  if (status === "failed" || status === "rejected") return "statusBadge statusBadgeFailed";
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

function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function entriesToRecord(entries: MetadataEntry[]): Record<string, string> {
  return entries.reduce<Record<string, string>>((acc, entry) => {
    const key = entry.key.trim();
    const value = entry.value.trim();
    if (key && value) {
      acc[key] = value;
    }
    return acc;
  }, {});
}

function toOptionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function buildFanoutDocumentConfig(document: FanoutDocumentDraft): RagLogicalDocumentConfigInput {
  const payload: RagLogicalDocumentConfigInput = {
    key: document.key.trim(),
    title: document.title.trim(),
  };
  if (document.authorId) payload.author_id = document.authorId;
  if (document.publishedAt) payload.published_at = document.publishedAt;
  payload.publication_year = toOptionalNumber(document.publicationYear);
  if (document.venue.trim()) payload.venue = document.venue.trim();
  if (document.collection.trim()) payload.collection = document.collection.trim();
  if (document.canonicalWorkId.trim()) payload.canonical_work_id = document.canonicalWorkId.trim();
  if (document.canonicalStatus.trim()) payload.canonical_status = document.canonicalStatus.trim();
  payload.dedupe_priority = toOptionalNumber(document.dedupePriority);
  if (document.sourceSection.trim()) payload.source_section = document.sourceSection.trim();
  if (document.noteTaker.trim()) payload.note_taker = document.noteTaker.trim();
  if (document.workType.trim()) payload.work_type = document.workType.trim();
  if (document.parentKey.trim()) payload.parent_key = document.parentKey.trim();

  const metadata = entriesToRecord(document.metadataEntries);
  if (Object.keys(metadata).length > 0) payload.metadata = metadata;

  const canonicalMetadata = entriesToRecord(document.canonicalMetadataEntries);
  if (Object.keys(canonicalMetadata).length > 0) payload.canonical_metadata = canonicalMetadata;

  const hasSelectiveOptions =
    document.selectiveStartAfter.trim() ||
    document.selectiveStopBefore.trim() ||
    document.selectiveIncludeHeadings.trim() ||
    document.selectiveExcludeSections.trim();
  if (hasSelectiveOptions) {
    payload.selective_ingestion = {
      start_after: document.selectiveStartAfter.trim() || null,
      stop_before: document.selectiveStopBefore.trim() || null,
      include_headings: splitCsv(document.selectiveIncludeHeadings),
      exclude_sections: splitCsv(document.selectiveExcludeSections),
    };
  }

  return payload;
}

function getLogicalDocumentOutcomes(job: RagIngestionJobRecord): LogicalDocumentOutcome[] {
  const rawDocuments = job.stats_json["documents"];
  if (!Array.isArray(rawDocuments)) return [];

  return rawDocuments
    .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
    .map((item) => ({
      key: typeof item.key === "string" ? item.key : "—",
      status: typeof item.status === "string" ? item.status : "pending",
      title: typeof item.title === "string" ? item.title : null,
      authorId: typeof item.author_id === "string" ? item.author_id : null,
      sourceSection: typeof item.source_section === "string" ? item.source_section : null,
      parentKey: typeof item.parent_key === "string" ? item.parent_key : null,
      failureCategory: typeof item.failure_category === "string" ? item.failure_category : null,
      error: typeof item.error === "string" ? item.error : null,
    }));
}

function logicalDocumentSummary(job: RagIngestionJobRecord): string {
  const outcomes = getLogicalDocumentOutcomes(job);
  if (!outcomes.length) return "—";
  const counts = outcomes.reduce<Record<string, number>>((acc, outcome) => {
    acc[outcome.status] = (acc[outcome.status] ?? 0) + 1;
    return acc;
  }, {});
  return Object.entries(counts)
    .map(([status, count]) => `${count} ${STATUS_LABELS[status] ?? status}`)
    .join(" / ");
}

function previewMetadataSummary(preview: RagFanoutPreview["documents"][number]): string {
  const keys = Object.keys(preview.metadata);
  if (!keys.length) return "—";
  return keys.join(", ");
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

  const [showSelectiveOptions, setShowSelectiveOptions] = useState(false);
  const [selStartAfter, setSelStartAfter] = useState("");
  const [selStopBefore, setSelStopBefore] = useState("");
  const [selIncludeHeadings, setSelIncludeHeadings] = useState("");
  const [selExcludeSections, setSelExcludeSections] = useState("");

  const [showFanoutEditor, setShowFanoutEditor] = useState(false);
  const [fanoutDocuments, setFanoutDocuments] = useState<FanoutDocumentDraft[]>([createFanoutDocumentDraft(1)]);
  const [fanoutPreview, setFanoutPreview] = useState<RagFanoutPreview | null>(null);
  const [fanoutPreviewLoading, setFanoutPreviewLoading] = useState(false);
  const [fanoutPreviewError, setFanoutPreviewError] = useState<string | null>(null);

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
      domains: newDomains ? splitCsv(newDomains) : [],
      expertise_tags: newTags ? splitCsv(newTags) : [],
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

  function buildSelectiveIngestion(): SelectiveIngestionOptions | null {
    const hasSel =
      selStartAfter.trim() ||
      selStopBefore.trim() ||
      selIncludeHeadings.trim() ||
      selExcludeSections.trim();
    if (!hasSel) return null;
    return {
      start_after: selStartAfter.trim() || null,
      stop_before: selStopBefore.trim() || null,
      include_headings: splitCsv(selIncludeHeadings),
      exclude_sections: splitCsv(selExcludeSections),
    };
  }

  function validateFanoutDocuments(): string | null {
    if (!showFanoutEditor) return null;
    if (!fanoutDocuments.length) {
      return "Add at least one logical document before previewing or submitting.";
    }
    for (const document of fanoutDocuments) {
      if (!document.key.trim() || !document.title.trim()) {
        return "Every logical document needs both a key and a title.";
      }
    }
    return null;
  }

  function buildFanoutConfig(): RagIngestionConfigInput | null {
    if (!showFanoutEditor) return null;
    return {
      mode: "fanout",
      documents: fanoutDocuments.map((document) => buildFanoutDocumentConfig(document)),
    };
  }

  async function handlePreviewFanout() {
    if (!selectedAuthorId) return;
    const validationError = validateFanoutDocuments();
    if (validationError) {
      setFanoutPreviewError(validationError);
      setFanoutPreview(null);
      return;
    }

    setFanoutPreviewError(null);
    setFanoutPreviewLoading(true);
    try {
      const preview = await api.ragPreviewFanout({
        author_id: selectedAuthorId,
        ingestion_config: buildFanoutConfig(),
      });
      setFanoutPreview(preview);
    } catch (e: unknown) {
      setFanoutPreview(null);
      setFanoutPreviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setFanoutPreviewLoading(false);
    }
  }

  async function handleIngestUrls() {
    if (!selectedAuthorId) return;
    const validUrls = urls.map((u) => u.trim()).filter(Boolean);
    if (!validUrls.length) {
      setIngestError("Add at least one URL before submitting.");
      return;
    }
    const fanoutValidationError = validateFanoutDocuments();
    if (fanoutValidationError) {
      setIngestError(fanoutValidationError);
      return;
    }

    setIngestError(null);
    setIngestResult(null);
    setIngestLoading(true);

    try {
      const result = await api.ragIngestUrls(selectedAuthorId, {
        urls: validUrls,
        source_type: sourceType,
        selective_ingestion: buildSelectiveIngestion(),
        ingestion_config: buildFanoutConfig(),
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
    setUrls((prev) => prev.filter((_, itemIndex) => itemIndex !== index));
  }

  function updateUrl(index: number, value: string) {
    setUrls((prev) => prev.map((url, itemIndex) => (itemIndex === index ? value : url)));
  }

  function addFanoutDocument() {
    setFanoutDocuments((prev) => [...prev, createFanoutDocumentDraft(prev.length + 1)]);
  }

  function removeFanoutDocument(id: string) {
    setFanoutDocuments((prev) => prev.filter((document) => document.id !== id));
  }

  function updateFanoutDocument(id: string, updates: Partial<FanoutDocumentDraft>) {
    setFanoutDocuments((prev) =>
      prev.map((document) => (document.id === id ? { ...document, ...updates } : document)),
    );
  }

  function addMetadataRow(documentId: string, field: "metadataEntries" | "canonicalMetadataEntries") {
    setFanoutDocuments((prev) =>
      prev.map((document) =>
        document.id === documentId ? { ...document, [field]: [...document[field], createMetadataEntry()] } : document,
      ),
    );
  }

  function updateMetadataRow(
    documentId: string,
    field: "metadataEntries" | "canonicalMetadataEntries",
    entryId: string,
    updates: Partial<MetadataEntry>,
  ) {
    setFanoutDocuments((prev) =>
      prev.map((document) =>
        document.id === documentId
          ? {
              ...document,
              [field]: document[field].map((entry) => (entry.id === entryId ? { ...entry, ...updates } : entry)),
            }
          : document,
      ),
    );
  }

  function removeMetadataRow(
    documentId: string,
    field: "metadataEntries" | "canonicalMetadataEntries",
    entryId: string,
  ) {
    setFanoutDocuments((prev) =>
      prev.map((document) =>
        document.id === documentId
          ? {
              ...document,
              [field]:
                document[field].length === 1
                  ? [createMetadataEntry()]
                  : document[field].filter((entry) => entry.id !== entryId),
            }
          : document,
      ),
    );
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

            <div className="formRow" style={{ marginTop: "12px" }}>
              <label className="formLabel" htmlFor="fanoutToggle">
                <input
                  id="fanoutToggle"
                  type="checkbox"
                  checked={showFanoutEditor}
                  onChange={(e) => {
                    setShowFanoutEditor(e.target.checked);
                    setFanoutPreview(null);
                    setFanoutPreviewError(null);
                  }}
                  style={{ marginRight: "8px" }}
                />
                Compendium / logical-document fanout
              </label>
              <span className="formHint">
                Keep this off for the simple single-work flow. Turn it on to split one raw source into multiple logical documents.
              </span>
            </div>

            {showFanoutEditor && (
              <div className="formSection" aria-label="Fanout definition">
                <p className="muted" style={{ marginBottom: "12px" }}>
                  Define deterministic logical documents, author overrides, metadata, and optional parent-child links before ingestion.
                </p>

                {fanoutDocuments.map((document, index) => {
                  const otherDocuments = fanoutDocuments.filter((item) => item.id !== document.id);
                  return (
                    <div
                      key={document.id}
                      style={{
                        border: "1px solid var(--border-color, #2b3340)",
                        borderRadius: "12px",
                        padding: "16px",
                        marginBottom: "16px",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          gap: "12px",
                          marginBottom: "12px",
                        }}
                      >
                        <h3 style={{ margin: 0 }}>Logical document {index + 1}</h3>
                        {fanoutDocuments.length > 1 && (
                          <button
                            type="button"
                            className="btn btnDanger"
                            onClick={() => removeFanoutDocument(document.id)}
                          >
                            Remove
                          </button>
                        )}
                      </div>

                      <div className="formRow">
                        <label className="formLabel" htmlFor={`fanout-key-${document.id}`}>
                          Logical key <span className="required">*</span>
                        </label>
                        <input
                          id={`fanout-key-${document.id}`}
                          className="formInput"
                          type="text"
                          value={document.key}
                          onChange={(e) => updateFanoutDocument(document.id, { key: e.target.value })}
                        />
                      </div>
                      <div className="formRow">
                        <label className="formLabel" htmlFor={`fanout-title-${document.id}`}>
                          Title <span className="required">*</span>
                        </label>
                        <input
                          id={`fanout-title-${document.id}`}
                          className="formInput"
                          type="text"
                          value={document.title}
                          onChange={(e) => updateFanoutDocument(document.id, { title: e.target.value })}
                        />
                      </div>
                      <div className="formRow">
                        <label className="formLabel" htmlFor={`fanout-author-${document.id}`}>
                          Author override
                        </label>
                        <select
                          id={`fanout-author-${document.id}`}
                          className="formInput"
                          value={document.authorId}
                          onChange={(e) => updateFanoutDocument(document.id, { authorId: e.target.value })}
                        >
                          <option value="">Use selected author ({selectedAuthor?.name ?? selectedAuthorId})</option>
                          {authors.map((author) => (
                            <option key={author.id} value={author.id}>
                              {author.name} ({author.id})
                            </option>
                          ))}
                        </select>
                      </div>
                      <div
                        style={{
                          display: "grid",
                          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                          gap: "12px",
                        }}
                      >
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-published-${document.id}`}>
                            Publication date
                          </label>
                          <input
                            id={`fanout-published-${document.id}`}
                            className="formInput"
                            type="date"
                            value={document.publishedAt}
                            onChange={(e) => updateFanoutDocument(document.id, { publishedAt: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-year-${document.id}`}>
                            Publication year
                          </label>
                          <input
                            id={`fanout-year-${document.id}`}
                            className="formInput"
                            type="number"
                            value={document.publicationYear}
                            onChange={(e) => updateFanoutDocument(document.id, { publicationYear: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-venue-${document.id}`}>
                            Venue
                          </label>
                          <input
                            id={`fanout-venue-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.venue}
                            onChange={(e) => updateFanoutDocument(document.id, { venue: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-collection-${document.id}`}>
                            Collection
                          </label>
                          <input
                            id={`fanout-collection-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.collection}
                            onChange={(e) => updateFanoutDocument(document.id, { collection: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-canonical-id-${document.id}`}>
                            Canonical work ID
                          </label>
                          <input
                            id={`fanout-canonical-id-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.canonicalWorkId}
                            onChange={(e) => updateFanoutDocument(document.id, { canonicalWorkId: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-canonical-status-${document.id}`}>
                            Canonical status
                          </label>
                          <input
                            id={`fanout-canonical-status-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.canonicalStatus}
                            onChange={(e) => updateFanoutDocument(document.id, { canonicalStatus: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-dedupe-${document.id}`}>
                            Dedupe priority
                          </label>
                          <input
                            id={`fanout-dedupe-${document.id}`}
                            className="formInput"
                            type="number"
                            value={document.dedupePriority}
                            onChange={(e) => updateFanoutDocument(document.id, { dedupePriority: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-section-${document.id}`}>
                            Source section
                          </label>
                          <input
                            id={`fanout-section-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.sourceSection}
                            onChange={(e) => updateFanoutDocument(document.id, { sourceSection: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-note-taker-${document.id}`}>
                            Note taker
                          </label>
                          <input
                            id={`fanout-note-taker-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.noteTaker}
                            onChange={(e) => updateFanoutDocument(document.id, { noteTaker: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-work-type-${document.id}`}>
                            Work type
                          </label>
                          <input
                            id={`fanout-work-type-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.workType}
                            onChange={(e) => updateFanoutDocument(document.id, { workType: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-parent-${document.id}`}>
                            Parent logical document
                          </label>
                          <select
                            id={`fanout-parent-${document.id}`}
                            className="formInput"
                            value={document.parentKey}
                            onChange={(e) => updateFanoutDocument(document.id, { parentKey: e.target.value })}
                          >
                            <option value="">No parent</option>
                            {otherDocuments.map((item) => (
                              <option key={item.id} value={item.key}>
                                {item.title || item.key}
                              </option>
                            ))}
                          </select>
                        </div>
                      </div>

                      <details style={{ marginTop: "16px" }}>
                        <summary className="formLabel" style={{ cursor: "pointer" }}>
                          Selective extraction rules
                        </summary>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-start-after-${document.id}`}>
                            Start after heading
                          </label>
                          <input
                            id={`fanout-start-after-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.selectiveStartAfter}
                            onChange={(e) => updateFanoutDocument(document.id, { selectiveStartAfter: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-stop-before-${document.id}`}>
                            Stop before heading
                          </label>
                          <input
                            id={`fanout-stop-before-${document.id}`}
                            className="formInput"
                            type="text"
                            value={document.selectiveStopBefore}
                            onChange={(e) => updateFanoutDocument(document.id, { selectiveStopBefore: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-include-${document.id}`}>
                            Include headings only
                          </label>
                          <input
                            id={`fanout-include-${document.id}`}
                            className="formInput"
                            type="text"
                            placeholder="Essay A, Appendix"
                            value={document.selectiveIncludeHeadings}
                            onChange={(e) => updateFanoutDocument(document.id, { selectiveIncludeHeadings: e.target.value })}
                          />
                        </div>
                        <div className="formRow">
                          <label className="formLabel" htmlFor={`fanout-exclude-${document.id}`}>
                            Exclude sections
                          </label>
                          <input
                            id={`fanout-exclude-${document.id}`}
                            className="formInput"
                            type="text"
                            placeholder="Notes, Disclaimer"
                            value={document.selectiveExcludeSections}
                            onChange={(e) => updateFanoutDocument(document.id, { selectiveExcludeSections: e.target.value })}
                          />
                        </div>
                      </details>

                      <div style={{ marginTop: "16px" }}>
                        <div className="cardTitleRow" style={{ marginBottom: "8px" }}>
                          <h4 style={{ margin: 0 }}>Additional metadata</h4>
                          <button
                            type="button"
                            className="btn btnSmall"
                            onClick={() => addMetadataRow(document.id, "metadataEntries")}
                          >
                            Add metadata row
                          </button>
                        </div>
                        {document.metadataEntries.map((entry) => (
                          <div key={entry.id} className="urlInputRow">
                            <input
                              className="formInput"
                              type="text"
                              placeholder="key"
                              value={entry.key}
                              onChange={(e) =>
                                updateMetadataRow(document.id, "metadataEntries", entry.id, { key: e.target.value })
                              }
                            />
                            <input
                              className="formInput"
                              type="text"
                              placeholder="value"
                              value={entry.value}
                              onChange={(e) =>
                                updateMetadataRow(document.id, "metadataEntries", entry.id, { value: e.target.value })
                              }
                            />
                            <button
                              type="button"
                              className="btn btnDanger urlRemoveBtn"
                              aria-label={`Remove metadata row ${entry.id}`}
                              onClick={() => removeMetadataRow(document.id, "metadataEntries", entry.id)}
                            >
                              ✕
                            </button>
                          </div>
                        ))}
                      </div>

                      <div style={{ marginTop: "16px" }}>
                        <div className="cardTitleRow" style={{ marginBottom: "8px" }}>
                          <h4 style={{ margin: 0 }}>Canonical metadata</h4>
                          <button
                            type="button"
                            className="btn btnSmall"
                            onClick={() => addMetadataRow(document.id, "canonicalMetadataEntries")}
                          >
                            Add canonical row
                          </button>
                        </div>
                        {document.canonicalMetadataEntries.map((entry) => (
                          <div key={entry.id} className="urlInputRow">
                            <input
                              className="formInput"
                              type="text"
                              placeholder="key"
                              value={entry.key}
                              onChange={(e) =>
                                updateMetadataRow(document.id, "canonicalMetadataEntries", entry.id, { key: e.target.value })
                              }
                            />
                            <input
                              className="formInput"
                              type="text"
                              placeholder="value"
                              value={entry.value}
                              onChange={(e) =>
                                updateMetadataRow(document.id, "canonicalMetadataEntries", entry.id, { value: e.target.value })
                              }
                            />
                            <button
                              type="button"
                              className="btn btnDanger urlRemoveBtn"
                              aria-label={`Remove canonical metadata row ${entry.id}`}
                              onClick={() => removeMetadataRow(document.id, "canonicalMetadataEntries", entry.id)}
                            >
                              ✕
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}

                <div className="cardTitleRow">
                  <button type="button" className="btn" onClick={addFanoutDocument}>
                    + Add logical document
                  </button>
                  <button
                    type="button"
                    className="btn btnPrimary"
                    disabled={fanoutPreviewLoading}
                    onClick={() => void handlePreviewFanout()}
                  >
                    {fanoutPreviewLoading ? "Previewing..." : "Preview logical documents"}
                  </button>
                </div>

                {fanoutPreviewError && <div className="error formRow">{fanoutPreviewError}</div>}
                {fanoutPreview && (
                  <div className="tableWrap" aria-label="Fanout preview results" style={{ marginTop: "12px" }}>
                    <div className="successBanner formRow">
                      Preview ready. {fanoutPreview.document_count} logical document{fanoutPreview.document_count === 1 ? "" : "s"} will be created.
                    </div>
                    <table className="dataTable">
                      <thead>
                        <tr>
                          <th>Key</th>
                          <th>Title</th>
                          <th>Author</th>
                          <th>Parent</th>
                          <th>Section</th>
                          <th>Metadata</th>
                        </tr>
                      </thead>
                      <tbody>
                        {fanoutPreview.documents.map((document) => (
                          <tr key={document.key}>
                            <td className="muted monospace">{document.key}</td>
                            <td>{document.title ?? "—"}</td>
                            <td>{document.author_id ?? selectedAuthorId}</td>
                            <td>{document.parent_key ?? "—"}</td>
                            <td>{document.source_section ?? "—"}</td>
                            <td>{previewMetadataSummary(document)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {ingestError && <div className="error formRow">{ingestError}</div>}
            {ingestResult && (
              <div className="successBanner formRow">
                ✓ Registered {ingestResult.registered} URL{ingestResult.registered === 1 ? "" : "s"}
                {ingestResult.requeued_existing
                  ? `, re-queued ${ingestResult.requeued_existing} existing URL${ingestResult.requeued_existing === 1 ? "" : "s"}`
                  : ""}
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
                      <th>Fanout</th>
                      <th>Last Ingested</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sources.map((source) => {
                      const sourceMode =
                        typeof source.ingestion_config === "object" &&
                        source.ingestion_config !== null &&
                        "mode" in source.ingestion_config
                          ? String(source.ingestion_config.mode)
                          : "single_work";
                      return (
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
                          <td>{sourceMode === "fanout" ? "Compendium" : "Single work"}</td>
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
                      );
                    })}
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
                      <th>Logical docs</th>
                      <th>Started</th>
                      <th>Finished</th>
                      <th>Failure Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.map((job) => {
                      const linkedSource = sources.find((source) => source.id === job.source_id);
                      const outcomes = getLogicalDocumentOutcomes(job);
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
                          <td>
                            <div>{logicalDocumentSummary(job)}</div>
                            {outcomes.length > 0 && (
                              <details style={{ marginTop: "8px" }}>
                                <summary className="muted" style={{ cursor: "pointer" }}>
                                  View outcomes
                                </summary>
                                <div className="tableWrap" style={{ marginTop: "8px" }}>
                                <table className="dataTable">
                                  <thead>
                                    <tr>
                                      <th>Key</th>
                                      <th>Status</th>
                                      <th>Author</th>
                                      <th>Parent</th>
                                      <th>Reason</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {outcomes.map((outcome) => (
                                      <tr key={`${job.id}-${outcome.key}`}>
                                        <td className="muted monospace">{outcome.key}</td>
                                        <td>
                                          <span className={statusBadgeClass(outcome.status)}>
                                            {STATUS_LABELS[outcome.status] ?? outcome.status}
                                          </span>
                                        </td>
                                        <td>{outcome.authorId ?? "—"}</td>
                                        <td>{outcome.parentKey ?? "—"}</td>
                                        <td>{outcome.failureCategory ?? outcome.error ?? "—"}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                                </div>
                              </details>
                            )}
                          </td>
                          <td className="muted">{formatDatetime(job.started_at)}</td>
                          <td className="muted">{formatDatetime(job.finished_at)}</td>
                          <td className="error">{job.failure_category ?? (job.error ? job.error.slice(0, 80) : "—")}</td>
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
