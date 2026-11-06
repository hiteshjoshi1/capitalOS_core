import { useEffect, useState, type DragEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, UploadRefusedError } from "../lib/api";
import type { Account, ImportJobListItem, UploadRefusal } from "../lib/api";
import { loadApiResource } from "../lib/useApiResource";
import "../App.css";
import PageShell from "../components/PageShell";
import StatusPill from "../components/StatusPill";
import { dateFromFilename, describeAsOf, resolvePlatformParser, todayLocalYYYYMMDD } from "./ingestUtils";
import type { SignatureDebug } from "./ingestUtils";
import * as fmt from "../lib/format";
import { formatPlatformLabel } from "../lib/platformLabels";
import LoadError from "../components/LoadError";

type LoadState = "idle" | "loading" | "ready" | "error";

function jobStatusMeta(status?: string | null): { tone: "good" | "warn" | "neutral"; label: string } {
  if (status === "IMPORTED") return { tone: "good", label: "Completed" };
  if (status === "NEEDS_MAPPING") return { tone: "warn", label: "Needs mapping" };
  if (status === "REJECTED") return { tone: "warn", label: "Refused" };
  if (status === "REMOVED") return { tone: "neutral", label: "Removed" };
  return { tone: "neutral", label: status ?? "—" };
}

function formatPreviewAmount(amount: unknown, currency: unknown): string {
  const value = typeof amount === "number" ? amount : Number(amount);
  return fmt.formatSignedMoney(value, typeof currency === "string" ? currency : null, { decimals: 2 });
}

export default function Ingest() {
  const [searchParams] = useSearchParams();
  const requestedAccountId = searchParams.get("account_id") ?? "";
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [jobs, setJobs] = useState<ImportJobListItem[]>([]);
  const [accountId, setAccountId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  // The statement's date, used only when the file states none of its own (#141).
  const [asOf, setAsOf] = useState<string>(() => todayLocalYYYYMMDD());
  const [dragActive, setDragActive] = useState<boolean>(false);
  const [uploading, setUploading] = useState<boolean>(false);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [registering, setRegistering] = useState<boolean>(false);
  const [loadingJob, setLoadingJob] = useState<number | null>(null);
  // An upload refused before anything was written (#180); some can be sent anyway.
  const [refusal, setRefusal] = useState<UploadRefusal | null>(null);
  // "Remove this import": the job awaiting confirmation, the one being removed.
  const [confirmRemoveJob, setConfirmRemoveJob] = useState<number | null>(null);
  const [removingJob, setRemovingJob] = useState<number | null>(null);
  const [removeNotice, setRemoveNotice] = useState<string>("");

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [a, j] = await Promise.all([loadApiResource("accounts", () => api.accounts()), api.ingestJobs()]);
        setAccounts(a);
        setJobs(j);
        if (requestedAccountId && a.some((account) => String(account.id) === requestedAccountId)) {
          setAccountId(requestedAccountId);
        }
        setState("ready");
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setErr(msg);
        setState("error");
      }
    })();
  }, [requestedAccountId]);

  async function onUpload(allowAccountMismatch = false) {
    if (!file || !accountId) return;
    setUploading(true);
    setErr("");
    setRefusal(null);
    try {
      const result = allowAccountMismatch
        ? await api.ingestUpload(Number(accountId), file, asOf || undefined, { allowAccountMismatch: true })
        : await api.ingestUpload(Number(accountId), file, asOf || undefined);
      setReport(result as Record<string, unknown>);
      const refreshed = await api.ingestJobs();
      setJobs(refreshed);
    } catch (e: unknown) {
      if (e instanceof UploadRefusedError) {
        setRefusal(e.refusal);
        setReport(null);
        try {
          setJobs(await api.ingestJobs());
        } catch {
          // The refusal is what matters; the list refreshes on the next upload.
        }
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        setErr(msg);
      }
    } finally {
      setUploading(false);
    }
  }

  async function onRemoveJob(jobId: number) {
    setRemovingJob(jobId);
    setErr("");
    setRemoveNotice("");
    try {
      const result = await api.removeIngestJob(jobId);
      const r = result.removed;
      setRemoveNotice(
        `Import #${jobId} removed: ${r.transactions} transactions, ${r.balance_snapshots} balances and ` +
          `${r.position_snapshots} holdings deleted${r.restored_rows ? `, ${r.restored_rows} earlier rows put back` : ""}.`,
      );
      setConfirmRemoveJob(null);
      if (report && (report as { job_id?: number }).job_id === jobId) setReport(null);
      setJobs(await api.ingestJobs());
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setRemovingJob(null);
    }
  }

  async function onRegisterSignature(jobId: number, parserKey: string) {
    setRegistering(true);
    setErr("");
    try {
      const result = await api.registerIngestSignature(jobId, parserKey, asOf || undefined);
      setReport(result as Record<string, unknown>);
      const refreshed = await api.ingestJobs();
      setJobs(refreshed);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setRegistering(false);
    }
  }

  async function onLoadJob(jobId: number) {
    setLoadingJob(jobId);
    setErr("");
    try {
      const result = await api.ingestJob(jobId);
      setReport((result.report as Record<string, unknown>) ?? null);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setLoadingJob(null);
    }
  }

  // A date in the file name (e.g. 2026_10_02.xls) pre-fills the statement date; the
  // user sees it and can change it. Holdings exports often state no date inside.
  function chooseFile(next: File | null) {
    setFile(next);
    const named = dateFromFilename(next?.name);
    if (named && named <= todayLocalYYYYMMDD()) setAsOf(named);
  }

  function handleDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragActive(false);
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) chooseFile(dropped);
  }

  const reportData = report as {
    job_id?: number;
    status?: string;
    platform?: string;
    original_filename?: string;
    parser_key?: string | null;
    format_signature?: string;
    signature_debug?: Record<string, unknown> | null;
    counts?: {
      rows_total?: number;
      transactions_parsed?: number;
      transactions_inserted?: number;
      duplicates_skipped?: number;
      positions_parsed?: number;
      canonical_positions_written?: number;
    };
    validation_warnings?: string[];
    preview_transactions?: Array<Record<string, unknown>>;
    preview_positions?: Array<Record<string, unknown>>;
    error_message?: string | null;
    canonical_result?: {
      report_date?: string;
      as_of_date?: string;
      as_of_source?: string;
      as_of_note?: string;
    } | null;
  } | null;
  const platformParser = resolvePlatformParser(
    reportData?.platform,
    reportData?.signature_debug as SignatureDebug | undefined,
  );
  // Holdings-only parsers (Sharekhan, DBS Vickers, ...) always report 0
  // transactions by design — they extract a positions snapshot, not
  // transaction history. Fall back to position counts/preview so a
  // successful holdings import doesn't look identical to a failed one.
  const isPositionsImport = (reportData?.counts?.transactions_parsed ?? 0) === 0
    && (reportData?.counts?.positions_parsed ?? 0) > 0;
  const previewTransactionRows = reportData?.preview_transactions?.slice(0, 3) ?? [];
  const previewPositionRows = reportData?.preview_positions?.slice(0, 3) ?? [];
  const previewRows = previewTransactionRows.length ? previewTransactionRows : previewPositionRows;
  const showingPositionsPreview = !previewTransactionRows.length && previewPositionRows.length > 0;
  const canonical = reportData?.canonical_result ?? null;
  const asOfLabel = describeAsOf(canonical?.as_of_date ?? canonical?.report_date, canonical?.as_of_source);

  return (
    <PageShell
      title="Import Statements"
      subtitle="Upload a statement. We'll detect the format and show you what we found."
    >
      {state === "loading" && <div className="card" role="status">Loading…</div>}

      {state === "error" && (
        <LoadError title="Load error" error={err} />
      )}

      {state === "ready" && (
        <div className="wealthOverviewLayout">
          <div className="card">
            <div className="cardTitle">Upload Statement CSV</div>
            {accounts.length === 0 ? (
              <div className="muted">
                No accounts found. <Link to="/accounts/new">Create account</Link>
              </div>
            ) : (
              <div className="formGrid">
                <label className="field">
                  <span className="label">Account</span>
                  <select
                    className="input"
                    value={accountId}
                    onChange={(e) => setAccountId(e.target.value)}
                  >
                    <option value="" disabled>
                      Select account
                    </option>
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.currency})
                      </option>
                    ))}
                  </select>
                </label>
                <label
                  className={`ingestDropzone${dragActive ? " ingestDropzoneActive" : ""}`}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragActive(true);
                  }}
                  onDragLeave={() => setDragActive(false)}
                  onDrop={handleDrop}
                >
                  <span className="label">Statement file</span>
                  <p className="ingestDropzoneTitle">
                    {file ? file.name : "Drag a statement here, or click to browse"}
                  </p>
                  <p className="ingestDropzoneHint">.csv · .xls · .xlsx</p>
                  <input
                    className="ingestDropzoneInput"
                    type="file"
                    accept=".csv,.xls,.xlsx"
                    aria-label="Statement file"
                    onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                <label className="field">
                  <span className="label">Statement date</span>
                  <input
                    className="input"
                    type="date"
                    aria-label="Statement date"
                    value={asOf}
                    max={todayLocalYYYYMMDD()}
                    onChange={(e) => setAsOf(e.target.value)}
                  />
                  <span className="hint">Used when the file doesn't state its own date. Taken from the file name when it has one.</span>
                </label>
                <div className="actions">
                  <button className="btn" disabled={!file || !accountId || uploading} onClick={() => onUpload()}>
                    {uploading ? "Uploading…" : "Upload statement"}
                  </button>
                </div>
                {refusal && (
                  <div className="mini" role="alert" aria-label="Upload refused">
                    <h3>Not imported</h3>
                    <div>{refusal.message}</div>
                    {refusal.suggested_account_id != null &&
                      accounts.some((a) => a.id === refusal.suggested_account_id) && (
                        <div className="actions">
                          <button
                            className="btn"
                            onClick={() => {
                              setAccountId(String(refusal.suggested_account_id));
                              setRefusal(null);
                            }}
                          >
                            Select {accounts.find((a) => a.id === refusal.suggested_account_id)?.name}
                          </button>
                        </div>
                      )}
                    {refusal.override_field && (
                      <div className="actions">
                        <button className="btn" disabled={uploading} onClick={() => onUpload(true)}>
                          {uploading ? "Uploading…" : "Upload anyway"}
                        </button>
                      </div>
                    )}
                  </div>
                )}
                {err && <div className="hint" role="alert">{err}</div>}
              </div>
            )}
          </div>

          {reportData && (
            <section aria-label="Import report">
              <div className="coSectionHeader">
                <div>
                  <p className="coEyebrow">Import report · job #{reportData.job_id ?? "—"}</p>
                  <h2 className="coSectionTitle">
                    {reportData.platform ?? "—"} · {reportData.original_filename ?? "—"}
                  </h2>
                </div>
                <StatusPill {...jobStatusMeta(reportData.status)} />
              </div>
              <div className="card">
                <div className="ingestStatChips">
                  <StatusPill tone="neutral" label={`${reportData.counts?.rows_total ?? 0} rows`} />
                  {isPositionsImport ? (
                    <>
                      <StatusPill tone="neutral" label={`${reportData.counts?.positions_parsed ?? 0} holdings parsed`} />
                      <StatusPill tone="good" label={`${reportData.counts?.canonical_positions_written ?? 0} saved`} />
                    </>
                  ) : (
                    <>
                      <StatusPill tone="neutral" label={`${reportData.counts?.transactions_parsed ?? 0} parsed`} />
                      <StatusPill tone="good" label={`${reportData.counts?.transactions_inserted ?? 0} inserted`} />
                    </>
                  )}
                  <StatusPill tone="warn" label={`${reportData.counts?.duplicates_skipped ?? 0} duplicates skipped`} />
                  {asOfLabel && <StatusPill tone="neutral" label={asOfLabel} />}
                </div>
                {canonical?.as_of_note && <div className="hint">{canonical.as_of_note}</div>}

                {reportData.validation_warnings && reportData.validation_warnings.length > 0 && (
                  <div className="ingestWarningStack">
                    {reportData.validation_warnings.map((w, i) => (
                      <div className="successBannerDot ingestWarningBanner" key={`${w}-${i}`}>
                        <span className="ingestWarningDotIcon" aria-hidden="true" />
                        <span>{w}</span>
                      </div>
                    ))}
                  </div>
                )}

                {reportData.status === "NEEDS_MAPPING" && (
                  <div className="mini">
                    <h3>Unknown format</h3>
                    <div className="muted">Signature: {reportData.format_signature ?? "—"}</div>
                    <div className="actions">
                      {platformParser && (
                        <button
                          className="btn"
                          disabled={!reportData.job_id || registering}
                          onClick={() => onRegisterSignature(reportData.job_id ?? 0, platformParser.parserKey)}
                        >
                          {registering ? "Registering…" : platformParser.label}
                        </button>
                      )}
                    </div>
                  </div>
                )}
                {reportData.error_message && (
                  <div className="hint" role="alert">{reportData.error_message}</div>
                )}

                <div className="ingestPreview">
                  <p className="ingestPreviewTitle">
                    Preview — first 3 {showingPositionsPreview ? "holdings" : "rows"}
                  </p>
                  {previewRows.length ? (
                    showingPositionsPreview ? (
                      previewRows.map((p, idx) => (
                        <div className="listRow" key={`pos-${idx}`}>
                          <strong className="ingestPreviewMerchant">{String(p.symbol ?? "—")}</strong>
                          <span className="tag">{String(p.quantity ?? "—")} units</span>
                          <strong className="ingestPreviewAmount">{formatPreviewAmount(p.market_value, "")}</strong>
                        </div>
                      ))
                    ) : (
                      previewRows.map((t, idx) => (
                        <div className="listRow" key={`tx-${idx}`}>
                          <span className="ingestPreviewDate">{fmt.formatDate(t.ts as string | null)}</span>
                          <strong className="ingestPreviewMerchant">{String(t.merchant_counterparty ?? "—")}</strong>
                          <span className="tag">{String(t.category ?? "—")}</span>
                          <strong className="ingestPreviewAmount">{formatPreviewAmount(t.amount, t.currency)}</strong>
                        </div>
                      ))
                    )
                  ) : (
                    <p className="muted">No preview available.</p>
                  )}
                </div>
              </div>
            </section>
          )}

          <section aria-label="Recent imports">
            <div className="coSectionHeader">
              <div>
                <p className="coEyebrow">HISTORY</p>
                <h2 className="coSectionTitle">Recent Imports</h2>
              </div>
            </div>
            <div className="card">
              {removeNotice && <div className="hint" role="status">{removeNotice}</div>}
              {jobs.length === 0 ? (
                <p className="muted">No import jobs yet.</p>
              ) : (
                jobs.map((j) => (
                  <div
                    className="listRow ingestJobRow"
                    key={j.id}
                    role="row"
                    aria-label={`${j.id}`}
                    onClick={() => onLoadJob(j.id)}
                  >
                    <div className="listRowMain">
                      <div className="listRowTitle">{j.original_filename}</div>
                      <div className="listRowMeta">
                        {formatPlatformLabel(j.platform)} · Account {j.account_id} · {fmt.formatDate(j.created_at)}
                      </div>
                    </div>
                    <StatusPill
                      tone={jobStatusMeta(j.status).tone}
                      label={loadingJob === j.id ? "Loading…" : jobStatusMeta(j.status).label}
                    />
                    {j.removable && (
                      <div className="actions" onClick={(e) => e.stopPropagation()}>
                        {confirmRemoveJob === j.id ? (
                          <>
                            <span className="hint">Delete everything this import wrote?</span>
                            <button
                              className="btn btnSmall btnDanger"
                              disabled={removingJob === j.id}
                              onClick={() => onRemoveJob(j.id)}
                            >
                              {removingJob === j.id ? "Removing…" : "Yes, remove"}
                            </button>
                            <button className="btn btnSmall" onClick={() => setConfirmRemoveJob(null)}>
                              Cancel
                            </button>
                          </>
                        ) : (
                          <button
                            className="btn btnSmall"
                            aria-label={`Remove import ${j.id}`}
                            onClick={() => setConfirmRemoveJob(j.id)}
                          >
                            Remove this import
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </section>
        </div>
      )}
    </PageShell>
  );
}
