from datetime import datetime, timezone

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.routers.crypto as crypto_router


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
                INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd)
                VALUES ('w1', :as_of, :fetched_at, 123.45)
                """
            ),
            {"as_of": datetime(2026, 2, 21).date(), "fetched_at": datetime.now(tz=timezone.utc)},
        )
        conn.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                (snapshot_id, chain_type, chain, asset_kind, symbol, normalized_amount, value_usd)
                VALUES (1, 'evm', 'ethereum', 'native', 'ETH', 0.5, 123.45)
                """
            )
        )

    resp = client.get("/crypto/summary?base_currency=SGD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_crypto_usd"] == 123.45
    assert body["total_crypto_base"] == 123.45
    assert body["top5_holdings"][0]["symbol"] == "ETH"
