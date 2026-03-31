from __future__ import annotations

import os
import logging
import hashlib
import base64
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
import time
import httpx

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, allow_legacy_null_ownership, require_current_user
from app.db.session import get_db
from app.crypto.verify import (
    verify_evm_signature,
    verify_solana_signature,
    verify_solana_signature_debug,
    verify_solana_signature_bytes_debug,
)
from app.crypto.ingest import ingest_wallet, upsert_snapshot, acquire_refresh_lock, release_refresh_lock
from app.crypto.pricing import lookup_contract_metadata, price_by_contract, price_by_mint
from app.fx import get_rates

_STALE_THRESHOLD_SECONDS = 24 * 3600

router = APIRouter(prefix="/crypto", tags=["crypto"], dependencies=[Depends(require_current_user)])
logger = logging.getLogger("uvicorn.error")
_SOLANA_MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"


class WalletInitIn(BaseModel):
    chain_type: str
    chain: str
    address: str
    label: Optional[str] = None


class WalletVerifyIn(BaseModel):
    chain_type: str
    chain: str
    address: str
    signature: str
    public_key: Optional[str] = None
    verification_id: Optional[int] = None


class SolanaDebugVerifyIn(BaseModel):
    address: str
    message_bytes_b64: str
    signature: str


class SolanaVerifyOnchainIn(BaseModel):
    address: str
    signature: str
    verification_id: int


class SolanaSubmitTxIn(BaseModel):
    tx_b64: str


class SolanaPreflightIn(BaseModel):
    tx_b64: str


def _nonce_ttl() -> int:
    return int(os.getenv("CRYPTO_SIGNING_NONCE_TTL_SECONDS", "600"))


def _wallet_scope_sql(alias: str = "w") -> str:
    if allow_legacy_null_ownership():
        return f"({alias}.user_id = :current_user_id OR {alias}.user_id IS NULL)"
    return f"{alias}.user_id = :current_user_id"


def _message(nonce: str, address: str, chain: str) -> str:
    return f"CapitalOS wallet verification\nNonce: {nonce}\nAddress: {address}\nChain: {chain}\nIssuedAt: {datetime.now(tz=timezone.utc).isoformat()}"


def _validate_address(chain_type: str, address: str) -> None:
    if chain_type == "evm":
        if not address.startswith("0x") or len(address) < 42:
            raise HTTPException(status_code=400, detail="Invalid EVM address")
    elif chain_type == "solana":
        try:
            import base58
            decoded = base58.b58decode(address)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid Solana address")
        if len(decoded) != 32:
            raise HTTPException(status_code=400, detail="Invalid Solana address")
    else:
        raise HTTPException(status_code=400, detail="Unsupported chain_type")


def _validate_chain(chain_type: str, chain: str) -> None:
    evm_chains = {"ethereum", "base", "arbitrum", "optimism", "mantle", "scroll"}
    sol_chains = {"solana"}
    if chain_type == "evm" and chain not in evm_chains:
        raise HTTPException(status_code=400, detail="Unsupported EVM chain")
    if chain_type == "solana" and chain not in sol_chains:
        raise HTTPException(status_code=400, detail="Unsupported Solana chain")


def _solana_rpc_urls() -> list[str]:
    urls: list[str] = []
    explicit = os.getenv("SOLANA_RPC_URL")
    if explicit:
        urls.append(explicit)
    explicit_helius = os.getenv("HELIUS_RPC_URL")
    if explicit_helius:
        urls.append(explicit_helius)
    helius = os.getenv("HELIUS_API_KEY")
    if helius:
        urls.append(f"https://mainnet.helius-rpc.com/?api-key={helius}")
    # Always keep a public fallback in case provider-specific endpoints 404.
    urls.append("https://api.mainnet-beta.solana.com")
    return urls


def _solana_rpc(method: str, params: list) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last_exc: Exception | None = None
    for url in _solana_rpc_urls():
        try:
            resp = httpx.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                err = data["error"]
                code = err.get("code") if isinstance(err, dict) else None
                # Skip endpoints that don't support the method
                if code == -32601:
                    logger.info("solana_rpc_method_missing method=%s url=%s", method, url)
                    continue
                raise HTTPException(status_code=400, detail=f"Solana RPC error: {err}")
            return data.get("result")
        except Exception as exc:  # noqa: BLE001
            logger.info("solana_rpc_failed method=%s url=%s error=%s", method, url, exc)
            last_exc = exc
            continue
    raise HTTPException(status_code=502, detail=f"Solana RPC failed: {last_exc}")


def _verify_solana_onchain(signature: str, address: str, nonce: str, expires_at: datetime | None) -> None:
    # Wait for the transaction to land (RPCs can be slow/lagged)
    result = None
    for _ in range(12):
        status = _solana_rpc("getSignatureStatuses", [[signature]])
        value = (status or {}).get("value", [None])[0]
        if value and value.get("confirmationStatus") in ("processed", "confirmed", "finalized"):
            result = _solana_rpc(
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
            )
            if result:
                break
        time.sleep(1)
    if not result:
        raise HTTPException(status_code=400, detail="Transaction not found")
    block_time = result.get("blockTime")
    if expires_at and block_time:
        if datetime.fromtimestamp(block_time, tz=timezone.utc) > expires_at + timedelta(minutes=5):
            raise HTTPException(status_code=400, detail="Transaction too late for nonce")
    tx = result.get("transaction") or {}
    msg = tx.get("message") or {}
    keys = msg.get("accountKeys") or []
    fee_payer = None
    if keys:
        first = keys[0]
        fee_payer = first.get("pubkey") if isinstance(first, dict) else first
    if fee_payer != address:
        raise HTTPException(status_code=400, detail="Transaction fee payer does not match wallet")
    instructions = msg.get("instructions") or []
    found_memo = False
    memo_debug: list[str] = []
    for inst in instructions:
        program_id = inst.get("programId") if isinstance(inst, dict) else None
        program = inst.get("program") if isinstance(inst, dict) else None
        if program_id != _SOLANA_MEMO_PROGRAM and program != "spl-memo":
            continue
        memo_text = None
        if isinstance(inst, dict) and "parsed" in inst:
            parsed = inst.get("parsed")
            if isinstance(parsed, dict):
                info = parsed.get("info") or {}
                memo_text = info.get("memo")
            elif isinstance(parsed, str):
                memo_text = parsed
        data = inst.get("data") if isinstance(inst, dict) else None
        if memo_text is None and data:
            try:
                memo_text = base58.b58decode(data).decode("utf-8", errors="ignore")
            except Exception:
                try:
                    memo_text = base64.b64decode(data).decode("utf-8", errors="ignore")
                except Exception:
                    memo_text = None
        if memo_text:
            memo_debug.append(memo_text)
        if memo_text and nonce in memo_text:
            found_memo = True
            break
    if not found_memo:
        logger.info(
            "solana_memo_not_found",
            extra={"nonce": nonce, "memos": memo_debug, "address": address},
        )
        raise HTTPException(status_code=400, detail="Nonce memo not found in transaction")


@router.post("/wallets/init")
def wallet_init(
    payload: WalletInitIn,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(require_current_user),
):
    _validate_address(payload.chain_type, payload.address)
    _validate_chain(payload.chain_type, payload.chain)

    normalized_address = payload.address.lower() if payload.chain_type == "evm" else payload.address
    existing = db.execute(
        text(
            "SELECT id, status FROM crypto_wallets WHERE chain_type = :chain_type AND chain = :chain AND address = :address"
        ),
        {"chain_type": payload.chain_type, "chain": payload.chain, "address": normalized_address},
    ).fetchone()
    if existing and existing[1] == "active":
        raise HTTPException(status_code=409, detail="Wallet already exists")

    nonce = secrets.token_hex(16)
    message = _message(nonce, normalized_address, payload.chain)
    expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=_nonce_ttl())

    row = db.execute(
        text(
            """
            INSERT INTO crypto_wallet_verifications (wallet_id, chain_type, chain, address, nonce, message, expires_at)
            VALUES (NULL, :chain_type, :chain, :address, :nonce, :message, :expires_at)
            RETURNING id
            """
        ),
        {
            "chain_type": payload.chain_type,
            "chain": payload.chain,
            "address": normalized_address,
            "nonce": nonce,
            "message": message,
            "expires_at": expires_at,
        },
    ).fetchone()
    db.commit()

    return {
        "verification_id": row[0],
        "chain_type": payload.chain_type,
        "chain": payload.chain,
        "address": normalized_address,
        "message_to_sign": message,
        "message_bytes_b64": base64.b64encode(message.encode("utf-8")).decode("utf-8"),
        "message_hash": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "nonce": nonce,
        "expires_at": expires_at.isoformat(),
    }


@router.post("/wallets/verify")
def wallet_verify(
    payload: WalletVerifyIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _validate_address(payload.chain_type, payload.address)
    _validate_chain(payload.chain_type, payload.chain)
    normalized_address = payload.address.lower() if payload.chain_type == "evm" else payload.address

    if payload.verification_id is not None:
        ver = db.execute(
            text(
                """
                SELECT id, message, expires_at, used_at
                FROM crypto_wallet_verifications
                WHERE id = :id AND chain_type = :chain_type AND chain = :chain AND address = :address
                  AND used_at IS NULL
                LIMIT 1
                """
            ),
            {
                "id": payload.verification_id,
                "chain_type": payload.chain_type,
                "chain": payload.chain,
                "address": normalized_address,
            },
        ).mappings().one_or_none()
    else:
        ver = db.execute(
            text(
                """
                SELECT id, message, expires_at, used_at
                FROM crypto_wallet_verifications
                WHERE chain_type = :chain_type AND chain = :chain AND address = :address
                  AND used_at IS NULL
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {
                "chain_type": payload.chain_type,
                "chain": payload.chain,
                "address": normalized_address,
            },
        ).mappings().one_or_none()
    if not ver:
        raise HTTPException(status_code=400, detail="Verification nonce missing")
    if ver["used_at"] is not None:
        raise HTTPException(status_code=400, detail="Nonce already used")
    expires_at = ver["expires_at"]
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid nonce expiry")
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if isinstance(expires_at, datetime) and expires_at < datetime.now(tz=timezone.utc):
        raise HTTPException(status_code=400, detail="Nonce expired")

    if payload.chain_type == "evm":
        addr = payload.address.lower()
        result = verify_evm_signature(ver["message"], payload.signature, addr)
    else:
        msg_hash = hashlib.sha256(ver["message"].encode("utf-8")).hexdigest()
        logger.info(
            "solana_signature_received addr=%s sig_len=%s sig=%s message_hash=%s",
            normalized_address,
            len(payload.signature or ""),
            payload.signature,
            msg_hash,
        )
        result = verify_solana_signature(ver["message"], payload.signature, payload.address)
    if not result.ok:
        logger.info(
            "wallet_verify_failed",
            extra={
                "chain_type": payload.chain_type,
                "chain": payload.chain,
                "address": normalized_address,
                "error": result.error,
                "sig_len": len(payload.signature or ""),
            },
        )
        msg_hash = hashlib.sha256(ver["message"].encode("utf-8")).hexdigest()
        raise HTTPException(
            status_code=400,
            detail=f"{result.error or 'Invalid signature'} (message_hash={msg_hash})",
        )

    wallet = db.execute(
        text(
            "SELECT id, user_id FROM crypto_wallets WHERE chain_type = :chain_type AND chain = :chain AND address = :address"
        ),
        {
            "chain_type": payload.chain_type,
            "chain": payload.chain,
            "address": normalized_address,
        },
    ).mappings().one_or_none()
    if wallet:
        wallet_owner = wallet["user_id"]
        if wallet_owner is not None and int(wallet_owner) != int(current_user.id):
            raise HTTPException(status_code=409, detail="Wallet is owned by another user")
        wallet_id = wallet["id"]
        db.execute(
            text(
                "UPDATE crypto_wallets SET status = 'active', verified_at = :now, user_id = COALESCE(user_id, :current_user_id) WHERE id = :id"
            ),
            {"id": wallet_id, "now": datetime.now(tz=timezone.utc), "current_user_id": current_user.id},
        )
    else:
        row = db.execute(
            text(
                """
                INSERT INTO crypto_wallets (user_id, chain_type, chain, address, status, created_at, verified_at)
                VALUES (:current_user_id, :chain_type, :chain, :address, 'active', :now, :now)
                RETURNING id
                """
            ),
            {
                "current_user_id": current_user.id,
                "chain_type": payload.chain_type,
                "chain": payload.chain,
                "address": normalized_address,
                "now": datetime.now(tz=timezone.utc),
            },
        ).fetchone()
        wallet_id = row[0]

    db.execute(
        text("UPDATE crypto_wallet_verifications SET used_at = :now, wallet_id = :wallet_id WHERE id = :id"),
        {"id": ver["id"], "wallet_id": wallet_id, "now": datetime.now(tz=timezone.utc)},
    )
    db.commit()

    background.add_task(_refresh_wallet, str(wallet_id))
    return {"wallet_id": str(wallet_id), "status": "active"}


@router.post("/wallets/verify-onchain")
def wallet_verify_onchain(
    payload: SolanaVerifyOnchainIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _validate_address("solana", payload.address)
    normalized_address = payload.address
    ver = db.execute(
        text(
            """
            SELECT id, message, expires_at, used_at, nonce
            FROM crypto_wallet_verifications
            WHERE id = :id AND chain_type = 'solana' AND chain = 'solana' AND address = :address
              AND used_at IS NULL
            LIMIT 1
            """
        ),
        {"id": payload.verification_id, "address": normalized_address},
    ).mappings().one_or_none()
    if not ver:
        raise HTTPException(status_code=400, detail="Verification nonce missing")
    expires_at = ver["expires_at"]
    if isinstance(expires_at, str):
        try:
            expires_at = datetime.fromisoformat(expires_at)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid nonce expiry")
    if isinstance(expires_at, datetime) and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if isinstance(expires_at, datetime) and expires_at < datetime.now(tz=timezone.utc):
        raise HTTPException(status_code=400, detail="Nonce expired")

    _verify_solana_onchain(payload.signature, normalized_address, ver["nonce"], expires_at)

    wallet = db.execute(
        text(
            "SELECT id, user_id FROM crypto_wallets WHERE chain_type = 'solana' AND chain = 'solana' AND address = :address"
        ),
        {"address": normalized_address},
    ).mappings().one_or_none()
    if wallet:
        wallet_owner = wallet["user_id"]
        if wallet_owner is not None and int(wallet_owner) != int(current_user.id):
            raise HTTPException(status_code=409, detail="Wallet is owned by another user")
        wallet_id = wallet["id"]
        db.execute(
            text("UPDATE crypto_wallets SET status = 'active', verified_at = :now, user_id = COALESCE(user_id, :current_user_id) WHERE id = :id"),
            {"id": wallet_id, "now": datetime.now(tz=timezone.utc), "current_user_id": current_user.id},
        )
    else:
        row = db.execute(
            text(
                """
                INSERT INTO crypto_wallets (user_id, chain_type, chain, address, status, created_at, verified_at)
                VALUES (:current_user_id, 'solana', 'solana', :address, 'active', :now, :now)
                RETURNING id
                """
            ),
            {"address": normalized_address, "now": datetime.now(tz=timezone.utc), "current_user_id": current_user.id},
        ).fetchone()
        wallet_id = row[0]

    db.execute(
        text("UPDATE crypto_wallet_verifications SET used_at = :now, wallet_id = :wallet_id WHERE id = :id"),
        {"id": ver["id"], "wallet_id": wallet_id, "now": datetime.now(tz=timezone.utc)},
    )
    db.commit()
    background.add_task(_refresh_wallet, str(wallet_id))
    return {"wallet_id": str(wallet_id), "status": "active"}


def _refresh_wallet(wallet_id: str):
    db = next(get_db())
    try:
        if not acquire_refresh_lock(db, wallet_id):
            return
        started = datetime.utcnow()
        result = ingest_wallet(db, wallet_id)
        upsert_snapshot(db, wallet_id, result)
        db.commit()
        logger.info(
            "crypto_refresh_success",
            extra={
                "wallet_id": wallet_id,
                "items": len(result.items),
                "total_usd": result.total_usd,
                "duration_ms": int((datetime.utcnow() - started).total_seconds() * 1000),
            },
        )
    except Exception as exc:
        db.rollback()
        logger.exception("crypto_refresh_failed", extra={"wallet_id": wallet_id, "error": str(exc)})
    finally:
        release_refresh_lock(db, wallet_id)
        db.commit()
        db.close()


@router.get("/wallets")
def list_wallets(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    rows = db.execute(
        text(
            "SELECT id, chain_type, chain, address, label, status, created_at, verified_at FROM crypto_wallets w WHERE "
            + _wallet_scope_sql("w")
            + " ORDER BY created_at DESC"
        ),
        {"current_user_id": current_user.id},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/summary")
def crypto_summary(
    base_currency: str = "USD",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              GROUP BY wallet_id
            )
            SELECT w.id, w.chain_type, w.chain, w.address, w.label, s.total_usd, s.fetched_at
            FROM crypto_wallets w
            LEFT JOIN latest l ON l.wallet_id = w.id
            LEFT JOIN crypto_wallet_snapshots s
              ON s.wallet_id = w.id AND s.as_of_date = l.as_of_date
            WHERE w.status = 'active'
              AND """
            + _wallet_scope_sql("w")
            + """
            """
        ),
        {"current_user_id": current_user.id},
    ).mappings().all()
    last_refreshed = None
    total_usd = 0.0
    refresh_triggered = False
    is_stale = False

    wallet_exposure = []
    for r in rows:
        if r["total_usd"]:
            total_usd += float(r["total_usd"])
            wallet_exposure.append(
                {
                    "wallet_id": str(r["id"]),
                    "label": r["label"],
                    "address": r["address"],
                    "chain_type": r["chain_type"],
                    "chain": r["chain"],
                    "total_usd": float(r["total_usd"]),
                }
            )
        fetched_at = r["fetched_at"]
        if isinstance(fetched_at, str):
            try:
                fetched_at = datetime.fromisoformat(fetched_at)
            except ValueError:
                fetched_at = None
        if isinstance(fetched_at, datetime) and fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if fetched_at and (last_refreshed is None or fetched_at > last_refreshed):
            last_refreshed = fetched_at
        is_stale = is_stale or (
            fetched_at is None
            or (datetime.now(tz=timezone.utc) - fetched_at).total_seconds() > _STALE_THRESHOLD_SECONDS
        )

    items = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              GROUP BY wallet_id
            )
            SELECT i.symbol, i.chain, i.chain_type, i.normalized_amount, i.value_usd, s.wallet_id
            FROM crypto_wallet_snapshot_items i
            JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            WHERE """
            + _wallet_scope_sql("w")
            + """
            ORDER BY i.value_usd DESC NULLS LAST
            LIMIT 50
            """
        ),
        {"current_user_id": current_user.id},
    ).mappings().all()

    chain_breakdown = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              GROUP BY wallet_id
            )
            SELECT s.wallet_id, i.chain, SUM(i.value_usd) AS total_usd
            FROM crypto_wallet_snapshot_items i
            JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            WHERE """
            + _wallet_scope_sql("w")
            + """
            GROUP BY s.wallet_id, i.chain
            ORDER BY total_usd DESC NULLS LAST
            """
        ),
        {"current_user_id": current_user.id},
    ).mappings().all()

    rate = get_rates(datetime.now(tz=timezone.utc), base_currency, {"USD"}).get("USD", 1.0)
    total_base = total_usd * rate

    eth = next((i for i in items if i["symbol"] == "ETH"), None)
    sol = next((i for i in items if i["symbol"] == "SOL"), None)

    eth_group = {"eth", "weth", "steth", "wsteth", "eeth", "weeth"}
    eth_usd = 0.0
    other_usd = 0.0
    token_count = 0
    priced_count = 0
    for r in items:
        token_count += 1
        if r["value_usd"] is None:
            continue
        if r["value_usd"] > 0:
            priced_count += 1
        symbol = (r["symbol"] or "").lower()
        if symbol in eth_group:
            eth_usd += float(r["value_usd"])
        else:
            other_usd += float(r["value_usd"])

    return {
        "total_crypto_usd": total_usd,
        "total_crypto_base": total_base,
        "base_currency": base_currency,
        "eth_exposure_usd": eth_usd,
        "eth_exposure_base": eth_usd * rate,
        "token_exposure_usd": other_usd,
        "token_exposure_base": other_usd * rate,
        "token_count": token_count,
        "priced_token_count": priced_count,
        "eth": {
            "balance": float(eth["normalized_amount"]) if eth and eth["normalized_amount"] is not None else 0,
            "value_usd": float(eth["value_usd"]) if eth and eth["value_usd"] is not None else 0,
            "value_base": float(eth["value_usd"]) * rate if eth and eth["value_usd"] is not None else 0,
        },
        "sol": {
            "balance": float(sol["normalized_amount"]) if sol and sol["normalized_amount"] is not None else 0,
            "value_usd": float(sol["value_usd"]) if sol and sol["value_usd"] is not None else 0,
            "value_base": float(sol["value_usd"]) * rate if sol and sol["value_usd"] is not None else 0,
        },
        "top5_holdings": [
            {
                "symbol": r["symbol"],
                "chain": r["chain"],
                "amount": float(r["normalized_amount"]) if r["normalized_amount"] is not None else 0,
                "value_usd": float(r["value_usd"]) if r["value_usd"] is not None else 0,
                "value_base": float(r["value_usd"]) * rate if r["value_usd"] is not None else 0,
                "wallet_id": str(r["wallet_id"]),
            }
            for r in items[:5]
        ],
        "top_holdings": [
            {
                "symbol": r["symbol"],
                "chain": r["chain"],
                "amount": float(r["normalized_amount"]) if r["normalized_amount"] is not None else 0,
                "value_usd": float(r["value_usd"]) if r["value_usd"] is not None else 0,
                "value_base": float(r["value_usd"]) * rate if r["value_usd"] is not None else 0,
                "asset_class": "CRYPTO",
                "wallet_id": str(r["wallet_id"]),
            }
            for r in items
        ],
        "wallet_exposure": [
            {
                **w,
                "total_base": w["total_usd"] * rate,
            }
            for w in wallet_exposure
        ],
        "wallet_chain_exposure": [
            {
                "wallet_id": str(r["wallet_id"]),
                "chain": r["chain"],
                "total_usd": float(r["total_usd"]) if r["total_usd"] is not None else 0,
                "total_base": (float(r["total_usd"]) if r["total_usd"] is not None else 0) * rate,
            }
            for r in chain_breakdown
        ],
        "last_refreshed_at": last_refreshed.isoformat() if last_refreshed else None,
        "is_stale": is_stale,
        "refresh_triggered": refresh_triggered,
    }


@router.get("/tokens")
def crypto_tokens(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              GROUP BY wallet_id
            )
            SELECT s.wallet_id, w.address, w.label, i.symbol, i.name, i.contract_or_mint,
                   i.chain, i.chain_type, i.normalized_amount, i.price_usd, i.value_usd, i.price_source
            FROM crypto_wallet_snapshot_items i
            JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            WHERE """
            + _wallet_scope_sql("w")
            + """
            ORDER BY i.value_usd DESC NULLS LAST
            """
        ),
        {"current_user_id": current_user.id},
    ).mappings().all()
    return {
        "total": len(rows),
        "tokens": [dict(r) for r in rows],
    }


class AllowlistIn(BaseModel):
    chain: str
    contract_address: str


@router.get("/allowlist")
def crypto_allowlist(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT id, chain, contract_address, symbol, name, created_at FROM crypto_allowlist ORDER BY created_at DESC")
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/allowlist")
def crypto_allowlist_add(payload: AllowlistIn, db: Session = Depends(get_db)):
    chain = payload.chain.lower()
    contract = payload.contract_address.lower()
    if chain == "solana":
        prices = price_by_mint([contract])
        if contract not in prices:
            raise HTTPException(status_code=400, detail="Token not priced by price providers")
        symbol = None
        name = None
    else:
        prices = price_by_contract(chain, [contract])
        if contract not in prices:
            raise HTTPException(status_code=400, detail="Token not priced by CoinGecko")
        meta = lookup_contract_metadata(chain, contract)
        symbol = meta.get("symbol") if isinstance(meta, dict) else None
        name = meta.get("name") if isinstance(meta, dict) else None
    row = db.execute(
        text(
            """
            INSERT INTO crypto_allowlist (chain, contract_address, symbol, name)
            VALUES (:chain, :contract, :symbol, :name)
            ON CONFLICT (chain, contract_address) DO UPDATE
              SET symbol = EXCLUDED.symbol, name = EXCLUDED.name
            RETURNING id, chain, contract_address, symbol, name, created_at
            """
        ),
        {"chain": chain, "contract": contract, "symbol": symbol, "name": name},
    ).mappings().one()
    db.commit()
    return dict(row)


_ADMIN_LAST_CALL: Optional[float] = None


@router.post("/refresh-now")
def refresh_now(
    background: BackgroundTasks,
    x_admin_key: Optional[str] = Header(None),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    admin_key = os.getenv("CRYPTO_ADMIN_KEY", "")
    if admin_key and x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    min_interval = int(os.getenv("CRYPTO_ADMIN_MIN_INTERVAL_SECONDS", "60"))
    global _ADMIN_LAST_CALL
    now = time.time()
    if _ADMIN_LAST_CALL and now - _ADMIN_LAST_CALL < min_interval:
        raise HTTPException(status_code=429, detail="Too many refresh requests")
    _ADMIN_LAST_CALL = now
    rows = db.execute(
        text("SELECT id FROM crypto_wallets w WHERE w.status = 'active' AND " + _wallet_scope_sql("w")),
        {"current_user_id": current_user.id},
    ).fetchall()
    for r in rows:
        background.add_task(_refresh_wallet, str(r[0]))
    return {"status": "queued", "wallets_refreshed": len(rows)}


@router.post("/debug/verify-sig")
def debug_verify_sig(
    payload: SolanaDebugVerifyIn,
    x_admin_key: Optional[str] = Header(None),
):
    admin_key = os.getenv("CRYPTO_ADMIN_KEY", "")
    if admin_key and x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        message_bytes = base64.b64decode(payload.message_bytes_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid message_bytes_b64: {exc}")
    message = message_bytes.decode("utf-8", errors="replace")
    result = verify_solana_signature_debug(message, payload.signature, payload.address)
    return {
        "ok": result.ok,
        "error": result.error,
        "matched_variant": result.matched_variant,
        "decoder": result.decoder,
        "decoded_len": result.decoded_len,
    }


@router.post("/debug/verify-bytes")
def debug_verify_bytes(
    payload: SolanaDebugVerifyIn,
    x_admin_key: Optional[str] = Header(None),
):
    admin_key = os.getenv("CRYPTO_ADMIN_KEY", "")
    if admin_key and x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        message_bytes = base64.b64decode(payload.message_bytes_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid message_bytes_b64: {exc}")
    result = verify_solana_signature_bytes_debug(message_bytes, payload.signature, payload.address)
    return {
        "ok": result.ok,
        "error": result.error,
        "matched_variant": result.matched_variant,
        "decoder": result.decoder,
        "decoded_len": result.decoded_len,
    }


@router.get("/solana/blockhash")
def solana_blockhash():
    try:
        result = _solana_rpc("getLatestBlockhash", [])
        return {"blockhash": result["value"]["blockhash"]}
    except HTTPException:
        result = _solana_rpc("getRecentBlockhash", [])
        return {"blockhash": result["value"]["blockhash"]}


@router.post("/solana/submit")
def solana_submit(payload: SolanaSubmitTxIn):
    try:
        tx_bytes = base64.b64decode(payload.tx_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid tx_b64: {exc}")
    raw_b64 = base64.b64encode(tx_bytes).decode("utf-8")
    # Use sendTransaction (widely supported). Some providers return 404 for sendRawTransaction.
    result = _solana_rpc("sendTransaction", [raw_b64, {"encoding": "base64"}])
    return {"signature": result}


@router.post("/solana/preflight")
def solana_preflight(payload: SolanaPreflightIn):
    try:
        tx_bytes = base64.b64decode(payload.tx_b64)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid tx_b64: {exc}")
    raw_b64 = base64.b64encode(tx_bytes).decode("utf-8")
    # Basic health check
    _solana_rpc("getHealth", [])
    # Preflight simulate
    result = _solana_rpc(
        "simulateTransaction",
        [raw_b64, {"sigVerify": False, "commitment": "processed", "encoding": "base64"}],
    )
    err = result.get("value", {}).get("err")
    if err:
        raise HTTPException(status_code=400, detail=f"Preflight failed: {err}")
    return {"ok": True}
