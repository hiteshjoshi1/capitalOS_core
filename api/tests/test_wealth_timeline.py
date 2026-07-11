from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.routers.dashboard import (
    _backfill_wealth_rollups,
    _current_anchor_ts,
    _networth_components,
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
    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})

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
    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})

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


def test_backfill_writes_requested_month_count(db_engine, monkeypatch):
    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    db = Session(bind=db_engine)
    try:
        written = _backfill_wealth_rollups(db, 1, "SGD", months=6)
        rows = db.execute(
            text("SELECT month FROM wealth_monthly_rollups WHERE user_id = 1 AND base_currency = 'SGD' ORDER BY month")
        ).fetchall()
    finally:
        db.close()

    assert written == 6
    assert len(rows) == 6
    current_month = _current_anchor_ts().strftime("%Y-%m")
    assert rows[-1][0] == current_month


def test_net_worth_timeline_endpoint_returns_points_with_upload_marker(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    _seed_platform_account(db_engine, account_id=960, platform="IBKR", asset_id=960, symbol="GOOGL")
    seed_canonical_position_snapshot_for_test(
        db_engine, account_id=960, asset_id=960, as_of=date(2026, 6, 5),
        quantity=2, market_value_base=4000.0, market_price=2000.0, platform_code="IBKR",
    )
    current_month = _current_anchor_ts().strftime("%Y-%m")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO import_jobs (account_id, platform, original_filename, stored_path, file_sha256, status, created_at, updated_at) "
                "VALUES (960, 'IBKR', 'stmt.csv', '/tmp/x', 'sha', 'IMPORTED', :now, :now)"
            ),
            {"now": _current_anchor_ts()},
        )

    backfill_resp = client.post("/dashboard/net-worth-timeline/backfill?months=3&base_currency=SGD")
    assert backfill_resp.status_code == 200
    assert backfill_resp.json()["months_written"] == 3

    resp = client.get("/dashboard/net-worth-timeline?months=3&base_currency=SGD")
    assert resp.status_code == 200
    data = resp.json()

    assert data["base_currency"] == "SGD"
    months = [p["month"] for p in data["points"]]
    assert months == sorted(months)
    assert current_month in months
    assert "now" in data and "total" in data["now"]

    current_point = next(p for p in data["points"] if p["month"] == current_month)
    assert current_point["uploads"] == ["IBKR"]
    assert current_point["total"] > 0
    assert any(s["platform"] == "IBKR" for s in current_point["source_freshness"])


def test_net_worth_timeline_read_endpoint_does_not_recompute_past_months(client: TestClient, db_engine, monkeypatch):
    """The read endpoint must stay a pure scan for anything but the current month —
    that's the whole point of pre-aggregating. Prove it by poisoning an old row's
    computed value directly in the DB and confirming a plain GET doesn't touch it."""
    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
    assert client.post("/dashboard/net-worth-timeline/backfill?months=6&base_currency=SGD").status_code == 200

    past_month = _current_anchor_ts().strftime("%Y-%m")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE wealth_monthly_rollups SET total = 999999999 "
                "WHERE user_id = 1 AND base_currency = 'SGD' AND month != :current"
            ),
            {"current": past_month},
        )

    resp = client.get("/dashboard/net-worth-timeline?months=6&base_currency=SGD")
    assert resp.status_code == 200
    older_points = [p for p in resp.json()["points"] if p["month"] != past_month]
    assert older_points, "expected at least one non-current month in range"
    assert all(p["total"] == 999999999 for p in older_points)


def test_net_worth_timeline_movers_endpoint_diffs_two_historical_anchors(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setattr("app.routers.dashboard.get_rates", lambda *_a, **_k: {"SGD": 1.0, "USD": 1.0})
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
