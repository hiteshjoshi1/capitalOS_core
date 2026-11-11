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
    report_path: string | null;
    error_message: string | null;
    created_at: string | null;
    updated_at: string | null;
  };
  report: Record<string, unknown> | string | null;
};
