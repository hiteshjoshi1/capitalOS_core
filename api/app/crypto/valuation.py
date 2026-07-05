from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import allow_legacy_null_ownership
from app.crypto.ingest import should_refresh
from app.crypto.pricing import price_by_contract, price_by_mint, price_by_symbol
from app.crypto.providers import configured_price_provider_order

logger = logging.getLogger("capitalos.crypto.valuation")


def wallet_scope_sql(alias: str = "w") -> str:
    if allow_legacy_null_ownership():
        return f"({alias}.user_id = :current_user_id OR {alias}.user_id IS NULL)"
    return f"{alias}.user_id = :current_user_id"


def _parse_source_versions(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _snapshot_meta(row: dict[str, Any]) -> dict[str, Any]:
    versions = _parse_source_versions(row.get("source_versions"))
    fetched_at = _parse_dt(row.get("fetched_at"))
    holdings_as_of = _parse_dt(versions.get("holdings_as_of")) or fetched_at
    price_as_of = _parse_dt(versions.get("price_as_of")) or fetched_at
    return {
        "holdings_as_of": holdings_as_of,
        "price_as_of": price_as_of,
        "holdings_provider": versions.get("holdings_provider") or versions.get("balances_provider"),
        "price_provider": versions.get("price_provider") or versions.get("pricing_provider"),
    }


def _ranked_snapshots_sql(as_of_filter: bool) -> str:
    date_predicate = "AND s.as_of_date <= :as_of_date" if as_of_filter else ""
    return (
        """
        WITH ranked AS (
          SELECT
            s.id,
            s.wallet_id,
            s.as_of_date,
            s.fetched_at,
            s.total_usd,
            s.source_versions,
            ROW_NUMBER() OVER (
              PARTITION BY s.wallet_id
              ORDER BY s.as_of_date DESC, s.fetched_at DESC, s.id DESC
            ) AS rn
          FROM crypto_wallet_snapshots s
          JOIN crypto_wallets w ON w.id = s.wallet_id
          WHERE w.status = 'active'
        """
        + f" {date_predicate} AND "
        + wallet_scope_sql("w")
        + """
        )
        """
    )


def latest_wallet_valuation(
    db: Session,
    current_user_id: int,
    *,
    as_of_date: date | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"current_user_id": current_user_id}
    if as_of_date is not None:
        params["as_of_date"] = as_of_date
    ranked = _ranked_snapshots_sql(as_of_date is not None)
    wallet_rows = db.execute(
        text(
            ranked
            + """
            SELECT
              w.id,
              w.chain_type,
              w.chain,
              w.address,
              w.label,
              r.id AS snapshot_id,
              r.total_usd AS snapshot_total_usd,
              r.fetched_at,
              r.as_of_date,
              r.source_versions
            FROM crypto_wallets w
            LEFT JOIN ranked r ON r.wallet_id = w.id AND r.rn = 1
            WHERE w.status = 'active'
              AND """
            + wallet_scope_sql("w")
        ),
        params,
    ).mappings().all()
    wallets = [dict(row) for row in wallet_rows]
    snapshot_ids = [int(row["snapshot_id"]) for row in wallets if row.get("snapshot_id") is not None]
    if not snapshot_ids:
        return {
            "wallets": [],
            "items": [],
            "total_usd": 0.0,
            "holdings_as_of": None,
            "price_as_of": None,
            "stale_holdings": bool(wallets),
            "stale_prices": bool(wallets),
        }

    item_rows = db.execute(
        text(
            ranked
            + """
            SELECT
              r.wallet_id,
              r.as_of_date,
              r.fetched_at,
              r.source_versions,
              w.address,
              w.label,
              w.chain_type AS wallet_chain_type,
              w.chain AS wallet_chain,
              i.symbol,
              i.chain,
              i.chain_type,
              i.contract_or_mint,
              i.normalized_amount,
              i.price_usd,
              i.value_usd,
              i.price_source
            FROM ranked r
            JOIN crypto_wallets w ON w.id = r.wallet_id
            JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = r.id
            WHERE r.rn = 1
              AND """
            + wallet_scope_sql("w")
            + """
            ORDER BY i.value_usd DESC NULLS LAST
            """
        ),
        params,
    ).mappings().all()
    items = [dict(row) for row in item_rows]

    totals_by_wallet: dict[str, float] = {}
    for item in items:
        wallet_id = str(item["wallet_id"])
        totals_by_wallet[wallet_id] = totals_by_wallet.get(wallet_id, 0.0) + float(item.get("value_usd") or 0.0)

    enriched_wallets: list[dict[str, Any]] = []
    holdings_dates: list[datetime] = []
    price_dates: list[datetime] = []
    stale_holdings = False
    stale_prices = False
    total_usd = 0.0
    for row in wallets:
        wallet_id = str(row["id"])
        meta = _snapshot_meta(row)
        holdings_as_of = meta["holdings_as_of"]
        price_as_of = meta["price_as_of"]
        if holdings_as_of:
            holdings_dates.append(holdings_as_of)
        if price_as_of:
            price_dates.append(price_as_of)
        wallet_stale_holdings = should_refresh(holdings_as_of)
        wallet_stale_prices = should_refresh(price_as_of)
        stale_holdings = stale_holdings or wallet_stale_holdings
        stale_prices = stale_prices or wallet_stale_prices
        item_total = totals_by_wallet.get(wallet_id)
        wallet_total = item_total if item_total is not None else float(row.get("snapshot_total_usd") or 0.0)
        total_usd += wallet_total
        enriched_wallets.append(
            {
                **row,
                "id": wallet_id,
                "total_usd": wallet_total,
                "holdings_as_of": holdings_as_of,
                "price_as_of": price_as_of,
                "holdings_provider": meta["holdings_provider"],
                "price_provider": meta["price_provider"],
                "stale_holdings": wallet_stale_holdings,
                "stale_prices": wallet_stale_prices,
            }
        )

    for item in items:
        meta = _snapshot_meta(item)
        item["holdings_as_of"] = meta["holdings_as_of"]
        item["price_as_of"] = meta["price_as_of"]
        item["holdings_provider"] = meta["holdings_provider"]
        item["price_provider"] = item.get("price_source") or meta["price_provider"]

    return {
        "wallets": enriched_wallets,
        "items": items,
        "total_usd": total_usd,
        "holdings_as_of": min(holdings_dates) if holdings_dates else None,
        "price_as_of": min(price_dates) if price_dates else None,
        "stale_holdings": stale_holdings,
        "stale_prices": stale_prices,
    }


def refresh_latest_snapshot_prices(db: Session, wallet_id: str) -> bool:
    snapshot = db.execute(
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
    ).mappings().one_or_none()
    if snapshot is None:
        return False

    items = db.execute(
        text(
            """
            SELECT id, chain_type, chain, asset_kind, contract_or_mint, symbol, normalized_amount, price_usd, value_usd
            FROM crypto_wallet_snapshot_items
            WHERE snapshot_id = :snapshot_id
            """
        ),
        {"snapshot_id": snapshot["id"]},
    ).mappings().all()
    if not items:
        return False

    evm_contracts_by_chain: dict[str, list[str]] = {}
    sol_mints: list[str] = []
    symbols: set[str] = set()
    for item in items:
        chain_type = str(item["chain_type"])
        contract = item.get("contract_or_mint")
        if chain_type == "evm" and contract:
            evm_contracts_by_chain.setdefault(str(item["chain"]), []).append(str(contract))
        elif chain_type == "solana" and contract:
            sol_mints.append(str(contract))
        elif item.get("symbol"):
            symbols.add(str(item["symbol"]).upper())

    prices_by_key: dict[tuple[str, str], float] = {}
    for chain, contracts in evm_contracts_by_chain.items():
        for contract, price in price_by_contract(chain, contracts).items():
            prices_by_key[(chain, contract.lower())] = price
    for mint, price in price_by_mint(sol_mints).items():
        prices_by_key[("solana", mint.lower())] = price
    symbol_prices = {symbol: price_by_symbol(symbol) for symbol in symbols}

    updated = 0
    total_usd = 0.0
    for item in items:
        normalized = float(item["normalized_amount"]) if item.get("normalized_amount") is not None else None
        contract = str(item.get("contract_or_mint") or "").lower()
        chain = str(item["chain"])
        price = prices_by_key.get((chain, contract)) if contract else symbol_prices.get(str(item.get("symbol") or "").upper())
        if price is None:
            price = float(item["price_usd"]) if item.get("price_usd") is not None else None
        value = normalized * price if normalized is not None and price is not None else item.get("value_usd")
        if value is None:
            continue
        total_usd += float(value)
        if price is not None:
            updated += 1
            db.execute(
                text(
                    """
                    UPDATE crypto_wallet_snapshot_items
                    SET price_usd = :price_usd,
                        value_usd = :value_usd,
                        price_source = :price_source
                    WHERE id = :id
                    """
                ),
                {
                    "id": item["id"],
                    "price_usd": price,
                    "value_usd": value,
                    "price_source": ",".join(configured_price_provider_order()),
                },
            )
    if updated == 0:
        return False

    now = datetime.now(tz=timezone.utc)
    versions = _parse_source_versions(snapshot.get("source_versions"))
    versions.setdefault("holdings_as_of", _iso_dt(_parse_dt(snapshot.get("fetched_at"))))
    versions["price_as_of"] = now.isoformat()
    versions["price_provider"] = ",".join(configured_price_provider_order())
    db.execute(
        text(
            """
            UPDATE crypto_wallet_snapshots
            SET total_usd = :total_usd,
                source_versions = :source_versions
            WHERE id = :snapshot_id
            """
        ),
        {"snapshot_id": snapshot["id"], "total_usd": total_usd, "source_versions": json.dumps(versions)},
    )
    logger.info("crypto_price_overlay_updated", extra={"wallet_id": wallet_id, "items": updated})
    return True
