"""#329 (D-81): an account whose starting figure is older than the period gets a
Catch-up part: its change over the period that belongs to earlier months.

Synthetic numbers only. The household (tests/valuation_household.py) has HSBC's
balance on 20 Feb and 10 Mar, so March's start (1 Mar) uses a balance 9 days old.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.valuation import bridge as b
from app.valuation.bridge import _Holding
from tests.valuation_household import DBS_SAVINGS, HSBC_USD, SCENARIOS, build_scenario, household_env

START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)


def _cash(monkeypatch, start: dict[int, tuple[float, date, str]], end: dict[int, tuple[float, date, str]],
          rows: dict[int, float]) -> None:
    def fake_cash(_db, anchor, _base, _uid):
        return start if anchor == START else end

    monkeypatch.setattr(b, "_cash_by_account", fake_cash)
    monkeypatch.setattr(b, "_period_cash_by_account", lambda *_a, **_k: rows)


def test_a_stale_balance_keeps_the_change_less_this_periods_own_transactions(monkeypatch):
    # Balance on 4 Jul (stale for a 1 Nov start), newer balance on 7 Nov; 300 of
    # November's own transactions are already in the period's lines.
    _cash(monkeypatch,
          start={1: (10_000.0, date(2026, 7, 4), "balance")},
          end={1: (12_500.0, date(2026, 11, 7), "balance")},
          rows={1: 300.0})
    [catch_up] = b.cash_catch_up(None, 1, "SGD", START, END, names={1: "Bank"})
    assert catch_up.amount == pytest.approx(2_500.0 - 300.0)
    assert catch_up.kind == "cash" and catch_up.since == date(2026, 7, 4) and catch_up.until == date(2026, 11, 7)
    assert catch_up.label == "Bank: balance of 4 Jul → 7 Nov"


@pytest.mark.parametrize("case,start,end", [
    ("recent start", (1_000.0, date(2026, 10, 28), "balance"), (1_200.0, date(2026, 11, 7), "balance")),
    ("no newer balance", (1_000.0, date(2026, 7, 4), "balance"), (1_000.0, date(2026, 7, 4), "balance")),
    ("an IBKR NAV's cash", (1_000.0, date(2026, 7, 4), "nav"), (1_200.0, date(2026, 11, 7), "nav")),
])
def test_no_catch_up(monkeypatch, case: str, start: Any, end: Any):
    _cash(monkeypatch, start={1: start}, end={1: end}, rows={1: 50.0})
    assert b.cash_catch_up(None, 1, "SGD", START, END) == [], case


def test_ledger_covered_accounts_are_skipped(monkeypatch):
    _cash(monkeypatch, start={1: (1_000.0, date(2026, 7, 4), "balance")},
          end={1: (2_000.0, date(2026, 11, 7), "balance")}, rows={})
    assert b.cash_catch_up(None, 1, "SGD", START, END, skip_accounts={1}) == []


def _holding(account_id: int, symbol: str, as_of: date, quantity: float = 1.0) -> _Holding:
    return _Holding(mover_key=("STOCK", symbol), asset_id=None, symbol=symbol, name=None, asset_class="STOCK",
                    platform="BROKER", account_id=account_id, quantity=quantity, price=10.0, value=10.0 * quantity,
                    as_of=as_of)


def test_holdings_statements_older_than_the_period_are_stale():
    start = {
        (7, None, "A"): _holding(7, "A", date(2026, 8, 29)),   # old statement, newer one at the end
        (8, None, "B"): _holding(8, "B", date(2026, 10, 30)),  # recent statement
        (9, None, "C"): _holding(9, "C", date(2026, 8, 29)),   # old, and no newer statement
    }
    end = {
        (7, None, "A"): _holding(7, "A", date(2026, 11, 7), 3.0),
        (7, None, "N"): _holding(7, "N", date(2026, 11, 7)),
        (8, None, "B"): _holding(8, "B", date(2026, 11, 7), 2.0),
        (9, None, "C"): _holding(9, "C", date(2026, 8, 29)),
    }
    assert b.stale_holdings_accounts(start, end, date(2026, 11, 1)) == {7: (date(2026, 8, 29), date(2026, 11, 7))}


@pytest.fixture
def mid(client: TestClient, db_engine, monkeypatch):
    household_env(monkeypatch, SCENARIOS["mid"])
    build_scenario(db_engine, "mid")
    return client


def test_household_march_catch_up_is_hsbc_only_and_adds_up(mid: TestClient):
    """March 2026 (live 18 Mar): HSBC's start is its 20 Feb balance (9 days old), DBS's
    its 26 Feb one (3 days: not stale), Sharekhan's holdings its 28 Feb statement."""
    resp = mid.get("/dashboard/month-bridge?month=2026-03&base_currency=SGD")
    assert resp.status_code == 200, resp.text
    bridge = resp.json()
    catch_up = next(line for line in bridge["lines"] if line["key"] == "catch_up")
    assert [part["key"] for part in catch_up["parts"]] == [f"cash:{HSBC_USD}"]
    assert "20 Feb → 10 Mar" in catch_up["parts"][0]["label"]
    assert f"cash:{DBS_SAVINGS}" not in {part["key"] for part in catch_up["parts"]}
    assert sum(p["amount"] for p in catch_up["parts"]) == pytest.approx(catch_up["amount"], abs=1e-6)
    total = bridge["start"]["value"] + sum(line["amount"] for line in bridge["lines"]) + bridge["unexplained"]["amount"]
    assert total == pytest.approx(bridge["end"]["value"], abs=1e-6)
    # Moved out of Unexplained, not double counted: the residual is the change less every line.
    assert bridge["unexplained"]["amount"] == pytest.approx(
        bridge["change"] - sum(line["amount"] for line in bridge["lines"]), abs=1e-6)
