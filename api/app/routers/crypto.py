from __future__ import annotations

import os
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
import time

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.crypto.verify import verify_evm_signature, verify_solana_signature
from app.crypto.ingest import ingest_wallet, upsert_snapshot, should_refresh, acquire_refresh_lock, release_refresh_lock
from app.crypto.pricing import price_by_contract, lookup_contract_metadata
from app.fx import get_rates

router = APIRouter(prefix="/crypto", tags=["crypto"])
logger = logging.getLogger("capitalos.crypto")


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


def _nonce_ttl() -> int:
    return int(os.getenv("CRYPTO_SIGNING_NONCE_TTL_SECONDS", "600"))


def _message(nonce: str, address: str, chain: str) -> str:
    return f"CapitalOS wallet verification\nNonce: {nonce}\nAddress: {address}\nChain: {chain}\nIssuedAt: {datetime.now(tz=timezone.utc).isoformat()}"


def _validate_address(chain_type: str, address: str) -> None:
    if chain_type == "evm":
        if not address.startswith("0x") or len(address) < 42:
            raise HTTPException(status_code=400, detail="Invalid EVM address")
    elif chain_type == "solana":
        if len(address) < 32:
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


@router.post("/wallets/init")
def wallet_init(payload: WalletInitIn, db: Session = Depends(get_db)):
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

    db.execute(
        text(
            """
            INSERT INTO crypto_wallet_verifications (wallet_id, chain_type, chain, address, nonce, message, expires_at)
            VALUES (NULL, :chain_type, :chain, :address, :nonce, :message, :expires_at)
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
    )
    db.commit()

    return {
        "chain_type": payload.chain_type,
        "chain": payload.chain,
        "address": normalized_address,
        "message_to_sign": message,
        "nonce": nonce,
        "expires_at": expires_at.isoformat(),
    }


@router.post("/wallets/verify")
def wallet_verify(payload: WalletVerifyIn, background: BackgroundTasks, db: Session = Depends(get_db)):
    _validate_address(payload.chain_type, payload.address)
    _validate_chain(payload.chain_type, payload.chain)
    normalized_address = payload.address.lower() if payload.chain_type == "evm" else payload.address

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
        result = verify_solana_signature(ver["message"], payload.signature, payload.address)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "Invalid signature")

    wallet = db.execute(
        text(
            "SELECT id FROM crypto_wallets WHERE chain_type = :chain_type AND chain = :chain AND address = :address"
        ),
        {
            "chain_type": payload.chain_type,
            "chain": payload.chain,
            "address": normalized_address,
        },
    ).fetchone()
    if wallet:
        wallet_id = wallet[0]
        db.execute(
            text(
                "UPDATE crypto_wallets SET status = 'active', verified_at = :now WHERE id = :id"
            ),
            {"id": wallet_id, "now": datetime.now(tz=timezone.utc)},
        )
    else:
        row = db.execute(
            text(
                """
                INSERT INTO crypto_wallets (chain_type, chain, address, status, created_at, verified_at)
                VALUES (:chain_type, :chain, :address, 'active', :now, :now)
                RETURNING id
                """
            ),
            {
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
def list_wallets(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT id, chain_type, chain, address, label, status, created_at, verified_at FROM crypto_wallets ORDER BY created_at DESC"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/summary")
def crypto_summary(
    base_currency: str = "USD",
    background: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    if background is None:
        background = BackgroundTasks()
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
            """
        )
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
        if should_refresh(fetched_at):
            is_stale = True
            if acquire_refresh_lock(db, r["id"]):
                refresh_triggered = True
                background.add_task(_refresh_wallet, str(r["id"]))

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
            ORDER BY i.value_usd DESC NULLS LAST
            LIMIT 50
            """
        )
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
            GROUP BY s.wallet_id, i.chain
            ORDER BY total_usd DESC NULLS LAST
            """
        )
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
def crypto_tokens(db: Session = Depends(get_db)):
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
            ORDER BY i.value_usd DESC NULLS LAST
            """
        )
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
        text("SELECT id FROM crypto_wallets WHERE status = 'active'")
    ).fetchall()
    for r in rows:
        background.add_task(_refresh_wallet, str(r[0]))
    return {"status": "queued", "wallets_refreshed": len(rows)}
