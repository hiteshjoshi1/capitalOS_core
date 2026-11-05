-- Remove rich dummy demo data seeded by migrations/seed_dummy.sql
-- Run with: make db-clear-dummy
BEGIN;

DELETE FROM market_dividend_yields WHERE source = 'DUMMY';
DELETE FROM prices WHERE source = 'DUMMY';

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
    'portfolio_reconciliations', 'portfolio_report_metrics', 'portfolio_event_groups'
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
