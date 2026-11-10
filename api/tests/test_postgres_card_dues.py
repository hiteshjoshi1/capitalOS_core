"""#352 on Postgres: migration 084's card_statement_dues (real DATE/NUMERIC types, its
checks), the upsert and the newest-due read. Synthetic data only."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.valuation.card_dues import load_due_records, write_due
from tests.auth_helpers import ensure_user
from tests.postgres_support import pg_engine  # noqa: F401  (fixture)

pytestmark = pytest.mark.postgres

OWNER = 93521
CARD = 93522


def test_dues_upsert_and_read_on_postgres(pg_engine):  # noqa: F811
    ensure_user(pg_engine, OWNER)
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:a, 'Synthetic Card', 'CITI', 'CREDIT_CARD', 'SGD', 'SG', :u)"
            ),
            {"a": CARD, "u": OWNER},
        )
    db = Session(bind=pg_engine)
    try:
        write_due(db, account_id=CARD, statement_date=date(2026, 10, 2), due_date=date(2026, 10, 27),
                  amount_due=120.5, minimum_due=50, source="manual")
        write_due(db, account_id=CARD, statement_date=date(2026, 11, 2), due_date=date(2026, 11, 26),
                  amount_due=None, minimum_due=None, source="manual")
        # The same statement again: updated in place, not a second row.
        write_due(db, account_id=CARD, statement_date=date(2026, 11, 2), due_date=date(2026, 11, 27),
                  amount_due=99.99, minimum_due=None, source="manual")
        db.commit()
        record = load_due_records(db, OWNER, today=date(2026, 11, 20))[CARD]
        assert (record.statement_date, record.due_date, record.amount_due) == (
            date(2026, 11, 2), date(2026, 11, 27), 99.99
        )
        count = db.execute(text("SELECT count(*) FROM card_statement_dues WHERE account_id = :a"), {"a": CARD}).scalar()
        assert count == 2
        with pytest.raises(IntegrityError):
            db.execute(
                text(
                    "INSERT INTO card_statement_dues (account_id, statement_date, due_date, source) "
                    "VALUES (:a, DATE '2026-12-02', DATE '2026-12-01', 'manual')"
                ),
                {"a": CARD},
            )
        db.rollback()
    finally:
        db.execute(text("DELETE FROM card_statement_dues WHERE account_id = :a"), {"a": CARD})
        db.execute(text("DELETE FROM accounts WHERE id = :a"), {"a": CARD})
        db.commit()
        db.close()
