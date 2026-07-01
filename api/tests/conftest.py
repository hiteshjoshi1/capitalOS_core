import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure test DB URL is set before importing app modules that read env vars.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:////tmp/capitalos_test.db"
os.environ.setdefault("DATA_DIR", "/tmp/capitalos_test_data")
os.environ.setdefault("SNAPSHOT_DAY", "1")
os.environ.setdefault("CRYPTO_SCHEDULER_ENABLED", "0")
os.environ.setdefault("STOCK_PRICE_SCHEDULER_ENABLED", "0")
os.environ.setdefault("IBKR_FLEX_SCHEDULER_ENABLED", "0")
os.environ.setdefault("FX_DISABLE_REMOTE", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")
os.environ.setdefault("AUTH_ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ["AUTH_ALLOW_LEGACY_NULL_OWNERSHIP"] = "1"
# Never allow backend tests to hit live inference just because the runtime
# container has real credentials configured in .env.
os.environ["INFERENCE_LLM_API_KEY"] = ""

from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402

connect_args = {}
if os.environ["DATABASE_URL"].startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(os.environ["DATABASE_URL"], connect_args=connect_args)
TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


def _create_canonical_portfolio_tables(conn):
    for ddl in (
        """
        CREATE TABLE IF NOT EXISTS broker_connections (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          user_id INTEGER,
          platform_code TEXT NOT NULL,
          connection_type TEXT NOT NULL,
          display_name TEXT,
          status TEXT NOT NULL DEFAULT 'active',
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS broker_accounts (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          connection_id INTEGER NOT NULL,
          legacy_account_id INTEGER,
          broker_account_id TEXT NOT NULL,
          account_alias TEXT,
          base_currency TEXT NOT NULL,
          country TEXT,
          status TEXT NOT NULL DEFAULT 'active',
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP,
          UNIQUE (connection_id, broker_account_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_source_authority_windows (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          source_kind TEXT NOT NULL,
          fact_scope TEXT NOT NULL,
          effective_from DATE NOT NULL,
          effective_to DATE,
          authority_status TEXT NOT NULL DEFAULT 'authoritative',
          created_at TIMESTAMP,
          UNIQUE (broker_account_id, source_kind, fact_scope, effective_from)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS broker_import_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER,
          legacy_account_id INTEGER,
          platform_code TEXT NOT NULL,
          source_type TEXT NOT NULL,
          import_scope TEXT NOT NULL DEFAULT 'daily',
          status TEXT NOT NULL,
          requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          started_at TIMESTAMP,
          fetched_at TIMESTAMP,
          parsed_at TIMESTAMP,
          finished_at TIMESTAMP,
          report_date_from DATE,
          report_date_to DATE,
          flex_reference_code TEXT,
          raw_document_id INTEGER,
          parser_version TEXT,
          error_code TEXT,
          error_message TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS raw_broker_documents (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          import_run_id INTEGER NOT NULL,
          broker_account_id INTEGER,
          source_type TEXT NOT NULL,
          content_hash TEXT NOT NULL,
          storage_path TEXT NOT NULL,
          content_type TEXT NOT NULL DEFAULT 'application/xml',
          report_date_from DATE,
          report_date_to DATE,
          parser_version TEXT NOT NULL,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS broker_instruments (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          platform_code TEXT NOT NULL,
          broker_instrument_id TEXT NOT NULL,
          asset_id INTEGER,
          symbol TEXT,
          description TEXT,
          security_type TEXT,
          listing_exchange TEXT,
          currency TEXT,
          country TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_broker_instruments_platform_contract
        ON broker_instruments(platform_code, broker_instrument_id, COALESCE(listing_exchange, ''), COALESCE(currency, ''))
        """,
        """
        CREATE TABLE IF NOT EXISTS asset_identifiers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          asset_id INTEGER,
          broker_instrument_id INTEGER,
          identifier_namespace TEXT NOT NULL,
          identifier_type TEXT NOT NULL,
          identifier_value TEXT NOT NULL,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_position_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          legacy_account_id INTEGER,
          broker_instrument_id INTEGER NOT NULL,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          report_date DATE NOT NULL,
          quantity NUMERIC NOT NULL,
          currency TEXT NOT NULL,
          market_price NUMERIC,
          market_value_local NUMERIC NOT NULL,
          market_value_base NUMERIC NOT NULL,
          cost_basis_local NUMERIC,
          cost_basis_base NUMERIC,
          fx_rate_to_base NUMERIC NOT NULL,
          authority_status TEXT NOT NULL DEFAULT 'authoritative',
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_cash_balance_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          legacy_account_id INTEGER,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          report_date DATE NOT NULL,
          currency TEXT NOT NULL,
          cash_balance NUMERIC NOT NULL,
          cash_balance_base NUMERIC NOT NULL,
          fx_rate_to_base NUMERIC NOT NULL,
          authority_status TEXT NOT NULL DEFAULT 'authoritative',
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_nav_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          legacy_account_id INTEGER,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          report_date DATE NOT NULL,
          base_currency TEXT NOT NULL,
          cash_base NUMERIC NOT NULL DEFAULT 0,
          stock_base NUMERIC NOT NULL DEFAULT 0,
          options_base NUMERIC NOT NULL DEFAULT 0,
          funds_base NUMERIC NOT NULL DEFAULT 0,
          bonds_base NUMERIC NOT NULL DEFAULT 0,
          interest_accrual_base NUMERIC NOT NULL DEFAULT 0,
          dividend_accrual_base NUMERIC NOT NULL DEFAULT 0,
          total_nav_base NUMERIC NOT NULL,
          authority_status TEXT NOT NULL DEFAULT 'authoritative',
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_report_metrics (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          report_date DATE NOT NULL,
          report_section TEXT NOT NULL,
          metric_code TEXT NOT NULL,
          currency TEXT,
          amount NUMERIC NOT NULL,
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_fx_rates (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          report_date DATE NOT NULL,
          from_currency TEXT NOT NULL,
          to_currency TEXT NOT NULL,
          rate NUMERIC NOT NULL,
          source_platform TEXT NOT NULL DEFAULT 'IBKR',
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP,
          UNIQUE (report_date, from_currency, to_currency, source_platform)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_reconciliations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          report_date DATE NOT NULL,
          reconciliation_type TEXT NOT NULL,
          expected_amount NUMERIC NOT NULL,
          actual_amount NUMERIC NOT NULL,
          difference_amount NUMERIC NOT NULL,
          tolerance_amount NUMERIC NOT NULL DEFAULT 0,
          status TEXT NOT NULL,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_data_quality_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER,
          import_run_id INTEGER,
          raw_document_id INTEGER,
          report_date DATE,
          severity TEXT NOT NULL,
          event_code TEXT NOT NULL,
          message TEXT NOT NULL,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_data_completeness (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          report_date DATE NOT NULL,
          fact_scope TEXT NOT NULL,
          completeness_status TEXT NOT NULL,
          missing_reason TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP,
          UNIQUE (broker_account_id, report_date, fact_scope)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_event_groups (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          event_date DATE NOT NULL,
          event_type TEXT NOT NULL,
          broker_event_id TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_trades (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          broker_instrument_id INTEGER,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          event_group_id INTEGER,
          trade_date DATE NOT NULL,
          settle_date DATE,
          side TEXT,
          quantity NUMERIC,
          price NUMERIC,
          proceeds NUMERIC,
          commission NUMERIC,
          currency TEXT,
          broker_execution_id TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_cash_ledger_entries (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          event_group_id INTEGER,
          activity_date DATE NOT NULL,
          currency TEXT NOT NULL,
          amount NUMERIC NOT NULL,
          activity_code TEXT,
          description TEXT,
          broker_activity_id TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_corporate_action_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          broker_account_id INTEGER NOT NULL,
          broker_instrument_id INTEGER,
          import_run_id INTEGER NOT NULL,
          raw_document_id INTEGER,
          event_group_id INTEGER,
          action_date DATE NOT NULL,
          action_type TEXT,
          quantity NUMERIC,
          cash_amount NUMERIC,
          currency TEXT,
          broker_action_id TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS portfolio_import_locks (
          broker_account_id INTEGER PRIMARY KEY,
          source_type TEXT NOT NULL,
          lock_owner TEXT NOT NULL,
          locked_at TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS account_balance_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          account_id INTEGER NOT NULL,
          broker_account_id INTEGER,
          import_job_id INTEGER,
          broker_import_run_id INTEGER,
          raw_document_id INTEGER,
          as_of_date DATE NOT NULL,
          currency TEXT NOT NULL,
          balance_type TEXT NOT NULL DEFAULT 'cash',
          balance_local NUMERIC NOT NULL,
          balance_base NUMERIC NOT NULL,
          fx_rate_to_base NUMERIC NOT NULL DEFAULT 1,
          authority_status TEXT NOT NULL DEFAULT 'authoritative',
          source_kind TEXT NOT NULL,
          source_row_hash TEXT,
          metadata_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_account_balance_snapshots_authoritative
        ON account_balance_snapshots(account_id, as_of_date, currency, balance_type)
        WHERE authority_status = 'authoritative'
        """,
    ):
        conn.exec_driver_sql(ddl)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    with engine.begin() as conn:
        # SQLite needs INTEGER PRIMARY KEY for auto-increment behavior.
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS accounts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              platform TEXT NOT NULL,
              user_id INTEGER,
              account_type TEXT NOT NULL,
              currency TEXT NOT NULL,
              country TEXT,
              platform_id INTEGER
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              display_name TEXT,
              email TEXT,
              is_active INTEGER NOT NULL DEFAULT 1,
              is_admin INTEGER NOT NULL DEFAULT 0,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS user_credentials (
              user_id INTEGER PRIMARY KEY,
              password_hash TEXT NOT NULL,
              password_algo TEXT NOT NULL,
              password_updated_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS auth_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              refresh_token_hash TEXT NOT NULL,
              expires_at TIMESTAMP NOT NULL,
              revoked_at TIMESTAMP,
              revoke_reason TEXT,
              created_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS oauth_identities (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL,
              provider TEXT NOT NULL,
              provider_subject TEXT NOT NULL,
              email TEXT,
              created_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS platforms (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              platform_type TEXT NOT NULL,
              country TEXT NOT NULL,
              website TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS currencies (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT NOT NULL UNIQUE,
              name TEXT,
              country TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS import_jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id INTEGER NOT NULL,
              platform TEXT NOT NULL,
              original_filename TEXT NOT NULL,
              stored_path TEXT NOT NULL,
              file_sha256 TEXT NOT NULL,
              format_signature TEXT,
              parser_key TEXT,
              status TEXT NOT NULL,
              report_path TEXT,
              error_message TEXT,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS parser_registry (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              format_signature TEXT NOT NULL UNIQUE,
              parser_key TEXT NOT NULL,
              version INTEGER NOT NULL DEFAULT 1,
              created_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS credit_card_accounts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id INTEGER NOT NULL UNIQUE,
              card_name TEXT NOT NULL,
              issuer TEXT NOT NULL,
              credit_limit REAL NOT NULL,
              statement_day INTEGER NOT NULL,
              due_day INTEGER NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS transactions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TIMESTAMP NOT NULL,
              account_id INTEGER NOT NULL,
              amount REAL NOT NULL,
              type TEXT NOT NULL,
              currency TEXT NOT NULL,
              asset_id INTEGER,
              quantity REAL,
              category TEXT,
              merchant_counterparty TEXT,
              platform_reference TEXT,
              notes TEXT,
              source TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS category_taxonomy (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              code TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL,
              parent_id INTEGER,
              display_order INTEGER NOT NULL DEFAULT 0,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS category_rules (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              priority INTEGER NOT NULL DEFAULT 100,
              merchant_pattern TEXT,
              description_pattern TEXT,
              source_category_pattern TEXT,
              txn_type TEXT,
              min_amount REAL,
              max_amount REAL,
              target_category_id INTEGER NOT NULL,
              active INTEGER NOT NULL DEFAULT 1,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS category_overrides (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              transaction_id INTEGER NOT NULL UNIQUE,
              category_id INTEGER NOT NULL,
              source TEXT NOT NULL,
              rule_id INTEGER,
              created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
              updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS crypto_wallets (
              id TEXT PRIMARY KEY,
              user_id INTEGER,
              chain_type TEXT NOT NULL,
              chain TEXT NOT NULL,
              address TEXT NOT NULL,
              label TEXT,
              status TEXT NOT NULL,
              refresh_in_progress INTEGER NOT NULL DEFAULT 0,
              refresh_started_at TIMESTAMP,
              created_at TIMESTAMP,
              verified_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS crypto_wallet_verifications (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              wallet_id TEXT,
              chain_type TEXT,
              chain TEXT,
              address TEXT,
              nonce TEXT NOT NULL,
              message TEXT NOT NULL,
              expires_at TIMESTAMP NOT NULL,
              used_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS crypto_wallet_snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              wallet_id TEXT NOT NULL,
              as_of_date DATE NOT NULL,
              fetched_at TIMESTAMP NOT NULL,
              total_usd REAL,
              source_versions TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS crypto_allowlist (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chain TEXT NOT NULL,
              contract_address TEXT NOT NULL,
              symbol TEXT,
              name TEXT,
              created_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS crypto_wallet_snapshot_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              snapshot_id INTEGER NOT NULL,
              asset_id INTEGER,
              chain_type TEXT NOT NULL,
              chain TEXT NOT NULL,
              asset_kind TEXT NOT NULL,
              contract_or_mint TEXT,
              symbol TEXT,
              name TEXT,
              decimals INTEGER,
              raw_amount TEXT,
              normalized_amount REAL,
              price_usd REAL,
              value_usd REAL,
              price_source TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS crypto_user_networth (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              as_of_date DATE NOT NULL,
              total_usd REAL,
              crypto_usd REAL,
              updated_at TIMESTAMP
            )
            """
        )
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS assets (
              id INTEGER PRIMARY KEY,
              symbol TEXT NOT NULL,
              name TEXT,
              asset_class TEXT NOT NULL,
              quote_currency TEXT,
              home_country TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS positions (
              id INTEGER PRIMARY KEY,
              account_id INTEGER NOT NULL,
              asset_id INTEGER NOT NULL,
              as_of TIMESTAMP NOT NULL,
              quantity REAL,
              avg_cost REAL,
              cost_basis_base REAL NOT NULL
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS transactions (
              id INTEGER PRIMARY KEY,
              ts TIMESTAMP NOT NULL,
              account_id INTEGER NOT NULL,
              amount REAL NOT NULL,
              type TEXT NOT NULL,
              currency TEXT NOT NULL,
              asset_id INTEGER,
              quantity REAL,
              category TEXT,
              merchant_counterparty TEXT,
              platform_reference TEXT,
              notes TEXT,
              source TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS prices (
              id INTEGER PRIMARY KEY,
              asset_id INTEGER NOT NULL,
              ts TIMESTAMP NOT NULL,
              price REAL NOT NULL,
              currency TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'MANUAL',
              trade_date DATE,
              exchange_code TEXT,
              provider_symbol TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS market_symbol_map (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              asset_id INTEGER NOT NULL,
              exchange_code TEXT NOT NULL,
              exchange_symbol TEXT NOT NULL,
              quote_currency TEXT NOT NULL,
              is_active INTEGER NOT NULL DEFAULT 1,
              eodhd_symbol_override TEXT,
              yahoo_symbol_override TEXT,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS market_data_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              provider TEXT NOT NULL,
              exchange_code TEXT NOT NULL,
              trade_date DATE NOT NULL,
              status TEXT NOT NULL,
              requested_symbols INTEGER NOT NULL DEFAULT 0,
              received_rows INTEGER NOT NULL DEFAULT 0,
              upserted_rows INTEGER NOT NULL DEFAULT 0,
              missing_symbols INTEGER NOT NULL DEFAULT 0,
              started_at TIMESTAMP,
              finished_at TIMESTAMP,
              error_summary TEXT
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS market_data_run_items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id INTEGER NOT NULL,
              asset_id INTEGER,
              provider TEXT NOT NULL,
              exchange_code TEXT NOT NULL,
              symbol TEXT NOT NULL,
              trade_date DATE NOT NULL,
              status TEXT NOT NULL,
              price REAL,
              currency TEXT,
              source_note TEXT,
              created_at TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS market_dividend_yields (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              asset_id INTEGER NOT NULL,
              as_of_date DATE NOT NULL,
              yield_rate REAL NOT NULL,
              annual_dividend_per_share REAL,
              price REAL,
              currency TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'yfinance_dividend',
              exchange_code TEXT,
              provider_symbol TEXT,
              created_at TIMESTAMP,
              updated_at TIMESTAMP
            )
            """
        )
        _create_canonical_portfolio_tables(conn)
    yield
    with engine.begin() as conn:
        for table_name in (
          "account_balance_snapshots",
            "portfolio_import_locks",
            "portfolio_corporate_action_events",
            "portfolio_cash_ledger_entries",
            "portfolio_trades",
            "portfolio_event_groups",
            "portfolio_data_completeness",
            "portfolio_data_quality_events",
            "portfolio_reconciliations",
            "portfolio_fx_rates",
            "portfolio_report_metrics",
            "portfolio_nav_snapshots",
            "portfolio_cash_balance_snapshots",
            "portfolio_position_snapshots",
            "asset_identifiers",
            "broker_instruments",
            "raw_broker_documents",
            "broker_import_runs",
            "portfolio_source_authority_windows",
            "broker_accounts",
            "broker_connections",
        ):
            conn.exec_driver_sql(f"DROP TABLE IF EXISTS {table_name}")
        conn.exec_driver_sql("DROP TABLE IF EXISTS currencies")
        conn.exec_driver_sql("DROP TABLE IF EXISTS parser_registry")
        conn.exec_driver_sql("DROP TABLE IF EXISTS import_jobs")
        conn.exec_driver_sql("DROP TABLE IF EXISTS credit_card_accounts")
        conn.exec_driver_sql("DROP TABLE IF EXISTS category_overrides")
        conn.exec_driver_sql("DROP TABLE IF EXISTS category_rules")
        conn.exec_driver_sql("DROP TABLE IF EXISTS category_taxonomy")
        conn.exec_driver_sql("DROP TABLE IF EXISTS transactions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS prices")
        conn.exec_driver_sql("DROP TABLE IF EXISTS market_data_run_items")
        conn.exec_driver_sql("DROP TABLE IF EXISTS market_data_runs")
        conn.exec_driver_sql("DROP TABLE IF EXISTS market_dividend_yields")
        conn.exec_driver_sql("DROP TABLE IF EXISTS market_symbol_map")
        conn.exec_driver_sql("DROP TABLE IF EXISTS positions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS assets")
        conn.exec_driver_sql("DROP TABLE IF EXISTS platforms")
        conn.exec_driver_sql("DROP TABLE IF EXISTS crypto_wallet_snapshot_items")
        conn.exec_driver_sql("DROP TABLE IF EXISTS crypto_wallet_snapshots")
        conn.exec_driver_sql("DROP TABLE IF EXISTS crypto_wallet_verifications")
        conn.exec_driver_sql("DROP TABLE IF EXISTS crypto_wallets")
        conn.exec_driver_sql("DROP TABLE IF EXISTS crypto_user_networth")
        conn.exec_driver_sql("DROP TABLE IF EXISTS crypto_allowlist")
        conn.exec_driver_sql("DROP TABLE IF EXISTS ai_sage_turn_evidence")
        conn.exec_driver_sql("DROP TABLE IF EXISTS ai_sage_messages")
        conn.exec_driver_sql("DROP TABLE IF EXISTS ai_sage_chats")
        conn.exec_driver_sql("DROP TABLE IF EXISTS auth_sessions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS oauth_identities")
        conn.exec_driver_sql("DROP TABLE IF EXISTS user_credentials")
        conn.exec_driver_sql("DROP TABLE IF EXISTS users")
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clear_db():
    with engine.begin() as conn:
        for table_name in (
        "account_balance_snapshots",
            "portfolio_import_locks",
            "portfolio_corporate_action_events",
            "portfolio_cash_ledger_entries",
            "portfolio_trades",
            "portfolio_event_groups",
            "portfolio_data_completeness",
            "portfolio_data_quality_events",
            "portfolio_reconciliations",
            "portfolio_fx_rates",
            "portfolio_report_metrics",
            "portfolio_nav_snapshots",
            "portfolio_cash_balance_snapshots",
            "portfolio_position_snapshots",
            "asset_identifiers",
            "broker_instruments",
            "raw_broker_documents",
            "broker_import_runs",
            "portfolio_source_authority_windows",
            "broker_accounts",
            "broker_connections",
        ):
            conn.exec_driver_sql(f"DELETE FROM {table_name}")
        conn.exec_driver_sql("DELETE FROM category_overrides")
        conn.exec_driver_sql("DELETE FROM category_rules")
        conn.exec_driver_sql("DELETE FROM category_taxonomy")
        conn.exec_driver_sql("DELETE FROM accounts")
        conn.exec_driver_sql("DELETE FROM platforms")
        conn.exec_driver_sql("DELETE FROM credit_card_accounts")
        conn.exec_driver_sql("DELETE FROM positions")
        conn.exec_driver_sql("DELETE FROM assets")
        conn.exec_driver_sql("DELETE FROM transactions")
        conn.exec_driver_sql("DELETE FROM prices")
        conn.exec_driver_sql("DELETE FROM market_data_run_items")
        conn.exec_driver_sql("DELETE FROM market_data_runs")
        conn.exec_driver_sql("DELETE FROM market_dividend_yields")
        conn.exec_driver_sql("DELETE FROM market_symbol_map")
        conn.exec_driver_sql("DELETE FROM currencies")
        conn.exec_driver_sql("DELETE FROM parser_registry")
        conn.exec_driver_sql("DELETE FROM import_jobs")
        conn.exec_driver_sql("DELETE FROM ai_sage_turn_evidence")
        conn.exec_driver_sql("DELETE FROM ai_sage_messages")
        conn.exec_driver_sql("DELETE FROM ai_sage_chats")
        conn.exec_driver_sql("DELETE FROM auth_sessions")
        conn.exec_driver_sql("DELETE FROM oauth_identities")
        conn.exec_driver_sql("DELETE FROM user_credentials")
        conn.exec_driver_sql("DELETE FROM users")
        conn.exec_driver_sql("DELETE FROM crypto_allowlist")
        conn.exec_driver_sql("DELETE FROM crypto_wallet_snapshot_items")
        conn.exec_driver_sql("DELETE FROM crypto_wallet_snapshots")
        conn.exec_driver_sql("DELETE FROM crypto_wallet_verifications")
        conn.exec_driver_sql("DELETE FROM crypto_wallets")
        conn.exec_driver_sql("DELETE FROM crypto_user_networth")
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def db_engine():
    return engine


@pytest.fixture()
def seed_dashboard_data():
    as_of_cur = datetime(2026, 2, 6, tzinfo=timezone.utc)
    as_of_prev = datetime(2026, 1, 6, tzinfo=timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) VALUES "
                "(1, 'DBS', 'DBS Bank', 'BANK', 'SG'), "
                "(2, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) VALUES "
                "(1, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG', 1), "
                "(2, 'IBKR Main', 'IBKR', 'BROKER', 'USD', 'US', 2)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(1, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', 'US'), "
                "(2, 'BTC', 'Bitcoin', 'CRYPTO', 'USD', 'GLOBAL'), "
                "(3, 'CASH', 'Cash', 'CASH', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_connections (id, user_id, platform_code, connection_type, display_name, status, metadata_json) VALUES "
                "(1, 1, 'IBKR', 'test', 'IBKR Fixture', 'active', '{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_accounts (id, connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) VALUES "
                "(1, 1, 2, 'U_FIXTURE', 'SGD', 'active', '{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_import_runs (id, broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status, metadata_json) VALUES "
                "(1, 1, 2, 'IBKR', 'test', 'daily', 'completed', '{}'), "
                "(2, 1, 2, 'IBKR', 'test', 'daily', 'completed', '{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_instruments (id, platform_code, broker_instrument_id, asset_id, symbol, description, security_type, currency, metadata_json) VALUES "
                "(1, 'IBKR', 'AAPL_FIXTURE', 1, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', '{}')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO portfolio_nav_snapshots
                  (id, broker_account_id, legacy_account_id, import_run_id, report_date, base_currency,
                   cash_base, stock_base, total_nav_base, authority_status, metadata_json)
                VALUES
                  (1, 1, 2, 1, '2026-02-06', 'SGD', 0, 50000, 50000, 'authoritative', '{}'),
                  (2, 1, 2, 2, '2026-01-06', 'SGD', 0, 45000, 45000, 'authoritative', '{}')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO portfolio_position_snapshots
                  (id, broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
                   quantity, currency, market_price, market_value_local, market_value_base,
                   cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (1, 1, 2, 1, 1, '2026-02-06', 10, 'USD', 5000, 50000, 50000, 50000, 50000, 1, 'authoritative', '{}'),
                  (2, 1, 2, 1, 2, '2026-01-06', 9, 'USD', 5000, 45000, 45000, 45000, 45000, 1, 'authoritative', '{}')
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO account_balance_snapshots
                  (id, account_id, as_of_date, currency, balance_type, balance_local, balance_base,
                   fx_rate_to_base, authority_status, source_kind, metadata_json)
                VALUES
                  (1, 1, '2026-02-06', 'SGD', 'bank_cash', 30000, 30000, 1, 'authoritative', 'test_fixture', '{}'),
                  (2, 1, '2026-01-06', 'SGD', 'bank_cash', 30000, 30000, 1, 'authoritative', 'test_fixture', '{}')
                """
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('wallet-btc', 'evm', 'ethereum', '0xbtc', 'BTC Wallet', 'active', :as_of_cur)"
            ),
            {"as_of_cur": as_of_cur},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(101, 'wallet-btc', '2026-02-06', :as_of_cur, 20000), "
                "(102, 'wallet-btc', '2026-01-06', :as_of_prev, 15000)"
            ),
            {"as_of_cur": as_of_cur, "as_of_prev": as_of_prev},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(101, 101, 'evm', 'ethereum', 'native', 'BTC', 1, 20000), "
                "(102, 102, 'evm', 'ethereum', 'native', 'BTC', 1, 15000)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category) VALUES "
                "(1, '2026-02-05 12:00:00+00:00', 1, 5000, 'INCOME', 'SGD', NULL), "
                "(2, '2026-02-10 12:00:00+00:00', 1, -2000, 'EXPENSE', 'SGD', 'Rent'), "
                "(3, '2026-02-20 12:00:00+00:00', 1, -100, 'FEE', 'SGD', 'Fees'), "
                "(4, '2026-02-15 12:00:00+00:00', 2, 999, 'INCOME', 'USD', NULL)"
            )
        )
    return {"as_of_cur": as_of_cur, "as_of_prev": as_of_prev}


@pytest.fixture()
def seed_spending_data():
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(10, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG'), "
                "(11, 'DBS Credit Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (id, account_id, card_name, issuer, credit_limit, statement_day, due_day) VALUES "
                "(1, 11, 'DBS Altitude', 'DBS', 20000, 20, 25)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category, merchant_counterparty, notes) VALUES "
                "(1, '2026-02-05 12:00:00+00:00', 10, 12000, 'INCOME', 'SGD', 'Salary', 'Employer', NULL), "
                "(2, '2026-02-08 09:00:00+00:00', 10, 480, 'INCOME', 'SGD', 'Dividends', 'Broker', NULL), "
                "(3, '2026-02-10 12:00:00+00:00', 10, -3200, 'EXPENSE', 'SGD', 'Rent', 'Landlord', NULL), "
                "(4, '2026-02-12 12:00:00+00:00', 10, -800, 'EXPENSE', 'SGD', 'Education', 'Course', NULL), "
                "(5, '2026-02-15 12:00:00+00:00', 10, -620, 'EXPENSE', 'SGD', 'Transport', 'Transit', NULL), "
                "(6, '2026-02-18 12:00:00+00:00', 10, -1100, 'EXPENSE', 'SGD', 'Recurring bills', 'Utilities', NULL), "
                "(7, '2026-02-20 12:00:00+00:00', 11, -1780, 'EXPENSE', 'SGD', 'Dining', 'Hawker Center', 'Weekend meals'), "
                "(8, '2026-02-22 12:00:00+00:00', 11, -1210, 'EXPENSE', 'SGD', 'Groceries', 'Netflix', 'Annual plan'), "
                "(9, '2026-01-22 12:00:00+00:00', 11, -18, 'EXPENSE', 'SGD', 'Subscription', 'Netflix', 'Monthly plan'), "
                "(10, '2025-12-22 12:00:00+00:00', 11, -18, 'EXPENSE', 'SGD', 'Subscription', 'Netflix', 'Monthly plan')"
            )
        )
    return True
