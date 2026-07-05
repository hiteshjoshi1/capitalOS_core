from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace


from eth_account import Account
from eth_account.messages import encode_defunct
from nacl.signing import SigningKey
import base58
import base64
import jwt
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

import app.routers.crypto as crypto_router
from app.crypto.coinbase import (
    CoinbaseClient,
    CoinbaseConfig,
    build_jwt,
    ensure_coinbase_wallet,
    parse_coinbase_accounts,
)
from app.crypto.ingest import SnapshotResult
from app.crypto.refresh import refresh_wallet_snapshot


def test_crypto_wallet_init_and_verify(client: TestClient, monkeypatch):
    monkeypatch.setattr(crypto_router, "_refresh_wallet", lambda wallet_id: None)

    acct = Account.create()
    payload = {
        "chain_type": "evm",
        "chain": "ethereum",
        "address": acct.address,
        "label": "Main wallet",
    }
    init = client.post("/crypto/wallets/init", json=payload)
    assert init.status_code == 200
    data = init.json()
    message = data["message_to_sign"]

    signed = Account.sign_message(encode_defunct(text=message), acct.key)
    verify = client.post(
        "/crypto/wallets/verify",
        json={
            "chain_type": "evm",
            "chain": "ethereum",
            "address": acct.address,
            "signature": signed.signature.hex(),
            "verification_id": data["verification_id"],
        },
    )
    assert verify.status_code == 200
    assert verify.json()["status"] == "active"


def test_crypto_summary_uses_snapshots(client: TestClient, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets (id, chain_type, chain, address, status, created_at)
                VALUES ('w1', 'evm', 'ethereum', '0xabc', 'active', :now)
                """
            ),
            {"now": datetime.now(tz=timezone.utc)},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd)
                VALUES (9001, 'w1', :as_of, :fetched_at, 123.45)
                """
            ),
            {"as_of": datetime(2026, 2, 21).date(), "fetched_at": datetime.now(tz=timezone.utc)},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                (snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd)
                VALUES (9001, 'evm', 'ethereum', 'native', 'ETH', 0.5, 123.45)
                """
            )
        )

    resp = client.get("/crypto/summary?base_currency=SGD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_crypto_usd"] == 123.45
    assert body["total_crypto_base"] == 123.45
    assert body["top5_holdings"][0]["symbol"] == "ETH"


def test_coinbase_account_parser_skips_fiat_inactive_and_zero_balances():
    accounts = [
        {
            "uuid": "btc-account",
            "name": "BTC Wallet",
            "currency": "BTC",
            "active": True,
            "available_balance": {"value": "0.10"},
            "hold": {"value": "0.025"},
        },
        {
            "uuid": "usd-account",
            "name": "USD Wallet",
            "currency": "USD",
            "active": True,
            "available_balance": {"value": "1000"},
        },
        {
            "uuid": "eth-account",
            "name": "ETH Wallet",
            "currency": "ETH",
            "active": False,
            "available_balance": {"value": "2"},
        },
        {
            "uuid": "sol-account",
            "name": "SOL Wallet",
            "currency": "SOL",
            "active": True,
            "available_balance": {"value": "0"},
        },
    ]

    positions = parse_coinbase_accounts(accounts, lambda symbol: {"BTC": Decimal("60000")}.get(symbol))

    assert len(positions) == 1
    position = positions[0]
    assert position.account_uuid == "btc-account"
    assert position.symbol == "BTC"
    assert position.quantity == Decimal("0.125")
    assert position.price_usd == Decimal("60000")
    assert position.value_usd == Decimal("7500.000")


def test_coinbase_jwt_uses_advanced_trade_uri_and_key_id():
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    config = CoinbaseConfig(
        key_id="organizations/test-org/apiKeys/test-key",
        key_secret=private_pem,
    )

    token = build_jwt(config, "GET", "/api/v3/brokerage/accounts")

    header = jwt.get_unverified_header(token)
    payload = jwt.decode(token, options={"verify_signature": False})
    assert header["kid"] == config.key_id
    assert header["alg"] == "ES256"
    assert payload["sub"] == config.key_id
    assert payload["iss"] == "cdp"
    assert payload["uri"] == "GET api.coinbase.com/api/v3/brokerage/accounts"


def test_coinbase_prices_usd_stablecoins_at_parity():
    client = CoinbaseClient(
        CoinbaseConfig(
            key_id="organizations/test-org/apiKeys/test-key",
            key_secret="not-used-for-stablecoin-price",
        )
    )

    assert client.price_usd("USDC") == Decimal("1")
    assert client.price_usd("usdt") == Decimal("1")


def test_coinbase_exchange_wallet_refreshes_into_crypto_summary(client: TestClient, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets
                  (id, user_id, chain_type, chain, address, label, status, created_at)
                VALUES
                  ('coinbase-wallet', 1, 'exchange', 'coinbase', 'coinbase:1:default', 'Coinbase', 'active', :now)
                """
            ),
            {"now": datetime.now(tz=timezone.utc)},
        )

    def fake_fetch_coinbase_snapshot():
        return SnapshotResult(
            total_usd=7500.0,
            items=[
                {
                    "asset_kind": "exchange_spot",
                    "contract_or_mint": "btc-account",
                    "symbol": "BTC",
                    "name": "BTC Wallet",
                    "decimals": None,
                    "raw_amount": "0.125",
                    "normalized_amount": 0.125,
                    "price_usd": 60000.0,
                    "value_usd": 7500.0,
                    "price_source": "coinbase_public_product",
                    "chain": "coinbase",
                }
            ],
            source_versions={
                "balances_provider": "coinbase_advanced_trade",
                "pricing_provider": "coinbase_public_products",
            },
        )

    monkeypatch.setattr("app.crypto.coinbase.fetch_coinbase_snapshot", fake_fetch_coinbase_snapshot)

    with Session(db_engine) as db:
        refreshed = refresh_wallet_snapshot(db, "coinbase-wallet", user_id=1, automatic=True)

    assert refreshed is True
    resp = client.get("/crypto/summary?base_currency=USD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_crypto_usd"] == 7500.0
    assert body["top_holdings"][0]["symbol"] == "BTC"
    assert body["top_holdings"][0]["chain"] == "coinbase"
    assert body["wallet_exposure"][0]["label"] == "Coinbase"


def test_coinbase_scheduler_creates_and_refreshes_stale_exchange_wallet(db_engine, monkeypatch):
    import app.crypto.scheduler as crypto_scheduler

    SessionLocal = sessionmaker(bind=db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, label, status, created_at)
                VALUES ('evm-stale-wallet', 1, 'evm', 'ethereum', '0xstale', 'Existing EVM', 'active', :now)
                """
            ),
            {"now": datetime.now(tz=timezone.utc)},
        )

    def fake_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    refreshed: list[dict] = []

    def fake_refresh_wallet_snapshot(db, wallet_id, *, user_id, automatic):
        refreshed.append({"wallet_id": wallet_id, "user_id": user_id, "automatic": automatic})
        return True

    monkeypatch.setenv("COINBASE_KEY_ID", "organizations/test-org/apiKeys/test-key")
    monkeypatch.setenv("COINBASE_KEY_SECRET", "test-secret")
    monkeypatch.setenv("COINBASE_SCHEDULER_ENABLED", "auto")
    monkeypatch.delenv("COINBASE_USERNAME", raising=False)
    monkeypatch.setenv("COINBASE_USER_ID", "1")
    monkeypatch.setattr(crypto_scheduler, "get_db", fake_get_db)
    monkeypatch.setattr(crypto_scheduler, "refresh_wallet_snapshot", fake_refresh_wallet_snapshot)

    crypto_scheduler._refresh_due_wallets()

    with db_engine.connect() as conn:
        wallet = conn.execute(
            text(
                """
                SELECT id, user_id, chain_type, chain, address, label, status
                FROM crypto_wallets
                WHERE chain_type = 'exchange' AND chain = 'coinbase'
                """
            )
        ).mappings().one()
    assert wallet["user_id"] == 1
    assert wallet["address"] == "coinbase:1:default"
    assert wallet["label"] == "Coinbase"
    assert wallet["status"] == "active"
    assert {item["wallet_id"] for item in refreshed} == {"evm-stale-wallet", wallet["id"]}
    assert all(item["user_id"] == 1 for item in refreshed)
    assert all(item["automatic"] is True for item in refreshed)


def test_coinbase_scheduler_resolves_configured_username(db_engine, monkeypatch):
    import app.crypto.scheduler as crypto_scheduler

    SessionLocal = sessionmaker(bind=db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, username, display_name, is_active)
                VALUES (2, 'hitesh', 'Hitesh', 1)
                """
            )
        )

    def fake_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    refreshed: list[dict] = []

    def fake_refresh_wallet_snapshot(db, wallet_id, *, user_id, automatic):
        refreshed.append({"wallet_id": wallet_id, "user_id": user_id, "automatic": automatic})
        return True

    monkeypatch.setenv("COINBASE_KEY_ID", "organizations/test-org/apiKeys/test-key")
    monkeypatch.setenv("COINBASE_KEY_SECRET", "test-secret")
    monkeypatch.setenv("COINBASE_SCHEDULER_ENABLED", "auto")
    monkeypatch.setenv("COINBASE_USERNAME", "hitesh")
    monkeypatch.setenv("COINBASE_USER_ID", "1")
    monkeypatch.setattr(crypto_scheduler, "get_db", fake_get_db)
    monkeypatch.setattr(crypto_scheduler, "refresh_wallet_snapshot", fake_refresh_wallet_snapshot)

    crypto_scheduler._refresh_due_wallets()

    with db_engine.connect() as conn:
        wallet = conn.execute(
            text(
                """
                SELECT id, user_id, address, label, status
                FROM crypto_wallets
                WHERE chain_type = 'exchange' AND chain = 'coinbase'
                """
            )
        ).mappings().one()
    assert wallet["user_id"] == 2
    assert wallet["address"] == "coinbase:2:default"
    assert wallet["label"] == "Coinbase"
    assert wallet["status"] == "active"
    assert refreshed == [{"wallet_id": wallet["id"], "user_id": 2, "automatic": True}]


def test_ensure_coinbase_wallet_is_idempotent(db_engine):
    with Session(db_engine) as db:
        first = ensure_coinbase_wallet(db, 1)
        second = ensure_coinbase_wallet(db, 1)

    assert first == second
    with db_engine.connect() as conn:
        count = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM crypto_wallets
                WHERE chain_type = 'exchange' AND chain = 'coinbase' AND address = 'coinbase:1:default'
                """
            )
        ).scalar_one()
    assert count == 1


def test_crypto_summary_exposes_snapshot_delta_and_refresh_movements(client: TestClient, db_engine, monkeypatch):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets (id, chain_type, chain, address, status, created_at)
                VALUES ('w-delta', 'evm', 'ethereum', '0xdelta', 'active', :now)
                """
            ),
            {"now": datetime(2026, 5, 23, tzinfo=timezone.utc)},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd)
                VALUES
                  (9101, 'w-delta', '2026-05-01', '2026-05-01T00:00:00+00:00', 3000),
                  (9102, 'w-delta', '2026-05-22', '2026-05-22T00:00:00+00:00', 3400),
                  (9103, 'w-delta', '2026-05-23', '2026-05-23T00:00:00+00:00', 3600)
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                  (snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, price_usd, value_usd)
                VALUES
                  (9101, 'evm', 'ethereum', 'native', 'ETH', 2, 1500, 3000),
                  (9102, 'evm', 'ethereum', 'native', 'ETH', 2, 1700, 3400),
                  (9103, 'evm', 'ethereum', 'native', 'ETH', 2, 1800, 3600)
                """
            )
        )

    monkeypatch.setattr("app.routers.crypto.get_rates", lambda *_args, **_kwargs: {"USD": 1.0})

    resp = client.get("/crypto/summary?month=2026-04&base_currency=USD")
    assert resp.status_code == 200
    body = resp.json()

    assert body["month"] == "2026-04"
    assert body["snapshot_as_of"] == "2026-05-01"
    assert body["snapshot_total_base"] == 3000.0
    assert body["snapshot_delta_base"] == 600.0
    assert body["trend"][-1] == {"month": "2026-04", "value": 3000.0}
    assert body["chain_exposure"][0]["chain"] == "ethereum"
    holding = body["top_holdings"][0]
    assert holding["price_change_usd"] == 100.0
    assert holding["value_change_base"] == 200.0
    assert holding["snapshot_delta_base"] == 600.0


def test_verify_solana_signature_unit():
    sk = SigningKey.generate()
    vk = sk.verify_key
    address = base58.b58encode(vk.encode()).decode("utf-8")
    message = "CapitalOS test message"
    raw_msg = message.encode("utf-8")
    sig = sk.sign(raw_msg).signature

    from app.crypto.verify import verify_solana_signature

    sig_b58 = base58.b58encode(sig).decode("utf-8")
    res_b58 = verify_solana_signature(message, sig_b58, address)
    assert res_b58.ok

    sig_b64 = base64.b64encode(sig).decode("utf-8")
    res_b64 = verify_solana_signature(message, sig_b64, address)
    assert res_b64.ok

    sip_prefix = b"\x18" + b"Solana Signed Message:" + b"\n"
    prefixed = sip_prefix + str(len(raw_msg)).encode("utf-8") + raw_msg
    sig_prefixed = sk.sign(prefixed).signature
    sig_prefixed_b58 = base58.b58encode(sig_prefixed).decode("utf-8")
    res_prefixed = verify_solana_signature(message, sig_prefixed_b58, address)
    assert res_prefixed.ok

    lower_prefix = b"\x18" + b"solana signed message:" + b"\n"
    prefixed_lower = lower_prefix + raw_msg
    sig_lower = sk.sign(prefixed_lower).signature
    sig_lower_b58 = base58.b58encode(sig_lower).decode("utf-8")
    res_lower = verify_solana_signature(message, sig_lower_b58, address)
    assert res_lower.ok


def test_crypto_summary_does_not_trigger_refresh(client: TestClient, db_engine):
    """GET /crypto/summary must return refresh_triggered=False and must not mutate DB state."""
    from sqlalchemy import text

    wallet_id = "wallet-no-refresh"
    as_of = datetime.now(tz=timezone.utc)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, chain_type, chain, address, label, status, created_at, refresh_in_progress) "
                "VALUES (:id, 'evm', 'ethereum', '0xNOREFRESH', 'Test', 'active', :now, FALSE)"
            ),
            {"id": wallet_id, "now": as_of},
        )
        conn.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd) "
                "VALUES (:wid, :as_of, :fetched, 500.0)"
            ),
            {"wid": wallet_id, "as_of": as_of.date(), "fetched": as_of},
        )

    resp = client.get("/crypto/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["refresh_triggered"] is False

    with db_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT refresh_in_progress, refresh_started_at FROM crypto_wallets WHERE id = :id"
            ),
            {"id": wallet_id},
        ).fetchone()
    assert row is not None
    assert not row[0], "refresh_in_progress must remain FALSE after /crypto/summary"
    assert row[1] is None, "refresh_started_at must remain NULL after /crypto/summary"


def test_refresh_wallet_snapshot_publishes_portfolio_refresh(db_engine, monkeypatch):
    published_events = []

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, status, created_at) "
                "VALUES ('wallet-refresh', 1, 'evm', 'ethereum', '0xrefresh', 'active', :now)"
            ),
            {"now": datetime.now(tz=timezone.utc)},
        )

    monkeypatch.setattr("app.crypto.refresh.acquire_refresh_lock", lambda db, wallet_id: True)
    monkeypatch.setattr("app.crypto.refresh.release_refresh_lock", lambda db, wallet_id: None)
    monkeypatch.setattr(
        "app.crypto.refresh.ingest_wallet",
        lambda db, wallet_id: SimpleNamespace(items=[object(), object()], total_usd=321.0),
    )
    monkeypatch.setattr("app.crypto.refresh.upsert_snapshot", lambda db, wallet_id, result: None)
    monkeypatch.setattr(
        "app.crypto.refresh.publish_portfolio_refresh",
        lambda user_id, **kwargs: published_events.append({"user_id": user_id, **kwargs}),
    )

    with Session(db_engine) as db:
        refreshed = refresh_wallet_snapshot(db, "wallet-refresh", user_id=1, automatic=True)

    assert refreshed is True
    assert published_events == [
        {
            "user_id": 1,
            "event_name": "crypto_refresh_completed",
            "source": "crypto",
            "payload": {
                "wallet_id": "wallet-refresh",
                "automatic": True,
                "total_usd": 321.0,
            },
        }
    ]


def test_refresh_wallet_snapshot_does_not_persist_partial_evm_snapshot(db_engine, monkeypatch):
    wallet_id = "wallet-partial-failure"
    old_as_of = datetime(2026, 7, 3, tzinfo=timezone.utc)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, status, created_at)
                VALUES (:wallet_id, 1, 'evm', 'ethereum', '0xpartial', 'active', :now)
                """
            ),
            {"wallet_id": wallet_id, "now": old_as_of},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd)
                VALUES (9901, :wallet_id, '2026-07-03', :fetched_at, 40000)
                """
            ),
            {"wallet_id": wallet_id, "fetched_at": old_as_of},
        )

    monkeypatch.setenv("CRYPTO_EVM_CHAINS", "ethereum")
    monkeypatch.setenv("CRYPTO_EVM_TOKEN_CHAINS", "ethereum")
    monkeypatch.setattr(
        "app.crypto.ingest.fetch_wallet_holdings",
        lambda chain_type, chain, address: (_ for _ in ()).throw(RuntimeError("Alchemy token balance fetch failed")),
    )

    with Session(db_engine) as db:
        refreshed = refresh_wallet_snapshot(db, wallet_id, user_id=1, automatic=True)

    assert refreshed is False
    with db_engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT as_of_date, total_usd
                FROM crypto_wallet_snapshots
                WHERE wallet_id = :wallet_id
                ORDER BY as_of_date DESC
                """
            ),
            {"wallet_id": wallet_id},
        ).mappings().all()
    assert len(rows) == 1
    assert str(rows[0]["as_of_date"]) == "2026-07-03"
    assert float(rows[0]["total_usd"]) == 40000.0


def test_evm_provider_order_falls_back_from_moralis_to_alchemy(monkeypatch):
    from app.crypto import providers
    from app.crypto.adapters import NativeBalance

    class FailingMoralis:
        provider_name = "moralis"
        supported_chains = {"ethereum"}

        def fetch_wallet_holdings(self, address, chain):
            raise RuntimeError("moralis unavailable")

    class WorkingAlchemy:
        provider_name = "alchemy"
        supported_chains = {"ethereum"}

        def fetch_wallet_holdings(self, address, chain):
            return (
                NativeBalance(
                    symbol="ETH",
                    decimals=18,
                    raw_amount="1000000000000000000",
                    normalized_amount=1.0,
                ),
                [],
            )

    monkeypatch.setenv("MORALIS_API_KEY", "test-key")
    monkeypatch.setenv("CRYPTO_EVM_HOLDINGS_PROVIDERS", "moralis,alchemy")
    monkeypatch.setattr(providers, "MoralisHoldingsProvider", FailingMoralis)
    monkeypatch.setattr(providers, "AlchemyHoldingsProvider", WorkingAlchemy)

    native, tokens, provider_name = providers.fetch_wallet_holdings("evm", "ethereum", "0xabc")

    assert provider_name == "alchemy"
    assert native.normalized_amount == 1.0
    assert tokens == []


def test_crypto_http_retry_is_bounded_for_rate_limits(monkeypatch):
    from app.crypto import http

    calls: list[dict] = []
    sleeps: list[float] = []

    class RateLimitedResponse:
        status_code = 429

    monkeypatch.setattr(http.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        http.httpx,
        "request",
        lambda method, url, **kwargs: calls.append({"method": method, "url": url, **kwargs}) or RateLimitedResponse(),
    )

    response = http.request_with_retry(
        "GET",
        "https://example.test/rate-limited",
        max_attempts=3,
        backoff_seconds=0.25,
        retry_statuses={429},
    )

    assert response.status_code == 429
    assert len(calls) == 3
    assert sleeps == [0.25, 0.5]


def test_failed_holdings_refresh_overlays_fresh_prices_without_new_snapshot(client: TestClient, db_engine, monkeypatch):
    wallet_id = "wallet-stale-holdings-fresh-price"
    old_as_of = datetime(2026, 7, 3, tzinfo=timezone.utc)

    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallets (id, user_id, chain_type, chain, address, label, status, created_at)
                VALUES (:wallet_id, 1, 'evm', 'ethereum', '0xstaleprice', 'Stale Wallet', 'active', :now)
                """
            ),
            {"wallet_id": wallet_id, "now": old_as_of},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshots (id, wallet_id, as_of_date, fetched_at, total_usd, source_versions)
                VALUES (
                  9910,
                  :wallet_id,
                  '2026-07-03',
                  :fetched_at,
                  200,
                  '{"holdings_as_of":"2026-07-03T00:00:00+00:00","price_as_of":"2026-07-03T00:00:00+00:00","holdings_provider":"alchemy","price_provider":"coingecko"}'
                )
                """
            ),
            {"wallet_id": wallet_id, "fetched_at": old_as_of},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                (snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, price_usd, value_usd)
                VALUES (9910, 'evm', 'ethereum', 'native', 'ETH', 2, 100, 200)
                """
            )
        )

    monkeypatch.setattr("app.crypto.refresh.ingest_wallet", lambda db, wallet_id: (_ for _ in ()).throw(RuntimeError("Alchemy 429")))
    monkeypatch.setattr("app.crypto.valuation.price_by_symbol", lambda symbol: 150.0 if symbol == "ETH" else None)
    monkeypatch.setattr("app.crypto.valuation.price_by_contract", lambda chain, contracts: {})
    monkeypatch.setattr("app.crypto.valuation.price_by_mint", lambda mints: {})

    with Session(db_engine) as db:
        refreshed = refresh_wallet_snapshot(db, wallet_id, user_id=1, automatic=True)

    assert refreshed is False
    with db_engine.connect() as conn:
        snapshots = conn.execute(
            text("SELECT COUNT(*) FROM crypto_wallet_snapshots WHERE wallet_id = :wallet_id"),
            {"wallet_id": wallet_id},
        ).scalar_one()
        row = conn.execute(
            text(
                """
                SELECT s.total_usd, i.price_usd, i.value_usd, s.source_versions
                FROM crypto_wallet_snapshots s
                JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
                WHERE s.wallet_id = :wallet_id
                """
            ),
            {"wallet_id": wallet_id},
        ).mappings().one()

    assert snapshots == 1
    assert float(row["total_usd"]) == 300.0
    assert float(row["price_usd"]) == 150.0
    assert float(row["value_usd"]) == 300.0
    assert "2026-07-03T00:00:00+00:00" in row["source_versions"]

    resp = client.get("/crypto/summary?base_currency=USD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_crypto_usd"] == 300.0
    assert body["holdings_as_of"] == "2026-07-03T00:00:00+00:00"
    assert body["price_as_of"] is not None
    assert body["stale_holdings"] is True
    assert body["stale_prices"] is False
