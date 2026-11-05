-- DB guardrails (#158; #130 findings 1.8 and 1.11). Schema only: no row is changed.
--
-- 1.8, ON DELETE. Deleting an import run, a raw statement or an account used to take
-- evidence with it (facts and raw documents CASCADE from their run) or silently unlink
-- it (SET NULL from facts to their raw document and their legacy account). These are
-- now RESTRICT: a run, raw document or account that rows still point at can't be
-- deleted; whoever deletes one deletes (or moves) its rows first, explicitly. The app
-- never deletes runs, raw documents or accounts: removing an upload (#180) deletes the
-- upload's facts and keeps its run (status 'removed') and raw document; an IBKR Flex
-- re-import deletes facts by date. Unchanged: broker_account_id CASCADEs (a broker
-- account's facts go with it; nothing deletes one), accounts -> transactions /
-- import_jobs / balances CASCADE, and the users / crypto / market-data FKs.
--
-- 1.11, CHECK constraints on enum-like TEXT columns. The allowed values are the ones
-- the code writes (see migrations/README.md and tests/test_db_guardrails.py, which ties
-- them to the code's constants), plus 'DUMMY' where migrations/seed_dummy.sql writes it.
-- Each is added NOT VALID (no scan while the lock is held) and then validated, so the
-- migration fails, and rolls back, if any existing row breaks one. Before applying this
-- to a database with data, run the read-only `make db-constraint-check` (it lists the
-- rows each pending constraint would reject).
--
-- The foreign keys keep their names; each is re-created NOT VALID and validated (the
-- existing rows already satisfy it).

-- 1. Facts and raw documents -> their import run: RESTRICT (was CASCADE; SET NULL for
--    account_balance_snapshots.broker_import_run_id).
ALTER TABLE portfolio_position_snapshots DROP CONSTRAINT portfolio_position_snapshots_import_run_id_fkey;
ALTER TABLE portfolio_position_snapshots ADD CONSTRAINT portfolio_position_snapshots_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_position_snapshots VALIDATE CONSTRAINT portfolio_position_snapshots_import_run_id_fkey;

ALTER TABLE portfolio_cash_balance_snapshots DROP CONSTRAINT portfolio_cash_balance_snapshots_import_run_id_fkey;
ALTER TABLE portfolio_cash_balance_snapshots ADD CONSTRAINT portfolio_cash_balance_snapshots_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_cash_balance_snapshots VALIDATE CONSTRAINT portfolio_cash_balance_snapshots_import_run_id_fkey;

ALTER TABLE portfolio_nav_snapshots DROP CONSTRAINT portfolio_nav_snapshots_import_run_id_fkey;
ALTER TABLE portfolio_nav_snapshots ADD CONSTRAINT portfolio_nav_snapshots_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_nav_snapshots VALIDATE CONSTRAINT portfolio_nav_snapshots_import_run_id_fkey;

ALTER TABLE portfolio_cash_ledger_entries DROP CONSTRAINT portfolio_cash_ledger_entries_import_run_id_fkey;
ALTER TABLE portfolio_cash_ledger_entries ADD CONSTRAINT portfolio_cash_ledger_entries_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_cash_ledger_entries VALIDATE CONSTRAINT portfolio_cash_ledger_entries_import_run_id_fkey;

ALTER TABLE portfolio_trades DROP CONSTRAINT portfolio_trades_import_run_id_fkey;
ALTER TABLE portfolio_trades ADD CONSTRAINT portfolio_trades_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_trades VALIDATE CONSTRAINT portfolio_trades_import_run_id_fkey;

ALTER TABLE portfolio_corporate_action_events DROP CONSTRAINT portfolio_corporate_action_events_import_run_id_fkey;
ALTER TABLE portfolio_corporate_action_events ADD CONSTRAINT portfolio_corporate_action_events_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_corporate_action_events VALIDATE CONSTRAINT portfolio_corporate_action_events_import_run_id_fkey;

ALTER TABLE portfolio_fx_rates DROP CONSTRAINT portfolio_fx_rates_import_run_id_fkey;
ALTER TABLE portfolio_fx_rates ADD CONSTRAINT portfolio_fx_rates_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_fx_rates VALIDATE CONSTRAINT portfolio_fx_rates_import_run_id_fkey;

ALTER TABLE portfolio_data_completeness DROP CONSTRAINT portfolio_data_completeness_import_run_id_fkey;
ALTER TABLE portfolio_data_completeness ADD CONSTRAINT portfolio_data_completeness_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_data_completeness VALIDATE CONSTRAINT portfolio_data_completeness_import_run_id_fkey;

ALTER TABLE portfolio_data_quality_events DROP CONSTRAINT portfolio_data_quality_events_import_run_id_fkey;
ALTER TABLE portfolio_data_quality_events ADD CONSTRAINT portfolio_data_quality_events_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_data_quality_events VALIDATE CONSTRAINT portfolio_data_quality_events_import_run_id_fkey;

ALTER TABLE portfolio_reconciliations DROP CONSTRAINT portfolio_reconciliations_import_run_id_fkey;
ALTER TABLE portfolio_reconciliations ADD CONSTRAINT portfolio_reconciliations_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_reconciliations VALIDATE CONSTRAINT portfolio_reconciliations_import_run_id_fkey;

ALTER TABLE portfolio_report_metrics DROP CONSTRAINT portfolio_report_metrics_import_run_id_fkey;
ALTER TABLE portfolio_report_metrics ADD CONSTRAINT portfolio_report_metrics_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_report_metrics VALIDATE CONSTRAINT portfolio_report_metrics_import_run_id_fkey;

ALTER TABLE portfolio_event_groups DROP CONSTRAINT portfolio_event_groups_import_run_id_fkey;
ALTER TABLE portfolio_event_groups ADD CONSTRAINT portfolio_event_groups_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_event_groups VALIDATE CONSTRAINT portfolio_event_groups_import_run_id_fkey;

ALTER TABLE raw_broker_documents DROP CONSTRAINT raw_broker_documents_import_run_id_fkey;
ALTER TABLE raw_broker_documents ADD CONSTRAINT raw_broker_documents_import_run_id_fkey
    FOREIGN KEY (import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE raw_broker_documents VALIDATE CONSTRAINT raw_broker_documents_import_run_id_fkey;

ALTER TABLE account_balance_snapshots DROP CONSTRAINT account_balance_snapshots_broker_import_run_id_fkey;
ALTER TABLE account_balance_snapshots ADD CONSTRAINT account_balance_snapshots_broker_import_run_id_fkey
    FOREIGN KEY (broker_import_run_id) REFERENCES broker_import_runs(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE account_balance_snapshots VALIDATE CONSTRAINT account_balance_snapshots_broker_import_run_id_fkey;

-- 2. Facts -> the raw document they were read from: RESTRICT (was SET NULL).
ALTER TABLE portfolio_position_snapshots DROP CONSTRAINT portfolio_position_snapshots_raw_document_id_fkey;
ALTER TABLE portfolio_position_snapshots ADD CONSTRAINT portfolio_position_snapshots_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_position_snapshots VALIDATE CONSTRAINT portfolio_position_snapshots_raw_document_id_fkey;

ALTER TABLE portfolio_cash_balance_snapshots DROP CONSTRAINT portfolio_cash_balance_snapshots_raw_document_id_fkey;
ALTER TABLE portfolio_cash_balance_snapshots ADD CONSTRAINT portfolio_cash_balance_snapshots_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_cash_balance_snapshots VALIDATE CONSTRAINT portfolio_cash_balance_snapshots_raw_document_id_fkey;

ALTER TABLE portfolio_nav_snapshots DROP CONSTRAINT portfolio_nav_snapshots_raw_document_id_fkey;
ALTER TABLE portfolio_nav_snapshots ADD CONSTRAINT portfolio_nav_snapshots_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_nav_snapshots VALIDATE CONSTRAINT portfolio_nav_snapshots_raw_document_id_fkey;

ALTER TABLE portfolio_cash_ledger_entries DROP CONSTRAINT portfolio_cash_ledger_entries_raw_document_id_fkey;
ALTER TABLE portfolio_cash_ledger_entries ADD CONSTRAINT portfolio_cash_ledger_entries_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_cash_ledger_entries VALIDATE CONSTRAINT portfolio_cash_ledger_entries_raw_document_id_fkey;

ALTER TABLE portfolio_trades DROP CONSTRAINT portfolio_trades_raw_document_id_fkey;
ALTER TABLE portfolio_trades ADD CONSTRAINT portfolio_trades_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_trades VALIDATE CONSTRAINT portfolio_trades_raw_document_id_fkey;

ALTER TABLE portfolio_corporate_action_events DROP CONSTRAINT portfolio_corporate_action_events_raw_document_id_fkey;
ALTER TABLE portfolio_corporate_action_events ADD CONSTRAINT portfolio_corporate_action_events_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_corporate_action_events VALIDATE CONSTRAINT portfolio_corporate_action_events_raw_document_id_fkey;

ALTER TABLE portfolio_fx_rates DROP CONSTRAINT portfolio_fx_rates_raw_document_id_fkey;
ALTER TABLE portfolio_fx_rates ADD CONSTRAINT portfolio_fx_rates_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_fx_rates VALIDATE CONSTRAINT portfolio_fx_rates_raw_document_id_fkey;

ALTER TABLE portfolio_data_completeness DROP CONSTRAINT portfolio_data_completeness_raw_document_id_fkey;
ALTER TABLE portfolio_data_completeness ADD CONSTRAINT portfolio_data_completeness_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_data_completeness VALIDATE CONSTRAINT portfolio_data_completeness_raw_document_id_fkey;

ALTER TABLE portfolio_data_quality_events DROP CONSTRAINT portfolio_data_quality_events_raw_document_id_fkey;
ALTER TABLE portfolio_data_quality_events ADD CONSTRAINT portfolio_data_quality_events_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_data_quality_events VALIDATE CONSTRAINT portfolio_data_quality_events_raw_document_id_fkey;

ALTER TABLE portfolio_reconciliations DROP CONSTRAINT portfolio_reconciliations_raw_document_id_fkey;
ALTER TABLE portfolio_reconciliations ADD CONSTRAINT portfolio_reconciliations_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_reconciliations VALIDATE CONSTRAINT portfolio_reconciliations_raw_document_id_fkey;

ALTER TABLE portfolio_report_metrics DROP CONSTRAINT portfolio_report_metrics_raw_document_id_fkey;
ALTER TABLE portfolio_report_metrics ADD CONSTRAINT portfolio_report_metrics_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_report_metrics VALIDATE CONSTRAINT portfolio_report_metrics_raw_document_id_fkey;

ALTER TABLE portfolio_event_groups DROP CONSTRAINT portfolio_event_groups_raw_document_id_fkey;
ALTER TABLE portfolio_event_groups ADD CONSTRAINT portfolio_event_groups_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_event_groups VALIDATE CONSTRAINT portfolio_event_groups_raw_document_id_fkey;

ALTER TABLE account_balance_snapshots DROP CONSTRAINT account_balance_snapshots_raw_document_id_fkey;
ALTER TABLE account_balance_snapshots ADD CONSTRAINT account_balance_snapshots_raw_document_id_fkey
    FOREIGN KEY (raw_document_id) REFERENCES raw_broker_documents(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE account_balance_snapshots VALIDATE CONSTRAINT account_balance_snapshots_raw_document_id_fkey;

-- 3. Canonical rows -> the legacy account they belong to: RESTRICT (was SET NULL).
ALTER TABLE broker_accounts DROP CONSTRAINT broker_accounts_legacy_account_id_fkey;
ALTER TABLE broker_accounts ADD CONSTRAINT broker_accounts_legacy_account_id_fkey
    FOREIGN KEY (legacy_account_id) REFERENCES accounts(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE broker_accounts VALIDATE CONSTRAINT broker_accounts_legacy_account_id_fkey;

ALTER TABLE broker_import_runs DROP CONSTRAINT broker_import_runs_legacy_account_id_fkey;
ALTER TABLE broker_import_runs ADD CONSTRAINT broker_import_runs_legacy_account_id_fkey
    FOREIGN KEY (legacy_account_id) REFERENCES accounts(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE broker_import_runs VALIDATE CONSTRAINT broker_import_runs_legacy_account_id_fkey;

ALTER TABLE portfolio_position_snapshots DROP CONSTRAINT portfolio_position_snapshots_legacy_account_id_fkey;
ALTER TABLE portfolio_position_snapshots ADD CONSTRAINT portfolio_position_snapshots_legacy_account_id_fkey
    FOREIGN KEY (legacy_account_id) REFERENCES accounts(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_position_snapshots VALIDATE CONSTRAINT portfolio_position_snapshots_legacy_account_id_fkey;

ALTER TABLE portfolio_cash_balance_snapshots DROP CONSTRAINT portfolio_cash_balance_snapshots_legacy_account_id_fkey;
ALTER TABLE portfolio_cash_balance_snapshots ADD CONSTRAINT portfolio_cash_balance_snapshots_legacy_account_id_fkey
    FOREIGN KEY (legacy_account_id) REFERENCES accounts(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_cash_balance_snapshots VALIDATE CONSTRAINT portfolio_cash_balance_snapshots_legacy_account_id_fkey;

ALTER TABLE portfolio_nav_snapshots DROP CONSTRAINT portfolio_nav_snapshots_legacy_account_id_fkey;
ALTER TABLE portfolio_nav_snapshots ADD CONSTRAINT portfolio_nav_snapshots_legacy_account_id_fkey
    FOREIGN KEY (legacy_account_id) REFERENCES accounts(id) ON DELETE RESTRICT NOT VALID;
ALTER TABLE portfolio_nav_snapshots VALIDATE CONSTRAINT portfolio_nav_snapshots_legacy_account_id_fkey;

-- 4. CHECK constraints on enum-like TEXT columns, then their validation.
ALTER TABLE portfolio_position_snapshots ADD CONSTRAINT portfolio_position_snapshots_authority_status_check CHECK (authority_status IN ('authoritative', 'reference', 'superseded')) NOT VALID;
ALTER TABLE portfolio_cash_balance_snapshots ADD CONSTRAINT portfolio_cash_balance_snapshots_authority_status_check CHECK (authority_status IN ('authoritative', 'reference', 'superseded')) NOT VALID;
ALTER TABLE portfolio_nav_snapshots ADD CONSTRAINT portfolio_nav_snapshots_authority_status_check CHECK (authority_status IN ('authoritative', 'reference', 'superseded')) NOT VALID;
ALTER TABLE account_balance_snapshots ADD CONSTRAINT account_balance_snapshots_authority_status_check CHECK (authority_status IN ('authoritative', 'reference', 'superseded')) NOT VALID;
ALTER TABLE portfolio_source_authority_windows ADD CONSTRAINT authority_windows_authority_status_check CHECK (authority_status IN ('authoritative', 'reference', 'superseded')) NOT VALID;
ALTER TABLE portfolio_source_authority_window_changes ADD CONSTRAINT authority_window_changes_old_authority_status_check CHECK (old_authority_status IS NULL OR old_authority_status IN ('authoritative', 'reference', 'superseded')) NOT VALID;
ALTER TABLE portfolio_source_authority_window_changes ADD CONSTRAINT authority_window_changes_new_authority_status_check CHECK (new_authority_status IS NULL OR new_authority_status IN ('authoritative', 'reference', 'superseded')) NOT VALID;
ALTER TABLE portfolio_source_authority_windows ADD CONSTRAINT authority_windows_source_kind_check CHECK (source_kind IN ('ibkr_flex_daily', 'ibkr_csv_upload', 'sharekhan_upload', 'dbs_vickers_upload')) NOT VALID;
ALTER TABLE portfolio_source_authority_window_changes ADD CONSTRAINT authority_window_changes_source_kind_check CHECK (source_kind IN ('ibkr_flex_daily', 'ibkr_csv_upload', 'sharekhan_upload', 'dbs_vickers_upload')) NOT VALID;
ALTER TABLE portfolio_source_authority_windows ADD CONSTRAINT authority_windows_fact_scope_check CHECK (fact_scope IN ('all', 'holdings')) NOT VALID;
ALTER TABLE portfolio_source_authority_window_changes ADD CONSTRAINT authority_window_changes_fact_scope_check CHECK (fact_scope IN ('all', 'holdings')) NOT VALID;
ALTER TABLE portfolio_source_authority_window_changes ADD CONSTRAINT authority_window_changes_action_check CHECK (action IN ('created', 'closed', 'moved', 'removed', 'merged', 'collapsed')) NOT VALID;
ALTER TABLE account_balance_snapshots ADD CONSTRAINT account_balance_snapshots_balance_type_check CHECK (balance_type IN ('cash', 'broker_cash', 'bank_cash', 'credit_balance', 'loan_balance', 'stablecoin_cash')) NOT VALID;
ALTER TABLE account_balance_snapshots ADD CONSTRAINT account_balance_snapshots_source_kind_check CHECK (source_kind IN ('upload_parser', 'legacy_positions_backfill', 'flex', 'backfill', 'manual_adjustment', 'DUMMY')) NOT VALID;
ALTER TABLE broker_import_runs ADD CONSTRAINT broker_import_runs_source_type_check CHECK (source_type IN ('ibkr_flex_daily', 'ibkr_csv_upload', 'sharekhan_upload', 'dbs_vickers_upload', 'legacy_positions_backfill', 'DUMMY')) NOT VALID;
ALTER TABLE raw_broker_documents ADD CONSTRAINT raw_broker_documents_source_type_check CHECK (source_type IN ('ibkr_flex_daily', 'ibkr_csv_upload', 'sharekhan_upload', 'dbs_vickers_upload', 'legacy_positions_backfill', 'DUMMY')) NOT VALID;
ALTER TABLE broker_import_runs ADD CONSTRAINT broker_import_runs_import_scope_check CHECK (import_scope IN ('daily', 'upload', 'backfill')) NOT VALID;
ALTER TABLE broker_import_runs ADD CONSTRAINT broker_import_runs_status_check CHECK (status IN ('started', 'completed', 'failed', 'removed')) NOT VALID;
ALTER TABLE portfolio_data_completeness ADD CONSTRAINT portfolio_data_completeness_fact_scope_check CHECK (fact_scope IN ('holdings', 'cash_balance', 'nav', 'trades', 'holdings_cash_nav_fx')) NOT VALID;
ALTER TABLE portfolio_data_completeness ADD CONSTRAINT portfolio_data_completeness_completeness_status_check CHECK (completeness_status IN ('complete', 'incomplete', 'nav_only', 'failed')) NOT VALID;
ALTER TABLE wealth_monthly_rollups ADD CONSTRAINT wealth_monthly_rollups_freshness_status_check CHECK (freshness_status IN ('fresh', 'carried', 'stale', 'missing')) NOT VALID;
ALTER TABLE wealth_monthly_rollups ADD CONSTRAINT wealth_monthly_rollups_month_format CHECK (month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$') NOT VALID;

ALTER TABLE portfolio_position_snapshots VALIDATE CONSTRAINT portfolio_position_snapshots_authority_status_check;
ALTER TABLE portfolio_cash_balance_snapshots VALIDATE CONSTRAINT portfolio_cash_balance_snapshots_authority_status_check;
ALTER TABLE portfolio_nav_snapshots VALIDATE CONSTRAINT portfolio_nav_snapshots_authority_status_check;
ALTER TABLE account_balance_snapshots VALIDATE CONSTRAINT account_balance_snapshots_authority_status_check;
ALTER TABLE portfolio_source_authority_windows VALIDATE CONSTRAINT authority_windows_authority_status_check;
ALTER TABLE portfolio_source_authority_window_changes VALIDATE CONSTRAINT authority_window_changes_old_authority_status_check;
ALTER TABLE portfolio_source_authority_window_changes VALIDATE CONSTRAINT authority_window_changes_new_authority_status_check;
ALTER TABLE portfolio_source_authority_windows VALIDATE CONSTRAINT authority_windows_source_kind_check;
ALTER TABLE portfolio_source_authority_window_changes VALIDATE CONSTRAINT authority_window_changes_source_kind_check;
ALTER TABLE portfolio_source_authority_windows VALIDATE CONSTRAINT authority_windows_fact_scope_check;
ALTER TABLE portfolio_source_authority_window_changes VALIDATE CONSTRAINT authority_window_changes_fact_scope_check;
ALTER TABLE portfolio_source_authority_window_changes VALIDATE CONSTRAINT authority_window_changes_action_check;
ALTER TABLE account_balance_snapshots VALIDATE CONSTRAINT account_balance_snapshots_balance_type_check;
ALTER TABLE account_balance_snapshots VALIDATE CONSTRAINT account_balance_snapshots_source_kind_check;
ALTER TABLE broker_import_runs VALIDATE CONSTRAINT broker_import_runs_source_type_check;
ALTER TABLE raw_broker_documents VALIDATE CONSTRAINT raw_broker_documents_source_type_check;
ALTER TABLE broker_import_runs VALIDATE CONSTRAINT broker_import_runs_import_scope_check;
ALTER TABLE broker_import_runs VALIDATE CONSTRAINT broker_import_runs_status_check;
ALTER TABLE portfolio_data_completeness VALIDATE CONSTRAINT portfolio_data_completeness_fact_scope_check;
ALTER TABLE portfolio_data_completeness VALIDATE CONSTRAINT portfolio_data_completeness_completeness_status_check;
ALTER TABLE wealth_monthly_rollups VALIDATE CONSTRAINT wealth_monthly_rollups_freshness_status_check;
ALTER TABLE wealth_monthly_rollups VALIDATE CONSTRAINT wealth_monthly_rollups_month_format;
