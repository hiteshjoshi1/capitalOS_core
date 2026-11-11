-- Remove rich dummy demo data seeded by migrations/seed_dummy.sql
-- Run with: make db-clear-dummy
BEGIN;

-- History (#221, D-29): the months these rows could have valued are recomputed on the next
-- read. DUMMY prices are in the SHARED prices table, so every user is marked from the earliest
-- DUMMY price date (UTC or trade date, whichever is earlier). The owners of the dummy accounts
-- and wallets (the demo user) lose whole accounts, so all of their history (1970-01-01,
-- ALL_HISTORY in app/wealth_rollup_dirty.py). A pending mark only ever moves earlier.
INSERT INTO wealth_rollup_dirty (user_id, from_date, generation, marked_at, reason)
SELECT marks.user_id, MIN(marks.from_date), 1, now(), 'dummy_cleanup'
FROM (
  SELECT u.id AS user_id, p.from_date
  FROM users u
  CROSS JOIN (
    SELECT MIN(LEAST(trade_date, (ts AT TIME ZONE 'UTC')::date)) AS from_date
    FROM prices WHERE source = 'DUMMY'
  ) p
  WHERE p.from_date IS NOT NULL
  UNION ALL
  -- DUMMY exchange rates (#291) are shared too: every user, from the earliest one.
  SELECT u.id, f.from_date
  FROM users u
  CROSS JOIN (SELECT MIN(rate_date) AS from_date FROM fx_rates WHERE source = 'DUMMY') f
  WHERE f.from_date IS NOT NULL
  UNION ALL
  SELECT a.user_id, DATE '1970-01-01' FROM accounts a WHERE a.name LIKE 'DUMMY - %' AND a.user_id IS NOT NULL
  UNION ALL
  SELECT w.user_id, DATE '1970-01-01' FROM crypto_wallets w WHERE w.label LIKE 'DUMMY - %' AND w.user_id IS NOT NULL
) marks
GROUP BY marks.user_id
ON CONFLICT (user_id) DO UPDATE SET
  from_date = LEAST(COALESCE(wealth_rollup_dirty.from_date, EXCLUDED.from_date), EXCLUDED.from_date),
  generation = wealth_rollup_dirty.generation + 1,
  marked_at = EXCLUDED.marked_at,
  reason = EXCLUDED.reason;

DELETE FROM market_dividend_yields WHERE source = 'DUMMY';
DELETE FROM prices WHERE source = 'DUMMY';
DELETE FROM fx_rates WHERE source = 'DUMMY';

DELETE FROM transfer_links
WHERE from_transaction_id IN (SELECT id FROM transactions WHERE source = 'DUMMY')
   OR to_transaction_id IN (SELECT id FROM transactions WHERE source = 'DUMMY');

DELETE FROM transactions WHERE source = 'DUMMY';
DELETE FROM import_jobs WHERE original_filename LIKE 'DUMMY_%';
DELETE FROM crypto_wallets WHERE label LIKE 'DUMMY - %';
-- Canonical rows of the dummy accounts, deleted explicitly: an import run, a raw document
-- and an account can't be deleted while rows still point at them (RESTRICT, #158).
DO $$
DECLARE
  run_ids bigint[];
  fact_table text;
BEGIN
  SELECT COALESCE(array_agg(r.id), '{}') INTO run_ids
  FROM broker_import_runs r
  WHERE r.source_type = 'DUMMY'
     OR r.legacy_account_id IN (SELECT a.id FROM accounts a WHERE a.name LIKE 'DUMMY - %');
  FOREACH fact_table IN ARRAY ARRAY[
    'portfolio_position_snapshots', 'portfolio_cash_balance_snapshots', 'portfolio_nav_snapshots',
    'portfolio_cash_ledger_entries', 'portfolio_trades', 'portfolio_corporate_action_events',
    'portfolio_fx_rates', 'portfolio_data_completeness', 'portfolio_data_quality_events',
    'portfolio_reconciliations', 'portfolio_report_metrics'
  ] LOOP
    EXECUTE format('DELETE FROM %I WHERE import_run_id = ANY($1)', fact_table) USING run_ids;
  END LOOP;
  DELETE FROM account_balance_snapshots WHERE broker_import_run_id = ANY(run_ids);
  DELETE FROM raw_broker_documents WHERE import_run_id = ANY(run_ids);
  DELETE FROM broker_import_runs WHERE id = ANY(run_ids);
  -- Broker accounts on a dummy account (their remaining facts cascade with them).
  DELETE FROM broker_accounts
  WHERE legacy_account_id IN (SELECT a.id FROM accounts a WHERE a.name LIKE 'DUMMY - %');
END $$;
DELETE FROM broker_connections WHERE connection_type = 'dummy_seed' AND display_name LIKE 'DUMMY - %';
DELETE FROM account_balance_snapshots WHERE source_kind = 'DUMMY';
DELETE FROM accounts WHERE name LIKE 'DUMMY - %';

COMMIT;
