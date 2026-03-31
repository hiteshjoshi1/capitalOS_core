-- Rich demo data seed for user "demo" (idempotent)
-- Goal: broad portfolio + spending + crypto + ingest coverage for UI demos
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
DELETE FROM accounts WHERE name LIKE 'DUMMY - %';
DELETE FROM transactions WHERE source = 'DUMMY';
DELETE FROM prices WHERE source = 'DUMMY';
DELETE FROM market_dividend_yields WHERE source = 'DUMMY';
DELETE FROM import_jobs WHERE original_filename LIKE 'DUMMY_%';

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

-- Accounts owned by demo user
WITH demo_user AS (
  SELECT id AS user_id FROM users WHERE LOWER(username) = 'demo' LIMIT 1
),
p AS (
  SELECT id, code FROM platforms WHERE code IN ('DBS', 'OCBC', 'UOB', 'IBKR', 'DBS_VICKERS')
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
  ('DUMMY - UOB Credit Card', 'UOB', (SELECT user_id FROM demo_user), 'CREDIT_CARD', 'SGD', 'SG', (SELECT id FROM p WHERE code = 'UOB'));

INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day)
VALUES
  ((SELECT id FROM accounts WHERE name = 'DUMMY - DBS Credit Card'), 'DBS Vantage', 'DBS', 120000, 20, 25),
  ((SELECT id FROM accounts WHERE name = 'DUMMY - UOB Credit Card'), 'UOB Reserve', 'UOB', 100000, 10, 18)
ON CONFLICT (account_id) DO NOTHING;

-- Portfolio snapshot at month anchor day (2026-03-06)
WITH a AS (
  SELECT id, name FROM accounts WHERE name LIKE 'DUMMY - %'
),
ast AS (
  SELECT id, symbol, quote_currency FROM assets
)
INSERT INTO positions (account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base)
VALUES
  -- Cash ~ 2M equivalent across 3 banks + IBKR
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'), (SELECT id FROM ast WHERE symbol = 'SGD' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 1, 1, 400000),
  ((SELECT id FROM a WHERE name = 'DUMMY - OCBC 360'), (SELECT id FROM ast WHERE symbol = 'SGD' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 1, 1, 350000),
  ((SELECT id FROM a WHERE name = 'DUMMY - UOB One'), (SELECT id FROM ast WHERE symbol = 'SGD' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 1, 1, 300000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'USD' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 1, 1, 700000),
  -- Money market fund
  ((SELECT id FROM a WHERE name = 'DUMMY - SG Money Market Fund'), (SELECT id FROM ast WHERE symbol = 'SGDMMF' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 300000, 1, 300000),

  -- US equities (conservative, equity-heavy; Mag7 + pharma overweight)
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'MSFT' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 700, 360, 252000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'GOOGL' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 1400, 150, 210000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'META' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 500, 430, 215000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'AMZN' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 1200, 160, 192000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'NVDA' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 1800, 110, 198000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'AAPL' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 1300, 170, 221000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'TSLA' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 700, 200, 140000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'BRK-B' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 256, 390, 99840),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'XOM' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 773, 95, 73435),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'CVX' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 516, 135, 69660),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'COP' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 609, 100, 60900),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'SLB' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 900, 42, 37800),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'JPM' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 500, 175, 87500),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'V' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 333, 250, 83250),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'MA' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 177, 430, 76110),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'UNH' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 180, 430, 77400),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'LLY' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 280, 700, 196000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'NVO' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 1900, 105, 199500),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'REGN' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 250, 860, 215000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'NFLX' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 123, 560, 68880),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'ORCL' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 500, 120, 60000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'PLTR' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 1500, 24, 36000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'AVGO' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 73, 1200, 87600),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = 'CRM' AND quote_currency = 'USD'), '2026-03-06T00:00:00Z', 317, 260, 82420),

  -- Singapore equities (5)
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Vickers SGX'), (SELECT id FROM ast WHERE symbol = 'D05' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 18000, 31, 558000),
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Vickers SGX'), (SELECT id FROM ast WHERE symbol = 'U11' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 12000, 27, 324000),
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Vickers SGX'), (SELECT id FROM ast WHERE symbol = 'O39' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 22000, 13, 286000),
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Vickers SGX'), (SELECT id FROM ast WHERE symbol = 'S68' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 15000, 10, 150000),
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Vickers SGX'), (SELECT id FROM ast WHERE symbol = 'H02' AND quote_currency = 'SGD'), '2026-03-06T00:00:00Z', 20000, 10.5, 210000),

  -- Hong Kong equities (3)
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = '0700' AND quote_currency = 'HKD'), '2026-03-06T00:00:00Z', 7500, 280, 2100000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = '9988' AND quote_currency = 'HKD'), '2026-03-06T00:00:00Z', 20000, 72, 1440000),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), (SELECT id FROM ast WHERE symbol = '0388' AND quote_currency = 'HKD'), '2026-03-06T00:00:00Z', 5240, 210, 1100400)
ON CONFLICT (account_id, asset_id, as_of) DO UPDATE
SET quantity = EXCLUDED.quantity,
    avg_cost = EXCLUDED.avg_cost,
    cost_basis_base = EXCLUDED.cost_basis_base;

-- Latest prices used by dashboard valuation
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
  '2026-03-06T00:00:00Z'::timestamptz,
  '2026-03-06'::date,
  v.price,
  v.currency,
  v.exchange_code,
  v.symbol,
  'DUMMY'
FROM v
JOIN assets a ON a.symbol = v.symbol AND a.quote_currency = v.currency
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
  asset_id,
  exchange_code,
  exchange_symbol,
  quote_currency,
  is_active,
  yahoo_symbol_override,
  updated_at
)
SELECT
  a.id,
  m.exchange_code,
  m.exchange_symbol,
  m.currency,
  TRUE,
  m.yahoo_override,
  NOW()
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

-- Fake crypto wallet + snapshot (no on-chain verification required for demo)
WITH demo_user AS (
  SELECT id AS user_id FROM users WHERE LOWER(username) = 'demo' LIMIT 1
),
wallet AS (
  INSERT INTO crypto_wallets (user_id, chain_type, chain, address, label, status, created_at, verified_at)
  VALUES (
    (SELECT user_id FROM demo_user),
    'evm',
    'ethereum',
    '0xdE00000000000000000000000000000000000001',
    'DUMMY - Demo Main Wallet',
    'active',
    NOW(),
    NOW()
  )
  RETURNING id
),
snap AS (
  INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd, source_versions)
  VALUES ((SELECT id FROM wallet), '2026-03-06', NOW(), 1200000, '{}'::jsonb)
  RETURNING id
)
INSERT INTO crypto_wallet_snapshot_items (
  snapshot_id,
  chain_type,
  chain,
  asset_kind,
  contract_or_mint,
  symbol,
  name,
  decimals,
  raw_amount,
  normalized_amount,
  price_usd,
  value_usd,
  price_source
)
VALUES
  ((SELECT id FROM snap), 'evm', 'ethereum', 'native', NULL, 'ETH', 'Ethereum', 18, '166666666666666666667', 166.6666666667, 3000, 500000, 'DUMMY'),
  ((SELECT id FROM snap), 'solana', 'solana', 'native', NULL, 'SOL', 'Solana', 9, '1562500000000', 1562.5, 160, 250000, 'DUMMY'),
  ((SELECT id FROM snap), 'evm', 'ethereum', 'erc20', '0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 'USDC', 'USD Coin', 6, '250000000000', 250000, 1, 250000, 'DUMMY'),
  ((SELECT id FROM snap), 'evm', 'ethereum', 'native', NULL, 'BTC', 'Bitcoin', 8, '125000000', 1.25, 80000, 100000, 'DUMMY'),
  ((SELECT id FROM snap), 'evm', 'ethereum', 'erc20', '0x514910771AF9Ca656af840dff83E8264EcF986CA', 'LINK', 'Chainlink', 18, '1944444444444444444444', 1944.4444444444, 18, 35000, 'DUMMY'),
  ((SELECT id FROM snap), 'evm', 'arbitrum', 'erc20', '0x912CE59144191C1204E64559FE8253a0e49E6548', 'ARB', 'Arbitrum', 18, '25000000000000000000000', 25000, 1, 25000, 'DUMMY'),
  ((SELECT id FROM snap), 'evm', 'ethereum', 'erc20', '0x1f9840a85d5af5bf1d1762f925bdaddc4201f984', 'UNI', 'Uniswap', 18, '2666666666666666666667', 2666.6666666667, 7.5, 20000, 'DUMMY'),
  ((SELECT id FROM snap), 'evm', 'ethereum', 'erc20', '0x7Fc66500c84A76Ad7E9c93437bFc5Ac33E2DDaE9', 'AAVE', 'Aave', 18, '40000000000000000000', 40, 300, 12000, 'DUMMY'),
  ((SELECT id FROM snap), 'evm', 'ethereum', 'erc20', '0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2', 'MKR', 'Maker', 18, '5333333333333333333', 5.3333333333, 1500, 8000, 'DUMMY');

-- Ingestion job history for Operations/Ingest screens
WITH a AS (
  SELECT id, name, platform FROM accounts WHERE name LIKE 'DUMMY - %'
)
INSERT INTO import_jobs (
  account_id,
  platform,
  original_filename,
  stored_path,
  file_sha256,
  format_signature,
  parser_key,
  status,
  report_path,
  error_message,
  created_at,
  updated_at
)
VALUES
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'), 'DBS', 'DUMMY_dbs_savings_2026_03.csv', '/app/data/uploads/DUMMY_dbs_savings_2026_03.csv', md5('dummy-dbs-2026-03'), 'dbs_account_csv_v1', 'dbs_account', 'IMPORTED', '/app/data/reports/DUMMY_dbs_savings_2026_03.json', NULL, NOW() - INTERVAL '20 days', NOW() - INTERVAL '20 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - OCBC 360'), 'OCBC', 'DUMMY_ocbc_2026_03.csv', '/app/data/uploads/DUMMY_ocbc_2026_03.csv', md5('dummy-ocbc-2026-03'), 'ocbc_account_csv_v1', 'ocbc_account', 'IMPORTED', '/app/data/reports/DUMMY_ocbc_2026_03.json', NULL, NOW() - INTERVAL '18 days', NOW() - INTERVAL '18 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - UOB One'), 'UOB', 'DUMMY_uob_2026_03.xls', '/app/data/uploads/DUMMY_uob_2026_03.xls', md5('dummy-uob-2026-03'), 'uob_account_xls_v1', 'uob_account', 'IMPORTED', '/app/data/reports/DUMMY_uob_2026_03.json', NULL, NOW() - INTERVAL '16 days', NOW() - INTERVAL '16 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), 'IBKR', 'DUMMY_ibkr_2026_03.csv', '/app/data/uploads/DUMMY_ibkr_2026_03.csv', md5('dummy-ibkr-2026-03'), 'ibkr_csv_v1', 'ibkr', 'IMPORTED', '/app/data/reports/DUMMY_ibkr_2026_03.json', NULL, NOW() - INTERVAL '14 days', NOW() - INTERVAL '14 days'),
  ((SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'DBS', 'DUMMY_dbs_card_2026_03.csv', '/app/data/uploads/DUMMY_dbs_card_2026_03.csv', md5('dummy-dbs-card-2026-03'), 'dbs_card_csv_v1', 'dbs_card', 'NEEDS_MAPPING', '/app/data/reports/DUMMY_dbs_card_2026_03.json', 'Some merchants require mapping review', NOW() - INTERVAL '10 days', NOW() - INTERVAL '10 days');

-- Cashflow + spending profile (March 2026): ~15k spend, higher travel/food/experiences
WITH a AS (
  SELECT id, name FROM accounts WHERE name LIKE 'DUMMY - %'
),
ast AS (
  SELECT id, symbol, quote_currency FROM assets
)
INSERT INTO transactions (
  ts,
  account_id,
  type,
  amount,
  currency,
  asset_id,
  quantity,
  category,
  merchant_counterparty,
  platform_reference,
  notes,
  source
)
VALUES
  -- income
  ('2026-03-01T09:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'), 'INCOME', 120000, 'SGD', NULL, NULL, 'Salary', 'CapitalOS Pte Ltd', 'DUMMY_SALARY_202603', 'DUMMY_SEED', 'DUMMY'),

  -- transfers
  ('2026-03-02T10:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'), 'TRANSFER', -120000, 'SGD', NULL, NULL, 'Transfer', 'IBKR Funding', 'DUMMY_XFER_IBKR_OUT', 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-02T10:05:00Z', (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), 'TRANSFER', 90000, 'USD', NULL, NULL, 'Transfer', 'DBS Funding', 'DUMMY_XFER_IBKR_IN', 'DUMMY_SEED', 'DUMMY'),

  -- card-heavy spending (15k total across lifestyle categories, plus recurring subscriptions/utilities)
  ('2026-03-03T11:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -3000, 'SGD', NULL, NULL, 'Travel', 'Singapore Airlines', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-04T12:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -2800, 'SGD', NULL, NULL, 'Travel', 'Marina Bay Hotel', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-05T19:30:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -1800, 'SGD', NULL, NULL, 'Dining', 'Odette', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-06T20:10:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -974, 'SGD', NULL, NULL, 'Experiences', 'Grand Prix Hospitality', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-07T14:10:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -1000, 'SGD', NULL, NULL, 'Experiences', 'Universal Studios Singapore', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-08T08:45:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -900, 'SGD', NULL, NULL, 'Food', 'Wei Dao Pte Ltd', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-09T16:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -700, 'SGD', NULL, NULL, 'Shopping', 'ION Orchard', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-10T09:30:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -600, 'SGD', NULL, NULL, 'Transport', 'Grab', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T06:50:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -300, 'SGD', NULL, NULL, 'Gym', 'Fitness First', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T08:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -45, 'SGD', NULL, NULL, 'Subscription', 'OpenAI ChatGPT Plus', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T08:10:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -35, 'SGD', NULL, NULL, 'Subscription', 'Anthropic Claude', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T08:20:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -30, 'SGD', NULL, NULL, 'Subscription', 'Google Gemini Advanced', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T08:30:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -28, 'SGD', NULL, NULL, 'Subscription', 'Perplexity Pro', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T08:40:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -20, 'SGD', NULL, NULL, 'Subscription', 'Cursor Pro', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T08:50:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -120, 'SGD', NULL, NULL, 'Utilities', 'Singtel', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T09:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -180, 'SGD', NULL, NULL, 'Utilities', 'SP Services', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T09:10:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -16, 'SGD', NULL, NULL, 'Subscription', 'Spotify', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-12T09:20:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -52, 'SGD', NULL, NULL, 'Subscription', 'Wall Street Journal', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-14T08:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'), 'EXPENSE', -1700, 'SGD', NULL, NULL, 'Rent', 'Landlord', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-15T08:05:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Savings'), 'EXPENSE', -700, 'SGD', NULL, NULL, 'School Fees', 'School', NULL, 'DUMMY_SEED', 'DUMMY'),

  -- recurring subscriptions/utilities in prior month (for recurring-payments detection)
  ('2026-02-12T08:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -45, 'SGD', NULL, NULL, 'Subscription', 'OpenAI ChatGPT Plus', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T08:10:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -35, 'SGD', NULL, NULL, 'Subscription', 'Anthropic Claude', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T08:20:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -30, 'SGD', NULL, NULL, 'Subscription', 'Google Gemini Advanced', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T08:30:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -28, 'SGD', NULL, NULL, 'Subscription', 'Perplexity Pro', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T08:40:00Z', (SELECT id FROM a WHERE name = 'DUMMY - DBS Credit Card'), 'EXPENSE', -20, 'SGD', NULL, NULL, 'Subscription', 'Cursor Pro', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T08:50:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -120, 'SGD', NULL, NULL, 'Utilities', 'Singtel', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T09:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -180, 'SGD', NULL, NULL, 'Utilities', 'SP Services', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T09:10:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -16, 'SGD', NULL, NULL, 'Subscription', 'Spotify', NULL, 'DUMMY_SEED', 'DUMMY'),
  ('2026-02-12T09:20:00Z', (SELECT id FROM a WHERE name = 'DUMMY - UOB Credit Card'), 'EXPENSE', -52, 'SGD', NULL, NULL, 'Subscription', 'Wall Street Journal', NULL, 'DUMMY_SEED', 'DUMMY'),

  -- investment activity
  ('2026-03-16T13:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), 'BUY', -250000, 'USD', (SELECT id FROM ast WHERE symbol = 'MSFT' AND quote_currency = 'USD'), 600, 'Investment', 'NASDAQ', 'DUMMY_BUY_MSFT_202603', 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-18T14:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), 'BUY', -180000, 'USD', (SELECT id FROM ast WHERE symbol = 'GOOGL' AND quote_currency = 'USD'), 1050, 'Investment', 'NASDAQ', 'DUMMY_BUY_GOOGL_202603', 'DUMMY_SEED', 'DUMMY'),
  ('2026-03-20T15:30:00Z', (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), 'SELL', 50000, 'USD', (SELECT id FROM ast WHERE symbol = 'NVDA' AND quote_currency = 'USD'), 420, 'Investment', 'NASDAQ', 'DUMMY_SELL_NVDA_202603', 'DUMMY_SEED', 'DUMMY'),

  -- realized dividend sample
  ('2026-03-21T03:00:00Z', (SELECT id FROM a WHERE name = 'DUMMY - IBKR Global'), 'INCOME', 5200, 'SGD', (SELECT id FROM ast WHERE symbol = 'D05' AND quote_currency = 'SGD'), NULL, 'Dividends', 'DBS Dividend', 'DUMMY_DIV_D05_202603', 'DUMMY_SEED', 'DUMMY');

INSERT INTO transfer_links (from_transaction_id, to_transaction_id)
SELECT
  out_tx.id,
  in_tx.id
FROM transactions out_tx
JOIN transactions in_tx
  ON out_tx.platform_reference = 'DUMMY_XFER_IBKR_OUT'
 AND in_tx.platform_reference = 'DUMMY_XFER_IBKR_IN'
ON CONFLICT (from_transaction_id, to_transaction_id) DO NOTHING;

COMMIT;
