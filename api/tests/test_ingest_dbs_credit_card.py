import os
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.parsers import ParseResult
from app.ingestion.parsers.dbs_credit_card_csv_v1 import parse_dbs_credit_card_csv
from app.ingestion.registry import lookup_parser_key
from app.ingestion.signature import compute_format_signature


FULL_CARD_NUMBER = "5520-3800-5921-2403"


def _fixture_path() -> Path:
    fixture_name = "transaction_history_04072026_105429.csv"
    candidates = [
        Path("/app/data/fixtures") / fixture_name,
        Path(__file__).resolve().parents[2] / "data" / "fixtures" / fixture_name,
        Path(__file__).resolve().parents[1] / "data" / "fixtures" / fixture_name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("/app/data/fixtures") / fixture_name


def _next_account_id(db) -> int:
    return int(db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM accounts")).scalar())


def test_dbs_credit_card_signature_resolves_to_card_parser():
    fixture = _fixture_path()
    signature, debug = compute_format_signature(str(fixture), platform_hint="DBS")

    migration_candidates = [
        Path("/app/migrations/059_register_dbs_credit_card_parser_and_account.sql"),
        Path(__file__).resolve().parents[2] / "migrations" / "059_register_dbs_credit_card_parser_and_account.sql",
        Path(__file__).resolve().parents[1] / "migrations" / "059_register_dbs_credit_card_parser_and_account.sql",
    ]
    migration_path = next((candidate for candidate in migration_candidates if candidate.exists()), None)
    migration_sql = migration_path.read_text(encoding="utf-8") if migration_path else ""

    assert signature == "2c6766db5419e1fa6f96e4991f6f0bcd96b873f50c93a72ecfa367c47b81bd2a"
    if migration_sql:
        assert signature in migration_sql
    assert debug["file_kind"] == "flat_csv"
    assert "card transaction details for:" in debug["header"]
    assert (
        lookup_parser_key(None, signature, signature_debug=debug, platform_hint="DBS")
        == "dbs_credit_card_csv_v1"
    )


def test_parse_dbs_credit_card_csv_fixture():
    result = parse_dbs_credit_card_csv(str(_fixture_path()), ",")

    assert isinstance(result, ParseResult)
    assert len(result.transactions) == 11
    assert result.positions == []
    assert result.section_counts == {"transactions": 11}
    assert result.parser_meta == {
        "card_display_name": "DBS/POSB MasterCard Platinum",
        "card_last_four": "2403",
        "card_masked": "****-****-****-2403",
        "credit_limit": 60000.0,
        "available_limit": 59739.44,
        "transactions_as_at": "2026-07-04T00:00:00+00:00",
        "currency": "SGD",
    }

    type_counts = Counter(tx["type"] for tx in result.transactions)
    category_counts = Counter(tx["category"] for tx in result.transactions)
    assert type_counts == {"EXPENSE": 7, "FEE": 2, "TAX": 1, "INTEREST": 1}
    # All 7 purchases are SHENG SIONG → classified as "Groceries" by merchant categorizer
    assert category_counts == {
        "Groceries": 7,
        "CreditCard::Fee": 2,
        "CreditCard::Tax": 1,
        "CreditCard::Interest": 1,
    }

    assert result.transactions[0]["ts"].isoformat() == "2026-01-14T00:00:00+00:00"
    assert all(tx["currency"] == "SGD" for tx in result.transactions)
    assert all(tx["amount"] < 0 for tx in result.transactions)
    assert result.transactions[0]["merchant_counterparty"] == "FINANCE CHARGES"
    assert result.transactions[0]["type"] == "INTEREST"
    assert result.transactions[0]["amount"] == -16.73

    gst = [tx for tx in result.transactions if tx["merchant_counterparty"] == "GST @ 9%"]
    assert len(gst) == 1
    assert gst[0]["type"] == "TAX"
    assert gst[0]["amount"] == -16.2

    notes_blob = " ".join(str(tx.get("notes") or "") for tx in result.transactions)
    meta_blob = " ".join(str(value or "") for value in result.parser_meta.values())
    assert FULL_CARD_NUMBER not in notes_blob
    assert FULL_CARD_NUMBER not in meta_blob
    assert "card_last4=2403" in notes_blob
    assert "card_masked=****-****-****-2403" in notes_blob


def test_dbs_credit_card_ingest_upload_and_idempotent(client: TestClient, db_engine):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    fixture = _fixture_path()
    expected_signature, _ = compute_format_signature(str(fixture), platform_hint="DBS")

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        account_id = _next_account_id(db)
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(:id, 'DBS Credit Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
        db.execute(
            text(
                """
                INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day)
                VALUES (:account_id, 'DBS/POSB MasterCard Platinum (2403)', 'DBS', 60000, 14, 25)
                """
            ),
            {"account_id": account_id},
        )
        db.commit()
    finally:
        db.close()

    with open(fixture, "rb") as f:
        first = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("transaction_history_04072026_105429.csv", f, "text/csv")},
        )
    with open(fixture, "rb") as f:
        second = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("transaction_history_04072026_105429.csv", f, "text/csv")},
        )

    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["status"] == "IMPORTED"
    assert first_payload["format_signature"] == expected_signature
    assert first_payload["parser_key"] == "dbs_credit_card_csv_v1"
    assert first_payload["counts"]["transactions_parsed"] == 11
    assert first_payload["counts"]["transactions_inserted"] == 11
    assert first_payload["counts"]["duplicates_skipped"] == 0
    assert first_payload["parser_meta"]["card_masked"] == "****-****-****-2403"
    assert FULL_CARD_NUMBER not in str(first_payload["parser_meta"])
    assert FULL_CARD_NUMBER not in str(first_payload["preview_transactions"])

    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["status"] == "IMPORTED"
    assert second_payload["parser_key"] == "dbs_credit_card_csv_v1"
    assert second_payload["counts"]["transactions_inserted"] == 0
    assert second_payload["counts"]["duplicates_skipped"] == 11

    db = Session()
    try:
        rows = db.execute(
            text(
                """
                SELECT a.account_type, t.currency, t.type, t.amount, t.category, t.merchant_counterparty, t.notes
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE t.account_id = :account_id
                ORDER BY t.ts DESC, t.id
                """
            ),
            {"account_id": account_id},
        ).mappings().all()
        card_meta = db.execute(
            text(
                """
                SELECT credit_limit, available_limit, available_limit_as_of
                FROM credit_card_accounts
                WHERE account_id = :account_id
                """
            ),
            {"account_id": account_id},
        ).mappings().one()
    finally:
        db.close()

    assert len(rows) == 11
    assert {row["account_type"] for row in rows} == {"CREDIT_CARD"}
    assert {row["currency"] for row in rows} == {"SGD"}
    assert all(row["amount"] < 0 for row in rows)
    assert {row["type"] for row in rows} == {"EXPENSE", "FEE", "TAX", "INTEREST"}
    assert any(row["category"] == "CreditCard::Tax" for row in rows)
    assert any(row["category"] == "CreditCard::Interest" for row in rows)
    assert any(row["category"] == "CreditCard::Fee" for row in rows)
    assert all(FULL_CARD_NUMBER not in str(row["notes"] or "") for row in rows)
    assert float(card_meta["credit_limit"]) == 60000.0
    assert float(card_meta["available_limit"]) == 59739.44
    assert str(card_meta["available_limit_as_of"]).startswith("2026-07-04")
