// #449 (V23): several statements at once. Each file is routed to the account its format fits
// (detection, nothing stored); a file it can't place asks for its account. "Upload all" sends
// them one after another and each row then says what it changed.
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, UploadRefusedError } from "../lib/api";
import type { Account } from "../lib/api";
import { batchSummary, newRow, phaseOf, rowNote, uploadable, withDetect, type BatchReport, type BatchRow } from "../lib/batchUpload";
import { groupAccounts } from "../lib/uploadAccount";
import { todayLocalYYYYMMDD } from "../routes/ingestUtils";
import StatusPill from "./StatusPill";

type Props = {
  files: File[];
  accounts: Account[];
  onUploaded: () => void; // refresh the jobs list and the checklist
  onClose: () => void;
};

const TONE: Record<BatchRow["phase"], "good" | "warn" | "neutral"> = {
  detecting: "neutral",
  ready: "neutral",
  uploading: "neutral",
  imported: "good",
  needs_mapping: "warn",
  refused: "warn",
  failed: "warn",
};
const LABEL: Record<BatchRow["phase"], string> = {
  detecting: "Reading",
  ready: "Ready",
  uploading: "Uploading",
  imported: "Imported",
  needs_mapping: "Unknown format",
  refused: "Not imported",
  failed: "Failed",
};

export default function BatchUpload({ files, accounts, onUploaded, onClose }: Props) {
  const [rows, setRows] = useState<BatchRow[]>(() => files.map((f, i) => newRow(f, i)));
  const [running, setRunning] = useState(false);
  // The rows and accounts as first rendered: detection runs once per batch (the parent remounts
  // this component with a new key for a new drop).
  const firstRows = useRef(rows);
  const firstAccounts = useRef(accounts);

  const update = (key: string, patch: (r: BatchRow) => BatchRow) =>
    setRows((current) => current.map((r) => (r.key === key ? patch(r) : r)));

  useEffect(() => {
    let live = true;
    for (const row of firstRows.current) {
      api.ingestDetect(row.file).then(
        (d) => live && update(row.key, (r) => withDetect(r, d, firstAccounts.current)),
        () => live && update(row.key, (r) => withDetect(r, null, firstAccounts.current)),
      );
    }
    return () => {
      live = false;
    };
  }, []);

  async function send(row: BatchRow, allowAccountMismatch = false) {
    update(row.key, (r) => ({ ...r, phase: "uploading", error: undefined, refusal: undefined }));
    try {
      const report = (allowAccountMismatch
        ? await api.ingestUpload(Number(row.accountId), row.file, row.asOf || undefined, { allowAccountMismatch: true })
        : await api.ingestUpload(Number(row.accountId), row.file, row.asOf || undefined)) as BatchReport;
      update(row.key, (r) => ({ ...r, report, phase: phaseOf(report) }));
    } catch (e: unknown) {
      if (e instanceof UploadRefusedError) {
        update(row.key, (r) => ({ ...r, phase: "refused", refusal: e.refusal }));
      } else {
        update(row.key, (r) => ({ ...r, phase: "failed", error: e instanceof Error ? e.message : String(e) }));
      }
    }
  }

  async function uploadAll() {
    setRunning(true);
    // One after another: imports of the same account must not race (the server locks per account).
    for (const row of uploadable(rows)) await send(row);
    setRunning(false);
    onUploaded();
  }

  async function uploadOne(row: BatchRow, allowAccountMismatch: boolean) {
    setRunning(true);
    await send(row, allowAccountMismatch);
    setRunning(false);
    onUploaded();
  }

  const pending = uploadable(rows);
  const detecting = rows.some((r) => r.phase === "detecting");
  const finished = rows.some((r) => ["imported", "needs_mapping", "refused", "failed"].includes(r.phase));
  const summary = finished ? batchSummary(rows) : "";

  return (
    <section className="card" aria-label="Upload several statements">
      <div className="cardTitle">{rows.length} statements</div>
      <p className="hint">Each file goes to the account its format fits. Pick one only where it asks.</p>
      <ul className="batchList">
        {rows.map((row) => {
          const editable = row.phase === "ready" || row.phase === "failed" || row.phase === "refused";
          return (
            <li className="batchRow" key={row.key} data-testid="batch-row">
              <div className="batchRowHead">
                <strong className="batchFile">{row.file.name}</strong>
                <StatusPill tone={TONE[row.phase]} label={LABEL[row.phase]} />
              </div>
              <p className="batchNote">{rowNote(row, accounts)}</p>
              {editable ? (
                <div className="batchControls">
                  <select
                    className="input"
                    aria-label={`Account for ${row.file.name}`}
                    value={row.accountId}
                    onChange={(e) => update(row.key, (r) => ({ ...r, accountId: e.target.value, phase: r.phase === "refused" ? "ready" : r.phase }))}
                  >
                    <option value="">Select account</option>
                    {groupAccounts(accounts)
                      .filter((g) => g.label !== "Closed")
                      .map((group) => (
                        <optgroup key={group.label} label={group.label}>
                          {group.accounts.map((a) => (
                            <option key={a.id} value={a.id}>
                              {a.name} ({a.currency})
                            </option>
                          ))}
                        </optgroup>
                      ))}
                  </select>
                  <input
                    className="input"
                    type="date"
                    aria-label={`Statement date for ${row.file.name}`}
                    value={row.asOf}
                    max={todayLocalYYYYMMDD()}
                    onChange={(e) => update(row.key, (r) => ({ ...r, asOf: e.target.value }))}
                  />
                </div>
              ) : null}
              {row.phase === "refused" && row.refusal?.override_field ? (
                <button className="btn btnSmall" disabled={running} onClick={() => uploadOne(row, true)}>
                  Upload anyway
                </button>
              ) : null}
              {row.phase === "needs_mapping" && row.report?.job_id ? (
                <Link className="btn btnSmall" to={`/ingest?job=${row.report.job_id}`}>
                  Open it
                </Link>
              ) : null}
            </li>
          );
        })}
      </ul>
      {summary ? (
        <p className="ingestEffect" role="status" data-testid="batch-summary">
          {summary}
        </p>
      ) : null}
      <div className="actions">
        <button className="btn" disabled={running || detecting || pending.length === 0} onClick={uploadAll}>
          {running ? "Uploading…" : `Upload ${pending.length === 1 ? "1 file" : `${pending.length} files`}`}
        </button>
        <button className="btn" disabled={running} onClick={onClose}>
          {finished ? "Done" : "Cancel"}
        </button>
      </div>
    </section>
  );
}
