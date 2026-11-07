"""#190: account numbers in the app's own copies of statement headers (import
reports, upload / register responses) are masked to the last 4 digits.
#301: so are the numbers parsers put in transaction notes (card_number=...), stored
and in the preview. merchant_counterparty stays as the bank wrote it (D-35's key).

Synthetic statements and fake numbers only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest
from openpyxl import load_workbook
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.account_checks import identity_from_number, normalise_account_number
from app.ingestion.masking import mask_account_numbers, mask_report, mask_transaction_notes
from app.ingestion.registry import register_signature
from app.ingestion.runner import PARSER_REGISTRY
from app.ingestion.signature import compute_format_signature
from app.scripts import mask_reports as mask_reports_script

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# --- The helper ----------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("DBS/POSB MasterCard Platinum 5555-5555-5555-4444", "DBS/POSB MasterCard Platinum ****-****-****-4444"),
        ("Test Savings 012-345678-9", "Test Savings ***-***678-9"),
        ("4111111111111111", "************1111"),
        ("Card 5520-xxxx-xxxx-2403", "Card ****-****-****-2403"),
        ("360 Account 009-876543-210", "360 Account ***-*****3-210"),
        ("x 5555-5555-5555-4444", "x ****-****-****-4444"),
        ("card 5555 5555 5555 4444 x", "card **** **** **** 4444 x"),
        ("****-****-****-4444", "****-****-****-4444"),
        # Not account numbers: amounts, years, dates, short codes, ids glued to letters.
        ("SGD 10000.00", "SGD 10000.00"),
        ("statement period: 01 mar 2026 to 09 mar 2026", "statement period: 01 mar 2026 to 09 mar 2026"),
        ("2026-03-09", "2026-03-09"),
        ("ref 1234", "ref 1234"),
        ("U12345678", "U12345678"),
        ("transaction date", "transaction date"),
        ("", ""),
    ],
)
def test_masking_keeps_only_the_last_four_digits(value, expected):
    assert mask_account_numbers(value) == expected
    assert mask_account_numbers(expected) == expected  # idempotent


def test_a_masked_number_still_names_the_same_last_four_but_not_the_same_identity():
    full = "Test Savings 012-345678-9"
    masked = mask_account_numbers(full)
    assert normalise_account_number(masked)[-4:] == normalise_account_number(full)[-4:]
    # Hashing must therefore happen on the unmasked value (the runner does it first).
    assert identity_from_number(normalise_account_number(masked)) != identity_from_number(normalise_account_number(full))


def test_mask_report_changes_only_the_in_scope_fields():
    report = {
        "status": "IMPORTED",
        "parser_meta": {"account_number": "4111111111111111", "currency": "SGD", "statement_date": "2026-02-12"},
        "signature_debug": {"file_kind": "flat_csv", "header": ["card transaction details for:", "card 5555-5555-5555-4444"]},
        "preview_transactions": [{"notes": "card_number=4111111111111111", "merchant_counterparty": "PAY 5555555555554444"}],
    }
    masked, fields = mask_report(report)
    assert fields == ["parser_meta.account_number", "signature_debug.header"]
    assert masked["parser_meta"] == {"account_number": "************1111", "currency": "SGD", "statement_date": "2026-02-12"}
    assert masked["signature_debug"]["header"][1] == "card ****-****-****-4444"
    assert masked["preview_transactions"] == report["preview_transactions"]
    assert report["parser_meta"]["account_number"] == "4111111111111111"  # the input is not changed
    assert mask_report(masked) == (masked, [])


# --- Every registered parser: no full number in a report or response ----------

ACCOUNT_IDS = iter(range(1901, 1999))


def _replace_in_text(src: Path, old: str, new: str, dest: Path) -> Path:
    content = src.read_text(encoding="utf-8")
    assert old in content
    dest.write_text(content.replace(old, new), encoding="utf-8")
    return dest


def _copy(src: Path, dest: Path) -> Path:
    """For fixtures that already carry the fake number."""
    shutil.copy(src, dest)
    return dest


def _replace_in_workbook(src: Path, old: str, new: str, dest: Path) -> Path:
    shutil.copy(src, dest)  # the fixture is xlsx content under an .xls name
    workbook = load_workbook(dest)
    hits = 0
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value == old:
                    cell.value = new
                    hits += 1
    assert hits
    workbook.save(dest)
    return dest


def _dbs_bank(tmp: Path, number: str) -> Path:
    path = tmp / "dbs.csv"
    path.write_text(
        f"Account Details For:,Test Savings {number}\n"
        "Statement as at:,19 Feb 2026\n"
        "Currency:,SGD - Singapore Dollar\n"
        "Available Balance:,SGD 1700.00\n"
        "Ledger Balance:,SGD 1700.00\n"
        "Transaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,"
        "Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n"
        "19 Feb 2026,19 Feb 2026,GR,Test salary,IBG,Payments,REF,OTHR,Settled,SGD,,500\n",
        encoding="utf-8",
    )
    return path


def _holdings(tmp: Path, number: str, name: str) -> Path:
    path = tmp / name
    path.write_text(
        "<html><body><table>"
        f"<tr><td>Account No</td><td>{number}</td></tr>"
        "<tr><th>Symbol</th><th>Stock Name</th><th>Qty</th><th>Avg Price</th><th>Mkt Value</th></tr>"
        "<tr><td>S68</td><td>SGX</td><td>100</td><td>9.5</td><td>950</td></tr>"
        "</table></body></html>",
        encoding="utf-8",
    )
    return path


def _sharekhan(tmp: Path, number: str) -> Path:
    path = tmp / "sharekhan.xls"
    path.write_text(
        "<html><body><table>"
        f"<tr><td>Client Code</td><td>{number}</td></tr>"
        "<tr><th>Scrip Name</th><th>Available Qty</th><th>Hold Price</th><th>Hold Value</th><th>Market Price</th><th>Market Value</th></tr>"
        "<tr><td>RELIANCE</td><td>10</td><td>2500</td><td>25000</td><td>2600</td><td>26000</td></tr>"
        "</table></body></html>",
        encoding="utf-8",
    )
    return path


def _ibkr(tmp: Path, number: str) -> Path:
    path = tmp / "ibkr.csv"
    path.write_text(
        "Account Information,Header,Field Name,Field Value\n"
        f"Account Information,Data,Account,{number}\n"
        "Cash Transactions,Header,Date,Amount,Currency,Type,Description\n"
        "Cash Transactions,Data,2026-02-02,10,USD,Dividend,Test\n",
        encoding="utf-8",
    )
    return path


# parser_key -> (platform, account type, fake full number, statement builder)
STATEMENTS: dict[str, tuple[str, str, str, Callable[[Path, str], Path]]] = {
    "dbs_transaction_history_csv_v1": ("DBS", "BANK", "012-345678-9", _dbs_bank),
    "dbs_credit_card_csv_v1": (
        "DBS", "CREDIT_CARD", "5555-5555-5555-4444",
        lambda tmp, n: _replace_in_text(
            FIXTURES / "transaction_history_04072026_105429.csv", "5555-5555-5555-4444", n, tmp / "card.csv"
        ),
    ),
    "ocbc_account_csv_v1": (
        "OCBC", "BANK", "009-876543-210",
        lambda tmp, n: _replace_in_text(
            FIXTURES / "ocbc_TransactionHistory_20260313165630.csv", "000-000000-001", n, tmp / "ocbc.csv"
        ),
    ),
    "uob_account_xls_v1": (
        "UOB", "BANK", "012-3456-789",
        lambda tmp, n: _replace_in_workbook(
            FIXTURES / "UOB_ACC_TXN_History_09032026225218.xls", "000-000-001", n, tmp / "uob.xlsx"
        ),
    ),
    "uob_credit_card_xls_v1": (
        "UOB", "CREDIT_CARD", "4111111111111111",
        lambda tmp, n: _copy(FIXTURES / "UOB_CC_TXN_History_09032026222725.xls", tmp / "uob_cc.xlsx"),
    ),
    "citi_credit_card_csv_v1": (
        "CITI", "CREDIT_CARD", "4111111111111111",
        lambda tmp, n: _copy(FIXTURES / "citi_credit_card_sample.csv", tmp / "citi.csv"),
    ),
    "dbs_vickers_holdings_xls_v1": ("DBS_VICKERS", "BROKER", "0123456789012", lambda tmp, n: _holdings(tmp, n, "vickers.xls")),
    "sharekhan_holdings_xls_v1": ("SHAREKHAN", "BROKER", "0987654321098", _sharekhan),
    "ibkr_activity_csv_v1": ("IBKR", "BROKER", "0123456780123", _ibkr),
}


def test_every_registered_parser_has_a_statement_here():
    assert set(STATEMENTS) == set(PARSER_REGISTRY)


def _seed_account(db_engine, account_id: int, platform: str, account_type: str) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) "
                "VALUES (:id, :name, :platform, 1, :type, 'SGD', 'SG')"
            ),
            {"id": account_id, "name": f"Test {platform} {account_id}", "platform": platform, "type": account_type},
        )


def _register(db_engine, path: Path, platform: str, parser_key: str) -> None:
    db = sessionmaker(bind=db_engine)()
    try:
        sig, _ = compute_format_signature(str(path), platform_hint=platform)
        register_signature(db, sig, parser_key, 1)
    finally:
        db.close()


def _post(client, account_id: int, path: Path, **form: str):
    with open(path, "rb") as f:
        return client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": (path.name, f, "application/octet-stream")},
            data=form or None,
        )


def _outside_descriptions(report: dict[str, Any]) -> str:
    """The report as text, without the transaction descriptions (out of scope)."""
    kept = {k: v for k, v in report.items() if k != "preview_transactions"}
    return json.dumps(kept, ensure_ascii=False)


def _assert_no_full_number(blob: str, number: str) -> None:
    digits = re.sub(r"\D", "", number)
    assert number not in blob
    assert digits not in re.sub(r"[\s\-]", "", blob)


def _all_copies(response_json: dict) -> list[dict]:
    job_id = response_json["job_id"]
    with open(os.path.join(os.environ["DATA_DIR"], "reports", f"{job_id}.json"), encoding="utf-8") as f:
        stored = json.load(f)
    # GET /ingest/jobs/{id} serves this stored file as it is.
    return [response_json, stored]


@pytest.mark.parametrize("parser_key", sorted(STATEMENTS))
def test_no_report_or_response_carries_the_full_number(parser_key, client, db_engine, tmp_path):
    platform, account_type, number, build = STATEMENTS[parser_key]
    account_id = next(ACCOUNT_IDS)
    _seed_account(db_engine, account_id, platform, account_type)
    statement = build(tmp_path, number)
    _register(db_engine, statement, platform, parser_key)

    resp = _post(client, account_id, statement)

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "IMPORTED", resp.json().get("error_message")
    assert resp.json()["parser_key"] == parser_key
    for copy in _all_copies(resp.json()):
        _assert_no_full_number(_outside_descriptions(copy), number)


# 12+ digits in a row, not part of a longer word: a full card or account number (#301).
_LONG_DIGITS = re.compile(r"(?<![0-9A-Za-z])[0-9]{12,}(?![0-9A-Za-z])")


def _parser_part(notes: str | None) -> str:
    """A stored note without the runner's " | fp:<hash>" suffix (the hash is hex, not a number)."""
    return re.sub(r"(^| \| )fp:[0-9a-f]{64}$", "", notes or "")


@pytest.mark.parametrize("parser_key", sorted(STATEMENTS))
def test_no_transaction_note_carries_the_full_number(parser_key, client, db_engine, tmp_path):
    """Stored notes and the report's preview notes hold the last 4 only, for every parser (#301)."""
    platform, account_type, number, build = STATEMENTS[parser_key]
    account_id = next(ACCOUNT_IDS)
    _seed_account(db_engine, account_id, platform, account_type)
    statement = build(tmp_path, number)
    _register(db_engine, statement, platform, parser_key)

    resp = _post(client, account_id, statement)

    assert resp.status_code == 200, resp.text
    with db_engine.connect() as conn:
        stored = [r[0] for r in conn.execute(text("SELECT notes FROM transactions WHERE account_id = :a"), {"a": account_id})]
    previews = [tx.get("notes") for copy in _all_copies(resp.json()) for tx in copy.get("preview_transactions") or []]
    for note in stored + previews:
        _assert_no_full_number(_parser_part(note), number)
        assert not _LONG_DIGITS.search(_parser_part(note)), note


def test_the_card_number_note_keeps_its_last_four():
    parsed = [
        {"notes": "card_number=4111111111111111; posting_date=2026-02-09"},
        {"notes": "Inward DR - GIRO | 4111 111111111111 | COLL 123456789012 | TEST CARD CENTRE"},
        {"notes": None},
        {"notes": "reference=TEST000001; foreign_currency=USD 21.80"},
    ]
    mask_transaction_notes(parsed)
    assert parsed[0]["notes"] == "card_number=************1111; posting_date=2026-02-09"
    assert parsed[1]["notes"] == "Inward DR - GIRO | **** ********1111 | COLL ********9012 | TEST CARD CENTRE"
    assert parsed[2]["notes"] is None
    assert parsed[3]["notes"] == "reference=TEST000001; foreign_currency=USD 21.80"  # nothing to mask
    assert mask_transaction_notes([dict(p) for p in parsed]) == parsed  # idempotent


def test_reimporting_after_the_repair_adds_no_rows(client, db_engine, tmp_path):
    """Rows stored before #301 (full number in notes) and masked by migration 082 still
    count as the same transactions: notes are not part of the dedup key (D-35)."""
    platform, account_type, number, build = STATEMENTS["uob_credit_card_xls_v1"]
    account_id = next(ACCOUNT_IDS)
    _seed_account(db_engine, account_id, platform, account_type)
    statement = build(tmp_path, number)
    _register(db_engine, statement, platform, "uob_credit_card_xls_v1")
    first = _post(client, account_id, statement).json()
    inserted = first["counts"]["transactions_inserted"]
    assert inserted > 0
    # As an import before #301 left them: the full number in the notes.
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE transactions SET notes = REPLACE(notes, '************1111', :n) WHERE account_id = :a"),
            {"n": number, "a": account_id},
        )
    before_repair = _post(client, account_id, statement).json()
    assert before_repair["counts"]["transactions_inserted"] == 0
    # Then the repair (migration 082's rule) masks them: still the same transactions.
    with db_engine.begin() as conn:
        rows = conn.execute(text("SELECT id, notes FROM transactions WHERE account_id = :a"), {"a": account_id}).all()
        for row_id, note in rows:
            head, sep, fp = note.rpartition(" | fp:")
            conn.execute(
                text("UPDATE transactions SET notes = :n WHERE id = :i"),
                {"n": f"{mask_account_numbers(head)}{sep}{fp}" if sep else mask_account_numbers(note), "i": row_id},
            )

    again = _post(client, account_id, statement).json()

    assert again["counts"]["transactions_inserted"] == 0
    assert again["counts"]["duplicates_skipped"] == inserted
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM transactions WHERE account_id = :a"), {"a": account_id}).scalar() == inserted


def test_an_unrecognised_card_statement_and_its_register_response_are_masked(client, db_engine, tmp_path):
    """The DBS card header line (with the number) is the file's first wide row, so
    it is what signature_debug.header shows while the format awaits mapping."""
    number = "5555-5555-5555-4444"
    account_id = next(ACCOUNT_IDS)
    _seed_account(db_engine, account_id, "DBS", "CREDIT_CARD")
    # Another card brand: no registered or inferred mapping applies, so it waits for one.
    statement = _replace_in_text(
        FIXTURES / "transaction_history_04072026_105429.csv", "MasterCard", "Visa", tmp_path / "unmapped.csv"
    )

    pending = _post(client, account_id, statement)

    assert pending.status_code == 200, pending.text
    assert pending.json()["status"] == "NEEDS_MAPPING"
    header = pending.json()["signature_debug"]["header"]
    assert any("****-****-****-4444" in h for h in header)
    for copy in _all_copies(pending.json()):
        _assert_no_full_number(_outside_descriptions(copy), number)

    registered = client.post(
        f"/ingest/jobs/{pending.json()['job_id']}/register", json={"parser_key": "dbs_credit_card_csv_v1"}
    )
    assert registered.status_code == 200, registered.text
    _assert_no_full_number(_outside_descriptions(registered.json()), number)


# --- #180's identity link hashes the unmasked number ----------------------------


def test_the_statement_identity_link_uses_the_unmasked_number(client, db_engine, tmp_path):
    number, other = "012-3456-789", "098-7654-321"
    account_id = next(ACCOUNT_IDS)
    _seed_account(db_engine, account_id, "UOB", "BANK")
    src = FIXTURES / "UOB_ACC_TXN_History_09032026225218.xls"
    first = _replace_in_workbook(src, "000-000-001", number, tmp_path / "first.xlsx")
    _register(db_engine, first, "UOB", "uob_account_xls_v1")

    resp = _post(client, account_id, first)

    assert resp.status_code == 200, resp.text
    assert resp.json()["parser_meta"]["account_number"] == "***-***6-789"
    with db_engine.connect() as conn:
        row = conn.execute(
            text("SELECT identity_hash, last4 FROM account_statement_identities WHERE account_id = :a"), {"a": account_id}
        ).one()
    assert row.identity_hash == identity_from_number(normalise_account_number(number)).identity_hash
    assert row.last4 == "6789"

    # The same account again still links; a different account is still refused.
    again = _replace_in_workbook(src, "000-000-001", number, tmp_path / "again.xlsx")
    assert _post(client, account_id, again).status_code == 200
    different = _replace_in_workbook(src, "000-000-001", other, tmp_path / "different.xlsx")
    refused = _post(client, account_id, different)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "statement_account_mismatch"
    assert (detail["statement_last4"], detail["linked_last4"]) == ("4321", "6789")
    _assert_no_full_number(json.dumps(refused.json()), other)


# --- The one-off script for existing reports ----------------------------------


def _old_report(job_id: int) -> dict:
    return {
        "job_id": job_id,
        "status": "IMPORTED",
        "parser_meta": {"account_number": "4111111111111111", "currency": "SGD"},
        "signature_debug": {"file_kind": "flat_csv", "header": ["card transaction details for:", "card 5555-5555-5555-4444"]},
        "preview_transactions": [{"notes": "card_number=4111111111111111"}],
    }


@pytest.fixture()
def reports_dir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "reports").mkdir(parents=True)
    monkeypatch.setenv("DATA_DIR", str(data))
    return data / "reports"


def test_script_dry_run_reports_and_writes_nothing(reports_dir, capsys):
    path = reports_dir / "7.json"
    path.write_text(json.dumps(_old_report(7)), encoding="utf-8")
    (reports_dir / "8.json").write_text(json.dumps({"job_id": 8, "parser_meta": {"currency": "SGD"}}), encoding="utf-8")
    before = path.read_bytes()

    assert mask_reports_script.main([]) == 0

    out = capsys.readouterr().out
    assert "would mask 7.json: parser_meta.account_number, signature_debug.header" in out
    assert "8.json" not in out
    assert "4111" not in out and "5555" not in out  # field names, never values
    assert "would_change=1" in out
    assert path.read_bytes() == before


def test_script_apply_masks_only_the_in_scope_fields(reports_dir, capsys):
    path = reports_dir / "7.json"
    path.write_text(json.dumps(_old_report(7)), encoding="utf-8")

    assert mask_reports_script.main(["--apply"]) == 0

    after = json.loads(path.read_text(encoding="utf-8"))
    expected = _old_report(7)
    expected["parser_meta"]["account_number"] = "************1111"
    expected["signature_debug"]["header"][1] = "card ****-****-****-4444"
    assert after == expected  # preview_transactions untouched
    assert "changed=1" in capsys.readouterr().out
    # A second run finds nothing left to change.
    assert mask_reports_script.main([]) == 0
    assert "would_change=0" in capsys.readouterr().out


def test_script_refuses_any_other_directory(reports_dir, tmp_path, capsys):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "1.json").write_text(json.dumps(_old_report(1)), encoding="utf-8")

    assert mask_reports_script.main(["--reports-dir", str(elsewhere), "--apply"]) == 2
    assert mask_reports_script.main(["--reports-dir", str(reports_dir / ".." / ".." / "elsewhere")]) == 2

    assert "refusing" in capsys.readouterr().err
    assert json.loads((elsewhere / "1.json").read_text(encoding="utf-8")) == _old_report(1)


def test_script_skips_a_link_that_leads_outside(reports_dir, tmp_path, capsys):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_old_report(2)), encoding="utf-8")
    (reports_dir / "2.json").symlink_to(outside)

    assert mask_reports_script.main(["--apply"]) == 0

    assert "skip 2.json" in capsys.readouterr().out
    assert json.loads(outside.read_text(encoding="utf-8")) == _old_report(2)
