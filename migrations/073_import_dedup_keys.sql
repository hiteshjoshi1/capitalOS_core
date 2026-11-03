-- Import dedup by occurrence count and broker ids (#157).

-- Bank/card uploads: each new row carries the identity of the occurrence it
-- stores (natural key + occurrence index; runner.py). Rows imported before this
-- migration keep NULL: the dedup decision counts rows by natural key, so they
-- still count, and the partial unique index ignores them.
ALTER TABLE transactions ADD COLUMN IF NOT EXISTS source_fingerprint TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_account_source_fingerprint
  ON transactions(account_id, source_fingerprint)
  WHERE source_fingerprint IS NOT NULL;

-- IBKR cash ledger: two genuinely identical lines without a transaction id
-- (e.g. two equal FX translation adjustments on one day) must both be kept, so
-- the value-tuple unique index goes. Lines with an IBKR transaction id stay
-- unique on the full line; the import replaces them by id.
DROP INDEX IF EXISTS uq_portfolio_cash_ledger_activity;

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_cash_ledger_activity_id
  ON portfolio_cash_ledger_entries(
    broker_account_id, broker_activity_id, activity_date, currency, amount,
    COALESCE(activity_code, ''), COALESCE(description, '')
  )
  WHERE broker_activity_id IS NOT NULL AND broker_activity_id <> '';

CREATE INDEX IF NOT EXISTS idx_portfolio_cash_ledger_account_date
  ON portfolio_cash_ledger_entries(broker_account_id, activity_date);
