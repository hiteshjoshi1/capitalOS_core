from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import allow_legacy_null_ownership
from app.crypto.ingest import should_refresh, wallet_as_of_date
from app.crypto.pricing import price_by_contract, price_by_mint, price_by_symbol
from app.crypto.providers import configured_price_provider_order
from app.valuation_cache import valuation_cached
from app.wealth_rollup_dirty import mark_rollups_dirty

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


# Per request only: its stale_* flags are relative to the current time.
@valuation_cached()
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
    # #331: an item with no price takes the newest price of the same token stored within
    # CARRY_DAYS before it (marked "carried:<date>"), so a held coin isn't worth 0.
    from app.crypto.price_backfill import carry_prices

    carry_prices(db, current_user_id, items)

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
    """After a failed holdings refresh: today's prices for the newest snapshot's
    holdings, written as a **new prices-only snapshot dated today** (#144, #130
    2.10). The newest snapshot itself is left as it was, so the day it describes
    keeps its own prices (it used to be overwritten with today's, changing every
    anchor from its date on). If the newest snapshot is already today's, it is
    repriced in place: that changes only today.

    True when at least one price was refreshed and a snapshot written.
    """
    snapshot = db.execute(
        text(
            """
            SELECT id, as_of_date, fetched_at, source_versions
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
            SELECT id, asset_id, chain_type, chain, asset_kind, contract_or_mint, symbol, name, decimals,
                   raw_amount, normalized_amount, price_usd, value_usd, price_source
            FROM crypto_wallet_snapshot_items
            WHERE snapshot_id = :snapshot_id
            ORDER BY id
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

    provider = ",".join(configured_price_provider_order())
    updated = 0
    total_usd = 0.0
    new_items: list[dict[str, Any]] = []
    for item in items:
        normalized = float(item["normalized_amount"]) if item.get("normalized_amount") is not None else None
        contract = str(item.get("contract_or_mint") or "").lower()
        chain = str(item["chain"])
        fresh = prices_by_key.get((chain, contract)) if contract else symbol_prices.get(str(item.get("symbol") or "").upper())
        row = dict(item)
        if fresh is not None and normalized is not None:
            updated += 1
            row["price_usd"] = fresh
            row["value_usd"] = normalized * fresh
            row["price_source"] = provider
        if row.get("value_usd") is not None:
            total_usd += float(row["value_usd"])
        new_items.append(row)
    if updated == 0:
        return False

    now = datetime.now(tz=timezone.utc)
    today = wallet_as_of_date(db, wallet_id)
    versions = _parse_source_versions(snapshot.get("source_versions"))
    # The holdings are the newest snapshot's: their time stays theirs.
    versions.setdefault("holdings_as_of", _iso_dt(_parse_dt(snapshot.get("fetched_at"))))
    versions["price_as_of"] = now.isoformat()
    versions["price_provider"] = provider
    source_date = snapshot["as_of_date"]
    source_date_value = source_date if isinstance(source_date, date) else date.fromisoformat(str(source_date)[:10])
    if source_date_value >= today:
        snapshot_id = int(snapshot["id"])
        db.execute(
            text(
                """
                UPDATE crypto_wallet_snapshots
                SET total_usd = :total_usd,
                    source_versions = :source_versions
                WHERE id = :snapshot_id
                """
            ),
            {"snapshot_id": snapshot_id, "total_usd": total_usd, "source_versions": json.dumps(versions)},
        )
        db.execute(text("DELETE FROM crypto_wallet_snapshot_items WHERE snapshot_id = :id"), {"id": snapshot_id})
    else:
        versions["prices_only"] = True
        versions["holdings_snapshot_id"] = int(snapshot["id"])
        versions["holdings_snapshot_date"] = source_date_value.isoformat()
        snapshot_id = int(
            db.execute(
                text(
                    "INSERT INTO crypto_wallet_snapshots (wallet_id, as_of_date, fetched_at, total_usd, source_versions) "
                    "VALUES (:wallet_id, :as_of_date, :now, :total_usd, :source_versions) RETURNING id"
                ),
                {
                    "wallet_id": wallet_id,
                    "as_of_date": today,
                    "now": now,
                    "total_usd": total_usd,
                    "source_versions": json.dumps(versions),
                },
            ).scalar_one()
        )
    for row in new_items:
        db.execute(
            text(
                """
                INSERT INTO crypto_wallet_snapshot_items
                (snapshot_id, asset_id, chain_type, chain, asset_kind, contract_or_mint, symbol, name, decimals,
                 raw_amount, normalized_amount, price_usd, value_usd, price_source)
                VALUES
                (:snapshot_id, :asset_id, :chain_type, :chain, :asset_kind, :contract_or_mint, :symbol, :name, :decimals,
                 :raw_amount, :normalized_amount, :price_usd, :value_usd, :price_source)
                """
            ),
            {**{k: v for k, v in row.items() if k != "id"}, "snapshot_id": snapshot_id},
        )
    logger.info(
        "crypto_price_overlay_updated",
        extra={"wallet_id": wallet_id, "items": updated, "snapshot_db_id": snapshot_id, "as_of_date": today.isoformat()},
    )
    # Only today's snapshot changed: History from today on (#138).
    mark_rollups_dirty(db, today, wallet_id=wallet_id, reason="crypto_snapshot_repriced")
    return True
