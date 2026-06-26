import os
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.parsers.ocbc_account_csv_v1 import parse_ocbc_account_csv
from app.ingestion.registry import lookup_parser_key
from app.ingestion.signature import compute_format_signature


def _fixture_path() -> Path:
    fixture_name = "ocbc_TransactionHistory_20260313165630.csv"
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


def test_ocbc_parser_extracts_metadata():
    result = parse_ocbc_account_csv(str(_fixture_path()))

    assert result.parser_meta["account_name"] == "360 Account 511-558900-001"
    assert result.parser_meta["available_balance"] == 25136.91
    assert result.parser_meta["ledger_balance"] == 25136.91
    assert result.parser_meta["currency"] == "SGD"


def test_ocbc_parser_extracts_transactions():
    result = parse_ocbc_account_csv(str(_fixture_path()))

    assert len(result.transactions) == 20
    assert result.section_counts["transactions"] == 20

    first = result.transactions[0]
    assert first["ts"].date().isoformat() == "2026-03-10"
    assert first["amount"] == 7.27
    assert first["type"] == "INCOME"
    assert first["merchant_counterparty"] == "BONUS INTEREST 360 SAVE BONUS"

    salary = next(tx for tx in result.transactions if tx["ts"].date().isoformat() == "2026-03-03")
    assert salary["amount"] == 1500.0
    assert salary["type"] == "TRANSFER"
    assert salary["merchant_counterparty"] == "IBG GIRO SI SALARY JOSHI HITESH OTHR"

    withdrawal = next(tx for tx in result.transactions if tx["merchant_counterparty"].startswith("CASH WITHDRAWAL"))
    assert withdrawal["amount"] == -100.0
    assert withdrawal["type"] == "EXPENSE"


def test_ocbc_parser_multiline_description(tmp_path: Path):
    fixture = tmp_path / "ocbc_multiline.csv"
    fixture.write_text(
        (
            "Account details for:,360 Account 511-558900-001\n"
            "Available Balance,100.00\n"
            "Ledger Balance,100.00\n"
            "Transaction date,Value date,Description,Withdrawals(SGD),Deposits(SGD)\n"
            "\"10/03/2026\",\"10/03/2026\",\"FUND TRANSFER\n"
            "OTHR - REF 123 via PayNow-QR Code\",14.00,\n"
        ),
        encoding="utf-8",
    )

    result = parse_ocbc_account_csv(str(fixture))

    assert len(result.transactions) == 1
    assert result.transactions[0]["merchant_counterparty"] == "FUND TRANSFER OTHR - REF 123 via PayNow-QR Code"
    assert result.transactions[0]["type"] == "TRANSFER"


def test_ocbc_parser_transfer_classification():
    result = parse_ocbc_account_csv(str(_fixture_path()))
    types_by_prefix = {tx["merchant_counterparty"].split()[0]: tx["type"] for tx in result.transactions}

    assert types_by_prefix["BONUS"] == "INCOME"
    assert types_by_prefix["INTEREST"] == "INCOME"
    assert types_by_prefix["NETS"] == "EXPENSE"
    assert types_by_prefix["FAST"] == "TRANSFER"
    assert types_by_prefix["FUND"] == "TRANSFER"
    assert types_by_prefix["IBG"] == "TRANSFER"


def test_ocbc_parser_cash_position():
    result = parse_ocbc_account_csv(str(_fixture_path()))

    assert len(result.positions) == 1
    assert result.positions[0]["asset_class"] == "CASH"
    assert result.positions[0]["currency"] == "SGD"
    assert result.positions[0]["quantity"] == 25136.91


def test_ocbc_parser_empty_file(tmp_path: Path):
    fixture = tmp_path / "ocbc_empty.csv"
    fixture.write_text(
        (
            "Account details for:,360 Account 511-558900-001\n"
            "Available Balance,25,136.91\n"
            "Ledger Balance,25,136.91\n"
            "Transaction date,Value date,Description,Withdrawals(SGD),Deposits(SGD)\n"
        ),
        encoding="utf-8",
    )

    result = parse_ocbc_account_csv(str(fixture))

    assert result.transactions == []
    assert result.section_counts["transactions"] == 0
    assert len(result.positions) == 1


def test_ocbc_signature_stable_and_matches_registered_source():
    fixture = _fixture_path()

    sig_one, debug_one = compute_format_signature(str(fixture), platform_hint="OCBC")
    sig_two, debug_two = compute_format_signature(str(fixture), platform_hint="OCBC")

    migration_candidates = [
        Path("/app/migrations/026_register_ocbc_account_parser.sql"),
        Path(__file__).resolve().parents[2] / "migrations" / "026_register_ocbc_account_parser.sql",
        Path(__file__).resolve().parents[1] / "migrations" / "026_register_ocbc_account_parser.sql",
    ]
    migration_path = next((candidate for candidate in migration_candidates if candidate.exists()), None)
    migration_sql = migration_path.read_text(encoding="utf-8") if migration_path else None

    assert sig_one == sig_two == "49291988f2110dd6431bf71a286f2192c98fba692608468006d052b33022423f"
    assert debug_one == debug_two
    assert debug_one["file_kind"] == "flat_csv"
    assert debug_one["header"] == [
        "transaction date",
        "value date",
        "description",
        "withdrawals(sgd)",
        "deposits(sgd)",
    ]
    if migration_sql is not None:
        assert sig_one in migration_sql
    assert lookup_parser_key(None, sig_one, signature_debug=debug_one, platform_hint="BANK") == "ocbc_account_csv_v1"


def test_ocbc_ingest_upload_and_import(client: TestClient, db_engine):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    fixture = _fixture_path()
    expected_signature, _ = compute_format_signature(str(fixture), platform_hint="OCBC")

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        account_id = _next_account_id(db)
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(:id, 'OCBC 360', 'OCBC', 'BANK', 'SGD', 'SG')"
            ),
            {"id": account_id},
        )
        db.commit()
    finally:
        db.close()

    with open(fixture, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("ocbc_account.csv", f, "text/csv")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["format_signature"] == expected_signature
    assert data["parser_key"] == "ocbc_account_csv_v1"
    assert data["counts"]["transactions_parsed"] == 20
    assert data["counts"]["transactions_inserted"] == 20
    assert data["counts"]["duplicates_skipped"] == 0
    assert data["counts"]["positions_parsed"] == 1
    assert data["counts"]["positions_inserted"] == 0
    assert data["counts"].get("canonical_balances_written", 0) >= 1

    with open(fixture, "rb") as f:
        resp_two = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("ocbc_account.csv", f, "text/csv")},
        )

    assert resp_two.status_code == 200
    payload = resp_two.json()
    assert payload["status"] == "IMPORTED"
    assert payload["counts"]["transactions_inserted"] == 0
    assert payload["counts"]["duplicates_skipped"] == 20

    db = Session()
    try:
        tx_count = db.execute(
            text("SELECT COUNT(*) FROM transactions WHERE account_id = :account_id"),
            {"account_id": account_id},
        ).scalar()
        pos_count = db.execute(
            text("SELECT COUNT(*) FROM account_balance_snapshots WHERE account_id = :account_id"),
            {"account_id": account_id},
        ).scalar()
        position_as_of = db.execute(
            text("SELECT as_of_date FROM account_balance_snapshots WHERE account_id = :account_id LIMIT 1"),
            {"account_id": account_id},
        ).scalar()
    finally:
        db.close()

    assert tx_count == 20
    assert pos_count >= 1
    assert position_as_of is not None
