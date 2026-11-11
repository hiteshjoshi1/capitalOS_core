// Market data and FX: response and request types (split out of lib/api.ts, #368).

/** FX back-fill (#290): `GET /fx/backfill-plan` and `POST /fx/backfill` (admin). */
export type FxBackfillPlan = {
  span_start: string | null;
  span_end: string | null;
  currencies: string[];
  unsupported_currencies: string[];
  uncovered_days: number;
  planned_requests: Array<{ start: string; end: string }>;
  remaining_requests: number;
};

export type FxBackfillResult = FxBackfillPlan & {
  status: "completed" | "partial" | "failed" | "up_to_date" | "remote_disabled";
  fetched_requests: number;
  failed_requests: number;
  rows_stored: number;
};

export type MarketDataRun = {
  id: number;
  provider: string;
  exchange_code: string;
  trade_date: string;
  status: string;
  requested_symbols: number;
  received_rows: number;
  upserted_rows: number;
  missing_symbols: number;
  started_at?: string | null;
  finished_at?: string | null;
  error_summary?: string | null;
};

export type MarketDataSymbolDiagnostic = {
  asset_id: number;
  symbol: string;
  mapped_symbol: string;
  provider_symbol?: string | null;
  provider?: string | null;
  source?: string | null;
  currency?: string | null;
  latest_price?: number | null;
  latest_trade_date?: string | null;
  age_days?: number | null;
  freshness_status: string;
  refresh_status: string;
  failure_reason?: string | null;
  reason_code?: "RATE_LIMITED" | "NO_TRADE_REPORTED" | "PROVIDER_ERROR" | "INVALID_PRICE" | null;
  attempt_status?: string | null;
};

/** A held stock or fund the quote refresh can't price (#222, #320), with Yahoo tickers worth trying. */
export type MarketDataUnpricedItem = {
  instrument_id: number;
  asset_id: number | null;
  symbol: string | null;
  name: string | null;
  currency: string | null;
  exchange_code: string | null;
  platform: string | null;
  reason: "no_asset" | "no_symbol" | "no_quote" | string;
  suggested_yahoo_symbols: string[];
};

export type MarketDataUnpriced = {
  items: MarketDataUnpricedItem[];
  /** Admins only: the symbol map and prices are shared data (#152). */
  can_fix: boolean;
};

/** POST /market-data/ticker-test (#320). */
export type MarketDataTickerTest = {
  found: boolean;
  yahoo_symbol: string;
  close?: number | null;
  trade_date?: string | null;
  currency?: string | null;
  error?: string | null;
};

/** POST /market-data/ticker (#320): the saved override and the stored quote. */
export type MarketDataTickerSet = MarketDataTickerTest & {
  asset_id: number;
  exchange_code: string;
  action: "set" | "create_map" | "unchanged" | string;
};

export type MarketDataExchangeStatus = Partial<MarketDataRun> & {
  exchange_code: string;
  diagnostics_summary: {
    active_symbols: number;
    refreshed: number;
    failed: number;
    deferred: number;
    fresh: number;
    stale: number;
    missing: number;
  };
  symbols: MarketDataSymbolDiagnostic[];
};
