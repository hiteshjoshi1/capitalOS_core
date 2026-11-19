// #449 (V23): several statements dropped at once. Each file is detected (POST /ingest/detect, nothing
// stored), routed to the one account it fits, and asks only when it can't tell; then all are uploaded
// one after another and each says what it changed.
import type { Account, UploadDetect, UploadRefusal } from "./api";
import { formatDate } from "./format";
import { uploadEffectLine, type UploadEffect } from "./uploadEffect";
import { dateFromFilename, todayLocalYYYYMMDD } from "../routes/ingestUtils";

export type BatchPhase = "detecting" | "ready" | "uploading" | "imported" | "needs_mapping" | "refused" | "failed";

export type BatchReport = {
  job_id?: number;
  status?: string;
  counts?: {
    transactions_inserted?: number;
    duplicates_skipped?: number;
    positions_parsed?: number;
    canonical_positions_written?: number;
  };
  effect?: UploadEffect | null;
  error_message?: string | null;
};

export type BatchRow = {
  key: string;
  file: File;
  asOf: string; // YYYY-MM-DD, used only when the file states no date of its own (#141)
  accountId: string; // "" until detected or picked
  detect: UploadDetect | null;
  phase: BatchPhase;
  report?: BatchReport;
  refusal?: UploadRefusal;
  error?: string;
};

export function newRow(file: File, index: number, today = todayLocalYYYYMMDD()): BatchRow {
  const named = dateFromFilename(file.name);
  return {
    key: `${index}-${file.name}-${file.size}`,
    file,
    asOf: named && named <= today ? named : today,
    accountId: "",
    detect: null,
    phase: "detecting",
  };
}

/** The detection result: pre-select the one account it fits; never override a pick. */
export function withDetect(row: BatchRow, d: UploadDetect | null, accounts: Account[]): BatchRow {
  const suggested = d?.suggested_account_id;
  const fits = suggested != null && accounts.some((a) => a.id === suggested && !a.closed_on);
  return { ...row, detect: d, phase: "ready", accountId: row.accountId || (fits ? String(suggested) : "") };
}

/** Rows that will go on "Upload all": ready (or failed, to retry) with an account. */
export function uploadable(rows: BatchRow[]): BatchRow[] {
  return rows.filter((r) => (r.phase === "ready" || r.phase === "failed") && r.accountId);
}

/** The phase an upload's report puts the row in. */
export function phaseOf(report: BatchReport): BatchPhase {
  if (report.status === "IMPORTED") return "imported";
  if (report.status === "NEEDS_MAPPING") return "needs_mapping";
  return "failed";
}

/** What the row says under the file name. */
export function rowNote(row: BatchRow, accounts: Account[]): string {
  const name = (id: string) => accounts.find((a) => String(a.id) === id)?.name ?? `account ${id}`;
  switch (row.phase) {
    case "detecting":
      return "Reading the file…";
    case "uploading":
      return `Uploading to ${name(row.accountId)}…`;
    case "imported": {
      const c = row.report?.counts ?? {};
      const what = (c.transactions_inserted ?? 0) > 0 || !(c.positions_parsed ?? 0)
        ? `${c.transactions_inserted ?? 0} transactions added`
        : `${c.canonical_positions_written ?? c.positions_parsed ?? 0} holdings saved`;
      const dupes = c.duplicates_skipped ? `, ${c.duplicates_skipped} already there` : "";
      const effect = row.report?.effect ? `. ${uploadEffectLine(row.report.effect)}` : "";
      return `Imported into ${name(row.accountId)}: ${what}${dupes}${effect}`;
    }
    case "needs_mapping":
      return "Uploaded, but the format isn't recognised: open it to say which statement it is.";
    case "refused":
      return `Not imported: ${row.refusal?.message ?? "refused"}`;
    case "failed":
      return `Failed: ${row.error ?? row.report?.error_message ?? "unknown error"}`;
    case "ready": {
      const d = row.detect;
      if (!d || !d.recognised) return row.accountId ? `Format not recognised: will try ${name(row.accountId)}.` : "Format not recognised: pick the account.";
      const what = d.file_label ?? "statement";
      if (row.accountId && d.candidate_account_ids.includes(Number(row.accountId))) return `${what} → ${name(row.accountId)}`;
      if (row.accountId) return `${what}: ${name(row.accountId)} (your pick)`;
      if (d.candidate_account_ids.length > 1) return `${what}: fits ${d.candidate_account_ids.map((id) => name(String(id))).join(" or ")}. Pick one.`;
      if (d.candidate_account_ids.length === 0) return `${what}: none of your open accounts fits it.`;
      return `${what}: pick the account.`;
    }
  }
}

/** "3 imported, 1 needs a format, 1 not imported" after the batch. */
export function batchSummary(rows: BatchRow[]): string {
  const n = (p: BatchPhase) => rows.filter((r) => r.phase === p).length;
  const parts = [
    n("imported") && `${n("imported")} imported`,
    n("needs_mapping") && `${n("needs_mapping")} with an unknown format`,
    n("refused") && `${n("refused")} not imported`,
    n("failed") && `${n("failed")} failed`,
    rows.filter((r) => r.phase === "ready").length && `${rows.filter((r) => r.phase === "ready").length} waiting for an account`,
  ].filter(Boolean);
  return parts.join(", ");
}

/** "Last upload 3 Nov" / "Last data 29 Aug" / "No data yet" for a checklist row: whichever is newer,
 *  so a source ticked by data dated this month doesn't show an older upload. */
export function checklistMeta(lastImport: string | null, lastData: string | null): string {
  if (lastData && (!lastImport || lastData > lastImport)) return `Last data ${formatDate(lastData)}`;
  if (lastImport) return `Last upload ${formatDate(lastImport)}`;
  return "No data yet";
}
