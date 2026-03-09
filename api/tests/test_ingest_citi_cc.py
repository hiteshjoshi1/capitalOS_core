import os
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.parsers import ParseResult
from app.ingestion.parsers.citi_credit_card_csv_v1 import parse_citi_credit_card_csv
from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature


def _fixture_path() -> Path:
    fixture_name = "citi_credit_card_sample.csv"
    override = os.getenv("CITI_CC_FIXTURE_PATH")
    candidates: list[Path] = []
    if override:
        candidates.append(Path(override))
    candidates.extend([
        # docker-compose api container mount.
        Path("/app/data/fixtures") / fixture_name,
        # Repo layout when running tests from host.
        Path(__file__).resolve().parents[2] / "data" / "fixtures" / fixture_name,
        # Container tests copied to /app/tests (WORKDIR=/app).
        Path(__file__).resolve().parents[1] / "data" / "fixtures" / fixture_name,
    ])
    for candidate in candidates:
        if str(candidate) and candidate.exists():
            return candidate
    # Return canonical container path for clearer failure messaging if still missing.
    return Path("/app/data/fixtures") / fixture_name


def test_parse_citi_credit_card_csv_fixture():
    result = parse_citi_credit_card_csv(str(_fixture_path()), ",")
    assert isinstance(result, ParseResult)
    assert len(result.transactions) == 51
    assert result.positions == []
    assert result.section_counts == {"transactions": 51}

    type_counts = Counter(tx["type"] for tx in result.transactions)
    assert type_counts == {
        "EXPENSE": 42,
        "TRANSFER": 2,
        "FEE": 2,
        "INTEREST": 4,
        "INCOME": 1,
    }

    assert result.transactions[0]["ts"].isoformat() == "2026-03-06T00:00:00+00:00"
    assert all(tx["currency"] == "SGD" for tx in result.transactions)

    payments = [tx for tx in result.transactions if "PAYMENT - THANK YOU" in tx["merchant_counterparty"]]
    assert len(payments) == 2
    assert all(tx["type"] == "TRANSFER" for tx in payments)
    assert all(tx["amount"] > 0 for tx in payments)

    fees = [tx for tx in result.transactions if "LATE CHARGE FEE" in tx["merchant_counterparty"]]
    assert len(fees) == 2
    assert {tx["type"] for tx in fees} == {"FEE"}
    assert sorted(tx["amount"] for tx in fees) == [-100.0, 100.0]

    interest = [
        tx
        for tx in result.transactions
        if "BILLED FINANCE CHARGES" in tx["merchant_counterparty"]
        or "RTL INT CRED ADJ" in tx["merchant_counterparty"]
    ]
    assert len(interest) == 4
    assert {tx["type"] for tx in interest} == {"INTEREST"}
    assert sorted(tx["amount"] for tx in interest) == [-88.31, -16.92, 16.92, 88.31]

    foreign_rows = [tx for tx in result.transactions if "OPENAI" in tx["merchant_counterparty"] or "FIREFLIES" in tx["merchant_counterparty"]]
    assert foreign_rows
    assert all("foreign_currency=USD" in (tx.get("notes") or "") for tx in foreign_rows)
    assert all("card_number=4147464004225540" in (tx.get("notes") or "") for tx in result.transactions)


def test_citi_ingest_upload_and_idempotent(client: TestClient, db_engine):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    fixture = _fixture_path()
    signature, debug = compute_format_signature(str(fixture), platform_hint="CITI")
    assert debug["file_kind"] == "citi_credit_card_csv"

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(500, 'Citi CC', 'CITI', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        db.commit()
        register_signature(db, signature, "citi_credit_card_csv_v1", 1)
    finally:
        db.close()

    with open(fixture, "rb") as f:
        resp = client.post(
            "/ingest/upload?account_id=500",
            files={"file": ("citi_credit_card_sample.csv", f, "text/csv")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["counts"]["transactions_parsed"] == 51
    assert data["counts"]["transactions_inserted"] == 51
    assert data["counts"]["duplicates_skipped"] == 0

    with open(fixture, "rb") as f:
        resp2 = client.post(
            "/ingest/upload?account_id=500",
            files={"file": ("citi_credit_card_sample.csv", f, "text/csv")},
        )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "IMPORTED"
    assert data2["counts"]["transactions_inserted"] == 0
    assert data2["counts"]["duplicates_skipped"] == 51

    db = Session()
    try:
        notes = db.execute(
            text(
                """
                SELECT notes
                FROM transactions
                WHERE account_id = 500 AND merchant_counterparty LIKE 'OPENAI %'
                LIMIT 1
                """
            )
        ).scalar()
    finally:
        db.close()

    assert isinstance(notes, str)
    assert "foreign_currency=USD 21.80" in notes
    assert "card_number=4147464004225540" in notes
