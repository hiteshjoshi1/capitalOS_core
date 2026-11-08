"""Past crypto prices (#331): no held coin is worth S$ 0 just because its snapshot had no price.

Two parts, both per user (wallet snapshots are the user's own data, not a shared table):

1. Carry (valuation time, ``carry_prices``): a snapshot item with no price takes the newest
   price stored for the same token (chain + contract/mint, or the native symbol) in any of the
   user's wallets' snapshots dated within CARRY_DAYS before it. It is marked
   ``price_source = "carried:<date>"``. Never a price from after the item's date; never
   a made-up price: a token never priced in that window stays unpriced (and named).

2. Back-fill (``plan_backfill`` / ``run_backfill``, ``make crypto-price-backfill``): items with no
   price whose token *is* priced somewhere (a priced item for the same token exists in any
   snapshot, so tokens no provider knows, e.g. spam airdrops, are never fetched) get DefiLlama's
   historical price for the snapshot's date. One request per date (coins chunked by
   DEFILLAMA_CHUNK_SIZE), at most ``max_requests()`` per run, newest dates first; dates whose items
   are all priced are skipped. Stored on the item (``price_source = "defillama_historical"``), the
   snapshot total re-summed, History marked dirty from the earliest changed date per wallet
   (#138), and a ``job_runs`` row (``crypto_price_backfill``) for Data Hub (#156).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.job_runs import JOB_CRYPTO_PRICE_BACKFILL
from app.crypto.pricing import LLAMA_CHAIN, NATIVE_IDS, _is_valid_contract

logger = logging.getLogger("capitalos.crypto")

CARRY_DAYS = 7
SOURCE_HISTORICAL = "defillama_historical"
DEFILLAMA_BASE = "https://coins.llama.fi"

TokenKey = Tuple[str, str]  # (chain, contract/mint lower-cased, or "native:<SYMBOL>")


def max_requests() -> int:
    try:
        return max(int(os.getenv("CRYPTO_PRICE_BACKFILL_MAX_REQUESTS", "30")), 0)
    except ValueError:
        return 30


def token_key(item: Dict[str, Any]) -> Optional[TokenKey]:
    chain = str(item.get("chain") or "").lower()
    contract = str(item.get("contract_or_mint") or "").strip()
    if contract:
        return (chain, contract.lower())
    symbol = str(item.get("symbol") or "").upper()
    return (chain, f"native:{symbol}") if symbol else None


def coin_id(item: Dict[str, Any]) -> Optional[str]:
    """DefiLlama's coin id for an item, or None when it can't be priced there."""
    chain = str(item.get("chain") or "").lower()
    contract = str(item.get("contract_or_mint") or "").strip()
    if not contract:
        native = NATIVE_IDS.get(str(item.get("symbol") or "").upper())
        return f"coingecko:{native}" if native else None
    if chain == "solana":
        return f"solana:{contract}"
    llama_chain = LLAMA_CHAIN.get(chain)
    if llama_chain and _is_valid_contract(contract):
        return f"{llama_chain}:{contract.lower()}"
    return None


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ─── 1. Carry at valuation time ──────────────────────────────────────────────


def carry_prices(db: Session, current_user_id: int, items: List[Dict[str, Any]]) -> int:
    """Fill ``price_usd``/``value_usd`` on unpriced items (in place) from the newest price of the
    same token within CARRY_DAYS on or before each item's snapshot date. Returns how many."""
    from app.crypto.valuation import wallet_scope_sql

    missing = [
        item for item in items
        if item.get("price_usd") is None and float(item.get("normalized_amount") or 0.0) > 0
        and token_key(item) is not None and _as_date(item.get("as_of_date")) is not None
    ]
    if not missing:
        return 0
    days = [_as_date(item["as_of_date"]) for item in missing]
    lo = min(d for d in days if d is not None) - timedelta(days=CARRY_DAYS)
    hi = max(d for d in days if d is not None)
    rows = db.execute(
        text(
            """
            SELECT i.chain, i.contract_or_mint, i.symbol, s.as_of_date, i.price_usd
            FROM crypto_wallet_snapshot_items i
            JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id
            JOIN crypto_wallets w ON w.id = s.wallet_id
            WHERE i.price_usd IS NOT NULL
              AND s.as_of_date >= :lo AND s.as_of_date <= :hi
              AND """
            + wallet_scope_sql("w")
        ),
        {"lo": lo, "hi": hi, "current_user_id": current_user_id},
    ).mappings().all()
    known: Dict[TokenKey, List[Tuple[date, float]]] = {}
    for row in rows:
        key = token_key(dict(row))
        day = _as_date(row["as_of_date"])
        if key is not None and day is not None and float(row["price_usd"]) > 0:
            known.setdefault(key, []).append((day, float(row["price_usd"])))
    filled = 0
    for item in missing:
        key = token_key(item)
        day = _as_date(item["as_of_date"])
        if key is None or day is None:
            continue
        candidates = [(d, p) for d, p in known.get(key, []) if day - timedelta(days=CARRY_DAYS) <= d <= day]
        if not candidates:
            continue
        carried_day, price = max(candidates, key=lambda c: c[0])
        item["price_usd"] = price
        item["value_usd"] = float(item["normalized_amount"]) * price
        item["price_source"] = f"carried:{carried_day.isoformat()}"
        item["price_carried_from"] = carried_day.isoformat()
        filled += 1
    return filled


# ─── 2. Back-fill from DefiLlama's historical prices ─────────────────────────


@dataclass
class BackfillPlan:
    # Per snapshot date: the coin ids to fetch, newest date first.
    requests: List[Tuple[date, List[str]]] = field(default_factory=list)
    remaining_requests: int = 0
    items: int = 0
    skipped_unknown_tokens: int = 0  # never priced anywhere (no provider knows them)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "requests": [{"date": d.isoformat(), "coins": len(c)} for d, c in self.requests],
            "remaining_requests": self.remaining_requests,
            "items": self.items,
            "skipped_unknown_tokens": self.skipped_unknown_tokens,
        }


def _chunk_size() -> int:
    try:
        return max(int(os.getenv("DEFILLAMA_CHUNK_SIZE", "50")), 1)
    except ValueError:
        return 50


def _unpriced_items(db: Session, user_id: int) -> List[Dict[str, Any]]:
    from app.crypto.valuation import wallet_scope_sql

    return [
        dict(row)
        for row in db.execute(
            text(
                """
                SELECT i.id, i.snapshot_id, s.wallet_id, s.as_of_date, i.chain, i.contract_or_mint,
                       i.symbol, i.normalized_amount, i.price_usd
                FROM crypto_wallet_snapshot_items i
                JOIN crypto_wallet_snapshots s ON s.id = i.snapshot_id
                JOIN crypto_wallets w ON w.id = s.wallet_id
                WHERE """
                + wallet_scope_sql("w")
            ),
            {"current_user_id": user_id},
        ).mappings().all()
    ]


def plan_backfill(db: Session, user_id: int) -> BackfillPlan:
    rows = _unpriced_items(db, user_id)
    priced_tokens = {token_key(r) for r in rows if r.get("price_usd") is not None}
    by_day: Dict[date, set[str]] = {}
    plan = BackfillPlan()
    for row in rows:
        if row.get("price_usd") is not None or float(row.get("normalized_amount") or 0.0) <= 0:
            continue
        key, cid, day = token_key(row), coin_id(row), _as_date(row.get("as_of_date"))
        if key not in priced_tokens or cid is None or day is None:
            plan.skipped_unknown_tokens += 1
            continue
        plan.items += 1
        by_day.setdefault(day, set()).add(cid)
    chunk = _chunk_size()
    all_requests: List[Tuple[date, List[str]]] = []
    for day in sorted(by_day, reverse=True):
        coins = sorted(by_day[day])
        for i in range(0, len(coins), chunk):
            all_requests.append((day, coins[i:i + chunk]))
    cap = max_requests()
    plan.requests = all_requests[:cap]
    plan.remaining_requests = max(len(all_requests) - cap, 0)
    return plan


def _historical_prices(day: date, coins: Iterable[str]) -> Dict[str, float]:
    """DefiLlama's price for each coin at noon UTC on ``day`` (searchWidth 12h either side)."""
    from app.crypto.http import request_with_retry
    from app.crypto.pricing import _throttle_defillama

    ts = int(datetime.combine(day, time(12, 0), tzinfo=timezone.utc).timestamp())
    url = f"{DEFILLAMA_BASE}/prices/historical/{ts}/{','.join(coins)}?searchWidth=12h"
    _throttle_defillama()
    resp = request_with_retry(
        "GET", url, timeout=10, max_attempts=3, backoff_seconds=1.0, retry_statuses={429, 500, 502, 503, 504}
    )
    if resp.status_code != 200:
        raise RuntimeError(f"defillama historical HTTP {resp.status_code}")
    payload = resp.json()
    out: Dict[str, float] = {}
    for key, meta in (payload.get("coins") or {}).items():
        price = meta.get("price") if isinstance(meta, dict) else None
        if price is not None and float(price) > 0:
            out[key] = float(price)
    return out


def run_backfill(db: Session, user_id: int, *, apply: bool, trigger: str = "manual") -> Dict[str, Any]:
    """Plan, and with ``apply`` fetch and store. A failed request is counted; the rest go on."""
    from app.core.job_runs import STATUS_FAILED, STATUS_NO_NEW_DATA, STATUS_PARTIAL, STATUS_SUCCESS, record_job_run
    from app.wealth_rollup_dirty import mark_rollups_dirty

    started_at = datetime.now(tz=timezone.utc)
    plan = plan_backfill(db, user_id)
    result: Dict[str, Any] = {**plan.as_dict(), "fetched_requests": 0, "failed_requests": 0, "items_priced": 0}
    if not apply or not plan.requests:
        result["status"] = "dry_run" if not apply else "up_to_date"
        return result

    rows = [r for r in _unpriced_items(db, user_id) if r.get("price_usd") is None]
    earliest_by_wallet: Dict[str, date] = {}
    touched_snapshots: set[int] = set()
    last_error: Optional[BaseException] = None
    for day, coins in plan.requests:
        try:
            prices = _historical_prices(day, coins)
            result["fetched_requests"] += 1
        except Exception as exc:  # noqa: BLE001 - one failed date must not stop the rest
            result["failed_requests"] += 1
            last_error = exc
            continue
        for row in rows:
            if _as_date(row["as_of_date"]) != day or row.get("price_usd") is not None:
                continue
            price = prices.get(coin_id(row) or "")
            if price is None:
                continue
            qty = float(row.get("normalized_amount") or 0.0)
            db.execute(
                text(
                    "UPDATE crypto_wallet_snapshot_items SET price_usd = :p, value_usd = :v, price_source = :s "
                    "WHERE id = :id AND price_usd IS NULL"
                ),
                {"p": price, "v": qty * price, "s": SOURCE_HISTORICAL, "id": int(row["id"])},
            )
            row["price_usd"] = price
            result["items_priced"] += 1
            touched_snapshots.add(int(row["snapshot_id"]))
            wallet = str(row["wallet_id"])
            if wallet not in earliest_by_wallet or day < earliest_by_wallet[wallet]:
                earliest_by_wallet[wallet] = day
    for snapshot_id in touched_snapshots:
        db.execute(
            text(
                "UPDATE crypto_wallet_snapshots SET total_usd = ("
                "  SELECT COALESCE(SUM(value_usd), 0) FROM crypto_wallet_snapshot_items WHERE snapshot_id = :id"
                ") WHERE id = :id"
            ),
            {"id": snapshot_id},
        )
    for wallet, day in earliest_by_wallet.items():
        mark_rollups_dirty(db, day, wallet_id=wallet, reason="crypto_price_backfill")
    db.commit()

    if result["failed_requests"] and not result["fetched_requests"]:
        result["status"] = "failed"
    elif result["failed_requests"] or plan.remaining_requests:
        result["status"] = "partial"
    else:
        result["status"] = "completed"
    record_job_run(
        db,
        job=JOB_CRYPTO_PRICE_BACKFILL,
        trigger=trigger,
        status={
            "failed": STATUS_FAILED,
            "partial": STATUS_PARTIAL,
            "completed": STATUS_SUCCESS if result["items_priced"] else STATUS_NO_NEW_DATA,
        }[result["status"]],
        started_at=started_at,
        user_id=user_id,
        data_as_of=plan.requests[0][0] if result["fetched_requests"] else None,
        data_advanced=bool(result["items_priced"]),
        error=last_error,
        details={k: result[k] for k in ("fetched_requests", "failed_requests", "items_priced", "remaining_requests")},
    )
    logger.info(
        "crypto_price_backfill_finished",
        extra={"event": "crypto_price_backfill_finished", "status": result["status"], "items": result["items_priced"]},
    )
    return result
