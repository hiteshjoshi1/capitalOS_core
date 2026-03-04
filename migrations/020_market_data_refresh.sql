CREATE TABLE IF NOT EXISTS market_symbol_map (
  id BIGSERIAL PRIMARY KEY,
  asset_id BIGINT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  exchange_code TEXT NOT NULL,
  exchange_symbol TEXT NOT NULL,
  quote_currency TEXT NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  eodhd_symbol_override TEXT,
  yahoo_symbol_override TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(asset_id, exchange_code),
  UNIQUE(exchange_code, exchange_symbol)
);

CREATE INDEX IF NOT EXISTS idx_market_symbol_map_exchange_active
  ON market_symbol_map(exchange_code, is_active);

CREATE TABLE IF NOT EXISTS market_data_runs (
  id BIGSERIAL PRIMARY KEY,
  provider TEXT NOT NULL,
  exchange_code TEXT NOT NULL,
  trade_date DATE NOT NULL,
  status TEXT NOT NULL,
  requested_symbols INTEGER NOT NULL DEFAULT 0,
  received_rows INTEGER NOT NULL DEFAULT 0,
  upserted_rows INTEGER NOT NULL DEFAULT 0,
  missing_symbols INTEGER NOT NULL DEFAULT 0,
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at TIMESTAMPTZ,
  error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_market_data_runs_exchange_date
  ON market_data_runs(exchange_code, trade_date DESC);

CREATE TABLE IF NOT EXISTS market_data_run_items (
  id BIGSERIAL PRIMARY KEY,
  run_id BIGINT NOT NULL REFERENCES market_data_runs(id) ON DELETE CASCADE,
  asset_id BIGINT REFERENCES assets(id) ON DELETE SET NULL,
  provider TEXT NOT NULL,
  exchange_code TEXT NOT NULL,
  symbol TEXT NOT NULL,
  trade_date DATE NOT NULL,
  status TEXT NOT NULL,
  price NUMERIC(38, 18),
  currency TEXT,
  source_note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_data_run_items_run_id
  ON market_data_run_items(run_id);

CREATE INDEX IF NOT EXISTS idx_market_data_run_items_asset_date
  ON market_data_run_items(asset_id, trade_date DESC);

ALTER TABLE prices
  ADD COLUMN IF NOT EXISTS trade_date DATE,
  ADD COLUMN IF NOT EXISTS exchange_code TEXT,
  ADD COLUMN IF NOT EXISTS provider_symbol TEXT,
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'MANUAL';

CREATE UNIQUE INDEX IF NOT EXISTS uq_prices_asset_trade_date_source
  ON prices(asset_id, trade_date, source)
  WHERE trade_date IS NOT NULL;
