"""Uploads are dated by the statement's own as-of date, not the upload day (#141).

Synthetic fixtures only.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import app_today
from app.ingestion.as_of import find_stated_date, resolve_upload_as_of
from app.ingestion.parsers.dbs_vickers_holdings_xls_v1 import parse_dbs_vickers_holdings_xls
from app.ingestion.parsers.ibkr_activity_csv_v1 import parse_ibkr_activity_csv
from app.ingestion.parsers.sharekhan_holdings_xls_v1 import parse_sharekhan_holdings_xls
from app.ingestion.registry import register_signature
from app.ingestion.signature import compute_format_signature
from app.wealth_rollup_dirty import dirty_state

ACCOUNT = 941
OLD = date(2025, 6, 30)  # well before any "today" the suite runs on: always a completed History month


# ─── The app-timezone "today" ─────────────────────────────────────────────────


def test_app_today_uses_app_timezone(monkeypatch):
    late_utc_evening = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)  # 04:00 on 3 Nov in Singapore
    monkeypatch.delenv("TZ", raising=False)
    assert app_today(late_utc_evening) == date(2026, 11, 3)
    monkeypatch.setenv("TZ", "UTC")
    assert app_today(late_utc_evening) == date(2026, 11, 2)
    monkeypatch.setenv("TZ", "Not/AZone")
    assert app_today(late_utc_evening) == date(2026, 11, 3)
    # A naive instant is UTC.
    monkeypatch.delenv("TZ", raising=False)
    assert app_today(datetime(2026, 11, 2, 20, 0)) == date(2026, 11, 3)


# ─── Reading a stated date ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cells, expected",
    [
        (["Holdings as on 01/10/2026"], date(2026, 10, 1)),
        (["Holding Statement As On : 05-Oct-2026"], date(2026, 10, 5)),
        (["As at", "2026-09-30"], date(2026, 9, 30)),
        (["As of:", datetime(2026, 9, 30, 0, 0)], date(2026, 9, 30)),
        (["Date : 3 September 2026"], date(2026, 9, 3)),
        (["Valuation date October 31, 2026"], date(2026, 10, 31)),
        (["Report Date", "31.10.2026"], date(2026, 10, 31)),
        # Unlabelled or mid-text "date" columns are not the statement's date.
        (["Purchase Date", "01/02/2020", "Qty"], None),
        (["Client Code XX000", "15/08/1990"], None),
        (["as on", "not a date"], None),
        (["As on 31/02/2026"], None),
    ],
)
def test_find_stated_date(cells, expected):
    assert find_stated_date(cells) == expected


def test_resolve_precedence_file_then_user_then_fallback():
    user = date(2026, 8, 1)
    assert resolve_upload_as_of({"as_of": "2026-07-31"}, user) == (date(2026, 7, 31), "file")
    assert resolve_upload_as_of({}, user) == (user, "user")
    assert resolve_upload_as_of({}, None) == (app_today(), "fallback")
    # A balance row dated by the parser counts as the file's date.
    assert resolve_upload_as_of({}, user, [{"as_of": datetime(2026, 7, 15)}]) == (date(2026, 7, 15), "file")


# ─── Parsers pick the date up ─────────────────────────────────────────────────


def _sharekhan_html(as_on: str | None) -> str:
    title = (
        f"<table><tr><td>Client Code</td><td>XX000</td></tr><tr><td>Holdings as on {as_on}</td></tr></table>"
        if as_on
        else ""
    )
    return f"""<html><body>{title}
    <table>
      <tr><th>Scrip Name</th><th>Available Qty</th><th>Hold Price</th><th>Hold Value</th><th>Market Price</th><th>Market Value</th></tr>
      <tr><td>TESTCO</td><td>10</td><td>100</td><td>1000</td><td>110</td><td>1100</td></tr>
    </table></body></html>"""


def test_sharekhan_html_reads_as_on(tmp_path):
    fixture = tmp_path / "holdings.xls"
    fixture.write_text(_sharekhan_html("30/06/2025"), encoding="utf-8")
    result = parse_sharekhan_holdings_xls(str(fixture))
    assert result.parser_meta["as_of"] == "2025-06-30"
    assert len(result.positions) == 1

    fixture.write_text(_sharekhan_html(None), encoding="utf-8")
    assert "as_of" not in parse_sharekhan_holdings_xls(str(fixture)).parser_meta


def test_dbs_vickers_xlsx_reads_preamble_date(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Portfolio Holdings"])
    ws.append(["As at", datetime(2025, 6, 30)])
    ws.append([])
    ws.append(["Symbol", "Stock Name", "Qty", "Avg Price", "Mkt Value"])
    ws.append(["TST", "Test Co", 100, 1.5, 160])
    fixture = tmp_path / "vickers.xlsx"
    wb.save(fixture)
    result = parse_dbs_vickers_holdings_xls(str(fixture))
    assert result.parser_meta["as_of"] == "2025-06-30"
    assert result.positions[0]["quantity"] == 100


def test_sharekhan_xlsx_reads_preamble_date(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Holding Statement As On : 30-Jun-2025"])
    ws.append(["Scrip Name", "Available Qty", "Hold Price", "Market Price"])
    ws.append(["TESTCO", 10, 100, 110])
    fixture = tmp_path / "sharekhan.xlsx"
    wb.save(fixture)
    result = parse_sharekhan_holdings_xls(str(fixture))
    assert result.parser_meta["as_of"] == "2025-06-30"
    assert result.positions[0]["symbol"] == "TESTCO"


def test_ibkr_activity_reads_statement_period_end(tmp_path):
    fixture = tmp_path / "activity.csv"
    fixture.write_text(
        "Statement,Header,Field Name,Field Value\n"
        'Statement,Data,Period,"June 1, 2025 - June 30, 2025"\n'
        "Open Positions,Header,Symbol,Quantity,Currency,Asset Category\n"
        "Open Positions,Data,TST,5,USD,Stocks\n",
        encoding="utf-8",
    )
    result = parse_ibkr_activity_csv(str(fixture), ",")
    assert result.parser_meta["statement_period_end"] == "2025-06-30"
    assert result.positions[0]["symbol"] == "TST"


# ─── End to end through POST /ingest/upload ──────────────────────────────────


@pytest.fixture()
def sharekhan_account(db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(:id, 'Synthetic broker', 'SHAREKHAN', 1, 'BROKER', 'INR', 'IN')"
            ),
            {"id": ACCOUNT},
        )
    return ACCOUNT


def _upload(client: TestClient, db_engine, tmp_path, html: str, as_of: str | None = None, name: str = "h.xls") -> dict:
    fixture = tmp_path / name
    fixture.write_text(html, encoding="utf-8")
    sig, _ = compute_format_signature(str(fixture), platform_hint="SHAREKHAN")
    db = sessionmaker(bind=db_engine)()
    try:
        register_signature(db, sig, "sharekhan_holdings_xls_v1", 1)
    finally:
        db.close()
    os.makedirs(os.getenv("DATA_DIR", "/tmp/capitalos_test_data"), exist_ok=True)
    data = {"as_of": as_of} if as_of else None
    with open(fixture, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={ACCOUNT}",
            files={"file": (name, f, "application/vnd.ms-excel")},
            data=data,
        )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["status"] == "IMPORTED", report
    return report


def _snapshot_dates(db_engine) -> dict[str, int]:
    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT ps.report_date, COUNT(*) FROM portfolio_position_snapshots ps "
                "JOIN broker_accounts ba ON ba.id = ps.broker_account_id "
                "WHERE ba.legacy_account_id = :a GROUP BY ps.report_date"
            ),
            {"a": ACCOUNT},
        ).fetchall()
    return {str(r[0])[:10]: int(r[1]) for r in rows}


def _run_metadata(db_engine, import_run_id: int) -> dict:
    with db_engine.connect() as conn:
        raw = conn.execute(
            text("SELECT metadata_json FROM broker_import_runs WHERE id = :id"), {"id": import_run_id}
        ).scalar()
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


def test_older_holdings_file_lands_on_its_own_date_and_keeps_todays(client, db_engine, tmp_path, sharekhan_account):
    today = app_today()
    current = _upload(client, db_engine, tmp_path, _sharekhan_html(None), name="today.xls")
    assert current["canonical_result"]["report_date"] == today.isoformat()
    assert current["canonical_result"]["as_of_source"] == "fallback"

    older = _upload(client, db_engine, tmp_path, _sharekhan_html(OLD.strftime("%d/%m/%Y")), name="older.xls")
    result = older["canonical_result"]
    assert result["report_date"] == OLD.isoformat()
    assert result["as_of_date"] == OLD.isoformat()
    assert result["as_of_source"] == "file"

    # Two snapshots: the older file's own date, and today's left intact.
    assert _snapshot_dates(db_engine) == {today.isoformat(): 1, OLD.isoformat(): 1}
    assert _run_metadata(db_engine, result["import_run_id"])["as_of_source"] == "file"

    # History is invalidated from the statement's date, not the upload day.
    db = Session(bind=db_engine)
    try:
        assert dirty_state(db, 1)[0] == OLD
    finally:
        db.close()


def test_user_as_of_dates_a_file_without_one(client, db_engine, tmp_path, sharekhan_account):
    report = _upload(client, db_engine, tmp_path, _sharekhan_html(None), as_of=OLD.isoformat())
    result = report["canonical_result"]
    assert (result["report_date"], result["as_of_source"], result["user_as_of"]) == (OLD.isoformat(), "user", OLD.isoformat())
    assert _snapshot_dates(db_engine) == {OLD.isoformat(): 1}
    meta = _run_metadata(db_engine, result["import_run_id"])
    assert meta == {"as_of_date": OLD.isoformat(), "as_of_source": "user", "user_as_of": OLD.isoformat()}


def test_file_date_beats_user_date(client, db_engine, tmp_path, sharekhan_account):
    chosen = OLD + timedelta(days=10)
    report = _upload(client, db_engine, tmp_path, _sharekhan_html(OLD.strftime("%d/%m/%Y")), as_of=chosen.isoformat())
    result = report["canonical_result"]
    assert result["report_date"] == OLD.isoformat()
    assert result["as_of_source"] == "file"
    assert result["user_as_of"] == chosen.isoformat()
    assert "as_of_note" in result
    assert _snapshot_dates(db_engine) == {OLD.isoformat(): 1}


def test_future_as_of_is_rejected(client, db_engine, tmp_path, sharekhan_account):
    fixture = tmp_path / "h.xls"
    fixture.write_text(_sharekhan_html(None), encoding="utf-8")
    with open(fixture, "rb") as f:
        resp = client.post(
            f"/ingest/upload?account_id={ACCOUNT}",
            files={"file": ("h.xls", f, "application/vnd.ms-excel")},
            data={"as_of": (app_today() + timedelta(days=5)).isoformat()},
        )
    assert resp.status_code == 422
    assert _snapshot_dates(db_engine) == {}


def test_bank_balance_upload_records_user_as_of(db_engine):
    from app.ingestion.parsers.base import ParseResult
    from app.portfolio.upload_canonical import run_upload_balance_canonical_adapter

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(942, 'Synthetic bank', 'TESTBANK', 1, 'BANK', 'SGD', 'SG')"
            )
        )
    db = Session(bind=db_engine)
    try:
        result = run_upload_balance_canonical_adapter(
            db,
            account_id=942,
            import_job_id=None,
            parse_result=ParseResult(
                transactions=[],
                positions=[{"asset_class": "CASH", "currency": "SGD", "quantity": 100.0, "as_of": None}],
                section_counts={},
                parser_meta={},
            ),
            user_as_of=OLD,
        )
        db.commit()
    finally:
        db.close()
    assert (result["as_of_date"], result["as_of_source"]) == (OLD.isoformat(), "user")
    with db_engine.connect() as conn:
        row = conn.execute(
            text("SELECT as_of_date, metadata_json FROM account_balance_snapshots WHERE account_id = 942")
        ).one()
    assert str(row[0])[:10] == OLD.isoformat()
    assert json.loads(row[1])["as_of_source"] == "user"
