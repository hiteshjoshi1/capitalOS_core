from __future__ import annotations

import os
import logging
import hashlib
import base64
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import time
import httpx

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, allow_legacy_null_ownership, require_current_user
from app.crypto.coinbase import coinbase_configured, ensure_coinbase_wallet
from app.crypto.refresh import refresh_wallet_snapshot
from app.db.session import get_db
from app.crypto.verify import (
    verify_evm_signature,
    verify_solana_signature,
    verify_solana_signature_debug,
    verify_solana_signature_bytes_debug,
)
from app.crypto.ingest import acquire_refresh_lock, ingest_wallet, release_refresh_lock, upsert_snapshot
from app.crypto.pricing import lookup_contract_metadata, price_by_contract, price_by_mint
from app.fx import get_rates

_STALE_THRESHOLD_SECONDS = 24 * 3600

router = APIRouter(prefix="/crypto", tags=["crypto"], dependencies=[Depends(require_current_user)])
logger = logging.getLogger("capitalos.crypto.router")
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
        wallet = db.execute(
            text("SELECT user_id FROM crypto_wallets WHERE id = :wallet_id"),
            {"wallet_id": wallet_id},
        ).mappings().one_or_none()
        user_id = int(wallet["user_id"]) if wallet and wallet["user_id"] is not None else None
        refresh_wallet_snapshot(db, wallet_id, user_id=user_id, automatic=False)
    finally:
        db.close()


def _parse_month_start(month: str | None) -> datetime:
    if not month:
        now = datetime.now(tz=timezone.utc)
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        return datetime.strptime(f"{month}-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM.") from exc


def _add_months(dt: datetime, months: int) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=year, month=month)


def _snapshot_day() -> int:
    raw = os.getenv("SNAPSHOT_DAY", "1")
    try:
        day = int(raw)
    except ValueError:
        day = 1
    return max(1, min(day, 31))


def _anchor_date(month_start: datetime) -> datetime:
    next_month_start = _add_months(month_start, 1).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = (_add_months(next_month_start, 1) - timedelta(days=1)).day
    return next_month_start.replace(day=min(_snapshot_day(), last_day))


def _month_window(end_month_start: datetime, months: int = 6) -> list[datetime]:
    return [_add_months(end_month_start, offset) for offset in range(-(months - 1), 1)]


def _iso_date_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _latest_wallet_rows(
    db: Session,
    current_user_id: int,
    *,
    as_of_date: datetime | None = None,
) -> list[dict[str, Any]]:
    date_filter = "WHERE s.as_of_date <= :as_of_date" if as_of_date else ""
    rows = db.execute(
        text(
            f"""
            WITH latest AS (
              SELECT s.wallet_id, MAX(s.as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots s
              JOIN crypto_wallets w ON w.id = s.wallet_id
              {date_filter}
              {"AND" if as_of_date else "WHERE"} w.status = 'active'
                AND """
            + _wallet_scope_sql("w")
            + """
              GROUP BY s.wallet_id
            )
            SELECT w.id, w.chain_type, w.chain, w.address, w.label, s.total_usd, s.fetched_at, s.as_of_date
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
        {
            "current_user_id": current_user_id,
            **({"as_of_date": as_of_date.date()} if as_of_date else {}),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _latest_wallet_items(
    db: Session,
    current_user_id: int,
    *,
    as_of_date: datetime | None = None,
) -> list[dict[str, Any]]:
    date_filter = "WHERE s.as_of_date <= :as_of_date" if as_of_date else ""
    rows = db.execute(
        text(
            f"""
            WITH latest AS (
              SELECT s.wallet_id, MAX(s.as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots s
              JOIN crypto_wallets w ON w.id = s.wallet_id
              {date_filter}
              {"AND" if as_of_date else "WHERE"} w.status = 'active'
                AND """
            + _wallet_scope_sql("w")
            + """
              GROUP BY s.wallet_id
            )
            SELECT
              s.wallet_id,
              s.as_of_date,
              w.address,
              w.label,
              w.chain_type AS wallet_chain_type,
              w.chain AS wallet_chain,
              i.symbol,
              i.chain,
              i.chain_type,
              i.normalized_amount,
              i.price_usd,
              i.value_usd
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
        {
            "current_user_id": current_user_id,
            **({"as_of_date": as_of_date.date()} if as_of_date else {}),
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _latest_and_previous_wallet_items(db: Session, current_user_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = db.execute(
        text(
            """
            WITH ranked AS (
              SELECT
                s.id,
                s.wallet_id,
                s.as_of_date,
                ROW_NUMBER() OVER (
                  PARTITION BY s.wallet_id
                  ORDER BY s.as_of_date DESC, s.fetched_at DESC NULLS LAST, s.id DESC
                ) AS rn
              FROM crypto_wallet_snapshots s
              JOIN crypto_wallets w ON w.id = s.wallet_id
              WHERE w.status = 'active'
                AND """
            + _wallet_scope_sql("w")
            + """
            )
            SELECT
              r.wallet_id,
              r.as_of_date,
              r.rn,
              w.address,
              w.label,
              w.chain_type AS wallet_chain_type,
              w.chain AS wallet_chain,
              i.symbol,
              i.chain,
              i.chain_type,
              i.normalized_amount,
              i.price_usd,
              i.value_usd
            FROM ranked r
            JOIN crypto_wallets w ON w.id = r.wallet_id
            JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = r.id
            WHERE r.rn <= 2
              AND """
            + _wallet_scope_sql("w")
            + """
            """
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    current_items: list[dict[str, Any]] = []
    previous_items: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        if int(record["rn"]) == 1:
            current_items.append(record)
        elif int(record["rn"]) == 2:
            previous_items.append(record)
    return current_items, previous_items


def _crypto_total_and_freshness(wallet_rows: list[dict[str, Any]]) -> tuple[float, datetime | None, bool]:
    total_usd = 0.0
    last_refreshed = None
    is_stale = False
    for row in wallet_rows:
        if row.get("total_usd") is not None:
            total_usd += float(row["total_usd"])
        fetched_at = row.get("fetched_at")
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
    return total_usd, last_refreshed, is_stale


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
    month: str | None = None,
    base_currency: str = "USD",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    selected_month_start = _parse_month_start(month)
    snapshot_anchor = _anchor_date(selected_month_start)

    wallet_rows = _latest_wallet_rows(db, current_user.id)
    snapshot_wallet_rows = _latest_wallet_rows(db, current_user.id, as_of_date=snapshot_anchor)
    current_items, previous_items = _latest_and_previous_wallet_items(db, current_user.id)
    snapshot_items = _latest_wallet_items(db, current_user.id, as_of_date=snapshot_anchor)

    total_usd, last_refreshed, is_stale = _crypto_total_and_freshness(wallet_rows)
    snapshot_total_usd, _, _ = _crypto_total_and_freshness(snapshot_wallet_rows)
    rate = get_rates(datetime.now(tz=timezone.utc), base_currency, {"USD"}).get("USD", 1.0)
    total_base = total_usd * rate
    snapshot_total_base = snapshot_total_usd * rate
    snapshot_delta_base = total_base - snapshot_total_base

    previous_lookup = {
        (str(item["wallet_id"]), str(item.get("symbol") or "").upper(), str(item.get("chain") or "").lower()): item
        for item in previous_items
    }
    snapshot_lookup = {
        (str(item["wallet_id"]), str(item.get("symbol") or "").upper(), str(item.get("chain") or "").lower()): item
        for item in snapshot_items
    }

    holdings: list[dict[str, Any]] = []
    eth_group = {"eth", "weth", "steth", "wsteth", "eeth", "weeth"}
    eth_usd = 0.0
    other_usd = 0.0
    token_count = 0
    priced_count = 0
    chain_totals: dict[str, float] = {}

    for row in sorted(current_items, key=lambda item: float(item.get("value_usd") or 0.0), reverse=True):
        wallet_id = str(row["wallet_id"])
        symbol = str(row.get("symbol") or "").upper()
        chain = str(row.get("chain") or "").lower()
        key = (wallet_id, symbol, chain)
        previous = previous_lookup.get(key)
        snapshot_item = snapshot_lookup.get(key)
        current_amount = float(row["normalized_amount"]) if row.get("normalized_amount") is not None else 0.0
        current_price_usd = float(row["price_usd"]) if row.get("price_usd") is not None else None
        current_value_usd = float(row["value_usd"]) if row.get("value_usd") is not None else 0.0
        previous_price_usd = float(previous["price_usd"]) if previous and previous.get("price_usd") is not None else None
        previous_value_usd = float(previous["value_usd"]) if previous and previous.get("value_usd") is not None else None
        snapshot_value_usd = float(snapshot_item["value_usd"]) if snapshot_item and snapshot_item.get("value_usd") is not None else 0.0
        token_count += 1
        if current_value_usd > 0:
            priced_count += 1
        if symbol.lower() in eth_group:
            eth_usd += current_value_usd
        else:
            other_usd += current_value_usd
        chain_totals[chain or "unknown"] = chain_totals.get(chain or "unknown", 0.0) + current_value_usd
        holdings.append(
            {
                "symbol": symbol,
                "chain": chain,
                "amount": current_amount,
                "value_usd": current_value_usd,
                "value_base": current_value_usd * rate,
                "asset_class": "CRYPTO",
                "wallet_id": wallet_id,
                "wallet_label": row.get("label"),
                "wallet_address": row.get("address"),
                "price_usd": current_price_usd,
                "price_change_usd": (current_price_usd - previous_price_usd)
                if current_price_usd is not None and previous_price_usd is not None
                else None,
                "price_change_pct": ((current_price_usd - previous_price_usd) / previous_price_usd)
                if current_price_usd is not None and previous_price_usd not in (None, 0)
                else None,
                "value_change_base": (current_value_usd - previous_value_usd) * rate
                if previous_value_usd is not None
                else None,
                "value_change_pct": ((current_value_usd - previous_value_usd) / previous_value_usd)
                if previous_value_usd not in (None, 0)
                else None,
                "snapshot_value_base": snapshot_value_usd * rate,
                "snapshot_delta_base": (current_value_usd - snapshot_value_usd) * rate,
                "snapshot_delta_pct": ((current_value_usd - snapshot_value_usd) / snapshot_value_usd)
                if snapshot_value_usd > 0
                else None,
            }
        )

    eth = next((item for item in holdings if item["symbol"] == "ETH"), None)
    sol = next((item for item in holdings if item["symbol"] == "SOL"), None)
    wallet_total = sum(float(row.get("total_usd") or 0.0) for row in wallet_rows)
    wallet_exposure = [
        {
            "wallet_id": str(row["id"]),
            "label": row.get("label"),
            "address": row.get("address"),
            "chain_type": row.get("chain_type"),
            "chain": row.get("chain"),
            "total_usd": float(row["total_usd"]) if row.get("total_usd") is not None else 0.0,
            "total_base": (float(row["total_usd"]) if row.get("total_usd") is not None else 0.0) * rate,
            "percent": (
                (float(row["total_usd"]) / wallet_total) * 100
                if wallet_total > 0 and row.get("total_usd") is not None
                else 0.0
            ),
        }
        for row in wallet_rows
        if row.get("total_usd") is not None
    ]
    chain_exposure = [
        {
            "chain": chain,
            "total_usd": total_chain_usd,
            "total_base": total_chain_usd * rate,
            "percent": (total_chain_usd / total_usd) * 100 if total_usd > 0 else 0.0,
        }
        for chain, total_chain_usd in sorted(chain_totals.items(), key=lambda item: item[1], reverse=True)
    ]
    wallet_chain_exposure = [
        {
            "wallet_id": item["wallet_id"],
            "chain": item["chain"],
            "total_usd": item["value_usd"],
            "total_base": item["value_base"],
        }
        for item in holdings
    ]

    trend = []
    for candidate_month in _month_window(selected_month_start, months=6):
        candidate_anchor = _anchor_date(candidate_month)
        candidate_wallet_rows = _latest_wallet_rows(db, current_user.id, as_of_date=candidate_anchor)
        candidate_total_usd, _, _ = _crypto_total_and_freshness(candidate_wallet_rows)
        trend.append(
            {
                "month": candidate_month.strftime("%Y-%m"),
                "value": candidate_total_usd * rate if candidate_wallet_rows else None,
            }
        )

    snapshot_dates = [row.get("as_of_date") for row in snapshot_wallet_rows if row.get("as_of_date") is not None]
    snapshot_as_of = _iso_date_value(min(snapshot_dates)) if snapshot_dates else None

    return {
        "month": selected_month_start.strftime("%Y-%m"),
        "snapshot_day": _snapshot_day(),
        "snapshot_as_of": snapshot_as_of,
        "total_crypto_usd": total_usd,
        "total_crypto_base": total_base,
        "snapshot_total_base": snapshot_total_base,
        "snapshot_total_usd": snapshot_total_usd,
        "snapshot_delta_base": snapshot_delta_base,
        "snapshot_delta_pct": (snapshot_delta_base / snapshot_total_base) if snapshot_total_base > 0 else None,
        "base_currency": base_currency,
        "eth_exposure_usd": eth_usd,
        "eth_exposure_base": eth_usd * rate,
        "token_exposure_usd": other_usd,
        "token_exposure_base": other_usd * rate,
        "token_count": token_count,
        "priced_token_count": priced_count,
        "trend": trend,
        "eth": {
            "balance": float(eth["amount"]) if eth is not None else 0,
            "value_usd": float(eth["value_usd"]) if eth is not None else 0,
            "value_base": float(eth["value_base"]) if eth is not None else 0,
        },
        "sol": {
            "balance": float(sol["amount"]) if sol is not None else 0,
            "value_usd": float(sol["value_usd"]) if sol is not None else 0,
            "value_base": float(sol["value_base"]) if sol is not None else 0,
        },
        "top5_holdings": holdings[:5],
        "top_holdings": holdings,
        "wallet_exposure": wallet_exposure,
        "chain_exposure": chain_exposure,
        "wallet_chain_exposure": wallet_chain_exposure,
        "last_refreshed_at": last_refreshed.isoformat() if last_refreshed else None,
        "is_stale": is_stale,
        "refresh_triggered": False,
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
    if coinbase_configured():
        ensure_coinbase_wallet(db, current_user.id)
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
