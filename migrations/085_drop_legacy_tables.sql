-- Drop dead and legacy tables and columns (#359, D-98; #130 finding 1.9, #353 T2).
--
-- None of these is read or written by the app any more (`scripts/db-table-usage.py`), and
-- every one was empty on the real database when this was written. The guard below refuses
-- to run if any of them holds a row, so this migration can never delete data.
--
--   positions                 legacy holdings table, retired by #57 (write guard, migration 057);
--                             its last readers (legacy_backfill.py, parity_report.py and a
--                             UNION branch in market_data held_asset_ids) are removed with it
--   asset_identifiers         never used
--   portfolio_event_groups    never used; the event_group_id columns pointing at it were
--                             never set, so they go too
--   wallet_accounts           never used
--   raw_files, ingestion_jobs the pre-import_jobs upload tables (uploads use import_jobs)
--   crypto_user_networth      never written; only the ownership reassign counted it
--   legacy_account_id on portfolio_position_snapshots / portfolio_cash_balance_snapshots /
--                             portfolio_nav_snapshots: a copy written on every fact row and
--                             never read; reads go through broker_accounts.legacy_account_id
--
-- Kept on purpose: broker_accounts.legacy_account_id (the broker account's CapitalOS account,
-- read everywhere) and broker_import_runs.legacy_account_id (read by the Flex scheduler and the
-- rebuild, and returned by the portfolio API).

DO $$
DECLARE
  t text;
  n bigint;
BEGIN
  FOREACH t IN ARRAY ARRAY['positions', 'asset_identifiers', 'portfolio_event_groups', 'wallet_accounts',
                           'raw_files', 'ingestion_jobs', 'crypto_user_networth'] LOOP
    IF to_regclass('public.' || t) IS NOT NULL THEN
      EXECUTE format('SELECT count(*) FROM public.%I', t) INTO n;
      IF n > 0 THEN
        RAISE EXCEPTION '085: % still has % row(s); refusing to drop it (#359)', t, n;
      END IF;
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM portfolio_trades WHERE event_group_id IS NOT NULL)
     OR EXISTS (SELECT 1 FROM portfolio_cash_ledger_entries WHERE event_group_id IS NOT NULL)
     OR EXISTS (SELECT 1 FROM portfolio_corporate_action_events WHERE event_group_id IS NOT NULL) THEN
    RAISE EXCEPTION '085: an event_group_id is set; refusing to drop it (#359)';
  END IF;
END $$;

ALTER TABLE portfolio_trades DROP COLUMN IF EXISTS event_group_id;
ALTER TABLE portfolio_cash_ledger_entries DROP COLUMN IF EXISTS event_group_id;
ALTER TABLE portfolio_corporate_action_events DROP COLUMN IF EXISTS event_group_id;

ALTER TABLE portfolio_position_snapshots DROP COLUMN IF EXISTS legacy_account_id;
ALTER TABLE portfolio_cash_balance_snapshots DROP COLUMN IF EXISTS legacy_account_id;
ALTER TABLE portfolio_nav_snapshots DROP COLUMN IF EXISTS legacy_account_id;

DROP TABLE IF EXISTS raw_files;
DROP TABLE IF EXISTS ingestion_jobs;
DROP TABLE IF EXISTS asset_identifiers;
DROP TABLE IF EXISTS portfolio_event_groups;
DROP TABLE IF EXISTS wallet_accounts;
DROP TABLE IF EXISTS crypto_user_networth;
-- Its BEFORE INSERT/UPDATE/DELETE guard triggers (057) go with the table; then their function.
DROP TABLE IF EXISTS positions;
DROP FUNCTION IF EXISTS prevent_legacy_positions_write();
