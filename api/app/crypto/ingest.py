from __future__ import annotations

import os
import logging
from dataclasses import dataclass
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from app.crypto.adapters import EvmAlchemyAdapter, SolanaHeliusAdapter, TokenBalance, NativeBalance
from app.crypto.pricing import price_by_contract, price_by_mint, price_by_symbol


SINGAPORE_TZ = ZoneInfo("Asia/Singapore")
logger = logging.getLogger("capitalos.crypto")
DEFAULT_EVM_CHAINS = ["ethereum", "base", "arbitrum", "optimism", "mantle", "scroll"]
DEFAULT_EVM_TOKEN_CHAINS = ["ethereum", "base", "arbitrum", "optimism"]


@dataclass
class SnapshotResult:
    total_usd: float
    items: list[dict]
    source_versions: dict


def _now_sg() -> datetime:
    return datetime.now(tz=SINGAPORE_TZ)


def _as_of_date() -> datetime.date:
    return _now_sg().date()


def _normalize_price(balance: TokenBalance | NativeBalance, price: float | None) -> Tuple[float | None, float | None]:
    if price is None or balance.normalized_amount is None:
        return None, None
    value = balance.normalized_amount * price
    return price, value


def _fetch_prices(chain_type: str, chain: str, tokens: List[TokenBalance]) -> Dict[str, float]:
    if chain_type == "evm":
        contracts = [t.contract_or_mint for t in tokens if t.contract_or_mint]
        return price_by_contract(chain, contracts)
    if chain_type == "solana":
        mints = [t.contract_or_mint for t in tokens if t.contract_or_mint]
        return price_by_mint(mints)
    return {}


def _adapter(chain_type: str, chain: str):
    if chain_type == "evm":
        return EvmAlchemyAdapter(chain)
    if chain_type == "solana":
        return SolanaHeliusAdapter()
    raise ValueError(f"Unsupported chain_type: {chain_type}")


def _evm_chains() -> list[str]:
    raw = os.getenv("CRYPTO_EVM_CHAINS", "")
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return DEFAULT_EVM_CHAINS


def _evm_token_chains() -> set[str]:
    raw = os.getenv("CRYPTO_EVM_TOKEN_CHAINS", "")
    if raw:
        return {c.strip() for c in raw.split(",") if c.strip()}
    return set(DEFAULT_EVM_TOKEN_CHAINS)


def _allow_contracts() -> set[str]:
    raw = os.getenv("CRYPTO_ALLOW_CONTRACTS", "")
    if not raw:
        return set()
    return {c.strip().lower() for c in raw.split(",") if c.strip()}


def _allowlist_from_db(db: Session) -> dict[str, set[str]]:
    rows = db.execute(
        text("SELECT chain, contract_address FROM crypto_allowlist")
    ).mappings().all()
    allow: dict[str, set[str]] = {}
    for r in rows:
        chain = (r["chain"] or "").lower()
        contract = (r["contract_address"] or "").lower()
        if not chain or not contract:
            continue
        allow.setdefault(chain, set()).add(contract)
    return allow


def ingest_wallet(db: Session, wallet_id: str) -> SnapshotResult:
    wallet = db.execute(
        text("SELECT id, chain_type, chain, address FROM crypto_wallets WHERE id = :id"),
        {"id": wallet_id},
    ).mappings().one_or_none()
    if not wallet:
        raise ValueError("Wallet not found")

    items: list[dict] = []
    total_usd = 0.0
    source_versions = {
        "balances_provider": "alchemy" if wallet["chain_type"] == "evm" else "helius",
        "pricing_provider": "coingecko",
    }

    if wallet["chain_type"] == "evm":
        allow_contracts = _allow_contracts()
        allow_by_chain = _allowlist_from_db(db)
        chains = _evm_chains()
        token_chains = _evm_token_chains()
        for chain in chains:
            try:
                adapter = _adapter("evm", chain)
                native = adapter.get_native_balance(wallet["address"])
                tokens = (
                    adapter.get_token_balances(wallet["address"])
                    if chain in token_chains
                    else []
                )
            except Exception as exc:
                logger.warning(
                    "crypto_chain_fetch_failed",
                    extra={"wallet_id": wallet_id, "chain": chain, "error": str(exc)},
                )
                continue
            raw_count = len(tokens)
            if allow_contracts or allow_by_chain.get(chain):
                tokens = [
                    t for t in tokens
                    if t.contract_or_mint
                    and (
                        t.contract_or_mint.lower() in allow_contracts
                        or t.contract_or_mint.lower() in allow_by_chain.get(chain, set())
                    )
                ]
            if os.getenv("CRYPTO_DEBUG", "0") == "1":
                logger.info(
                    "crypto_allowlist_filter",
                    extra={
                        "chain": chain,
                        "raw_tokens": raw_count,
                        "filtered_tokens": len(tokens),
                        "allow_env": len(allow_contracts),
                        "allow_db": len(allow_by_chain.get(chain, set())),
                    },
                )
            try:
                prices = _fetch_prices("evm", chain, tokens)
            except Exception:
                prices = {}
            price = native.price_usd
            value = native.value_usd
            if price is None:
                symbol_price = price_by_symbol(native.symbol)
                if symbol_price is not None:
                    price, value = _normalize_price(native, symbol_price)
                    native.price_source = "coingecko_symbol"
            if value is not None:
                total_usd += value
                items.append(
                    {
                        "asset_kind": "native",
                        "contract_or_mint": None,
                        "symbol": native.symbol,
                        "name": native.symbol,
                        "decimals": native.decimals,
                        "raw_amount": native.raw_amount,
                        "normalized_amount": native.normalized_amount,
                        "price_usd": price if price is not None else native.price_usd,
                        "value_usd": value,
                        "price_source": native.price_source,
                        "chain": chain,
                    }
                )

            for token in tokens:
                price = token.price_usd
                value = token.value_usd
                if price is None and token.contract_or_mint:
                    price = prices.get(token.contract_or_mint.lower())
                    if price:
                        value = token.normalized_amount * price if token.normalized_amount is not None else None
                        token.price_source = "coingecko_contract"
                # No fallback pricing: rely on API prices only.
                if value is None and price is not None and token.normalized_amount is not None:
                    value = token.normalized_amount * price
                if value is not None:
                    total_usd += value
                items.append(
                    {
                        "asset_kind": "erc20",
                        "contract_or_mint": token.contract_or_mint,
                        "symbol": token.symbol,
                        "name": token.name,
                        "decimals": token.decimals,
                        "raw_amount": token.raw_amount,
                        "normalized_amount": token.normalized_amount,
                        "price_usd": price,
                        "value_usd": value,
                        "price_source": token.price_source,
                        "chain": chain,
                    }
                )
    else:
        adapter = _adapter(wallet["chain_type"], wallet["chain"])
        native = adapter.get_native_balance(wallet["address"])
        tokens = adapter.get_token_balances(wallet["address"])
        try:
            prices = _fetch_prices(wallet["chain_type"], wallet["chain"], tokens)
        except Exception:
            prices = {}

        price = native.price_usd
        value = native.value_usd
        if price is None:
            symbol_price = price_by_symbol(native.symbol)
            if symbol_price is not None:
                price, value = _normalize_price(native, symbol_price)
                native.price_source = "coingecko_symbol"
        if value is not None:
            total_usd += value
            items.append(
                {
                    "asset_kind": "native",
                    "contract_or_mint": None,
                    "symbol": native.symbol,
                    "name": native.symbol,
                    "decimals": native.decimals,
                    "raw_amount": native.raw_amount,
                    "normalized_amount": native.normalized_amount,
                    "price_usd": price if price is not None else native.price_usd,
                    "value_usd": value,
                    "price_source": native.price_source,
                    "chain": wallet["chain"],
                }
            )

        for token in tokens:
            price = token.price_usd
            value = token.value_usd
            if price is None and token.contract_or_mint:
                price = prices.get(token.contract_or_mint.lower())
                if price:
                    value = token.normalized_amount * price if token.normalized_amount is not None else None
                    token.price_source = "coingecko_mint"
            if value is not None:
                total_usd += value
            items.append(
                {
                    "asset_kind": "spl",
                    "contract_or_mint": token.contract_or_mint,
                    "symbol": token.symbol,
                    "name": token.name,
                    "decimals": token.decimals,
                    "raw_amount": token.raw_amount,
                    "normalized_amount": token.normalized_amount,
                    "price_usd": price,
                    "value_usd": value,
                    "price_source": token.price_source,
                    "chain": wallet["chain"],
                }
            )

    return SnapshotResult(total_usd=total_usd, items=items, source_versions=source_versions)


def upsert_snapshot(db: Session, wallet_id: str, result: SnapshotResult) -> int:
    as_of = _as_of_date()
    existing = db.execute(
        text(
            "SELECT id FROM crypto_wallet_snapshots WHERE wallet_id = :wallet_id AND as_of_date = :as_of"
        ),
        {"wallet_id": wallet_id, "as_of": as_of},
    ).fetchone()
    if existing:
        snapshot_id = int(existing[0])
        db.execute(
            text(
                "UPDATE crypto_wallet_snapshots SET fetched_at = :now, total_usd = :total_usd, source_versions = :source_versions WHERE id = :id"
            ),
            {
                "id": snapshot_id,
                "total_usd": result.total_usd,
                "source_versions": json.dumps(result.source_versions),
                "now": datetime.now(tz=timezone.utc),
            },
        )
        db.execute(
            text("DELETE FROM crypto_wallet_snapshot_items WHERE snapshot_id = :id"),
            {"id": snapshot_id},
        )
    else:
        row = db.execute(
            text(
                "INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd, source_versions) "
                "VALUES (:wallet_id, :as_of_date, :now, :total_usd, :source_versions) RETURNING id"
            ),
            {
                "wallet_id": wallet_id,
                "as_of_date": as_of,
                "total_usd": result.total_usd,
                "source_versions": json.dumps(result.source_versions),
                "now": datetime.now(tz=timezone.utc),
            },
        ).fetchone()
        snapshot_id = int(row[0])

    # Cap items
    max_items = int(os.getenv("CRYPTO_SNAPSHOT_MAX_ITEMS", "500"))
    if len(result.items) > max_items:
        logger.info(
            "crypto_snapshot_item_cap",
            extra={"wallet_id": wallet_id, "items": len(result.items), "cap": max_items},
        )
    wallet_row = db.execute(
        text("SELECT chain_type, chain FROM crypto_wallets WHERE id = :wallet_id"),
        {"wallet_id": wallet_id},
    ).mappings().one()
    for item in result.items[:max_items]:
        db.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                (snapshot_id, chain_type, chain, asset_kind, contract_or_mint, symbol, name, decimals, raw_amount, normalized_amount, price_usd, value_usd, price_source)
                VALUES
                (:snapshot_id, :chain_type, :chain, :asset_kind, :contract_or_mint, :symbol, :name, :decimals, :raw_amount, :normalized_amount, :price_usd, :value_usd, :price_source)
                """
            ),
            {
                "snapshot_id": snapshot_id,
                "chain_type": wallet_row["chain_type"],
                "chain": item.get("chain") or wallet_row["chain"],
                "asset_kind": item["asset_kind"],
                "contract_or_mint": item["contract_or_mint"],
                "symbol": item["symbol"],
                "name": item["name"],
                "decimals": item["decimals"],
                "raw_amount": item["raw_amount"],
                "normalized_amount": item["normalized_amount"],
                "price_usd": item["price_usd"],
                "value_usd": item["value_usd"],
                "price_source": item["price_source"],
            },
        )

    return snapshot_id


def should_refresh(last_fetched_at: datetime | None) -> bool:
    if not last_fetched_at:
        return True
    if isinstance(last_fetched_at, str):
        try:
            last_fetched_at = datetime.fromisoformat(last_fetched_at)
        except ValueError:
            return True
    if last_fetched_at.tzinfo is None:
        last_fetched_at = last_fetched_at.replace(tzinfo=timezone.utc)
    return (datetime.now(tz=timezone.utc) - last_fetched_at) > timedelta(hours=24)


def acquire_refresh_lock(db: Session, wallet_id: str) -> bool:
    row = db.execute(
        text(
            """
            UPDATE crypto_wallets
            SET refresh_in_progress = TRUE, refresh_started_at = :now
            WHERE id = :wallet_id AND refresh_in_progress = FALSE
            RETURNING id
            """
        ),
        {"wallet_id": wallet_id, "now": datetime.now(tz=timezone.utc)},
    ).fetchone()
    return row is not None


def release_refresh_lock(db: Session, wallet_id: str) -> None:
    db.execute(
        text(
            "UPDATE crypto_wallets SET refresh_in_progress = FALSE WHERE id = :wallet_id"
        ),
        {"wallet_id": wallet_id},
    )
