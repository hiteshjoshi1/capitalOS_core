-- Migration 056: Canonical account balance snapshot table (Phase 4).
-- Additive schema only. No data migration. No breaking changes.
--
-- account_balance_snapshots is the canonical, account-level storage for
-- non-security balances: cash, bank balances, broker cash, stablecoin cash, etc.
--
-- Design rationale:
--   - positions(asset_class='CASH') is a legacy projection. New cash facts must
--     go here instead, so the portfolio read layer can consume a single canonical
--     cash abstraction without special legacy fallbacks.
--   - References accounts(id) directly so bank accounts are not forced into
--     broker_accounts just to reuse broker-specific tables.
--   - broker_account_id is nullable for non-broker sources (bank parsers, etc.)
--   - import_job_id tracks upload lineage for bank/card/account parsers.
--   - broker_import_run_id tracks canonical broker import lineage (Flex, API).
--   - authority_status semantics match portfolio_position_snapshots:
--       'authoritative' | 'reference' | 'superseded'
--   - source_kind values: upload_parser | flex | backfill | manual_adjustment
--   - balance_type values:
--       cash | broker_cash | bank_cash | credit_balance |
--       loan_balance | stablecoin_cash
--   - Natural-key uniqueness for authoritative rows:
--       (account_id, as_of_date, currency, balance_type)
--       WHERE authority_status = 'authoritative'

CREATE TABLE IF NOT EXISTS account_balance_snapshots (
  id                   BIGSERIAL PRIMARY KEY,
  account_id           BIGINT    NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  broker_account_id    BIGINT    REFERENCES broker_accounts(id) ON DELETE SET NULL,
  import_job_id        BIGINT    REFERENCES import_jobs(id) ON DELETE SET NULL,
  broker_import_run_id BIGINT    REFERENCES broker_import_runs(id) ON DELETE SET NULL,
  raw_document_id      BIGINT    REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  as_of_date           DATE      NOT NULL,
  currency             TEXT      NOT NULL,
  balance_type         TEXT      NOT NULL DEFAULT 'cash',
  balance_local        NUMERIC(38,18) NOT NULL,
  balance_base         NUMERIC(38,18) NOT NULL,
  fx_rate_to_base      NUMERIC(38,18) NOT NULL DEFAULT 1,
  authority_status     TEXT      NOT NULL DEFAULT 'authoritative',
  source_kind          TEXT      NOT NULL,
  source_row_hash      TEXT,
  metadata_json        JSONB     NOT NULL DEFAULT '{}'::jsonb,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Natural-key uniqueness for authoritative rows.
-- Only one authoritative balance per (account, date, currency, type).
CREATE UNIQUE INDEX IF NOT EXISTS uq_account_balance_snapshots_authoritative
  ON account_balance_snapshots(account_id, as_of_date, currency, balance_type)
  WHERE authority_status = 'authoritative';

-- Primary access pattern: look up all balances for an account up to a date.
CREATE INDEX IF NOT EXISTS idx_account_balance_snapshots_account_date
  ON account_balance_snapshots(account_id, as_of_date DESC);

-- Broker-account scoped access (when promoting broker cash to this abstraction).
CREATE INDEX IF NOT EXISTS idx_account_balance_snapshots_broker_account
  ON account_balance_snapshots(broker_account_id, as_of_date DESC)
  WHERE broker_account_id IS NOT NULL;
