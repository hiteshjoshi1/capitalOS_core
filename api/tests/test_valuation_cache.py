"""Valuation caching (#147): same answers with and without the caches, fresh
answers after a write, and never another user's data."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.valuation import clock as valuation_clock, fx as valuation_fx
from app import fx, valuation_cache
from app.valuation_cache import request_scope, valuation_cached
from tests.canonical_test_helpers import (
    seed_canonical_account_balance_for_test,
    seed_canonical_position_snapshot_for_test,
)


_NOW = datetime(2026, 3, 10, 18, 0, tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Singapore"))


@pytest.fixture()
def frozen_now(monkeypatch):
    """"Now" is 2026-03-10 18:00 SGT for live views: March is the open month,
    February closed. (Fixed, so cached and uncached responses carry the same
    live timestamps.)"""
    monkeypatch.setattr(valuation_clock, "_current_anchor_ts", lambda: _NOW)


@pytest.fixture()
def count_queries(db_engine):
    statements: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    event.listen(db_engine, "before_cursor_execute", _count)
    yield statements
    event.remove(db_engine, "before_cursor_execute", _count)


def _seed_extras(db_engine):
    """On top of seed_dashboard_data: a stablecoin snapshot, a credit card and a
    dividend-paying holding, so every cached path has something to compute."""
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(103, 101, 'evm', 'ethereum', 'token', 'USDC', 500, 500)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(40, 'Test Card', 'DBS', 'CREDIT_CARD', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO credit_card_accounts (id, account_id, card_name, issuer, credit_limit, statement_day, due_day) "
                "VALUES (40, 40, 'Test Card', 'DBS', 10000, 20, 25)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, category) VALUES "
                "(40, '2026-03-02 12:00:00+00:00', 40, -250, 'EXPENSE', 'SGD', 'Food')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO market_dividend_yields "
                "(asset_id, as_of_date, yield_rate, annual_dividend_per_share, price, currency, source, exchange_code, provider_symbol) "
                "VALUES (1, '2026-02-01', 0.02, 4, 200, 'USD', 'test', 'US', 'AAPL')"
            )
        )


ENDPOINTS = [
    "/dashboard/bootstrap?month=2026-03&base_currency=SGD",
    "/dashboard/summary?month=2026-03&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/summary?month=2026-02&base_currency=SGD&compare=prev_month,prev_year",
    "/dashboard/summary?month=2026-03&base_currency=SGD&skip_networth=true",
    "/dashboard/stock-holdings?month=2026-03&base_currency=SGD",
    "/dashboard/stock-holdings?month=2026-02&base_currency=SGD",
    "/dashboard/net-worth-since-update?base_currency=SGD",
    "/dashboard/net-worth-change?month=2026-03&base_currency=SGD",
    "/dashboard/geography-exposure?month=2026-03&base_currency=SGD",
    "/dashboard/cash-deposits?month=2026-03&base_currency=SGD",
    "/dashboard/platform-allocation?month=2026-03&base_currency=SGD",
    "/dashboard/stock-exposure?month=2026-03&base_currency=SGD",
    "/dashboard/net-worth-timeline/2026-02/movers?base_currency=SGD",
    "/dashboard/data-hub-summary",
    "/dividends/expected/overview?from_month=2026-01&to_month=2026-03&base_currency=SGD&assumed_tax_rate=0.1",
    "/spending/cash-flow-detail?month=2026-02&base_currency=SGD",
]


def test_responses_are_identical_with_and_without_caches(
    client: TestClient, seed_dashboard_data, db_engine, frozen_now, monkeypatch
):
    _seed_extras(db_engine)

    monkeypatch.setenv("VALUATION_CACHE_ENABLED", "0")
    uncached = {}
    for path in ENDPOINTS:
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.text)
        uncached[path] = resp.json()

    monkeypatch.setenv("VALUATION_CACHE_ENABLED", "1")
    valuation_cache.clear_shared_cache()
    cold = {path: client.get(path).json() for path in ENDPOINTS}  # fills the shared cache
    warm = {path: client.get(path).json() for path in ENDPOINTS}  # served from it
    assert valuation_cache.shared_cache.hits > 0
    for path in ENDPOINTS:
        assert cold[path] == uncached[path], path
        assert warm[path] == uncached[path], path


def test_second_request_reuses_cached_valuation(
    client: TestClient, seed_dashboard_data, frozen_now, count_queries
):
    path = "/dashboard/summary?month=2026-03&base_currency=SGD&compare=prev_month,prev_year"
    # The very first request fills fx_rates on demand (#139); that write rightly
    # invalidates the shared cache. Measure once the rates are stored.
    client.get(path)
    valuation_cache.clear_shared_cache()
    count_queries.clear()
    first = client.get(path)
    first_queries = len(count_queries)
    count_queries.clear()
    second = client.get(path)

    assert first.json() == second.json()
    assert len(count_queries) < first_queries / 2


def test_one_request_computes_each_valuation_once(
    client: TestClient, seed_dashboard_data, frozen_now, count_queries, monkeypatch
):
    """Within one request the same helper call is computed once (shared puts
    are disabled here, so this is the per-request layer alone)."""
    path = "/dashboard/stock-holdings?month=2026-03&base_currency=SGD"

    def position_reads() -> int:
        return sum(1 for s in count_queries if "flex_authority_accounts" in s)

    monkeypatch.setenv("VALUATION_CACHE_ENABLED", "0")
    uncached = client.get(path).json()
    uncached_reads = position_reads()
    uncached_queries = len(count_queries)
    count_queries.clear()

    monkeypatch.setenv("VALUATION_CACHE_ENABLED", "1")
    monkeypatch.setattr(valuation_cache.shared_cache, "put", lambda *_args, **_kwargs: None)
    memoised = client.get(path).json()

    assert memoised == uncached
    assert position_reads() < uncached_reads
    assert len(count_queries) < uncached_queries


def test_write_invalidates_cached_valuation(client: TestClient, seed_dashboard_data, db_engine, frozen_now):
    path = "/dashboard/cash-deposits?month=2026-03&base_currency=SGD"
    before = client.get(path).json()
    assert client.get(path).json() == before  # cached

    seed_canonical_account_balance_for_test(
        db_engine, account_id=1, as_of="2026-03-05", currency="SGD", balance_base=31000
    )

    after = client.get(path).json()
    assert after["current_total"] == pytest.approx(before["current_total"] + 1000)


def test_write_inside_a_request_is_seen_by_that_request(db_engine):
    with request_scope() as scope:
        scope.memo[("k",)] = "stale"
        scope.watermark = ("old", None)
        with Session(db_engine) as session:
            session.execute(text("UPDATE accounts SET name = name WHERE id = -1"))
            session.commit()
        assert scope.memo == {}
        assert scope.watermark is valuation_cache._MISSING


def test_read_only_commit_does_not_invalidate(db_engine):
    generation = valuation_cache.write_generation()
    with Session(db_engine) as session:
        session.execute(text("SELECT 1"))
        session.commit()
    assert valuation_cache.write_generation() == generation


def test_shared_cache_never_serves_another_users_data(client: TestClient, db_engine, frozen_now, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country, user_id) VALUES "
                "(71, 'User One Bank', 'DBS', 'BANK', 'SGD', 'SG', 71), "
                "(72, 'User Two Bank', 'OCBC', 'BANK', 'SGD', 'SG', 72)"
            )
        )
    seed_canonical_account_balance_for_test(db_engine, account_id=71, as_of="2026-03-01", currency="SGD", balance_base=1000)
    seed_canonical_account_balance_for_test(db_engine, account_id=72, as_of="2026-03-01", currency="SGD", balance_base=2000)
    path = "/dashboard/cash-deposits?month=2026-03&base_currency=SGD"

    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "71")
    first_user = client.get(path).json()
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "72")
    second_user = client.get(path).json()  # no write in between: same watermark
    monkeypatch.setenv("AUTH_BYPASS_USER_ID", "71")
    first_user_again = client.get(path).json()

    assert first_user["current_total"] == 1000.0
    assert second_user["current_total"] == 2000.0
    assert [item["source"] for item in second_user["items"]] == ["OCBC"]
    assert first_user_again == first_user


def test_shared_caching_requires_the_user_in_the_key():
    with pytest.raises(TypeError):

        @valuation_cached(shared=True)
        def _no_user(db, anchor_ts):  # noqa: ANN001
            return None


def test_nothing_is_cached_outside_a_request(db_engine):
    calls = []

    @valuation_cached(shared=True)
    def _helper(db, current_user_id):  # noqa: ANN001
        calls.append(current_user_id)
        return {"n": len(calls)}

    assert _helper(db_engine, 1) == {"n": 1}
    assert _helper(db_engine, 1) == {"n": 2}


def test_cached_values_are_copies():
    @valuation_cached()
    def _helper(db, key):  # noqa: ANN001
        return {"rows": [{"value": 1}]}

    with request_scope():
        first = _helper(None, "k")
        first["rows"][0]["value"] = 99
        assert _helper(None, "k") == {"rows": [{"value": 1}]}


def test_degraded_fx_result_is_not_shared(db_engine):
    calls = []

    @valuation_cached(shared=True)
    def _helper(db, current_user_id):  # noqa: ANN001
        calls.append(1)
        # XYZ resolves nowhere: left out and reported missing, never 1.0 (#139).
        return dict(fx.get_rates(datetime(2026, 3, 1, tzinfo=timezone.utc), "SGD", {"USD", "XYZ"}))

    with Session(db_engine) as session:
        with request_scope() as scope:
            assert "XYZ" not in _helper(session, 1)
            assert scope.degraded
        with request_scope():
            _helper(session, 1)
    assert len(calls) == 2  # the degraded result wasn't reused by the next request


# FX provider/caching tests moved to test_fx.py with the rate table (#139).


# ─── Batched reads (#147) ────────────────────────────────────────────────────


def test_expected_dividends_batched_reads_pick_latest_rows_per_asset(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(520, 'IBKR Main', 'IBKR', 'BROKER', 'USD', 'US')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO assets (id, symbol, name, asset_class, quote_currency, home_country) VALUES "
                "(920, 'AAA', 'Alpha', 'STOCK', 'USD', 'US'), "
                "(921, 'BBB', 'Beta', 'STOCK', 'USD', 'US')"
            )
        )
        # AAA: two yield snapshots (the later one at/before the anchor wins), one after it.
        # BBB: no price on the yield row, so the latest dated price is used.
        conn.execute(
            text(
                "INSERT INTO market_dividend_yields "
                "(asset_id, as_of_date, yield_rate, annual_dividend_per_share, price, currency, source, exchange_code, provider_symbol) VALUES "
                "(920, '2026-01-31', 0.01, 1, 100, 'USD', 'test', 'US', 'AAA'), "
                "(920, '2026-03-15', 0.02, 2, 100, 'USD', 'test', 'US', 'AAA'), "
                "(920, '2026-04-15', 0.09, 9, 100, 'USD', 'test', 'US', 'AAA'), "
                "(921, '2026-03-20', 0.05, 1, 0, 'USD', 'test', 'US', 'BBB')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO prices (id, asset_id, ts, price, currency, source, trade_date, exchange_code, provider_symbol) VALUES "
                "(920, 921, '2026-03-01T00:00:00+00:00', 40, 'USD', 'test', '2026-03-01', 'US', 'BBB'), "
                "(921, 921, '2026-03-30T00:00:00+00:00', 50, 'USD', 'test', '2026-03-30', 'US', 'BBB'), "
                "(922, 921, '2026-04-05T00:00:00+00:00', 99, 'USD', 'test', '2026-04-05', 'US', 'BBB')"
            )
        )
        # AAA's shares come from trades (8 - 3 = 5), BBB's from the snapshot (20).
        conn.execute(
            text(
                "INSERT INTO transactions (id, ts, account_id, amount, type, currency, asset_id, quantity) VALUES "
                "(920, '2026-01-10T00:00:00+00:00', 520, -800, 'BUY', 'USD', 920, 8), "
                "(921, '2026-02-10T00:00:00+00:00', 520, 300, 'SELL', 'USD', 920, 3), "
                "(922, '2026-04-10T00:00:00+00:00', 520, -100, 'BUY', 'USD', 920, 1)"
            )
        )
    for asset_id, quantity in ((920, 7), (921, 20)):
        seed_canonical_position_snapshot_for_test(
            db_engine,
            account_id=520,
            asset_id=asset_id,
            as_of="2026-03-06",
            quantity=quantity,
            market_value_base=1000,
            market_price=50,
            cost_basis_base=1000,
            currency="USD",
            platform_code="IBKR",
        )

    resp = client.get("/dividends/expected/overview?from_month=2026-03&to_month=2026-03&base_currency=USD")
    assert resp.status_code == 200
    companies = {row["symbol"]: row for row in resp.json()["companies"]}
    assert companies["AAA"]["shares"] == 5.0
    assert companies["AAA"]["yield_pct"] == pytest.approx(2.0)
    assert companies["AAA"]["yearly_dividend"] == pytest.approx(5 * 100 * 0.02)
    assert companies["BBB"]["shares"] == 20.0
    assert companies["BBB"]["price"] == 50.0
    assert companies["BBB"]["yearly_dividend"] == pytest.approx(20 * 50 * 0.05)


def test_cash_trend_stablecoins_use_each_months_latest_snapshot(client: TestClient, db_engine, monkeypatch):
    monkeypatch.setattr(valuation_fx, "get_rates", lambda _date, base, symbols: {base: 1.0, **{s: 1.0 for s in symbols}})
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, platform, account_type, currency, country) VALUES "
                "(530, 'DBS Savings', 'DBS', 'BANK', 'SGD', 'SG')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at) VALUES "
                "('w-a', 'evm', 'ethereum', '0xa', 'A', 'active', '2026-01-01'), "
                "('w-b', 'evm', 'base', '0xb', 'B', 'active', '2026-01-01'), "
                "('w-off', 'evm', 'base', '0xc', 'Off', 'inactive', '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) VALUES "
                "(531, 'w-a', '2026-02-10', '2026-02-10', 100), "
                "(532, 'w-a', '2026-03-10', '2026-03-10', 300), "
                "(533, 'w-b', '2026-03-12', '2026-03-12', 50), "
                "(534, 'w-off', '2026-03-12', '2026-03-12', 999)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshot_items "
                "(id, snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd) VALUES "
                "(531, 531, 'evm', 'ethereum', 'token', 'USDC', 100, 100), "
                "(532, 532, 'evm', 'ethereum', 'token', 'usdt', 250, 250), "
                "(533, 532, 'evm', 'ethereum', 'native', 'ETH', 1, 50), "
                "(534, 533, 'evm', 'base', 'token', 'USDC', 50, 50), "
                "(535, 534, 'evm', 'base', 'token', 'USDC', 999, 999)"
            )
        )
    for as_of in ("2026-02-01", "2026-03-01", "2026-04-01"):
        seed_canonical_account_balance_for_test(db_engine, account_id=530, as_of=as_of, currency="SGD", balance_base=1000)

    trend = {p["month"]: p["value"] for p in client.get("/dashboard/cash-deposits?month=2026-03").json()["trend"]}
    assert trend["2026-01"] == 1000.0  # anchor Feb 1: no wallet snapshot yet
    assert trend["2026-02"] == 1100.0  # anchor Mar 1: w-a's Feb snapshot
    assert trend["2026-03"] == 1300.0  # anchor Apr 1: w-a's Mar snapshot (USDT only) + w-b; w-off excluded


def test_concurrent_requests_compute_a_shared_value_once(db_engine):
    """Wealth Overview's /bootstrap and /summary run in parallel: the second
    request waits for the value the first is computing instead of redoing it."""
    import threading
    import time

    calls = []

    @valuation_cached(shared=True)
    def _slow(db, current_user_id):  # noqa: ANN001
        calls.append(current_user_id)
        time.sleep(0.2)
        return {"value": 42}

    results = []

    def _request():
        with Session(db_engine) as session, request_scope():
            results.append(_slow(session, 1))

    threads = [threading.Thread(target=_request) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [{"value": 42}] * 3
    assert calls == [1]
