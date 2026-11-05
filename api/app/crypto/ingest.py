from __future__ import annotations

import os
import logging
from dataclasses import dataclass
import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import app_today, default_timezone_name, use_timezone
from app.core.job_runs import safe_error_summary
from app.crypto.adapters import TokenBalance, NativeBalance
from app.crypto.pricing import price_by_contract, price_by_mint, price_by_symbol
from app.crypto.providers import configured_price_provider_order, fetch_wallet_holdings
from app.services.user_preferences import effective_timezone
from app.wealth_rollup_dirty import mark_rollups_dirty


logger = logging.getLogger("capitalos.crypto")
DEFAULT_EVM_CHAINS = ["ethereum", "base", "arbitrum", "optimism", "mantle", "scroll"]
DEFAULT_EVM_TOKEN_CHAINS = ["ethereum", "base", "arbitrum", "optimism"]


@dataclass
class SnapshotResult:
    total_usd: float
    items: list[dict]
    source_versions: dict


def _as_of_date() -> date:
    """Today in the current timezone (``app.core.clock``). Callers date a
    wallet's snapshot through ``wallet_as_of_date``, which sets the owner's."""
    return app_today()


def wallet_timezone(db: Session, wallet_id: str) -> str:
    """The wallet owner's home timezone (#211, D-49); the app timezone for a
    wallet without an owner."""
    owner = db.execute(
        text("SELECT user_id FROM crypto_wallets WHERE id = :id"),
        {"id": wallet_id},
    ).scalar()
    if owner is None:
        return default_timezone_name()
    return effective_timezone(db, int(owner))


def wallet_as_of_date(db: Session, wallet_id: str) -> date:
    """The date a wallet snapshot taken now is filed under: today in the wallet
    owner's timezone (#211), whoever triggered the refresh (the owner's
    request, an admin's, or the scheduler, which has no user). Like a statement
    balance it is the owner's own holding, so it follows their calendar, not
    UTC market dates (D-44)."""
    with use_timezone(wallet_timezone(db, wallet_id)):
        return _as_of_date()


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

    if wallet["chain_type"] == "exchange" and wallet["chain"] == "coinbase":
        from app.crypto.coinbase import fetch_coinbase_snapshot

        return fetch_coinbase_snapshot()

    items: list[dict] = []
    total_usd = 0.0
    provider_names: set[str] = set()
    source_versions = {
        "holdings_provider": None,
        "price_provider": ",".join(configured_price_provider_order()),
    }

    if wallet["chain_type"] == "evm":
        allow_contracts = _allow_contracts()
        allow_by_chain = _allowlist_from_db(db)
        chains = _evm_chains()
        token_chains = _evm_token_chains()
        chain_errors: list[str] = []
        failed_chain_names: list[str] = []
        for chain in chains:
            try:
                native, tokens, provider_name = fetch_wallet_holdings("evm", chain, wallet["address"])
                provider_names.add(provider_name)
                if chain not in token_chains:
                    tokens = []
            except Exception as exc:
                # Stored on the snapshot: scrubbed, since provider errors can carry
                # an RPC URL with its key (#156).
                chain_errors.append(f"{chain}: {safe_error_summary(exc)}")
                failed_chain_names.append(chain)
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
                    native.price_source = ",".join(configured_price_provider_order())
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
                        token.price_source = ",".join(configured_price_provider_order())
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
        if chain_errors:
            if items:
                # A single misbehaving chain (e.g. an unsupported/rate-limited L2) must
                # not discard holdings already fetched from every other chain in the
                # sweep — record what failed so it stays debuggable, keep the rest.
                logger.warning(
                    "crypto_wallet_partial_chains",
                    extra={
                        "wallet_id": wallet_id,
                        "failed_chains": chain_errors,
                        "succeeded_chains": [c for c in chains if not any(e.startswith(f"{c}:") for e in chain_errors)],
                    },
                )
            else:
                # Every chain failed — there's nothing to distinguish this from total
                # provider outage, so refuse to persist a $0 snapshot over real history.
                raise RuntimeError("Crypto wallet refresh incomplete: " + "; ".join(chain_errors))
    else:
        native, tokens, provider_name = fetch_wallet_holdings(wallet["chain_type"], wallet["chain"], wallet["address"])
        provider_names.add(provider_name)
        allow_by_chain = _allowlist_from_db(db)
        if allow_by_chain.get("solana"):
            tokens = [
                t for t in tokens
                if t.contract_or_mint and t.contract_or_mint.lower() in allow_by_chain.get("solana", set())
            ]
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
                native.price_source = ",".join(configured_price_provider_order())
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
                    token.price_source = ",".join(configured_price_provider_order())
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

    source_versions["holdings_provider"] = ",".join(sorted(provider_names)) if provider_names else None
    source_versions["balances_provider"] = source_versions["holdings_provider"]
    source_versions["pricing_provider"] = source_versions["price_provider"]
    if wallet["chain_type"] == "evm" and chain_errors:
        source_versions["failed_chains"] = "; ".join(chain_errors)
        # The chains upsert_snapshot carries forward from the previous snapshot,
        # and the reason the wallet stays due for a retry (#156).
        source_versions["failed_chain_names"] = failed_chain_names
    return SnapshotResult(total_usd=total_usd, items=items, source_versions=source_versions)


_ITEM_COLUMNS = (
    "chain",
    "asset_kind",
    "contract_or_mint",
    "symbol",
    "name",
    "decimals",
    "raw_amount",
    "normalized_amount",
    "price_usd",
    "value_usd",
    "price_source",
)


def _load_versions(value) -> dict:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _carry_forward_failed_chains(db: Session, wallet_id: str, failed_chains: list[str]) -> tuple[list[dict], dict[str, str]]:
    """The previous snapshot's items on chains this refresh could not fetch, and
    how old each chain's data is (#156). A partial refresh then replaces today's
    snapshot without dropping those holdings; the wallet stays due for a retry."""
    if not failed_chains:
        return [], {}
    previous = db.execute(
        text(
            """
            SELECT id, fetched_at, source_versions
            FROM crypto_wallet_snapshots
            WHERE wallet_id = :wallet_id
            ORDER BY as_of_date DESC, fetched_at DESC, id DESC
            LIMIT 1
            """
        ),
        {"wallet_id": wallet_id},
    ).fetchone()
    if previous is None:
        return [], {}
    versions = _load_versions(previous[2])
    previous_stale = versions.get("stale_chains") if isinstance(versions.get("stale_chains"), dict) else {}
    holdings_as_of = versions.get("holdings_as_of") or (
        previous[1].isoformat() if isinstance(previous[1], datetime) else (str(previous[1]) if previous[1] else None)
    )
    rows = db.execute(
        text(
            "SELECT " + ", ".join(_ITEM_COLUMNS) + " FROM crypto_wallet_snapshot_items WHERE snapshot_id = :id ORDER BY id"
        ),
        {"id": int(previous[0])},
    ).mappings().all()
    wanted = set(failed_chains)
    items = [dict(row) for row in rows if row["chain"] in wanted]
    stale_as_of = {
        chain: str(previous_stale.get(chain) or holdings_as_of)
        for chain in failed_chains
        if previous_stale.get(chain) or holdings_as_of
    }
    return items, stale_as_of


def upsert_snapshot(db: Session, wallet_id: str, result: SnapshotResult) -> int:
    as_of = wallet_as_of_date(db, wallet_id)
    now = datetime.now(tz=timezone.utc)
    source_versions = dict(getattr(result, "source_versions", {}) or {})
    source_versions.setdefault("holdings_as_of", now.isoformat())
    source_versions.setdefault("price_as_of", now.isoformat())
    items = list(result.items)
    total_usd = result.total_usd
    failed_chains = [str(c) for c in (source_versions.get("failed_chain_names") or [])]
    if failed_chains:
        carried, stale_as_of = _carry_forward_failed_chains(db, wallet_id, failed_chains)
        items.extend(carried)
        total_usd = (total_usd or 0.0) + sum(float(item.get("value_usd") or 0.0) for item in carried)
        if stale_as_of:
            source_versions["stale_chains"] = stale_as_of
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
                "total_usd": total_usd,
                "source_versions": json.dumps(source_versions),
                "now": now,
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
                "total_usd": total_usd,
                "source_versions": json.dumps(source_versions),
                "now": now,
            },
        ).fetchone()
        snapshot_id = int(row[0])

    # Cap items
    max_items = int(os.getenv("CRYPTO_SNAPSHOT_MAX_ITEMS", "500"))
    if len(items) > max_items:
        logger.info(
            "crypto_snapshot_item_cap",
            extra={"wallet_id": wallet_id, "items": len(items), "cap": max_items},
        )
    wallet_row = db.execute(
        text("SELECT chain_type, chain FROM crypto_wallets WHERE id = :wallet_id"),
        {"wallet_id": wallet_id},
    ).mappings().one()
    for item in items[:max_items]:
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

    # A snapshot dated on/before a completed anchor (normally only on the
    # snapshot day itself) changes that month's History row (#138).
    mark_rollups_dirty(db, as_of, wallet_id=wallet_id, reason="crypto_snapshot")
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


DEFAULT_REFRESH_LOCK_STALE_MINUTES = 30.0


def refresh_lock_stale_after() -> timedelta:
    """How old a wallet's refresh flag may get before a new refresh takes it over (#135).

    A process killed mid-refresh never clears ``refresh_in_progress``; without a
    limit that wallet would never refresh again.
    """
    raw = os.getenv("CRYPTO_REFRESH_LOCK_STALE_MINUTES", "").strip()
    try:
        minutes = float(raw) if raw else DEFAULT_REFRESH_LOCK_STALE_MINUTES
    except ValueError:
        minutes = DEFAULT_REFRESH_LOCK_STALE_MINUTES
    if minutes <= 0:
        minutes = DEFAULT_REFRESH_LOCK_STALE_MINUTES
    return timedelta(minutes=minutes)


def acquire_refresh_lock(db: Session, wallet_id: str) -> bool:
    now = datetime.now(tz=timezone.utc)
    stale_after = refresh_lock_stale_after()
    previous = db.execute(
        text("SELECT refresh_in_progress, refresh_started_at FROM crypto_wallets WHERE id = :wallet_id"),
        {"wallet_id": wallet_id},
    ).fetchone()
    # One conditional UPDATE, so two refreshes can't both win: a free flag, or a
    # held one whose start is missing or older than the stale threshold.
    row = db.execute(
        text(
            """
            UPDATE crypto_wallets
            SET refresh_in_progress = TRUE, refresh_started_at = :now
            WHERE id = :wallet_id
              AND (
                refresh_in_progress = FALSE
                OR refresh_started_at IS NULL
                OR refresh_started_at < :stale_before
              )
            RETURNING id
            """
        ),
        {"wallet_id": wallet_id, "now": now, "stale_before": now - stale_after},
    ).fetchone()
    if row is not None and previous is not None and previous[0]:
        logger.warning(
            "crypto_stale_refresh_lock_taken_over",
            extra={
                "event": "crypto_stale_refresh_lock_taken_over",
                "provider": "crypto",
                "platform": "crypto",
                "wallet_id": wallet_id,
                "refresh_started_at": str(previous[1]) if previous[1] is not None else None,
                "stale_after_seconds": int(stale_after.total_seconds()),
            },
        )
    return row is not None


def release_refresh_lock(db: Session, wallet_id: str) -> None:
    db.execute(
        text(
            "UPDATE crypto_wallets SET refresh_in_progress = FALSE WHERE id = :wallet_id"
        ),
        {"wallet_id": wallet_id},
    )
