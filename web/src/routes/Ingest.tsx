import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import type { Account, ImportJobListItem } from "../lib/api";
import "../App.css";

type LoadState = "idle" | "loading" | "ready" | "error";

export default function Ingest() {
  const [state, setState] = useState<LoadState>("idle");
  const [err, setErr] = useState<string>("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [jobs, setJobs] = useState<ImportJobListItem[]>([]);
  const [accountId, setAccountId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState<boolean>(false);
  const [report, setReport] = useState<Record<string, unknown> | null>(null);
  const [registering, setRegistering] = useState<boolean>(false);
  const [loadingJob, setLoadingJob] = useState<number | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setState("loading");
        const [a, j] = await Promise.all([api.accounts(), api.ingestJobs()]);
        setAccounts(a);
        setJobs(j);
        setState("ready");
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        setErr(msg);
        setState("error");
      }
    })();
  }, []);

  async function onUpload() {
    if (!file || !accountId) return;
    setUploading(true);
    setErr("");
    try {
      const result = await api.ingestUpload(Number(accountId), file);
      setReport(result as Record<string, unknown>);
      const refreshed = await api.ingestJobs();
      setJobs(refreshed);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setErr(msg);
    } finally {
      setUploading(false);
    }
  }

  async function onRegisterSignature(jobId: number, parserKey: string) {
    setRegistering(true);
    setErr("");
    try {
      const result = await api.registerIngestSignature(jobId, parserKey);
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

  const reportData = report as {
    job_id?: number;
    status?: string;
    platform?: string;
    parser_key?: string | null;
    format_signature?: string;
    signature_debug?: Record<string, unknown> | null;
    counts?: {
      rows_total?: number;
      transactions_parsed?: number;
      transactions_inserted?: number;
      duplicates_skipped?: number;
    };
    validation_warnings?: string[];
    section_summary?: Array<{ section: string; rows: number }>;
    preview_transactions?: Array<Record<string, unknown>>;
    error_message?: string | null;
  } | null;

  return (
    <div className="wrap">
      <header className="header">
        <div className="titleBlock">
          <div className="title">CapitalOS — Ingest</div>
          <div className="subtitle">Upload a statement CSV. We will detect the format and show a report.</div>
        </div>
        <div className="pillRow">
          <Link className="pill" to="/">Dashboard</Link>
          <Link className="pill" to="/ingest">Ingest</Link>
          <Link className="pill" to="/crypto">Crypto</Link>
        </div>
      </header>

      {state === "loading" && <div className="card">Loading…</div>}

      {state === "error" && (
        <div className="card error">
          <div className="cardTitle">Load error</div>
          <pre className="pre">{err}</pre>
        </div>
      )}

      {state === "ready" && (
        <>
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
                <label className="field">
                  <span className="label">Statement file</span>
                  <input
                    className="input"
                    type="file"
                    accept=".csv,.xls,.xlsx"
                    onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                  />
                </label>
                <div className="actions">
                  <button className="btn" disabled={!file || !accountId || uploading} onClick={onUpload}>
                    {uploading ? "Uploading…" : "Upload CSV"}
                  </button>
                </div>
                {err && <div className="hint" role="alert">{err}</div>}
              </div>
            )}
          </div>

          {reportData && (
            <div className="card" style={{ marginTop: 14 }}>
              <div className="cardTitle">Import Report</div>
                <div className="formGrid">
                  <div className="muted">Job #{reportData.job_id ?? "—"} · Status: {reportData.status ?? "—"}</div>
                  <div className="muted">
                    Platform: {reportData.platform ?? "—"} · Parser: {reportData.parser_key ?? "—"}
                  </div>
                {reportData.status === "NEEDS_MAPPING" && (
                  <div className="mini">
                    <h3>Unknown format</h3>
                    <div className="muted">Signature: {reportData.format_signature ?? "—"}</div>
                    <div className="actions">
                      {reportData.platform === "IBKR" && (
                        <button
                          className="btn"
                          disabled={!reportData.job_id || registering}
                          onClick={() => onRegisterSignature(reportData.job_id ?? 0, "ibkr_activity_csv_v1")}
                        >
                          {registering ? "Registering…" : "Approve as IBKR"}
                        </button>
                      )}
                      {reportData.platform === "DBS" && (
                        <button
                          className="btn"
                          disabled={!reportData.job_id || registering}
                          onClick={() => onRegisterSignature(reportData.job_id ?? 0, "dbs_transaction_history_csv_v1")}
                        >
                          {registering ? "Registering…" : "Approve as DBS"}
                        </button>
                      )}
                      {reportData.platform === "SHAREKHAN" && (
                        <button
                          className="btn"
                          disabled={!reportData.job_id || registering}
                          onClick={() => onRegisterSignature(reportData.job_id ?? 0, "sharekhan_holdings_xls_v1")}
                        >
                          {registering ? "Registering…" : "Approve as Sharekhan"}
                        </button>
                      )}
                      {reportData.platform === "DBS_VICKERS" && (
                        <button
                          className="btn"
                          disabled={!reportData.job_id || registering}
                          onClick={() => onRegisterSignature(reportData.job_id ?? 0, "dbs_vickers_holdings_xls_v1")}
                        >
                          {registering ? "Registering…" : "Approve as DBS Vickers"}
                        </button>
                      )}
                    </div>
                  </div>
                )}
                {reportData.error_message && (
                  <div className="hint" role="alert">{reportData.error_message}</div>
                )}
                <div className="split">
                  <div className="mini">
                    <h3>Counts</h3>
                    <div className="muted">Rows total: {reportData.counts?.rows_total ?? 0}</div>
                    <div className="muted">Parsed: {reportData.counts?.transactions_parsed ?? 0}</div>
                    <div className="muted">Inserted: {reportData.counts?.transactions_inserted ?? 0}</div>
                    <div className="muted">Duplicates: {reportData.counts?.duplicates_skipped ?? 0}</div>
                  </div>
                  <div className="mini">
                    <h3>Sections</h3>
                    {reportData.section_summary?.length ? (
                      reportData.section_summary.map((s) => (
                        <div className="muted" key={s.section}>
                          {s.section}: {s.rows}
                        </div>
                      ))
                    ) : (
                      <div className="muted">No section summary.</div>
                    )}
                  </div>
                </div>
                <div className="mini">
                  <h3>Warnings</h3>
                  {reportData.validation_warnings?.length ? (
                    reportData.validation_warnings.map((w, i) => (
                      <div className="muted" key={`${w}-${i}`}>{w}</div>
                    ))
                  ) : (
                    <div className="muted">No warnings.</div>
                  )}
                </div>
                <div className="mini">
                  <h3>Preview (first 10)</h3>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>ts</th>
                        <th>type</th>
                        <th className="right">amount</th>
                        <th>currency</th>
                        <th>category</th>
                        <th>merchant</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reportData.preview_transactions?.length ? (
                        reportData.preview_transactions.map((t, idx) => (
                          <tr key={`tx-${idx}`}>
                            <td className="muted">{String(t.ts ?? "—")}</td>
                            <td>{String(t.type ?? "—")}</td>
                            <td className="right">{String(t.amount ?? "—")}</td>
                            <td>{String(t.currency ?? "—")}</td>
                            <td className="muted">{String(t.category ?? "—")}</td>
                            <td className="muted">{String(t.merchant_counterparty ?? "—")}</td>
                          </tr>
                        ))
                      ) : (
                        <tr>
                          <td className="muted" colSpan={6}>No preview available.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          <div className="card" style={{ marginTop: 14 }}>
            <div className="cardTitle">Recent Imports</div>
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Status</th>
                  <th>Platform</th>
                  <th>Account</th>
                  <th>File</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((j) => (
                  <tr
                    key={j.id}
                    onClick={() => onLoadJob(j.id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>{j.id}</td>
                    <td>{j.status}</td>
                    <td>{j.platform}</td>
                    <td>{j.account_id}</td>
                    <td>{j.original_filename}</td>
                    <td className="muted">{j.created_at ?? "—"}</td>
                    <td className="right muted">{loadingJob === j.id ? "Loading…" : "View report"}</td>
                  </tr>
                ))}
                {jobs.length === 0 && (
                  <tr>
                    <td className="muted" colSpan={7}>No import jobs yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
