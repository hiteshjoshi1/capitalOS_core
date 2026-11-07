"""Why the headline moved (#289): the data causes behind a period's change.

Each cause on the pure classifier (``classify``), with hand-built holdings and accounts,
plus the "none" case; then the month bridge returns them on the synthetic household.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

import pytest
from fastapi.testclient import TestClient

from app.valuation.bridge import _Holding
from app.valuation.move_causes import CATCH_UP_DAYS, NONE_REASON, _Account, classify
from tests.valuation_household import SCENARIOS, build_scenario, household_env

START = date(2026, 10, 1)
NAMES = {1: "Synthetic Broker", 2: "Synthetic Savings", 3: "Synthetic New Bank"}


def _h(symbol: str, value: float, *, account: Optional[int] = 1, qty: Optional[float] = 10.0, price: Optional[float] = None,
       as_of: date = date(2026, 10, 31), fallback: Optional[str] = None) -> _Holding:
    return _Holding(
        mover_key=("STOCK", symbol), asset_id=None, symbol=symbol, name=symbol, asset_class="STOCK", platform="IBKR",
        account_id=account, quantity=qty, price=price if price is not None else (value / qty if qty else None),
        value=value, fx_rate=1.0, price_currency="SGD", as_of=as_of, fallback_reason=fallback,
    )


def _acct(value: float, as_of: Optional[date]) -> _Account:
    a = _Account()
    a.value = value
    a.as_of = as_of
    return a


def _run(start_total: float, end_total: float, *, start_accounts: dict, end_accounts: dict,
         start_holdings: list = (), end_holdings: list = (), fx_flags: Optional[dict] = None,
         baseline_missing: bool = False) -> dict[str, Any]:
    return classify(
        start_total=start_total, end_total=end_total, start_accounts=start_accounts, end_accounts=end_accounts,
        start_holdings=list(start_holdings), end_holdings=list(end_holdings), names=NAMES,
        fx_flags=fx_flags or {}, baseline_missing=baseline_missing, period_start=START,
    )


def _keys(result: dict[str, Any]) -> list[str]:
    return [c["key"] for c in result["causes"]]


def test_first_statement_is_sized_at_its_whole_value():
    r = _run(100_000, 160_000,
             start_accounts={2: _acct(100_000, date(2026, 9, 30))},
             end_accounts={2: _acct(100_000, date(2026, 9, 30)), 3: _acct(60_000, date(2026, 10, 31))})
    assert _keys(r) == ["first_statement"]
    cause = r["causes"][0]
    assert cause["amount"] == pytest.approx(60_000)
    assert cause["significant"] and cause["account_id"] == 3 and "Synthetic New Bank" in cause["label"]
    assert r["is_big_move"] and r["change_pct"] == pytest.approx(60.0)
    assert r["none_reason"] is None


def test_catch_up_names_the_gap_and_leaves_the_market_out():
    # The broker's statement jumps 92 days; its one holding gained 5,000 on price, and
    # 20,000 of cash/positions changed besides: the cause is the 20,000.
    start_h = _h("AAA", 50_000, qty=100, as_of=date(2026, 7, 31))
    end_h = _h("AAA", 55_000, qty=100, as_of=date(2026, 10, 31))
    r = _run(100_000, 125_000,
             start_accounts={1: _acct(50_000 + 50_000, date(2026, 7, 31))},
             end_accounts={1: _acct(55_000 + 70_000, date(2026, 10, 31))},
             start_holdings=[start_h], end_holdings=[end_h])
    assert _keys(r) == ["catch_up"]
    cause = r["causes"][0]
    assert cause["amount"] == pytest.approx(20_000)
    assert f"{(date(2026, 10, 31) - date(2026, 7, 31)).days} days" in cause["detail"]
    assert "(31 Jul 2026 to 31 Oct 2026)" in cause["detail"]
    assert (date(2026, 10, 31) - date(2026, 7, 31)).days > CATCH_UP_DAYS


def test_a_new_statement_counts_only_when_large_and_not_the_market():
    # A monthly statement whose change is all price: no cause.
    r = _run(100_000, 104_000,
             start_accounts={1: _acct(100_000, date(2026, 9, 30))},
             end_accounts={1: _acct(104_000, date(2026, 10, 31))},
             start_holdings=[_h("AAA", 100_000, qty=100, as_of=date(2026, 9, 30))],
             end_holdings=[_h("AAA", 104_000, qty=100)])
    assert _keys(r) == []
    # A cash statement that moved 30,000 (a large transfer in): a cause.
    r = _run(100_000, 130_000,
             start_accounts={2: _acct(100_000, date(2026, 9, 30))},
             end_accounts={2: _acct(130_000, date(2026, 10, 31))})
    assert _keys(r) == ["statement"]
    assert r["causes"][0]["amount"] == pytest.approx(30_000) and r["causes"][0]["significant"]


def test_new_position_in_an_existing_account():
    r = _run(100_000, 140_000,
             start_accounts={1: _acct(100_000, date(2026, 10, 31))},
             end_accounts={1: _acct(140_000, date(2026, 10, 31))},
             start_holdings=[_h("AAA", 100_000)],
             end_holdings=[_h("AAA", 100_000), _h("NEWCO", 40_000)])
    assert _keys(r) == ["new_position"]
    assert r["causes"][0]["label"] == "New position: NEWCO" and r["causes"][0]["amount"] == pytest.approx(40_000)


def test_fx_gap_has_no_size_and_is_always_significant():
    r = _run(100_000, 101_000, start_accounts={}, end_accounts={}, fx_flags={"fx_missing_currencies": ["HKD", "USD"]})
    assert _keys(r) == ["fx_gap"]
    cause = r["causes"][0]
    assert cause["amount"] is None and cause["significant"] and "HKD, USD" in cause["label"]
    assert not r["is_big_move"]


def test_price_fallback_is_context_not_a_cause():
    r = _run(100_000, 100_500,
             start_accounts={1: _acct(100_000, date(2026, 10, 31))},
             end_accounts={1: _acct(100_500, date(2026, 10, 31))},
             start_holdings=[_h("AAA", 100_000)],
             end_holdings=[_h("AAA", 100_500, fallback="no_quote")])
    assert _keys(r) == ["price_fallback"]
    assert not r["causes"][0]["significant"] and r["causes"][0]["amount"] == pytest.approx(100_500)


def test_a_big_move_with_no_data_cause_says_so():
    r = _run(100_000, 112_000,
             start_accounts={1: _acct(100_000, date(2026, 10, 31))},
             end_accounts={1: _acct(112_000, date(2026, 10, 31))},
             start_holdings=[_h("AAA", 100_000, qty=100)],
             end_holdings=[_h("AAA", 112_000, qty=100)])
    assert r["is_big_move"] and _keys(r) == []
    assert r["none_reason"] == NONE_REASON
    # A small move with no cause says nothing.
    small = _run(100_000, 101_000, start_accounts={}, end_accounts={})
    assert not small["is_big_move"] and small["none_reason"] is None


def test_no_baseline_is_never_a_big_move():
    r = _run(0, 50_000, start_accounts={}, end_accounts={2: _acct(50_000, date(2026, 10, 31))}, baseline_missing=True)
    assert r["change_pct"] is None and not r["is_big_move"]
    assert _keys(r) == ["first_statement"]


def test_significant_causes_come_first():
    r = _run(100_000, 170_000,
             start_accounts={1: _acct(100_000, date(2026, 10, 31))},
             end_accounts={1: _acct(110_000, date(2026, 10, 31)), 3: _acct(60_000, date(2026, 10, 31))},
             start_holdings=[_h("AAA", 100_000)],
             end_holdings=[_h("AAA", 110_000, fallback="quote_older")],
             fx_flags={"fx_missing_currencies": ["USD"]})
    assert [c["significant"] for c in r["causes"]] == sorted((c["significant"] for c in r["causes"]), reverse=True)
    assert _keys(r)[-1] == "price_fallback"


def test_the_month_bridge_returns_the_causes(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    resp = client.get("/dashboard/month-bridge?month=2026-03&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    causes = resp.json()["move_causes"]
    assert set(causes) >= {"change", "change_pct", "is_big_move", "causes", "none_reason"}
    assert causes["change"] == pytest.approx(resp.json()["change"], abs=1e-6)
    for cause in causes["causes"]:
        assert cause["key"] in {"first_statement", "catch_up", "statement", "new_position", "fx_gap", "price_fallback"}
        assert cause["label"]
