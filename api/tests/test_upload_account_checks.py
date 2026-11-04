"""#180: an upload is refused when it goes to the wrong account, a credit-card
account never counts as cash, and an upload can be removed.

Synthetic statements and account numbers only.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion import account_checks
from app.ingestion.account_checks import (
    PARSER_ACCOUNT_TYPES,
    looks_like_holdings_file,
    normalise_account_number,
)
from app.ingestion.registry import register_signature
from app.ingestion.runner import PARSER_REGISTRY
from app.ingestion.signature import compute_format_signature

BANK_ID = 1801
CARD_ID = 1802
BROKER_ID = 1803
OTHER_BANK_ID = 1804

SAVINGS_NUMBER = "012-345678-9"
OTHER_NUMBER = "098-765432-1"

_DBS_COLUMNS = (
    "Transaction Date,Value Date,Statement Code,Description,Supplementary Code,Supplementary Code Description,"
    "Client Reference,Additional Reference,Status,Currency,Debit Amount,Credit Amount\n"
)


def _dbs_csv(
    tmp_path: Path,
    *,
    number: str = SAVINGS_NUMBER,
    as_at: str = "19 Feb 2026",
    ledger: str = "1700.00",
    rows: tuple[str, ...] = ("19 Feb 2026,19 Feb 2026,GR,Test salary,IBG,Payments,REF,OTHR,Settled,SGD,,500",),
    name: str = "dbs.csv",
) -> Path:
    path = tmp_path / name
    path.write_text(
        f"Account Details For:,Test Savings {number}\n"
        f"Statement as at:,{as_at}\n"
        "Currency:,SGD - Singapore Dollar\n"
        f"Available Balance:,SGD {ledger}\n"
        f"Ledger Balance:,SGD {ledger}\n" + _DBS_COLUMNS + "".join(r + "\n" for r in rows),
        encoding="utf-8",
    )
    return path


_HOLDINGS_HTML = """<html><body>
<table>
  <tr><th>Symbol</th><th>Stock Name</th><th>Qty</th><th>Avg Price</th><th>Mkt Value</th></tr>
  <tr><td>S68</td><td>SGX</td><td>{qty}</td><td>9.5</td><td>{value}</td></tr>
</table>
</body></html>"""


def _holdings_xls(tmp_path: Path, *, qty: int = 100, name: str = "holdings_2026_02_19.xls") -> Path:
    path = tmp_path / name
    path.write_text(_HOLDINGS_HTML.format(qty=qty, value=qty * 9.5), encoding="utf-8")
    return path


def _card_fixture() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "transaction_history_04072026_105429.csv"


def _seed_accounts(db_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(:bank, 'Test DBS Savings', 'DBS', 1, 'BANK', 'SGD', 'SG'), "
                "(:card, 'Test DBS Card', 'DBS', 1, 'CREDIT_CARD', 'SGD', 'SG'), "
                "(:broker, 'Test Vickers', 'DBS_VICKERS', 1, 'BROKER', 'SGD', 'SG'), "
                "(:other, 'Test DBS Joint', 'DBS', 1, 'BANK', 'SGD', 'SG')"
            ),
            {"bank": BANK_ID, "card": CARD_ID, "broker": BROKER_ID, "other": OTHER_BANK_ID},
        )


def _register(db_engine, path: Path, platform: str, parser_key: str) -> None:
    db = sessionmaker(bind=db_engine)()
    try:
        sig, _ = compute_format_signature(str(path), platform_hint=platform)
        register_signature(db, sig, parser_key, 1)
    finally:
        db.close()


def _post(client, account_id: int, path: Path, filename: str | None = None, **form: str):
    with open(path, "rb") as f:
        return client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": (filename or path.name, f, "text/csv")},
            data=form or None,
        )


def _scalar(db_engine, sql: str, **params: Any) -> Any:
    with db_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


# Everything an upload can write, as comparable rows.
_DATA_TABLES = (
    "transactions",
    "account_balance_snapshots",
    "portfolio_position_snapshots",
    "portfolio_data_completeness",
    "portfolio_source_authority_windows",
    "credit_card_accounts",
    "account_statement_identities",
    "category_overrides",
)


def _data_state(db_engine) -> dict[str, list[tuple]]:
    state: dict[str, list[tuple]] = {}
    with db_engine.connect() as conn:
        for table in _DATA_TABLES:
            rows = conn.execute(text(f"SELECT * FROM {table}")).fetchall()
            state[table] = sorted((tuple(str(v) for v in row) for row in rows))
    return state


# --- Part 1: account type -----------------------------------------------------


def test_every_registered_parser_declares_its_account_types():
    assert set(PARSER_REGISTRY) <= set(PARSER_ACCOUNT_TYPES)
    for parser_key, types in PARSER_ACCOUNT_TYPES.items():
        assert types, parser_key
        assert types <= {"BANK", "CREDIT_CARD", "BROKER", "MUTUAL_FUND", "EXCHANGE", "WALLET", "LOAN"}
        assert parser_key in account_checks.PARSER_FILE_LABELS


def test_bank_statement_to_a_card_account_is_refused_before_anything_is_written(client, db_engine, tmp_path):
    """The sprint 2 case: a savings CSV sent to a card account with no credit_card_accounts row."""
    _seed_accounts(db_engine)
    statement = _dbs_csv(tmp_path)
    _register(db_engine, statement, "DBS", "dbs_transaction_history_csv_v1")
    before = _data_state(db_engine)

    resp = _post(client, CARD_ID, statement)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "account_type_mismatch"
    assert detail["expected_account_types"] == ["BANK"]
    assert detail["account_type"] == "CREDIT_CARD"
    assert "bank account (BANK)" in detail["message"]
    assert _data_state(db_engine) == before
    assert _scalar(db_engine, "SELECT status FROM import_jobs WHERE id = :id", id=detail["job_id"]) == "REJECTED"
    jobs = client.get("/ingest/jobs").json()
    assert jobs[0]["status"] == "REJECTED"
    assert jobs[0]["removable"] is False
    assert "bank account" in jobs[0]["error_message"]


def test_card_statement_to_a_bank_account_is_refused(client, db_engine):
    _seed_accounts(db_engine)
    before = _data_state(db_engine)

    resp = _post(client, BANK_ID, _card_fixture())

    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["expected_account_types"] == ["CREDIT_CARD"]
    assert _data_state(db_engine) == before


def test_unrecognised_holdings_file_to_a_bank_account_is_refused_not_needs_mapping(client, db_engine, tmp_path):
    """The August case: a holdings export uploaded to the savings account."""
    _seed_accounts(db_engine)

    resp = _post(client, BANK_ID, _holdings_xls(tmp_path))

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "account_type_mismatch"
    assert detail["expected_account_types"] == ["BROKER", "MUTUAL_FUND"]
    assert "holdings" in detail["message"]


def test_registered_holdings_file_to_a_bank_account_is_refused(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    holdings = _holdings_xls(tmp_path)
    _register(db_engine, holdings, "DBS", "dbs_vickers_holdings_xls_v1")

    resp = _post(client, BANK_ID, holdings)

    assert resp.status_code == 409
    assert resp.json()["detail"]["parser_key"] == "dbs_vickers_holdings_xls_v1"


def test_unknown_bank_csv_still_needs_mapping(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    odd = tmp_path / "odd.csv"
    odd.write_text("Date,Narrative,Amount\n01/02/2026,Synthetic,1.00\n", encoding="utf-8")

    resp = _post(client, BANK_ID, odd)

    assert resp.status_code == 200
    assert resp.json()["status"] == "NEEDS_MAPPING"


def test_register_refuses_a_parser_for_the_wrong_account_type_without_writing_the_registry(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    odd = tmp_path / "odd.csv"
    odd.write_text("Date,Narrative,Amount\n01/02/2026,Synthetic,1.00\n", encoding="utf-8")
    job_id = _post(client, CARD_ID, odd).json()["job_id"]

    resp = client.post(f"/ingest/jobs/{job_id}/register", json={"parser_key": "dbs_transaction_history_csv_v1"})

    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "account_type_mismatch"
    assert _scalar(db_engine, "SELECT COUNT(*) FROM parser_registry") == 0


def test_holdings_shape_detection():
    assert looks_like_holdings_file({"file_kind": "excel", "header": ["scrip name", "available qty", "hold value"]})
    assert not looks_like_holdings_file(
        {"file_kind": "excel", "header": ["transaction date", "description", "withdrawal", "deposit", "available balance"]}
    )
    assert not looks_like_holdings_file({"file_kind": "flat_csv", "header": ["symbol", "qty"]})


# --- Part 2: statement identity -------------------------------------------------


def test_account_numbers_are_normalised_from_header_values():
    assert normalise_account_number("Test Savings 012-345678-9") == "0123456789"
    assert normalise_account_number("360 Account 000-000000-009") == "000000000009"
    assert normalise_account_number("DBS/POSB MasterCard Platinum 5555-5555-5555-4444") == "5555555555554444"
    assert normalise_account_number("Card 5520-xxxx-xxxx-2403") == "5520XXXXXXXX2403"
    assert normalise_account_number("Savings") is None


def test_first_import_links_the_account_and_stores_no_full_number(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    statement = _dbs_csv(tmp_path)
    _register(db_engine, statement, "DBS", "dbs_transaction_history_csv_v1")

    resp = _post(client, BANK_ID, statement)

    assert resp.status_code == 200, resp.text
    with db_engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM account_statement_identities")).mappings().one()
        job = conn.execute(text("SELECT undo_json, error_message FROM import_jobs")).mappings().one()
    assert row["account_id"] == BANK_ID
    digits = "0123456789"
    assert row["last4"] == digits[-4:]
    for value in list(row.values()) + list(job.values()):
        assert digits not in str(value)
        assert SAVINGS_NUMBER not in str(value)
    assert digits not in json.dumps(resp.json())


def test_a_statement_for_another_account_is_refused_with_an_override(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    first = _dbs_csv(tmp_path, name="first.csv")
    _register(db_engine, first, "DBS", "dbs_transaction_history_csv_v1")
    assert _post(client, BANK_ID, first).status_code == 200
    other = _dbs_csv(
        tmp_path,
        number=OTHER_NUMBER,
        as_at="20 Feb 2026",
        ledger="250.00",
        rows=("20 Feb 2026,20 Feb 2026,GR,Other salary,IBG,Payments,REF,OTHR,Settled,SGD,,90",),
        name="other.csv",
    )
    before = _data_state(db_engine)

    refused = _post(client, BANK_ID, other)

    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["code"] == "statement_account_mismatch"
    assert detail["statement_last4"] == "4321"
    assert detail["linked_last4"] == "6789"
    assert detail["override_field"] == "allow_account_mismatch"
    assert "ending 4321" in detail["message"] and "ending 6789" in detail["message"]
    assert _data_state(db_engine) == before

    anyway = _post(client, BANK_ID, other, allow_account_mismatch="true")

    assert anyway.status_code == 200, anyway.text
    assert anyway.json()["status"] == "IMPORTED"
    # Sent anyway: the account now follows the new number (a replaced card)...
    link = "SELECT last4 FROM account_statement_identities WHERE account_id = :a"
    assert _scalar(db_engine, link, a=BANK_ID) == "4321"
    follow_up = _post(client, BANK_ID, other)
    assert follow_up.status_code == 200
    # ...and removing those uploads (newest first) puts the earlier link back.
    assert client.post(f"/ingest/jobs/{follow_up.json()['job_id']}/remove").status_code == 200
    assert client.post(f"/ingest/jobs/{anyway.json()['job_id']}/remove").status_code == 200
    assert _scalar(db_engine, link, a=BANK_ID) == "6789"
    assert _data_state(db_engine) == before


def test_same_statement_account_uploads_again_without_override(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    first = _dbs_csv(tmp_path, name="first.csv")
    _register(db_engine, first, "DBS", "dbs_transaction_history_csv_v1")
    assert _post(client, BANK_ID, first).status_code == 200
    later = _dbs_csv(tmp_path, as_at="28 Feb 2026", ledger="1800.00", name="later.csv")

    assert _post(client, BANK_ID, later).status_code == 200


def test_refusal_names_the_account_the_statement_belongs_to(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    savings = _dbs_csv(tmp_path, name="savings.csv")
    joint = _dbs_csv(tmp_path, number=OTHER_NUMBER, name="joint.csv")
    _register(db_engine, savings, "DBS", "dbs_transaction_history_csv_v1")
    assert _post(client, BANK_ID, savings).status_code == 200
    assert _post(client, OTHER_BANK_ID, joint).status_code == 200

    resp = _post(client, OTHER_BANK_ID, savings)

    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["suggested_account_id"] == BANK_ID
    assert "Test DBS Savings" in detail["message"]


# --- Part 3: card accounts never count as cash --------------------------------------


def test_a_credit_card_account_balance_never_counts_as_cash(db_engine):
    from app.valuation import facts, state

    _seed_accounts(db_engine)
    with db_engine.begin() as conn:
        # A bank_cash balance stored on the card account (no credit_card_accounts row),
        # as the wrong upload left it, next to the real savings balance.
        for account_id, balance in ((BANK_ID, 1000), (CARD_ID, 1700)):
            conn.execute(
                text(
                    "INSERT INTO account_balance_snapshots (account_id, as_of_date, currency, balance_type, "
                    "balance_local, balance_base, fx_rate_to_base, authority_status, source_kind) "
                    "VALUES (:a, '2026-02-19', 'SGD', 'bank_cash', :b, :b, 1, 'authoritative', 'upload_parser')"
                ),
                {"a": account_id, "b": balance},
            )
    anchor = datetime(2026, 3, 1, tzinfo=timezone.utc)
    db = sessionmaker(bind=db_engine)()
    try:
        rows = state._cash_balance_rows(db, current_user_id=1, anchor_date=anchor.date())
        assert {int(r["account_id"]) for r in rows} == {BANK_ID}
        assert state._credit_card_account_ids(db, 1) == {CARD_ID}
        components = facts._networth_asset_components(db, anchor, "SGD", 1)
        assert components["cash"] == pytest.approx(1000.0)
        assert sum(b["value"] for b in facts._cash_balances(db, anchor, "SGD", 1)) == pytest.approx(1000.0)
        deposits = facts._cash_deposits(db, anchor, "SGD", 1)
        assert deposits["total"] == pytest.approx(1000.0)
    finally:
        db.close()


# --- Part 4: remove an import ---------------------------------------------------------


def _clear_dirty(db_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM wealth_rollup_dirty"))


def _dirty_from(db_engine) -> str | None:
    value = _scalar(db_engine, "SELECT from_date FROM wealth_rollup_dirty WHERE user_id = 1")
    return str(value)[:10] if value is not None else None


def test_removing_a_bank_upload_leaves_the_data_as_before(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    statement = _dbs_csv(
        tmp_path,
        rows=(
            "12 Feb 2026,12 Feb 2026,POS,Synthetic grocer,,,REF,OTHR,Settled,SGD,12.30,",
            "19 Feb 2026,19 Feb 2026,GR,Test salary,IBG,Payments,REF,OTHR,Settled,SGD,,500",
        ),
    )
    _register(db_engine, statement, "DBS", "dbs_transaction_history_csv_v1")
    before = _data_state(db_engine)

    job = _post(client, BANK_ID, statement).json()
    assert job["counts"]["transactions_inserted"] == 2
    assert _data_state(db_engine) != before
    assert client.get("/ingest/jobs").json()[0]["removable"] is True
    _clear_dirty(db_engine)

    resp = client.post(f"/ingest/jobs/{job['job_id']}/remove")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "REMOVED"
    assert body["removed"]["transactions"] == 2
    assert body["removed"]["balance_snapshots"] == 1
    assert body["history_dirty_from"] == "2026-02-12"
    assert _data_state(db_engine) == before
    assert _dirty_from(db_engine) == "2026-02-12"
    listed = client.get("/ingest/jobs").json()[0]
    assert listed["status"] == "REMOVED" and listed["removable"] is False and listed["removed_at"]
    # The same statement can be uploaded again afterwards (no stale link or fingerprint).
    again = _post(client, BANK_ID, statement)
    assert again.status_code == 200 and again.json()["counts"]["transactions_inserted"] == 2


def test_removing_a_re_upload_puts_the_earlier_balance_back(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    first = _dbs_csv(tmp_path, ledger="1700.00", name="first.csv")
    _register(db_engine, first, "DBS", "dbs_transaction_history_csv_v1")
    first_job = _post(client, BANK_ID, first).json()["job_id"]
    after_first = _data_state(db_engine)
    corrected = _dbs_csv(tmp_path, ledger="1750.00", name="corrected.csv")
    second_job = _post(client, BANK_ID, corrected).json()["job_id"]
    assert float(_scalar(db_engine, "SELECT balance_local FROM account_balance_snapshots")) == 1750.0

    # The first upload's balance was replaced by the second: undo is a stack.
    blocked = client.post(f"/ingest/jobs/{first_job}/remove")
    assert blocked.status_code == 409
    assert f"#{second_job}" in blocked.json()["detail"]

    assert client.post(f"/ingest/jobs/{second_job}/remove").status_code == 200
    assert _data_state(db_engine) == after_first
    assert client.post(f"/ingest/jobs/{first_job}/remove").status_code == 200


def test_removing_a_holdings_upload_restores_the_holdings_it_replaced(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    first = _holdings_xls(tmp_path, qty=100, name="first_2026_02_19.xls")
    _register(db_engine, first, "DBS_VICKERS", "dbs_vickers_holdings_xls_v1")
    before = _data_state(db_engine)
    first_job = _post(client, BROKER_ID, first, as_of="2026-02-19").json()
    assert first_job["status"] == "IMPORTED", first_job
    after_first = _data_state(db_engine)
    second = _holdings_xls(tmp_path, qty=150, name="second_2026_02_19.xls")
    second_job = _post(client, BROKER_ID, second, as_of="2026-02-19").json()
    assert second_job["status"] == "IMPORTED", second_job
    _clear_dirty(db_engine)

    resp = client.post(f"/ingest/jobs/{second_job['job_id']}/remove")

    assert resp.status_code == 200, resp.text
    assert resp.json()["removed"]["position_snapshots"] == 1
    assert _data_state(db_engine) == after_first
    assert _dirty_from(db_engine) == "2026-02-19"

    assert client.post(f"/ingest/jobs/{first_job['job_id']}/remove").status_code == 200
    assert _data_state(db_engine) == before
    statuses = _scalar(db_engine, "SELECT COUNT(*) FROM broker_import_runs WHERE status = 'removed'")
    assert statuses == 2


def test_removing_a_card_upload_puts_the_limits_back(client, db_engine):
    _seed_accounts(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (id, account_id, card_name, issuer, credit_limit, available_limit, "
                "available_limit_as_of, statement_day, due_day) "
                "VALUES (1, :a, 'Test Card', 'DBS', 5000, 4000, '2026-01-31 00:00:00+00:00', 1, 20)"
            ),
            {"a": CARD_ID},
        )
    before = _data_state(db_engine)
    job = _post(client, CARD_ID, _card_fixture()).json()
    assert job["status"] == "IMPORTED", job
    assert float(_scalar(db_engine, "SELECT credit_limit FROM credit_card_accounts")) == 10000.0

    resp = client.post(f"/ingest/jobs/{job['job_id']}/remove")

    assert resp.status_code == 200, resp.text
    assert _data_state(db_engine) == before


def test_an_upload_from_before_removal_existed_is_refused(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    statement = _dbs_csv(tmp_path)
    _register(db_engine, statement, "DBS", "dbs_transaction_history_csv_v1")
    job_id = _post(client, BANK_ID, statement).json()["job_id"]
    with db_engine.begin() as conn:  # what a pre-074 import looks like
        conn.execute(text("UPDATE import_jobs SET undo_json = NULL"))
        conn.execute(text("UPDATE transactions SET import_job_id = NULL"))
    before = _data_state(db_engine)

    resp = client.post(f"/ingest/jobs/{job_id}/remove")

    assert resp.status_code == 409
    assert "before uploads could be removed" in resp.json()["detail"]
    assert _data_state(db_engine) == before
    assert client.get("/ingest/jobs").json()[0]["removable"] is False


def test_only_imported_jobs_can_be_removed(client, db_engine, tmp_path):
    _seed_accounts(db_engine)
    odd = tmp_path / "odd.csv"
    odd.write_text("Date,Narrative,Amount\n01/02/2026,Synthetic,1.00\n", encoding="utf-8")
    job_id = _post(client, BANK_ID, odd).json()["job_id"]

    resp = client.post(f"/ingest/jobs/{job_id}/remove")

    assert resp.status_code == 409
    assert "NEEDS_MAPPING" in resp.json()["detail"]


def test_removal_is_for_the_account_owner_only(client, db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_ALLOW_LEGACY_NULL_OWNERSHIP", "0")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(:id, 'Someone else', 'DBS', 2, 'BANK', 'SGD', 'SG')"
            ),
            {"id": BANK_ID},
        )
        conn.execute(
            text(
                "INSERT INTO import_jobs (id, account_id, platform, original_filename, stored_path, file_sha256, "
                "status, undo_json, created_at, updated_at) VALUES (77, :a, 'DBS', 'x.csv', '', '', 'IMPORTED', "
                "'{\"version\": 1}', '2026-02-19', '2026-02-19')"
            ),
            {"a": BANK_ID},
        )

    resp = client.post("/ingest/jobs/77/remove")

    assert resp.status_code == 404
    assert _scalar(db_engine, "SELECT status FROM import_jobs WHERE id = 77") == "IMPORTED"


def test_remove_marks_history_from_the_earliest_card_transaction(client, db_engine):
    _seed_accounts(db_engine)
    job = _post(client, CARD_ID, _card_fixture()).json()
    _clear_dirty(db_engine)
    earliest = _scalar(db_engine, "SELECT MIN(ts) FROM transactions WHERE account_id = :a", a=CARD_ID)

    resp = client.post(f"/ingest/jobs/{job['job_id']}/remove")

    assert resp.status_code == 200
    assert resp.json()["history_dirty_from"] == str(earliest)[:10]
    assert _dirty_from(db_engine) == str(earliest)[:10]
    assert date.fromisoformat(resp.json()["history_dirty_from"]) <= date(2026, 7, 4)
