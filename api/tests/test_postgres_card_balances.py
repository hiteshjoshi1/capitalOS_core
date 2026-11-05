"""#207 on Postgres: migration 078's backfill of card statement balances, the card
balance upsert, and closed accounts in the as-of readers (real DATE types)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ingestion.card_balances import write_card_statement_balance
from app.routers.health import _migrations_dir
from app.valuation.clock import _anchor_ts
from app.valuation.facts import _networth_components
from tests.auth_helpers import ensure_user, signed_in_client
from tests.postgres_support import pg_engine  # noqa: F401  (fixture)

pytestmark = pytest.mark.postgres

OWNER = 92071
CARD = 92171
BANK = 92172
MIGRATION_078 = "078_account_closed_on_and_card_statement_balances.sql"


def _accounts(engine) -> None:
    ensure_user(engine, OWNER)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:card, 'Synthetic Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG', :u), "
                "(:bank, 'Synthetic Bank', 'DBS', 'BANK', 'SGD', 'SG', :u)"
            ),
            {"card": CARD, "bank": BANK, "u": OWNER},
        )


def _card_balances(engine) -> list[tuple[date, float, str]]:
    with engine.connect() as conn:
        return [
            (r[0], float(r[1]), r[2])
            for r in conn.execute(
                text(
                    "SELECT as_of_date, balance_local, source_kind FROM account_balance_snapshots "
                    "WHERE account_id = :a AND balance_type = 'credit_balance' ORDER BY as_of_date"
                ),
                {"a": CARD},
            )
        ]


def test_migration_078_backfills_the_current_limits_once(pg_engine):  # noqa: F811
    _accounts(pg_engine)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, available_limit, "
                "available_limit_as_of, statement_day, due_day) VALUES (:a, 'Synthetic', 'DBS', 10000, 9200, :t, 28, 15)"
            ),
            {"a": CARD, "t": datetime(2026, 3, 27, tzinfo=timezone.utc)},
        )
    sql = (Path(_migrations_dir()) / MIGRATION_078).read_text(encoding="utf-8")
    with pg_engine.begin() as conn:
        conn.exec_driver_sql(sql)
    assert _card_balances(pg_engine) == [(date(2026, 3, 27), -800.0, "backfill")]
    with pg_engine.connect() as conn:
        assert conn.execute(text("SELECT from_date FROM wealth_rollup_dirty WHERE user_id = :u"), {"u": OWNER}).scalar() == date(2026, 3, 27)
    # Re-running changes no row.
    with pg_engine.begin() as conn:
        conn.exec_driver_sql(sql)
    assert _card_balances(pg_engine) == [(date(2026, 3, 27), -800.0, "backfill")]

    # The liability reads it exactly as it read the limits before (anchor on/after the date).
    db = Session(bind=pg_engine)
    try:
        assert _networth_components(db, _anchor_ts(datetime(2026, 3, 1, tzinfo=timezone.utc)), "SGD", OWNER)[
            "liabilities"
        ] == pytest.approx(800.0)
    finally:
        db.close()


def test_card_statement_upsert_and_closed_account(pg_engine):  # noqa: F811
    _accounts(pg_engine)
    meta = {"credit_limit": 10000, "available_limit": 8500, "transactions_as_at": "2026-02-26T00:00:00+00:00"}
    db = Session(bind=pg_engine)
    try:
        write_card_statement_balance(db, account_id=CARD, import_job_id=None, parser_key="dbs_credit_card_csv_v1", parser_meta=meta)
        write_card_statement_balance(
            db, account_id=CARD, import_job_id=None, parser_key="dbs_credit_card_csv_v1",
            parser_meta={**meta, "available_limit": 8400},
        )
        db.execute(
            text(
                "INSERT INTO account_balance_snapshots (account_id, as_of_date, currency, balance_type, balance_local, "
                "balance_base, source_kind) VALUES (:a, '2026-01-20', 'SGD', 'bank_cash', 1000, 1000, 'upload_parser')"
            ),
            {"a": BANK},
        )
        db.commit()
    finally:
        db.close()
    assert _card_balances(pg_engine) == [(date(2026, 2, 26), -1600.0, "upload_parser")]

    feb_anchor = _anchor_ts(datetime(2026, 2, 1, tzinfo=timezone.utc))

    def components() -> dict:
        db = Session(bind=pg_engine)
        try:
            return _networth_components(db, feb_anchor, "SGD", OWNER)
        finally:
            db.close()

    before = components()
    assert before["liabilities"] == pytest.approx(1600.0)
    assert before["cash"] > 0

    client = signed_in_client(pg_engine, OWNER)
    for account_id in (CARD, BANK):
        resp = client.patch(f"/accounts/{account_id}", json={"closed_on": "2026-02-27"})
        assert resp.status_code == 200, resp.text
    after = components()
    assert after["liabilities"] == 0.0 and after["cash"] == 0.0
    listed = {a["id"]: a for a in client.get("/accounts?month=2026-01").json()}
    assert listed[BANK]["closed_on"] == "2026-02-27"
    assert listed[BANK]["last_data_as_of"] == "2026-01-20"
