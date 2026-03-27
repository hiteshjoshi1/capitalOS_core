from datetime import datetime, timezone


from eth_account import Account
from eth_account.messages import encode_defunct
from nacl.signing import SigningKey
import base58
import base64
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
