"""#342: spam/unknown wallet tokens are hidden by default; "Not spam" / "Hide" per user.
Synthetic wallets and tokens only."""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.crypto import token_visibility as tv
from tests.auth_helpers import ensure_user, signed_in_client

USER = 1
OTHER = 2
SPAM_SOL = "0x1111111111111111111111111111111111111111"  # an ERC-20 calling itself "SOL"
SPAM_2 = "0x2222222222222222222222222222222222222222"
STETH = "0xae7ab96520de3a18e5e111b5eaab095312d7fe84"
WAS_PRICED = "0x3333333333333333333333333333333333333333"
ALLOWED = "0x4444444444444444444444444444444444444444"


def _seed(engine, rows, *, wallet="w-a", user=USER, chain="ethereum", chain_type="evm"):
    """rows: (snapshot_id, as_of_date, [(symbol, kind, contract, qty, price)])"""
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, status, created_at, user_id) "
                "VALUES (:w, :ct, :c, :a, 'active', '2026-01-01T00:00:00+00:00', :u)"
            ),
            {"w": wallet, "ct": chain_type, "c": chain, "a": f"0x{wallet}", "u": user},
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
                        "VALUES (:s, :ct, :c, :k, :ctr, :sym, :q, :p, :v)"
                    ),
                    {"s": sid, "ct": chain_type, "c": chain, "k": kind, "ctr": contract, "sym": symbol, "q": qty,
                     "p": price, "v": None if price is None else qty * price},
                )


def _eth_wallet(engine, *, user=USER, wallet="w-a"):
    _seed(
        engine,
        [
            (1 if user == USER else 11, "2026-10-01", [("OLD", "erc20", WAS_PRICED, 3, 1.5)]),
            (2 if user == USER else 12, "2026-11-05", [
                ("ETH", "native", None, 2, 2000.0),
                ("stETH", "erc20", STETH, 1, 1990.0),
                ("SOL", "erc20", SPAM_SOL, 5, None),      # spam: never priced
                ("FREE", "erc20", SPAM_2, 1000, None),    # spam: never priced
                ("OLD", "erc20", WAS_PRICED, 3, None),    # priced once before: a real token
                ("ALW", "erc20", ALLOWED, 7, None),       # allowlisted
            ]),
        ],
        user=user,
        wallet=wallet,
    )


def _allow(engine, contract):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO crypto_allowlist (chain, contract_address, symbol, name) VALUES ('ethereum', :c, 'ALW', 'Allowed')"),
            {"c": contract.upper().replace("0X", "0x")},
        )


def _latest_items(db_engine, user=USER):
    from app.crypto.valuation import latest_wallet_valuation

    with Session(db_engine) as db:
        items = latest_wallet_valuation(db, user)["items"]
        hidden = tv.annotate(db, user, items)
    return {item["symbol"]: item for item in items}, hidden


def test_never_priced_tokens_are_unknown_and_hidden(db_engine):
    ensure_user(db_engine, USER)
    _eth_wallet(db_engine)
    _allow(db_engine, ALLOWED)
    items, hidden = _latest_items(db_engine)
    assert items["SOL"]["unknown_token"] and items["SOL"]["hidden"]
    assert items["SOL"]["hidden_reason"] == "unknown_token"
    assert items["FREE"]["hidden"]
    assert hidden == 2


def test_priced_native_once_priced_and_allowlisted_tokens_stay(db_engine):
    ensure_user(db_engine, USER)
    _eth_wallet(db_engine)
    _allow(db_engine, ALLOWED)
    items, _ = _latest_items(db_engine)
    for symbol in ("ETH", "stETH", "OLD", "ALW"):
        assert not items[symbol]["hidden"], symbol
        assert not items[symbol]["unknown_token"], symbol
    assert items["ETH"]["token_key"] is None  # a native coin has no contract: never unknown
    assert items["stETH"]["token_key"] == f"ethereum:{STETH}"


def test_same_symbol_on_another_chain_or_contract_is_judged_on_its_own(db_engine):
    ensure_user(db_engine, USER)
    _eth_wallet(db_engine)
    # Real SOL on Solana (native, priced) and a priced token with the same symbol elsewhere.
    _seed(db_engine, [(3, "2026-11-05", [("SOL", "native", None, 56, 160.0)])],
          wallet="w-sol", chain="solana", chain_type="solana")
    from app.crypto.valuation import latest_wallet_valuation

    with Session(db_engine) as db:
        items = latest_wallet_valuation(db, USER)["items"]
        tv.annotate(db, USER, items)
    sols = {(i["chain"], bool(i.get("contract_or_mint"))): i for i in items if i["symbol"] == "SOL"}
    assert sols[("ethereum", True)]["hidden"]
    assert not sols[("solana", False)]["hidden"]


def test_user_overrides_win_and_can_be_reset(db_engine):
    ensure_user(db_engine, USER)
    _eth_wallet(db_engine)
    with Session(db_engine) as db:
        tv.set_override(db, USER, "ethereum", SPAM_SOL.upper().replace("0X", "0x"), "shown")  # "Not spam"
        tv.set_override(db, USER, "ethereum", STETH, "hidden")
    items, hidden = _latest_items(db_engine)
    assert not items["SOL"]["hidden"] and items["SOL"]["visibility_override"] == "shown"
    assert items["SOL"]["unknown_token"]  # still unknown; the user chose to see it
    assert items["stETH"]["hidden"] and items["stETH"]["hidden_reason"] == "user_hidden"
    assert hidden == 3  # FREE and ALW (unknown: not allowlisted here) + stETH (user)
    with Session(db_engine) as db:
        tv.set_override(db, USER, "ethereum", SPAM_SOL, None)
    items, _ = _latest_items(db_engine)
    assert items["SOL"]["hidden"] and items["SOL"]["visibility_override"] is None


def test_set_override_rejects_bad_input(db_engine):
    ensure_user(db_engine, USER)
    with Session(db_engine) as db:
        for chain, contract, vis in (("ethereum", "", "hidden"), ("ethereum", SPAM_SOL, "maybe")):
            try:
                tv.set_override(db, USER, chain, contract, vis)
            except ValueError:
                continue
            raise AssertionError(f"accepted {contract!r} {vis!r}")


def test_summary_flags_hidden_holdings_without_changing_totals(db_engine):
    me = signed_in_client(db_engine, USER)
    _eth_wallet(db_engine)
    before = me.get("/crypto/summary").json()
    assert before["hidden_token_count"] == 3  # SOL + FREE + ALW (not allowlisted here)
    by_symbol = {h["symbol"]: h for h in before["top_holdings"]}
    assert by_symbol["SOL"]["hidden"] and by_symbol["SOL"]["hidden_reason"] == "unknown_token"
    assert by_symbol["SOL"]["contract_or_mint"].lower() == SPAM_SOL
    assert not any(h["hidden"] for h in before["top5_holdings"])
    total = before["total_crypto_usd"]

    r = me.put("/crypto/token-visibility", json={"chain": "ethereum", "contract_or_mint": SPAM_SOL, "visibility": "shown"})
    assert r.status_code == 200
    assert r.json()["overrides"] == [{"chain": "ethereum", "contract_or_mint": SPAM_SOL, "visibility": "shown"}]
    after = me.get("/crypto/summary").json()
    assert after["hidden_token_count"] == 2
    assert after["total_crypto_usd"] == total  # valuation unchanged
    tokens = me.get("/crypto/tokens").json()
    assert tokens["hidden_count"] == 2
    assert me.put("/crypto/token-visibility", json={"chain": "ethereum", "contract_or_mint": "", "visibility": "x"}).status_code == 422


def test_overrides_are_per_user(db_engine):
    me = signed_in_client(db_engine, USER)
    other = signed_in_client(db_engine, OTHER)
    _eth_wallet(db_engine)
    _eth_wallet(db_engine, user=OTHER, wallet="w-b")
    me.put("/crypto/token-visibility", json={"chain": "ethereum", "contract_or_mint": SPAM_SOL, "visibility": "shown"})
    assert other.get("/crypto/token-visibility").json() == {"overrides": []}
    theirs = {h["symbol"]: h for h in other.get("/crypto/summary").json()["top_holdings"]}
    assert theirs["SOL"]["hidden"]
