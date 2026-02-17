import os
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure test DB URL is set before importing app modules that read env vars.
os.environ["DATABASE_URL"] = "sqlite+pysqlite:////tmp/capitalos_test.db"
os.environ.setdefault("SNAPSHOT_DAY", "6")

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
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS assets (
              id INTEGER PRIMARY KEY,
              symbol TEXT NOT NULL,
              asset_class TEXT NOT NULL,
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
              category TEXT
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
              currency TEXT NOT NULL
            )
            """
        )
    yield
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS currencies")
        conn.exec_driver_sql("DROP TABLE IF EXISTS credit_card_accounts")
        conn.exec_driver_sql("DROP TABLE IF EXISTS transactions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS prices")
        conn.exec_driver_sql("DROP TABLE IF EXISTS positions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS assets")
        conn.exec_driver_sql("DROP TABLE IF EXISTS platforms")
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
        conn.exec_driver_sql("DELETE FROM currencies")
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
                "INSERT INTO assets (id, symbol, asset_class, home_country) VALUES "
                "(1, 'AAPL', 'STOCK', 'US'), "
                "(2, 'BTC', 'CRYPTO', 'GLOBAL'), "
                "(3, 'CASH', 'CASH', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO positions (id, account_id, asset_id, as_of, cost_basis_base) VALUES "
                "(1, 2, 1, :as_of_cur, 50000), "
                "(2, 2, 2, :as_of_cur, 20000), "
                "(3, 1, 3, :as_of_cur, 30000), "
                "(4, 2, 1, :as_of_prev, 45000), "
                "(5, 2, 2, :as_of_prev, 15000), "
                "(6, 1, 3, :as_of_prev, 30000)"
            ),
            {"as_of_cur": as_of_cur, "as_of_prev": as_of_prev},
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
                "(11, 'DBS Credit Card', 'DBS_CARDS', 'CREDIT_CARD', 'SGD', 'SG')"
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
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category) VALUES "
                "(1, '2026-02-05 12:00:00+00:00', 10, 12000, 'INCOME', 'SGD', 'Salary'), "
                "(2, '2026-02-08 09:00:00+00:00', 10, 480, 'INCOME', 'SGD', 'Dividends'), "
                "(3, '2026-02-10 12:00:00+00:00', 10, -3200, 'EXPENSE', 'SGD', 'Rent'), "
                "(4, '2026-02-12 12:00:00+00:00', 10, -800, 'EXPENSE', 'SGD', 'Education'), "
                "(5, '2026-02-15 12:00:00+00:00', 10, -620, 'EXPENSE', 'SGD', 'Transport'), "
                "(6, '2026-02-18 12:00:00+00:00', 10, -1100, 'EXPENSE', 'SGD', 'Recurring bills'), "
                "(7, '2026-02-20 12:00:00+00:00', 11, -1780, 'EXPENSE', 'SGD', 'Dining'), "
                "(8, '2026-02-22 12:00:00+00:00', 11, -1210, 'EXPENSE', 'SGD', 'Groceries')"
            )
        )
    return True
