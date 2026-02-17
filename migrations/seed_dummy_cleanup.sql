-- Remove dummy demo data
BEGIN;
DELETE FROM credit_card_accounts WHERE account_id IN (
  SELECT id FROM accounts WHERE name LIKE 'DUMMY - %'
);
DELETE FROM accounts WHERE name LIKE 'DUMMY - %';
DELETE FROM transactions WHERE source = 'DUMMY';
COMMIT;
