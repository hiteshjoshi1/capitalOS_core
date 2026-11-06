"""Valuation invariants (#142): relations that must hold between the numbers
the app shows, whatever the numbers are. They run on the synthetic household
(tests/valuation_household.py) at a frozen "now".

An invariant that fails today because of a known, tracked bug is marked
``xfail(strict=True)`` with the issue number: when the fix lands the test
passes, strict xfail turns that into a failure, and the marker is removed in
the fixing PR.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import valuation_cache
from app.portfolio.ibkr_flex import run_ibkr_flex_import_from_xml
from tests.test_valuation_golden import ENDPOINTS, collect
from tests.valuation_golden import normalise
from tests.valuation_household import (
    DBS_SAVINGS,
    FLEX_REPORTS,
    IBKR,
    MISFILED_CARD,
    SCENARIOS,
    USER_A,
    USER_B,
    FlexReport,
    as_user,
    build_household,
    build_scenario,
    build_user,
    flex_xml,
    fx,
    household_env,
    import_flex,
    upload_balance,
)

MID = SCENARIOS["mid"]
FIRST = SCENARIOS["first"]
TOL = 0.01  # one cent: every figure here is a sum of floats


@pytest.fixture()
def household(client: TestClient, db_engine, monkeypatch):
    """The household at the "mid" instant (2026-03-18 10:00 SGT)."""
    household_env(monkeypatch, MID)
    build_household(db_engine, now=MID)
    return client


@pytest.fixture()
def household_first(client: TestClient, db_engine, monkeypatch):
    """The household at the "first" instant (2026-04-01 06:00 SGT, still 31 March in UTC)."""
    household_env(monkeypatch, FIRST)
    build_household(db_engine, now=FIRST)
    return client


def _get(client: TestClient, path: str) -> dict:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _summary(client: TestClient, month: str, extra: str = "&compare=prev_month,prev_year") -> dict:
    return _get(client, f"/dashboard/summary?month={month}&base_currency=SGD{extra}")


def _timeline(client: TestClient, months: int = 6, *, backfill: bool = False) -> dict:
    if backfill:
        resp = client.post(f"/dashboard/net-worth-timeline/backfill?months={months}&base_currency=SGD")
        assert resp.status_code == 200, resp.text
    return _get(client, f"/dashboard/net-worth-timeline?months={months}&base_currency=SGD")


def _components(nw: dict) -> tuple[float, float, float, float, float]:
    return nw["cash"], nw["stocks_funds"], nw["crypto"], nw["liabilities"], nw["total"]


def _stablecoins_usd(db_engine, user_id: int, as_of: date) -> float:
    """USDC/USDT in each active wallet's latest snapshot on or before ``as_of``."""
    with db_engine.connect() as conn:
        return float(
            conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(i.value_usd), 0)
                    FROM crypto_wallet_snapshot_items i
                    JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id
                    JOIN crypto_wallets w ON w.id = s.wallet_id
                    WHERE w.user_id = :u AND w.status = 'active'
                      AND UPPER(i.symbol) IN ('USDC', 'USDT')
                      AND s.as_of_date = (
                        SELECT MAX(s2.as_of_date) FROM crypto_wallet_snapshots s2
                        WHERE s2.wallet_id = s.wallet_id AND s2.as_of_date <= :d
                      )
                    """
                ),
                {"u": user_id, "d": as_of.isoformat()},
            ).scalar_one()
        )


# ─── Breakdowns add up to the headline ───────────────────────────────────────


def test_net_worth_components_add_up(household):
    summary = _summary(household, "2026-03")
    bootstrap = _get(household, "/dashboard/bootstrap?month=2026-03&base_currency=SGD")
    timeline = _timeline(household, backfill=True)
    candidates = [
        summary["net_worth"],
        summary["current_net_worth"],
        bootstrap["net_worth"],
        bootstrap["current_net_worth"],
        timeline["now"],
        *timeline["points"],
    ]
    for nw in candidates:
        cash, stocks, crypto, liabilities, total = _components(nw)
        assert total == pytest.approx(cash + stocks + crypto - liabilities, abs=TOL), nw


def test_household_has_something_in_every_component(household):
    """Guards the fixture: an invariant over zeros proves nothing."""
    cash, stocks, crypto, liabilities, total = _components(_summary(household, "2026-03")["current_net_worth"])
    assert min(cash, stocks, crypto, liabilities, total) > 0


def test_stock_pages_equal_net_worth_stocks(household):
    """Live: the Stocks page total and the stock exposure card are the
    stocks_funds component of the live headline. Past month: the same at that
    month's anchor."""
    live = _summary(household, "2026-03")["current_net_worth"]["stocks_funds"]
    assert _get(household, "/dashboard/stock-holdings?month=2026-03&base_currency=SGD")["stock_current_total"] == pytest.approx(live, abs=TOL)
    assert _get(household, "/dashboard/stock-exposure?month=2026-03&base_currency=SGD")["total"] == pytest.approx(live, abs=TOL)
    past = _summary(household, "2026-02")["net_worth"]["stocks_funds"]
    assert _get(household, "/dashboard/stock-holdings?month=2026-02&base_currency=SGD")["stock_current_total"] == pytest.approx(past, abs=TOL)


def test_crypto_page_equals_net_worth_crypto(household):
    live = _summary(household, "2026-03")["current_net_worth"]["crypto"]
    assert _get(household, "/crypto/summary?month=2026-03&base_currency=SGD")["total_crypto_base"] == pytest.approx(live, abs=TOL)
    past = _summary(household, "2026-02")["net_worth"]["crypto"]
    assert _get(household, "/crypto/summary?month=2026-02&base_currency=SGD")["total_crypto_base"] == pytest.approx(past, abs=TOL)


def test_cash_page_equals_net_worth_cash_plus_stablecoins(household, db_engine):
    """The Cash page shows net-worth cash plus stablecoins (which net worth
    counts under crypto), live and for a past month."""
    live_nw = _summary(household, "2026-03")["current_net_worth"]["cash"]
    live_page = _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")
    usd = fx(MID.date(), "USD")
    live_stable = _stablecoins_usd(db_engine, USER_A, MID.date()) * usd
    assert live_page["current_total"] == pytest.approx(live_nw + live_stable, abs=TOL)
    assert live_page["total"] == pytest.approx(live_nw + live_stable, abs=TOL)

    past_nw = _summary(household, "2026-02")["net_worth"]["cash"]
    past_page = _get(household, "/dashboard/cash-deposits?month=2026-02&base_currency=SGD")
    anchor = date(2026, 3, 1)
    past_stable = _stablecoins_usd(db_engine, USER_A, anchor) * fx(anchor, "USD")
    assert past_page["current_total"] == pytest.approx(past_nw + past_stable, abs=TOL)


def test_cash_page_ibkr_cash_is_nav_cash(household):
    report = next(r for r in FLEX_REPORTS if r.report_date == date(2026, 3, 16))
    nav_cash = report.cash_sgd + report.cash_usd * fx(report.report_date, "USD")
    items = {i["source"]: i["value"] for i in _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")["items"]}
    assert items["IBKR"] == pytest.approx(nav_cash, abs=TOL)


def test_card_account_balance_never_counts_as_cash(household, db_engine):
    """A savings balance uploaded to a card account (the #180 case) never adds
    to cash: not to net worth, not to the Cash page. (Allocation and geography
    read the same cash, _cash_positions: covered by the #144 invariants.)"""
    def figures() -> dict:
        cash_page = _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")
        past_page = _get(household, "/dashboard/cash-deposits?month=2026-02&base_currency=SGD")
        return {
            "nw_cash": _summary(household, "2026-03")["current_net_worth"]["cash"],
            "cash_page": cash_page["current_total"],
            "cash_items": cash_page["total"],
            "cash_page_february": past_page["current_total"],
        }

    with_card_balance = figures()
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM account_balance_snapshots WHERE account_id = :a"), {"a": MISFILED_CARD})
    valuation_cache.clear_shared_cache()
    assert with_card_balance == pytest.approx(figures(), abs=TOL)


def test_platform_allocation_total_is_assets(household):
    """Allocation splits gross assets: its total is net worth + liabilities."""
    nw = _summary(household, "2026-03")["current_net_worth"]
    allocation = _get(household, "/dashboard/platform-allocation?month=2026-03&base_currency=SGD")
    assert allocation["total"] == pytest.approx(nw["total"] + nw["liabilities"], abs=TOL)
    assert sum(i["value"] for i in allocation["items"]) == pytest.approx(allocation["total"], abs=TOL)


def test_summary_geography_adds_up_to_assets(household):
    summary = _summary(household, "2026-03")
    nw = summary["current_net_worth"]
    assert sum(g["value"] for g in summary["geography"]) == pytest.approx(nw["total"] + nw["liabilities"], abs=TOL)
    assert sum(g["percent"] for g in summary["geography"]) == pytest.approx(100.0, abs=0.05)


def test_geography_exposure_total_is_assets(household):
    """Geography exposure for a month splits the gross assets shown for it: live for
    the open month (2026-03, like the headline, #241), a past month's month-end."""
    for month, live in (("2026-02", False), ("2026-03", True)):
        summary = _summary(household, month)
        nw = summary["current_net_worth"] if live else summary["net_worth"]
        geo = _get(household, f"/dashboard/geography-exposure?month={month}&base_currency=SGD")
        assert geo["is_live"] is live, month
        assert geo["total"] == pytest.approx(nw["cash"] + nw["stocks_funds"] + nw["crypto"], abs=TOL), month


def test_breakdowns_add_up_to_their_own_totals(household):
    """Within one response, the items add up to the total it states."""
    cash = _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")
    assert sum(i["value"] for i in cash["items"]) == pytest.approx(cash["total"], abs=TOL)
    geo = _get(household, "/dashboard/geography-exposure?month=2026-03&base_currency=SGD")
    assert sum(i["total"] for i in geo["items"]) == pytest.approx(geo["total"], abs=TOL)
    for item in geo["items"]:
        assert item["stocks_funds"] + item["cash"] + item["crypto"] == pytest.approx(item["total"], abs=TOL)
    exposure = _get(household, "/dashboard/stock-exposure?month=2026-03&base_currency=SGD")
    for key in ("by_country", "by_platform"):
        assert sum(i["value"] for i in exposure[key]) == pytest.approx(exposure["total"], abs=TOL), key


# ─── Live vs anchor, and one figure per page ─────────────────────────────────


def test_live_headline_is_the_same_everywhere(household):
    summary = _summary(household, "2026-03")
    bootstrap = _get(household, "/dashboard/bootstrap?month=2026-03&base_currency=SGD")
    timeline = _timeline(household, backfill=True)
    now = {k: v for k, v in timeline["now"].items() if k not in {"as_of", "uploads"}}
    assert bootstrap["current_net_worth"] == pytest.approx(summary["current_net_worth"], abs=TOL)
    assert now == pytest.approx(summary["current_net_worth"], abs=TOL)
    assert bootstrap["net_worth"] == pytest.approx(summary["net_worth"], abs=TOL)


def test_open_month_reports_the_last_completed_anchor(household):
    """For the open month the snapshot figures are the last completed
    month-end's, the same as browsing that month."""
    assert _summary(household, "2026-03")["net_worth"] == pytest.approx(_summary(household, "2026-02")["net_worth"], abs=TOL)
    assert _summary(household, "2026-03")["net_worth_boundary_at"] == "2026-03-01T00:00:00+00:00"


def test_history_points_equal_the_dashboard_for_each_month(household):
    """Every stored History month is what the dashboard shows for that month,
    and History's month-on-month change is the dashboard's "vs last month"."""
    points = {p["month"]: p for p in _timeline(household, backfill=True)["points"]}
    assert set(points) == {"2025-10", "2025-11", "2025-12", "2026-01", "2026-02"}
    for month in ("2025-12", "2026-01", "2026-02"):
        summary = _summary(household, month)
        point = {k: points[month][k] for k in ("cash", "stocks_funds", "crypto", "liabilities", "total")}
        assert point == pytest.approx(summary["net_worth"], abs=TOL), month
    change = _summary(household, "2026-02")["net_worth_change"]["vs_prev_month"]["abs"]
    assert change == pytest.approx(points["2026-02"]["total"] - points["2026-01"]["total"], abs=TOL)


def test_cash_trend_points_equal_each_months_cash_page(household):
    trend = {p["month"]: p["value"] for p in _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")["trend"]}
    for month in ("2026-01", "2026-02"):
        page = _get(household, f"/dashboard/cash-deposits?month={month}&base_currency=SGD")
        assert trend[month] == pytest.approx(page["current_total"], abs=TOL), month


def test_first_of_month_dashboard_and_history_agree(household_first):
    """At 06:00 SGT on 1 April the dashboard's snapshot figures and History's
    newest point must describe the same completed month (#143: one anchor
    rule in the app timezone; it is already 1 April there)."""
    summary = _summary(household_first, "2026-04")
    points = _timeline(household_first, backfill=True)["points"]
    newest = points[-1]
    assert newest["month"] == "2026-03"
    assert summary["net_worth_boundary_at"][:10] == newest["anchor_date"]
    point = {k: newest[k] for k in ("cash", "stocks_funds", "crypto", "liabilities", "total")}
    assert point == pytest.approx(summary["net_worth"], abs=TOL)


def test_first_of_month_last_month_is_closed_everywhere(household_first):
    """At 06:00 SGT on 1 April, March is a completed month on every page: its
    summary is its own month-end (the same figures the open month reports), the
    live change compares with March's month-end, and the Stocks, Cash and
    Crypto pages browse March as a past month, not live."""
    april = _summary(household_first, "2026-04")
    march = _summary(household_first, "2026-03")
    assert march["net_worth_boundary_at"] == april["net_worth_boundary_at"] == "2026-04-01T00:00:00+00:00"
    assert march["net_worth"] == pytest.approx(april["net_worth"], abs=TOL)
    assert april["current_net_worth_change"]["vs_prev_month"]["compare_month"] == "2026-03"
    for path in ("/dashboard/stock-holdings", "/dashboard/cash-deposits", "/crypto/summary"):
        assert _get(household_first, f"{path}?month=2026-03&base_currency=SGD")["is_live"] is False, path
        assert _get(household_first, f"{path}?month=2026-04&base_currency=SGD")["is_live"] is True, path
    crypto_march = _get(household_first, "/crypto/summary?month=2026-03&base_currency=SGD")["total_crypto_base"]
    assert crypto_march == pytest.approx(march["net_worth"]["crypto"], abs=TOL)


# ─── User isolation ──────────────────────────────────────────────────────────


def _a_view(client: TestClient) -> dict:
    return normalise(collect(client, ENDPOINTS["mid"]))


def test_other_users_data_never_changes_my_numbers(client: TestClient, db_engine, monkeypatch):
    """User A's every golden endpoint, before and after user B's bank, card,
    wallet and transactions are written, is identical."""
    household_env(monkeypatch, MID)
    build_household(db_engine, now=MID, include_user_b=False)
    alone = _a_view(client)

    build_user(db_engine, USER_B, now=MID)
    valuation_cache.clear_shared_cache()
    together = _a_view(client)

    assert [path for path in alone if alone[path] != together[path]] == []


def test_user_b_sees_only_their_own_money(household, monkeypatch, db_engine):
    as_user(household, USER_B)
    nw = _summary(household, "2026-03")["current_net_worth"]
    usd = fx(MID.date(), "USD")
    # B: OCBC 17,000 SGD; wallet 1 ETH @ 3,000 + 700 USDT; card limit 5,000 - 4,200 available.
    assert nw["cash"] == pytest.approx(17000.0, abs=TOL)
    assert nw["crypto"] == pytest.approx((3000.0 + 700.0) * usd, abs=TOL)
    assert nw["liabilities"] == pytest.approx(800.0, abs=TOL)
    assert nw["stocks_funds"] == 0.0
    cash_page = _get(household, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")
    assert {i["source"] for i in cash_page["items"]} == {"OCBC", "Base"}
    assert _get(household, "/dashboard/stock-holdings?month=2026-03&base_currency=SGD")["top_holdings"] == []
    dividends = _get(household, "/dividends/summary?from_month=2026-01&to_month=2026-03&base_currency=SGD")
    assert dividends["totals"]["gross"] == 0.0


# ─── FX (D-30): a missing rate is never 1.0 ──────────────────────────────────


def test_missing_fx_rate_is_left_out_and_flagged(household, db_engine):
    """A balance in a currency with no rate at all is left out of every total
    (not valued 1:1) and the response says which currency is missing."""
    paths = {
        "summary": "/dashboard/summary?month=2026-03&base_currency=SGD&compare=prev_month",
        "cash": "/dashboard/cash-deposits?month=2026-03&base_currency=SGD",
        "allocation": "/dashboard/platform-allocation?month=2026-03&base_currency=SGD",
        "geography": "/dashboard/geography-exposure?month=2026-03&base_currency=SGD",
    }
    before = {k: _get(household, p) for k, p in paths.items()}
    assert before["summary"]["fx_incomplete"] is False

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, user_id, account_type, currency, country, platform_id) "
                "VALUES (190, 'TWD Savings', 'DBS', :a, 'BANK', 'TWD', 'TW', 1)"
            ),
            {"a": USER_A},
        )
    upload_balance(db_engine, 190, "2026-02-15", "TWD", 250000.0)
    after = {k: _get(household, p) for k, p in paths.items()}

    assert after["summary"]["fx_incomplete"] is True
    assert after["summary"]["fx_missing_currencies"] == ["TWD"]
    for key in ("net_worth", "current_net_worth"):
        assert after["summary"][key] == pytest.approx(before["summary"][key], abs=TOL), key
    def by_currency(rows: list[dict]) -> dict[str, float]:
        return {row["currency"]: row["value"] for row in rows if row["value"]}

    assert by_currency(after["summary"]["cash_balances"]) == pytest.approx(
        by_currency(before["summary"]["cash_balances"]), abs=TOL
    )
    assert after["cash"]["current_total"] == pytest.approx(before["cash"]["current_total"], abs=TOL)
    assert after["allocation"]["total"] == pytest.approx(before["allocation"]["total"], abs=TOL)
    assert after["geography"]["total"] == pytest.approx(before["geography"]["total"], abs=TOL)


# ─── History (D-29): stored rollups equal a fresh recompute after writes ─────


def _points(data: dict) -> dict[str, dict]:
    return {p["month"]: {k: v for k, v in p.items() if k != "computed_at"} for p in data["points"]}


def test_history_after_writes_equals_a_fresh_recompute(household, db_engine, monkeypatch):
    """Back-dated writes through the real write paths (an uploaded statement, an
    IBKR Flex re-import, a crypto snapshot) are reflected in History on the
    next ordinary read, exactly as a full recompute and the dashboard give."""
    from app.crypto.ingest import SnapshotResult, upsert_snapshot

    before = _points(_timeline(household, backfill=True))  # rows stored, nothing dirty

    upload_balance(db_engine, DBS_SAVINGS, "2026-02-27", "SGD", 48000.0)
    import_flex(db_engine, FlexReport(date(2026, 1, 30), 2600.0, 1400.0, FLEX_REPORTS[0].holdings))
    monkeypatch.setattr("app.crypto.ingest._as_of_date", lambda: date(2026, 1, 25))
    db = Session(bind=db_engine)
    try:
        upsert_snapshot(
            db,
            "wallet-a-sol",
            SnapshotResult(
                total_usd=4000.0,
                items=[
                    {
                        "chain": "solana", "asset_kind": "native", "contract_or_mint": None, "symbol": "SOL",
                        "name": "Solana", "decimals": 9, "raw_amount": "25000000000", "normalized_amount": 25.0,
                        "price_usd": 160.0, "value_usd": 4000.0, "price_source": "synthetic",
                    }
                ],
                source_versions={},
            ),
        )
        db.commit()
    finally:
        db.close()

    lazily = _points(_timeline(household))  # the next ordinary read
    recomputed = _points(_timeline(household, backfill=True))  # "Generate history": every month recomputed
    assert lazily == recomputed
    for month in ("2026-01", "2026-02"):
        point = {k: lazily[month][k] for k in ("cash", "stocks_funds", "crypto", "liabilities", "total")}
        assert point == pytest.approx(_summary(household, month)["net_worth"], abs=TOL), month
    # The writes did reach History (else this proves nothing): the crypto
    # snapshot and the Flex re-import change January, the statement February.
    assert [m for m in before if before[m]["total"] != recomputed[m]["total"]] == ["2026-01", "2026-02"]


def test_history_after_an_fx_correction_equals_a_fresh_process(household):
    """A corrected rate for a past date (here 1 Jan, December's anchor) is in
    History on the next read, the same as a fresh process computes it (#188:
    storing it drops the in-process rate cache from that date on)."""
    from app import fx as fx_module

    before = _points(_timeline(household, backfill=True))
    fx_module._store_rows(
        [{"rate_date": "2026-01-01", "base": "EUR", "quote": "USD", "rate": 1.12, "source": "synthetic",
          "fetched_at": datetime(2026, 3, 18, tzinfo=timezone.utc).isoformat()}]
    )
    lazily = _points(_timeline(household))
    fx_module._CACHE.clear()  # what a restarted API would know
    fresh = _points(_timeline(household, backfill=True))
    assert fresh["2025-12"]["total"] != before["2025-12"]["total"]  # the correction matters
    assert lazily == fresh


def _with_usd_sgd(xml: str, rate: float) -> str:
    """The same Flex statement with another USD->SGD ConversionRate (only that
    rate: positions and NAV keep the values IBKR computed them with)."""
    out, count = re.subn(r'(fromCurrency="USD" toCurrency="SGD" rate=")[^"]+', rf"\g<1>{rate:.8f}", xml)
    assert count == 1
    return out


def _import_flex_xml(db_engine, xml: str) -> None:
    db = Session(bind=db_engine)
    try:
        run_ibkr_flex_import_from_xml(db, current_user_id=USER_A, legacy_account_id=IBKR, xml_text=xml)
    finally:
        db.close()


def _statement_rates_decide(db_engine) -> None:
    """The synthetic ECB-style rows win over a statement rate on the same day, so
    for the days January's and February's anchors (1 Feb, 1 Mar) resolve to,
    drop them: those anchors then read the 30 Jan and 27 Feb statement rates."""
    from app import fx as fx_module

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "DELETE FROM fx_rates WHERE rate_date BETWEEN '2026-01-30' AND '2026-02-01' "
                "OR rate_date BETWEEN '2026-02-27' AND '2026-03-01'"
            )
        )
    fx_module._CACHE.clear()


def _statement_rates(db_engine) -> dict[tuple[str, str, str], float]:
    with db_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT report_date, from_currency, to_currency, rate FROM portfolio_fx_rates")
        ).fetchall()
    return {(str(r[0])[:10], r[1], r[2]): float(r[3]) for r in rows}


def test_history_after_a_corrected_flex_statement_rate_equals_a_fresh_process(household, db_engine, monkeypatch):
    """#197: re-importing a Flex statement with a corrected rate (30 Jan, what
    January's anchor reads) is in History and in the cached dashboard on the
    next read, the same as a fresh process computes them: the import drops the
    in-process rate cache from that date on and marks History dirty."""
    from app import fx as fx_module

    monkeypatch.setenv("VALUATION_CACHE_ENABLED", "1")
    _statement_rates_decide(db_engine)
    before = _points(_timeline(household, backfill=True))
    summary_before = _summary(household, "2026-01")["net_worth"]["total"]
    jan = FLEX_REPORTS[0]
    _import_flex_xml(db_engine, _with_usd_sgd(flex_xml(jan), fx(jan.report_date, "USD") * 1.04))

    lazily = _points(_timeline(household))
    summary_lazily = _summary(household, "2026-01")["net_worth"]["total"]
    fx_module._CACHE.clear()  # what a restarted API would know
    valuation_cache.clear_shared_cache()
    fresh = _points(_timeline(household, backfill=True))
    summary_fresh = _summary(household, "2026-01")["net_worth"]["total"]
    assert fresh["2026-01"]["total"] != pytest.approx(before["2026-01"]["total"], abs=TOL)  # the correction matters
    assert summary_fresh != pytest.approx(summary_before, abs=TOL)
    assert lazily == fresh
    assert summary_lazily == summary_fresh


def test_an_older_flex_report_imported_after_newer_ones_leaves_newer_rates_and_history(household, db_engine):
    """#197: the household has the 27 Feb and March reports; importing the
    30 Jan report again (with a corrected rate) replaces only 30 Jan's rate.
    The newer dates' statement rates and their History months stay as they were."""
    _statement_rates_decide(db_engine)
    before = _points(_timeline(household, backfill=True))
    rates_before = _statement_rates(db_engine)
    jan = FLEX_REPORTS[0]
    new_rate = fx(jan.report_date, "USD") * 1.04
    _import_flex_xml(db_engine, _with_usd_sgd(flex_xml(jan), new_rate))

    after = _points(_timeline(household))
    rates_after = _statement_rates(db_engine)
    jan_key = ("2026-01-30", "USD", "SGD")
    assert rates_after[jan_key] == pytest.approx(new_rate)
    assert {k: v for k, v in rates_after.items() if k != jan_key} == {
        k: v for k, v in rates_before.items() if k != jan_key
    }
    assert after["2026-01"]["total"] != pytest.approx(before["2026-01"]["total"], abs=TOL)  # it did reach History
    for month in ("2026-02",):  # read from the 27 Feb statement rate
        assert after[month] == before[month], month


def test_flex_backfill_does_not_resource_older_history(household, db_engine):
    """December's IBKR cash came from an upload (Flex took over on 30 January).
    Importing a Flex statement that starts in December must not change which
    source counts for December without an explicit action."""
    before = {p["month"]: p["total"] for p in _timeline(household, backfill=True)["points"]}
    report = FlexReport(
        date(2026, 1, 30), 2000.0, 1500.0, FLEX_REPORTS[0].holdings,
        nav_history=((date(2025, 12, 31), 4000.0, 9000.0),),
    )
    import_flex(db_engine, report, from_date=date(2025, 12, 1))
    after = {p["month"]: p["total"] for p in _timeline(household)["points"]}
    assert after["2025-12"] == pytest.approx(before["2025-12"], abs=TOL)


# ─── Caching (D-28): on or off, the same answers ─────────────────────────────


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_cache_on_and_off_give_identical_results(scenario: str, client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS[scenario])
    build_scenario(db_engine, scenario)
    paths = ENDPOINTS[scenario]

    monkeypatch.setenv("VALUATION_CACHE_ENABLED", "0")
    uncached = normalise(collect(client, paths))
    monkeypatch.setenv("VALUATION_CACHE_ENABLED", "1")
    valuation_cache.clear_shared_cache()
    cold = normalise(collect(client, paths))
    warm = normalise(collect(client, paths))
    assert valuation_cache.shared_cache.hits > 0
    assert [p for p in paths if cold[p] != uncached[p]] == []
    assert [p for p in paths if warm[p] != uncached[p]] == []
