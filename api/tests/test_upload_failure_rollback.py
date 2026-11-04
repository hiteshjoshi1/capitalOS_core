"""A failed import keeps no partial work, and leaves evidence behind (#136).

- Upload runner: an error inside the canonical write rolls back the
  transactions inserted earlier in the same upload and the snapshots the adapter
  deleted, then records the FAILED job plus a failed import run, its raw
  document and a data-quality event in a fresh transaction.
- IBKR Flex: the run row and raw XML are stored before parsing, so malformed XML
  leaves a failed run, the stored document and an error event; rows the parser
  drops and NAV attributes it can't read become data-quality warnings, and a
  NAV row with no total fails the import instead of being summed from parts.

Synthetic data only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

import app.ingestion.runner as runner_mod
import app.portfolio.upload_canonical as uc
from app.ingestion.parsers.base import ParseResult
from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature
from app.portfolio.ibkr_flex import IbkrFlexImportError, parse_flex_statement, run_ibkr_flex_import_from_xml

PARSER_KEY = "sharekhan_holdings_xls_v1"


def _scalar(db_engine, sql: str, **params: Any) -> Any:
    with db_engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _seed_upload_account(db_engine, account_id: int) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) "
                "VALUES (:id, 'Rollback Test', 'SHAREKHAN', 'BROKER', 'INR', 'XX')"
            ),
            {"id": account_id},
        )


def _fake_parse_result(tag: str, quantity: float) -> ParseResult:
    return ParseResult(
        transactions=[
            {
                "ts": datetime(2026, 10, 15, tzinfo=timezone.utc),
                "type": "DEPOSIT",
                "amount": 100.0 + quantity,
                "currency": "INR",
                "merchant_counterparty": f"Synthetic {tag}",
                "category": "",
            }
        ],
        positions=[
            {
                "symbol": "SYNTH",
                "name": "Synthetic Co",
                "asset_class": "STOCK",
                "currency": "INR",
                "quantity": quantity,
                "avg_cost": 10.0,
                "cost_basis_base": 10.0 * quantity,
                "market_price": 11.0,
                "market_value_base": 11.0 * quantity,
                "home_country": "IN",
            }
        ],
        section_counts={"holdings": 1},
        parser_meta={},
    )


def _upload(client: TestClient, account_id: int, fixture: Path) -> dict:
    with open(fixture, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={account_id}",
            files={"file": (fixture.name, f, "application/vnd.ms-excel")},
        )
    assert resp.status_code == 200
    return resp.json()


def test_canonical_failure_mid_upload_rolls_back_transactions_and_snapshot_deletes(
    client: TestClient, db_engine, tmp_path, monkeypatch
):
    account_id = 9136
    _seed_upload_account(db_engine, account_id)
    fixture = tmp_path / "holdings.xls"
    fixture.write_text("<html><body><table><tr><th>Scrip Name</th></tr></table></body></html>", encoding="utf-8")
    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, PARSER_KEY, 1)
    finally:
        db.close()

    # First upload succeeds: one transaction, one canonical snapshot (qty 5).
    monkeypatch.setitem(
        runner_mod.PARSER_REGISTRY, PARSER_KEY, ("excel", lambda path: _fake_parse_result("first", 5.0))
    )
    first = _upload(client, account_id, fixture)
    assert first["status"] == "IMPORTED"
    tx_before = _scalar(db_engine, "SELECT COUNT(*) FROM transactions WHERE account_id = :a", a=account_id)
    snap_sql = (
        "SELECT COUNT(*) FROM portfolio_position_snapshots pps "
        "JOIN broker_accounts ba ON ba.id = pps.broker_account_id WHERE ba.legacy_account_id = :a"
    )
    snaps_before = _scalar(db_engine, snap_sql, a=account_id)
    assert tx_before == 1
    assert snaps_before == 1

    # Second upload: a new transaction is inserted, the adapter deletes the
    # existing snapshot, then the canonical insert fails part-way.
    monkeypatch.setitem(
        runner_mod.PARSER_REGISTRY, PARSER_KEY, ("excel", lambda path: _fake_parse_result("second", 7.0))
    )

    def _fail(*args: Any, **kwargs: Any) -> int:
        raise ValueError("synthetic parser error mid-upload")

    monkeypatch.setattr(uc, "_insert_upload_position_snapshots", _fail)
    second = _upload(client, account_id, fixture)

    assert second["status"] == "FAILED"
    assert second["error_class"] == "ValueError"
    assert _scalar(db_engine, "SELECT COUNT(*) FROM transactions WHERE account_id = :a", a=account_id) == tx_before
    assert _scalar(db_engine, snap_sql, a=account_id) == snaps_before
    assert _scalar(
        db_engine,
        "SELECT pps.quantity FROM portfolio_position_snapshots pps "
        "JOIN broker_accounts ba ON ba.id = pps.broker_account_id WHERE ba.legacy_account_id = :a",
        a=account_id,
    ) == pytest.approx(5.0)
    assert _scalar(db_engine, "SELECT status FROM import_jobs WHERE id = :id", id=second["job_id"]) == "FAILED"

    # The failure itself was recorded in a fresh transaction.
    with db_engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT id, status, error_code, raw_document_id FROM broker_import_runs "
                "WHERE legacy_account_id = :a ORDER BY id DESC LIMIT 1"
            ),
            {"a": account_id},
        ).mappings().one()
        event = conn.execute(
            text(
                "SELECT severity, event_code, message, raw_document_id FROM portfolio_data_quality_events "
                "WHERE import_run_id = :run ORDER BY id DESC LIMIT 1"
            ),
            {"run": run["id"]},
        ).mappings().one()
    assert run["status"] == "failed"
    assert run["error_code"] == "canonical_write_failed"
    assert run["raw_document_id"] is not None
    assert event["severity"] == "error"
    assert event["event_code"] == "canonical_write_failed"
    assert "ValueError" in event["message"]
    assert event["raw_document_id"] == run["raw_document_id"]


def test_canonical_adapter_missing_does_not_commit_transactions(client: TestClient, db_engine, tmp_path, monkeypatch):
    account_id = 9137
    _seed_upload_account(db_engine, account_id)
    fixture = tmp_path / "unknown.xls"
    fixture.write_text("<html><body><table><tr><th>Unknown Col</th></tr></table></body></html>", encoding="utf-8")
    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        register_signature(db, sig, "future_parser_v136", 1)
    finally:
        db.close()
    monkeypatch.setitem(
        runner_mod.PARSER_REGISTRY, "future_parser_v136", ("excel", lambda path: _fake_parse_result("x", 1.0))
    )
    from app.ingestion import account_checks

    monkeypatch.setitem(account_checks.PARSER_ACCOUNT_TYPES, "future_parser_v136", frozenset({"BROKER"}))

    data = _upload(client, account_id, fixture)

    assert data["status"] == "FAILED"
    assert "canonical_adapter_missing" in data["error_message"]
    assert _scalar(db_engine, "SELECT COUNT(*) FROM transactions WHERE account_id = :a", a=account_id) == 0


# ---------------------------------------------------------------------------
# IBKR Flex
# ---------------------------------------------------------------------------

def _seed_ibkr_account(db_engine, account_id: int = 9300) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) "
                "VALUES (93, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) "
                "VALUES (:id, 'IBKR Synthetic', 'IBKR', 'BROKER', 'USD', 'US', 93)"
            ),
            {"id": account_id},
        )


def _flex_xml(*, nav_row: str, positions: str) -> str:
    return f"""
    <FlexQueryResponse>
      <FlexStatements count="1">
        <FlexStatement accountId="U0000000" fromDate="2026-10-30" toDate="2026-10-30">
          <EquitySummaryInBase>{nav_row}</EquitySummaryInBase>
          <OpenPositions>{positions}</OpenPositions>
          <ConversionRates>
            <ConversionRate reportDate="2026-10-30" fromCurrency="USD" toCurrency="USD" rate="1" />
          </ConversionRates>
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """


GOOD_POSITION = (
    '<OpenPosition reportDate="2026-10-30" conid="111" symbol="SYNA" currency="USD" '
    'position="2" positionValue="200" markPrice="100" />'
)
NO_CONID_POSITION = (
    '<OpenPosition reportDate="2026-10-30" symbol="SYNB" currency="USD" position="1" positionValue="50" />'
)


def test_malformed_flex_xml_leaves_failed_run_and_stored_raw_document(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    xml_text = "<FlexQueryResponse><FlexStatements><FlexStatement accountId="  # truncated

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        with pytest.raises(IbkrFlexImportError) as exc:
            run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=9300, xml_text=xml_text)
        assert exc.value.code == "parse_failed"
    finally:
        db.close()

    with db_engine.connect() as conn:
        run = conn.execute(
            text(
                "SELECT id, status, error_code, error_message, raw_document_id, finished_at "
                "FROM broker_import_runs WHERE legacy_account_id = 9300"
            )
        ).mappings().one()
        doc = conn.execute(
            text("SELECT id, import_run_id, storage_path, content_type FROM raw_broker_documents")
        ).mappings().one()
        event = conn.execute(
            text("SELECT import_run_id, raw_document_id, severity, event_code FROM portfolio_data_quality_events")
        ).mappings().one()
    assert run["status"] == "failed"
    assert run["error_code"] == "parse_failed"
    assert "Invalid Flex XML" in run["error_message"]
    assert run["finished_at"] is not None
    assert run["raw_document_id"] == doc["id"]
    assert doc["import_run_id"] == run["id"]
    assert doc["content_type"] == "application/xml"
    assert Path(doc["storage_path"]).read_text(encoding="utf-8") == xml_text
    assert event["import_run_id"] == run["id"]
    assert event["raw_document_id"] == doc["id"]
    assert (event["severity"], event["event_code"]) == ("error", "parse_failed")
    assert _scalar(db_engine, "SELECT COUNT(*) FROM portfolio_import_locks") == 0
    assert _scalar(db_engine, "SELECT COUNT(*) FROM portfolio_nav_snapshots") == 0


def test_unexpected_parser_exception_records_error_class(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    import app.portfolio.ibkr_flex as flex

    def _boom(xml_text: str):
        raise KeyError("someAttribute")

    monkeypatch.setattr(flex, "parse_flex_statement", _boom)
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        with pytest.raises(KeyError):
            run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=9300, xml_text="<x/>")
    finally:
        db.close()
    with db_engine.connect() as conn:
        run = conn.execute(text("SELECT status, error_code, error_message FROM broker_import_runs")).mappings().one()
    assert run["status"] == "failed"
    assert run["error_code"] == "parse_failed"
    assert run["error_message"].startswith("KeyError")
    assert _scalar(db_engine, "SELECT COUNT(*) FROM raw_broker_documents") == 1


def test_parse_failure_run_is_linked_to_known_broker_account(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    good = _flex_xml(
        nav_row='<EquitySummaryByReportDateInBase reportDate="2026-10-30" cash="10" stock="200" total="210" />',
        positions=GOOD_POSITION,
    )
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        first = run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=9300, xml_text=good)
        with pytest.raises(IbkrFlexImportError):
            run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=9300, xml_text="not xml")
    finally:
        db.close()
    assert _scalar(
        db_engine, "SELECT broker_account_id FROM broker_import_runs WHERE status = 'failed'"
    ) == first["broker_account_id"]


def test_successful_import_fills_run_and_document_after_parsing(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    xml_text = _flex_xml(
        nav_row='<EquitySummaryByReportDateInBase reportDate="2026-10-30" cash="10" stock="200" total="210" />',
        positions=GOOD_POSITION,
    )
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        result = run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=9300, xml_text=xml_text)
    finally:
        db.close()
    with db_engine.connect() as conn:
        run = conn.execute(text("SELECT * FROM broker_import_runs")).mappings().one()
        doc = conn.execute(text("SELECT * FROM raw_broker_documents")).mappings().one()
    assert run["status"] == "completed"
    assert run["broker_account_id"] == result["broker_account_id"]
    assert str(run["report_date_to"]) == "2026-10-30"
    assert run["parsed_at"] is not None
    assert doc["broker_account_id"] == result["broker_account_id"]
    assert str(doc["report_date_from"]) == "2026-10-30"
    assert _scalar(db_engine, "SELECT COUNT(*) FROM portfolio_data_quality_events") == 0


def test_skipped_position_row_is_recorded_as_warning(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    xml_text = _flex_xml(
        nav_row='<EquitySummaryByReportDateInBase reportDate="2026-10-30" cash="10" stock="250" total="260" />',
        positions=GOOD_POSITION + NO_CONID_POSITION,
    )
    statement = parse_flex_statement(xml_text)
    assert [p.symbol for p in statement.positions] == ["SYNA"]
    assert statement.data_quality_warnings == [
        ("skipped_position_row", "1 OpenPosition row(s) skipped: no conid (SYNB)")
    ]

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        result = run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=9300, xml_text=xml_text)
    finally:
        db.close()
    assert result["status"] == "IMPORTED"
    with db_engine.connect() as conn:
        event = conn.execute(
            text(
                "SELECT severity, event_code, message, import_run_id, raw_document_id "
                "FROM portfolio_data_quality_events"
            )
        ).mappings().one()
    assert (event["severity"], event["event_code"]) == ("warning", "skipped_position_row")
    assert "SYNB" in event["message"]
    assert event["import_run_id"] == result["import_run_id"]
    assert event["raw_document_id"] == result["raw_document_id"]


def test_missing_nav_component_is_a_warning():
    statement = parse_flex_statement(
        _flex_xml(
            nav_row='<EquitySummaryByReportDateInBase reportDate="2026-10-30" cash="10" equities="200" total="210" />',
            positions=GOOD_POSITION,
        )
    )
    assert statement.data_quality_errors == []
    assert statement.nav_snapshots[0].total_nav_base == 210
    assert ("missing_nav_component", "1 equity summary row(s) have no stock attribute; read as 0") in (
        statement.data_quality_warnings
    )


def test_missing_nav_total_fails_the_import_instead_of_summing_parts(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed_ibkr_account(db_engine)
    xml_text = _flex_xml(
        nav_row='<EquitySummaryByReportDateInBase reportDate="2026-10-30" cash="10" stock="200" netAssetValue="210" />',
        positions=GOOD_POSITION,
    )
    statement = parse_flex_statement(xml_text)
    assert statement.nav_snapshots == []
    assert statement.data_quality_errors[0][0] == "missing_nav_total"

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        with pytest.raises(IbkrFlexImportError) as exc:
            run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=9300, xml_text=xml_text)
    finally:
        db.close()
    assert exc.value.code == "missing_nav_total"
    assert _scalar(db_engine, "SELECT status FROM broker_import_runs") == "failed"
    assert _scalar(db_engine, "SELECT COUNT(*) FROM portfolio_nav_snapshots") == 0
    assert _scalar(db_engine, "SELECT COUNT(*) FROM portfolio_import_locks") == 0
    assert "2026-10-30" in _scalar(
        db_engine, "SELECT message FROM portfolio_data_quality_events WHERE event_code = 'missing_nav_total'"
    )
