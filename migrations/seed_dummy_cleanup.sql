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
DELETE FROM broker_connections WHERE connection_type = 'dummy_seed' AND display_name LIKE 'DUMMY - %';
DELETE FROM account_balance_snapshots WHERE source_kind = 'DUMMY';
DELETE FROM accounts WHERE name LIKE 'DUMMY - %';

COMMIT;
