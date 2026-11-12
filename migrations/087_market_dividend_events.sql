-- Dividend calendar (#417, U17, D-117): per-share dividend events from the market-data provider
-- (Yahoo via yfinance), shared market data like market_dividend_yields (written only by the
-- market-data refresh, admin/scheduler).
--   kind 'history'   a past dividend: its ex-date and the amount per share actually paid. The
--                    calendar projects each holding's next dates from this rhythm.
--   kind 'announced' the next ex-date (and pay date when Yahoo has one) the provider lists ahead.
--                    Yahoo gives no amount for it; the calendar estimates it from history.
-- amount_per_share is in `currency` (the asset's quote currency). fetched_at says how fresh it is
-- and lets the refresh skip symbols fetched recently.
CREATE TABLE IF NOT EXISTS market_dividend_events (
  id BIGSERIAL PRIMARY KEY,
  asset_id BIGINT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('history', 'announced')),
  ex_date DATE NOT NULL,
  pay_date DATE,
  amount_per_share NUMERIC(38, 18),
  currency TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'yfinance',
  exchange_code TEXT,
  provider_symbol TEXT,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (asset_id, kind, ex_date)
);

CREATE INDEX IF NOT EXISTS idx_market_dividend_events_asset_date
  ON market_dividend_events (asset_id, ex_date DESC);
