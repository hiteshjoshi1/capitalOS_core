import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure test DB URL is set before importing app modules that read env vars.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:////tmp/capitalos_test.db"
os.environ.setdefault("DATA_DIR", "/tmp/capitalos_test_data")
os.environ.setdefault("SNAPSHOT_DAY", "6")
os.environ.setdefault("CRYPTO_SCHEDULER_ENABLED", "0")
os.environ.setdefault("STOCK_PRICE_SCHEDULER_ENABLED", "0")
os.environ.setdefault("FX_DISABLE_REMOTE", "1")

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
              account_type TEXT NOT NULL,
              currency TEXT NOT NULL,
              country TEXT,
              platform_id INTEGER
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
    yield
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS currencies")
        conn.exec_driver_sql("DROP TABLE IF EXISTS parser_registry")
        conn.exec_driver_sql("DROP TABLE IF EXISTS import_jobs")
        conn.exec_driver_sql("DROP TABLE IF EXISTS credit_card_accounts")
        conn.exec_driver_sql("DROP TABLE IF EXISTS transactions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS prices")
        conn.exec_driver_sql("DROP TABLE IF EXISTS market_data_run_items")
        conn.exec_driver_sql("DROP TABLE IF EXISTS market_data_runs")
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
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clear_db():
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM accounts")
        conn.exec_driver_sql("DELETE FROM platforms")
        conn.exec_driver_sql("DELETE FROM credit_card_accounts")
        conn.exec_driver_sql("DELETE FROM positions")
        conn.exec_driver_sql("DELETE FROM assets")
        conn.exec_driver_sql("DELETE FROM transactions")
        conn.exec_driver_sql("DELETE FROM prices")
        conn.exec_driver_sql("DELETE FROM market_data_run_items")
        conn.exec_driver_sql("DELETE FROM market_data_runs")
        conn.exec_driver_sql("DELETE FROM market_symbol_map")
        conn.exec_driver_sql("DELETE FROM currencies")
        conn.exec_driver_sql("DELETE FROM parser_registry")
        conn.exec_driver_sql("DELETE FROM import_jobs")
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
                "INSERT INTO positions (id, account_id, asset_id, as_of, quantity, avg_cost, cost_basis_base) VALUES "
                "(1, 2, 1, :as_of_cur, 10, 5000, 50000), "
                "(2, 2, 2, :as_of_cur, 1, 20000, 20000), "
                "(3, 1, 3, :as_of_cur, 1, 30000, 30000), "
                "(4, 2, 1, :as_of_prev, 9, 5000, 45000), "
                "(5, 2, 2, :as_of_prev, 1, 15000, 15000), "
                "(6, 1, 3, :as_of_prev, 1, 30000, 30000)"
            ),
            {"as_of_cur": as_of_cur, "as_of_prev": as_of_prev},
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
