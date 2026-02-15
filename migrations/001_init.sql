-- =========
-- Enums
-- =========
DO $$ BEGIN
  CREATE TYPE account_type AS ENUM ('BANK','BROKER','EXCHANGE','WALLET','CREDIT_CARD','LOAN');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE txn_type AS ENUM ('INCOME','EXPENSE','TRANSFER','BUY','SELL','FEE','TAX','INTEREST');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
  CREATE TYPE asset_class AS ENUM ('CASH','STOCK','FUND','CRYPTO','BOND','OTHER');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- =========
-- Tables
-- =========
CREATE TABLE IF NOT EXISTS accounts (
  id           BIGSERIAL PRIMARY KEY,
  name         TEXT NOT NULL,
  platform     TEXT NOT NULL, -- IBKR, DBS, Coinbase, Wallet, etc.
  account_type account_type NOT NULL,
  currency     TEXT NOT NULL,
  country      TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assets (
  id            BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL,
  name          TEXT,
  asset_class   asset_class NOT NULL,
  quote_currency TEXT NOT NULL,
  home_country  TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(symbol, quote_currency)
);

CREATE TABLE IF NOT EXISTS positions (
  id              BIGSERIAL PRIMARY KEY,
  account_id      BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  asset_id        BIGINT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  as_of           TIMESTAMPTZ NOT NULL,
  quantity        NUMERIC(38, 18) NOT NULL DEFAULT 0,
  avg_cost        NUMERIC(38, 18),
  cost_basis_base NUMERIC(38, 18),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(account_id, asset_id, as_of)
);

CREATE TABLE IF NOT EXISTS transactions (
  id                    BIGSERIAL PRIMARY KEY,
  ts                    TIMESTAMPTZ NOT NULL,
  account_id            BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  type                  txn_type NOT NULL,
  amount                NUMERIC(38, 18) NOT NULL, -- +in, -out
  currency              TEXT NOT NULL,
  asset_id              BIGINT REFERENCES assets(id),
  quantity              NUMERIC(38, 18),
  category              TEXT,
  merchant_counterparty TEXT,
  platform_reference    TEXT,
  notes                 TEXT,
  source                TEXT NOT NULL DEFAULT 'MANUAL',
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS transfer_links (
  id                  BIGSERIAL PRIMARY KEY,
  from_transaction_id BIGINT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  to_transaction_id   BIGINT NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(from_transaction_id, to_transaction_id)
);

CREATE TABLE IF NOT EXISTS prices (
  id        BIGSERIAL PRIMARY KEY,
  asset_id  BIGINT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  ts        TIMESTAMPTZ NOT NULL,
  price     NUMERIC(38, 18) NOT NULL,
  currency  TEXT NOT NULL,
  source    TEXT NOT NULL DEFAULT 'MANUAL',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(asset_id, ts, currency, source)
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id            BIGSERIAL PRIMARY KEY,
  source        TEXT NOT NULL,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at   TIMESTAMPTZ,
  status        TEXT NOT NULL DEFAULT 'RUNNING',
  records       INTEGER NOT NULL DEFAULT 0,
  errors        INTEGER NOT NULL DEFAULT 0,
  error_summary TEXT
);

CREATE TABLE IF NOT EXISTS raw_files (
  id              BIGSERIAL PRIMARY KEY,
  ingestion_job_id BIGINT REFERENCES ingestion_jobs(id) ON DELETE SET NULL,
  filename        TEXT NOT NULL,
  content_type    TEXT,
  byte_size       BIGINT,
  sha256          TEXT,
  stored_path     TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_transactions_ts ON transactions(ts);
CREATE INDEX IF NOT EXISTS idx_transactions_account_ts ON transactions(account_id, ts);
CREATE INDEX IF NOT EXISTS idx_prices_asset_ts ON prices(asset_id, ts);
