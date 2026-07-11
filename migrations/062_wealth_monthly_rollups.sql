-- Migration 062: Wealth Timeline monthly rollup table (Phase 2).
-- Additive schema only. No data migration. No breaking changes.
--
-- wealth_monthly_rollups pre-aggregates one net-worth snapshot per
-- (user, month, base_currency), computed with the same anchor/canonical-read
-- semantics as the existing dashboard endpoints (see _networth_components,
-- _anchor_ts, SNAPSHOT_DAY in api/app/routers/dashboard.py). Rows are written
-- by the backfill/refresh endpoints, not computed on demand by readers, so
-- the History timeline is a single indexed scan instead of N heavy queries.
--
-- Design rationale:
--   - One row per base currency (not one row + FX-on-read) so a currency
--     switch on the History page never re-prices old months against today's
--     rates.
--   - anchor_date is stored, not re-derived, so a later SNAPSHOT_DAY change
--     doesn't silently reinterpret old rows against a different convention —
--     see the rebuild note below.
--   - source_freshness is a per-platform breakdown (not a single scalar),
--     because MAX()-across-accounts freshness hides a stale manual source
--     behind a fresh automated one (the bug this table exists to fix).
--   - freshness_status is the worst-of bucket across source_freshness,
--     for cheap "is this row trustworthy" queries without unpacking JSON.
--
-- Rebuild note: changing SNAPSHOT_DAY changes what "the anchor for March"
-- means. Existing rows keep the anchor_date they were computed with; a full
-- backfill re-run is required after a SNAPSHOT_DAY change to make old and
-- new rows comparable again.

CREATE TABLE IF NOT EXISTS wealth_monthly_rollups (
  id                BIGSERIAL PRIMARY KEY,
  user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  month             TEXT NOT NULL,               -- 'YYYY-MM'
  anchor_date       DATE NOT NULL,                -- exact SNAPSHOT_DAY-aware anchor used
  base_currency     TEXT NOT NULL,
  total             NUMERIC(38,18) NOT NULL,
  cash              NUMERIC(38,18) NOT NULL,
  stocks_funds      NUMERIC(38,18) NOT NULL,
  crypto            NUMERIC(38,18) NOT NULL,
  liabilities       NUMERIC(38,18) NOT NULL,
  source_freshness  JSONB NOT NULL DEFAULT '[]'::jsonb,
  freshness_status  TEXT NOT NULL DEFAULT 'missing', -- fresh | carried | stale | missing (worst-of)
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_wealth_monthly_rollups_user_month_currency
  ON wealth_monthly_rollups(user_id, month, base_currency);

-- Primary access pattern: a user's timeline for one base currency, in order.
CREATE INDEX IF NOT EXISTS idx_wealth_monthly_rollups_user_currency_month
  ON wealth_monthly_rollups(user_id, base_currency, month);
