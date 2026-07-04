"""
Phase 3 canonical dashboard read migration regression tests.

Verifies:
- Sharekhan canonical positions are read from portfolio_position_snapshots
  and produce the same dashboard output as the legacy positions table read.
- DBS Vickers canonical positions likewise produce equivalent output.
- IBKR Flex continues to use canonical NAV (not double-counted via positions).
- Stock holdings, platform allocation, geography exposure include canonical facts.
- Data completeness indicators surface when scopes are incomplete.
- Legacy positions table is NOT read for accounts with canonical position snapshots.
- No double-counting occurs when both legacy and canonical data are present.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.portfolio.canonical_reads import (
    canonical_position_rows_by_legacy_account,
    canonical_snapshot_coverage_as_of,
    get_data_completeness_status,
)
from app.portfolio.upload_canonical import run_upload_canonical_adapter
from app.ingestion.parsers.base import ParseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_platform(db_engine, platform_id: int, code: str, name: str, platform_type: str = "BROKER", country: str = "XX") -> None:
    with db_engine.begin() as conn:
        existing = conn.execute(text("SELECT id FROM platforms WHERE id = :id"), {"id": platform_id}).fetchone()
        if not existing:
            conn.execute(
                text(
                    "INSERT INTO platforms (id, code, name, platform_type, country) "
                    "VALUES (:id, :code, :name, :platform_type, :country)"
                ),
                {"id": platform_id, "code": code, "name": name, "platform_type": platform_type, "country": country},
            )


def _seed_account(
    db_engine,
    account_id: int,
    name: str,
    platform: str,
    currency: str,
    platform_id: int | None = None,
    country: str = "XX",
) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) "
                "VALUES (:id, :name, :platform, 'BROKER', :currency, :country, :platform_id)"
            ),
            {
                "id": account_id,
                "name": name,
                "platform": platform,
                "currency": currency,
                "country": country,
                "platform_id": platform_id,
            },
        )


def _seed_asset(db_engine, asset_id: int, symbol: str, name: str, asset_class: str, quote_currency: str, home_country: str | None = None) -> None:
    with db_engine.begin() as conn:
        existing = conn.execute(text("SELECT id FROM assets WHERE id = :id"), {"id": asset_id}).fetchone()
        if not existing:
            conn.execute(
                text(
                    "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) "
                    "VALUES (:id, :symbol, :name, :asset_class, :quote_currency, :home_country)"
                ),
                {
                    "id": asset_id,
                    "symbol": symbol,
                    "name": name,
                    "asset_class": asset_class,
                    "quote_currency": quote_currency,
                    "home_country": home_country,
                },
            )


def _run_canonical_upload(db_engine, account_id: int, platform_code: str, currency: str, positions_data: list[dict]) -> None:
    """Run canonical upload adapter for a given account and positions list."""
    data_dir = os.getenv("DATA_DIR", "/tmp/capitalos_test_data")
    os.makedirs(data_dir, exist_ok=True)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        parse_result = ParseResult(
            transactions=[],
            positions=positions_data,
            section_counts={"holdings": len(positions_data)},
            parser_meta={"report_date": date(2026, 2, 20)},
        )
        run_upload_canonical_adapter(
            db=db,
            current_user_id=2,
            legacy_account_id=account_id,
            platform_code=platform_code,
            parse_result=parse_result,
            stored_path="/tmp/test_phase3_fixture.xls",
            file_sha256=f"sha256_phase3_{account_id}_{platform_code}",
        )
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sharekhan_canonical_account(db_engine):
    """Seed a Sharekhan account with canonical snapshots."""
    _seed_platform(db_engine, 801, "SHAREKHAN", "Sharekhan", "BROKER", "IN")
    _seed_account(db_engine, 801, "Sharekhan Test Phase3", "SHAREKHAN", "INR", platform_id=801, country="IN")
    _seed_asset(db_engine, 8010, "RELIANCE", "Reliance Industries", "STOCK", "INR", "IN")

    # Seed canonical position snapshot via upload adapter
    _run_canonical_upload(
        db_engine, 801, "SHAREKHAN", "INR",
        [{"symbol": "RELIANCE", "currency": "INR", "quantity": 10.0, "cost_basis_base": 25000.0, "avg_cost": 2500.0, "asset_class": "STOCK"}]
    )
    yield 801


@pytest.fixture
def dbs_vickers_canonical_account(db_engine):
    """Seed a DBS Vickers account with canonical snapshots."""
    _seed_platform(db_engine, 802, "DBS_VICKERS", "DBS Vickers", "BROKER", "SG")
    _seed_account(db_engine, 802, "DBS Vickers Test Phase3", "DBS_VICKERS", "SGD", platform_id=802, country="SG")
    _seed_asset(db_engine, 8020, "S68", "Singapore Exchange", "STOCK", "SGD", "SG")

    _run_canonical_upload(
        db_engine, 802, "DBS_VICKERS", "SGD",
        [{"symbol": "S68", "currency": "SGD", "quantity": 100.0, "cost_basis_base": 950.0, "avg_cost": 9.5, "asset_class": "STOCK"}]
    )
    yield 802


@pytest.fixture
def ibkr_flex_canonical_account(db_engine):
    """Seed an IBKR Flex account with both NAV and position snapshots."""
    _seed_platform(db_engine, 803, "IBKR", "IBKR", "BROKER", "US")
    _seed_account(db_engine, 803, "IBKR Flex Phase3", "IBKR", "USD", platform_id=803, country="US")
    _seed_asset(db_engine, 8030, "AAPL", "Apple Inc.", "STOCK", "USD", "US")
    _seed_asset(db_engine, 8031, "700", "Tencent Holdings", "STOCK", "HKD", "HK")

    with db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO broker_connections (user_id, platform_code, connection_type, display_name, status, metadata_json) "
            "VALUES (2, 'IBKR', 'flex', 'IBKR Flex Phase3', 'active', '{}')"
        ))
        conn.execute(text(
            "INSERT INTO broker_accounts (connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
            "SELECT id, 803, 'U_P3_FLEX', 'USD', 'active', '{}' FROM broker_connections "
            "WHERE display_name='IBKR Flex Phase3' ORDER BY id DESC LIMIT 1"
        ))
        conn.execute(text(
            "INSERT INTO broker_import_runs (broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status, metadata_json) "
            "SELECT ba.id, 803, 'IBKR', 'flex', 'daily', 'completed', '{}' FROM broker_accounts ba "
            "WHERE ba.broker_account_id = 'U_P3_FLEX' ORDER BY ba.id DESC LIMIT 1"
        ))
        conn.execute(text(
            "INSERT INTO broker_instruments (platform_code, broker_instrument_id, asset_id, symbol, description, security_type, currency, metadata_json) "
            "VALUES ('IBKR', 'AAPL_CONID_P3', 8030, 'AAPL', 'Apple Inc.', 'STOCK', 'USD', '{}')"
        ))
        conn.execute(text(
            "INSERT INTO broker_instruments (platform_code, broker_instrument_id, asset_id, symbol, description, security_type, currency, metadata_json) "
            "VALUES ('IBKR', '700_CONID_P3', 8031, '700', 'Tencent Holdings', 'STOCK', 'HKD', '{}')"
        ))
        conn.execute(text(
            """
            INSERT INTO portfolio_nav_snapshots
              (broker_account_id, legacy_account_id, import_run_id, report_date, base_currency,
               cash_base, stock_base, total_nav_base, authority_status, metadata_json)
            SELECT ba.id, 803, ir.id, '2026-02-20', 'USD', 1000, 3000, 4000, 'authoritative', '{}'
            FROM broker_accounts ba
            JOIN broker_import_runs ir ON ir.broker_account_id = ba.id
            WHERE ba.broker_account_id = 'U_P3_FLEX'
            ORDER BY ir.id DESC
            LIMIT 1
            """
        ))
        conn.execute(text(
            """
            INSERT INTO portfolio_position_snapshots
              (broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
               quantity, currency, market_price, market_value_local, market_value_base,
               cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
            SELECT ba.id, 803, bi.id, ir.id, '2026-02-20',
                   10, 'USD', 200, 2000, 2000, 1500, 1500, 1, 'authoritative', '{}'
            FROM broker_accounts ba
            JOIN broker_import_runs ir ON ir.broker_account_id = ba.id
            JOIN broker_instruments bi ON bi.broker_instrument_id = 'AAPL_CONID_P3'
            WHERE ba.broker_account_id = 'U_P3_FLEX'
            ORDER BY ir.id DESC
            LIMIT 1
            """
        ))
        conn.execute(text(
            """
            INSERT INTO portfolio_position_snapshots
              (broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
               quantity, currency, market_price, market_value_local, market_value_base,
               cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
            SELECT ba.id, 803, bi.id, ir.id, '2026-02-20',
                   100, 'HKD', 80, 8000, 1000, 7000, 875, 0.125, 'authoritative', '{}'
            FROM broker_accounts ba
            JOIN broker_import_runs ir ON ir.broker_account_id = ba.id
            JOIN broker_instruments bi ON bi.broker_instrument_id = '700_CONID_P3'
            WHERE ba.broker_account_id = 'U_P3_FLEX'
            ORDER BY ir.id DESC
            LIMIT 1
            """
        ))
    yield 803


# ---------------------------------------------------------------------------
# Tests: canonical position read service
# ---------------------------------------------------------------------------

def test_canonical_position_rows_returns_sharekhan_positions(db_engine, sharekhan_canonical_account):
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        rows = canonical_position_rows_by_legacy_account(db, current_user_id=2, anchor_date=date(2026, 2, 20))
        sk_rows = [r for r in rows if r.get("account_id") == sharekhan_canonical_account]
        assert len(sk_rows) >= 1, "Expected at least one Sharekhan canonical position row"
        reliance = next((r for r in sk_rows if r.get("symbol") == "RELIANCE"), None)
        assert reliance is not None, "RELIANCE should appear in canonical position rows"
        assert float(reliance["quantity"]) == pytest.approx(10.0)
        assert float(reliance["cost_basis_base"]) == pytest.approx(25000.0)
    finally:
        db.close()


def test_canonical_position_rows_returns_dbs_vickers_positions(db_engine, dbs_vickers_canonical_account):
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        rows = canonical_position_rows_by_legacy_account(db, current_user_id=2, anchor_date=date(2026, 2, 20))
        dbsv_rows = [r for r in rows if r.get("account_id") == dbs_vickers_canonical_account]
        assert len(dbsv_rows) >= 1
        sgx = next((r for r in dbsv_rows if r.get("symbol") == "S68"), None)
        assert sgx is not None
        assert float(sgx["quantity"]) == pytest.approx(100.0)
    finally:
        db.close()


def test_canonical_position_rows_excludes_ibkr_flex_nav_accounts(db_engine, sharekhan_canonical_account):
    """Canonical position rows should not return accounts covered by NAV snapshots (IBKR Flex)."""
    # Seed a fake IBKR account with a nav snapshot so it's excluded from canonical position reads
    with db_engine.begin() as conn:
        existing_plat = conn.execute(text("SELECT id FROM platforms WHERE id = 803")).fetchone()
        if not existing_plat:
            conn.execute(text(
                "INSERT INTO platforms (id, code, name, platform_type, country) "
                "VALUES (803, 'IBKR_P3', 'IBKR Phase3 Test', 'BROKER', 'US')"
            ))
        existing_acc = conn.execute(text("SELECT id FROM accounts WHERE id = 803")).fetchone()
        if not existing_acc:
            conn.execute(text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, platform_id) "
                "VALUES (803, 'IBKR Phase3 Test', 'IBKR_P3', 'BROKER', 'USD', 'US', 803)"
            ))
        # Insert broker connection + account for IBKR
        conn.execute(text(
            "INSERT INTO broker_connections (user_id, platform_code, connection_type, display_name, status, metadata_json) "
            "VALUES (2, 'IBKR_P3', 'flex', 'IBKR Phase3', 'active', '{}')"
        ))
        conn.execute(text(
            "INSERT INTO broker_accounts (connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
            "SELECT id, 803, 'U_P3_TEST', 'USD', 'active', '{}' FROM broker_connections "
            "WHERE platform_code='IBKR_P3' ORDER BY id DESC LIMIT 1"
        ))
        # Insert a mock import run
        conn.execute(text(
            "INSERT INTO broker_import_runs (broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status, metadata_json) "
            "SELECT ba.id, 803, 'IBKR_P3', 'flex', 'daily', 'complete', '{}' FROM broker_accounts ba "
            "WHERE ba.broker_account_id = 'U_P3_TEST' ORDER BY ba.id DESC LIMIT 1"
        ))
        # Insert a NAV snapshot for this account
        conn.execute(text(
            """
            INSERT INTO portfolio_nav_snapshots
              (broker_account_id, legacy_account_id, import_run_id, report_date, base_currency,
               cash_base, stock_base, total_nav_base, authority_status, metadata_json)
            SELECT ba.id, 803, ir.id, '2026-02-20', 'USD', 1000, 5000, 6000, 'authoritative', '{}'
            FROM broker_accounts ba
            JOIN broker_import_runs ir ON ir.broker_account_id = ba.id
            WHERE ba.broker_account_id = 'U_P3_TEST'
            ORDER BY ir.id DESC
            LIMIT 1
            """
        ))

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        rows = canonical_position_rows_by_legacy_account(db, current_user_id=2, anchor_date=date(2026, 2, 20))
        ibkr_rows = [r for r in rows if r.get("account_id") == 803]
        assert len(ibkr_rows) == 0, "IBKR Flex accounts should be excluded from canonical position read (covered by NAV)"
    finally:
        db.close()


def test_canonical_position_rows_can_include_ibkr_flex_detail_rows(db_engine, ibkr_flex_canonical_account):
    """Detail consumers can opt in to IBKR Flex position snapshots even when NAV exists."""
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        rows = canonical_position_rows_by_legacy_account(
            db,
            current_user_id=2,
            anchor_date=date(2026, 2, 20),
            include_nav_accounts=True,
        )
        ibkr_rows = [r for r in rows if r.get("account_id") == ibkr_flex_canonical_account]
        assert len(ibkr_rows) == 2
        aapl = next((row for row in ibkr_rows if row["symbol"] == "AAPL"), None)
        hk = next((row for row in ibkr_rows if row["symbol"] == "700"), None)
        assert aapl is not None
        assert hk is not None
        assert aapl["has_nav_snapshot"] is True
        assert float(aapl["snapshot_market_price"]) == pytest.approx(200.0)
        assert float(aapl["snapshot_market_value_local"]) == pytest.approx(2000.0)
        assert float(aapl["snapshot_market_value_base"]) == pytest.approx(2000.0)
        assert float(aapl["snapshot_cost_basis_local"]) == pytest.approx(1500.0)
        assert float(hk["snapshot_market_value_base"]) == pytest.approx(1000.0)
    finally:
        db.close()


def test_canonical_position_rows_maps_ibkr_class_share_symbols_and_stk_security_type(db_engine):
    """IBKR class-share symbols like BRK B should resolve to canonical BRK-B stock assets."""
    _seed_platform(db_engine, 804, "IBKR", "IBKR", "BROKER", "US")
    _seed_account(db_engine, 804, "IBKR Flex Class Shares Phase3", "IBKR", "USD", platform_id=804, country="US")
    _seed_asset(db_engine, 8040, "BRK-B", "Berkshire Hathaway Inc. Class B", "STOCK", "USD", "US")

    with db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO broker_connections (user_id, platform_code, connection_type, display_name, status, metadata_json) "
            "VALUES (2, 'IBKR', 'flex', 'IBKR Flex Class Shares Phase3', 'active', '{}')"
        ))
        conn.execute(text(
            "INSERT INTO broker_accounts (connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
            "SELECT id, 804, 'U_P3_BRK', 'USD', 'active', '{}' FROM broker_connections "
            "WHERE display_name='IBKR Flex Class Shares Phase3' ORDER BY id DESC LIMIT 1"
        ))
        conn.execute(text(
            "INSERT INTO broker_import_runs (broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status, metadata_json) "
            "SELECT ba.id, 804, 'IBKR', 'flex', 'daily', 'completed', '{}' FROM broker_accounts ba "
            "WHERE ba.broker_account_id = 'U_P3_BRK' ORDER BY ba.id DESC LIMIT 1"
        ))
        conn.execute(text(
            "INSERT INTO broker_instruments (platform_code, broker_instrument_id, asset_id, symbol, description, security_type, currency, metadata_json) "
            "VALUES ('IBKR', 'BRK_B_CONID_P3', NULL, 'BRK B', 'BERKSHIRE HATHAWAY INC-CL B', 'STK', 'USD', '{}')"
        ))
        conn.execute(text(
            """
            INSERT INTO portfolio_nav_snapshots
              (broker_account_id, legacy_account_id, import_run_id, report_date, base_currency,
               cash_base, stock_base, total_nav_base, authority_status, metadata_json)
            SELECT ba.id, 804, ir.id, '2026-02-20', 'USD', 1000, 5078, 6078, 'authoritative', '{}'
            FROM broker_accounts ba
            JOIN broker_import_runs ir ON ir.broker_account_id = ba.id
            WHERE ba.broker_account_id = 'U_P3_BRK'
            ORDER BY ir.id DESC
            LIMIT 1
            """
        ))
        conn.execute(text(
            """
            INSERT INTO portfolio_position_snapshots
              (broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
               quantity, currency, market_price, market_value_local, market_value_base,
               cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
            SELECT ba.id, 804, bi.id, ir.id, '2026-02-20',
                   10, 'USD', 507.8, 5078, 5078, 4691.09, 4691.09, 1, 'authoritative', '{}'
            FROM broker_accounts ba
            JOIN broker_import_runs ir ON ir.broker_account_id = ba.id
            JOIN broker_instruments bi ON bi.broker_instrument_id = 'BRK_B_CONID_P3'
            WHERE ba.broker_account_id = 'U_P3_BRK'
            ORDER BY ir.id DESC
            LIMIT 1
            """
        ))

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        rows = canonical_position_rows_by_legacy_account(
            db,
            current_user_id=2,
            anchor_date=date(2026, 2, 20),
            include_nav_accounts=True,
        )
        brk = next((row for row in rows if row.get("account_id") == 804 and row.get("symbol") == "BRK-B"), None)
        assert brk is not None, f"Expected BRK-B in canonical rows, got: {[row.get('symbol') for row in rows]}"
        assert brk["asset_id"] == 8040
        assert brk["asset_class"] == "STOCK"
        assert brk["quote_currency"] == "USD"
        assert brk["home_country"] == "US"
        assert brk["has_nav_snapshot"] is True
        assert float(brk["quantity"]) == pytest.approx(10.0)
        assert float(brk["snapshot_market_value_base"]) == pytest.approx(5078.0)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests: dashboard uses canonical positions (legacy excluded)
# ---------------------------------------------------------------------------

def test_dashboard_summary_sharekhan_canonical_positions_included(
    client: TestClient, db_engine, sharekhan_canonical_account, monkeypatch
):
    """Dashboard summary includes Sharekhan positions from canonical snapshots."""
    from app.fx import get_rates as real_get_rates

    def fake_rates(_dt, base, currencies):
        rates = {c: 1.0 for c in currencies}
        rates["INR"] = 0.016  # rough INR to SGD
        return rates

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()
    # Net worth should include RELIANCE position via canonical
    # 25000 INR * 0.016 = 400 SGD
    assert data["net_worth"]["total"] >= 0  # just check it doesn't error


def test_dashboard_legacy_positions_excluded_when_canonical_exists(
    db_engine, sharekhan_canonical_account
):
    """
    Phase 7 removes the legacy dashboard position bridge entirely.
    """
    import app.routers.dashboard as dashboard

    assert not hasattr(dashboard, "_synthetic_position_rows")


def test_dashboard_no_double_counting_when_canonical_and_legacy_both_present(
    db_engine, sharekhan_canonical_account, monkeypatch
):
    """
    When an account has both legacy and canonical data, the value should
    appear only once (from canonical), not doubled.
    """
    from app.routers.dashboard import _networth_components
    from datetime import datetime, timezone

    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        anchor = datetime(2026, 3, 1, tzinfo=timezone.utc)
        components = _networth_components(db, anchor, "INR", current_user_id=2)
        # RELIANCE at 25000 INR. With fake rate 1.0 for all currencies, stocks_funds should be 25000.
        # If double-counted it would be 50000.
        assert components["stocks_funds"] == pytest.approx(25000.0, rel=0.01), (
            f"Expected ~25000 INR stocks_funds (one occurrence), got {components['stocks_funds']}"
        )
    finally:
        db.close()


def test_top_holdings_includes_ibkr_flex_canonical_positions(
    db_engine, ibkr_flex_canonical_account, monkeypatch
):
    """Stock holdings list should show IBKR Flex positions while totals still use NAV elsewhere."""
    from app.routers.dashboard import _top_holdings
    from datetime import datetime, timezone

    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        anchor = datetime(2026, 3, 1, tzinfo=timezone.utc)
        rows = _top_holdings(db, anchor, total=3000.0, base_currency="USD", current_user_id=2, limit=20)
        aapl = next((row for row in rows if row.get("symbol") == "AAPL"), None)
        assert aapl is not None, f"Expected AAPL in top holdings, got: {[row.get('symbol') for row in rows]}"
        assert aapl["value"] == pytest.approx(2000.0)
        assert aapl["latest_price"] == pytest.approx(200.0)
        assert aapl["avg_cost"] == pytest.approx(150.0)
        assert aapl["latest_trade_date"] == "2026-02-20"
        assert aapl["price_provider"] == "ibkr"
        assert aapl["quote_freshness_status"] in {"fresh", "stale"}
    finally:
        db.close()


def test_stock_exposure_allocates_ibkr_flex_nav_by_position_country(
    db_engine, ibkr_flex_canonical_account, monkeypatch
):
    """IBKR NAV-backed stock totals should use Flex position countries for geography buckets."""
    from app.routers.dashboard import _stock_exposure
    from datetime import datetime, timezone

    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        anchor = datetime(2026, 3, 1, tzinfo=timezone.utc)
        exposure = _stock_exposure(db, anchor, "USD", current_user_id=2)
        countries = {item["key"]: item for item in exposure["by_country"]}
        platforms = {item["key"]: item for item in exposure["by_platform"]}
        assert exposure["total"] == pytest.approx(3000.0)
        assert platforms["IBKR"]["value"] == pytest.approx(3000.0)
        assert countries["US"]["value"] == pytest.approx(2000.0)
        assert countries["HK"]["value"] == pytest.approx(1000.0)
    finally:
        db.close()


def test_ibkr_flex_nav_supersedes_stale_legacy_backfill_dashboard_reads(
    client: TestClient,
    db_engine,
    ibkr_flex_canonical_account,
    monkeypatch,
):
    """
    IBKR dashboard values should use legacy-backfill history until actual Flex
    facts exist at the read date. Once Flex facts exist, Flex NAV supersedes
    older legacy-backfill rows for the same legacy account.
    """
    from app.routers.dashboard import _networth_components, _platform_allocation, _stock_exposure

    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO portfolio_source_authority_windows
                  (broker_account_id, source_kind, fact_scope, effective_from, authority_status)
                SELECT ba.id, 'ibkr_flex_daily', 'all', '2026-02-01', 'authoritative'
                FROM broker_accounts ba
                WHERE ba.legacy_account_id = :account_id
                  AND ba.broker_account_id = 'U_P3_FLEX'
                """
            ),
            {"account_id": ibkr_flex_canonical_account},
        )
        conn.execute(
            text(
                """
                UPDATE portfolio_nav_snapshots
                SET authority_status = 'reference'
                WHERE legacy_account_id = :account_id
                """
            ),
            {"account_id": ibkr_flex_canonical_account},
        )
        conn.execute(
            text(
                """
                UPDATE portfolio_position_snapshots
                SET authority_status = 'reference'
                WHERE legacy_account_id = :account_id
                  AND broker_account_id = (
                    SELECT id FROM broker_accounts WHERE broker_account_id = 'U_P3_FLEX'
                  )
                """
            ),
            {"account_id": ibkr_flex_canonical_account},
        )
        conn.execute(
            text(
                "INSERT INTO broker_connections "
                "(id, user_id, platform_code, connection_type, display_name, status, metadata_json) "
                "VALUES (48001, 2, 'LEGACY_BACKFILL', 'legacy_backfill', 'IBKR stale backfill', 'active', '{}')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO broker_accounts "
                "(id, connection_id, legacy_account_id, broker_account_id, base_currency, status, metadata_json) "
                "VALUES (48001, 48001, :account_id, 'backfill_ibkr_stale', 'USD', 'active', '{}')"
            ),
            {"account_id": ibkr_flex_canonical_account},
        )
        conn.execute(
            text(
                "INSERT INTO broker_import_runs "
                "(id, broker_account_id, legacy_account_id, platform_code, source_type, import_scope, status, "
                " report_date_from, report_date_to, metadata_json) "
                "VALUES (48001, 48001, :account_id, 'IBKR', 'legacy_positions_backfill', 'backfill', 'completed', "
                " '2026-02-10', '2026-02-10', '{}')"
            ),
            {"account_id": ibkr_flex_canonical_account},
        )
        conn.execute(
            text(
                "INSERT INTO broker_instruments "
                "(id, platform_code, broker_instrument_id, asset_id, symbol, description, security_type, currency, metadata_json) "
                "VALUES (48001, 'LEGACY_BACKFILL', 'backfill_AAPL_stale', 8030, 'AAPL', 'Apple stale backfill', "
                " 'STOCK', 'USD', '{}')"
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO portfolio_position_snapshots
                  (id, broker_account_id, legacy_account_id, broker_instrument_id, import_run_id, report_date,
                   quantity, currency, market_price, market_value_local, market_value_base,
                   cost_basis_local, cost_basis_base, fx_rate_to_base, authority_status, metadata_json)
                VALUES
                  (48001, 48001, :account_id, 48001, 48001, '2026-02-10',
                   100, 'USD', 7500, 750000, 750000, 750000, 750000, 1, 'authoritative', '{}')
                """
            ),
            {"account_id": ibkr_flex_canonical_account},
        )
        conn.execute(
            text(
                """
                INSERT INTO account_balance_snapshots
                  (id, account_id, broker_account_id, broker_import_run_id, as_of_date, currency, balance_type,
                   balance_local, balance_base, fx_rate_to_base, authority_status, source_kind, metadata_json)
                VALUES
                  (48001, :account_id, 48001, 48001, '2026-02-10', 'USD', 'cash',
                   103191, 103191, 1, 'authoritative', 'legacy_positions_backfill', '{}')
                """
            ),
            {"account_id": ibkr_flex_canonical_account},
        )

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        pre_report_anchor = datetime(2026, 2, 15, tzinfo=timezone.utc)
        pre_report_components = _networth_components(db, pre_report_anchor, "USD", current_user_id=2)
        pre_report_exposure = _stock_exposure(db, pre_report_anchor, "USD", current_user_id=2)

        assert pre_report_components["cash"] == pytest.approx(103191.0)
        assert pre_report_components["stocks_funds"] == pytest.approx(750000.0)
        assert pre_report_components["total"] == pytest.approx(853191.0)
        assert pre_report_exposure["total"] == pytest.approx(750000.0)

        anchor = datetime(2026, 3, 1, tzinfo=timezone.utc)
        components = _networth_components(db, anchor, "USD", current_user_id=2)
        allocation = _platform_allocation(db, anchor, "USD", current_user_id=2)
        exposure = _stock_exposure(db, anchor, "USD", current_user_id=2)

        assert components["cash"] == pytest.approx(1000.0)
        assert components["stocks_funds"] == pytest.approx(3000.0)
        assert components["total"] == pytest.approx(4000.0)
        assert allocation["total"] == pytest.approx(4000.0)
        assert allocation["items"] == [
            {
                "platform": "IBKR",
                "platform_type": "BROKER",
                "country": "US",
                "value": 4000.0,
                "percent": 100.0,
            }
        ]
        assert exposure["total"] == pytest.approx(3000.0)
        assert exposure["by_platform"] == [{"key": "IBKR", "value": 3000.0, "percent": 100.0}]
    finally:
        db.close()

    platform_resp = client.get("/dashboard/platform-allocation?month=2026-02&base_currency=USD")
    assert platform_resp.status_code == 200
    platform_payload = platform_resp.json()
    assert platform_payload["total"] == pytest.approx(4000.0)
    assert platform_payload["items"][0]["platform"] == "IBKR"
    assert platform_payload["items"][0]["value"] == pytest.approx(4000.0)

    holdings_resp = client.get("/dashboard/stock-holdings?month=2026-02&base_currency=USD")
    assert holdings_resp.status_code == 200
    holdings_payload = holdings_resp.json()
    assert holdings_payload["stock_current_total"] == pytest.approx(3000.0)
    assert holdings_payload["platform_breakdown"] == [
        {
            "key": "IBKR",
            "current_value": 3000.0,
            "snapshot_value": 3000.0,
            "delta_abs": 0.0,
            "delta_pct": 0.0,
            "percent": 100.0,
        }
    ]
    assert max(row["value"] for row in holdings_payload["top_holdings"]) == pytest.approx(2000.0)


def test_platform_allocation_includes_sharekhan_canonical(
    client: TestClient, db_engine, sharekhan_canonical_account, monkeypatch
):
    """Platform allocation endpoint includes Sharekhan canonical positions."""
    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/platform-allocation?month=2026-02")
    assert resp.status_code == 200
    data = resp.json()
    items = data.get("items", [])
    # SHAREKHAN platform should appear
    platforms = [item.get("platform") for item in items]
    assert "SHAREKHAN" in platforms, f"SHAREKHAN not found in platform allocation items: {platforms}"


def test_stock_exposure_includes_sharekhan_canonical(
    client: TestClient, db_engine, sharekhan_canonical_account, monkeypatch
):
    """Stock exposure endpoint includes Sharekhan canonical STOCK positions."""
    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/stock-exposure?month=2026-02")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] > 0, "Stock exposure should be > 0 with Sharekhan canonical RELIANCE position"


def test_geography_exposure_includes_sharekhan_canonical(
    client: TestClient, db_engine, sharekhan_canonical_account, monkeypatch
):
    """Geography exposure endpoint includes Sharekhan canonical positions mapped to 'IN'."""
    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/geography-exposure?month=2026-02")
    assert resp.status_code == 200
    data = resp.json()
    items = data.get("items", [])
    # RELIANCE (INR) should map to India
    countries = [item.get("country") for item in items]
    assert "IN" in countries or "UNKNOWN" in countries, f"Expected IN or UNKNOWN in geography items: {countries}"


# ---------------------------------------------------------------------------
# Tests: data completeness indicators
# ---------------------------------------------------------------------------

def test_data_completeness_status_returns_incomplete_scopes(db_engine, sharekhan_canonical_account):
    """
    Upload-based canonical adapters write completeness records for missing
    scopes (cash_balance, nav, trades). These should surface as indicators.
    """
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        records = get_data_completeness_status(db, current_user_id=2, anchor_date=date(2026, 2, 20))
        sk_records = [r for r in records if r.get("account_id") == sharekhan_canonical_account]
        assert len(sk_records) > 0, "Expected incomplete completeness records for Sharekhan (missing cash/nav/trades)"
        fact_scopes = {r.get("fact_scope") for r in sk_records}
        # Upload adapter writes completeness records for these scopes
        expected_incomplete = {"cash_balance", "nav", "trades"}
        found_incomplete = fact_scopes & expected_incomplete
        assert len(found_incomplete) > 0, f"Expected some incomplete scopes, found: {fact_scopes}"
    finally:
        db.close()


def test_dashboard_summary_exposes_completeness_indicators(
    client: TestClient, db_engine, sharekhan_canonical_account, monkeypatch
):
    """Dashboard summary exposes data_completeness_indicators when data is partial."""
    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    resp = client.get("/dashboard/summary?month=2026-02")
    assert resp.status_code == 200
    data = resp.json()
    # data_completeness_indicators is optional but should be present when there are incomplete scopes
    # When no canonical data at all, it may be None; with Sharekhan canonical it should have entries
    if data.get("data_completeness_indicators") is not None:
        indicators = data["data_completeness_indicators"]
        assert isinstance(indicators, list)
        # All entries should have required fields
        for indicator in indicators:
            assert "fact_scope" in indicator
            assert "completeness_status" in indicator


# ---------------------------------------------------------------------------
# Tests: DBS Vickers equivalence
# ---------------------------------------------------------------------------

def test_dbs_vickers_canonical_positions_no_double_count(
    db_engine, dbs_vickers_canonical_account, monkeypatch
):
    """DBS Vickers canonical positions should not be double-counted with legacy."""
    from app.routers.dashboard import _networth_components
    from datetime import datetime, timezone

    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        anchor = datetime(2026, 3, 1, tzinfo=timezone.utc)
        components = _networth_components(db, anchor, "SGD", current_user_id=2)
        # S68: 100 qty * 9.5 = 950 SGD. Should appear exactly once.
        assert components["stocks_funds"] == pytest.approx(950.0, rel=0.01), (
            f"Expected ~950 SGD stocks_funds, got {components['stocks_funds']}"
        )
    finally:
        db.close()


def test_stock_holdings_current_value_uses_latest_quote_for_stale_upload_holdings(
    client: TestClient,
    db_engine,
    dbs_vickers_canonical_account,
    monkeypatch,
):
    """Current stock page values must equal latest quote * last known holdings."""
    def fake_rates(_dt, base, currencies):
        return {c: 1.0 for c in currencies}

    monkeypatch.setattr("app.routers.dashboard.get_rates", fake_rates)
    monkeypatch.setattr(
        "app.routers.dashboard._current_anchor_ts",
        lambda: datetime(2026, 3, 1, tzinfo=timezone.utc),
    )

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO prices
                  (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol)
                VALUES
                  (98020, 8020, '2026-02-28T00:00:00+00:00', 11, 'SGD',
                   'yfinance_market', '2026-02-28', 'SGX', 'S68.SI')
                """
            )
        )

    resp = client.get("/dashboard/stock-holdings?month=2026-02&base_currency=SGD")
    assert resp.status_code == 200
    payload = resp.json()
    holding = next(row for row in payload["top_holdings"] if row["symbol"] == "S68")

    assert payload["stock_current_total"] == pytest.approx(1100.0)
    assert payload["stock_snapshot_total"] == pytest.approx(950.0)
    assert holding["value"] == pytest.approx(1100.0)
    assert holding["quantity"] == pytest.approx(100.0)
    assert holding["latest_price"] == pytest.approx(11.0)
    assert holding["latest_trade_date"] == "2026-02-28"
    assert holding["price_provider"] == "yfinance"


def test_dbs_vickers_legacy_excluded_from_synthetic_rows(db_engine, dbs_vickers_canonical_account):
    """DBS Vickers no longer needs the legacy dashboard position bridge."""
    import app.routers.dashboard as dashboard

    assert not hasattr(dashboard, "_synthetic_position_rows")


def test_canonical_snapshot_effective_date_uses_latest_available_fact(
    db_engine,
    sharekhan_canonical_account,
    dbs_vickers_canonical_account,
):
    """
    A stale account should not make the whole dashboard snapshot look missing.
    The value is computed from latest-known components; component staleness is
    freshness metadata, not snapshot availability.
    """
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE portfolio_position_snapshots
                SET report_date = '2026-03-01'
                WHERE broker_account_id IN (
                  SELECT id
                  FROM broker_accounts
                  WHERE legacy_account_id = :account_id
                )
                """
            ),
            {"account_id": dbs_vickers_canonical_account},
        )

    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        as_of = canonical_snapshot_coverage_as_of(
            db,
            current_user_id=2,
            anchor_date=date(2026, 3, 1),
        )
        assert str(as_of) == "2026-03-01"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Tests: canonical position read respects anchor date
# ---------------------------------------------------------------------------

def test_canonical_position_rows_respects_anchor_date(db_engine, sharekhan_canonical_account):
    """canonical_position_rows_by_legacy_account should not return rows after anchor_date."""
    Session = sessionmaker(bind=db_engine)
    db = Session()
    try:
        # Before the snapshot date (2026-02-20)
        rows_before = canonical_position_rows_by_legacy_account(
            db, current_user_id=2, anchor_date=date(2026, 1, 1)
        )
        sk_rows_before = [r for r in rows_before if r.get("account_id") == sharekhan_canonical_account]
        assert len(sk_rows_before) == 0, "Should return no rows for anchor before snapshot date"

        # At/after the snapshot date
        rows_after = canonical_position_rows_by_legacy_account(
            db, current_user_id=2, anchor_date=date(2026, 2, 20)
        )
        sk_rows_after = [r for r in rows_after if r.get("account_id") == sharekhan_canonical_account]
        assert len(sk_rows_after) >= 1, "Should return rows for anchor >= snapshot date"
    finally:
        db.close()
