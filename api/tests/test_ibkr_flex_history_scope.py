"""#134: a multi-day Flex import must only replace what the report carries, and the
rebuild tool restores what earlier (pre-fix) imports deleted. Synthetic data only."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.portfolio.ibkr_flex import run_ibkr_flex_import_from_xml
from app.portfolio.ibkr_flex_rebuild import rebuild_ibkr_flex_snapshots

ACCOUNT = "U0000134"
LEGACY_ACCOUNT_ID = 340
D1, D2, D3 = "2026-03-02", "2026-03-03", "2026-03-04"


def _seed(db_engine) -> None:
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        db.execute(
            text(
                "INSERT INTO platforms (id, code, name, platform_type, country) "
                "VALUES (30, 'IBKR', 'Interactive Brokers', 'BROKER', 'US')"
            )
        )
        db.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) "
                "VALUES (:id, 'IBKR History Test', 'IBKR', 'BROKER', 'SGD', 'SG', 30)"
            ),
            {"id": LEGACY_ACCOUNT_ID},
        )
        db.commit()
    finally:
        db.close()


def _nav(day: str, total: str, stock: str = "100.00", cash: str = "50.00") -> str:
    return (
        f'<EquitySummaryByReportDateInBase reportDate="{day}" cash="{cash}" stock="{stock}" '
        f'options="0" funds="0" bonds="0" interestAccruals="0" dividendAccruals="0" total="{total}" />'
    )


def _position(day: str, conid: str = "1001", symbol: str = "SYNA", value: str = "100.00") -> str:
    return (
        f'<OpenPosition reportDate="{day}" conid="{conid}" symbol="{symbol}" description="SYNTHETIC" '
        f'assetCategory="STK" listingExchange="NASDAQ" currency="SGD" position="1" markPrice="{value}" '
        f'positionValue="{value}" positionValueInBase="{value}" fxRateToBase="1" />'
    )


def _cash(day: str, amount: str = "50.00") -> str:
    return f'<CashReportCurrency currency="SGD" toDate="{day}" endingCash="{amount}" />'


def _xml(
    from_date: str,
    to_date: str,
    *,
    navs: list[str],
    positions: list[str] = (),  # type: ignore[assignment]
    cash: list[str] = (),  # type: ignore[assignment]
    extra: str = "",
) -> str:
    return f"""
    <FlexQueryResponse>
      <FlexStatements count="1">
        <FlexStatement accountId="{ACCOUNT}" fromDate="{from_date}" toDate="{to_date}" baseCurrency="SGD">
          <EquitySummaryInBase>{''.join(navs)}</EquitySummaryInBase>
          <CashReport>{''.join(cash)}</CashReport>
          <OpenPositions>{''.join(positions)}</OpenPositions>
          {extra}
        </FlexStatement>
      </FlexStatements>
    </FlexQueryResponse>
    """


def _daily(day: str, *, ledger_id: str, exec_id: str, symbol: str = "SYNA") -> str:
    extra = (
        f'<StmtFunds><StatementOfFundsLine date="{day}" currency="SGD" amount="1.00" activityCode="DIV" '
        f'activityDescription="Synthetic dividend" transactionID="{ledger_id}" /></StmtFunds>'
        f'<Trades><Trade tradeDate="{day}" conid="1001" symbol="SYNA" currency="SGD" buySell="BUY" '
        f'quantity="1" tradePrice="1" proceeds="-1" ibCommission="0" ibExecID="{exec_id}" /></Trades>'
    )
    return _xml(day, day, navs=[_nav(day, "150.00")], positions=[_position(day, symbol=symbol)], cash=[_cash(day)], extra=extra)


def _backfill() -> str:
    # 30-day style: NAV for every day, positions and cash only for the period end.
    return _xml(
        D1,
        D3,
        navs=[_nav(D1, "151.00"), _nav(D2, "152.00"), _nav(D3, "153.00", stock="103.00")],
        positions=[_position(D3, value="103.00")],
        cash=[_cash(D3)],
    )


def _import(db, xml: str) -> dict:
    return run_ibkr_flex_import_from_xml(db, current_user_id=1, legacy_account_id=LEGACY_ACCOUNT_ID, xml_text=xml)


def _count(db, sql: str, **params) -> int:
    return int(db.execute(text(sql), params).scalar() or 0)


def _per_date(db, table: str) -> dict[str, int]:
    rows = db.execute(text(f"SELECT report_date, COUNT(*) FROM {table} GROUP BY report_date")).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def test_multi_day_report_keeps_earlier_positions_and_replaces_nav(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        first = _import(db, _daily(D1, ledger_id="L1", exec_id="E1"))
        second = _import(db, _daily(D2, ledger_id="L2", exec_id="E2"))
        backfill = _import(db, _backfill())

        assert _per_date(db, "portfolio_position_snapshots") == {D1: 1, D2: 1, D3: 1}
        assert _per_date(db, "portfolio_cash_balance_snapshots") == {D1: 1, D2: 1, D3: 1}
        # The surviving rows keep the lineage of the run that wrote them.
        lineage = dict(
            (str(r[0]), int(r[1]))
            for r in db.execute(text("SELECT report_date, import_run_id FROM portfolio_position_snapshots")).fetchall()
        )
        assert lineage == {D1: first["import_run_id"], D2: second["import_run_id"], D3: backfill["import_run_id"]}

        navs = {
            str(r[0]): (int(r[1]), float(r[2]))
            for r in db.execute(text("SELECT report_date, import_run_id, total_nav_base FROM portfolio_nav_snapshots")).fetchall()
        }
        run = backfill["import_run_id"]
        assert navs == {D1: (run, 151.0), D2: (run, 152.0), D3: (run, 153.0)}

        # Reconciliation is rewritten only where the report has positions and cash; no
        # fabricated warning for D1/D2, whose daily reconciliations stay.
        recs = {
            str(r[0]): (int(r[1]), r[2])
            for r in db.execute(text("SELECT report_date, import_run_id, status FROM portfolio_reconciliations")).fetchall()
        }
        assert recs == {
            D1: (first["import_run_id"], "passed"),
            D2: (second["import_run_id"], "passed"),
            D3: (run, "passed"),
        }

        # Holdings for D1/D2 are still stored, so those dates stay complete.
        completeness = {
            str(r[0]): r[1]
            for r in db.execute(text("SELECT report_date, completeness_status FROM portfolio_data_completeness")).fetchall()
        }
        assert completeness == {D1: "complete", D2: "complete", D3: "complete"}

        # Cash ledger and trades are untouched by the backfill.
        assert _count(db, "SELECT COUNT(*) FROM portfolio_cash_ledger_entries") == 2
        assert _count(db, "SELECT COUNT(*) FROM portfolio_trades") == 2
    finally:
        db.close()


def test_nav_only_dates_without_holdings_are_marked_nav_only(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        _import(db, _backfill())

        completeness = {
            str(r[0]): (r[1], r[2])
            for r in db.execute(
                text("SELECT report_date, completeness_status, missing_reason FROM portfolio_data_completeness")
            ).fetchall()
        }
        assert completeness == {
            D1: ("nav_only", "holdings_not_in_report"),
            D2: ("nav_only", "holdings_not_in_report"),
            D3: ("complete", None),
        }
        assert _per_date(db, "portfolio_reconciliations") == {D3: 1}
        assert _per_date(db, "portfolio_nav_snapshots") == {D1: 1, D2: 1, D3: 1}
    finally:
        db.close()


def test_period_end_without_positions_clears_stale_positions(db_engine, tmp_path, monkeypatch):
    """Re-importing a date after selling everything must not keep the old holding."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        _import(db, _daily(D1, ledger_id="L1", exec_id="E1"))
        _import(db, _xml(D1, D1, navs=[_nav(D1, "50.00", stock="0")], cash=[_cash(D1)]))

        assert _per_date(db, "portfolio_position_snapshots") == {}
        assert _per_date(db, "portfolio_cash_balance_snapshots") == {D1: 1}
    finally:
        db.close()


def _simulate_pre_fix_deletion(db, dates: list[str]) -> None:
    """What the old import did to the earlier dates of a multi-day report."""
    for day in dates:
        for table in ("portfolio_position_snapshots", "portfolio_cash_balance_snapshots"):
            db.execute(text(f"DELETE FROM {table} WHERE report_date = :d"), {"d": day})
        db.execute(
            text(
                "UPDATE portfolio_data_completeness SET completeness_status = 'nav_only', "
                "missing_reason = 'holdings_not_in_report' WHERE report_date = :d"
            ),
            {"d": day},
        )
    db.commit()


def _snapshot_untouchables(db) -> dict[str, list]:
    return {
        table: [tuple(r) for r in db.execute(text(f"SELECT * FROM {table} ORDER BY id")).fetchall()]
        for table in (
            "portfolio_nav_snapshots",
            "portfolio_cash_ledger_entries",
            "portfolio_trades",
            "portfolio_source_authority_windows",
            "portfolio_reconciliations",
            "portfolio_report_metrics",
        )
    }


def test_rebuild_restores_deleted_snapshots_from_raw_xml(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        first = _import(db, _daily(D1, ledger_id="L1", exec_id="E1"))
        second = _import(db, _daily(D2, ledger_id="L2", exec_id="E2"))
        _import(db, _backfill())
        _simulate_pre_fix_deletion(db, [D1, D2])
        before = _snapshot_untouchables(db)

        dry = rebuild_ibkr_flex_snapshots(db)
        assert len(dry) == 1
        assert [(str(d.report_date), d.positions, d.cash_balances) for d in dry[0].dates] == [(D1, 1, 1), (D2, 1, 1)]
        assert dry[0].documents_read == 3
        assert _per_date(db, "portfolio_position_snapshots") == {D3: 1}  # dry run wrote nothing

        applied = rebuild_ibkr_flex_snapshots(db, apply=True)
        assert [(str(d.report_date), d.completeness_upgraded) for d in applied[0].dates] == [(D1, True), (D2, True)]
        assert _per_date(db, "portfolio_position_snapshots") == {D1: 1, D2: 1, D3: 1}
        assert _per_date(db, "portfolio_cash_balance_snapshots") == {D1: 1, D2: 1, D3: 1}

        restored = {
            str(r[0]): (int(r[1]), int(r[2]), r[3])
            for r in db.execute(
                text(
                    "SELECT p.report_date, p.import_run_id, p.raw_document_id, p.authority_status "
                    "FROM portfolio_position_snapshots p"
                )
            ).fetchall()
        }
        assert restored[D1] == (first["import_run_id"], first["raw_document_id"], "authoritative")
        assert restored[D2] == (second["import_run_id"], second["raw_document_id"], "authoritative")
        cash_lineage = {
            str(r[0]): int(r[1])
            for r in db.execute(text("SELECT report_date, import_run_id FROM portfolio_cash_balance_snapshots")).fetchall()
        }
        assert cash_lineage[D1] == first["import_run_id"]
        statuses = {
            str(r[0]): r[1]
            for r in db.execute(text("SELECT report_date, completeness_status FROM portfolio_data_completeness")).fetchall()
        }
        assert statuses == {D1: "complete", D2: "complete", D3: "complete"}

        # NAV, ledger, trades, authority windows, reconciliations and metrics are untouched.
        assert _snapshot_untouchables(db) == before

        # Idempotent: nothing left to restore.
        again = rebuild_ibkr_flex_snapshots(db, apply=True)
        assert again[0].dates == []
        assert _per_date(db, "portfolio_position_snapshots") == {D1: 1, D2: 1, D3: 1}
    finally:
        db.close()


def test_rebuild_uses_newest_report_for_a_date_and_reports_missing_files(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    _seed(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        _import(db, _daily(D1, ledger_id="L1", exec_id="E1", symbol="OLDR"))
        newer = _import(db, _daily(D1, ledger_id="L1", exec_id="E1", symbol="NEWR"))
        _import(db, _daily(D2, ledger_id="L2", exec_id="E2"))
        _simulate_pre_fix_deletion(db, [D1, D2])

        # The D2 XML is gone from disk: reported as missing, D2 is not restored.
        d2_path = db.execute(
            text("SELECT storage_path FROM raw_broker_documents WHERE report_date_to = :d"), {"d": D2}
        ).scalar()
        Path(d2_path).unlink()

        result = rebuild_ibkr_flex_snapshots(db, apply=True)[0]
        assert result.documents_missing == 1
        assert [str(d.report_date) for d in result.dates] == [D1]
        row = db.execute(
            text(
                "SELECT bi.symbol, p.import_run_id FROM portfolio_position_snapshots p "
                "JOIN broker_instruments bi ON bi.id = p.broker_instrument_id"
            )
        ).fetchall()
        assert [(r[0], int(r[1])) for r in row] == [("NEWR", newer["import_run_id"])]
    finally:
        db.close()


def test_rebuild_reads_from_raw_dir_and_rejects_tampered_files(db_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "app-data"))
    _seed(db_engine)
    db = sessionmaker(bind=db_engine)()
    try:
        _import(db, _daily(D1, ledger_id="L1", exec_id="E1"))
        _import(db, _daily(D2, ledger_id="L2", exec_id="E2"))
        _simulate_pre_fix_deletion(db, [D1, D2])

        copy_dir = tmp_path / "copied"
        copy_dir.mkdir()
        for day in (D1, D2):
            stored = Path(
                db.execute(
                    text("SELECT storage_path FROM raw_broker_documents WHERE report_date_to = :d"), {"d": day}
                ).scalar()
            )
            content = stored.read_text(encoding="utf-8")
            if day == D2:
                content = content.replace('endingCash="50.00"', 'endingCash="99.00"')  # hash no longer matches
            (copy_dir / stored.name).write_text(content, encoding="utf-8")
            stored.unlink()

        result = rebuild_ibkr_flex_snapshots(db, apply=True, raw_dir=str(copy_dir))[0]
        assert result.documents_rejected == 1
        assert [str(d.report_date) for d in result.dates] == [D1]
        assert date.fromisoformat(D1) == result.dates[0].report_date
    finally:
        db.close()
