from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dashboard import (
    CashDepositsItem,
    CashDepositsOut,
    DashboardSummaryResponse,
    PlatformAllocationItem,
    PlatformAllocationOut,
    StockExposureItem,
    StockExposureOut,
)
from app.fx import get_rates

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_UPPERCASE_SOURCE_CODES = {"DBS", "OCBC", "UOB", "IBKR", "POSB", "CITI", "HSBC", "SCB"}


def _parse_month(month: str) -> datetime:
    """month: 'YYYY-MM' -> tz-aware datetime at month start (UTC)."""
    try:
        return datetime.strptime(month + "-01", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid month format. Use YYYY-MM, e.g. 2026-02")


def _add_months(dt: datetime, months: int) -> datetime:
    """Add months to a datetime (month start)."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    return dt.replace(year=y, month=m)


def _anchor_ts(month_start: datetime) -> datetime:
    """Anchor timestamp: end of month (00:00Z on next month start)."""
    return _add_months(month_start, 1).replace(hour=0, minute=0, second=0, microsecond=0)


def _effective_as_of(db: Session, anchor_ts: datetime) -> Optional[datetime]:
    """
    Pick the effective snapshot timestamp:
    max(positions.as_of) where as_of <= anchor_ts.
    Returns None if no snapshots exist at/before anchor.
    """
    q = text("SELECT MAX(as_of) AS as_of FROM positions WHERE as_of <= :anchor_ts")
    r = db.execute(q, {"anchor_ts": anchor_ts}).mappings().one()
    as_of = r["as_of"]
    if isinstance(as_of, str):
        try:
            as_of = datetime.fromisoformat(as_of)
        except ValueError:
            return None
    if isinstance(as_of, datetime) and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return as_of


def _infer_country(
    symbol: str | None,
    home: str | None,
    platform: str | None,
    quote_currency: str | None,
    exchange_code: str | None = None,
) -> str:
    if home:
        return home

    exchange_country_map = {
        "US": "US",
        "HKEX": "HK",
        "NSE": "IN",
        "SGX": "SG",
    }
    if exchange_code:
        mapped = exchange_country_map.get(exchange_code.upper())
        if mapped:
            return mapped

    if platform and platform.upper() == "IBKR":
        if symbol and symbol.isdigit():
            return "HK"
        if quote_currency and quote_currency.upper() == "HKD":
            return "HK"
        if quote_currency and quote_currency.upper() == "USD":
            return "US"

    if quote_currency and quote_currency.upper() == "USD":
        return "US"
    if quote_currency and quote_currency.upper() == "HKD":
        return "HK"
    if quote_currency and quote_currency.upper() == "INR":
        return "IN"
    return "UNKNOWN"


def _networth_components(db: Session, anchor_ts: datetime, base_currency: str) -> Dict[str, float]:
    """Compute net worth components using latest snapshot per account up to anchor_ts."""
    if anchor_ts is None:
        return {"cash": 0.0, "stocks_funds": 0.0, "crypto": 0.0, "liabilities": 0.0, "total": 0.0}
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        ),
        latest_prices AS (
          SELECT p1.asset_id, p1.price, p1.currency
          FROM prices p1
          JOIN (
            SELECT asset_id, MAX(trade_date) AS trade_date
            FROM prices
            WHERE trade_date IS NOT NULL AND trade_date <= :anchor_date
            GROUP BY asset_id
          ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        )
        SELECT
          a.asset_class,
          COALESCE(lp.currency, a.quote_currency) AS quote_currency,
          CASE
            WHEN a.asset_class IN ('STOCK', 'FUND') AND p.quantity IS NOT NULL AND lp.price IS NOT NULL
              THEN p.quantity * lp.price
            ELSE p.cost_basis_base
          END AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
        LEFT JOIN latest_prices lp ON lp.asset_id = p.asset_id
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date()}).mappings().all()
    if not rows:
        rows = []
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    currencies.add("USD")  # Include USD for crypto wallet conversions
    rates = get_rates(anchor_ts, base_currency, currencies)
    cash = 0.0
    stocks_funds = 0.0
    crypto = 0.0
    # Positions contribute cash and brokerage holdings only.
    # Crypto net worth is sourced from wallet snapshots below.
    for r in rows:
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        if r["asset_class"] == "CASH":
            cash += value
        elif r["asset_class"] in ("STOCK", "FUND"):
            stocks_funds += value
    # Add crypto wallet snapshots (USD -> base_currency), latest per wallet
    as_of_date = anchor_ts.date()
    wallet_total = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              WHERE as_of_date <= :as_of_date
              GROUP BY wallet_id
            )
            SELECT SUM(s.total_usd) AS total_usd
            FROM crypto_wallet_snapshots s
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            WHERE w.status = 'active'
            """
        ),
        {"as_of_date": as_of_date},
    ).mappings().one()
    wallet_usd = float(wallet_total["total_usd"]) if wallet_total and wallet_total["total_usd"] else 0.0
    if wallet_usd:
        usd_rate = rates.get("USD", 1.0)
        crypto += wallet_usd * usd_rate

    liabilities = 0.0  # later when loans modeled
    total = cash + stocks_funds + crypto - liabilities
    return {
        "cash": cash,
        "stocks_funds": stocks_funds,
        "crypto": crypto,
        "liabilities": liabilities,
        "total": total,
    }


def _geography(db: Session, anchor_ts: datetime, total: float, base_currency: str) -> List[Dict[str, Any]]:
    if total <= 0:
        return []
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        ),
        latest_prices AS (
          SELECT p1.asset_id, p1.price, p1.currency
          FROM prices p1
          JOIN (
            SELECT asset_id, MAX(trade_date) AS trade_date
            FROM prices
            WHERE trade_date IS NOT NULL AND trade_date <= :anchor_date
            GROUP BY asset_id
          ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        )
        SELECT
          a.symbol AS symbol,
          a.home_country AS home_country,
          COALESCE(lp.currency, a.quote_currency) AS quote_currency,
          COALESCE(pl.code, acc.platform) AS platform,
          CASE
            WHEN a.asset_class IN ('STOCK', 'FUND') AND p.quantity IS NOT NULL AND lp.price IS NOT NULL
              THEN p.quantity * lp.price
            ELSE p.cost_basis_base
          END AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
        JOIN accounts acc ON acc.id = p.account_id
        LEFT JOIN platforms pl ON pl.id = acc.platform_id
        LEFT JOIN latest_prices lp ON lp.asset_id = p.asset_id
        WHERE a.asset_class <> 'CRYPTO'
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date()}).mappings().all()
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[str, float] = {}
    for r in rows:
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        country = _infer_country(r["symbol"], r["home_country"], r["platform"], r["quote_currency"])
        buckets[country] = buckets.get(country, 0.0) + value
    out = []
    for country, value in sorted(buckets.items(), key=lambda x: x[1], reverse=True):
        out.append({
            "country": country,
            "value": value,
            "percent": round((value / total) * 100, 2)
        })
    return out


def _top_holdings(db: Session, anchor_ts: datetime, total: float, base_currency: str, limit: int = 10) -> List[Dict[str, Any]]:
    if total <= 0:
        return []
    
    # Combined query: positions (stocks/funds, excluding CASH) UNION ALL crypto wallet snapshots (grouped by base_asset)
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        ),
        map_exchange AS (
          SELECT
            m.asset_id,
            MIN(UPPER(m.exchange_code)) AS exchange_code
          FROM market_symbol_map m
          WHERE m.is_active = TRUE
          GROUP BY m.asset_id
        ),
        latest_prices AS (
          SELECT p1.asset_id, p1.price, p1.currency
          FROM prices p1
          JOIN (
            SELECT asset_id, MAX(trade_date) AS trade_date
            FROM prices
            WHERE trade_date IS NOT NULL AND trade_date <= :anchor_date
            GROUP BY asset_id
          ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        ),
        -- Positions: stocks/funds, excluding CASH
        positions_holdings AS (
          SELECT
            a.id AS asset_id,
            a.symbol AS symbol,
            CAST(a.asset_class AS TEXT) AS asset_class,
            CAST(COALESCE(lp.currency, a.quote_currency) AS TEXT) AS quote_currency,
            CAST(a.home_country AS TEXT) AS home_country,
            CAST(mx.exchange_code AS TEXT) AS exchange_code,
            CAST(COALESCE(pl.code, acc.platform) AS TEXT) AS platform,
            p.quantity AS quantity,
            p.avg_cost AS avg_cost,
            lp.price AS latest_price,
            CASE
              WHEN a.asset_class IN ('STOCK', 'FUND') AND p.quantity IS NOT NULL AND lp.price IS NOT NULL
                THEN p.quantity * lp.price
              ELSE p.cost_basis_base
            END AS value
          FROM positions p
          JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
          JOIN accounts acc ON acc.id = p.account_id
          LEFT JOIN platforms pl ON pl.id = acc.platform_id
          JOIN assets a ON a.id = p.asset_id
          LEFT JOIN map_exchange mx ON mx.asset_id = a.id
          LEFT JOIN latest_prices lp ON lp.asset_id = p.asset_id
          WHERE a.asset_class <> 'CRYPTO' AND a.asset_class <> 'CASH'
        ),
        -- Crypto: wallet snapshots grouped by base_asset (or symbol if base_asset is null)
        latest_wallets AS (
          SELECT wallet_id, MAX(as_of_date) AS as_of_date
          FROM crypto_wallet_snapshots
          WHERE as_of_date <= :as_of_date
          GROUP BY wallet_id
        ),
        -- Crypto asset fallback: provides base_asset for unlinked snapshot items
        -- Note: Uses MIN(base_asset) for symbol+chain collisions. This is non-deterministic
        -- if multiple crypto_assets with same symbol+chain have different base_asset values.
        -- Migration 028 includes validation to detect such collisions.
        crypto_asset_fallback AS (
          SELECT
            LOWER(ca.symbol) AS symbol_key,
            ca.chain AS chain,
            MIN(ca.base_asset) AS base_asset
          FROM crypto_assets ca
          GROUP BY LOWER(ca.symbol), ca.chain
        ),
        crypto_item_groups AS (
          SELECT
            UPPER(COALESCE(direct_ca.base_asset, fallback.base_asset, i.symbol)) AS symbol,
            SUM(i.value_usd) AS value
          FROM crypto_wallet_snapshots s
          JOIN latest_wallets lw ON lw.wallet_id = s.wallet_id AND lw.as_of_date = s.as_of_date
          JOIN crypto_wallets w ON w.id = s.wallet_id
          JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
          LEFT JOIN crypto_assets direct_ca ON direct_ca.id = i.asset_id
          LEFT JOIN crypto_asset_fallback fallback
            ON fallback.symbol_key = LOWER(i.symbol)
           AND (
                fallback.chain = i.chain
                OR (fallback.chain IS NULL AND i.chain IS NULL)
           )
          WHERE w.status = 'active'
          GROUP BY UPPER(COALESCE(direct_ca.base_asset, fallback.base_asset, i.symbol))
        ),
        crypto_holdings AS (
          SELECT
            CAST(NULL AS BIGINT) AS asset_id,
            CAST(g.symbol AS TEXT) AS symbol,
            CAST('CRYPTO' AS TEXT) AS asset_class,
            CAST('USD' AS TEXT) AS quote_currency,
            CAST(NULL AS TEXT) AS home_country,
            CAST(NULL AS TEXT) AS exchange_code,
            CAST('CRYPTO' AS TEXT) AS platform,
            CAST(NULL AS NUMERIC) AS quantity,
            CAST(NULL AS NUMERIC) AS avg_cost,
            CAST(NULL AS NUMERIC) AS latest_price,
            g.value AS value
          FROM crypto_item_groups g
        )
        SELECT * FROM positions_holdings
        UNION ALL
        SELECT * FROM crypto_holdings
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date(), "as_of_date": anchor_ts.date()}).mappings().all()

    # Collect all unique currencies for FX conversion
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    currencies.add("USD")
    rates = get_rates(anchor_ts, base_currency, currencies)
    
    # Aggregate by symbol (for crypto grouped by base_asset) or asset_id (for positions)
    agg: Dict[tuple, Dict[str, Any]] = {}
    geo_bucket: Dict[tuple, Dict[str, float]] = {}
    platform_bucket: Dict[tuple, Dict[str, float]] = {}
    
    for r in rows:
        # Skip rows with NULL value
        if r["value"] is None:
            continue
            
        # Key: (asset_id, symbol, asset_class) - for crypto, asset_id is None so symbol is the grouping key
        key = (r["asset_id"], r["symbol"], r["asset_class"])
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        
        if key not in agg:
            agg[key] = {
                "asset_id": r["asset_id"],
                "symbol": r["symbol"],
                "asset_class": r["asset_class"],
                "value": 0.0,
                "quantity": 0.0,
                "avg_cost": None,
                "latest_price": float(r["latest_price"]) if r["latest_price"] is not None else None,
                "quote_currency": cur if r["quote_currency"] else None,
                "_avg_cost_numerator": 0.0,
                "_avg_cost_denominator": 0.0,
                "_has_quantity": False,
            }
        
        agg[key]["value"] += value
        quantity = float(r["quantity"]) if r["quantity"] is not None else None
        if quantity is not None:
            agg[key]["quantity"] += quantity
            agg[key]["_has_quantity"] = True
            if r["avg_cost"] is not None and quantity > 0:
                agg[key]["_avg_cost_numerator"] += float(r["avg_cost"]) * quantity
                agg[key]["_avg_cost_denominator"] += quantity
        
        if not agg[key]["quote_currency"] and r["quote_currency"]:
            agg[key]["quote_currency"] = str(r["quote_currency"]).upper()
        if agg[key]["latest_price"] is None and r["latest_price"] is not None:
            agg[key]["latest_price"] = float(r["latest_price"])
        
        geo = _infer_country(
            r["symbol"],
            r["home_country"],
            r["platform"],
            r["quote_currency"],
            r["exchange_code"],
        )
        platform = r["platform"] or "UNKNOWN"
        geo_bucket.setdefault(key, {})[geo] = geo_bucket.setdefault(key, {}).get(geo, 0.0) + value
        platform_bucket.setdefault(key, {})[platform] = platform_bucket.setdefault(key, {}).get(platform, 0.0) + value
    
    # Sort by value and take top N
    out = sorted(agg.values(), key=lambda x: x["value"], reverse=True)[:limit]
    
    for r in out:
        value = float(r["value"])
        den = float(r.pop("_avg_cost_denominator"))
        num = float(r.pop("_avg_cost_numerator"))
        has_quantity = bool(r.pop("_has_quantity"))
        r["quantity"] = r["quantity"] if has_quantity else None
        r["avg_cost"] = (num / den) if den > 0 else None
        r["percent_of_networth"] = round((value / total) * 100, 2)
        
        key = (r["asset_id"], r["symbol"], r["asset_class"])
        geo = geo_bucket.get(key, {})
        platform = platform_bucket.get(key, {})
        r["geo"] = max(geo.items(), key=lambda x: x[1])[0] if geo else "UNKNOWN"
        r["platform"] = max(platform.items(), key=lambda x: x[1])[0] if platform else "UNKNOWN"
    
    return out


def _cash_balances(db: Session, anchor_ts: datetime, base_currency: str) -> List[Dict[str, Any]]:
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        )
        SELECT
          a.quote_currency AS currency,
          p.cost_basis_base AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
        WHERE a.asset_class = 'CASH'
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts}).mappings().all()
    if not rows:
        return []
    currencies = {r["currency"] for r in rows if r["currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[str, float] = {}
    for r in rows:
        cur = (r["currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        buckets[cur] = buckets.get(cur, 0.0) + value
    out = []
    for currency, value in sorted(buckets.items(), key=lambda x: x[1], reverse=True):
        out.append({
            "currency": currency,
            "value": value,
        })
    return out


def _display_source(value: str | None) -> str:
    if not value:
        return "UNKNOWN"
    text = value.strip()
    if not text:
        return "UNKNOWN"
    upper_text = text.upper()
    if upper_text in _UPPERCASE_SOURCE_CODES or (text.isupper() and len(text) <= 4):
        return upper_text
    return text.lower().title()


def _cash_deposits(db: Session, anchor_ts: datetime, base_currency: str) -> Dict[str, Any]:
    buckets: Dict[str, float] = {}

    cash_rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT account_id, MAX(as_of) AS as_of
              FROM positions
              WHERE as_of <= :anchor_ts
              GROUP BY account_id
            )
            SELECT
              COALESCE(pl.code, acc.platform) AS source,
              a.quote_currency AS quote_currency,
              p.cost_basis_base AS value
            FROM positions p
            JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
            JOIN accounts acc ON acc.id = p.account_id
            LEFT JOIN platforms pl ON pl.id = acc.platform_id
            JOIN assets a ON a.id = p.asset_id
            WHERE a.asset_class = 'CASH'
            """
        ),
        {"anchor_ts": anchor_ts},
    ).mappings().all()
    cash_currencies = {row["quote_currency"] for row in cash_rows if row["quote_currency"]}
    cash_rates = get_rates(anchor_ts, base_currency, cash_currencies) if cash_currencies else {}
    for row in cash_rows:
        source = _display_source(row["source"])
        quote_currency = (row["quote_currency"] or base_currency).upper()
        # Positions are persisted in their asset quote currency by current ingestion flows,
        # so cash deposits must use the same FX conversion path as the dashboard summary.
        value = float(row["value"]) * cash_rates.get(quote_currency, 1.0)
        buckets[source] = buckets.get(source, 0.0) + value

    wallet_rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              WHERE as_of_date <= :as_of_date
              GROUP BY wallet_id
            )
            SELECT
              i.chain AS source,
              SUM(i.value_usd) AS value_usd
            FROM crypto_wallet_snapshots s
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
            WHERE w.status = 'active'
              AND UPPER(COALESCE(i.symbol, '')) IN ('USDC', 'USDT')
            GROUP BY i.chain
            """
        ),
        {"as_of_date": anchor_ts.date()},
    ).mappings().all()
    if wallet_rows:
        usd_rate = get_rates(anchor_ts, base_currency, {"USD"}).get("USD", 1.0)
        for row in wallet_rows:
            if row["value_usd"] is None:
                continue
            source = _display_source(row["source"])
            value = float(row["value_usd"]) * usd_rate
            buckets[source] = buckets.get(source, 0.0) + value

    total = sum(buckets.values())
    items = []
    for source, value in sorted(buckets.items(), key=lambda item: item[1], reverse=True):
        items.append(
            {
                "source": source,
                "value": value,
                "percent": round((value / total) * 100, 2) if total > 0 else 0.0,
            }
        )
    return {"items": items, "total": total}


def _cashflow(db: Session, start: datetime, end: datetime, base_currency: str) -> Dict[str, Any]:
    q = text("""
        SELECT
          type,
          amount,
          currency
        FROM transactions
        WHERE ts >= :start AND ts < :end
    """)
    rows = db.execute(q, {"start": start, "end": end}).mappings().all()
    currencies = {r["currency"] for r in rows if r["currency"]}
    rates = get_rates(start, base_currency, currencies)
    income = 0.0
    expenses = 0.0
    for r in rows:
        cur = (r["currency"] or base_currency).upper()
        amount = float(r["amount"]) * rates.get(cur, 1.0)
        if r["type"] == "INCOME":
            income += amount
        elif r["type"] in ("EXPENSE", "FEE", "TAX", "INTEREST"):
            expenses += -amount
    net = income - expenses
    savings_rate = (net / income) if income > 0 else None
    return {"income": income, "expenses": expenses, "net": net, "savings_rate": savings_rate}


def _platform_allocation(db: Session, anchor_ts: datetime, base_currency: str) -> dict:
    q = text("""
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        ),
        latest_prices AS (
          SELECT p1.asset_id, p1.price, p1.currency
          FROM prices p1
          JOIN (
            SELECT asset_id, MAX(trade_date) AS trade_date
            FROM prices
            WHERE trade_date IS NOT NULL AND trade_date <= :anchor_date
            GROUP BY asset_id
          ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        )
        SELECT
          COALESCE(pl.code, a.platform) AS platform,
          pl.platform_type AS platform_type,
          COALESCE(pl.country, a.country) AS country,
          COALESCE(lp.currency, a2.quote_currency) AS quote_currency,
          CASE
            WHEN a2.asset_class IN ('STOCK', 'FUND') AND p.quantity IS NOT NULL AND lp.price IS NOT NULL
              THEN p.quantity * lp.price
            ELSE p.cost_basis_base
          END AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN accounts a ON a.id = p.account_id
        LEFT JOIN platforms pl ON pl.id = a.platform_id
        JOIN assets a2 ON a2.id = p.asset_id
        LEFT JOIN latest_prices lp ON lp.asset_id = p.asset_id
        WHERE a2.asset_class <> 'CRYPTO'
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date()}).mappings().all()
    if not rows:
        return {"as_of": None, "total": 0.0, "items": []}
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[tuple, float] = {}
    for r in rows:
        key = (r["platform"], r["platform_type"], r["country"])
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        buckets[key] = buckets.get(key, 0.0) + value
    total = sum(buckets.values())
    items = []
    for (platform, platform_type, country), value in sorted(buckets.items(), key=lambda x: x[1], reverse=True):
        percent = round((value / total) * 100, 2) if total > 0 else 0.0
        items.append({
            "platform": platform,
            "platform_type": platform_type,
            "country": country,
            "value": value,
            "percent": percent,
        })
    return {"as_of": None, "total": total, "items": items}


def _stock_exposure(db: Session, anchor_ts: datetime, base_currency: str) -> dict:
    q = text(
        """
        WITH latest AS (
          SELECT account_id, MAX(as_of) AS as_of
          FROM positions
          WHERE as_of <= :anchor_ts
          GROUP BY account_id
        ),
        latest_prices AS (
          SELECT p1.asset_id, p1.price, p1.currency
          FROM prices p1
          JOIN (
            SELECT asset_id, MAX(trade_date) AS trade_date
            FROM prices
            WHERE trade_date IS NOT NULL AND trade_date <= :anchor_date
            GROUP BY asset_id
          ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        )
        SELECT
          COALESCE(pl.code, a.platform) AS platform,
          a2.symbol AS symbol,
          a2.home_country AS home_country,
          COALESCE(lp.currency, a2.quote_currency) AS quote_currency,
          CASE
            WHEN p.quantity IS NOT NULL AND lp.price IS NOT NULL
              THEN p.quantity * lp.price
            ELSE p.cost_basis_base
          END AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN accounts a ON a.id = p.account_id
        LEFT JOIN platforms pl ON pl.id = a.platform_id
        JOIN assets a2 ON a2.id = p.asset_id
        LEFT JOIN latest_prices lp ON lp.asset_id = p.asset_id
        WHERE a2.asset_class IN ('STOCK', 'FUND')
        """
    )
    rows = db.execute(q, {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date()}).mappings().all()
    if not rows:
        return {"as_of": None, "base_currency": base_currency, "total": 0.0, "by_country": [], "by_platform": []}
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    rates = get_rates(anchor_ts, base_currency, currencies)

    by_country: Dict[str, float] = {}
    by_platform: Dict[str, float] = {}
    total = 0.0

    for r in rows:
        cur = (r["quote_currency"] or base_currency).upper()
        value = float(r["value"]) * rates.get(cur, 1.0)
        total += value
        platform = r["platform"] or "UNKNOWN"
        country = _infer_country(r["symbol"], r["home_country"], platform, r["quote_currency"])
        by_platform[platform] = by_platform.get(platform, 0.0) + value
        by_country[country] = by_country.get(country, 0.0) + value

    def _to_items(bucket: Dict[str, float]) -> list[dict]:
        items = []
        for key, value in sorted(bucket.items(), key=lambda x: x[1], reverse=True):
            percent = round((value / total) * 100, 2) if total > 0 else 0.0
            items.append({"key": key, "value": value, "percent": percent})
        return items

    return {
        "as_of": None,
        "base_currency": base_currency,
        "total": total,
        "by_country": _to_items(by_country),
        "by_platform": _to_items(by_platform),
    }


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("", description="Comma-separated: prev_month,prev_year"),
    db: Session = Depends(get_db),
):
    # Calendar month window for cashflow
    month_start = _parse_month(month)
    month_end = _add_months(month_start, 1)

    # Snapshot anchor + effective snapshot timestamp
    anchor = _anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor)

    nw = _networth_components(db, anchor, base_currency)
    geo = _geography(db, anchor, nw["total"], base_currency)
    top = _top_holdings(db, anchor, nw["total"], base_currency, limit=15)
    cash_balances = _cash_balances(db, anchor, base_currency)
    cf = _cashflow(db, month_start, month_end, base_currency)

    # Comparisons (Option A)
    compare_set = {c.strip() for c in compare.split(",") if c.strip()}
    changes = {}

    def _delta(label: str, other_month_start: datetime):
        other_anchor = _anchor_ts(other_month_start)
        other_as_of = _effective_as_of(db, other_anchor)
        other_nw = _networth_components(db, other_as_of, base_currency)

        cur = nw["total"]
        prev = other_nw["total"]
        abs_change = cur - prev
        pct_change = (abs_change / prev) if prev > 0 else None

        changes[label] = {
            "abs": abs_change,
            "pct": pct_change,
            "current_as_of": as_of.isoformat() if as_of else None,
            "compare_as_of": other_as_of.isoformat() if other_as_of else None,
            "compare_month": other_month_start.strftime("%Y-%m"),
        }

    if "prev_month" in compare_set:
        _delta("vs_prev_month", _add_months(month_start, -1))
    if "prev_year" in compare_set:
        _delta("vs_prev_year", _add_months(month_start, -12))

    # Compute cash_percent
    cash_percent = round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": None,
        "net_worth_as_of": as_of.isoformat() if as_of else None,
        "net_worth": {
            "total": nw["total"],
            "cash": nw["cash"],
            "stocks_funds": nw["stocks_funds"],
            "crypto": nw["crypto"],
            "liabilities": nw["liabilities"],
        },
        "geography": geo,
        "cash_flow": cf,
        "top_holdings": top,
        "cash_balances": cash_balances,
        "net_worth_change": changes if changes else None,
        "cash_percent": cash_percent,
    }


@router.get("/platform-allocation", response_model=PlatformAllocationOut)
def platform_allocation(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    month_start = _parse_month(month)
    anchor = _anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor)
    payload = _platform_allocation(db, anchor, base_currency)
    return PlatformAllocationOut(
        as_of=as_of.isoformat() if as_of else None,
        total=payload["total"],
        items=[PlatformAllocationItem(**item) for item in payload["items"]],
    )


@router.get("/cash-deposits", response_model=CashDepositsOut)
def cash_deposits(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    month_start = _parse_month(month)
    anchor = _anchor_ts(month_start)
    payload = _cash_deposits(db, anchor, base_currency)
    return CashDepositsOut(
        total=payload["total"],
        items=[CashDepositsItem(**item) for item in payload["items"]],
    )


@router.get("/stock-exposure", response_model=StockExposureOut)
def stock_exposure(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
):
    month_start = _parse_month(month)
    anchor = _anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor)
    payload = _stock_exposure(db, anchor, base_currency)
    return StockExposureOut(
        as_of=as_of.isoformat() if as_of else None,
        base_currency=base_currency,
        total=payload["total"],
        by_country=[StockExposureItem(**item) for item in payload["by_country"]],
        by_platform=[StockExposureItem(**item) for item in payload["by_platform"]],
    )
