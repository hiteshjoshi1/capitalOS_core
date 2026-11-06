"""One number everywhere (#232, #131 item 1): the contract between pages.

For the synthetic household (tests/valuation_household.py) at each golden
instant, in base currencies SGD and USD, for the live month and past months,
the figures the pages show for one month are one set of numbers:

- the Overview headline (live: ``/dashboard/bootstrap`` ``current_net_worth``;
  a past month: its month-end ``net_worth``, #223) is the sum of its
  components, cash + stocks_funds + crypto - liabilities;
- it is History's point for that month (live: the "now" point);
- the Stocks, Crypto and Cash page headlines are its components (the Cash page
  adds stablecoins, which net worth counts under Crypto: D-42; the response
  names the stablecoin part, so the page can say so);
- the allocation donuts (by platform and by asset class) split gross assets,
  cash + stocks_funds + crypto: net worth plus liabilities;
- every "previous" figure (vs last month, since last update, the pages' compare
  month) names its month and the date of its data, unless there is no data for
  it at all (``baseline_missing``, #224), and is History's point for that month;
- Overview's "This month" bridge (#240, D-60) starts at the hero's "vs last
  month" figure and ends at the headline, and its lines plus the unexplained
  residual add up to the difference;
- Risk (#241) divides by the headline (live: the Overview hero; a past month:
  that month-end) and its geography splits the same gross assets, at one point
  in time, which it names;
- the six-month trends on the Stocks, Crypto and Cash pages (#241, D-61): the
  open month's bar is the live headline (month to date, marked live), every
  other bar is History's point for a completed month-end, and a month whose
  month-end hasn't passed has no bar.

The figure helpers mirror what the web pages read (web/src/routes/*).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.valuation_household import SCENARIOS, SGT, build_household, build_scenario, household_env

TOL = 0.01  # one cent: every figure is a sum of floats
COMPONENTS = ("cash", "stocks_funds", "crypto", "liabilities", "total")

# scenario -> (the live month, past months browsed)
MONTHS: dict[str, tuple[str, tuple[str, ...]]] = {
    "mid": ("2026-03", ("2026-02", "2026-01", "2025-12")),
    "first": ("2026-04", ("2026-03", "2026-02")),
    "first_us": ("2026-03", ("2026-02", "2026-01")),
    # SNAPSHOT_DAY=5 on 3 March: February is a past month whose month-end
    # anchor (5 March) hasn't passed yet, so every page reads January's
    # month-end for it, and the live month compares with January (D-55).
    "early_snapshot_day": ("2026-03", ("2026-02", "2026-01")),
}
EARLY_SNAPSHOT_DAY_NOW = datetime(2026, 3, 3, 10, 0, tzinfo=SGT)
BASES = ("SGD", "USD")
HISTORY_MONTHS = 6


def _get(client: TestClient, path: str) -> dict[str, Any]:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _prev_month(month: str) -> str:
    year, mon = (int(part) for part in month.split("-"))
    return f"{year - 1}-12" if mon == 1 else f"{year}-{mon - 1:02d}"


def _nw(values: dict[str, Any]) -> dict[str, float]:
    return {key: float(values[key]) for key in COMPONENTS}


def _gross(nw: dict[str, float]) -> float:
    return nw["cash"] + nw["stocks_funds"] + nw["crypto"]


def _overview_headline(bootstrap: dict[str, Any]) -> dict[str, float]:
    """What WealthOverview.tsx shows: live, current_net_worth; a past month,
    its month-end net_worth."""
    return _nw(bootstrap["current_net_worth"] if bootstrap["is_live"] else bootstrap["net_worth"])


def _overview_month(bootstrap: dict[str, Any]) -> str:
    """The month History's point is for: the month before the anchor date
    (WealthOverview.tsx ``snapshotMonth``)."""
    return _prev_month(bootstrap["net_worth_boundary_at"][:7])


def _assert_dated(figure: dict[str, Any], *, date_key: str, missing: bool, where: str) -> None:
    """A previous figure names its month and the date of its data; only a
    comparison with no data at all (#224) has no date, and says so."""
    assert figure.get("compare_month"), where
    if missing:
        assert figure.get(date_key) is None, where
    else:
        assert figure.get(date_key), where


class _Pages:
    """One base currency's pages for the household, read like the web app."""

    def __init__(self, client: TestClient, base: str):
        self.client = client
        self.base = base
        backfill = client.post(f"/dashboard/net-worth-timeline/backfill?months={HISTORY_MONTHS}&base_currency={base}")
        assert backfill.status_code == 200, backfill.text
        self.timeline = self.get(f"/dashboard/net-worth-timeline?months={HISTORY_MONTHS}")
        self.points = {p["month"]: p for p in self.timeline["points"]}

    def get(self, path: str) -> dict[str, Any]:
        sep = "&" if "?" in path else "?"
        return _get(self.client, f"{path}{sep}base_currency={self.base}")

    def history_point(self, month: str) -> dict[str, float]:
        assert month in self.points, (month, sorted(self.points))
        return _nw(self.points[month])


def _check_month(pages: _Pages, month: str, *, live: bool) -> None:
    where = f"{pages.base} {month} ({'live' if live else 'past'})"
    bootstrap = pages.get(f"/dashboard/bootstrap?month={month}")
    summary = pages.get(f"/dashboard/summary?month={month}&compare=prev_month,prev_year")
    assert bootstrap["is_live"] is live, where
    assert summary["is_live"] is live, where
    assert bootstrap["base_currency"] == summary["base_currency"] == pages.base, where

    # Overview: the headline, and the same figures from the heavier summary.
    headline = _overview_headline(bootstrap)
    assert _nw(summary["current_net_worth"]) == pytest.approx(_nw(bootstrap["current_net_worth"]), abs=TOL), where
    assert _nw(summary["net_worth"]) == pytest.approx(_nw(bootstrap["net_worth"]), abs=TOL), where
    assert headline["total"] == pytest.approx(
        headline["cash"] + headline["stocks_funds"] + headline["crypto"] - headline["liabilities"], abs=TOL
    ), where
    if live:
        assert bootstrap["current_stock_exposure_total"] == pytest.approx(headline["stocks_funds"], abs=TOL), where
        assert bootstrap["current_crypto_exposure_total"] == pytest.approx(headline["crypto"], abs=TOL), where
    else:
        assert bootstrap["stock_exposure_total"] == pytest.approx(headline["stocks_funds"], abs=TOL), where
        assert bootstrap["crypto_exposure_total"] == pytest.approx(headline["crypto"], abs=TOL), where

    # History: the "now" point live, else the stored point of that month-end.
    if live:
        now = _nw(pages.timeline["now"])
        assert now == pytest.approx(headline, abs=TOL), where
    else:
        assert pages.history_point(_overview_month(bootstrap)) == pytest.approx(headline, abs=TOL), where

    # Overview's breakdowns: allocation by platform and by asset class, the
    # cash balances and geography all split gross assets.
    gross = _gross(headline)
    allocation = pages.get(f"/dashboard/platform-allocation?month={month}")
    assert allocation["is_live"] is live, where
    assert allocation["total"] == pytest.approx(gross, abs=TOL), where
    assert sum(item["value"] for item in allocation["items"]) == pytest.approx(gross, abs=TOL), where
    assert sum(item["value"] for item in summary["cash_balances"]) == pytest.approx(headline["cash"], abs=TOL), where
    assert sum(item["value"] for item in summary["geography"]) == pytest.approx(gross, abs=TOL), where

    # Stocks page headline (and the stock exposure card).
    stocks = pages.get(f"/dashboard/stock-holdings?month={month}")
    assert stocks["is_live"] is live, where
    assert stocks["stock_current_total"] == pytest.approx(headline["stocks_funds"], abs=TOL), where
    exposure = pages.get(f"/dashboard/stock-exposure?month={month}")
    assert exposure["total"] == pytest.approx(headline["stocks_funds"], abs=TOL), where

    # Crypto page headline.
    crypto = pages.get(f"/crypto/summary?month={month}")
    assert crypto["is_live"] is live, where
    assert crypto["total_crypto_base"] == pytest.approx(headline["crypto"], abs=TOL), where

    # Cash page headline: net-worth cash plus stablecoins (D-42), and it says how much.
    cash = pages.get(f"/dashboard/cash-deposits?month={month}")
    assert cash["is_live"] is live, where
    assert cash["current_total"] == pytest.approx(cash["total"], abs=TOL), where
    assert sum(item["value"] for item in cash["items"]) == pytest.approx(cash["total"], abs=TOL), where
    assert cash["current_total"] - cash["current_stablecoin_total"] == pytest.approx(headline["cash"], abs=TOL), where
    stablecoins_counted_as_crypto = cash["current_stablecoin_total"]
    assert 0 <= stablecoins_counted_as_crypto <= headline["crypto"] + TOL, where

    # Risk (#241): its shares divide by the headline, at the positions' point in
    # time, and its geography splits the same gross assets.
    risk = pages.get(f"/dashboard/risk-summary?month={month}")
    assert risk["is_live"] is live, where
    assert risk["basis"] == ("live" if live else "month_end"), where
    assert _nw(risk["view_net_worth"]) == pytest.approx(headline, abs=TOL), where
    risk_stocks = sum(row["value"] for row in risk["top_holdings"] if row["asset_class"] in {"STOCK", "FUND"})
    assert risk_stocks == pytest.approx(headline["stocks_funds"], abs=TOL), where
    geography = pages.get(f"/dashboard/geography-exposure?month={month}")
    assert geography["is_live"] is live, where
    assert geography["total"] == pytest.approx(gross, abs=TOL), where

    # A past month: every page is taken at the month-end Overview shows.
    if not live:
        boundary = bootstrap["net_worth_boundary_at"]
        assert stocks["net_worth_boundary_at"] == cash["net_worth_boundary_at"] == crypto["as_of"] == boundary, where
        assert risk["net_worth_boundary_at"] == boundary, where

    _check_trends(pages, month, live=live, bootstrap=bootstrap, headline=headline, stocks=stocks, crypto=crypto, cash=cash)
    _check_previous_figures(pages, month, live=live, summary=summary, stocks=stocks, crypto=crypto, cash=cash)


def _assert_bar(point: dict[str, Any], figure: float, where: Any) -> None:
    """A trend bar shows ``figure``; a zero figure has no bar (the trends' rule)."""
    if figure > TOL:
        assert point["value"] == pytest.approx(figure, abs=TOL), where
    else:
        assert point["value"] in (None, 0), where


def _check_trends(
    pages: _Pages,
    month: str,
    *,
    live: bool,
    bootstrap: dict[str, Any],
    headline: dict[str, float],
    stocks: dict[str, Any],
    crypto: dict[str, Any],
    cash: dict[str, Any],
) -> None:
    """The six-month trends (#241, D-61): one point in time per bar."""
    where = f"{pages.base} {month} ({'live' if live else 'past'})"
    shown_month = month if live else _overview_month(bootstrap)
    trends = {
        "stocks": (stocks["trend"], headline["stocks_funds"], stocks["stock_snapshot_total"], "stocks_funds"),
        "crypto": (crypto["trend"], headline["crypto"], crypto["snapshot_total_base"], "crypto"),
        # The Cash page's cash includes stablecoins (D-42), so its bars are
        # checked against the page's own figures, not History's cash.
        "cash": (cash["trend"], cash["current_total"], cash["snapshot_total"], None),
    }
    for name, (trend, current, previous, component) in trends.items():
        label = f"{where} {name} trend"
        assert len(trend) == 6 and trend[-1]["month"] == month, label
        bars = {point["month"]: point for point in trend}
        live_bars = [point["month"] for point in trend if point["is_live"]]
        # Only the open month is live, and only when it's in the window.
        assert live_bars == ([month] if live else []), label
        # The month the page shows is its headline; the month it compares with,
        # its previous figure.
        if shown_month in bars:
            _assert_bar(bars[shown_month], current, (label, shown_month))
        prev_month = stocks["compare_month"]
        if prev_month in bars:
            _assert_bar(bars[prev_month], previous, (label, prev_month))
        for point in trend:
            if point["is_live"]:
                continue
            if point["month"] in pages.points:
                # A completed month-end: History's point for that month.
                if component is not None:
                    _assert_bar(point, pages.history_point(point["month"])[component], (label, point["month"]))
            elif point["month"] > min(pages.points):
                # Inside History's range but no point: its month-end hasn't
                # passed, so no bar either.
                assert point["value"] is None, (label, point["month"])


def _check_previous_figures(
    pages: _Pages,
    month: str,
    *,
    live: bool,
    summary: dict[str, Any],
    stocks: dict[str, Any],
    crypto: dict[str, Any],
    cash: dict[str, Any],
) -> None:
    """Every "previous" figure names its date, and is History's point for its month."""
    where = f"{pages.base} {month} ({'live' if live else 'past'})"

    # Overview hero: live vs the latest completed month-end (D-24), a past
    # month-end vs the one before it; and vs the same month-end a year earlier.
    change = summary["current_net_worth_change"] if live else summary["net_worth_change"]
    for label in ("vs_prev_month", "vs_prev_year"):
        figure = change[label]
        _assert_dated(figure, date_key="compare_as_of", missing=figure["baseline_missing"], where=f"{where} {label}")
        if figure["compare_month"] in pages.points:
            point = pages.history_point(figure["compare_month"])
            assert figure["compare_value"] == pytest.approx(point["total"], abs=TOL), (where, label)
    prev_month = change["vs_prev_month"]["compare_month"]
    _check_bridge(pages, month, live=live, figure=change["vs_prev_month"])

    if live:
        since = pages.get("/dashboard/net-worth-since-update")
        figure = since["net_worth_change"]
        assert figure["compare_month"] and figure["current_as_of"], where
        assert bool(figure["compare_as_of"]) is not figure["baseline_missing"], where
        assert since["compare_as_of"] == figure["compare_as_of"], where

    # The pages compare with the month before the one shown, the same month the
    # Overview hero compares with.
    assert stocks["compare_month"] == crypto["compare_month"] == cash["compare_month"] == prev_month, where
    previous = pages.history_point(prev_month)

    figure = {"compare_month": stocks["compare_month"], "as_of": stocks["stock_snapshot_as_of"]}
    _assert_dated(figure, date_key="as_of", missing=stocks["stock_snapshot_missing"], where=f"{where} stocks")
    assert stocks["stock_snapshot_total"] == pytest.approx(previous["stocks_funds"], abs=TOL), where

    _assert_dated(crypto, date_key="snapshot_as_of", missing=crypto["snapshot_missing"], where=f"{where} crypto")
    assert crypto["snapshot_total_base"] == pytest.approx(previous["crypto"], abs=TOL), where

    _assert_dated(cash, date_key="snapshot_cash_as_of", missing=cash["snapshot_missing"], where=f"{where} cash")
    assert cash["snapshot_total"] - cash["snapshot_stablecoin_total"] == pytest.approx(previous["cash"], abs=TOL), where
    assert cash["delta_abs"] == pytest.approx(cash["current_total"] - cash["snapshot_total"], abs=TOL), where


def _check_bridge(pages: _Pages, month: str, *, live: bool, figure: dict[str, Any]) -> None:
    """The bridge's start is the hero's "vs last month" figure, its end the
    headline, and start + lines + unexplained = end."""
    where = f"{pages.base} {month} ({'live' if live else 'past'}) bridge"
    bootstrap = pages.get(f"/dashboard/bootstrap?month={month}")
    headline = _overview_headline(bootstrap)
    bridge = pages.get(f"/dashboard/month-bridge?month={month}")
    assert bridge["is_live"] is live and bridge["base_currency"] == pages.base, where
    assert _nw(bridge["end"]["net_worth"]) == pytest.approx(headline, abs=TOL), where
    assert bridge["end"]["value"] == pytest.approx(headline["total"], abs=TOL), where
    start = bridge["start"]
    assert start["month"] == figure["compare_month"], where
    assert start["value"] == pytest.approx(figure["compare_value"], abs=TOL), where
    assert start["as_of"] == figure["compare_as_of"], where
    assert start["baseline_missing"] is figure["baseline_missing"], where
    if start["month"] in pages.points:
        assert _nw(start["net_worth"]) == pytest.approx(pages.history_point(start["month"]), abs=TOL), where
    total = start["value"] + sum(line["amount"] for line in bridge["lines"]) + bridge["unexplained"]["amount"]
    assert total == pytest.approx(bridge["end"]["value"], abs=1e-6), where
    assert bridge["change"] == pytest.approx(bridge["end"]["value"] - start["value"], abs=1e-6), where


@pytest.mark.parametrize("base", BASES)
@pytest.mark.parametrize("scenario", sorted(MONTHS))
def test_one_number_everywhere(scenario: str, base: str, client: TestClient, db_engine, monkeypatch):
    if scenario == "early_snapshot_day":
        household_env(monkeypatch, EARLY_SNAPSHOT_DAY_NOW)
        monkeypatch.setenv("SNAPSHOT_DAY", "5")
        build_household(db_engine, now=EARLY_SNAPSHOT_DAY_NOW)
    else:
        household_env(monkeypatch, SCENARIOS[scenario])
        build_scenario(db_engine, scenario)
    pages = _Pages(client, base)
    live_month, past_months = MONTHS[scenario]
    _check_month(pages, live_month, live=True)
    for month in past_months:
        _check_month(pages, month, live=False)


def test_the_contract_is_not_over_zeros(client: TestClient, db_engine, monkeypatch):
    """Guards the fixture: every component, the stablecoins the Cash page adds
    and a liability the donut must not hide are non-zero in the live month."""
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    bootstrap = _get(client, "/dashboard/bootstrap?month=2026-03&base_currency=SGD")
    headline = _overview_headline(bootstrap)
    assert min(headline.values()) > 0, headline
    cash = _get(client, "/dashboard/cash-deposits?month=2026-03&base_currency=SGD")
    assert cash["current_stablecoin_total"] > 0
    assert cash["snapshot_stablecoin_total"] > 0
