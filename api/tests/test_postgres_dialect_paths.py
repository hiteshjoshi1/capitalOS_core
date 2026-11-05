"""Code that branches on the database dialect, run on its Postgres branch (#154, #130 9.1).

The default suite runs on SQLite, so these branches never ran in a test before: the
ON CONFLICT upserts (market data, uploaded balances), the upload's advisory lock and
dedup, the upload undo, and the valuation cache's WAL watermark. Each test gets a fresh
copy of the migrated database (tests/postgres_support.py). The cross-user sweep in
test_cross_user_isolation.py covers the read routes, the IBKR Flex import and the
History rollup write on Postgres.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import valuation_cache
from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature
from app.market_data.service import _upsert_dividend_snapshot, _upsert_price
from tests.auth_helpers import signed_in_client
from tests.postgres_support import pg_engine  # noqa: F401  (fixture)

pytestmark = pytest.mark.postgres

OWNER = 92001
BANK = 92101


def _asset(engine, symbol: str = "SYNTH154", currency: str = "USD") -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO assets (symbol, name, asset_class, quote_currency, home_country) "
                "VALUES (:s, 'Synthetic Co', 'STOCK', :c, 'US') RETURNING id"
            ),
            {"s": symbol, "c": currency},
        ).scalar_one()


def test_price_upsert_updates_the_days_row(pg_engine):  # noqa: F811
    asset_id = _asset(pg_engine)
    kwargs = dict(asset_id=asset_id, trade_date=date(2026, 3, 16), currency="USD", source="synthetic",
                  exchange_code="US", provider_symbol="SYNTH154")
    with Session(bind=pg_engine) as db:
        assert _upsert_price(db, price=101.5, **kwargs) is True
        assert _upsert_price(db, price=102.25, **kwargs) is True
        db.commit()
    with pg_engine.connect() as conn:
        rows = conn.execute(text("SELECT price FROM prices WHERE asset_id = :a"), {"a": asset_id}).scalars().all()
    assert [float(p) for p in rows] == [102.25]


def test_dividend_yield_upsert_updates_the_days_row(pg_engine):  # noqa: F811
    asset_id = _asset(pg_engine)
    kwargs = dict(asset_id=asset_id, as_of_date=date(2026, 3, 16), annual_dividend_per_share=2.0, price=100.0,
                  currency="USD", source="synthetic", exchange_code="US", provider_symbol="SYNTH154")
    with Session(bind=pg_engine) as db:
        assert _upsert_dividend_snapshot(db, yield_rate=0.02, **kwargs) is True
        assert _upsert_dividend_snapshot(db, yield_rate=0.025, **kwargs) is True
        db.commit()
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT yield_rate FROM market_dividend_yields WHERE asset_id = :a"), {"a": asset_id}
        ).scalars().all()
    assert [float(y) for y in rows] == [0.025]


def test_cache_watermark_moves_on_a_committed_write(pg_engine):  # noqa: F811
    with Session(bind=pg_engine) as db:
        first = valuation_cache._db_watermark(db)
        assert isinstance(first, str) and "/" in first  # a WAL position, e.g. "0/1A2B3C4"
    _asset(pg_engine)
    with Session(bind=pg_engine) as db:
        assert valuation_cache._db_watermark(db) != first


_DBS_CSV = (
    "Account Details For:,Test Savings 012-345678-9\n"
    "Statement as at:,19 Feb 2026\n"
    "Currency:,SGD - Singapore Dollar\n"
    "Available Balance:,SGD 1700.00\n"
    "Ledger Balance:,SGD 1700.00\n"
    "Transaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,"
    "Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n"
    "12 Feb 2026,12 Feb 2026,POS,Synthetic grocer,,,REF,OTHR,Settled,SGD,12.30,\n"
    "19 Feb 2026,19 Feb 2026,GR,Test salary,IBG,Payments,REF,OTHR,Settled,SGD,,500\n"
)


def _upload(client, path: Path):
    with open(path, "rb") as f:
        return client.post(f"/ingest/upload?account_id={BANK}", files={"file": (path.name, f, "text/csv")})


def _counts(engine) -> dict[str, int]:
    with engine.connect() as conn:
        return {
            "transactions": conn.execute(text("SELECT COUNT(*) FROM transactions WHERE account_id = :a"), {"a": BANK}).scalar_one(),
            "balances": conn.execute(
                text("SELECT COUNT(*) FROM account_balance_snapshots WHERE account_id = :a"), {"a": BANK}
            ).scalar_one(),
        }


def test_bank_upload_dedups_and_removes_cleanly(pg_engine, tmp_path):  # noqa: F811
    """The upload write path on Postgres: advisory lock, inserts, the balance upsert (ON
    CONFLICT, CAST ... AS jsonb), dedup on a second upload, then the undo."""
    client = signed_in_client(pg_engine, OWNER)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) "
                "VALUES (:id, 'Test DBS Savings', 'DBS', :u, 'BANK', 'SGD', 'SG')"
            ),
            {"id": BANK, "u": OWNER},
        )
    statement = tmp_path / "dbs.csv"
    statement.write_text(_DBS_CSV, encoding="utf-8")
    with Session(bind=pg_engine) as db:
        signature, _ = compute_format_signature(str(statement), platform_hint="DBS")
        register_signature(db, signature, "dbs_transaction_history_csv_v1", 1)

    first = _upload(client, statement)
    assert first.status_code == 200, first.text
    assert first.json()["counts"]["transactions_inserted"] == 2
    assert _counts(pg_engine) == {"transactions": 2, "balances": 1}

    again = _upload(client, statement)
    assert again.status_code == 200, again.text
    assert again.json()["counts"]["transactions_inserted"] == 0
    assert _counts(pg_engine) == {"transactions": 2, "balances": 1}

    for job in (again.json(), first.json()):
        removed = client.post(f"/ingest/jobs/{job['job_id']}/remove")
        assert removed.status_code == 200, removed.text
    assert _counts(pg_engine) == {"transactions": 0, "balances": 0}
