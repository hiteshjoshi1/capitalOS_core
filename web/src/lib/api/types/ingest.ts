// Uploads and import jobs: response and request types (split out of lib/api.ts, #368).

export type ImportJobListItem = {
  id: number;
  status: string;
  platform: string;
  account_id: number;
  original_filename: string;
  created_at: string | null;
  // #180: why it was refused or failed, when it was removed, and whether
  // "Remove this import" can undo it.
  error_message?: string | null;
  removed_at?: string | null;
  removable?: boolean;
};

// Why an upload was refused before anything was written (409 detail, #180).
export type UploadRefusal = {
  code: "account_type_mismatch" | "statement_account_mismatch" | string;
  message: string;
  job_id?: number | null;
  parser_key?: string | null;
  account_type?: string | null;
  expected_account_types?: string[];
  statement_last4?: string;
  linked_last4?: string;
  suggested_account_id?: number | null;
  // Present when the refusal can be overridden ("upload anyway").
  override_field?: string;
};

export type ImportJobRemoval = {
  job_id: number;
  status: "REMOVED";
  account_id: number;
  removed: {
    transactions: number;
    balance_snapshots: number;
    position_snapshots: number;
    restored_rows: number;
  };
  history_dirty_from: string | null;
};

export type ImportJobDetail = {
  job: {
    id: number;
    status: string;
    platform: string;
    account_id: number;
    original_filename: string;
    // stored_path (a server file path) was removed in #361 (D-99).
    file_sha256: string | null;
    format_signature: string | null;
    parser_key: string | null;
    error_message: string | null;
    created_at: string | null;
    updated_at: string | null;
  };
  report: Record<string, unknown> | string | null;
};

/** POST /ingest/detect (#399, U27): what a statement file is and which account it fits;
 *  nothing is stored. `suggested_account_id` only when exactly one open account fits (or the
 *  statement's number is linked to one). */
export type UploadDetect = {
  recognised: boolean;
  parser_key: string | null;
  file_label: string | null;
  account_types: string[];
  candidate_account_ids: number[];
  suggested_account_id: number | null;
  statement_last4: string | null;
};

/** GET /ingest/checklist (#449, V23): this calendar month's statement uploads. A source is
 *  `done` once a statement for it was imported this month or it has data dated this month.
 *  Not-done sources first; Flex, wallets and feeds refresh themselves and aren't listed. */
export type UploadChecklistSource = {
  source_key: string;
  account_id: number;
  label: string;
  platform: string | null;
  kind: string;
  done: boolean;
  last_import_date: string | null; // YYYY-MM-DD
  last_data_date: string | null; // YYYY-MM-DD
  overdue: boolean;
};

export type UploadChecklist = {
  month: string; // YYYY-MM
  done: number;
  total: number;
  sources: UploadChecklistSource[];
};
