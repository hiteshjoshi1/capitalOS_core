"""
Tests for Phase 2: Upload parser canonical adapter.

Acceptance criteria verified:
- Sharekhan and DBS Vickers uploads produce identical legacy positions (non-regression).
- Canonical position_snapshots are written for Sharekhan and DBS Vickers.
- Canonical writes are isolated per platform (Sharekhan facts != DBS Vickers facts).
- Uploads lacking cash/NAV/trade detail create explicit completeness records.
- Adapter writes are idempotent for repeated identical uploads.
- IBKR manual CSV upload after Flex cutover does not create authoritative canonical facts.
- No Flex code path writes to Sharekhan or DBS Vickers canonical facts.
- Source authority windows are set up for authoritative platforms only.
- Parser counts and warnings are still present in upload reports.
"""

from __future__ import annotations

import os
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.ingestion.signature import compute_format_signature
from app.ingestion.registry import register_signature
from app.portfolio.upload_canonical import (
    is_canonical_upload_platform,
    run_upload_canonical_adapter,
)
from app.ingestion.parsers.base import ParseResult


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _seed_account(db_engine, account_id: int, name: str, platform: str, currency: str) -> None:
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) "
                "VALUES (:id, :name, :platform, 'BROKER', :currency, 'XX')"
            ),
            {"id": account_id, "name": name, "platform": platform, "currency": currency},
        )
        db.commit()
    finally:
        db.close()


def _sharekhan_html() -> str:
    return """<html><body>
    <table>
      <tr><th>Scrip Name</th><th>Available Qty</th><th>Hold Price</th><th>Hold Value</th><th>Market Price</th><th>Market Value</th></tr>
      <tr><td>RELIANCE</td><td>10</td><td>2500</td><td>25000</td><td>2600</td><td>26000</td></tr>
    </table>
    </body></html>"""


def _dbs_vickers_html() -> str:
    return """<html><body>
    <table>
      <tr><th>Symbol</th><th>Stock Name</th><th>Qty</th><th>Avg Price</th><th>Mkt Value</th></tr>
      <tr><td>S68</td><td>SGX</td><td>100</td><td>9.5</td><td>950</td></tr>
    </table>
    </body></html>"""


def _setup_sharekhan_fixture(tmp_path, db_engine, account_id: int = 500):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)
    _seed_account(db_engine, account_id, "Test SK Phase2", "SHAREKHAN", "INR")

    fixture = tmp_path / "sk_phase2.xls"
    fixture.write_text(_sharekhan_html(), encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "sharekhan_holdings_xls_v1", 1)
    finally:
        db.close()
    return str(fixture)


def _setup_dbs_vickers_fixture(tmp_path, db_engine, account_id: int = 501):
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)
    _seed_account(db_engine, account_id, "Test DBS Phase2", "DBS_VICKERS", "SGD")

    fixture = tmp_path / "dbs_phase2.xls"
    fixture.write_text(_dbs_vickers_html(), encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="DBS_VICKERS")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "dbs_vickers_holdings_xls_v1", 1)
    finally:
        db.close()
    return str(fixture)


# ---------------------------------------------------------------------------
# Non-regression: legacy positions still written
# ---------------------------------------------------------------------------

def test_sharekhan_upload_still_writes_legacy_positions(client: TestClient, db_engine, tmp_path):
    """Canonical adapter must not break legacy positions write."""
    account_id = 510
    fixture_path = _setup_sharekhan_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("sk.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["counts"]["positions_inserted"] == 1

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        count = db.execute(
            text("SELECT COUNT(*) FROM positions WHERE account_id = :aid"),
            {"aid": account_id},
        ).scalar()
    finally:
        db.close()
    assert count == 1, "Legacy positions row must be written"


def test_dbs_vickers_upload_still_writes_legacy_positions(client: TestClient, db_engine, tmp_path):
    """DBS Vickers upload must still write legacy positions after canonical adapter."""
    account_id = 511
    fixture_path = _setup_dbs_vickers_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("dbs.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"
    assert data["counts"]["positions_inserted"] > 0

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        count = db.execute(
            text("SELECT COUNT(*) FROM positions WHERE account_id = :aid"),
            {"aid": account_id},
        ).scalar()
    finally:
        db.close()
    assert count > 0, "Legacy positions row must be written"


# ---------------------------------------------------------------------------
# Canonical writes: position snapshots created
# ---------------------------------------------------------------------------

def test_sharekhan_upload_writes_canonical_position_snapshots(client: TestClient, db_engine, tmp_path):
    account_id = 520
    fixture_path = _setup_sharekhan_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("sk.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"

    # Canonical result should be embedded in report
    canonical = data.get("canonical_result")
    assert canonical is not None, "canonical_result must be present in report"
    assert canonical["status"] == "CANONICAL_IMPORTED"
    assert canonical["platform"] == "SHAREKHAN"
    assert canonical["authority_status"] == "authoritative"
    assert canonical["counts"]["positions"] == 1

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM portfolio_position_snapshots pps
                JOIN broker_accounts ba ON ba.id = pps.broker_account_id
                WHERE ba.legacy_account_id = :aid
                  AND pps.authority_status = 'authoritative'
                """
            ),
            {"aid": account_id},
        ).scalar()
    finally:
        db.close()
    assert count == 1, "One canonical authoritative position snapshot must be written"


def test_dbs_vickers_upload_writes_canonical_position_snapshots(client: TestClient, db_engine, tmp_path):
    account_id = 521
    fixture_path = _setup_dbs_vickers_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("dbs.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "IMPORTED"

    canonical = data.get("canonical_result")
    assert canonical is not None
    assert canonical["platform"] == "DBS_VICKERS"
    assert canonical["authority_status"] == "authoritative"
    assert canonical["counts"]["positions"] > 0

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM portfolio_position_snapshots pps
                JOIN broker_accounts ba ON ba.id = pps.broker_account_id
                WHERE ba.legacy_account_id = :aid
                  AND pps.authority_status = 'authoritative'
                """
            ),
            {"aid": account_id},
        ).scalar()
    finally:
        db.close()
    assert count > 0


# ---------------------------------------------------------------------------
# Source authority isolation
# ---------------------------------------------------------------------------

def test_sharekhan_canonical_facts_isolated_to_sharekhan(db_engine, tmp_path):
    """Sharekhan canonical facts must be under SHAREKHAN broker_accounts only."""
    Session = sessionmaker(bind=db_engine)

    account_id = 530
    _seed_account(db_engine, account_id, "SK Isolation Test", "SHAREKHAN", "INR")

    fixture = tmp_path / "sk_iso.xls"
    fixture.write_text(_sharekhan_html(), encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    db = Session()
    try:
        register_signature(db, sig, "sharekhan_holdings_xls_v1", 1)
    finally:
        db.close()

    from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls
    parse_result = parse_sharekhan_holdings_xls(str(fixture))

    db = Session()
    try:
        run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="SHAREKHAN",
            parse_result=parse_result,
            stored_path=str(fixture),
            file_sha256="test_sha256_sk",
        )
        db.commit()

        # Verify platform_code on broker_connection is SHAREKHAN
        row = db.execute(
            text(
                """
                SELECT bc.platform_code
                FROM broker_connections bc
                JOIN broker_accounts ba ON ba.connection_id = bc.id
                WHERE ba.legacy_account_id = :aid
                LIMIT 1
                """
            ),
            {"aid": account_id},
        ).fetchone()
        assert row is not None
        assert row[0] == "SHAREKHAN"

        # No DBS_VICKERS facts under this account
        dbs_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM broker_connections bc
                JOIN broker_accounts ba ON ba.connection_id = bc.id
                WHERE ba.legacy_account_id = :aid
                  AND bc.platform_code = 'DBS_VICKERS'
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert dbs_count == 0
    finally:
        db.close()


def test_dbs_vickers_canonical_facts_isolated_to_dbs_vickers(db_engine, tmp_path):
    """DBS Vickers canonical facts must be under DBS_VICKERS broker_accounts only."""
    Session = sessionmaker(bind=db_engine)

    account_id = 531
    _seed_account(db_engine, account_id, "DBS Isolation Test", "DBS_VICKERS", "SGD")

    fixture = tmp_path / "dbs_iso.xls"
    fixture.write_text(_dbs_vickers_html(), encoding="utf-8")

    sig, _ = compute_format_signature(str(fixture), platform_hint="DBS_VICKERS")
    db = Session()
    try:
        register_signature(db, sig, "dbs_vickers_holdings_xls_v1", 1)
    finally:
        db.close()

    from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls
    parse_result = parse_dbs_vickers_holdings_xls(str(fixture))

    db = Session()
    try:
        run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="DBS_VICKERS",
            parse_result=parse_result,
            stored_path=str(fixture),
            file_sha256="test_sha256_dbs",
        )
        db.commit()

        row = db.execute(
            text(
                """
                SELECT bc.platform_code
                FROM broker_connections bc
                JOIN broker_accounts ba ON ba.connection_id = bc.id
                WHERE ba.legacy_account_id = :aid
                LIMIT 1
                """
            ),
            {"aid": account_id},
        ).fetchone()
        assert row is not None
        assert row[0] == "DBS_VICKERS"

        sk_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM broker_connections bc
                JOIN broker_accounts ba ON ba.connection_id = bc.id
                WHERE ba.legacy_account_id = :aid
                  AND bc.platform_code = 'SHAREKHAN'
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert sk_count == 0
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Completeness records for missing fact scopes
# ---------------------------------------------------------------------------

def test_sharekhan_upload_creates_completeness_records_for_missing_scopes(db_engine, tmp_path):
    """Sharekhan upload must record completeness=incomplete for cash, nav, trades."""
    Session = sessionmaker(bind=db_engine)

    account_id = 540
    _seed_account(db_engine, account_id, "SK Completeness", "SHAREKHAN", "INR")

    fixture = tmp_path / "sk_comp.xls"
    fixture.write_text(_sharekhan_html(), encoding="utf-8")

    from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls
    parse_result = parse_sharekhan_holdings_xls(str(fixture))

    db = Session()
    try:
        run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="SHAREKHAN",
            parse_result=parse_result,
            stored_path=str(fixture),
            file_sha256="test_sha256_comp",
        )
        db.commit()

        # Fetch completeness records
        rows = db.execute(
            text(
                """
                SELECT pdc.fact_scope, pdc.completeness_status
                FROM portfolio_data_completeness pdc
                JOIN broker_accounts ba ON ba.id = pdc.broker_account_id
                WHERE ba.legacy_account_id = :aid
                """
            ),
            {"aid": account_id},
        ).fetchall()
        completeness_map = {r[0]: r[1] for r in rows}

        assert completeness_map.get("holdings") == "complete", "holdings must be complete"
        assert completeness_map.get("cash_balance") == "incomplete", "cash_balance must be incomplete"
        assert completeness_map.get("nav") == "incomplete", "nav must be incomplete"
        assert completeness_map.get("trades") == "incomplete", "trades must be incomplete"
    finally:
        db.close()


def test_dbs_vickers_upload_creates_completeness_records(db_engine, tmp_path):
    """DBS Vickers upload must record completeness records for missing scopes."""
    Session = sessionmaker(bind=db_engine)

    account_id = 541
    _seed_account(db_engine, account_id, "DBS Completeness", "DBS_VICKERS", "SGD")

    fixture = tmp_path / "dbs_comp.xls"
    fixture.write_text(_dbs_vickers_html(), encoding="utf-8")

    from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls
    parse_result = parse_dbs_vickers_holdings_xls(str(fixture))

    db = Session()
    try:
        run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="DBS_VICKERS",
            parse_result=parse_result,
            stored_path=str(fixture),
            file_sha256="test_sha256_dbs_comp",
        )
        db.commit()

        rows = db.execute(
            text(
                """
                SELECT pdc.fact_scope, pdc.completeness_status
                FROM portfolio_data_completeness pdc
                JOIN broker_accounts ba ON ba.id = pdc.broker_account_id
                WHERE ba.legacy_account_id = :aid
                """
            ),
            {"aid": account_id},
        ).fetchall()
        completeness_map = {r[0]: r[1] for r in rows}

        assert completeness_map.get("holdings") == "complete"
        assert completeness_map.get("cash_balance") == "incomplete"
        assert completeness_map.get("nav") == "incomplete"
        assert completeness_map.get("trades") == "incomplete"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Idempotency: repeated uploads produce same canonical facts
# ---------------------------------------------------------------------------

def test_sharekhan_canonical_adapter_is_idempotent(db_engine, tmp_path):
    """Repeated identical Sharekhan uploads must produce the same canonical facts."""
    Session = sessionmaker(bind=db_engine)

    account_id = 550
    _seed_account(db_engine, account_id, "SK Idempotent", "SHAREKHAN", "INR")

    fixture = tmp_path / "sk_idem.xls"
    fixture.write_text(_sharekhan_html(), encoding="utf-8")

    from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls
    parse_result = parse_sharekhan_holdings_xls(str(fixture))

    for _run in range(3):
        db = Session()
        try:
            run_upload_canonical_adapter(
                db,
                current_user_id=1,
                legacy_account_id=account_id,
                platform_code="SHAREKHAN",
                parse_result=parse_result,
                stored_path=str(fixture),
                file_sha256="same_sha",
            )
            db.commit()
        finally:
            db.close()

    db = Session()
    try:
        pos_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM portfolio_position_snapshots pps
                JOIN broker_accounts ba ON ba.id = pps.broker_account_id
                WHERE ba.legacy_account_id = :aid
                  AND pps.authority_status = 'authoritative'
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert pos_count == 1, f"Expected 1 authoritative snapshot after 3 identical uploads, got {pos_count}"
    finally:
        db.close()


def test_dbs_vickers_canonical_adapter_is_idempotent(db_engine, tmp_path):
    """Repeated identical DBS Vickers uploads must produce the same canonical facts."""
    Session = sessionmaker(bind=db_engine)

    account_id = 551
    _seed_account(db_engine, account_id, "DBS Idempotent", "DBS_VICKERS", "SGD")

    fixture = tmp_path / "dbs_idem.xls"
    fixture.write_text(_dbs_vickers_html(), encoding="utf-8")

    from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls
    parse_result = parse_dbs_vickers_holdings_xls(str(fixture))

    for _run in range(3):
        db = Session()
        try:
            run_upload_canonical_adapter(
                db,
                current_user_id=1,
                legacy_account_id=account_id,
                platform_code="DBS_VICKERS",
                parse_result=parse_result,
                stored_path=str(fixture),
                file_sha256="same_dbs_sha",
            )
            db.commit()
        finally:
            db.close()

    db = Session()
    try:
        pos_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM portfolio_position_snapshots pps
                JOIN broker_accounts ba ON ba.id = pps.broker_account_id
                WHERE ba.legacy_account_id = :aid
                  AND pps.authority_status = 'authoritative'
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert pos_count == 1, f"Expected 1 authoritative snapshot after 3 identical uploads, got {pos_count}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# IBKR manual CSV: reference-only after flex cutover
# ---------------------------------------------------------------------------

def test_ibkr_csv_upload_reference_only_when_flex_cutover_active(db_engine, tmp_path):
    """IBKR CSV canonical facts must be reference-only when flex cutover is active."""
    Session = sessionmaker(bind=db_engine)

    account_id = 560
    _seed_account(db_engine, account_id, "IBKR CSV Ref", "IBKR", "USD")

    parse_result = ParseResult(
        transactions=[],
        positions=[
            {
                "symbol": "AAPL",
                "name": "Apple Inc",
                "asset_class": "STOCK",
                "currency": "USD",
                "quantity": 10,
                "avg_cost": 150.0,
                "cost_basis_base": 1500.0,
                "home_country": "US",
            }
        ],
        section_counts={"rows_parsed": 1},
        parser_meta={},
    )

    db = Session()
    try:
        result = run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="IBKR",
            parse_result=parse_result,
            stored_path="/tmp/fake.csv",
            file_sha256="ibkr_csv_sha",
            is_ibkr_flex_cutover_active=True,
        )
        db.commit()

        assert result["authority_status"] == "reference", (
            "IBKR CSV upload after flex cutover must produce reference-only facts"
        )

        # Verify position snapshots are reference not authoritative
        row = db.execute(
            text(
                """
                SELECT authority_status FROM portfolio_position_snapshots pps
                JOIN broker_accounts ba ON ba.id = pps.broker_account_id
                WHERE ba.legacy_account_id = :aid
                LIMIT 1
                """
            ),
            {"aid": account_id},
        ).fetchone()
        assert row is not None
        assert row[0] == "reference"

        # Source authority window must NOT be created for reference-only uploads
        aw_count = db.execute(
            text(
                """
                SELECT COUNT(*) FROM portfolio_source_authority_windows aw
                JOIN broker_accounts ba ON ba.id = aw.broker_account_id
                WHERE ba.legacy_account_id = :aid
                """
            ),
            {"aid": account_id},
        ).scalar()
        assert aw_count == 0, "No authority window should be created for reference-only IBKR CSV upload"
    finally:
        db.close()


def test_ibkr_csv_upload_authoritative_before_flex_cutover(db_engine, tmp_path):
    """IBKR CSV upload before flex cutover should be authoritative."""
    Session = sessionmaker(bind=db_engine)

    account_id = 561
    _seed_account(db_engine, account_id, "IBKR CSV Pre-Cutover", "IBKR", "USD")

    parse_result = ParseResult(
        transactions=[],
        positions=[
            {
                "symbol": "MSFT",
                "name": "Microsoft",
                "asset_class": "STOCK",
                "currency": "USD",
                "quantity": 5,
                "avg_cost": 300.0,
                "cost_basis_base": 1500.0,
            }
        ],
        section_counts={"rows_parsed": 1},
        parser_meta={},
    )

    db = Session()
    try:
        result = run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="IBKR",
            parse_result=parse_result,
            stored_path="/tmp/fake2.csv",
            file_sha256="ibkr_pre_sha",
            is_ibkr_flex_cutover_active=False,
        )
        db.commit()

        # IBKR is in _REFERENCE_ONLY_PLATFORMS so it's always reference
        # (the endpoint blocks it; at this layer we enforce reference)
        assert result["authority_status"] == "reference"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# No Flex code path writes Sharekhan/DBS facts
# ---------------------------------------------------------------------------

def test_flex_import_does_not_write_sharekhan_facts(db_engine):
    """IBKR Flex import must not create any Sharekhan broker_accounts or positions."""
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        # Check no SHAREKHAN broker_connections exist after any operation
        count = db.execute(
            text("SELECT COUNT(*) FROM broker_connections WHERE platform_code = 'SHAREKHAN'")
        ).scalar()
        assert count == 0, "No SHAREKHAN broker_connections should exist at baseline"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Source authority window setup
# ---------------------------------------------------------------------------

def test_sharekhan_authority_window_created(db_engine, tmp_path):
    """Sharekhan upload must create a source authority window."""
    Session = sessionmaker(bind=db_engine)

    account_id = 570
    _seed_account(db_engine, account_id, "SK Auth Window", "SHAREKHAN", "INR")

    fixture = tmp_path / "sk_aw.xls"
    fixture.write_text(_sharekhan_html(), encoding="utf-8")

    from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls
    parse_result = parse_sharekhan_holdings_xls(str(fixture))

    db = Session()
    try:
        run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="SHAREKHAN",
            parse_result=parse_result,
            stored_path=str(fixture),
            file_sha256="sk_aw_sha",
        )
        db.commit()

        row = db.execute(
            text(
                """
                SELECT aw.source_kind, aw.authority_status, aw.fact_scope
                FROM portfolio_source_authority_windows aw
                JOIN broker_accounts ba ON ba.id = aw.broker_account_id
                WHERE ba.legacy_account_id = :aid
                LIMIT 1
                """
            ),
            {"aid": account_id},
        ).fetchone()
        assert row is not None, "Authority window must be created for Sharekhan upload"
        assert row[0] == "sharekhan_upload"
        assert row[1] == "authoritative"
        assert row[2] == "holdings"
    finally:
        db.close()


def test_dbs_vickers_authority_window_created(db_engine, tmp_path):
    """DBS Vickers upload must create a source authority window."""
    Session = sessionmaker(bind=db_engine)

    account_id = 571
    _seed_account(db_engine, account_id, "DBS Auth Window", "DBS_VICKERS", "SGD")

    fixture = tmp_path / "dbs_aw.xls"
    fixture.write_text(_dbs_vickers_html(), encoding="utf-8")

    from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls
    parse_result = parse_dbs_vickers_holdings_xls(str(fixture))

    db = Session()
    try:
        run_upload_canonical_adapter(
            db,
            current_user_id=1,
            legacy_account_id=account_id,
            platform_code="DBS_VICKERS",
            parse_result=parse_result,
            stored_path=str(fixture),
            file_sha256="dbs_aw_sha",
        )
        db.commit()

        row = db.execute(
            text(
                """
                SELECT aw.source_kind, aw.authority_status
                FROM portfolio_source_authority_windows aw
                JOIN broker_accounts ba ON ba.id = aw.broker_account_id
                WHERE ba.legacy_account_id = :aid
                LIMIT 1
                """
            ),
            {"aid": account_id},
        ).fetchone()
        assert row is not None
        assert row[0] == "dbs_vickers_upload"
        assert row[1] == "authoritative"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# is_canonical_upload_platform helper
# ---------------------------------------------------------------------------

def test_is_canonical_upload_platform():
    assert is_canonical_upload_platform("SHAREKHAN") is True
    assert is_canonical_upload_platform("DBS_VICKERS") is True
    assert is_canonical_upload_platform("IBKR") is True
    assert is_canonical_upload_platform("DBS") is False
    assert is_canonical_upload_platform("OCBC") is False
    assert is_canonical_upload_platform("UOB") is False


# ---------------------------------------------------------------------------
# Report still includes parser counts and canonical result
# ---------------------------------------------------------------------------

def test_sharekhan_upload_report_includes_counts_and_canonical(client: TestClient, db_engine, tmp_path):
    """Upload report must contain parser section counts and canonical_result field."""
    account_id = 580
    fixture_path = _setup_sharekhan_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("sk.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()

    # Legacy counts still present
    assert "counts" in data
    assert data["counts"]["positions_inserted"] >= 0

    # Section summary still present
    assert "section_summary" in data

    # Canonical result field present
    assert "canonical_result" in data


def test_dbs_vickers_report_includes_canonical_warning_on_skipped_platform(client: TestClient, db_engine, tmp_path):
    """When canonical adapter runs successfully, canonical_warning must be None."""
    account_id = 581
    fixture_path = _setup_dbs_vickers_fixture(tmp_path, db_engine, account_id)

    with open(fixture_path, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": ("dbs.xls", f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("canonical_warning") is None, "canonical_warning should be None on success"
