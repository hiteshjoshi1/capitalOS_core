"""#408: U9 (crypto change split into price / quantity / FX), U10 (stablecoin and wrapped
tags), U3 ("Since your last visit")."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.auth_context import CurrentUser
from app.crypto.token_kinds import is_stablecoin, wrapped_of
from app.models.last_visit import UserLastVisit
from app.services import last_visit


def _seed_wallet(db_engine) -> None:
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets (id, chain_type, chain, address, status, created_at, user_id)
                VALUES ('w-408', 'evm', 'ethereum', '0x408', 'active', :now, 1)
                """
            ),
            {"now": datetime(2026, 5, 23, tzinfo=timezone.utc)},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd)
                VALUES
                  (40801, 'w-408', '2026-05-01', '2026-05-01T00:00:00+00:00', 3500),
                  (40802, 'w-408', '2026-05-23', '2026-05-23T00:00:00+00:00', 5900)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                  (snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, price_usd, value_usd)
                VALUES
                  (40801, 'evm', 'ethereum', 'native', 'ETH', 2, 1500, 3000),
                  (40801, 'evm', 'ethereum', 'erc20', 'USDC', 500, 1, 500),
                  (40802, 'evm', 'ethereum', 'native', 'ETH', 3, 1800, 5400),
                  (40802, 'evm', 'ethereum', 'erc20', 'USDC', 500, 1, 500)
                """
            )
        )


def test_crypto_change_split_into_price_and_quantity(client: TestClient, db_engine):
    _seed_wallet(db_engine)
    body = client.get("/crypto/summary?month=2026-05&base_currency=USD").json()
    eth = next(h for h in body["top_holdings"] if h["symbol"] == "ETH")
    change = eth["month_change"]
    # 2 ETH at 1,500 -> 3 ETH at 1,800: price = 2 x 300 = 600, quantity = 1 x 1,800 = 1,800.
    assert change["abs"] == pytest.approx(2400.0)
    assert change["price_effect"] == pytest.approx(600.0)
    assert change["quantity_effect"] == pytest.approx(1800.0)
    assert change["fx_effect"] == pytest.approx(0.0)
    assert change["unsplit"] == pytest.approx(0.0)
    assert change["abs"] == pytest.approx(eth["value_change_base"])
    assert change["side"] == "held"
    assert change["compare_month"] == "2026-04"
    assert change["start_quantity"] == 2 and change["end_quantity"] == 3

    usdc = next(h for h in body["top_holdings"] if h["symbol"] == "USDC")
    assert usdc["is_stablecoin"] is True and eth["is_stablecoin"] is False
    assert usdc["month_change"]["abs"] == pytest.approx(0.0)


def test_a_new_token_is_all_quantity(client: TestClient, db_engine):
    _seed_wallet(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                  (snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, price_usd, value_usd)
                VALUES (40802, 'evm', 'ethereum', 'erc20', 'WBTC', 0.01, 60000, 600)
                """
            )
        )
    body = client.get("/crypto/summary?month=2026-05&base_currency=USD").json()
    wbtc = next(h for h in body["top_holdings"] if h["symbol"] == "WBTC")
    assert wbtc["wrapped_of"] == "BTC"
    assert wbtc["month_change"]["side"] == "new"
    assert wbtc["month_change"]["quantity_effect"] == pytest.approx(600.0)
    assert wbtc["month_change"]["price_effect"] == pytest.approx(0.0)


def test_token_kinds():
    assert is_stablecoin("usdc") and is_stablecoin("DAI") and not is_stablecoin("ETH")
    assert wrapped_of("WETH", "ethereum") == "ETH"
    assert wrapped_of("cbBTC", "base") == "BTC"
    assert wrapped_of("BTC", "ethereum") == "BTC"
    assert wrapped_of("BTC", "bitcoin") is None
    assert wrapped_of("BTC", "coinbase") is None  # an exchange balance is the coin itself
    assert wrapped_of("SOL", "solana") is None
    assert wrapped_of("stETH", "ethereum") is None  # liquid staking, not wrapped
    assert wrapped_of("ETH", "ethereum") is None


@pytest.fixture
def stub_net_worth(monkeypatch):
    values = {"now": 1000.0}

    def fake(db, user_id, base_currency):
        from decimal import Decimal

        return Decimal(str(values["now"]))

    monkeypatch.setattr(last_visit, "live_net_worth", fake)
    return values


def test_first_visit_has_no_strip(client: TestClient, stub_net_worth):
    body = client.get("/dashboard/since-last-visit?base_currency=SGD").json()
    assert body["first_visit"] is True


def test_since_last_visit_change_and_mark(client: TestClient, db_engine, stub_net_worth):
    assert client.post("/dashboard/visit?base_currency=SGD").json()["moved"] is True
    stub_net_worth["now"] = 1250.0
    body = client.get("/dashboard/since-last-visit?base_currency=SGD").json()
    assert body["first_visit"] is False
    assert body["net_worth_then"] == pytest.approx(1000.0)
    assert body["change"] == pytest.approx(250.0)
    assert body["imports_since"] == 0
    # A second visit within the hour keeps the mark (a reload shows the same comparison) ...
    assert client.post("/dashboard/visit?base_currency=SGD").json()["moved"] is False
    assert client.get("/dashboard/since-last-visit?base_currency=SGD").json()["change"] == pytest.approx(250.0)
    # ... Dismiss moves it now.
    assert client.post("/dashboard/visit?base_currency=SGD&force=true").json()["moved"] is True
    assert client.get("/dashboard/since-last-visit?base_currency=SGD").json()["change"] == pytest.approx(0.0)


def test_another_base_currency_is_not_compared(client: TestClient, stub_net_worth):
    client.post("/dashboard/visit?base_currency=SGD")
    body = client.get("/dashboard/since-last-visit?base_currency=USD").json()
    assert body["change"] is None and body["currency_changed"] is True


def test_visit_mark_moves_after_the_gap(db_engine, stub_net_worth):
    Session = sessionmaker(bind=db_engine)
    with Session() as db:
        user = CurrentUser(id=1, username="test")
        assert db.get(UserLastVisit, 1) is None  # conftest clears it between tests
        t0 = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)
        assert last_visit.mark_visit(db, user, "SGD", now=t0)["moved"] is True
        assert last_visit.mark_visit(db, user, "SGD", now=t0 + timedelta(minutes=30))["moved"] is False
        assert last_visit.mark_visit(db, user, "SGD", now=t0 + timedelta(hours=2))["moved"] is True
        assert db.get(UserLastVisit, 1).net_worth is not None
