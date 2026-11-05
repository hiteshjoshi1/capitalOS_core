"""#181: bank uploads store the LEDGER balance. Available = ledger minus funds on hold,
which still belong to the owner, so storing available understated cash and net worth.
Synthetic statements only."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.parsers.dbs_transaction_history_csv_v1 import parse_dbs_transaction_history_csv
from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature
from app.ingestion.parsers.ocbc_account_csv_v1 import parse_ocbc_account_csv

ACCOUNT_ID = 952

_DBS_COLUMNS = (
    "Transaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,"
    "Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n"
)
_DBS_ROW = "19 Feb 2026,19 Feb 2026,GR,Test salary,IBG,Payments,REF,OTHR,Settled,SGD,,500\n"


def _dbs_csv(tmp_path: Path, *, available: str | None, ledger: str | None, name: str = "dbs.csv") -> Path:
    lines = [
        "Account Details For:,Test Savings 000-000000-0\n",
        "Statement as at:,19 Feb 2026\n",
        "Currency:,SGD - Singapore Dollar\n",
    ]
    if available is not None:
        lines.append(f"Available Balance:,SGD {available}\n")
    if ledger is not None:
        lines.append(f"Ledger Balance:,SGD {ledger}\n")
    path = tmp_path / name
    path.write_text("".join(lines) + _DBS_COLUMNS + _DBS_ROW, encoding="utf-8")
    return path


def _ocbc_csv(tmp_path: Path, *, available: str, ledger: str) -> Path:
    path = tmp_path / "ocbc.csv"
    path.write_text(
        "Account details for:,360 Account 000-000000-009\n"
        f"Available Balance,{available}\n"
        f"Ledger Balance,{ledger}\n"
        "Transaction date,Value date,Description,Withdrawals(SGD),Deposits(SGD)\n"
        "08/03/2026,08/03/2026,NETS TEST COFFEE,4.50,\n",
        encoding="utf-8",
    )
    return path


def test_dbs_cash_position_is_the_ledger_balance_with_available_kept(tmp_path):
    result = parse_dbs_transaction_history_csv(str(_dbs_csv(tmp_path, available="1000.00", ledger="1700.00")))
    assert result.positions[0]["quantity"] == 1700.0
    assert result.parser_meta["available_balance"] == 1000.0
    assert result.parser_meta["ledger_balance"] == 1700.0


def test_dbs_falls_back_to_available_without_a_ledger_line(tmp_path):
    result = parse_dbs_transaction_history_csv(str(_dbs_csv(tmp_path, available="1000.00", ledger=None)))
    assert result.positions[0]["quantity"] == 1000.0


def test_dbs_ledger_only_still_works(tmp_path):
    result = parse_dbs_transaction_history_csv(str(_dbs_csv(tmp_path, available=None, ledger="1700.00")))
    assert result.positions[0]["quantity"] == 1700.0


def test_ocbc_cash_position_is_the_ledger_balance(tmp_path):
    result = parse_ocbc_account_csv(str(_ocbc_csv(tmp_path, available="1000.00", ledger="1250.00")))
    assert result.positions[0]["quantity"] == 1250.0
    assert result.parser_meta["available_balance"] == 1000.0


def _seed_dbs_account(db_engine, statement: Path) -> None:
    db = sessionmaker(bind=db_engine)()
    try:
        sig, _ = compute_format_signature(str(statement), platform_hint="DBS")
        register_signature(db, sig, "dbs_transaction_history_csv_v1", 1)
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(:id, 'Test DBS Savings', 'DBS', 'BANK', 'SGD', 'SG', 1)"
            ),
            {"id": ACCOUNT_ID},
        )
        db.commit()
    finally:
        db.close()


def _upload(client, path: Path) -> dict:
    with open(path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={ACCOUNT_ID}",
            files={"file": ("transaction_history.csv", f, "text/csv")},
        )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["status"] == "IMPORTED", payload
    return payload


def _balances(db_engine) -> list[tuple]:
    with db_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT as_of_date, balance_local, metadata_json FROM account_balance_snapshots "
                "WHERE account_id = :a ORDER BY as_of_date"
            ),
            {"a": ACCOUNT_ID},
        ).fetchall()


def test_upload_stores_ledger_and_records_the_hold(client, db_engine, tmp_path):
    statement = _dbs_csv(tmp_path, available="1000.00", ledger="1700.00")
    _seed_dbs_account(db_engine, statement)
    _upload(client, statement)

    rows = _balances(db_engine)
    assert len(rows) == 1
    assert float(rows[0][1]) == 1700.0
    meta = rows[0][2] if isinstance(rows[0][2], dict) else json.loads(rows[0][2])
    assert meta["available_balance"] == 1000.0
    assert meta["ledger_balance"] == 1700.0
    assert meta["held_amount"] == 700.0


def test_reupload_corrects_the_stored_balance_without_new_transactions(client, db_engine, tmp_path):
    """How past statements are corrected: an import made before #181 stored available;
    re-uploading the same file replaces that date's balance with ledger and inserts no
    transactions (#157 dedup)."""
    statement = _dbs_csv(tmp_path, available="1000.00", ledger="1700.00")
    _seed_dbs_account(db_engine, statement)
    first = _upload(client, statement)
    assert first["counts"]["transactions_inserted"] == 1
    with db_engine.begin() as conn:  # what a pre-#181 import left behind
        conn.execute(
            text("UPDATE account_balance_snapshots SET balance_local = 1000, balance_base = 1000, metadata_json = '{}' WHERE account_id = :a"),
            {"a": ACCOUNT_ID},
        )

    second = _upload(client, statement)

    assert second["counts"]["transactions_inserted"] == 0
    rows = _balances(db_engine)
    assert len(rows) == 1
    assert float(rows[0][1]) == 1700.0
