// Data Hub: inbox, sources, reminders, alerts: response and request types (split out of lib/api.ts, #368).

export type DataHubActivityItem = {
  kind: string;
  title: string;
  meta: string;
  occurred_at: string;
};

export type DataHubJobScopeStatus = {
  scope: string;
  label?: string | null;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_run_trigger?: string | null;
  last_success_at?: string | null;
  data_as_of?: string | null;
  consecutive_failures: number;
  last_error?: string | null;
};

// One data source's job status from job_runs (#156).
export type DataHubJobState = "ok" | "warning" | "failing" | "never_run" | "not_configured";

export type DataHubJobStatus = {
  job: string;
  label: string;
  state: DataHubJobState | string;
  failure_threshold: number;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_success_at?: string | null;
  data_as_of?: string | null;
  consecutive_failures: number;
  last_error?: string | null;
  scopes: DataHubJobScopeStatus[];
};

// A held stock or fund with no live price (#222): not linked to an asset,
// no ticker on a configured exchange, or never quoted.
export type DataHubUnpricedHolding = {
  symbol?: string | null;
  name?: string | null;
  currency?: string | null;
  exchange_code?: string | null;
  platform?: string | null;
  reason: "no_asset" | "no_symbol" | "no_quote" | string;
};

// Source freshness (#252, D-67): one row per data source (/dashboard/source-freshness).
export type SourceFreshnessKind =
  | "ibkr_flex"
  | "broker_statement"
  | "bank_statement"
  | "card_statement"
  | "account_statement"
  | "crypto_wallet"
  | "market_data"
  | "fx";

export type SourceFreshnessCadence = "daily" | "weekdays" | "weekly" | "monthly" | "quarterly" | "off";

export type SourceFreshnessStatus = "on_time" | "overdue" | "never_loaded" | "no_schedule";

export type SourceFreshnessRow = {
  source_key: string;
  kind: SourceFreshnessKind | string;
  label: string;
  platform?: string | null;
  /** ISO date of the newest data, or null when the source has never loaded. */
  last_data_date?: string | null;
  cadence: SourceFreshnessCadence | string;
  /** Business days for "weekdays", calendar days otherwise. */
  grace_days: number;
  default_cadence: SourceFreshnessCadence | string;
  default_grace_days: number;
  overridden: boolean;
  /** The last day the newest data is on time. */
  due_date?: string | null;
  status: SourceFreshnessStatus | string;
  /** True for overdue and never-loaded sources. */
  overdue: boolean;
  days_overdue?: number | null;
};

export type SourceFreshness = {
  as_of: string;
  overdue_count: number;
  cadences: string[];
  sources: SourceFreshnessRow[];
};

/** The Data Hub inbox (#316): one item that needs the user, with its action. */
export type InboxAction = {
  label: string;
  /** A page to open, with `params` as its query string. */
  route: string | null;
  params: Record<string, string>;
  /** A refresh the page runs in place. */
  run: "refresh_prices" | "fx_backfill" | "refresh_ibkr" | "refresh_crypto" | null;
  /** Writes shared data (#152): only an admin gets the button. */
  admin_only: boolean;
};

export type InboxItem = {
  id: string;
  kind:
    | "source_overdue"
    | "source_never_loaded"
    | "unknown_format"
    | "import_pending"
    | "unpriced_holding"
    | "fx_gap"
    | "fx_unsupported"
    | "job_failing"
    | "unmapped_transactions"
    | "card_due_soon"
    | "card_overdue"
    | "backup_stale"
    // #410 (U29): about the money itself.
    | "month_closed_stale"
    | "concentration"
    | "unusual_move"
    | "recurring_new"
    | "recurring_up"
    | string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string | null;
  action: InboxAction | null;
  /** The source-freshness row, for the source kinds (prefilled Upload link, #278). */
  source: SourceFreshnessRow | null;
};

export type InboxResponse = {
  as_of: string;
  count: number;
  items: InboxItem[];
  all_good: string[];
  recent_activity: DataHubActivityItem[];
};

export type DataHubSummary = {
  linked_accounts: number;
  platform_count: number;
  currency_count: number;
  import_health: {
    pending_count: number;
    last_import_platform?: string | null;
    last_import_at?: string | null;
  };
  market_data: {
    fresh: number;
    stale: number;
    // Held stocks/funds the quote refresh can't price (#222).
    unpriced?: number;
    unpriced_holdings?: DataHubUnpricedHolding[];
  };
  connected_wallet_count: number;
  connected_wallet_labels: string[];
  recent_activity: DataHubActivityItem[];
  job_status: DataHubJobStatus[];
};

export type UploadReminder = {
  account_id: number;
  account_name: string;
  platform: string;
  account_type: string;
  last_upload_date: string | null;
  last_transaction_date: string | null;
  days_since_upload: number;
  message: string;
};

export type UploadReminderCount = {
  count: number;
};

export type UnifiedAlertsResponse = {
  upload_reminders: UploadReminder[];
  total_count: number;
};

/** GET /alerts/notifications/count (#149): /alerts/notifications' total_count only. */
export type UnifiedAlertsCount = {
  total_count: number;
};

/** GET /operations/backup-status (#399, U22, D-111). `available` false: no backup has reported
 *  here (a worktree or the test instance). Times are ISO 8601 with the Mac's offset. */
export type BackupStatus = {
  available: boolean;
  last_verified_at: string | null;
  age_hours: number | null;
  /** No verified backup in 48 hours, or the last daily run failed. */
  stale: boolean;
  /** Over 7 days, or the last run failed. */
  very_stale: boolean;
  next_run_at: string | null;
  daily_time: string | null;
  location: "icloud" | "local" | null;
  location_label: string | null;
  sets: number | null;
  encrypted: boolean | null;
  last_run_at: string | null;
  last_run_ok: boolean | null;
  status_written_at: string | null;
};

/** GET /settings/facts (#399, U24): read-only server settings the Settings page explains. */
export type SettingsFacts = {
  snapshot_day: number;
  upload_stale_days: number;
  base_currencies: string[];
};
