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
              amount REAL NOT NULL,
              type TEXT NOT NULL,
              currency TEXT NOT NULL
            )
            """
        )
    yield
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS transactions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS positions")
        conn.exec_driver_sql("DROP TABLE IF EXISTS assets")
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clear_db():
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM accounts")
        conn.exec_driver_sql("DELETE FROM platforms")
        conn.exec_driver_sql("DELETE FROM positions")
        conn.exec_driver_sql("DELETE FROM assets")
        conn.exec_driver_sql("DELETE FROM transactions")
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
                "INSERT INTO assets (id, symbol, asset_class, home_country) VALUES "
                "(1, 'AAPL', 'STOCK', 'US'), "
                "(2, 'BTC', 'CRYPTO', 'GLOBAL'), "
                "(3, 'CASH', 'CASH', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO positions (id, asset_id, as_of, cost_basis_base) VALUES "
                "(1, 1, :as_of_cur, 50000), "
                "(2, 2, :as_of_cur, 20000), "
                "(3, 3, :as_of_cur, 30000), "
                "(4, 1, :as_of_prev, 45000), "
                "(5, 2, :as_of_prev, 15000), "
                "(6, 3, :as_of_prev, 30000)"
            ),
            {"as_of_cur": as_of_cur, "as_of_prev": as_of_prev},
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, amount, type, currency) VALUES "
                "(1, '2026-02-05 12:00:00+00:00', 5000, 'INCOME', 'SGD'), "
                "(2, '2026-02-10 12:00:00+00:00', -2000, 'EXPENSE', 'SGD'), "
                "(3, '2026-02-20 12:00:00+00:00', -100, 'FEE', 'SGD'), "
                "(4, '2026-02-15 12:00:00+00:00', 999, 'INCOME', 'USD')"
            )
        )
    return {"as_of_cur": as_of_cur, "as_of_prev": as_of_prev}
