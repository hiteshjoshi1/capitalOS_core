-- Migration 055: Canonical portfolio phase 1 - IBKR Flex cutover.
-- Additive schema only. Existing upload-parser tables remain unchanged.

CREATE TABLE IF NOT EXISTS broker_connections (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  platform_code TEXT NOT NULL,
  connection_type TEXT NOT NULL,
  display_name TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_broker_connections_user_platform
  ON broker_connections(user_id, platform_code, status);

CREATE TABLE IF NOT EXISTS broker_accounts (
  id BIGSERIAL PRIMARY KEY,
  connection_id BIGINT NOT NULL REFERENCES broker_connections(id) ON DELETE CASCADE,
  legacy_account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
  broker_account_id TEXT NOT NULL,
  account_alias TEXT,
  base_currency TEXT NOT NULL,
  country TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (connection_id, broker_account_id)
);

CREATE INDEX IF NOT EXISTS idx_broker_accounts_legacy_account
  ON broker_accounts(legacy_account_id);

CREATE TABLE IF NOT EXISTS portfolio_source_authority_windows (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  source_kind TEXT NOT NULL,
  fact_scope TEXT NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  authority_status TEXT NOT NULL DEFAULT 'authoritative',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (broker_account_id, source_kind, fact_scope, effective_from)
);

CREATE INDEX IF NOT EXISTS idx_portfolio_source_authority_active
  ON portfolio_source_authority_windows(broker_account_id, source_kind, fact_scope, effective_from, effective_to);

CREATE TABLE IF NOT EXISTS broker_import_runs (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT REFERENCES broker_accounts(id) ON DELETE SET NULL,
  legacy_account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
  platform_code TEXT NOT NULL,
  source_type TEXT NOT NULL,
  import_scope TEXT NOT NULL DEFAULT 'daily',
  status TEXT NOT NULL,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ,
  parsed_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  report_date_from DATE,
  report_date_to DATE,
  flex_reference_code TEXT,
  raw_document_id BIGINT,
  parser_version TEXT,
  error_code TEXT,
  error_message TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_broker_import_runs_account_status
  ON broker_import_runs(broker_account_id, source_type, status, requested_at DESC);

CREATE TABLE IF NOT EXISTS raw_broker_documents (
  id BIGSERIAL PRIMARY KEY,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  broker_account_id BIGINT REFERENCES broker_accounts(id) ON DELETE SET NULL,
  source_type TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'application/xml',
  report_date_from DATE,
  report_date_to DATE,
  parser_version TEXT NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_broker_documents_hash
  ON raw_broker_documents(content_hash);

CREATE TABLE IF NOT EXISTS broker_instruments (
  id BIGSERIAL PRIMARY KEY,
  platform_code TEXT NOT NULL,
  broker_instrument_id TEXT NOT NULL,
  asset_id BIGINT REFERENCES assets(id) ON DELETE SET NULL,
  symbol TEXT,
  description TEXT,
  security_type TEXT,
  listing_exchange TEXT,
  currency TEXT,
  country TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_broker_instruments_platform_contract
  ON broker_instruments(platform_code, broker_instrument_id, COALESCE(listing_exchange, ''), COALESCE(currency, ''));

CREATE INDEX IF NOT EXISTS idx_broker_instruments_asset
  ON broker_instruments(asset_id);

CREATE TABLE IF NOT EXISTS asset_identifiers (
  id BIGSERIAL PRIMARY KEY,
  asset_id BIGINT REFERENCES assets(id) ON DELETE SET NULL,
  broker_instrument_id BIGINT REFERENCES broker_instruments(id) ON DELETE SET NULL,
  identifier_namespace TEXT NOT NULL,
  identifier_type TEXT NOT NULL,
  identifier_value TEXT NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_asset_identifiers_namespace_value
  ON asset_identifiers(identifier_namespace, identifier_type, identifier_value);

CREATE TABLE IF NOT EXISTS portfolio_position_snapshots (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  legacy_account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
  broker_instrument_id BIGINT NOT NULL REFERENCES broker_instruments(id) ON DELETE RESTRICT,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE NOT NULL,
  quantity NUMERIC(38,18) NOT NULL,
  currency TEXT NOT NULL,
  market_price NUMERIC(38,18),
  market_value_local NUMERIC(38,18) NOT NULL,
  market_value_base NUMERIC(38,18) NOT NULL,
  cost_basis_local NUMERIC(38,18),
  cost_basis_base NUMERIC(38,18),
  fx_rate_to_base NUMERIC(38,18) NOT NULL,
  authority_status TEXT NOT NULL DEFAULT 'authoritative',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_position_snapshots_authoritative
  ON portfolio_position_snapshots(broker_account_id, report_date, broker_instrument_id, currency)
  WHERE authority_status = 'authoritative';

CREATE INDEX IF NOT EXISTS idx_portfolio_position_snapshots_account_date
  ON portfolio_position_snapshots(broker_account_id, report_date DESC);

CREATE TABLE IF NOT EXISTS portfolio_cash_balance_snapshots (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  legacy_account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE NOT NULL,
  currency TEXT NOT NULL,
  cash_balance NUMERIC(38,18) NOT NULL,
  cash_balance_base NUMERIC(38,18) NOT NULL,
  fx_rate_to_base NUMERIC(38,18) NOT NULL,
  authority_status TEXT NOT NULL DEFAULT 'authoritative',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_cash_balance_snapshots_authoritative
  ON portfolio_cash_balance_snapshots(broker_account_id, report_date, currency)
  WHERE authority_status = 'authoritative';

CREATE INDEX IF NOT EXISTS idx_portfolio_cash_balance_snapshots_account_date
  ON portfolio_cash_balance_snapshots(broker_account_id, report_date DESC);

CREATE TABLE IF NOT EXISTS portfolio_nav_snapshots (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  legacy_account_id BIGINT REFERENCES accounts(id) ON DELETE SET NULL,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE NOT NULL,
  base_currency TEXT NOT NULL,
  cash_base NUMERIC(38,18) NOT NULL DEFAULT 0,
  stock_base NUMERIC(38,18) NOT NULL DEFAULT 0,
  options_base NUMERIC(38,18) NOT NULL DEFAULT 0,
  funds_base NUMERIC(38,18) NOT NULL DEFAULT 0,
  bonds_base NUMERIC(38,18) NOT NULL DEFAULT 0,
  interest_accrual_base NUMERIC(38,18) NOT NULL DEFAULT 0,
  dividend_accrual_base NUMERIC(38,18) NOT NULL DEFAULT 0,
  total_nav_base NUMERIC(38,18) NOT NULL,
  authority_status TEXT NOT NULL DEFAULT 'authoritative',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_nav_snapshots_authoritative
  ON portfolio_nav_snapshots(broker_account_id, report_date)
  WHERE authority_status = 'authoritative';

CREATE INDEX IF NOT EXISTS idx_portfolio_nav_snapshots_account_date
  ON portfolio_nav_snapshots(broker_account_id, report_date DESC);

CREATE TABLE IF NOT EXISTS portfolio_report_metrics (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE NOT NULL,
  report_section TEXT NOT NULL,
  metric_code TEXT NOT NULL,
  currency TEXT,
  amount NUMERIC(38,18) NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_report_metrics
  ON portfolio_report_metrics(broker_account_id, report_date, report_section, metric_code, COALESCE(currency, ''));

CREATE TABLE IF NOT EXISTS portfolio_fx_rates (
  id BIGSERIAL PRIMARY KEY,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE NOT NULL,
  from_currency TEXT NOT NULL,
  to_currency TEXT NOT NULL,
  rate NUMERIC(38,18) NOT NULL,
  source_platform TEXT NOT NULL DEFAULT 'IBKR',
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (report_date, from_currency, to_currency, source_platform)
);

CREATE TABLE IF NOT EXISTS portfolio_reconciliations (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE NOT NULL,
  reconciliation_type TEXT NOT NULL,
  expected_amount NUMERIC(38,18) NOT NULL,
  actual_amount NUMERIC(38,18) NOT NULL,
  difference_amount NUMERIC(38,18) NOT NULL,
  tolerance_amount NUMERIC(38,18) NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_reconciliations_run_type_date
  ON portfolio_reconciliations(import_run_id, report_date, reconciliation_type);

CREATE TABLE IF NOT EXISTS portfolio_data_quality_events (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT REFERENCES broker_accounts(id) ON DELETE CASCADE,
  import_run_id BIGINT REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE,
  severity TEXT NOT NULL,
  event_code TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_portfolio_data_quality_events_run
  ON portfolio_data_quality_events(import_run_id, severity, event_code);

CREATE TABLE IF NOT EXISTS portfolio_data_completeness (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  report_date DATE NOT NULL,
  fact_scope TEXT NOT NULL,
  completeness_status TEXT NOT NULL,
  missing_reason TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (broker_account_id, report_date, fact_scope)
);

CREATE TABLE IF NOT EXISTS portfolio_event_groups (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  event_date DATE NOT NULL,
  event_type TEXT NOT NULL,
  broker_event_id TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_event_groups_broker_event
  ON portfolio_event_groups(broker_account_id, event_date, event_type, COALESCE(broker_event_id, ''));

CREATE TABLE IF NOT EXISTS portfolio_trades (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  broker_instrument_id BIGINT REFERENCES broker_instruments(id) ON DELETE SET NULL,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  event_group_id BIGINT REFERENCES portfolio_event_groups(id) ON DELETE SET NULL,
  trade_date DATE NOT NULL,
  settle_date DATE,
  side TEXT,
  quantity NUMERIC(38,18),
  price NUMERIC(38,18),
  proceeds NUMERIC(38,18),
  commission NUMERIC(38,18),
  currency TEXT,
  broker_execution_id TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_trades_execution
  ON portfolio_trades(broker_account_id, COALESCE(broker_execution_id, ''))
  WHERE broker_execution_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS portfolio_cash_ledger_entries (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  event_group_id BIGINT REFERENCES portfolio_event_groups(id) ON DELETE SET NULL,
  activity_date DATE NOT NULL,
  currency TEXT NOT NULL,
  amount NUMERIC(38,18) NOT NULL,
  activity_code TEXT,
  description TEXT,
  broker_activity_id TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_cash_ledger_activity
  ON portfolio_cash_ledger_entries(broker_account_id, activity_date, currency, amount, COALESCE(activity_code, ''), COALESCE(broker_activity_id, ''), COALESCE(description, ''));

CREATE TABLE IF NOT EXISTS portfolio_corporate_action_events (
  id BIGSERIAL PRIMARY KEY,
  broker_account_id BIGINT NOT NULL REFERENCES broker_accounts(id) ON DELETE CASCADE,
  broker_instrument_id BIGINT REFERENCES broker_instruments(id) ON DELETE SET NULL,
  import_run_id BIGINT NOT NULL REFERENCES broker_import_runs(id) ON DELETE CASCADE,
  raw_document_id BIGINT REFERENCES raw_broker_documents(id) ON DELETE SET NULL,
  event_group_id BIGINT REFERENCES portfolio_event_groups(id) ON DELETE SET NULL,
  action_date DATE NOT NULL,
  action_type TEXT,
  quantity NUMERIC(38,18),
  cash_amount NUMERIC(38,18),
  currency TEXT,
  broker_action_id TEXT,
  metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_corporate_actions_broker_action
  ON portfolio_corporate_action_events(broker_account_id, COALESCE(broker_action_id, ''))
  WHERE broker_action_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS portfolio_import_locks (
  broker_account_id BIGINT PRIMARY KEY REFERENCES broker_accounts(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL,
  lock_owner TEXT NOT NULL,
  locked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
