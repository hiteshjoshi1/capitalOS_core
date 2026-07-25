-- Rich demo data seed for user "demo" (idempotent)
-- Goal: broad portfolio + spending + crypto + ingest coverage for UI demos, for a
-- high-net-worth individual, with 12 months of trailing history so wealth/cash-flow/
-- stock/crypto trend charts show real month-over-month movement.
-- Run with: make db-seed-dummy

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM users WHERE LOWER(username) = 'demo') THEN
    RAISE EXCEPTION 'Demo user not found. Run migrations/033_seed_demo_user.sql first.';
  END IF;
END $$;

UPDATE users
SET display_name = 'Demo Joshi',
    is_active = TRUE,
    updated_at = NOW()
WHERE LOWER(username) = 'demo';

-- Remove prior demo artifacts (safe to re-run)
DELETE FROM crypto_wallets WHERE label LIKE 'DUMMY - %';
DELETE FROM account_balance_snapshots WHERE source_kind = 'DUMMY';
DELETE FROM broker_import_runs WHERE source_type = 'DUMMY';
DELETE FROM broker_connections WHERE connection_type = 'dummy_seed' AND display_name LIKE 'DUMMY - %';
DELETE FROM accounts WHERE name LIKE 'DUMMY - %';
DELETE FROM transactions WHERE source = 'DUMMY';
DELETE FROM prices WHERE source = 'DUMMY';
DELETE FROM market_dividend_yields WHERE source = 'DUMMY';
DELETE FROM import_jobs WHERE original_filename LIKE 'DUMMY_%';

-- ═══════════════════════════════════════════════════════════════════
-- Month scaffold: current month back to 11 months ago, used by every
-- time-series section below (cash, positions, crypto, transactions).
-- Current month keeps the exact baseline values; older months are
-- scaled down slightly so the trend charts show realistic growth
-- leading up to today.
-- ═══════════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS seed_months;
CREATE TEMP TABLE seed_months AS
SELECT
  gs AS month_offset,
  (date_trunc('month', CURRENT_DATE) - (gs || ' months')::interval)::date AS month_start,
  LEAST(6, CASE WHEN gs = 0 THEN EXTRACT(day FROM CURRENT_DATE)::int ELSE 6 END) AS day_cap,
  (1 - 0.03 * gs)::numeric AS growth_factor,
  (ARRAY[1.15, 0.95, 1.05, 0.90, 1.10, 1.00, 1.08, 0.92, 1.12, 0.97, 1.04, 0.88])[gs + 1]::numeric AS discretionary_multiplier
FROM generate_series(0, 11) AS gs;

-- snapshot date used for cash/position/crypto snapshots each month (day 6, or
-- today if the current month hasn't reached the 6th yet)
ALTER TABLE seed_months ADD COLUMN as_of_date date;
UPDATE seed_months SET as_of_date = (month_start + (day_cap - 1) * interval '1 day')::date;

-- Ensure assets exist (realistic symbols across US, SG, HK + cash and MMF)
INSERT INTO assets (symbol, name, asset_class, quote_currency, home_country)
VALUES
  -- Cash
  ('SGD', 'Singapore Dollar Cash', 'CASH', 'SGD', 'SG'),
  ('USD', 'US Dollar Cash', 'CASH', 'USD', 'US'),
  -- Cash-like fund
  ('SGDMMF', 'SGD Money Market Fund', 'FUND', 'SGD', 'SG'),
  -- US equities
  ('MSFT', 'Microsoft Corporation', 'STOCK', 'USD', 'US'),
  ('GOOGL', 'Alphabet Inc. Class A', 'STOCK', 'USD', 'US'),
  ('META', 'Meta Platforms, Inc.', 'STOCK', 'USD', 'US'),
  ('AMZN', 'Amazon.com, Inc.', 'STOCK', 'USD', 'US'),
  ('NVDA', 'NVIDIA Corporation', 'STOCK', 'USD', 'US'),
  ('AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US'),
  ('TSLA', 'Tesla, Inc.', 'STOCK', 'USD', 'US'),
  ('BRK-B', 'Berkshire Hathaway Inc. Class B', 'STOCK', 'USD', 'US'),
  ('XOM', 'Exxon Mobil Corporation', 'STOCK', 'USD', 'US'),
  ('CVX', 'Chevron Corporation', 'STOCK', 'USD', 'US'),
  ('COP', 'Conoco Phillips', 'STOCK', 'USD', 'US'),
  ('SLB', 'Schlumberger Limited', 'STOCK', 'USD', 'US'),
  ('JPM', 'JPMorgan Chase & Co.', 'STOCK', 'USD', 'US'),
  ('V', 'Visa Inc.', 'STOCK', 'USD', 'US'),
  ('MA', 'Mastercard Incorporated', 'STOCK', 'USD', 'US'),
  ('UNH', 'UnitedHealth Group Incorporated', 'STOCK', 'USD', 'US'),
  ('LLY', 'Eli Lilly and Company', 'STOCK', 'USD', 'US'),
  ('NVO', 'Novo Nordisk A/S', 'STOCK', 'USD', 'US'),
  ('REGN', 'Regeneron Pharmaceuticals, Inc.', 'STOCK', 'USD', 'US'),
  ('NFLX', 'Netflix, Inc.', 'STOCK', 'USD', 'US'),
  ('ORCL', 'Oracle Corporation', 'STOCK', 'USD', 'US'),
  ('PLTR', 'Palantir Technologies Inc.', 'STOCK', 'USD', 'US'),
  ('AVGO', 'Broadcom Inc.', 'STOCK', 'USD', 'US'),
  ('CRM', 'Salesforce, Inc.', 'STOCK', 'USD', 'US'),
  -- Singapore equities
  ('D05', 'DBS Group Holdings Ltd.', 'STOCK', 'SGD', 'SG'),
  ('U11', 'United Overseas Bank Ltd.', 'STOCK', 'SGD', 'SG'),
  ('O39', 'Oversea-Chinese Banking Corporation Ltd.', 'STOCK', 'SGD', 'SG'),
  ('S68', 'Singapore Exchange Limited', 'STOCK', 'SGD', 'SG'),
  ('H02', 'Haw Par Corporation Limited', 'STOCK', 'SGD', 'SG'),
  -- Hong Kong equities
  ('0700', 'Tencent Holdings Limited', 'STOCK', 'HKD', 'HK'),
  ('9988', 'Alibaba Group Holding Limited', 'STOCK', 'HKD', 'HK'),
  ('0388', 'Hong Kong Exchanges and Clearing Limited', 'STOCK', 'HKD', 'HK')
ON CONFLICT (symbol, quote_currency) DO NOTHING;

-- Card-issuer platform used by the credit cards below (Citi already exists)
INSERT INTO platforms (code, name, platform_type, country, website)
VALUES ('AMEX', 'American Express', 'CARD_ISSUER', 'US', 'https://www.americanexpress.com')
ON CONFLICT (code) DO NOTHING;

-- Accounts owned by demo user
WITH demo_user AS (
  SELECT id AS user_id FROM users WHERE LOWER(username) = 'demo' LIMIT 1
),
p AS (
  SELECT id, code FROM platforms WHERE code IN ('DBS', 'OCBC', 'UOB', 'IBKR', 'DBS_VICKERS', 'AMEX', 'CITI')
)
INSERT INTO accounts (name, platform, user_id, account_type, currency, country, platform_id)
VALUES
  ('DUMMY - DBS Savings', 'DBS', (SELECT user_id FROM demo_user), 'BANK', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'DBS')),
  ('DUMMY - OCBC 360', 'OCBC', (SELECT user_id FROM demo_user), 'BANK', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'OCBC')),
  ('DUMMY - UOB One', 'UOB', (SELECT user_id FROM demo_user), 'BANK', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'UOB')),
  ('DUMMY - IBKR Global', 'IBKR', (SELECT user_id FROM demo_user), 'BROKER', 'USD', 'US', (SELECT id FROM p WHERE code = 'IBKR')),
  ('DUMMY - DBS Vickers SGX', 'DBS_VICKERS', (SELECT user_id FROM demo_user), 'BROKER', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'DBS_VICKERS')),
  ('DUMMY - SG Money Market Fund', 'DBS', (SELECT user_id FROM demo_user), 'MUTUAL_FUND', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'DBS')),
  ('DUMMY - DBS Credit Card', 'DBS', (SELECT user_id FROM demo_user), 'CREDIT_CARD', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'DBS')),
  ('DUMMY - UOB Credit Card', 'UOB', (SELECT user_id FROM demo_user), 'CREDIT_CARD', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'UOB')),
  ('DUMMY - Amex Platinum', 'AMEX', (SELECT user_id FROM demo_user), 'CREDIT_CARD', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'AMEX')),
  ('DUMMY - Citi Prestige', 'CITI', (SELECT user_id FROM demo_user), 'CREDIT_CARD', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'CITI'));

INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day)
VALUES
  ((SELECT id FROM accounts WHERE name = 'DUMMY - DBS Credit Card'), 'DBS Vantage', 'DBS', 120000, 20, 25),
  ((SELECT id FROM accounts WHERE name = 'DUMMY - UOB Credit Card'), 'UOB Reserve', 'UOB', 100000, 10, 18),
  ((SELECT id FROM accounts WHERE name = 'DUMMY - Amex Platinum'), 'Amex Platinum Charge', 'Amex', 500000, 15, 22),
  ((SELECT id FROM accounts WHERE name = 'DUMMY - Citi Prestige'), 'Citi Prestige', 'Citi', 200000, 8, 15)
ON CONFLICT (account_id) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════════
-- Cash balance snapshots — one per month per cash account, scaled by
-- growth_factor so the 12-month trend shows a rising wealth trajectory.
-- ═══════════════════════════════════════════════════════════════════
WITH base(account_name, currency, balance_type, base_balance) AS (
  VALUES
    ('DUMMY - DBS Savings', 'SGD', 'bank_cash', 400000::numeric),
    ('DUMMY - OCBC 360', 'SGD', 'bank_cash', 350000::numeric),
    ('DUMMY - UOB One', 'SGD', 'bank_cash', 300000::numeric),
    ('DUMMY - IBKR Global', 'USD', 'broker_cash', 700000::numeric)
)
INSERT INTO account_balance_snapshots (
  account_id, as_of_date, currency, balance_type, balance_local, balance_base,
  fx_rate_to_base, authority_status, source_kind, metadata_json
)
SELECT
  a.id,
  sm.as_of_date,
  b.currency,
  b.balance_type,
  ROUND(b.base_balance * sm.growth_factor, 2),
  ROUND(b.base_balance * sm.growth_factor, 2),
  1,
  'authoritative',
  'DUMMY',
  '{}'::jsonb
FROM base b
JOIN accounts a ON a.name = b.account_name
CROSS JOIN seed_months sm
ON CONFLICT (account_id, as_of_date, currency, balance_type)
WHERE authority_status = 'authoritative'
DO UPDATE SET
  balance_local = EXCLUDED.balance_local,
  balance_base = EXCLUDED.balance_base,
  fx_rate_to_base = EXCLUDED.fx_rate_to_base,
  source_kind = EXCLUDED.source_kind,
  metadata_json = EXCLUDED.metadata_json,
  updated_at = NOW();

-- ═══════════════════════════════════════════════════════════════════
-- Canonical portfolio: broker connections/accounts (once), then a
-- position snapshot per holding per month (scaled by growth_factor).
-- ═══════════════════════════════════════════════════════════════════
WITH demo_user AS (
  SELECT id AS user_id FROM users WHERE LOWER(username) = 'demo' LIMIT 1
),
platforms_needed(platform_code) AS (
  VALUES ('DBS'), ('DBS_VICKERS'), ('IBKR')
)
INSERT INTO broker_connections (user_id, platform_code, connection_type, display_name, status, metadata_json)
SELECT
  demo_user.user_id,
  platforms_needed.platform_code,
  'dummy_seed',
  'DUMMY - ' || platforms_needed.platform_code || ' Connection',
  'active',
  '{}'::jsonb
FROM demo_user
CROSS JOIN platforms_needed;

WITH account_map(account_name, platform_code) AS (
  VALUES
    ('DUMMY - SG Money Market Fund', 'DBS'),
    ('DUMMY - DBS Vickers SGX', 'DBS_VICKERS'),
    ('DUMMY - IBKR Global', 'IBKR')
),
connections AS (
  SELECT bc.id, bc.platform_code
  FROM broker_connections bc
  JOIN users u ON u.id = bc.user_id
  WHERE LOWER(u.username) = 'demo'
    AND bc.connection_type = 'dummy_seed'
    AND bc.display_name LIKE 'DUMMY - %'
),
accounts_to_seed AS (
  SELECT
    acc.id AS account_id,
    acc.name,
    acc.currency,
    acc.country,
    account_map.platform_code,
    connections.id AS connection_id
  FROM account_map
  JOIN accounts acc ON acc.name = account_map.account_name
  JOIN connections ON connections.platform_code = account_map.platform_code
)
INSERT INTO broker_accounts (
  connection_id, legacy_account_id, broker_account_id, account_alias,
  base_currency, country, status, metadata_json
)
SELECT
  connection_id, account_id, 'DUMMY:' || account_id::text, name, currency, country, 'active', '{}'::jsonb
FROM accounts_to_seed;

DROP TABLE IF EXISTS seed_stock_holdings;
CREATE TEMP TABLE seed_stock_holdings AS
SELECT * FROM (VALUES
  ('DUMMY - SG Money Market Fund', 'DBS', 'SGDMMF', 'SGD', 300000::numeric, 1::numeric, 300000::numeric),
  ('DUMMY - IBKR Global', 'IBKR', 'MSFT', 'USD', 700::numeric, 360::numeric, 252000::numeric),
  ('DUMMY - IBKR Global', 'IBKR', 'GOOGL', 'USD', 1400, 150, 210000),
  ('DUMMY - IBKR Global', 'IBKR', 'META', 'USD', 500, 430, 215000),
  ('DUMMY - IBKR Global', 'IBKR', 'AMZN', 'USD', 1200, 160, 192000),
  ('DUMMY - IBKR Global', 'IBKR', 'NVDA', 'USD', 1800, 110, 198000),
  ('DUMMY - IBKR Global', 'IBKR', 'AAPL', 'USD', 1300, 170, 221000),
  ('DUMMY - IBKR Global', 'IBKR', 'TSLA', 'USD', 700, 200, 140000),
  ('DUMMY - IBKR Global', 'IBKR', 'BRK-B', 'USD', 256, 390, 99840),
  ('DUMMY - IBKR Global', 'IBKR', 'XOM', 'USD', 773, 95, 73435),
  ('DUMMY - IBKR Global', 'IBKR', 'CVX', 'USD', 516, 135, 69660),
  ('DUMMY - IBKR Global', 'IBKR', 'COP', 'USD', 609, 100, 60900),
  ('DUMMY - IBKR Global', 'IBKR', 'SLB', 'USD', 900, 42, 37800),
  ('DUMMY - IBKR Global', 'IBKR', 'JPM', 'USD', 500, 175, 87500),
  ('DUMMY - IBKR Global', 'IBKR', 'V', 'USD', 333, 250, 83250),
  ('DUMMY - IBKR Global', 'IBKR', 'MA', 'USD', 177, 430, 76110),
  ('DUMMY - IBKR Global', 'IBKR', 'UNH', 'USD', 180, 430, 77400),
  ('DUMMY - IBKR Global', 'IBKR', 'LLY', 'USD', 280, 700, 196000),
  ('DUMMY - IBKR Global', 'IBKR', 'NVO', 'USD', 1900, 105, 199500),
  ('DUMMY - IBKR Global', 'IBKR', 'REGN', 'USD', 250, 860, 215000),
  ('DUMMY - IBKR Global', 'IBKR', 'NFLX', 'USD', 123, 560, 68880),
  ('DUMMY - IBKR Global', 'IBKR', 'ORCL', 'USD', 500, 120, 60000),
  ('DUMMY - IBKR Global', 'IBKR', 'PLTR', 'USD', 1500, 24, 36000),
  ('DUMMY - IBKR Global', 'IBKR', 'AVGO', 'USD', 73, 1200, 87600),
  ('DUMMY - IBKR Global', 'IBKR', 'CRM', 'USD', 317, 260, 82420),
  ('DUMMY - DBS Vickers SGX', 'DBS_VICKERS', 'D05', 'SGD', 18000, 31, 558000),
  ('DUMMY - DBS Vickers SGX', 'DBS_VICKERS', 'U11', 'SGD', 12000, 27, 324000),
  ('DUMMY - DBS Vickers SGX', 'DBS_VICKERS', 'O39', 'SGD', 22000, 13, 286000),
  ('DUMMY - DBS Vickers SGX', 'DBS_VICKERS', 'S68', 'SGD', 15000, 10, 150000),
  ('DUMMY - DBS Vickers SGX', 'DBS_VICKERS', 'H02', 'SGD', 20000, 10.5, 210000),
  ('DUMMY - IBKR Global', 'IBKR', '0700', 'HKD', 7500, 280, 2100000),
  ('DUMMY - IBKR Global', 'IBKR', '9988', 'HKD', 20000, 72, 1440000),
  ('DUMMY - IBKR Global', 'IBKR', '0388', 'HKD', 5240, 210, 1100400)
) AS t(account_name, platform_code, symbol, currency, quantity, avg_cost, market_value_base);

WITH resolved AS (
  SELECT
    h.*,
    acc.id AS account_id,
    ba.id AS broker_account_id,
    ast.id AS asset_id,
    ast.asset_class,
    ast.name AS asset_name
  FROM seed_stock_holdings h
  JOIN accounts acc ON acc.name = h.account_name
  JOIN broker_accounts ba ON ba.legacy_account_id = acc.id
  JOIN broker_connections bc ON bc.id = ba.connection_id AND bc.platform_code = h.platform_code
  JOIN assets ast ON ast.symbol = h.symbol AND ast.quote_currency = h.currency
)
INSERT INTO broker_instruments (
  platform_code, broker_instrument_id, asset_id, symbol, description, security_type, currency, metadata_json
)
SELECT DISTINCT
  platform_code, 'DUMMY:' || symbol || ':' || currency, asset_id, symbol, asset_name, asset_class, currency, '{}'::jsonb
FROM resolved
ON CONFLICT DO NOTHING;

WITH resolved AS (
  SELECT
    h.*,
    acc.id AS account_id,
    ba.id AS broker_account_id
  FROM seed_stock_holdings h
  JOIN accounts acc ON acc.name = h.account_name
  JOIN broker_accounts ba ON ba.legacy_account_id = acc.id
  JOIN broker_connections bc ON bc.id = ba.connection_id AND bc.platform_code = h.platform_code
)
INSERT INTO broker_import_runs (
  broker_account_id, legacy_account_id, platform_code, source_type, import_scope,
  status, report_date_from, report_date_to, metadata_json
)
SELECT DISTINCT
  r.broker_account_id, r.account_id, r.platform_code, 'DUMMY', 'daily', 'completed', sm.as_of_date, sm.as_of_date, '{}'::jsonb
FROM resolved r
CROSS JOIN seed_months sm;

WITH resolved AS (
  SELECT
    h.*,
    acc.id AS account_id,
    ba.id AS broker_account_id,
    bi.id AS broker_instrument_id
  FROM seed_stock_holdings h
  JOIN accounts acc ON acc.name = h.account_name
  JOIN broker_accounts ba ON ba.legacy_account_id = acc.id
  JOIN broker_connections bc ON bc.id = ba.connection_id AND bc.platform_code = h.platform_code
  JOIN broker_instruments bi
    ON bi.platform_code = h.platform_code
   AND bi.broker_instrument_id = 'DUMMY:' || h.symbol || ':' || h.currency
   AND bi.currency = h.currency
)
INSERT INTO portfolio_position_snapshots (
  broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
  quantity, currency, market_price, market_value_local, market_value_base,
  cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json
)
SELECT
  r.broker_account_id,
  r.account_id,
  r.broker_instrument_id,
  bir.id,
  sm.as_of_date,
  r.quantity,
  r.currency,
  r.avg_cost,
  ROUND(r.market_value_base * sm.growth_factor, 2),
  ROUND(r.market_value_base * sm.growth_factor, 2),
  ROUND(r.market_value_base * sm.growth_factor, 2),
  ROUND(r.market_value_base * sm.growth_factor, 2),
  1,
  'authoritative',
  '{}'::jsonb
FROM resolved r
CROSS JOIN seed_months sm
JOIN broker_import_runs bir
  ON bir.broker_account_id = r.broker_account_id
 AND bir.source_type = 'DUMMY'
 AND bir.report_date_to = sm.as_of_date
ON CONFLICT (broker_account_id, report_date, broker_instrument_id, currency)
WHERE authority_status = 'authoritative'
DO UPDATE SET
  quantity = EXCLUDED.quantity,
  market_price = EXCLUDED.market_price,
  market_value_local = EXCLUDED.market_value_local,
  market_value_base = EXCLUDED.market_value_base,
  cost_basis_local = EXCLUDED.cost_basis_local,
  cost_basis_base = EXCLUDED.cost_basis_base,
  fx_rate_to_base = EXCLUDED.fx_rate_to_base,
  metadata_json = EXCLUDED.metadata_json,
  updated_at = NOW();

-- Monthly price history used by dashboard valuation and market-data demos.
WITH v(symbol, currency, price, exchange_code) AS (
  VALUES
    ('SGDMMF', 'SGD', 1.00, 'SGX'),
    ('MSFT', 'USD', 420, 'US'),
    ('GOOGL', 'USD', 170, 'US'),
    ('META', 'USD', 500, 'US'),
    ('AMZN', 'USD', 180, 'US'),
    ('NVDA', 'USD', 120, 'US'),
    ('AAPL', 'USD', 195, 'US'),
    ('TSLA', 'USD', 220, 'US'),
    ('BRK-B', 'USD', 430, 'US'),
    ('XOM', 'USD', 110, 'US'),
    ('CVX', 'USD', 155, 'US'),
    ('COP', 'USD', 115, 'US'),
    ('SLB', 'USD', 50, 'US'),
    ('JPM', 'USD', 200, 'US'),
    ('V', 'USD', 285, 'US'),
    ('MA', 'USD', 480, 'US'),
    ('UNH', 'USD', 500, 'US'),
    ('LLY', 'USD', 780, 'US'),
    ('NVO', 'USD', 130, 'US'),
    ('REGN', 'USD', 980, 'US'),
    ('NFLX', 'USD', 650, 'US'),
    ('ORCL', 'USD', 140, 'US'),
    ('PLTR', 'USD', 30, 'US'),
    ('AVGO', 'USD', 1300, 'US'),
    ('CRM', 'USD', 300, 'US'),
    ('D05', 'SGD', 35, 'SGX'),
    ('U11', 'SGD', 31.5, 'SGX'),
    ('O39', 'SGD', 15, 'SGX'),
    ('S68', 'SGD', 12, 'SGX'),
    ('H02', 'SGD', 12, 'SGX'),
    ('0700', 'HKD', 320, 'HKEX'),
    ('9988', 'HKD', 85, 'HKEX'),
    ('0388', 'HKD', 250, 'HKEX')
)
INSERT INTO prices (asset_id, ts, trade_date, price, currency, exchange_code, provider_symbol, source)
SELECT
  a.id,
  sm.as_of_date::timestamptz,
  sm.as_of_date,
  ROUND(v.price * sm.growth_factor, 6),
  v.currency,
  v.exchange_code,
  v.symbol,
  'DUMMY'
FROM v
JOIN assets a ON a.symbol = v.symbol AND a.quote_currency = v.currency
CROSS JOIN seed_months sm
ON CONFLICT (asset_id, ts, currency, source) DO UPDATE
SET trade_date = EXCLUDED.trade_date,
    price = EXCLUDED.price,
    exchange_code = EXCLUDED.exchange_code,
    provider_symbol = EXCLUDED.provider_symbol;

-- Explicit symbol map to keep refresh deterministic for demo assets.
WITH m(symbol, currency, exchange_code, exchange_symbol, yahoo_override) AS (
  VALUES
    ('MSFT', 'USD', 'US', 'MSFT', NULL),
    ('GOOGL', 'USD', 'US', 'GOOGL', NULL),
    ('META', 'USD', 'US', 'META', NULL),
    ('AMZN', 'USD', 'US', 'AMZN', NULL),
    ('NVDA', 'USD', 'US', 'NVDA', NULL),
    ('AAPL', 'USD', 'US', 'AAPL', NULL),
    ('TSLA', 'USD', 'US', 'TSLA', NULL),
    ('BRK-B', 'USD', 'US', 'BRK-B', 'BRK-B'),
    ('XOM', 'USD', 'US', 'XOM', NULL),
    ('CVX', 'USD', 'US', 'CVX', NULL),
    ('COP', 'USD', 'US', 'COP', NULL),
    ('SLB', 'USD', 'US', 'SLB', NULL),
    ('JPM', 'USD', 'US', 'JPM', NULL),
    ('V', 'USD', 'US', 'V', NULL),
    ('MA', 'USD', 'US', 'MA', NULL),
    ('UNH', 'USD', 'US', 'UNH', NULL),
    ('LLY', 'USD', 'US', 'LLY', NULL),
    ('NVO', 'USD', 'US', 'NVO', NULL),
    ('REGN', 'USD', 'US', 'REGN', NULL),
    ('NFLX', 'USD', 'US', 'NFLX', NULL),
    ('ORCL', 'USD', 'US', 'ORCL', NULL),
    ('PLTR', 'USD', 'US', 'PLTR', NULL),
    ('AVGO', 'USD', 'US', 'AVGO', NULL),
    ('CRM', 'USD', 'US', 'CRM', NULL),
    ('D05', 'SGD', 'SGX', 'D05', 'D05.SI'),
    ('U11', 'SGD', 'SGX', 'U11', 'U11.SI'),
    ('O39', 'SGD', 'SGX', 'O39', 'O39.SI'),
    ('S68', 'SGD', 'SGX', 'S68', 'S68.SI'),
    ('H02', 'SGD', 'SGX', 'H02', 'H02.SI'),
    ('0700', 'HKD', 'HKEX', '0700', '0700.HK'),
    ('9988', 'HKD', 'HKEX', '9988', '9988.HK'),
    ('0388', 'HKD', 'HKEX', '0388', '0388.HK')
)
INSERT INTO market_symbol_map (
  asset_id, exchange_code, exchange_symbol, quote_currency, is_active, yahoo_symbol_override, updated_at
)
SELECT
  a.id, m.exchange_code, m.exchange_symbol, m.currency, TRUE, m.yahoo_override, NOW()
FROM m
JOIN assets a ON a.symbol = m.symbol AND a.quote_currency = m.currency
ON CONFLICT (asset_id, exchange_code) DO UPDATE
SET exchange_symbol = EXCLUDED.exchange_symbol,
    quote_currency = EXCLUDED.quote_currency,
    is_active = TRUE,
    yahoo_symbol_override = EXCLUDED.yahoo_symbol_override,
    updated_at = NOW();

-- Intentionally no hardcoded market_dividend_yields rows:
-- expected-dividend yields are sourced from the normal market data refresh (yfinance path).

-- ═══════════════════════════════════════════════════════════════════
-- Crypto: three wallets across different chains/providers (no real
-- on-chain verification needed for demo), each with a 12-month
-- snapshot history scaled by the same growth curve as the rest of
-- the portfolio.
-- ═══════════════════════════════════════════════════════════════════
DROP TABLE IF EXISTS seed_wallets;
CREATE TEMP TABLE seed_wallets (
  label TEXT PRIMARY KEY,
  chain_type TEXT,
  chain TEXT,
  address TEXT
);
INSERT INTO seed_wallets (label, chain_type, chain, address) VALUES
  ('DUMMY - Ledger (cold)', 'evm', 'ethereum', '0xdE00000000000000000000000000000000000001'),
  ('DUMMY - MetaMask', 'evm', 'arbitrum', '0xdE00000000000000000000000000000000000002'),
  ('DUMMY - Phantom', 'solana', 'solana', '7xKXtg2CW3xxxxxxxxxxxxxxxxxxxxxxxxxxxxF3q1');

WITH demo_user AS (
  SELECT id AS user_id FROM users WHERE LOWER(username) = 'demo' LIMIT 1
)
INSERT INTO crypto_wallets (user_id, chain_type, chain, address, label, status, created_at, verified_at)
SELECT
  demo_user.user_id, w.chain_type, w.chain, w.address, w.label, 'active', NOW(), NOW()
FROM seed_wallets w
CROSS JOIN demo_user;

-- Per-wallet token composition (base USD values at current month baseline)
DROP TABLE IF EXISTS seed_wallet_items;
CREATE TEMP TABLE seed_wallet_items AS
SELECT * FROM (VALUES
  -- Ledger (cold) — Ethereum mainnet: blue-chip majors
  ('DUMMY - Ledger (cold)', 'evm', 'ethereum', 'native', NULL::text, 'ETH', 'Ethereum', 18, 166.6666666667::numeric, 3000::numeric, 500000::numeric),
  ('DUMMY - Ledger (cold)', 'evm', 'ethereum', 'native', NULL, 'BTC', 'Bitcoin (Wrapped)', 8, 1.25, 80000, 100000),
  ('DUMMY - Ledger (cold)', 'evm', 'ethereum', 'erc20', '0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 'USDC', 'USD Coin', 6, 250000, 1, 250000),
  ('DUMMY - Ledger (cold)', 'evm', 'ethereum', 'erc20', '0x514910771AF9Ca656af840dff83E8264EcF986CA', 'LINK', 'Chainlink', 18, 1944.4444444444, 18, 35000),
  ('DUMMY - Ledger (cold)', 'evm', 'ethereum', 'erc20', '0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2', 'MKR', 'Maker', 18, 5.3333333333, 1500, 8000),
  -- MetaMask — Arbitrum: L2-native + DeFi
  ('DUMMY - MetaMask', 'evm', 'arbitrum', 'erc20', '0x912CE59144191C1204E64559FE8253a0e49E6548', 'ARB', 'Arbitrum', 18, 25000, 1, 25000),
  ('DUMMY - MetaMask', 'evm', 'arbitrum', 'erc20', '0x1f9840a85d5af5bf1d1762f925bdaddc4201f984', 'UNI', 'Uniswap', 18, 2666.6666666667, 7.5, 20000),
  ('DUMMY - MetaMask', 'evm', 'arbitrum', 'erc20', '0x7Fc66500c84A76Ad7E9c93437bFc5Ac33E2DDaE9', 'AAVE', 'Aave', 18, 40, 300, 12000),
  ('DUMMY - MetaMask', 'evm', 'arbitrum', 'erc20', '0xaf88d065e77c8cC2239327C5EDb3A432268e5831', 'USDC', 'USD Coin', 6, 60000, 1, 60000),
  -- Phantom — Solana: SOL + memecoin/DeFi flavor
  ('DUMMY - Phantom', 'solana', 'solana', 'native', NULL, 'SOL', 'Solana', 9, 1562.5, 160, 250000),
  ('DUMMY - Phantom', 'solana', 'solana', 'spl', 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'USDC', 'USD Coin', 6, 80000, 1, 80000),
  ('DUMMY - Phantom', 'solana', 'solana', 'spl', 'JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN', 'JUP', 'Jupiter', 6, 100000, 0.85, 85000)
) AS t(wallet_label, chain_type, chain, asset_kind, contract_or_mint, symbol, name, decimals, base_normalized_amount, price_usd, base_value_usd);

WITH snap AS (
  INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd, source_versions)
  SELECT
    w.id,
    sm.as_of_date,
    NOW(),
    ROUND((SELECT SUM(base_value_usd) FROM seed_wallet_items i WHERE i.wallet_label = sw.label) * sm.growth_factor, 2),
    '{}'::jsonb
  FROM seed_wallets sw
  JOIN crypto_wallets w ON w.label = sw.label
  CROSS JOIN seed_months sm
  RETURNING id, wallet_id, as_of_date, total_usd
)
INSERT INTO crypto_wallet_snapshot_items (
  snapshot_id, chain_type, chain, asset_kind, contract_or_mint, symbol, name,
  decimals, raw_amount, normalized_amount, price_usd, value_usd, price_source
)
SELECT
  snap.id,
  i.chain_type,
  i.chain,
  i.asset_kind,
  i.contract_or_mint,
  i.symbol,
  i.name,
  i.decimals,
  ROUND(i.base_normalized_amount * sm.growth_factor)::text,
  ROUND(i.base_normalized_amount * sm.growth_factor, 6),
  i.price_usd,
  ROUND(i.base_value_usd * sm.growth_factor, 2),
  'DUMMY'
FROM seed_wallet_items i
JOIN seed_wallets sw ON sw.label = i.wallet_label
JOIN crypto_wallets w ON w.label = sw.label
JOIN seed_months sm ON TRUE
JOIN snap ON snap.wallet_id = w.id AND snap.as_of_date = sm.as_of_date;

-- ═══════════════════════════════════════════════════════════════════
-- Ingestion job history for Data Hub / Import Statements screens
-- ═══════════════════════════════════════════════════════════════════
WITH a AS (
  SELECT id, name, platform FROM accounts WHERE name LIKE 'DUMMY - %'
)
INSERT INTO import_jobs (
  account_id, platform, original_filename, stored_path, file_sha256, format_signature,
  parser_key, status, report_path, error_message, created_at, updated_at
)
VALUES
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'), 'DBS', 'DUMMY_dbs_savings.csv', '/app/data/uploads/DUMMY_dbs_savings.csv', md5('dummy-dbs'), 'dbs_account_csv_v1', 'dbs_account', 'IMPORTED', '/app/data/reports/DUMMY_dbs_savings.json', NULL, NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - OCBC 360'), 'OCBC', 'DUMMY_ocbc.csv', '/app/data/uploads/DUMMY_ocbc.csv', md5('dummy-ocbc'), 'ocbc_account_csv_v1', 'ocbc_account', 'IMPORTED', '/app/data/reports/DUMMY_ocbc.json', NULL, NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - UOB One'), 'UOB', 'DUMMY_uob.xls', '/app/data/uploads/DUMMY_uob.xls', md5('dummy-uob'), 'uob_account_xls_v1', 'uob_account', 'IMPORTED', '/app/data/reports/DUMMY_uob.json', NULL, NOW() - INTERVAL '16 days', NOW() - INTERVAL '16 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), 'IBKR', 'DUMMY_ibkr.csv', '/app/data/uploads/DUMMY_ibkr.csv', md5('dummy-ibkr'), 'ibkr_csv_v1', 'ibkr', 'IMPORTED', '/app/data/reports/DUMMY_ibkr.json', NULL, NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'DBS', 'DUMMY_dbs_card.csv', '/app/data/uploads/DUMMY_dbs_card.csv', md5('dummy-dbs-card'), 'dbs_card_csv_v1', 'dbs_card', 'IMPORTED', '/app/data/reports/DUMMY_dbs_card.json', NULL, NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - Amex Platinum'), 'AMEX', 'DUMMY_amex_card.csv', '/app/data/uploads/DUMMY_amex_card.csv', md5('dummy-amex-card'), 'amex_card_csv_v1', 'amex_card', 'NEEDS_MAPPING', '/app/data/reports/DUMMY_amex_card.json', 'Some merchants require mapping review', NOW() - INTERVAL '8 days', NOW() - INTERVAL '8 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - Citi Prestige'), 'CITI', 'DUMMY_citi_card.csv', '/app/data/uploads/DUMMY_citi_card.csv', md5('dummy-citi-card'), 'citi_credit_card_csv_v1', 'citi_credit_card', 'IMPORTED', '/app/data/reports/DUMMY_citi_card.json', NULL, NOW() - INTERVAL '6 days', NOW() - INTERVAL '6 days');

-- ═══════════════════════════════════════════════════════════════════
-- Transactions: HNW income + spending streams, repeated every month
-- for 12 months (recurring templates) plus month-varying discretionary
-- spend, so Cash Flow / Liabilities / recurring-charge detection all
-- have real month-over-month history.
-- ═══════════════════════════════════════════════════════════════════

-- Recurring monthly templates (income, household, subscriptions) — identical
-- every month, dated relative to each month's own calendar.
DROP TABLE IF EXISTS seed_recurring_tx;
CREATE TEMP TABLE seed_recurring_tx AS
SELECT * FROM (VALUES
  ('DUMMY - DBS Savings', 'INCOME', 'Salary', 'CapitalOS Pte Ltd', 120000::numeric, 1),
  ('DUMMY - DBS Savings', 'EXPENSE', 'Household', 'Sentosa Cove Estate Management', -15000::numeric, 1),
  ('DUMMY - DBS Savings', 'EXPENSE', 'Education', 'UWC South East Asia', -7000::numeric, 3),
  ('DUMMY - DBS Savings', 'EXPENSE', 'Household', 'Quintessentially Household Staffing', -4500::numeric, 3),
  ('DUMMY - DBS Savings', 'EXPENSE', 'Insurance', 'AIA Private Wealth', -2200::numeric, 5),
  ('DUMMY - UOB Credit Card', 'EXPENSE', 'Utilities', 'Singtel', -180::numeric, 5),
  ('DUMMY - UOB Credit Card', 'EXPENSE', 'Utilities', 'SP Services', -480::numeric, 5),
  ('DUMMY - Amex Platinum', 'EXPENSE', 'Membership', 'Sentosa Golf Club', -1200::numeric, 6),
  ('DUMMY - Citi Prestige', 'EXPENSE', 'Wellness', 'Chi Wellness Spa', -800::numeric, 6),
  ('DUMMY - DBS Credit Card', 'EXPENSE', 'Subscription', 'OpenAI ChatGPT Pro', -270::numeric, 6),
  ('DUMMY - DBS Credit Card', 'EXPENSE', 'Subscription', 'Anthropic Claude Max', -270::numeric, 6),
  ('DUMMY - Amex Platinum', 'EXPENSE', 'Subscription', 'Perplexity Max', -270::numeric, 6),
  ('DUMMY - DBS Credit Card', 'EXPENSE', 'Subscription', 'Cursor Pro', -27::numeric, 6),
  ('DUMMY - Citi Prestige', 'EXPENSE', 'Subscription', 'Google Gemini Ultra', -40::numeric, 6),
  ('DUMMY - UOB Credit Card', 'EXPENSE', 'Subscription', 'Spotify Premium Family', -22::numeric, 6),
  ('DUMMY - Amex Platinum', 'EXPENSE', 'Subscription', 'Apple One Premier', -45::numeric, 6),
  ('DUMMY - UOB Credit Card', 'EXPENSE', 'Subscription', 'Netflix Premium', -23::numeric, 6),
  ('DUMMY - Citi Prestige', 'EXPENSE', 'Subscription', 'Wall Street Journal', -52::numeric, 6),
  ('DUMMY - Citi Prestige', 'EXPENSE', 'Subscription', 'The Economist', -40::numeric, 6),
  ('DUMMY - Amex Platinum', 'EXPENSE', 'Subscription', 'New York Times', -30::numeric, 6),
  ('DUMMY - DBS Credit Card', 'EXPENSE', 'Subscription', 'Bloomberg Digital', -45::numeric, 6),
  ('DUMMY - UOB Credit Card', 'EXPENSE', 'Subscription', 'Peloton Membership', -60::numeric, 6)
) AS t(account_name, tx_type, category, merchant, amount, day_of_month);

-- Discretionary lifestyle spend — varies month to month via discretionary_multiplier
DROP TABLE IF EXISTS seed_discretionary_tx;
CREATE TEMP TABLE seed_discretionary_tx AS
SELECT * FROM (VALUES
  ('DUMMY - DBS Credit Card', 'Travel', 'Singapore Airlines Suites', -4200::numeric, 8),
  ('DUMMY - Amex Platinum', 'Travel', 'Four Seasons Resort', -6500::numeric, 9),
  ('DUMMY - Citi Prestige', 'Dining', 'Odette', -1800::numeric, 6),
  ('DUMMY - DBS Credit Card', 'Dining', 'Les Amis', -1500::numeric, 7),
  ('DUMMY - Amex Platinum', 'Shopping', 'Hermes Boutique', -8500::numeric, 8),
  ('DUMMY - Amex Platinum', 'Experiences', 'Yacht Charter Sentosa', -3500::numeric, 9),
  ('DUMMY - UOB Credit Card', 'Transport', 'Grab Premium', -350::numeric, 4),
  ('DUMMY - DBS Credit Card', 'Groceries', 'Culina Fine Foods', -900::numeric, 4)
) AS t(account_name, category, merchant, base_amount, day_of_month);

-- One-off luxury purchases, each pinned to a specific month for realism
DROP TABLE IF EXISTS seed_oneoff_tx;
CREATE TEMP TABLE seed_oneoff_tx AS
SELECT * FROM (VALUES
  ('DUMMY - Citi Prestige', 2, 'Shopping', 'Rolex Boutique', -22000::numeric, 8),
  ('DUMMY - Citi Prestige', 4, 'Experiences', 'Sothebys Auction House', -35000::numeric, 9),
  ('DUMMY - Amex Platinum', 0, 'Travel', 'NetJets Private Aviation', -18000::numeric, 8),
  ('DUMMY - Amex Platinum', 3, 'Shopping', 'Chanel Boutique', -6200::numeric, 7),
  ('DUMMY - Amex Platinum', 6, 'Travel', 'Aman Tokyo', -12500::numeric, 8),
  ('DUMMY - DBS Credit Card', 8, 'Experiences', 'Singapore Yacht Show', -7800::numeric, 9),
  ('DUMMY - Citi Prestige', 10, 'Shopping', 'Patek Philippe Service Centre', -9800::numeric, 7),
  ('DUMMY - Amex Platinum', 11, 'Travel', 'Six Senses Bhutan', -14500::numeric, 8)
) AS t(account_name, month_offset, category, merchant, amount, day_of_month);

WITH ins_recurring AS (
  INSERT INTO transactions (ts, account_id, type, amount, currency, category, merchant_counterparty, platform_reference, notes, source)
  SELECT
    (sm.month_start + (LEAST(r.day_of_month, sm.day_cap) - 1) * interval '1 day') + interval '9 hour',
    a.id,
    r.tx_type::txn_type,
    r.amount,
    'SGD',
    r.category,
    r.merchant,
    'DUMMY_' || sm.month_offset || '_' || md5(r.account_name || r.merchant),
    'DUMMY_SEED',
    'DUMMY'
  FROM seed_recurring_tx r
  JOIN accounts a ON a.name = r.account_name
  CROSS JOIN seed_months sm
  RETURNING 1
),
ins_discretionary AS (
  INSERT INTO transactions (ts, account_id, type, amount, currency, category, merchant_counterparty, platform_reference, notes, source)
  SELECT
    (sm.month_start + (LEAST(d.day_of_month, sm.day_cap) - 1) * interval '1 day') + interval '19 hour',
    a.id,
    'EXPENSE',
    ROUND(d.base_amount * sm.discretionary_multiplier, 2),
    'SGD',
    d.category,
    d.merchant,
    'DUMMY_DISC_' || sm.month_offset || '_' || md5(d.account_name || d.merchant),
    'DUMMY_SEED',
    'DUMMY'
  FROM seed_discretionary_tx d
  JOIN accounts a ON a.name = d.account_name
  CROSS JOIN seed_months sm
  RETURNING 1
),
ins_oneoff AS (
  INSERT INTO transactions (ts, account_id, type, amount, currency, category, merchant_counterparty, platform_reference, notes, source)
  SELECT
    (sm.month_start + (LEAST(o.day_of_month, sm.day_cap) - 1) * interval '1 day') + interval '15 hour',
    a.id,
    'EXPENSE',
    o.amount,
    'SGD',
    o.category,
    o.merchant,
    'DUMMY_ONEOFF_' || md5(o.account_name || o.merchant),
    'DUMMY_SEED',
    'DUMMY'
  FROM seed_oneoff_tx o
  JOIN accounts a ON a.name = o.account_name
  JOIN seed_months sm ON sm.month_offset = o.month_offset
  RETURNING 1
)
SELECT 1;

-- Transfers: quarterly funding from DBS savings into IBKR across the year.
WITH a AS (SELECT id, name FROM accounts WHERE name LIKE 'DUMMY - %'),
sm AS (SELECT month_offset, month_start FROM seed_months WHERE month_offset IN (0, 3, 6, 9))
INSERT INTO transactions (ts, account_id, type, amount, currency, category, merchant_counterparty, platform_reference, notes, source)
SELECT
  sm.month_start + interval '10 hour',
  (SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'),
  'TRANSFER'::txn_type,
  -120000,
  'SGD',
  'Transfer',
  'IBKR Funding',
  'DUMMY_XFER_IBKR_OUT_' || sm.month_offset,
  'DUMMY_SEED',
  'DUMMY'
FROM sm
UNION ALL
SELECT
  sm.month_start + interval '10 hour 5 minute',
  (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'),
  'TRANSFER'::txn_type,
  90000,
  'USD',
  'Transfer',
  'DBS Funding',
  'DUMMY_XFER_IBKR_IN_' || sm.month_offset,
  'DUMMY_SEED',
  'DUMMY'
FROM sm;

-- Card charges: annual fee, finance charge, and GST, once at the current month —
-- keeps the Credit Card Analytics "charges need attention" banner demonstrable.
WITH a AS (SELECT id, name FROM accounts WHERE name LIKE 'DUMMY - %'),
sm0 AS (SELECT month_start, day_cap FROM seed_months WHERE month_offset = 0)
INSERT INTO transactions (ts, account_id, type, amount, currency, category, merchant_counterparty, platform_reference, notes, source)
VALUES
  ((SELECT month_start FROM sm0) + (LEAST(3, (SELECT day_cap FROM sm0)) - 1) * interval '1 day' + interval '9 hour',
   (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'FEE', -196.20, 'SGD', 'Fees', 'DBS Annual Membership Fee', 'DUMMY_CC_FEE', 'DUMMY_SEED', 'DUMMY'),
  ((SELECT month_start FROM sm0) + (LEAST(2, (SELECT day_cap FROM sm0)) - 1) * interval '1 day' + interval '9 hour',
   (SELECT id FROM a WHERE name = 'DUMMY - Citi Prestige'), 'INTEREST', -114.86, 'SGD', 'Interest', 'Finance charges', 'DUMMY_CC_INTEREST', 'DUMMY_SEED', 'DUMMY'),
  ((SELECT month_start FROM sm0) + (LEAST(2, (SELECT day_cap FROM sm0)) - 1) * interval '1 day' + interval '9 hour 5 minute',
   (SELECT id FROM a WHERE name = 'DUMMY - Citi Prestige'), 'TAX', -10.34, 'SGD', 'Tax', 'GST @ 9%', 'DUMMY_CC_TAX', 'DUMMY_SEED', 'DUMMY');

-- Quarterly investment activity + dividend income across the full year.
WITH a AS (SELECT id, name FROM accounts WHERE name LIKE 'DUMMY - %'),
ast AS (SELECT id, symbol, quote_currency FROM assets),
sm AS (SELECT month_offset, month_start, day_cap FROM seed_months WHERE month_offset IN (0, 3, 6, 9))
INSERT INTO transactions (ts, account_id, type, amount, currency, asset_id, quantity, category, merchant_counterparty, platform_reference, notes, source)
SELECT
  sm.month_start + (LEAST(16, sm.day_cap) - 1) * interval '1 day' + interval '13 hour',
  (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'),
  'BUY'::txn_type,
  -250000,
  'USD',
  (SELECT id FROM ast WHERE symbol = 'MSFT' AND quote_currency = 'USD'),
  600,
  'Investment',
  'NASDAQ',
  'DUMMY_BUY_MSFT_' || sm.month_offset,
  'DUMMY_SEED',
  'DUMMY'
FROM sm
UNION ALL
SELECT
  sm.month_start + (LEAST(20, sm.day_cap) - 1) * interval '1 day' + interval '3 hour',
  (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'),
  'INCOME'::txn_type,
  5200,
  'SGD',
  (SELECT id FROM ast WHERE symbol = 'D05' AND quote_currency = 'SGD'),
  NULL,
  'Dividends',
  'DBS Dividend',
  'DUMMY_DIV_D05_' || sm.month_offset,
  'DUMMY_SEED',
  'DUMMY'
FROM sm;

INSERT INTO transfer_links (from_transaction_id, to_transaction_id)
SELECT out_tx.id, in_tx.id
FROM transactions out_tx
JOIN transactions in_tx
  ON out_tx.platform_reference LIKE 'DUMMY_XFER_IBKR_OUT_%'
 AND in_tx.platform_reference = REPLACE(out_tx.platform_reference, 'DUMMY_XFER_IBKR_OUT_', 'DUMMY_XFER_IBKR_IN_')
ON CONFLICT (from_transaction_id, to_transaction_id) DO NOTHING;

DROP TABLE IF EXISTS seed_months;
DROP TABLE IF EXISTS seed_stock_holdings;
DROP TABLE IF EXISTS seed_wallets;
DROP TABLE IF EXISTS seed_wallet_items;
DROP TABLE IF EXISTS seed_recurring_tx;
DROP TABLE IF EXISTS seed_discretionary_tx;
DROP TABLE IF EXISTS seed_oneoff_tx;

COMMIT;
