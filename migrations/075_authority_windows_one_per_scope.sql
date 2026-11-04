-- Migration 075: one source authority window per (broker account, source, scope) (#140).
--
-- Before: every IBKR Flex statement with a new start date (and every authoritative
-- upload with a new report date) added another open window, and readers counted a
-- row if its authority_status was 'authoritative' OR it fell inside any Flex window.
-- After: readers count a row by authority_status alone; the window is what the
-- importer stamps that status from, and it only moves by an explicit, logged action
-- (app.portfolio.authority.move_window).
--
-- This migration keeps every read the same:
--   1. Stop (changing nothing) if the existing windows can't be merged without
--      changing a date's authority: a triple whose authoritative windows leave a gap,
--      or rows whose promotion (step 3) would give two authoritative rows one key.
--   2. Mark History dirty for the owners of rows step 3 promotes (D-29), from the
--      earliest such date.
--   3. Promote every position / cash / NAV row that today's readers already count
--      only because a Flex window covers it: authority_status := 'authoritative'.
--      The set of rows counted is then the same with or without the window lookup.
--   4. Collapse the windows, one per (broker_account_id, source_kind, fact_scope):
--      the keeper is the row ordered first by (authoritative first, earliest
--      effective_from, lowest id). If it is authoritative, its effective_to becomes
--      NULL when any authoritative window of the triple was open, else the latest
--      effective_to among them. Every other row of the triple is logged in
--      portfolio_source_authority_window_changes (action 'collapsed') and deleted.
--      With no gaps (step 1), the keeper covers exactly the dates the union covered.
--   5. A unique index makes it one row per triple from now on; a CHECK keeps
--      effective_to on or after effective_from.
--
-- The block between the @portable markers is plain SQL that the backend tests also
-- run on SQLite (tests/test_authority_windows.py), so the rule is tested there.

CREATE TABLE IF NOT EXISTS portfolio_source_authority_window_changes (
  id                    BIGSERIAL PRIMARY KEY,
  window_id             BIGINT,          -- no FK: a collapsed window is deleted, its log row stays
  broker_account_id     BIGINT NOT NULL,
  source_kind           TEXT NOT NULL,
  fact_scope            TEXT NOT NULL,
  action                TEXT NOT NULL,   -- created | moved | closed | merged | collapsed
  old_effective_from    DATE,
  old_effective_to      DATE,
  old_authority_status  TEXT,
  new_effective_from    DATE,
  new_effective_to      DATE,
  new_authority_status  TEXT,
  reason                TEXT NOT NULL DEFAULT '',
  actor                 TEXT NOT NULL DEFAULT '',
  changed_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_authority_window_changes_account
  ON portfolio_source_authority_window_changes (broker_account_id, changed_at DESC);

-- Step 1: guards.
DO $$
DECLARE
  bad RECORD;
BEGIN
  SELECT broker_account_id, source_kind, fact_scope, effective_from, prev_end
  INTO bad
  FROM (
    SELECT
      broker_account_id, source_kind, fact_scope, effective_from,
      MAX(COALESCE(effective_to, 'infinity'::date)) OVER (
        PARTITION BY broker_account_id, source_kind, fact_scope
        ORDER BY effective_from, id
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
      ) AS prev_end
    FROM portfolio_source_authority_windows
    WHERE authority_status = 'authoritative'
  ) w
  WHERE prev_end IS NOT NULL
    AND effective_from > prev_end + 1
  LIMIT 1;
  IF FOUND THEN
    RAISE EXCEPTION
      '075: authoritative windows of broker account % (%/%) leave a gap before %; merging them would change authority. Nothing was changed.',
      bad.broker_account_id, bad.source_kind, bad.fact_scope, bad.effective_from;
  END IF;

  IF EXISTS (
    SELECT 1 FROM portfolio_source_authority_windows
    WHERE effective_to IS NOT NULL AND effective_to < effective_from
  ) THEN
    RAISE EXCEPTION '075: a window ends before it starts. Nothing was changed.';
  END IF;

  IF EXISTS (
    SELECT 1
    FROM portfolio_position_snapshots t
    WHERE t.authority_status = 'authoritative'
       OR EXISTS (
         SELECT 1 FROM portfolio_source_authority_windows aw
         WHERE aw.broker_account_id = t.broker_account_id
           AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
           AND aw.authority_status = 'authoritative'
           AND aw.effective_from <= t.report_date
           AND (aw.effective_to IS NULL OR aw.effective_to >= t.report_date))
    GROUP BY t.broker_account_id, t.report_date, t.broker_instrument_id, t.currency
    HAVING COUNT(*) > 1
  ) OR EXISTS (
    SELECT 1
    FROM portfolio_cash_balance_snapshots t
    WHERE t.authority_status = 'authoritative'
       OR EXISTS (
         SELECT 1 FROM portfolio_source_authority_windows aw
         WHERE aw.broker_account_id = t.broker_account_id
           AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
           AND aw.authority_status = 'authoritative'
           AND aw.effective_from <= t.report_date
           AND (aw.effective_to IS NULL OR aw.effective_to >= t.report_date))
    GROUP BY t.broker_account_id, t.report_date, t.currency
    HAVING COUNT(*) > 1
  ) OR EXISTS (
    SELECT 1
    FROM portfolio_nav_snapshots t
    WHERE t.authority_status = 'authoritative'
       OR EXISTS (
         SELECT 1 FROM portfolio_source_authority_windows aw
         WHERE aw.broker_account_id = t.broker_account_id
           AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
           AND aw.authority_status = 'authoritative'
           AND aw.effective_from <= t.report_date
           AND (aw.effective_to IS NULL OR aw.effective_to >= t.report_date))
    GROUP BY t.broker_account_id, t.report_date
    HAVING COUNT(*) > 1
  ) THEN
    RAISE EXCEPTION
      '075: some rows counted today through a Flex window share a key with another counted row; promoting them would break the authoritative unique indexes. Nothing was changed.';
  END IF;
END $$;

-- @portable-begin

-- Step 2: History dirty marks for the owners of the rows step 3 promotes.
INSERT INTO wealth_rollup_dirty (user_id, from_date, generation, marked_at, reason)
SELECT acc.user_id, MIN(f.report_date), 1, CURRENT_TIMESTAMP, 'authority_windows_075'
FROM (
  SELECT t.broker_account_id, t.report_date FROM portfolio_position_snapshots t
  WHERE t.authority_status <> 'authoritative'
    AND EXISTS (
      SELECT 1 FROM portfolio_source_authority_windows aw
      WHERE aw.broker_account_id = t.broker_account_id
        AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
        AND aw.authority_status = 'authoritative'
        AND aw.effective_from <= t.report_date
        AND (aw.effective_to IS NULL OR aw.effective_to >= t.report_date))
  UNION ALL
  SELECT t.broker_account_id, t.report_date FROM portfolio_cash_balance_snapshots t
  WHERE t.authority_status <> 'authoritative'
    AND EXISTS (
      SELECT 1 FROM portfolio_source_authority_windows aw
      WHERE aw.broker_account_id = t.broker_account_id
        AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
        AND aw.authority_status = 'authoritative'
        AND aw.effective_from <= t.report_date
        AND (aw.effective_to IS NULL OR aw.effective_to >= t.report_date))
  UNION ALL
  SELECT t.broker_account_id, t.report_date FROM portfolio_nav_snapshots t
  WHERE t.authority_status <> 'authoritative'
    AND EXISTS (
      SELECT 1 FROM portfolio_source_authority_windows aw
      WHERE aw.broker_account_id = t.broker_account_id
        AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
        AND aw.authority_status = 'authoritative'
        AND aw.effective_from <= t.report_date
        AND (aw.effective_to IS NULL OR aw.effective_to >= t.report_date))
) f
JOIN broker_accounts ba ON ba.id = f.broker_account_id
JOIN accounts acc ON acc.id = ba.legacy_account_id
WHERE acc.user_id IS NOT NULL
GROUP BY acc.user_id
ON CONFLICT (user_id) DO UPDATE SET
  from_date = CASE
    WHEN wealth_rollup_dirty.from_date IS NULL OR EXCLUDED.from_date < wealth_rollup_dirty.from_date
    THEN EXCLUDED.from_date
    ELSE wealth_rollup_dirty.from_date
  END,
  generation = wealth_rollup_dirty.generation + 1,
  marked_at = EXCLUDED.marked_at,
  reason = EXCLUDED.reason;

-- Step 3: promote rows counted today only through a Flex window.
UPDATE portfolio_position_snapshots
SET authority_status = 'authoritative', updated_at = CURRENT_TIMESTAMP
WHERE authority_status <> 'authoritative'
  AND EXISTS (
    SELECT 1 FROM portfolio_source_authority_windows aw
    WHERE aw.broker_account_id = portfolio_position_snapshots.broker_account_id
      AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
      AND aw.authority_status = 'authoritative'
      AND aw.effective_from <= portfolio_position_snapshots.report_date
      AND (aw.effective_to IS NULL OR aw.effective_to >= portfolio_position_snapshots.report_date));

UPDATE portfolio_cash_balance_snapshots
SET authority_status = 'authoritative', updated_at = CURRENT_TIMESTAMP
WHERE authority_status <> 'authoritative'
  AND EXISTS (
    SELECT 1 FROM portfolio_source_authority_windows aw
    WHERE aw.broker_account_id = portfolio_cash_balance_snapshots.broker_account_id
      AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
      AND aw.authority_status = 'authoritative'
      AND aw.effective_from <= portfolio_cash_balance_snapshots.report_date
      AND (aw.effective_to IS NULL OR aw.effective_to >= portfolio_cash_balance_snapshots.report_date));

UPDATE portfolio_nav_snapshots
SET authority_status = 'authoritative', updated_at = CURRENT_TIMESTAMP
WHERE authority_status <> 'authoritative'
  AND EXISTS (
    SELECT 1 FROM portfolio_source_authority_windows aw
    WHERE aw.broker_account_id = portfolio_nav_snapshots.broker_account_id
      AND aw.source_kind = 'ibkr_flex_daily' AND aw.fact_scope = 'all'
      AND aw.authority_status = 'authoritative'
      AND aw.effective_from <= portfolio_nav_snapshots.report_date
      AND (aw.effective_to IS NULL OR aw.effective_to >= portfolio_nav_snapshots.report_date));

-- Step 4: collapse to one window per triple. Rank 1 is the keeper.
INSERT INTO portfolio_source_authority_window_changes
  (window_id, broker_account_id, source_kind, fact_scope, action,
   old_effective_from, old_effective_to, old_authority_status,
   new_effective_from, new_effective_to, new_authority_status,
   reason, actor, changed_at)
SELECT
  k.id, k.broker_account_id, k.source_kind, k.fact_scope, 'merged',
  k.effective_from, k.effective_to, k.authority_status,
  k.effective_from,
  CASE
    WHEN k.authority_status <> 'authoritative' THEN k.effective_to
    ELSE (
      SELECT CASE WHEN COUNT(*) > COUNT(o.effective_to) THEN NULL ELSE MAX(o.effective_to) END
      FROM portfolio_source_authority_windows o
      WHERE o.broker_account_id = k.broker_account_id
        AND o.source_kind = k.source_kind
        AND o.fact_scope = k.fact_scope
        AND o.authority_status = 'authoritative')
  END,
  k.authority_status,
  'migration 075: kept as the one window of its scope', 'migration_075', CURRENT_TIMESTAMP
FROM (
  SELECT w.*, ROW_NUMBER() OVER (
    PARTITION BY broker_account_id, source_kind, fact_scope
    ORDER BY CASE WHEN authority_status = 'authoritative' THEN 0 ELSE 1 END, effective_from, id
  ) AS rn,
  COUNT(*) OVER (PARTITION BY broker_account_id, source_kind, fact_scope) AS n
  FROM portfolio_source_authority_windows w
) k
WHERE k.rn = 1 AND k.n > 1;

INSERT INTO portfolio_source_authority_window_changes
  (window_id, broker_account_id, source_kind, fact_scope, action,
   old_effective_from, old_effective_to, old_authority_status,
   new_effective_from, new_effective_to, new_authority_status,
   reason, actor, changed_at)
SELECT
  d.id, d.broker_account_id, d.source_kind, d.fact_scope, 'collapsed',
  d.effective_from, d.effective_to, d.authority_status,
  NULL, NULL, NULL,
  'migration 075: merged into the earliest window of its scope', 'migration_075', CURRENT_TIMESTAMP
FROM (
  SELECT w.*, ROW_NUMBER() OVER (
    PARTITION BY broker_account_id, source_kind, fact_scope
    ORDER BY CASE WHEN authority_status = 'authoritative' THEN 0 ELSE 1 END, effective_from, id
  ) AS rn
  FROM portfolio_source_authority_windows w
) d
WHERE d.rn > 1;

UPDATE portfolio_source_authority_windows
SET effective_to = (
  SELECT CASE WHEN COUNT(*) > COUNT(o.effective_to) THEN NULL ELSE MAX(o.effective_to) END
  FROM portfolio_source_authority_windows o
  WHERE o.broker_account_id = portfolio_source_authority_windows.broker_account_id
    AND o.source_kind = portfolio_source_authority_windows.source_kind
    AND o.fact_scope = portfolio_source_authority_windows.fact_scope
    AND o.authority_status = 'authoritative')
WHERE authority_status = 'authoritative'
  AND id IN (
    SELECT id FROM (
      SELECT id, ROW_NUMBER() OVER (
        PARTITION BY broker_account_id, source_kind, fact_scope
        ORDER BY CASE WHEN authority_status = 'authoritative' THEN 0 ELSE 1 END, effective_from, id
      ) AS rn,
      COUNT(*) OVER (PARTITION BY broker_account_id, source_kind, fact_scope) AS n
      FROM portfolio_source_authority_windows
    ) r
    WHERE r.rn = 1 AND r.n > 1);

DELETE FROM portfolio_source_authority_windows
WHERE id IN (
  SELECT id FROM (
    SELECT id, ROW_NUMBER() OVER (
      PARTITION BY broker_account_id, source_kind, fact_scope
      ORDER BY CASE WHEN authority_status = 'authoritative' THEN 0 ELSE 1 END, effective_from, id
    ) AS rn
    FROM portfolio_source_authority_windows
  ) r
  WHERE r.rn > 1);

-- Step 5: one row per triple from now on.
CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_source_authority_windows_scope
  ON portfolio_source_authority_windows (broker_account_id, source_kind, fact_scope);

-- @portable-end

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_authority_window_dates'
  ) THEN
    ALTER TABLE portfolio_source_authority_windows
      ADD CONSTRAINT chk_authority_window_dates
      CHECK (effective_to IS NULL OR effective_to >= effective_from);
  END IF;
END $$;
