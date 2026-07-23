import os
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.parsers import ParseResult
from app.ingestion.parsers.uob_credit_card_xls_v1 import parse_uob_credit_card_xls
from app.ingestion.registry import lookup_parser_key
from app.ingestion.signature import compute_format_signature


def _fixture_path() -> Path:
    fixture_name = "UOB_CC_TXN_History_09032026222725.xls"
    return Path(__file__).resolve().parent / "fixtures" / fixture_name


def _next_account_id(db) -> int:
    return int(db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM accounts")).scalar())


def test_uob_cc_signature_stable_and_matches_registered_source():
    fixture = _fixture_path()

    sig_one, debug_one = compute_format_signature(str(fixture), platform_hint="UOB")
    sig_two, debug_two = compute_format_signature(str(fixture), platform_hint="UOB")

    migration_candidates = [
        Path("/app/migrations/025_register_uob_cc_parser.sql"),
        Path(__file__).resolve().parents[2] / "migrations" / "025_register_uob_cc_parser.sql",
        Path(__file__).resolve().parents[1] / "migrations" / "025_register_uob_cc_parser.sql",
    ]
    migration_path = next((candidate for candidate in migration_candidates if candidate.exists()), None)
    migration_sql = migration_path.read_text(encoding="utf-8") if migration_path else None

    assert sig_one == sig_two
    assert debug_one == debug_two
    assert debug_one["file_kind"] == "excel"
    assert debug_one["header_row_index"] == 9
    assert debug_one["header"] == [
        "transaction date",
        "posting date",
        "description",
        "foreign currency type",
        "transaction amount(foreign)",
        "local currency type",
        "transaction amount(local)",
    ]
    assert debug_one["type_profile"] == ["text", "text", "text", "empty", "empty", "text", "num"]
    if migration_sql is not None:
        assert sig_one in migration_sql
    else:
        assert sig_one == "4074417c4582687ecaeaeb5f0e8e6dda8a4bde42d801d613ef77d1852c912ef5"
    assert (
        lookup_parser_key(None, sig_one, signature_debug=debug_one, platform_hint="UOB")
        == "uob_credit_card_xls_v1"
    )


def test_uob_cc_lookup_accepts_header_with_overflow_columns_even_without_platform_hint():
    debug = {
        "file_kind": "excel",
        "header": [
            "transaction date",
            "posting date",
            "description",
            "foreign currency type",
            "transaction amount(foreign)",
            "local currency type",
            "transaction amount(local)",
            "",
            "Unnamed: 7",
        ],
    }

    assert (
        lookup_parser_key(None, "sig-uob-cc-overflow", signature_debug=debug, platform_hint="BANK")
        == "uob_credit_card_xls_v1"
    )


def test_parse_uob_credit_card_xls_fixture():
    result = parse_uob_credit_card_xls(str(_fixture_path()))
    assert isinstance(result, ParseResult)
    assert len(result.transactions) == 11
    assert result.positions == []
    assert result.section_counts == {"transactions": 11}

    type_counts = Counter(tx["type"] for tx in result.transactions)
    assert type_counts == {"EXPENSE": 10, "TRANSFER": 1}

    assert result.transactions[0]["ts"].isoformat() == "2026-02-06T00:00:00+00:00"
    assert all(tx["currency"] == "SGD" for tx in result.transactions)
    # Parser now emits merchant-based categories (e.g. "Dining") for known merchants
    # and "CreditCard::Purchase" for unknowns; "CreditCard::Payment" for transfers.
    VALID_CATEGORIES = {
        "CreditCard::Purchase", "CreditCard::Payment", "CreditCard::Fee",
        "CreditCard::Interest", "CreditCard::Refund",
        "Dining", "Groceries", "Transport", "Travel",
        "Subscriptions", "Shopping", "Utilities", "Medical",
    }
    assert all(tx["category"] in VALID_CATEGORIES for tx in result.transactions)

    first_tx = result.transactions[0]
    assert first_tx["merchant_counterparty"] == "TEST CAFE SINGAPORE SG"
    assert "card_number=4111111111111111" in (first_tx["notes"] or "")
    assert "posting_date=2026-02-09" in (first_tx["notes"] or "")
    assert "reference=TEST000001" in (first_tx["notes"] or "")

    payment_rows = [tx for tx in result.transactions if tx["type"] == "TRANSFER"]
    assert len(payment_rows) == 1
    assert payment_rows[0]["merchant_counterparty"] == "GIRO PAYMENT"
    assert payment_rows[0]["amount"] == 424.03
    assert payment_rows[0]["category"] == "CreditCard::Payment"

    assert result.parser_meta == {
        "sheet_name": "Sheet0",
        "header_row_index": 9,
        "account_number": "4111111111111111",
        "account_type": "UOB TEST CARD",
        "currency": "SGD",
        "statement_date": "2026-02-12T00:00:00+00:00",
        "statement_balance": 321.84,
    }


def test_uob_cc_ingest_upload_and_idempotent(client: TestClient, db_engine):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    fixture = _fixture_path()
    expected_signature, _ = compute_format_signature(str(fixture), platform_hint="UOB")

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        account_id = _next_account_id(db)
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(:id, 'UOB One Card', 'UOB', 'CREDIT_CARD', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
        db.execute(
            text(
                """
                INSERT INTO credit_card_accounts (account_id, card_name, issuer, credit_limit, statement_day, due_day)
                VALUES (:account_id, 'UOB One Card', 'UOB', 5000, 12, 28)
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
            files={"file": ("uob_credit_card.xls", f, "application/vnd.ms-excel")},
        )
    with open(fixture, "rb") as f:
        second = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("uob_credit_card.xls", f, "application/vnd.ms-excel")},
        )

    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["status"] == "IMPORTED"
    assert first_payload["format_signature"] == expected_signature
    assert first_payload["parser_key"] == "uob_credit_card_xls_v1"
    assert first_payload["counts"]["transactions_parsed"] == 11
    assert first_payload["counts"]["transactions_inserted"] == 11
    assert first_payload["counts"]["duplicates_skipped"] == 0

    detail_resp = client.get("/spending/credit-card-transactions?month=2026-02&base_currency=SGD")
    assert detail_resp.status_code == 200
    detail_payload = detail_resp.json()
    assert detail_payload["total_spend"] == 99.62
    assert detail_payload["cards"][0]["card_name"] == "UOB One Card"
    assert detail_payload["transactions"][0]["description"] == "TEST CAFE SINGAPORE SG"
    assert detail_payload["top_purchases"][0]["description"] == "NTUC FAIRPRICE TEST STORE"
    assert detail_payload["recurring_payments"] == []

    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["status"] == "IMPORTED"
    assert second_payload["format_signature"] == expected_signature
    assert second_payload["counts"]["transactions_inserted"] == 0
    assert second_payload["counts"]["duplicates_skipped"] == 11

    db = Session()
    try:
        tx_count = db.execute(
            text("SELECT COUNT(*) FROM transactions WHERE account_id = :account_id"),
            {"account_id": account_id},
        ).scalar()
        notes = db.execute(
            text(
                """
                SELECT notes
                FROM transactions
                WHERE account_id = :account_id
                  AND merchant_counterparty = 'TEST CAFE SINGAPORE SG'
                LIMIT 1
                """
            ),
            {"account_id": account_id},
        ).scalar()
    finally:
        db.close()

    assert tx_count == 11
    assert isinstance(notes, str)
    assert "card_number=4111111111111111" in notes
    assert "reference=TEST000001" in notes
