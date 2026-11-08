"""#331: past crypto prices. Carry within CARRY_DAYS at valuation time; back-fill from
DefiLlama's historical prices (always mocked here); an unpriced item adds no quantity
in the bridge. Synthetic wallets and tokens only."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crypto import price_backfill as pb
from app.crypto.valuation import latest_wallet_valuation
from app.valuation import bridge as b
from tests.auth_helpers import ensure_user, signed_in_client

USER = 1
OTHER = 2
STETH = "0xae7ab96520de3a18e5e111b5eaab095312d7fe84"
SPAM = "0x209ba0deaa26f5f95acd2110de7ce3bd01bd1258"


def _seed(engine, rows, *, wallet="w-a", user=USER, chain="ethereum"):
    """rows: (snapshot_id, as_of_date, [(symbol, kind, contract, qty, price)])"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, status, created_at, user_id) "
                "VALUES (:w, 'evm', :c, :a, 'active', '2026-01-01T00:00:00+00:00', :u)"
            ),
            {"w": wallet, "c": chain, "a": f"0x{wallet}", "u": user},
        )
        for sid, day, items in rows:
            total = sum(q * p for _s, _k, _c, q, p in items if p is not None)
            conn.execute(
                text(
                    "INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd) "
                    "VALUES (:id, :w, :d, :f, :t)"
                ),
                {"id": sid, "w": wallet, "d": day, "f": f"{day}T00:00:00+00:00", "t": total},
            )
            for symbol, kind, contract, qty, price in items:
                conn.execute(
                    text(
                        "INSERT INTO crypto_wallet_snapshot_items (snapshot_id, chain_type, chain, asset_kind, "
                        "contract_or_mint, symbol, normalized_amount, price_usd, value_usd) "
                        "VALUES (:s, 'evm', :c, :k, :ct, :sym, :q, :p, :v)"
                    ),
                    {"s": sid, "c": chain, "k": kind, "ct": contract, "sym": symbol, "q": qty, "p": price,
                     "v": None if price is None else qty * price},
                )


def _items(engine, snapshot_id):
    with engine.connect() as conn:
        return {
            r.symbol: (r.price_usd, r.value_usd, r.price_source)
            for r in conn.execute(
                text("SELECT symbol, price_usd, value_usd, price_source FROM crypto_wallet_snapshot_items WHERE snapshot_id = :s"),
                {"s": snapshot_id},
            )
        }


# ─── keys ────────────────────────────────────────────────────────────────────


def test_token_key_and_coin_id():
    native = {"chain": "ethereum", "symbol": "eth", "contract_or_mint": None}
    erc20 = {"chain": "ethereum", "symbol": "stETH", "contract_or_mint": STETH.upper().replace("0X", "0x")}
    mint = {"chain": "solana", "symbol": "JUP", "contract_or_mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"}
    assert pb.token_key(native) == ("ethereum", "native:ETH")
    assert pb.coin_id(native) == "coingecko:ethereum"
    assert pb.coin_id(erc20) == f"ethereum:{STETH}"
    assert pb.coin_id(mint) == "solana:JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    assert pb.coin_id({"chain": "ethereum", "symbol": "XYZ", "contract_or_mint": None}) is None


# ─── carry at valuation time ─────────────────────────────────────────────────


def test_carry_uses_the_newest_earlier_price_within_the_window(db_engine):
    _seed(db_engine, [
        (9501, "2026-10-25", [("ETH", "native", None, 1.0, 2000.0)]),
        (9502, "2026-10-28", [("ETH", "native", None, 1.0, 2100.0)]),
        (9503, "2026-10-30", [("ETH", "native", None, 2.0, None)]),   # no price this day
        (9504, "2026-11-02", [("ETH", "native", None, 2.0, 2500.0)]),  # later: never used for 30 Oct
    ])
    with Session(db_engine) as db:
        val = latest_wallet_valuation(db, USER, as_of_date=date(2026, 10, 30))
    (eth,) = [i for i in val["items"] if i["symbol"] == "ETH"]
    assert eth["price_usd"] == 2100.0
    assert eth["value_usd"] == pytest.approx(4200.0)
    assert eth["price_source"] == "carried:2026-10-28"
    assert val["total_usd"] == pytest.approx(4200.0)


def test_no_carry_beyond_the_window_or_for_a_token_never_priced(db_engine):
    _seed(db_engine, [
        (9511, "2026-10-01", [("ETH", "native", None, 1.0, 2000.0)]),
        (9512, "2026-10-30", [("ETH", "native", None, 1.0, None), ("SOL", "erc20", SPAM, 5.0, None)]),
    ])
    with Session(db_engine) as db:
        val = latest_wallet_valuation(db, USER, as_of_date=date(2026, 10, 30))
    by = {i["symbol"]: i for i in val["items"]}
    assert by["ETH"]["price_usd"] is None  # 29 days earlier: outside CARRY_DAYS
    assert by["SOL"]["price_usd"] is None
    assert val["total_usd"] == 0


def test_carry_never_reads_another_users_wallets(db_engine):
    ensure_user(db_engine, OTHER)
    _seed(db_engine, [(9521, "2026-10-29", [("ETH", "native", None, 1.0, 2000.0)])], wallet="w-other", user=OTHER)
    _seed(db_engine, [(9522, "2026-10-30", [("ETH", "native", None, 1.0, None)])])
    with Session(db_engine) as db:
        val = latest_wallet_valuation(db, USER, as_of_date=date(2026, 10, 30))
    assert [i["price_usd"] for i in val["items"]] == [None]


# ─── bridge: an unpriced item adds no quantity ───────────────────────────────


def test_unpriced_token_with_the_same_symbol_does_not_skew_the_price(monkeypatch):
    # The real case: 5 unpriced ERC-20 "SOL" next to 56.86 real SOL. Summing quantities by symbol
    # gave 61.86 SOL "worth" the real wallet's value, a phantom unsplit part.
    valuation = {"total_usd": 5000.0, "items": [
        {"symbol": "SOL", "normalized_amount": 5.0, "value_usd": None},
        {"symbol": "SOL", "normalized_amount": 50.0, "value_usd": 5000.0},
    ]}
    monkeypatch.setattr(b, "_wallet_valuation", lambda *a, **k: valuation)
    monkeypatch.setattr(b.fx, "get_rates", lambda *a, **k: {"USD": 1.0})
    holdings, _total = b._crypto_holdings(None, datetime(2026, 11, 1, tzinfo=timezone.utc), "USD", USER, live=False)
    sol = holdings[("CRYPTO", "SOL")]
    assert sol.quantity == pytest.approx(50.0)
    assert sol.price == pytest.approx(100.0)


# ─── back-fill ───────────────────────────────────────────────────────────────


def _backfill_seed(engine):
    _seed(engine, [
        (9531, "2026-11-05", [("stETH", "erc20", STETH, 2.0, 2200.0), ("ETH", "native", None, 1.0, 2210.0)]),
        (9532, "2026-11-06", [("stETH", "erc20", STETH, 2.0, None), ("ETH", "native", None, 1.0, None),
                              ("SOL", "erc20", SPAM, 5.0, None)]),
        (9533, "2026-11-07", [("stETH", "erc20", STETH, 2.0, None)]),
    ])


def test_plan_targets_unpriced_items_of_known_tokens_newest_first(db_engine):
    _backfill_seed(db_engine)
    with Session(db_engine) as db:
        plan = pb.plan_backfill(db, USER)
    assert [(d.isoformat(), sorted(c)) for d, c in plan.requests] == [
        ("2026-11-07", [f"ethereum:{STETH}"]),
        ("2026-11-06", ["coingecko:ethereum", f"ethereum:{STETH}"]),
    ]
    assert plan.items == 3
    assert plan.skipped_unknown_tokens == 1  # the spam "SOL": no provider ever priced it


def test_plan_is_capped(db_engine, monkeypatch):
    _backfill_seed(db_engine)
    monkeypatch.setenv("CRYPTO_PRICE_BACKFILL_MAX_REQUESTS", "1")
    with Session(db_engine) as db:
        plan = pb.plan_backfill(db, USER)
    assert [d.isoformat() for d, _ in plan.requests] == ["2026-11-07"]
    assert plan.remaining_requests == 1


def test_dry_run_fetches_nothing(db_engine, monkeypatch):
    _backfill_seed(db_engine)
    monkeypatch.setattr(pb, "_historical_prices", lambda *a: pytest.fail("no fetch on a dry run"))
    with Session(db_engine) as db:
        result = pb.run_backfill(db, USER, apply=False)
    assert result["status"] == "dry_run"


def test_apply_stores_prices_resums_totals_marks_history_and_records_a_run(db_engine, monkeypatch):
    _backfill_seed(db_engine)
    calls = []

    def fake(day, coins):
        calls.append((day, sorted(coins)))
        return {f"ethereum:{STETH}": 2300.0, "coingecko:ethereum": 2310.0}

    monkeypatch.setattr(pb, "_historical_prices", fake)
    with Session(db_engine) as db:
        result = pb.run_backfill(db, USER, apply=True)
    assert result["status"] == "completed" and result["items_priced"] == 3
    assert len(calls) == 2
    day6 = _items(db_engine, 9532)
    assert day6["stETH"][:3] == (pytest.approx(2300.0), pytest.approx(4600.0), pb.SOURCE_HISTORICAL)
    assert day6["ETH"][0] == pytest.approx(2310.0)
    assert day6["SOL"][0] is None  # never fetched, never invented
    with db_engine.connect() as conn:
        total = conn.execute(text("SELECT total_usd FROM crypto_wallet_snapshots WHERE id = 9532")).scalar()
        dirty = conn.execute(text("SELECT from_date FROM wealth_rollup_dirty WHERE user_id = :u"), {"u": USER}).scalar()
        run = conn.execute(
            text("SELECT status FROM job_runs WHERE job = 'crypto_price_backfill' ORDER BY id DESC LIMIT 1")
        ).scalar()
    assert float(total) == pytest.approx(4600.0 + 2310.0)
    # Only marked when the date is on or before the latest completed anchor (#138); either way never later.
    assert dirty is None or str(dirty)[:10] <= "2026-11-06"
    assert run == "success"
    # A second run has nothing left for these tokens.
    with Session(db_engine) as db:
        assert pb.plan_backfill(db, USER).items == 0


def test_a_failed_request_is_counted_and_the_rest_go_on(db_engine, monkeypatch):
    _backfill_seed(db_engine)

    def flaky(day, coins):
        if day == date(2026, 11, 7):
            raise RuntimeError("boom")
        return {f"ethereum:{STETH}": 2300.0, "coingecko:ethereum": 2310.0}

    monkeypatch.setattr(pb, "_historical_prices", flaky)
    with Session(db_engine) as db:
        result = pb.run_backfill(db, USER, apply=True)
    assert result["status"] == "partial"
    assert result["failed_requests"] == 1 and result["items_priced"] == 2


def test_endpoints_plan_and_run_for_the_caller_only(db_engine, monkeypatch):
    _backfill_seed(db_engine)
    monkeypatch.setattr(pb, "_historical_prices", lambda day, coins: {f"ethereum:{STETH}": 2300.0})
    ensure_user(db_engine, OTHER)
    other = signed_in_client(db_engine, OTHER)
    assert other.get("/crypto/price-backfill-plan").json()["items"] == 0
    assert other.post("/crypto/price-backfill").json()["items_priced"] == 0
    me = signed_in_client(db_engine, USER, admin=True)
    assert me.get("/crypto/price-backfill-plan").json()["items"] == 3
    assert me.post("/crypto/price-backfill").json()["items_priced"] == 2
