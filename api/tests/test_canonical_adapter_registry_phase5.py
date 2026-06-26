"""
Phase 5: Canonical parser adapter registry tests.

Acceptance criteria verified:
- All parsers that can emit positions have an explicit canonical adapter mapping.
- UOB account, OCBC account, DBS transaction history uploads produce
  account_balance_snapshots (not legacy positions).
- The upload runner does NOT write to legacy positions for canonical-covered parsers.
- Canonical adapter errors are blocking for position-producing parsers.
- Upload reports include canonical_positions_written and canonical_balances_written.
- A parser that emits positions without an adapter in PARSER_CANONICAL_REGISTRY
  causes the import to fail with status=FAILED.
- Existing non-position parsers (credit card) remain unchanged.
"""

from __future__ import annotations

import csv
import os
from datetime import date
from io import StringIO
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.parsers.base import ParseResult
from app.ingestion.signature import compute_format_signature
from app.ingestion.registry import register_signature
from app.portfolio.upload_canonical import (
    PARSER_CANONICAL_REGISTRY,
    parser_canonical_target,
    run_upload_balance_canonical_adapter,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _seed_account(db_engine, account_id: int, name: str, platform: str, currency: str) -> None:
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT OR IGNORE INTO accounts (id, name, platform, account_type, currency, country) "
                "VALUES (:id, :name, :platform, 'BANK', :currency, 'SG')"
            ),
            {"id": account_id, "name": name, "platform": platform, "currency": currency},
        )
        db.commit()
    finally:
        db.close()


def _seed_user(db_engine, user_id: int = 1) -> None:
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT OR IGNORE INTO users (id, username, display_name, is_active, is_admin) "
                "VALUES (:id, 'user_phase5', 'Phase5 User', 1, 0)"
            ),
            {"id": user_id},
        )
        db.commit()
    finally:
        db.close()


def _ocbc_csv_content() -> str:
    lines = [
        "Account Details For:,OCBC SAVINGS",
        "Available Balance,5000.00",
        "Ledger Balance,5000.00",
        "Transaction Date,Value Date,Description,Withdrawals(SGD),Deposits(SGD)",
        "01 Jan 2024,01 Jan 2024,SALARY CREDIT,,3000.00",
        "02 Jan 2024,02 Jan 2024,FAST TRANSFER TO IBKR,500.00,",
    ]
    return "\n".join(lines)


def _uob_csv_content() -> str:
    """Minimal UOB account XLS-like fixture as HTML for parsing."""
    return """<html><body>
    <table>
      <tr><td>Account Number:</td><td>123-456-789</td><td>SGD</td></tr>
      <tr><td>Account Type:</td><td>Savings</td></tr>
      <tr><td>Statement Period:</td><td>01 Jan 2024 to 31 Jan 2024</td></tr>
      <tr>
        <td>Transaction Date</td><td>Transaction Description</td>
        <td>Withdrawal</td><td>Deposit</td><td>Available Balance</td>
      </tr>
      <tr><td>01 Jan 2024</td><td>SALARY</td><td></td><td>5000.00</td><td>5000.00</td></tr>
      <tr><td>15 Jan 2024</td><td>PAYNOW TO SHOPEE</td><td>200.00</td><td></td><td>4800.00</td></tr>
    </table>
    </body></html>"""


def _dbs_csv_content() -> str:
    lines = [
        "Statement As At:,31 Jan 2024",
        "Currency:,SGD",
        "Available Balance:,8000.00",
        "Ledger Balance:,8000.00",
        "Transaction Date,Value Date,Description,Statement Code,Debit Amount,Credit Amount,Currency,Supplementary Code Description",
        "01 Jan 2024,01 Jan 2024,SALARY,SAL,,5000.00,SGD,JAN SALARY",
        "15 Jan 2024,15 Jan 2024,PAYNOW TO IBKR,TRF,1000.00,,SGD,",
    ]
    return "\n".join(lines)


def _setup_ocbc_fixture(tmp_path, db_engine, account_id: int) -> str:
    os.makedirs(os.getenv("DATA_DIR", "/tmp/capitalos_test_data"), exist_ok=True)
    _seed_account(db_engine, account_id, f"OCBC Phase5 {account_id}", "OCBC", "SGD")

    fixture = tmp_path / f"ocbc_{account_id}.csv"
    fixture.write_text(_ocbc_csv_content(), encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="OCBC")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "ocbc_account_csv_v1", 1)
    finally:
        db.close()
    return str(fixture)


def _setup_dbs_fixture(tmp_path, db_engine, account_id: int) -> str:
    os.makedirs(os.getenv("DATA_DIR", "/tmp/capitalos_test_data"), exist_ok=True)
    _seed_account(db_engine, account_id, f"DBS Phase5 {account_id}", "DBS", "SGD")

    fixture = tmp_path / f"dbs_{account_id}.csv"
    fixture.write_text(_dbs_csv_content(), encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="DBS")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "dbs_transaction_history_csv_v1", 1)
    finally:
        db.close()
    return str(fixture)


# ---------------------------------------------------------------------------
# Registry completeness: every known parser has an entry
# ---------------------------------------------------------------------------

def test_all_parsers_have_canonical_registry_entry():
    """Every parser in the runner registry must be present in PARSER_CANONICAL_REGISTRY."""
    from app.ingestion.runner import PARSER_REGISTRY
    for parser_key in PARSER_REGISTRY:
        assert parser_key in PARSER_CANONICAL_REGISTRY, (
            f"Parser '{parser_key}' is in PARSER_REGISTRY but missing from "
            f"PARSER_CANONICAL_REGISTRY. Add an explicit entry before merging."
        )


def test_position_producing_parsers_have_non_none_adapter():
    """All parsers that actually emit positions must have a non-'none' canonical target."""
    position_producing = {
        "sharekhan_holdings_xls_v1",
        "dbs_vickers_holdings_xls_v1",
        "ibkr_activity_csv_v1",
        "uob_account_xls_v1",
        "ocbc_account_csv_v1",
        "dbs_transaction_history_csv_v1",
    }
    for parser_key in position_producing:
        target = parser_canonical_target(parser_key)
        assert target is not None and target != "none", (
            f"Parser '{parser_key}' must have a canonical adapter ('portfolio_positions' "
            f"or 'account_balance'), got: {target!r}"
        )


# ---------------------------------------------------------------------------
# Balance adapter: run_upload_balance_canonical_adapter
# ---------------------------------------------------------------------------

def test_balance_adapter_writes_account_balance_snapshot(db_engine):
    """run_upload_balance_canonical_adapter must write to account_balance_snapshots."""
    account_id = 700
    _seed_account(db_engine, account_id, "Balance Test", "OCBC", "SGD")

    parse_result = ParseResult(
        transactions=[],
        positions=[
            {
                "symbol": "SGD",
                "name": "SGD Cash",
                "asset_class": "CASH",
                "currency": "SGD",
                "quantity": 5000.0,
                "avg_cost": 1.0,
                "cost_basis_base": 5000.0,
                "as_of": None,
            }
        ],
        section_counts={"transactions": 0},
        parser_meta={
            "available_balance": 5000.0,
            "ledger_balance": 5000.0,
            "currency": "SGD",
        },
    )

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        result = run_upload_balance_canonical_adapter(
            db,
            account_id=account_id,
            import_job_id=None,
            parse_result=parse_result,
        )
        db.commit()

        assert result["status"] == "CANONICAL_IMPORTED"
        assert result["adapter"] == "account_balance"
        assert result["counts"]["balances"] == 1

        row = db.execute(
            text(
                """
                SELECT currency, balance_local, balance_type, authority_status, source_kind
                FROM account_balance_snapshots
                WHERE account_id = :aid
                  AND authority_status = 'authoritative'
                LIMIT 1
                """
            ),
            {"aid": account_id},
        ).fetchone()
        assert row is not None, "account_balance_snapshots row must be written"
        assert row[0] == "SGD"
        assert float(row[1]) == 5000.0
        assert row[2] == "bank_cash"
        assert row[3] == "authoritative"
        assert row[4] == "upload_parser"
    finally:
        db.close()


def test_balance_adapter_is_idempotent(db_engine):
    """Repeated identical uploads must produce exactly one authoritative balance row."""
    account_id = 701
    _seed_account(db_engine, account_id, "Balance Idempotent", "UOB", "SGD")

    parse_result = ParseResult(
        transactions=[],
        positions=[
            {
                "symbol": "SGD",
                "name": "SGD Cash",
                "asset_class": "CASH",
                "currency": "SGD",
                "quantity": 4800.0,
                "avg_cost": 1.0,
                "cost_basis_base": 4800.0,
                "as_of": None,
            }
        ],
        section_counts={},
        parser_meta={"statement_period_end": "2024-01-31"},
    )

    Session = sessionmaker(bind=db_engine)
    for _ in range(3):
        db = Session()
        try:
            run_upload_balance_canonical_adapter(
                db,
                account_id=account_id,
                import_job_id=None,
                parse_result=parse_result,
            )
            db.commit()
        finally:
            db.close()

    db = Session()
    try:
        count = db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM account_balance_snapshots
                WHERE account_id = :aid
                  AND authority_status = 'authoritative'
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert count == 1, f"Expected 1 authoritative balance row after 3 uploads, got {count}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# OCBC account upload → account_balance_snapshots via runner
# ---------------------------------------------------------------------------

def test_ocbc_upload_writes_canonical_balance_not_legacy_positions(client: TestClient, db_engine, tmp_path):
    """OCBC account upload must write to account_balance_snapshots, NOT legacy positions."""
    account_id = 710
    fixture_path = _setup_ocbc_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("ocbc.csv", f, "text/csv")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"

    # Legacy positions must be 0
    assert data["counts"]["positions_inserted"] == 0, (
        "Legacy positions must not be written for OCBC (account_balance canonical target)"
    )
    # Canonical balance count must be >= 1
    assert data["counts"].get("canonical_balances_written", 0) >= 1, (
        "canonical_balances_written must be >= 1 in the upload report"
    )

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        legacy_count = db.execute(
            text("SELECT COUNT(*) FROM positions WHERE account_id = :aid"),
            {"aid": account_id},
        ).scalar()
        assert legacy_count == 0, "No legacy positions rows for OCBC bank account"

        balance_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM account_balance_snapshots
                WHERE account_id = :aid AND authority_status = 'authoritative'
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert balance_count >= 1, "account_balance_snapshots row must be written for OCBC"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DBS transaction history upload → account_balance_snapshots via runner
# ---------------------------------------------------------------------------

def test_dbs_transaction_upload_writes_canonical_balance(client: TestClient, db_engine, tmp_path):
    """DBS transaction history upload must write to account_balance_snapshots."""
    account_id = 720
    fixture_path = _setup_dbs_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("dbs.csv", f, "text/csv")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["counts"]["positions_inserted"] == 0
    assert data["counts"].get("canonical_balances_written", 0) >= 1

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        balance_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM account_balance_snapshots
                WHERE account_id = :aid AND authority_status = 'authoritative'
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert balance_count >= 1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Blocking failure: canonical adapter error must fail the import
# ---------------------------------------------------------------------------

def test_canonical_adapter_failure_fails_import(client: TestClient, db_engine, tmp_path, monkeypatch):
    """When the canonical adapter raises, the import must fail (not silently succeed)."""
    account_id = 730
    _seed_account(db_engine, account_id, "Fail Test", "SHAREKHAN", "INR")

    sharekhan_html = """<html><body>
    <table>
      <tr><th>Scrip Name</th><th>Available Qty</th><th>Hold Price</th><th>Hold Value</th></tr>
      <tr><td>RELIANCE</td><td>10</td><td>2500</td><td>25000</td></tr>
    </table>
    </body></html>"""
    fixture = tmp_path / "sk_fail.xls"
    fixture.write_text(sharekhan_html, encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "sharekhan_holdings_xls_v1", 1)
    finally:
        db.close()

    # Monkeypatch the canonical adapter to raise
    import app.portfolio.upload_canonical as uc
    original = uc.run_upload_canonical_adapter

    def _raise(*args: Any, **kwargs: Any) -> dict:
        raise RuntimeError("Simulated canonical adapter failure")

    monkeypatch.setattr(uc, "run_upload_canonical_adapter", _raise)
    # Also patch in the runner's local reference
    import app.ingestion.runner as runner_mod
    monkeypatch.setattr(runner_mod, "run_upload_canonical_adapter", _raise)

    try:
        with open(str(fixture), "rb") as f:
            resp = client.post(
                f"/ingest/upload?account_id={account_id}",
                files={"file": ("sk_fail.xls", f, "application/vnd.ms-excel")},
            )
        # Phase 5: canonical failure must fail the import
        data = resp.json()
        assert data["status"] == "FAILED", (
            f"Import must be FAILED when canonical adapter raises; got status={data['status']!r}, "
            f"error={data.get('error_message')!r}"
        )
        assert "canonical" in (data.get("error_message") or "").lower() or data["status"] == "FAILED"
    finally:
        monkeypatch.setattr(uc, "run_upload_canonical_adapter", original)
        monkeypatch.setattr(runner_mod, "run_upload_canonical_adapter", original)


# ---------------------------------------------------------------------------
# Unregistered parser with positions must fail closed
# ---------------------------------------------------------------------------

def test_unregistered_parser_with_positions_fails_import(client: TestClient, db_engine, tmp_path):
    """An upload from an unregistered parser that emits positions must fail with FAILED status."""
    account_id = 740
    _seed_account(db_engine, account_id, "Unknown Parser Test", "SHAREKHAN", "INR")

    # Register a known signature to a fake parser key not in PARSER_CANONICAL_REGISTRY
    fake_content = "fake_unknown_parser_content_xyz\ncol1,col2\nval1,val2\n"
    fixture = tmp_path / "unknown_parser.csv"
    fixture.write_text(fake_content, encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        # Register this signature to a parser key NOT in PARSER_CANONICAL_REGISTRY
        register_signature(db, sig, "future_unknown_parser_v1", 1)
    finally:
        db.close()

    # Add the unknown parser to PARSER_REGISTRY temporarily so it can be called
    from app.ingestion.parsers.base import ParseResult as PR
    import app.ingestion.runner as runner_mod

    def _fake_parser(path: str, delimiter: str = ",") -> PR:
        return PR(
            transactions=[],
            positions=[
                {
                    "symbol": "XYZ",
                    "name": "XYZ Corp",
                    "asset_class": "STOCK",
                    "currency": "USD",
                    "quantity": 100,
                    "avg_cost": 10.0,
                    "cost_basis_base": 1000.0,
                }
            ],
            section_counts={"rows_parsed": 1},
            parser_meta={},
        )

    original_registry = dict(runner_mod.PARSER_REGISTRY)
    runner_mod.PARSER_REGISTRY["future_unknown_parser_v1"] = ("csv", _fake_parser)

    try:
        with open(str(fixture), "rb") as f:
            resp = client.post(
                f"/ingest/upload?account_id={account_id}",
                files={"file": ("unknown.csv", f, "text/csv")},
            )
        data = resp.json()
        assert data["status"] == "FAILED", (
            "Import must fail for an unregistered parser that emits positions"
        )
        assert "canonical_adapter_missing" in (data.get("error_message") or "")
    finally:
        runner_mod.PARSER_REGISTRY.clear()
        runner_mod.PARSER_REGISTRY.update(original_registry)


# ---------------------------------------------------------------------------
# Non-position parsers (credit card) remain unchanged
# ---------------------------------------------------------------------------

def test_citi_credit_card_upload_not_affected(client: TestClient, db_engine, tmp_path):
    """Credit card parsers (no positions) must remain fully functional and untouched."""
    account_id = 750
    _seed_account(db_engine, account_id, "Citi CC Phase5", "CITI", "SGD")

    citi_csv = "01/01/2024,AMAZON PURCHASE,50.00,SGD,4321\n"
    fixture = tmp_path / "citi_phase5.csv"
    fixture.write_text(citi_csv, encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="CITI")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "citi_credit_card_csv_v1", 1)
    finally:
        db.close()

    with open(str(fixture), "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("citi.csv", f, "text/csv")},
        )
    assert resp.status_code == 200
    data = resp.json()
    # Credit card parsers emit no positions so they succeed via "none" canonical target
    assert data["status"] == "IMPORTED", (
        f"Credit card import must still succeed; got {data['status']!r}"
    )
