import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.registry import lookup_parser_key
from app.ingestion.signature import compute_format_signature


def _fixture_path() -> Path:
    fixture_name = "UOB_ACC_TXN_History_09032026225218.xls"
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


def test_uob_signature_stable_and_matches_registered_source():
    fixture = _fixture_path()

    sig_one, debug_one = compute_format_signature(str(fixture), platform_hint="UOB")
    sig_two, debug_two = compute_format_signature(str(fixture), platform_hint="UOB")

    migration_candidates = [
        Path("/app/migrations/023_register_uob_account_parser.sql"),
        Path(__file__).resolve().parents[2] / "migrations" / "023_register_uob_account_parser.sql",
        Path(__file__).resolve().parents[1] / "migrations" / "023_register_uob_account_parser.sql",
    ]
    migration_path = next((candidate for candidate in migration_candidates if candidate.exists()), None)
    migration_sql = migration_path.read_text(encoding="utf-8") if migration_path else None

    assert sig_one == sig_two
    assert debug_one == debug_two
    assert debug_one["file_kind"] == "excel"
    assert debug_one["header_row_index"] == 7
    assert debug_one["header"] == [
        "transaction date",
        "transaction description",
        "withdrawal",
        "deposit",
        "available balance",
    ]
    if migration_sql is not None:
        assert sig_one in migration_sql
    else:
        assert sig_one == "d648dffea3a088441247548b7e50a3cf9e338efc1571aa0b37d8b625ee783770"
    assert (
        lookup_parser_key(None, sig_one, signature_debug=debug_one, platform_hint="UOB")
        == "uob_account_xls_v1"
    )


def test_uob_lookup_accepts_header_with_overflow_columns_even_without_platform_hint():
    debug = {
        "file_kind": "excel",
        "header": [
            "transaction date",
            "transaction description",
            "withdrawal",
            "deposit",
            "available balance",
            "",
            "Unnamed: 5",
        ],
    }

    assert lookup_parser_key(None, "sig-uob-overflow", signature_debug=debug, platform_hint="BANK") == "uob_account_xls_v1"


def test_uob_ingest_upload_and_import(client: TestClient, db_engine):
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
                "(:id, 'UOB One', 'UOB', 'BANK', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
        db.commit()
    finally:
        db.close()

    with open(fixture, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("uob_account.xls", f, "application/vnd.ms-excel")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["format_signature"] == expected_signature
    assert data["parser_key"] == "uob_account_xls_v1"
    assert data["counts"]["transactions_parsed"] == 3
    assert data["counts"]["transactions_inserted"] == 3
    assert data["counts"]["duplicates_skipped"] == 0
    assert data["counts"]["positions_parsed"] == 1
    assert data["counts"]["positions_inserted"] == 1

    db = Session()
    try:
        tx_count = db.execute(
            text("SELECT COUNT(*) FROM transactions WHERE account_id = :account_id"),
            {"account_id": account_id},
        ).scalar()
        pos_count = db.execute(
            text("SELECT COUNT(*) FROM positions WHERE account_id = :account_id"),
            {"account_id": account_id},
        ).scalar()
    finally:
        db.close()

    assert tx_count == 3
    assert pos_count == 1


def test_uob_ingest_idempotent(client: TestClient, db_engine):
    fixture = _fixture_path()
    expected_signature, _ = compute_format_signature(str(fixture), platform_hint="UOB")

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        account_id = _next_account_id(db)
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(:id, 'UOB One', 'UOB', 'BANK', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
        db.commit()
    finally:
        db.close()

    with open(fixture, "rb") as f:
        first = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("uob_account.xls", f, "application/vnd.ms-excel")},
        )
    with open(fixture, "rb") as f:
        second = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("uob_account.xls", f, "application/vnd.ms-excel")},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    payload = second.json()
    assert payload["status"] == "IMPORTED"
    assert payload["format_signature"] == expected_signature
    assert payload["counts"]["transactions_inserted"] == 0
    assert payload["counts"]["duplicates_skipped"] == 3

    db = Session()
    try:
        pos_count = db.execute(
            text("SELECT COUNT(*) FROM positions WHERE account_id = :account_id"),
            {"account_id": account_id},
        ).scalar()
    finally:
        db.close()

    assert pos_count == 1


def test_uob_ingest_upload_with_legacy_platform_label(client: TestClient, db_engine):
    fixture = _fixture_path()

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        account_id = _next_account_id(db)
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(:id, 'UOB One', 'UOB One Account', 'BANK', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
        db.commit()
    finally:
        db.close()

    with open(fixture, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("uob_account.xls", f, "application/vnd.ms-excel")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["parser_key"] == "uob_account_xls_v1"
    assert data["counts"]["transactions_parsed"] == 3
    assert data["counts"]["transactions_inserted"] == 3
    assert data["counts"]["positions_inserted"] == 1
