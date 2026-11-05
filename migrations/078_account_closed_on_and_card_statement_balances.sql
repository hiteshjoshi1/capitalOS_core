-- Past months change silently (#207, #130 findings 1.5 and 1.6).
--
-- closed_on: an account closed on this date counts at every anchor on or before
--   it, exactly as before, and contributes nothing at any later anchor (its last
--   snapshot is no longer carried forward). NULL = open. Set in Add Account.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS closed_on DATE;

-- Card statement balances become dated account_balance_snapshots rows
-- (balance_type 'credit_balance', negative while money is owed), read like a bank
-- balance: the newest one on or before an anchor. Until now a card's liability
-- came from the single credit_card_accounts row each DBS card upload overwrote,
-- so a newer statement changed every month in between.
--
-- Backfill the one dated balance the database holds: each card's current limits
-- (credit_limit - available_limit as of available_limit_as_of; the parser stores
-- that date at 00:00 UTC). Older statements are backfilled from their stored
-- files by `make card-balance-backfill` (it re-parses them). The columns of
-- credit_card_accounts stay as they are (the Spending page reads them).
-- Re-running is a no-op (an existing row for that date is left alone).
INSERT INTO account_balance_snapshots
  (account_id, as_of_date, currency, balance_type, balance_local, balance_base,
   fx_rate_to_base, authority_status, source_kind, metadata_json)
SELECT
  a.id,
  (cc.available_limit_as_of AT TIME ZONE 'UTC')::date,
  UPPER(a.currency),
  'credit_balance',
  cc.available_limit - cc.credit_limit,
  cc.available_limit - cc.credit_limit,
  1,
  'authoritative',
  'backfill',
  jsonb_build_object(
    'source', 'card_limits',
    'backfill', '078',
    'credit_limit', cc.credit_limit,
    'available_limit', cc.available_limit
  )
FROM credit_card_accounts cc
JOIN accounts a ON a.id = cc.account_id
WHERE a.account_type = 'CREDIT_CARD'
  AND cc.credit_limit IS NOT NULL
  AND cc.available_limit IS NOT NULL
  AND cc.available_limit_as_of IS NOT NULL
ON CONFLICT (account_id, as_of_date, currency, balance_type)
  WHERE authority_status = 'authoritative'
  DO NOTHING;

-- History (D-29): months from the earliest backfilled date on are recomputed.
-- Within 45 days of that date a month reads the same balance as before; later
-- months no longer carry it forward and read the card's transactions instead.
INSERT INTO wealth_rollup_dirty (user_id, from_date, generation, marked_at, reason)
SELECT a.user_id, MIN(abs.as_of_date), 1, now(), 'card_statement_balance_backfill'
FROM account_balance_snapshots abs
JOIN accounts a ON a.id = abs.account_id
WHERE abs.balance_type = 'credit_balance'
  AND abs.source_kind = 'backfill'
  AND abs.metadata_json ->> 'backfill' = '078'
  AND a.user_id IS NOT NULL
GROUP BY a.user_id
ON CONFLICT (user_id) DO UPDATE SET
  from_date = LEAST(COALESCE(wealth_rollup_dirty.from_date, EXCLUDED.from_date), EXCLUDED.from_date),
  generation = wealth_rollup_dirty.generation + 1,
  marked_at = EXCLUDED.marked_at,
  reason = EXCLUDED.reason;
