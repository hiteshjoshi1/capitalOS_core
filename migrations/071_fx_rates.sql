-- Local FX rate table (#139). Valuations read rates from here instead of
-- asking a provider on every request, so pages still load when the providers
-- are down, and a missing rate is reported instead of becoming 1.0.
--
-- One row = 1 `base` is worth `rate` units of `quote` on `rate_date`
-- (the providers' own convention: Frankfurter rows have base EUR, open.er-api
-- rows base USD). Readers derive any pair through a shared base, take the latest
-- row on or before the date they need, and report its source and age.
--
-- Filled daily by the market-data scheduler and on demand for dates a page asks
-- for. IBKR's statement rates stay in portfolio_fx_rates and are read alongside.
CREATE TABLE IF NOT EXISTS fx_rates (
  id BIGSERIAL PRIMARY KEY,
  rate_date DATE NOT NULL,
  base TEXT NOT NULL,
  quote TEXT NOT NULL,
  rate NUMERIC(38,18) NOT NULL CHECK (rate > 0),
  source TEXT NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT uq_fx_rates_date_base_quote UNIQUE (rate_date, base, quote)
);

CREATE INDEX IF NOT EXISTS idx_fx_rates_quote_date
  ON fx_rates (quote, rate_date);
