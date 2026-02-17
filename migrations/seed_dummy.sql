-- Dummy data seed for demo dashboards (idempotent)
-- Safe to re-run: removes prior dummy accounts first

BEGIN;

-- Remove prior dummy data (accounts cascade to positions/transactions)
DELETE FROM accounts WHERE name LIKE 'DUMMY - %';

-- Ensure base assets exist (no-op if already present)
INSERT INTO assets (symbol, name, asset_class, quote_currency, home_country)
VALUES
  ('SGD', 'Singapore Dollar Cash', 'CASH', 'SGD', 'SG'),
  ('USD', 'US Dollar Cash', 'CASH', 'USD', 'US'),
  ('AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US'),
  ('VTI', 'Vanguard Total Stock Market ETF', 'FUND', 'USD', 'US'),
  ('RELIANCE', 'Reliance Industries', 'STOCK', 'INR', 'IN')
ON CONFLICT (symbol, quote_currency) DO NOTHING;

-- Accounts
WITH p AS (
  SELECT id, code FROM platforms WHERE code IN ('DBS','IBKR','SHAREKHAN','DBS_CARDS')
)
INSERT INTO accounts (name, platform, account_type, currency, country, platform_id)
VALUES
  ('DUMMY - DBS Savings', 'DBS', 'BANK', 'SGD', 'SG', (SELECT id FROM p WHERE code='DBS')),
  ('DUMMY - IBKR Main', 'IBKR', 'BROKER', 'USD', 'US', (SELECT id FROM p WHERE code='IBKR')),
  ('DUMMY - Sharekhan Trading', 'SHAREKHAN', 'BROKER', 'INR', 'IN', (SELECT id FROM p WHERE code='SHAREKHAN')),
  ('DUMMY - DBS Credit Card', 'DBS_CARDS', 'CREDIT_CARD', 'SGD', 'SG', (SELECT id FROM p WHERE code='DBS_CARDS'));

-- Credit card metadata
INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day)
VALUES
  ((SELECT id FROM accounts WHERE name='DUMMY - DBS Credit Card'), 'DBS Altitude', 'DBS', 20000, 20, 25)
ON CONFLICT (account_id) DO NOTHING;

-- Positions snapshot (use snapshot day 6)
WITH a AS (
  SELECT id, name FROM accounts WHERE name LIKE 'DUMMY - %'
),
assets_cte AS (
  SELECT id, symbol, quote_currency FROM assets
  WHERE (symbol, quote_currency) IN (
    ('SGD','SGD'), ('USD','USD'), ('AAPL','USD'), ('VTI','USD'), ('RELIANCE','INR')
  )
)
INSERT INTO positions (account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base)
VALUES
  ((SELECT id FROM a WHERE name='DUMMY - DBS Savings'), (SELECT id FROM assets_cte WHERE symbol='SGD'), '2026-02-06T00:00:00Z', 1, 1, 42000),
  ((SELECT id FROM a WHERE name='DUMMY - IBKR Main'), (SELECT id FROM assets_cte WHERE symbol='USD'), '2026-02-06T00:00:00Z', 1, 1, 12000),
  ((SELECT id FROM a WHERE name='DUMMY - IBKR Main'), (SELECT id FROM assets_cte WHERE symbol='AAPL'), '2026-02-06T00:00:00Z', 120, 150, 18000),
  ((SELECT id FROM a WHERE name='DUMMY - IBKR Main'), (SELECT id FROM assets_cte WHERE symbol='VTI'), '2026-02-06T00:00:00Z', 80, 210, 16800),
  ((SELECT id FROM a WHERE name='DUMMY - Sharekhan Trading'), (SELECT id FROM assets_cte WHERE symbol='RELIANCE'), '2026-02-06T00:00:00Z', 300, 2400, 14500);

-- Transactions for cashflow (February 2026)
WITH a AS (
  SELECT id, name FROM accounts WHERE name LIKE 'DUMMY - %'
)
INSERT INTO transactions (ts, account_id, type, amount, currency, category, merchant_counterparty, notes, source)
VALUES
  ('2026-02-02T10:00:00Z', (SELECT id FROM a WHERE name='DUMMY - DBS Savings'), 'INCOME', 8200, 'SGD', 'Salary', 'Acme Pte Ltd', 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-05T12:00:00Z', (SELECT id FROM a WHERE name='DUMMY - DBS Savings'), 'EXPENSE', -230, 'SGD', 'Utilities', 'SP Group', 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-08T18:30:00Z', (SELECT id FROM a WHERE name='DUMMY - DBS Savings'), 'EXPENSE', -180, 'SGD', 'Insurance', 'NTUC Income', 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-10T13:00:00Z', (SELECT id FROM a WHERE name='DUMMY - DBS Credit Card'), 'EXPENSE', -420, 'SGD', 'Dining', 'Hawker Center', 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T09:15:00Z', (SELECT id FROM a WHERE name='DUMMY - DBS Credit Card'), 'EXPENSE', -310, 'SGD', 'Groceries', 'Cold Storage', 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-15T07:45:00Z', (SELECT id FROM a WHERE name='DUMMY - DBS Savings'), 'EXPENSE', -260, 'SGD', 'Subscription', 'Spotify', 'DUMMY_SEED', 'DUMMY');

COMMIT;
