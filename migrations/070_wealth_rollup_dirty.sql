-- Migration 070: keep the History rollups in step with imports (#138).
-- Additive schema only.
--
-- wealth_rollup_dirty: one row per user. Every write path that changes a
-- valuation input (uploads, IBKR Flex, crypto snapshots, card statements,
-- wallet/ownership changes) records the earliest date it changed. from_date
-- only ever moves earlier while a mark is pending, and generation goes up on
-- every mark. A rollup row is stale when its anchor_date >= from_date and it
-- was computed from an older generation (input_generation < generation).
-- After a recompute from_date moves to the earliest row that is still stale
-- (another currency, a month outside the range read), or NULL when none is.
-- The row is kept (not deleted) so generation never goes backwards.

CREATE TABLE IF NOT EXISTS wealth_rollup_dirty (
  user_id     BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  from_date   DATE,                        -- NULL = nothing pending
  generation  BIGINT NOT NULL DEFAULT 0,
  marked_at   TIMESTAMPTZ,
  reason      TEXT
);

-- The input watermark: the user's wealth_rollup_dirty.generation the row was
-- computed from. 0 for rows written before this migration, so any later mark
-- covering their anchor makes them stale.
ALTER TABLE wealth_monthly_rollups
  ADD COLUMN IF NOT EXISTS input_generation BIGINT NOT NULL DEFAULT 0;
