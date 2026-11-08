"""#330 (D-82): a wallet or account first seen in the period is "Newly tracked", not
money moving; a rebasing staking token's small quantity growth is staking income.
Synthetic numbers only."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.valuation import bridge as b
from app.valuation.bridge import HoldingChange, _Holding, _split

START = datetime(2026, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)


def _token(symbol: str, quantity: float, price: float) -> _Holding:
    return _Holding(mover_key=("CRYPTO", symbol), asset_id=None, symbol=symbol, name=symbol, asset_class="CRYPTO",
                    platform="CRYPTO", account_id=None, quantity=quantity, price=price, value=quantity * price,
                    fx_rate=1.0, price_currency="USD")


def _change(start: _Holding | None, end: _Holding | None) -> HoldingChange:
    return HoldingChange(("CRYPTO", (start or end).symbol), start, end, _split(start, end))  # type: ignore[union-attr]


def test_steth_growth_is_staking_rewards():
    change = _change(_token("STETH", 10.0, 3000.0), _token("STETH", 10.03, 3000.0))
    assert b.staking_reward(change) == pytest.approx(0.03 * 3000.0)


@pytest.mark.parametrize("case,start,end", [
    ("a deposit, not rewards (over 2%)", _token("STETH", 10.0, 3000.0), _token("STETH", 12.0, 3000.0)),
    ("not a rebasing token", _token("ETH", 10.0, 3000.0), _token("ETH", 10.03, 3000.0)),
    ("quantity went down", _token("STETH", 10.0, 3000.0), _token("STETH", 9.9, 3000.0)),
    ("new at the end", None, _token("STETH", 1.0, 3000.0)),
])
def test_not_staking(case, start, end):
    assert b.staking_reward(_change(start, end)) == 0.0, case


def test_a_cash_account_first_seen_in_the_period(monkeypatch):
    def fake_cash(_db, anchor, _base, _uid):
        if anchor == START:
            return {1: (500.0, date(2026, 10, 30), "balance")}
        return {1: (600.0, date(2026, 11, 7), "balance"), 2: (2_000.0, date(2026, 11, 5), "balance"),
                3: (900.0, date(2026, 11, 5), "nav")}

    monkeypatch.setattr(b, "_cash_by_account", fake_cash)
    monkeypatch.setattr(b, "_period_cash_by_account", lambda *_a, **_k: {1: 100.0, 2: 150.0})
    [new] = b.newly_tracked_cash(None, 1, "SGD", START, END, names={2: "New bank"})
    assert new.key == "cash:2" and new.label == "New bank: first balance 5 Nov"
    assert new.amount == pytest.approx(2_000.0 - 150.0)  # its own November transactions are in the lines


def test_holdings_accounts_with_no_start_holdings_are_new():
    def h(account: int) -> _Holding:
        return _Holding(mover_key=("STOCK", "X"), asset_id=None, symbol="X", name=None, asset_class="STOCK",
                        platform="BROKER", account_id=account, quantity=1.0, price=1.0, value=1.0)

    assert b.newly_tracked_holdings_accounts({(1, None, "X"): h(1)}, {(1, None, "X"): h(1), (2, None, "X"): h(2)}) == {2}


def test_a_wallet_first_seen_in_the_period(monkeypatch):
    monkeypatch.setattr(b, "new_wallets", lambda *_a: {"w2": ("Solana wallet", date(2026, 11, 5))})
    monkeypatch.setattr(b, "_wallet_valuation", lambda *_a, **_k: {"items": [
        {"wallet_id": "w1", "symbol": "ETH", "value_usd": 1_000.0},
        {"wallet_id": "w2", "symbol": "SOL", "value_usd": 400.0},
        {"wallet_id": "w2", "symbol": "USDC", "value_usd": 100.0},
    ]})
    monkeypatch.setattr(b.fx, "get_rates", lambda *_a, **_k: {"USD": 1.3})
    [wallet] = b.newly_tracked_wallets(None, 1, "SGD", START, END, live=True)
    assert wallet.key == "wallet:w2" and wallet.label == "Solana wallet: first seen 5 Nov"
    assert wallet.amount == pytest.approx(500.0 * 1.3)
    assert [symbol for symbol, _v in wallet.detail] == ["SOL", "USDC"]
