"""Migration 082 (#301) on Postgres: account/card numbers in transaction notes are masked to
the last 4, the runner's fp suffix is kept byte for byte, and a second run changes nothing.
Synthetic numbers only."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from app.ingestion.masking import mask_account_numbers
from app.routers.health import _migrations_dir
from tests.postgres_support import pg_engine  # noqa: F401  (fixture)

pytestmark = pytest.mark.postgres

FP = "fp:" + "0123456789ab" * 5 + "0123"  # 64 hex, with 12-digit runs inside the hash
NOTES = [
    f"card_number=4111111111111111; posting_date=2026-11-02; description=GIRO PAYMENT | {FP}",
    f"Inward DR - GIRO | 4111 111111111111 | COLL 123456789012 | TEST CARD CENTRE | {FP}",
    f"card_number=5555-5555-5555-4444 | {FP}",
    f"reference=TEST000001; foreign_currency=USD 21.80 | {FP}",
    FP,
    "Imported before fingerprints: card 4111111111111111",
    None,
]


def _migration_sql() -> str:
    return (Path(_migrations_dir()) / "082_mask_card_numbers_in_transaction_notes.sql").read_text(encoding="utf-8")


def _seed(conn) -> list[int]:
    conn.execute(text(
        "INSERT INTO users (id, username, is_active, is_admin) VALUES (9301, 'mask301', true, false) "
        "ON CONFLICT DO NOTHING"
    ))
    account_id = conn.execute(text(
        "INSERT INTO accounts (name, platform, account_type, currency, country, user_id) "
        "VALUES ('Test card 301', 'UOB', 'CREDIT_CARD', 'SGD', 'SG', 9301) RETURNING id"
    )).scalar_one()
    ids = []
    for i, note in enumerate(NOTES):
        ids.append(conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, type, amount, currency, merchant_counterparty, notes, source) "
                "VALUES (now() - make_interval(days => :i), :a, 'EXPENSE', -1.0 - :i, 'SGD', 'TEST', :n, 'test') RETURNING id"
            ),
            {"i": i, "a": account_id, "n": note},
        ).scalar_one())
    return ids


def test_082_masks_notes_like_the_importer_and_keeps_the_fingerprint(pg_engine):  # noqa: F811
    with pg_engine.begin() as conn:
        ids = _seed(conn)
    with pg_engine.begin() as conn:
        conn.exec_driver_sql(_migration_sql())
    with pg_engine.connect() as conn:
        got = [conn.execute(text("SELECT notes FROM transactions WHERE id = :i"), {"i": i}).scalar_one() for i in ids]

    expected = []
    for note in NOTES:
        if note is None or note == FP:
            expected.append(note)
        elif note.endswith(" | " + FP):
            expected.append(mask_account_numbers(note[: -len(" | " + FP)]) + " | " + FP)
        else:
            expected.append(mask_account_numbers(note))
    assert got == expected  # the same rule as masking.py, the hash untouched
    assert got[0].startswith("card_number=************1111; posting_date=2026-11-02;")
    assert got[1].startswith("Inward DR - GIRO | **** ********1111 | COLL ********9012 |")
    assert got[2].startswith("card_number=****-****-****-4444 |")
    assert got[3] == NOTES[3]

    with pg_engine.begin() as conn:  # idempotent
        conn.exec_driver_sql(_migration_sql())
    with pg_engine.connect() as conn:
        again = [conn.execute(text("SELECT notes FROM transactions WHERE id = :i"), {"i": i}).scalar_one() for i in ids]
    assert again == got
