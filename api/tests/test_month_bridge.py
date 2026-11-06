"""Overview's "This month" bridge (#240, D-60) on the synthetic household
(tests/valuation_household.py).

- For every golden instant, base SGD and USD, the open month and past months:
  start + lines + unexplained = end, each line's parts add up to it, and start/end
  are the contract figures (also held in test_one_number_contract.py).
- Each line's amount, worked out by hand from the household's inputs: cash kept
  and dividends/interest against the Cash flow and Dividends pages, the price /
  FX / quantity split of a holding, the named parts of the unexplained rest.
- New money: a broker deposit from outside your accounts counts; one matched by
  a transfer out of another of your accounts is a move inside net worth.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.valuation.bridge import _Holding, _split
from tests.valuation_household import DBS_SAVINGS, IBKR, SCENARIOS, build_scenario, fx, household_env

TOL = 0.01
MONTHS: dict[str, tuple[str, tuple[str, ...]]] = {
    "mid": ("2026-03", ("2026-02", "2026-01")),
    "first": ("2026-04", ("2026-03", "2026-02")),
    "first_us": ("2026-03", ("2026-02", "2026-01")),
}
LINES = ("new_money", "markets", "fx", "dividends_interest", "cash_kept")


def _get(client: TestClient, path: str) -> dict[str, Any]:
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.text)
    return resp.json()


def _bridge(client: TestClient, month: str, base: str = "SGD", limit: int = 20) -> dict[str, Any]:
    return _get(client, f"/dashboard/month-bridge?month={month}&base_currency={base}&limit={limit}")


def _line(bridge: dict[str, Any], key: str) -> dict[str, Any]:
    return next(line for line in bridge["lines"] if line["key"] == key)


def _part(line: dict[str, Any], key: str) -> float:
    return next((part["amount"] for part in line["parts"] if part["key"] == key), 0.0)


def _mover(bridge: dict[str, Any], symbol: str) -> dict[str, Any]:
    return next(m for m in bridge["movers"] if m["symbol"] == symbol)


def _assert_adds_up(bridge: dict[str, Any], where: str) -> None:
    assert [line["key"] for line in bridge["lines"]] == list(LINES), where
    total = bridge["start"]["value"] + sum(line["amount"] for line in bridge["lines"]) + bridge["unexplained"]["amount"]
    assert total == pytest.approx(bridge["end"]["value"], abs=1e-6), where
    for line in [*bridge["lines"], bridge["unexplained"]]:
        assert line["status"] in {"ok", "partial", "unavailable"}, (where, line["key"])
        if line["status"] != "ok":
            assert line["reason"], (where, line["key"])
        if line["parts"]:
            assert sum(p["amount"] for p in line["parts"]) == pytest.approx(line["amount"], abs=1e-6), (where, line["key"])
    for mover in bridge["movers"]:
        assert mover["cause"] in {"price", "quantity", "fx", "unknown"}, where
        assert mover["change"] == pytest.approx(mover["end_value"] - mover["start_value"], abs=1e-6), where


@pytest.mark.parametrize("base", ("SGD", "USD"))
@pytest.mark.parametrize("scenario", sorted(MONTHS))
def test_bridge_adds_up_for_every_instant(scenario: str, base: str, client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS[scenario])
    build_scenario(db_engine, scenario)
    live_month, past_months = MONTHS[scenario]
    for month, live in ((live_month, True), *((m, False) for m in past_months)):
        where = f"{scenario} {base} {month}"
        bridge = _bridge(client, month, base)
        assert bridge["is_live"] is live, where
        _assert_adds_up(bridge, where)
        bootstrap = _get(client, f"/dashboard/bootstrap?month={month}&base_currency={base}")
        headline = bootstrap["current_net_worth"] if live else bootstrap["net_worth"]
        assert bridge["end"]["value"] == pytest.approx(headline["total"], abs=TOL), where
        summary = _get(client, f"/dashboard/summary?month={month}&base_currency={base}&compare=prev_month")
        figure = (summary["current_net_worth_change"] if live else summary["net_worth_change"])["vs_prev_month"]
        assert bridge["start"]["value"] == pytest.approx(figure["compare_value"], abs=TOL), where
        assert bridge["start"]["month"] == figure["compare_month"], where


@pytest.fixture
def mid(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    return client


def test_open_month_lines_by_hand(mid: TestClient):
    """March 2026, live on 18 March (SGD): the household's inputs, line by line."""
    bridge = _bridge(mid, "2026-03")
    _assert_adds_up(bridge, "mid live")
    usd, inr = fx(date(2026, 3, 18), "USD"), fx(date(2026, 3, 18), "INR")
    assert bridge["start"]["month"] == "2026-02" and bridge["period_start"] == "2026-03-01"

    # Cash kept: the Cash flow page's income and expenses for the month so far,
    # without the Sharekhan dividend (its own line).
    kept = _line(bridge, "cash_kept")
    assert _part(kept, "income") == pytest.approx(450.0, abs=TOL)  # the refund
    spending = 2500.0 + 300.0 * usd + 660.0 + 310.55  # rent, travel (USD), two card purchases
    assert _part(kept, "spending") == pytest.approx(-spending, abs=TOL)
    cash_flow = _get(mid, "/spending/summary?month=2026-03&base_currency=SGD")
    dividends = _line(bridge, "dividends_interest")
    assert _part(dividends, "dividends") == pytest.approx(320.0 * inr, abs=TOL)
    assert _part(kept, "income") + _part(dividends, "dividends") == pytest.approx(cash_flow["income_total"], abs=TOL)
    assert -_part(kept, "spending") == pytest.approx(cash_flow["expense_total"], abs=TOL)

    # Markets: AAPL 20 @190 (27 Feb statement) -> 25 held, quoted 205 on 17 March;
    # the FX rate doesn't move within the month here, so FX is the statement's own.
    aapl = _mover(bridge, "AAPL")
    fx_feb = fx(date(2026, 2, 27), "USD")
    assert aapl["price_effect"] == pytest.approx(20 * (205.0 - 190.0) * usd, abs=TOL)
    assert aapl["fx_effect"] == pytest.approx(20 * 190.0 * (usd - fx_feb), abs=TOL)
    assert aapl["quantity_effect"] == pytest.approx(5 * 205.0 * usd, abs=TOL)
    assert aapl["cause"] == "quantity"
    # Crypto: ETH 2 @2800 -> 2.5 @3100, SOL 40 @150 -> @170; USDC 2000 -> 1000, USDT 0 -> 250.
    markets = _line(bridge, "markets")
    assert _part(markets, "crypto") == pytest.approx((2 * 300.0 + 40 * 20.0) * usd, abs=TOL)

    # Unexplained, named: two RELIANCE bought at Sharekhan (no cash record there),
    # tokens moved into the wallets, and February's card spend that March's card
    # liability (this month's transactions, no statement) no longer counts.
    rest = bridge["unexplained"]
    assert _part(rest, "untracked_trades") == pytest.approx(2 * 2900.0 * inr, abs=TOL)
    assert _part(rest, "crypto_moved") == pytest.approx((0.5 * 3100.0 - 1000.0 + 250.0) * usd, abs=TOL)
    assert _part(rest, "card_balances") == pytest.approx(1210.4 + 95.0 - 1000.0, abs=TOL)
    assert bridge["liabilities_change"] == pytest.approx((660.0 + 310.55) - (1210.4 + 95.0 - 1000.0), abs=TOL)
    new_money = _line(bridge, "new_money")
    assert new_money["amount"] == 0.0
    assert new_money["status"] == "partial" and "Sharekhan" in new_money["reason"]
    assert any("Sharekhan" in part["label"] for part in rest["parts"] if part["key"] == "untracked_trades")


def test_past_month_lines_by_hand(mid: TestClient):
    """February 2026 (a past month): its whole calendar month, month-end to month-end."""
    bridge = _bridge(mid, "2026-02")
    _assert_adds_up(bridge, "mid past")
    assert bridge["start"]["month"] == "2026-01" and bridge["end"]["month"] == "2026-02"
    assert bridge["period_start"] == "2026-02-01" and bridge["period_end"].startswith("2026-03-01")

    kept = _line(bridge, "cash_kept")
    assert _part(kept, "income") == pytest.approx(8000.0 + 2200.0, abs=TOL)  # salary; salary on the misfiled card
    assert _part(kept, "spending") == pytest.approx(-(2500.0 + 1210.4 + 95.0), abs=TOL)  # the card payment is a transfer

    # Dividends net of withholding, the Dividends page's figure (IBKR's from the
    # broker ledger, Sharekhan's from transactions), and HSBC's interest.
    dividends = _line(bridge, "dividends_interest")
    page = _get(mid, "/dividends/summary?from_month=2026-02&to_month=2026-02&base_currency=SGD")
    assert _part(dividends, "dividends") == pytest.approx(page["totals"]["net_received"], abs=TOL)
    expected = (450.0 - 45.0) * fx(date(2026, 2, 14), "INR") + (5.0 - 1.5) * fx(date(2026, 2, 12), "USD")
    assert _part(dividends, "dividends") == pytest.approx(expected, abs=TOL)
    assert _part(dividends, "interest") == pytest.approx(120.0 * fx(date(2026, 2, 15), "USD"), abs=TOL)

    # AAPL 20 @180 (30 Jan) -> 20 @190 (27 Feb), each statement at its own date's rate.
    aapl = _mover(bridge, "AAPL")
    fx_jan, fx_feb = fx(date(2026, 1, 30), "USD"), fx(date(2026, 2, 27), "USD")
    assert aapl["price_effect"] == pytest.approx(20 * 10.0 * fx_feb, abs=TOL)
    assert aapl["fx_effect"] == pytest.approx(20 * 180.0 * (fx_feb - fx_jan), abs=TOL)
    assert aapl["quantity_effect"] == pytest.approx(0.0, abs=TOL)
    assert aapl["cause"] == "price"
    # Crypto in USD moves with USD/SGD: the start's tokens revalued from 1 Feb's rate to 1 Mar's.
    assert _part(_line(bridge, "fx"), "crypto") != 0.0


def test_usd_base_converts_every_line(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    sgd, usd = _bridge(client, "2026-02", "SGD"), _bridge(client, "2026-02", "USD")
    assert usd["base_currency"] == "USD"
    # Cash kept is all SGD flows: the same flows at each date's SGD->USD rate.
    sgd_per_usd = fx(date(2026, 2, 24), "USD")
    assert _part(_line(usd, "cash_kept"), "income") == pytest.approx(10200.0 / sgd_per_usd, abs=TOL)
    assert _part(_line(sgd, "cash_kept"), "income") == pytest.approx(10200.0, abs=TOL)
    # AAPL in USD: IBKR states it in SGD at the statement's own rate, net worth turns
    # that into USD at the month-end's. The rate it implies is USD per USD at two
    # dates, near 1: the price move is the split's, the small rest is FX.
    r0 = fx(date(2026, 1, 30), "USD") / fx(date(2026, 2, 1), "USD")
    r1 = fx(date(2026, 2, 27), "USD") / fx(date(2026, 3, 1), "USD")
    aapl = _mover(usd, "AAPL")
    assert aapl["price_effect"] == pytest.approx(20 * 10.0 * r1, abs=TOL)
    assert aapl["fx_effect"] == pytest.approx(20 * 180.0 * (r1 - r0), abs=TOL)
    assert abs(aapl["fx_effect"]) < 0.01 * aapl["end_value"]


def _ledger_row(db_engine, *, day: str, currency: str, amount: float, code: str, tid: str) -> None:
    with db_engine.begin() as conn:
        ref = conn.execute(
            text(
                "SELECT l.broker_account_id, l.import_run_id FROM portfolio_cash_ledger_entries l "
                "JOIN broker_accounts ba ON ba.id = l.broker_account_id WHERE ba.legacy_account_id = :a LIMIT 1"
            ),
            {"a": IBKR},
        ).mappings().one()
        conn.execute(
            text(
                "INSERT INTO portfolio_cash_ledger_entries (broker_account_id, import_run_id, activity_date, currency, "
                "amount, activity_code, description, broker_activity_id, metadata_json, created_at) "
                "VALUES (:b, :r, :d, :c, :amt, :code, 'synthetic', :tid, '{}', '2026-03-12 00:00:00+00:00')"
            ),
            {"b": ref["broker_account_id"], "r": ref["import_run_id"], "d": day, "c": currency, "amt": amount,
             "code": code, "tid": tid},
        )


def test_new_money_counts_deposits_from_outside_only(mid: TestClient, db_engine):
    # A deposit from outside the household's accounts: new money.
    _ledger_row(db_engine, day="2026-03-10", currency="USD", amount=1000.0, code="DEP", tid="SYN-DEP-1")
    # A deposit funded from the DBS account two days earlier: a move inside net worth.
    _ledger_row(db_engine, day="2026-03-11", currency="SGD", amount=2000.0, code="DEP", tid="SYN-DEP-2")
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions (ts, account_id, amount, type, currency, category, merchant_counterparty) "
                "VALUES ('2026-03-09 09:00:00+00:00', :a, -2000, 'TRANSFER', 'SGD', 'Transfer', 'To broker')"
            ),
            {"a": DBS_SAVINGS},
        )
    bridge = _bridge(mid, "2026-03")
    _assert_adds_up(bridge, "new money")
    new_money = _line(bridge, "new_money")
    assert new_money["amount"] == pytest.approx(1000.0 * fx(date(2026, 3, 10), "USD"), abs=TOL)
    assert _part(new_money, "deposits") == pytest.approx(new_money["amount"], abs=TOL)
    internal = next(note for note in new_money["notes"] if note["key"] == "internal_transfers")
    assert internal["amount"] == pytest.approx(2000.0, abs=TOL)
    # The transfer out of DBS isn't spending.
    assert _part(_line(bridge, "cash_kept"), "spending") == pytest.approx(
        -(2500.0 + 300.0 * fx(date(2026, 3, 15), "USD") + 660.0 + 310.55), abs=TOL
    )


def test_no_baseline_still_adds_up(client: TestClient, db_engine, monkeypatch):
    """The household's first month: nothing at the start, so everything is a change
    from zero, and the start says it has no data (#224)."""
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    bridge = _bridge(client, "2025-12")
    _assert_adds_up(bridge, "no baseline")
    assert bridge["start"]["baseline_missing"] is True and bridge["start"]["value"] == 0.0


def _holding(quantity: float | None, price: float | None, value: float, fx_rate: float | None = None) -> _Holding:
    return _Holding(("STOCK", 1), 1, "X", "X", "STOCK", "P", 1, quantity, price, value, fx_rate)


def test_split_is_exact():
    start, end = _holding(10, 100.0, 1000.0 * 1.30), _holding(12, 110.0, 1320.0 * 1.35)
    split = _split(start, end)
    assert split.price == pytest.approx(10 * 10 * 1.35)
    assert split.fx == pytest.approx(10 * 100 * 0.05)
    assert split.quantity == pytest.approx(2 * 110 * 1.35)
    assert split.gap == pytest.approx(0.0, abs=1e-9)
    assert split.total == pytest.approx(end.value - start.value)
    # New and sold holdings are all quantity; one without a price can't be split.
    assert _split(None, end).quantity == end.value
    assert _split(start, None).quantity == -start.value
    no_price = _split(_holding(10, None, 500.0), end)
    assert no_price.quantity == pytest.approx(2 * 110 * 1.35)
    assert no_price.unsplit == pytest.approx(end.value - 500.0 - 2 * 110 * 1.35)
    # Neither side priced (or a quantity missing): nothing can be split.
    assert _split(_holding(10, None, 500.0), _holding(12, None, 700.0)).unsplit == pytest.approx(200.0)
    assert _split(_holding(None, 100.0, 500.0), end).unsplit == pytest.approx(end.value - 500.0)
    # Priced on one side only: the change in quantity is split at that side's price
    # and rate; the unpriced side's value is what can't be split.
    unpriced = _holding(5, 0.0, 0.0)
    bought = _holding(60, 80.0, 60 * 80.0 * 1.3)
    split = _split(unpriced, bought)
    assert split.quantity == pytest.approx(55 * 80.0 * 1.3)
    assert split.unsplit == pytest.approx(5 * 80.0 * 1.3)
    assert split.total == pytest.approx(bought.value)
    lost = _split(_holding(2, 0.25, 0.5), _holding(2, 0.0, 0.0))
    assert (lost.quantity, lost.unsplit) == pytest.approx((0.0, -0.5))
    # A value that doesn't match its quantity x price (over 1% from the stored rate):
    # the stored rate splits it, and the mismatch is a gap, not FX.
    odd = _holding(10, 100.0, 970.0, fx_rate=1.0)
    same = _holding(10, 110.0, 1100.0, fx_rate=1.0)
    split = _split(odd, same)
    assert (split.price, split.fx, split.quantity) == pytest.approx((100.0, 0.0, 0.0))
    assert split.gap == pytest.approx(30.0)
