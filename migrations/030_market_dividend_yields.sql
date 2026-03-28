CREATE TABLE IF NOT EXISTS market_dividend_yields (
  id BIGSERIAL PRIMARY KEY,
  asset_id BIGINT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  as_of_date DATE NOT NULL,
  yield_rate NUMERIC(20, 10) NOT NULL,
  annual_dividend_per_share NUMERIC(38, 18),
  price NUMERIC(38, 18),
  currency TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'yfinance_dividend',
  exchange_code TEXT,
  provider_symbol TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(asset_id, as_of_date, source)
);

CREATE INDEX IF NOT EXISTS idx_market_dividend_yields_asset_date
  ON market_dividend_yields(asset_id, as_of_date DESC);
