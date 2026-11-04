from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.valuation.facts import _networth_components
from app.valuation.history import (
    _backfill_wealth_rollups,
    _platform_freshness_entries,
    _upsert_wealth_rollup,
    _wealth_rollup_row,
)
from tests.canonical_test_helpers import seed_canonical_position_snapshot_for_test


def _seed_platform_account(db_engine, *, account_id: int, platform: str, asset_id: int, symbol: str) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country) VALUES "
                "(:id, :name, :platform, 1, 'BROKER', 'SGD', 'SG')"
            ),
            {"id": account_id, "name": f"{platform} account", "platform": platform},
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(:id, :symbol, :symbol, 'STOCK', 'SGD', 'SG')"
            ),
            {"id": asset_id, "symbol": symbol},
        )


def test_wealth_rollup_row_matches_networth_components(db_engine, monkeypatch):
    anchor = datetime(2026, 7, 1, tzinfo=timezone.utc)
    _seed_platform_account(db_engine, account_id=940, platform="IBKR", asset_id=940, symbol="AAPL")
    seed_canonical_position_snapshot_for_test(
        db_engine,
        account_id=940,
        asset_id=940,
        as_of=date(2026, 6, 28),
        quantity=10,
        market_value_base=5000.0,
        market_price=500.0,
        platform_code="IBKR",
    )
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})

    db = Session(bind=db_engine)
    try:
        expected = _networth_components(db, anchor, "SGD", 1)
        row = _wealth_rollup_row(db, anchor, "SGD", 1)
    finally:
        db.close()

    assert row["components"] == expected
    assert row["anchor_date"] == anchor.date()


def test_platform_freshness_distinguishes_daily_vs_manual_cadence(db_engine, monkeypatch):
    """The bug this whole feature exists to fix: MAX()-across-accounts freshness
    hides a 10-day-stale automated feed behind a 10-day-old manual upload that is
    still perfectly normal for its own cadence. Same days_old, different verdicts."""
    anchor = datetime(2026, 7, 1, tzinfo=timezone.utc)
    stale_date = date(2026, 6, 21)  # 10 days before anchor for both platforms

    _seed_platform_account(db_engine, account_id=950, platform="IBKR", asset_id=950, symbol="MSFT")
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=950, asset_id=950, as_of=stale_date,
        quantity=5, market_value_base=2000.0, market_price=400.0, platform_code="IBKR",
    )
    _seed_platform_account(db_engine, account_id=951, platform="SHAREKHAN", asset_id=951, symbol="RELIANCE")
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=951, asset_id=951, as_of=stale_date,
        quantity=20, market_value_base=3000.0, market_price=150.0, platform_code="SHAREKHAN",
    )
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})

    db = Session(bind=db_engine)
    try:
        _, rows = _networth_components(db, anchor, "SGD", 1, return_rows=True)
    finally:
        db.close()

    entries = _platform_freshness_entries(rows, anchor.date(), crypto_as_of=None)
    by_platform = {e["platform"]: e for e in entries}

    assert by_platform["IBKR"]["days_old"] == 10
    assert by_platform["IBKR"]["status"] == "carried"
    assert by_platform["SHAREKHAN"]["days_old"] == 10
    assert by_platform["SHAREKHAN"]["status"] == "fresh"


def test_upsert_wealth_rollup_is_idempotent(db_engine):
    db = Session(bind=db_engine)
    try:
        row_v1 = {
            "anchor_date": date(2026, 5, 1),
            "components": {"total": 100.0, "cash": 100.0, "stocks_funds": 0.0, "crypto": 0.0, "liabilities": 0.0},
            "source_freshness": [],
            "freshness_status": "fresh",
        }
        _upsert_wealth_rollup(db, 1, "2026-04", "SGD", row_v1)
        db.commit()

        row_v2 = dict(row_v1)
        row_v2["components"] = {"total": 250.0, "cash": 250.0, "stocks_funds": 0.0, "crypto": 0.0, "liabilities": 0.0}
        _upsert_wealth_rollup(db, 1, "2026-04", "SGD", row_v2)
        db.commit()

        rows = db.execute(
            text("SELECT total FROM wealth_monthly_rollups WHERE user_id = 1 AND month = '2026-04' AND base_currency = 'SGD'")
        ).fetchall()
    finally:
        db.close()

    assert len(rows) == 1
    assert float(rows[0][0]) == 250.0


def test_backfill_writes_completed_months_only(db_engine, monkeypatch):
    """The open month isn't stored (#138): "now" covers it."""
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    monkeypatch.setattr("app.valuation.clock._current_anchor_ts", lambda: datetime(2026, 7, 13, tzinfo=timezone.utc))
    db = Session(bind=db_engine)
    try:
        written = _backfill_wealth_rollups(db, 1, "SGD", months=6)
        rows = db.execute(
            text(
                "SELECT month, anchor_date FROM wealth_monthly_rollups "
                "WHERE user_id = 1 AND base_currency = 'SGD' ORDER BY month"
            )
        ).fetchall()
    finally:
        db.close()

    assert written == 5
    assert [r[0] for r in rows] == ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]
    assert str(rows[-1][1])[:10] == "2026-07-01"  # June at its own anchor


def test_net_worth_timeline_endpoint_returns_points_with_upload_marker(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setenv("SNAPSHOT_DAY", "1")
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    monkeypatch.setattr("app.valuation.clock._current_anchor_ts", lambda: datetime(2026, 7, 13, tzinfo=timezone.utc))
    _seed_platform_account(db_engine, account_id=960, platform="IBKR", asset_id=960, symbol="GOOGL")
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=960, asset_id=960, as_of=date(2026, 6, 5),
        quantity=2, market_value_base=4000.0, market_price=2000.0, platform_code="IBKR",
    )
    with db_engine.begin() as conn:
        for created_at in (datetime(2026, 6, 20, tzinfo=timezone.utc), datetime(2026, 7, 2, tzinfo=timezone.utc)):
            conn.execute(
                text(
                    "INSERT INTO import_jobs (account_id, platform, original_filename, stored_path, file_sha256, status, created_at, updated_at) "
                    "VALUES (960, 'IBKR', 'stmt.csv', '/tmp/x', 'sha', 'IMPORTED', :now, :now)"
                ),
                {"now": created_at},
            )

    backfill_resp = client.post("/dashboard/net-worth-timeline/backfill?months=3&base_currency=SGD")
    assert backfill_resp.status_code == 200
    assert backfill_resp.json()["months_written"] == 2  # May, June; July is open

    resp = client.get("/dashboard/net-worth-timeline?months=3&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["base_currency"] == "SGD"
    assert [p["month"] for p in data["points"]] == ["2026-05", "2026-06"]
    assert "now" in data and "total" in data["now"]
    assert data["now"]["uploads"] == ["IBKR"]  # July's upload sits on "now"

    june = next(p for p in data["points"] if p["month"] == "2026-06")
    assert june["uploads"] == ["IBKR"]
    assert june["total"] > 0
    assert any(s["platform"] == "IBKR" for s in june["source_freshness"])


def test_net_worth_timeline_read_endpoint_does_not_recompute_past_months(client: TestClient, db_engine, monkeypatch):
    """The read endpoint must stay a pure scan for rows that aren't stale —
    that's the whole point of pre-aggregating. Prove it by poisoning stored
    rows directly in the DB and confirming a plain GET doesn't touch them."""
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    assert client.post("/dashboard/net-worth-timeline/backfill?months=6&base_currency=SGD").status_code == 200

    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE wealth_monthly_rollups SET total = 999999999 WHERE user_id = 1 AND base_currency = 'SGD'")
        )

    resp = client.get("/dashboard/net-worth-timeline?months=6&base_currency=SGD")
    assert resp.status_code == 200
    points = resp.json()["points"]
    assert points, "expected stored months in range"
    # Nothing is dirty and every row sits at its own anchor: a pure read.
    assert all(p["total"] == 999999999 for p in points)


def test_net_worth_timeline_movers_endpoint_diffs_two_historical_anchors(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setattr("app.valuation.fx.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    _seed_platform_account(db_engine, account_id=970, platform="IBKR", asset_id=970, symbol="NVDA")
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=970, asset_id=970, as_of=date(2025, 5, 15),
        quantity=10, market_value_base=1000.0, market_price=100.0, platform_code="IBKR",
    )
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=970, asset_id=970, as_of=date(2025, 6, 15),
        quantity=10, market_value_base=1800.0, market_price=180.0, platform_code="IBKR",
    )

    resp = client.get("/dashboard/net-worth-timeline/2025-06/movers?base_currency=SGD&limit=5")
    assert resp.status_code == 200
    data = resp.json()

    assert data["compare_month"] == "2025-05"
    assert len(data["gainers"]) == 1
    mover = data["gainers"][0]
    assert mover["symbol"] == "NVDA"
    assert mover["current_value"] == 1800.0
    assert mover["previous_value"] == 1000.0
    assert mover["delta_abs"] == 800.0
    assert data["detractors"] == []


def test_net_worth_timeline_movers_endpoint_rejects_bad_month(client: TestClient):
    resp = client.get("/dashboard/net-worth-timeline/2026-13/movers")
    assert resp.status_code == 400
