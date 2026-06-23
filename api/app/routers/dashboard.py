from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Callable

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, require_current_user
from app.db.session import get_db
from app.schemas.dashboard import (
    BootstrapResponse,
    CashDepositsItem,
    CashCurrencyBreakdownItem,
    CashDepositsOut,
    DashboardSummaryResponse,
    MiniTrendPoint,
    NetWorthChangeResponse,
    GeographyExposureItem,
    GeographyExposureOut,
    PlatformAllocationItem,
    PlatformAllocationOut,
    QuoteFreshnessSummary,
    StockGeographyBreakdownItem,
    StockHoldingsResponse,
    StockExposureItem,
    StockExposureOut,
)
from app.fx import get_rates
from app.portfolio.ibkr_flex import latest_authoritative_nav_by_legacy_account

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_current_user)])

_UPPERCASE_SOURCE_CODES = {"DBS", "OCBC", "UOB", "IBKR", "POSB", "CITI", "HSBC", "SCB"}
_SYNTHETIC_TRANSFER_CATEGORIES = {
    "bank::transfer",
    "creditcard::payment",
    "brokerage::transfer",
}
_SYNTHETIC_INTERNAL_MARKERS = (
    "ICT SELF",
    "OWN ACCOUNT",
    "INTERACTIVE BROKERS",
    "IBKR",
    "PHILLIP SECURITIES",
    "DBS VICKERS",
    "VICKERS SECURITIES",
    "GIRO PAYMENT",
    "COINBASE",
)
_SYNTHETIC_ALLOWED_BANK_INCOME_MARKERS = (
    "SALARY",
    "PAYROLL",
    "INTEREST",
    "DIVIDEND",
    "REFUND",
    "RFD",
    "REBATE",
    "BONUS INTEREST",
)


def _summary_top_holdings_limit() -> int:
    raw = os.getenv("DASHBOARD_TOP_HOLDINGS_LIMIT", "200")
    try:
        limit = int(raw)
    except ValueError:
        limit = 200
    # Keep payload bounded while allowing rich detail pages to paginate client-side.
    return max(20, min(limit, 500))


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


def _configured_snapshot_day() -> int:
    raw = os.getenv("SNAPSHOT_DAY", "1")
    try:
        snapshot_day = int(raw)
    except ValueError:
        snapshot_day = 1
    return max(1, min(snapshot_day, 31))


def _clamp_day(dt: datetime, day: int) -> datetime:
    month_end = _add_months(dt, 1)
    last_day = (month_end - timedelta(days=1)).day
    safe_day = min(day, last_day)
    return dt.replace(day=safe_day)


def _anchor_ts(month_start: datetime) -> datetime:
    """Snapshot anchor timestamp: configured day in the next month (00:00Z)."""
    next_month_start = _add_months(month_start, 1).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return _clamp_day(next_month_start, _configured_snapshot_day()).replace(hour=0, minute=0, second=0, microsecond=0)


def _current_anchor_ts() -> datetime:
    return datetime.now(tz=timezone.utc).replace(microsecond=0)


def _completed_snapshot_anchor_ts(month_start: datetime) -> datetime:
    requested_anchor = _anchor_ts(month_start)
    if requested_anchor <= _current_anchor_ts():
        return requested_anchor
    return _anchor_ts(_add_months(month_start, -1))


def _effective_as_of(db: Session, anchor_ts: datetime, current_user_id: int) -> Optional[datetime]:
    """
    Pick the effective snapshot timestamp:
    max(positions.as_of) where as_of <= anchor_ts.
    Returns None if no snapshots exist at/before anchor.
    """
    q = text(
        """
        SELECT MAX(p.as_of) AS as_of
        FROM positions p
        JOIN accounts acc ON acc.id = p.account_id
        WHERE p.as_of <= :anchor_ts
          AND """
        + account_scope_sql("acc")
    )
    r = db.execute(q, {"anchor_ts": anchor_ts, "current_user_id": current_user_id}).mappings().one()
    as_of = r["as_of"]
    if isinstance(as_of, str):
        try:
            as_of = datetime.fromisoformat(as_of)
        except ValueError:
            return None
    if isinstance(as_of, datetime) and as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    return as_of


def _normalize_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _iso_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return normalized.isoformat()
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return iso()
    return str(value)


def _snapshot_freshness(db: Session, anchor_ts: datetime, current_user_id: int) -> tuple[Optional[datetime], bool, str]:
    as_of = _effective_as_of(db, anchor_ts, current_user_id)
    if as_of is None:
        return None, False, "missing"
    return as_of, as_of == anchor_ts, ("exact" if as_of == anchor_ts else "synthetic")


def _quote_stale_days() -> int:
    raw = os.getenv("QUOTE_STALE_DAYS", "3")
    try:
        days = int(raw)
    except ValueError:
        days = 3
    return max(1, days)


def _price_provider(source: str | None) -> str | None:
    if not source:
        return None
    provider = source.split("_", 1)[0].strip()
    return provider or None


def _quote_age_days(trade_date_value: Any) -> Optional[int]:
    trade_dt = _normalize_ts(trade_date_value)
    if trade_dt is not None:
        return max(0, (datetime.now(tz=timezone.utc).date() - trade_dt.date()).days)
    iso = _iso_value(trade_date_value)
    if not iso:
        return None
    try:
        return max(0, (datetime.now(tz=timezone.utc).date() - datetime.fromisoformat(iso).date()).days)
    except ValueError:
        return None


def _quote_freshness_status(trade_date_value: Any) -> str:
    age_days = _quote_age_days(trade_date_value)
    if age_days is None:
        return "missing"
    return "stale" if age_days > _quote_stale_days() else "fresh"


def _month_window(end_month_start: datetime, months: int = 6) -> list[datetime]:
    return [_add_months(end_month_start, offset) for offset in range(-(months - 1), 1)]


def _latest_price_map(db: Session, anchor_ts: datetime, asset_ids: set[int]) -> Dict[int, Dict[str, Any]]:
    if not asset_ids:
        return {}
    placeholders = ",".join(str(int(asset_id)) for asset_id in sorted(asset_ids))
    q = text(
        f"""
                SELECT p1.asset_id, p1.price, p1.currency, p1.trade_date, p1.source, p1.provider_symbol, p1.exchange_code
        FROM prices p1
        JOIN (
          SELECT asset_id, MAX(trade_date) AS trade_date
          FROM prices
          WHERE trade_date IS NOT NULL
            AND trade_date <= :anchor_date
            AND asset_id IN ({placeholders})
          GROUP BY asset_id
        ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        """
    )
    rows = db.execute(q, {"anchor_date": anchor_ts.date()}).mappings().all()
    return {
        int(row["asset_id"]): {
            "price": float(row["price"]) if row["price"] is not None else None,
            "currency": row["currency"],
            "trade_date": row["trade_date"],
            "source": row["source"],
            "provider_symbol": row["provider_symbol"],
            "exchange_code": row["exchange_code"],
        }
        for row in rows
    }


def _positions_coverage_as_of(db: Session, anchor_ts: datetime, current_user_id: int) -> Optional[datetime]:
    q = text(
        """
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND NOT EXISTS (
              SELECT 1
              FROM broker_accounts ba
              JOIN portfolio_nav_snapshots ns ON ns.broker_account_id = ba.id
              WHERE ba.legacy_account_id = p.account_id
                AND ns.report_date <= :anchor_date
                AND ns.authority_status = 'authoritative'
            )
            AND """
        + account_scope_sql("acc")
        + """
          GROUP BY p.account_id
        )
        SELECT MIN(as_of) AS as_of FROM latest
        """
    )
    row = db.execute(
        q,
        {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().one()
    return _normalize_ts(row["as_of"])


def _crypto_snapshot_coverage_as_of(db: Session, anchor_date: Any, current_user_id: int) -> Any:
    q = text(
        """
        WITH latest AS (
          SELECT s.wallet_id, MAX(s.as_of_date) AS as_of_date
          FROM crypto_wallet_snapshots s
          JOIN crypto_wallets w ON w.id = s.wallet_id
          WHERE s.as_of_date <= :anchor_date
            AND w.status = 'active'
            AND """
        + account_scope_sql("w")
        + """
          GROUP BY s.wallet_id
        )
        SELECT MIN(as_of_date) AS as_of_date FROM latest
        """
    )
    row = db.execute(q, {"anchor_date": anchor_date, "current_user_id": current_user_id}).mappings().one()
    return row["as_of_date"]


def _serialize_net_worth(components: Dict[str, float]) -> Dict[str, float]:
    return {
        "total": components["total"],
        "cash": components["cash"],
        "stocks_funds": components["stocks_funds"],
        "crypto": components["crypto"],
        "liabilities": components["liabilities"],
    }


def _current_networth_state(db: Session, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    anchor = _current_anchor_ts()
    components = _networth_components(db, anchor, base_currency, current_user_id)
    rows = _synthetic_position_rows(db, anchor, current_user_id)
    price_map = _latest_price_map(
        db,
        anchor,
        {
            int(row["asset_id"])
            for row in rows
            if row.get("asset_id") is not None and str(row.get("asset_class") or "").upper() in {"STOCK", "FUND"}
        },
    )
    trade_dates = [row.get("trade_date") for row in price_map.values() if row.get("trade_date") is not None]
    market_data_as_of = min(trade_dates) if trade_dates else None
    positions_as_of = _positions_coverage_as_of(db, anchor, current_user_id)
    crypto_as_of = _crypto_snapshot_coverage_as_of(db, anchor.date(), current_user_id)
    cash_percent = round((components["cash"] / components["total"]) * 100, 2) if components["total"] > 0 else 0.0
    return {
        "anchor": anchor,
        "net_worth": _serialize_net_worth(components),
        "cash_percent": cash_percent,
        "freshness": {
            "positions_as_of": _iso_value(positions_as_of),
            "market_data_as_of": _iso_value(market_data_as_of),
            "crypto_as_of": _iso_value(crypto_as_of),
        },
    }


def _is_synthetic_internal_cash_movement(row: Dict[str, Any]) -> bool:
    tx_type = str(row.get("type") or "").upper()
    if tx_type == "TRANSFER":
        return True
    raw_category = str(row.get("category") or "").strip().lower()
    if raw_category in _SYNTHETIC_TRANSFER_CATEGORIES:
        return True
    text = " ".join(
        [
            str(row.get("merchant_counterparty") or ""),
            str(row.get("notes") or ""),
            str(row.get("category") or ""),
        ]
    ).upper()
    if tx_type == "INCOME" and raw_category.startswith("bank::"):
        if not any(marker in text for marker in _SYNTHETIC_ALLOWED_BANK_INCOME_MARKERS):
            return True
    return any(marker in text for marker in _SYNTHETIC_INTERNAL_MARKERS)


def _synthetic_position_rows(db: Session, anchor_ts: datetime, current_user_id: int) -> List[Dict[str, Any]]:
    q = text(
        """
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND NOT EXISTS (
              SELECT 1
              FROM broker_accounts ba
              JOIN portfolio_nav_snapshots ns ON ns.broker_account_id = ba.id
              WHERE ba.legacy_account_id = p.account_id
                AND ns.report_date <= :anchor_date
                AND ns.authority_status = 'authoritative'
            )
            AND """
        + account_scope_sql("acc")
        + """
          GROUP BY p.account_id
        ),
        map_exchange AS (
          SELECT
            m.asset_id,
            MIN(UPPER(m.exchange_code)) AS exchange_code
          FROM market_symbol_map m
          WHERE m.is_active = TRUE
          GROUP BY m.asset_id
        )
        SELECT
          p.account_id,
          p.as_of,
          acc.account_type,
          acc.currency AS account_currency,
          COALESCE(NULLIF(acc.platform, ''), pl.code) AS platform,
          COALESCE(pl_by_code.platform_type, pl.platform_type) AS platform_type,
          COALESCE(pl_by_code.country, pl.country, acc.country) AS platform_country,
          a.id AS asset_id,
          a.symbol,
          a.name,
          a.asset_class,
          a.quote_currency,
          a.home_country,
          mx.exchange_code,
          p.quantity,
          p.avg_cost,
          p.cost_basis_base
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN accounts acc ON acc.id = p.account_id
        LEFT JOIN platforms pl ON pl.id = acc.platform_id
        LEFT JOIN platforms pl_by_code ON pl_by_code.code = acc.platform
        JOIN assets a ON a.id = p.asset_id
        LEFT JOIN map_exchange mx ON mx.asset_id = a.id
        WHERE """
        + account_scope_sql("acc")
    )
    rows = db.execute(q, {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date(), "current_user_id": current_user_id}).mappings().all()
    if not rows:
        return []

    synthetic_rows: Dict[tuple[int, Optional[int], str], Dict[str, Any]] = {}
    account_snapshot_as_of: Dict[int, datetime] = {}
    account_meta: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        account_id = int(row["account_id"])
        normalized_as_of = _normalize_ts(row["as_of"])
        if normalized_as_of is None:
            continue
        account_snapshot_as_of[account_id] = normalized_as_of
        account_meta[account_id] = {
            "account_type": row["account_type"],
            "account_currency": row["account_currency"],
            "platform": row["platform"],
            "platform_type": row["platform_type"],
            "platform_country": row["platform_country"],
        }
        key = (account_id, row["asset_id"], (row["quote_currency"] or row["account_currency"] or "").upper())
        synthetic_rows[key] = {
            "account_id": account_id,
            "asset_id": row["asset_id"],
            "symbol": row["symbol"],
            "name": row["name"],
            "asset_class": row["asset_class"],
            "quote_currency": row["quote_currency"],
            "home_country": row["home_country"],
            "exchange_code": row["exchange_code"],
            "platform": row["platform"],
            "platform_type": row["platform_type"],
            "platform_country": row["platform_country"],
            "quantity": float(row["quantity"]) if row["quantity"] is not None else None,
            "avg_cost": float(row["avg_cost"]) if row["avg_cost"] is not None else None,
            "cost_basis_base": float(row["cost_basis_base"]) if row["cost_basis_base"] is not None else 0.0,
        }

    min_snapshot_as_of = min(account_snapshot_as_of.values())
    tx_rows = db.execute(
        text(
            """
            SELECT
              t.account_id,
              t.ts,
              t.amount,
              t.type,
              t.currency,
              t.category,
              t.merchant_counterparty,
              t.notes,
              t.asset_id,
              t.quantity,
              a.symbol,
              a.name,
              a.asset_class,
              a.quote_currency,
              a.home_country
            FROM transactions t
            JOIN accounts acc ON acc.id = t.account_id
            LEFT JOIN assets a ON a.id = t.asset_id
            WHERE t.ts > :min_snapshot_as_of
              AND t.ts < :anchor_ts
              AND """
            + account_scope_sql("acc")
            + """
            ORDER BY t.ts ASC, t.id ASC
            """
        ),
        {
            "min_snapshot_as_of": min_snapshot_as_of,
            "anchor_ts": anchor_ts,
            "current_user_id": current_user_id,
        },
    ).mappings().all()

    for raw_tx in tx_rows:
        tx = dict(raw_tx)
        account_id = int(tx["account_id"])
        snapshot_as_of = account_snapshot_as_of.get(account_id)
        tx_ts = _normalize_ts(tx["ts"])
        if snapshot_as_of is None or tx_ts is None or tx_ts <= snapshot_as_of:
            continue

        currency = (tx["currency"] or account_meta[account_id]["account_currency"] or "").upper()
        cash_key = next(
            (
                key
                for key, row in synthetic_rows.items()
                if row["account_id"] == account_id
                and row["asset_class"] == "CASH"
                and (row["quote_currency"] or currency or "").upper() == currency
            ),
            None,
        )
        if cash_key is None and currency:
            cash_key = (account_id, None, currency)
            synthetic_rows[cash_key] = {
                "account_id": account_id,
                "asset_id": None,
                "symbol": currency,
                "name": f"{currency} Cash",
                "asset_class": "CASH",
                "quote_currency": currency,
                "home_country": None,
                "exchange_code": None,
                "platform": account_meta[account_id]["platform"],
                "platform_type": account_meta[account_id]["platform_type"],
                "platform_country": account_meta[account_id]["platform_country"],
                "quantity": 0.0,
                "avg_cost": 1.0,
                "cost_basis_base": 0.0,
            }
        if cash_key is not None and not _is_synthetic_internal_cash_movement(tx):
            synthetic_rows[cash_key]["quantity"] = float(synthetic_rows[cash_key]["quantity"] or 0.0) + float(tx["amount"] or 0.0)
            synthetic_rows[cash_key]["cost_basis_base"] = float(synthetic_rows[cash_key]["cost_basis_base"] or 0.0) + float(tx["amount"] or 0.0)

        tx_asset_id = tx["asset_id"]
        tx_type = (tx["type"] or "").upper()
        tx_quantity = float(tx["quantity"]) if tx["quantity"] is not None else None
        tx_asset_class = (tx["asset_class"] or "").upper()
        if not tx_asset_id or tx_quantity is None or tx_type not in {"BUY", "SELL"} or tx_asset_class not in {"STOCK", "FUND"}:
            continue

        asset_currency = (tx["quote_currency"] or tx["currency"] or "").upper()
        position_key = (account_id, tx_asset_id, asset_currency)
        position = synthetic_rows.get(position_key)
        if position is None:
            position = {
                "account_id": account_id,
                "asset_id": tx_asset_id,
                "symbol": tx["symbol"],
                "name": tx["name"] or tx["symbol"],
                "asset_class": tx_asset_class,
                "quote_currency": tx["quote_currency"] or tx["currency"],
                "home_country": tx["home_country"],
                "exchange_code": None,
                "platform": account_meta[account_id]["platform"],
                "platform_type": account_meta[account_id]["platform_type"],
                "platform_country": account_meta[account_id]["platform_country"],
                "quantity": 0.0,
                "avg_cost": None,
                "cost_basis_base": 0.0,
            }
            synthetic_rows[position_key] = position

        if tx_type == "BUY":
            position["quantity"] = float(position["quantity"] or 0.0) + tx_quantity
            position["cost_basis_base"] = float(position["cost_basis_base"] or 0.0) + abs(float(tx["amount"] or 0.0))
            if tx_quantity > 0:
                position["avg_cost"] = abs(float(tx["amount"] or 0.0)) / tx_quantity
        else:
            position["quantity"] = float(position["quantity"] or 0.0) - tx_quantity

    return list(synthetic_rows.values())


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
    if quote_currency and quote_currency.upper() == "SGD":
        return "SG"
    if quote_currency and quote_currency.upper() == "HKD":
        return "HK"
    if quote_currency and quote_currency.upper() == "INR":
        return "IN"
    return "UNKNOWN"


def _networth_components(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> Dict[str, float]:
    """Compute reporting net worth components, synthesizing month-boundary state from real snapshots + activity."""
    if anchor_ts is None:
        return {"cash": 0.0, "stocks_funds": 0.0, "crypto": 0.0, "liabilities": 0.0, "total": 0.0}
    rows = _synthetic_position_rows(db, anchor_ts, current_user_id)
    if not rows:
        rows = []
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    price_map = _latest_price_map(
        db,
        anchor_ts,
        {
            int(r["asset_id"])
            for r in rows
            if r.get("asset_id") is not None and str(r.get("asset_class") or "").upper() in {"STOCK", "FUND"}
        },
    )
    currencies = {
        (price_map[int(r["asset_id"])]["currency"] if r.get("asset_id") in price_map else r["quote_currency"])
        for r in rows
        if r["quote_currency"] or r.get("asset_id") in price_map
    }
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    currencies.add("USD")  # Include USD for crypto wallet conversions
    rates = get_rates(anchor_ts, base_currency, currencies)
    cash = 0.0
    stocks_funds = 0.0
    crypto = 0.0
    # Positions contribute cash and brokerage holdings only.
    # Crypto net worth is sourced from wallet snapshots below.
    for r in rows:
        asset_class = str(r["asset_class"] or "").upper()
        asset_id = r.get("asset_id")
        latest_price = price_map.get(int(asset_id), {}).get("price") if asset_id is not None else None
        quote_currency = price_map.get(int(asset_id), {}).get("currency") if asset_id is not None else None
        cur = (quote_currency or r["quote_currency"] or base_currency).upper()
        quantity = float(r["quantity"]) if r["quantity"] is not None else None
        if asset_class in ("STOCK", "FUND") and quantity is not None and latest_price is not None:
            value_local = quantity * float(latest_price)
        else:
            value_local = float(r["cost_basis_base"] or 0.0)
        value = value_local * rates.get(cur, 1.0)
        if asset_class == "CASH":
            cash += value
        elif asset_class in ("STOCK", "FUND"):
            stocks_funds += value
    for row in canonical_nav_rows:
        nav_currency = str(row["base_currency"] or base_currency).upper()
        rate = rates.get(nav_currency, 1.0)
        cash_base = float(row["cash_base"] or 0.0)
        total_nav_base = float(row["total_nav_base"] or 0.0)
        cash += cash_base * rate
        stocks_funds += (total_nav_base - cash_base) * rate
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
              AND """
            + account_scope_sql("w")
            + """
            """
        ),
        {"as_of_date": as_of_date, "current_user_id": current_user_id},
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


def _geography(db: Session, anchor_ts: datetime, total: float, base_currency: str, current_user_id: int) -> List[Dict[str, Any]]:
    if total <= 0:
        return []
    q = text("""
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND NOT EXISTS (
              SELECT 1
              FROM broker_accounts ba
              JOIN portfolio_nav_snapshots ns ON ns.broker_account_id = ba.id
              WHERE ba.legacy_account_id = p.account_id
                AND ns.report_date <= :anchor_date
                AND ns.authority_status = 'authoritative'
            )
            AND """
            + account_scope_sql("acc")
            + """
          GROUP BY p.account_id
        ),
        latest_prices AS (
          SELECT p1.asset_id, p1.price, p1.currency, p1.trade_date, p1.source, p1.provider_symbol, p1.exchange_code
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
          AND """
        + account_scope_sql("acc")
        + """
    """)
    rows = db.execute(
        q,
        {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()
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


def _blank_geo_country_bucket() -> Dict[str, float]:
    return {"stocks_funds": 0.0, "cash": 0.0, "crypto": 0.0}


def _geography_exposure(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    q = text(
        """
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND """
          + account_scope_sql("acc")
          + """
          GROUP BY p.account_id
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
          SELECT p1.asset_id, p1.price, p1.currency, p1.trade_date, p1.source, p1.provider_symbol, p1.exchange_code
          FROM prices p1
          JOIN (
            SELECT asset_id, MAX(trade_date) AS trade_date
            FROM prices
            WHERE trade_date IS NOT NULL AND trade_date <= :anchor_date
            GROUP BY asset_id
          ) lp ON lp.asset_id = p1.asset_id AND lp.trade_date = p1.trade_date
        )
        SELECT
          a.asset_class AS asset_class,
          a.symbol AS symbol,
          a.home_country AS home_country,
          COALESCE(lp.currency, a.quote_currency) AS quote_currency,
          COALESCE(pl.code, acc.platform) AS platform,
          mx.exchange_code AS exchange_code,
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
        WHERE a.asset_class IN ('CASH', 'STOCK', 'FUND')
          AND """
        + account_scope_sql("acc")
        + """
        """
    )
    rows = db.execute(
        q,
        {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()
    currencies = {(row.get("quote_currency") or "").upper() for row in rows if row.get("quote_currency")}
    currencies.add("USD")
    rates = get_rates(anchor_ts, base_currency, currencies)
    usd_rate = rates.get("USD", 1.0)

    buckets: Dict[str, Dict[str, float]] = {}

    def _bucket(country: str) -> Dict[str, float]:
        if country not in buckets:
            buckets[country] = _blank_geo_country_bucket()
        return buckets[country]

    for row in rows:
        asset_class = str(row.get("asset_class") or "").upper()
        quote_currency = (row.get("quote_currency") or base_currency).upper()
        value_base = float(row.get("value") or 0.0) * rates.get(quote_currency, 1.0)
        if value_base <= 0:
            continue
        country = _infer_country(
            row.get("symbol"),
            row.get("home_country"),
            row.get("platform"),
            row.get("quote_currency"),
            row.get("exchange_code"),
        )
        bucket = _bucket(country)
        if asset_class == "CASH":
            bucket["cash"] += value_base
        else:
            bucket["stocks_funds"] += value_base

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
              UPPER(COALESCE(i.symbol, '')) AS symbol,
              SUM(i.value_usd) AS value_usd
            FROM crypto_wallet_snapshots s
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
            WHERE w.status = 'active'
              AND """
            + account_scope_sql("w")
            + """
            GROUP BY UPPER(COALESCE(i.symbol, ''))
            """
        ),
        {"as_of_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()

    us_bucket = _bucket("US")
    for row in wallet_rows:
        value_usd = float(row.get("value_usd") or 0.0)
        if value_usd <= 0:
            continue
        value_base = value_usd * usd_rate
        symbol = str(row.get("symbol") or "").upper()
        if symbol in {"USDC", "USDT"}:
            us_bucket["cash"] += value_base
        else:
            us_bucket["crypto"] += value_base

    items: List[Dict[str, Any]] = []
    grand_total = 0.0
    for country, vals in buckets.items():
        country_total = vals["stocks_funds"] + vals["cash"] + vals["crypto"]
        if country_total <= 0:
            continue
        grand_total += country_total
        items.append(
            {
                "country": country,
                "stocks_funds": vals["stocks_funds"],
                "cash": vals["cash"],
                "crypto": vals["crypto"],
                "total": country_total,
            }
        )

    items.sort(key=lambda row: row["total"], reverse=True)
    for row in items:
        row["percent"] = round((row["total"] / grand_total) * 100, 2) if grand_total > 0 else 0.0

    return {"base_currency": base_currency, "total": grand_total, "items": items}


def _top_holdings(
    db: Session,
    anchor_ts: datetime,
    total: float,
    base_currency: str,
    current_user_id: int,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    if total <= 0:
        return []
    
    # Combined query: positions (stocks/funds, excluding CASH) UNION ALL crypto wallet snapshots (grouped by base_asset)
    q = text("""
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND NOT EXISTS (
              SELECT 1
              FROM broker_accounts ba
              JOIN portfolio_nav_snapshots ns ON ns.broker_account_id = ba.id
              WHERE ba.legacy_account_id = p.account_id
                AND ns.report_date <= :anchor_date
                AND ns.authority_status = 'authoritative'
            )
            AND """
            + account_scope_sql("acc")
            + """
          GROUP BY p.account_id
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
          SELECT p1.asset_id, p1.price, p1.currency, p1.trade_date, p1.source, p1.provider_symbol, p1.exchange_code
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
            CAST(COALESCE(NULLIF(acc.platform, ''), pl.code) AS TEXT) AS platform,
            p.quantity AS quantity,
            p.avg_cost AS avg_cost,
            lp.price AS latest_price,
            lp.trade_date AS latest_trade_date,
            CAST(lp.source AS TEXT) AS price_source,
            CAST(lp.provider_symbol AS TEXT) AS provider_symbol,
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
            AND """
          + account_scope_sql("acc")
          + """
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
            AND """
          + account_scope_sql("w")
          + """
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
            CAST(NULL AS DATE) AS latest_trade_date,
            CAST(NULL AS TEXT) AS price_source,
            CAST(NULL AS TEXT) AS provider_symbol,
            g.value AS value
          FROM crypto_item_groups g
        )
        SELECT * FROM positions_holdings
        UNION ALL
        SELECT * FROM crypto_holdings
    """)
    rows = db.execute(
        q,
        {
            "anchor_ts": anchor_ts,
            "anchor_date": anchor_ts.date(),
            "as_of_date": anchor_ts.date(),
            "current_user_id": current_user_id,
        },
    ).mappings().all()

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
                "latest_trade_date": _iso_value(r["latest_trade_date"]),
                "quote_age_days": _quote_age_days(r["latest_trade_date"]),
                "price_source": r["price_source"],
                "price_provider": _price_provider(r["price_source"]),
                "quote_freshness_status": _quote_freshness_status(r["latest_trade_date"]),
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
        if agg[key]["latest_trade_date"] is None and r["latest_trade_date"] is not None:
            agg[key]["latest_trade_date"] = _iso_value(r["latest_trade_date"])
        if agg[key]["price_source"] is None and r["price_source"] is not None:
            agg[key]["price_source"] = r["price_source"]
            agg[key]["price_provider"] = _price_provider(r["price_source"])
        if agg[key]["quote_freshness_status"] == "missing":
            agg[key]["quote_age_days"] = _quote_age_days(r["latest_trade_date"])
            agg[key]["quote_freshness_status"] = _quote_freshness_status(r["latest_trade_date"])
        
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
        r["quote_age_days"] = int(r["quote_age_days"]) if r.get("quote_age_days") is not None else None

        key = (r["asset_id"], r["symbol"], r["asset_class"])
        geo = geo_bucket.get(key, {})
        platform = platform_bucket.get(key, {})
        r["geo"] = max(geo.items(), key=lambda x: x[1])[0] if geo else "UNKNOWN"
        r["platform"] = max(platform.items(), key=lambda x: x[1])[0] if platform else "UNKNOWN"
    
    return out


def _top_movers_from_holdings(
    current_holdings: List[Dict[str, Any]],
    prior_holdings: List[Dict[str, Any]],
    compare_month: str,
    limit: int = 3,
) -> Dict[str, Any]:
    current_by_key = {
        (row.get("asset_id"), row["symbol"], row["asset_class"]): row
        for row in current_holdings
    }
    prior_by_key = {
        (row.get("asset_id"), row["symbol"], row["asset_class"]): row
        for row in prior_holdings
    }
    movers: List[Dict[str, Any]] = []
    for key in sorted(set(current_by_key) | set(prior_by_key), key=lambda item: (str(item[1]).lower(), str(item[2]).lower())):
        current = current_by_key.get(key)
        prior = prior_by_key.get(key)
        current_value = float(current["value"]) if current else 0.0
        previous_value = float(prior["value"]) if prior else 0.0
        delta_abs = current_value - previous_value
        if abs(delta_abs) < 0.005:
            continue
        delta_pct = (delta_abs / previous_value) if previous_value else None
        symbol = current["symbol"] if current else prior["symbol"]
        asset_class = current["asset_class"] if current else prior["asset_class"]
        asset_id = current.get("asset_id") if current else prior.get("asset_id")
        movers.append(
            {
                "asset_id": asset_id,
                "symbol": symbol,
                "asset_class": asset_class,
                "current_value": current_value,
                "previous_value": previous_value,
                "delta_abs": delta_abs,
                "delta_pct": delta_pct,
                "compare_month": compare_month,
            }
        )

    gainers = sorted(
        [row for row in movers if row["delta_abs"] > 0],
        key=lambda row: (-row["delta_abs"], row["symbol"].lower()),
    )[:limit]
    detractors = sorted(
        [row for row in movers if row["delta_abs"] < 0],
        key=lambda row: (row["delta_abs"], row["symbol"].lower()),
    )[:limit]
    return {
        "compare_month": compare_month,
        "gainers": gainers,
        "detractors": detractors,
    }


def _stock_geo_bucket(country: str | None) -> str:
    normalized = (country or "").upper()
    if normalized in {"US", "HK", "SG", "IN"}:
        return normalized
    return "Other"


def _stock_geo_value_map(items: list[dict[str, Any]]) -> dict[str, float]:
    grouped = {"US": 0.0, "HK": 0.0, "SG": 0.0, "IN": 0.0, "Other": 0.0}
    for item in items:
        grouped[_stock_geo_bucket(item.get("key"))] += float(item.get("value") or 0.0)
    return grouped


def _stock_key_value_map(items: list[dict[str, Any]]) -> dict[str, float]:
    grouped: dict[str, float] = {}
    for item in items:
        key = str(item.get("key") or "UNKNOWN")
        grouped[key] = grouped.get(key, 0.0) + float(item.get("value") or 0.0)
    return grouped


def _stock_breakdown_items(
    current_values: dict[str, float],
    snapshot_values: dict[str, float],
    *,
    current_total: float,
    preferred_order: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    keys = set(current_values) | set(snapshot_values)
    if preferred_order:
        ordered_keys = [key for key in preferred_order if key in keys]
        ordered_keys.extend(sorted(keys - set(preferred_order)))
    else:
        ordered_keys = sorted(keys, key=lambda key: (-current_values.get(key, 0.0), key))

    items: list[dict[str, Any]] = []
    for key in ordered_keys:
        current_value = current_values.get(key, 0.0)
        snapshot_value = snapshot_values.get(key, 0.0)
        delta_abs = current_value - snapshot_value
        items.append(
            {
                "key": key,
                "current_value": current_value,
                "snapshot_value": snapshot_value,
                "delta_abs": delta_abs,
                "delta_pct": (delta_abs / snapshot_value) if snapshot_value > 0 else None,
                "percent": round((current_value / current_total) * 100, 2) if current_total > 0 else 0.0,
            }
        )
    return items


def _stock_geography_breakdown(
    current_payload: dict[str, Any],
    snapshot_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    current_values = _stock_geo_value_map(current_payload["by_country"])
    snapshot_values = _stock_geo_value_map(snapshot_payload["by_country"])

    return [
        {
            "geography": item["key"],
            "current_value": item["current_value"],
            "snapshot_value": item["snapshot_value"],
            "delta_abs": item["delta_abs"],
            "delta_pct": item["delta_pct"],
        }
        for item in _stock_breakdown_items(
            current_values,
            snapshot_values,
            current_total=float(current_payload.get("total") or 0.0),
            preferred_order=("US", "HK", "SG", "IN", "Other"),
        )
    ]


def _stock_platform_breakdown(
    current_payload: dict[str, Any],
    snapshot_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    current_values = _stock_key_value_map(current_payload["by_platform"])
    snapshot_values = _stock_key_value_map(snapshot_payload["by_platform"])
    return _stock_breakdown_items(
        current_values,
        snapshot_values,
        current_total=float(current_payload.get("total") or 0.0),
    )


def _quote_freshness_summary(top_holdings: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"fresh": 0, "stale": 0, "missing": 0}
    for holding in top_holdings:
        status = str(holding.get("quote_freshness_status") or "missing").lower()
        if status not in summary:
            status = "missing"
        summary[status] += 1
    return summary


def _sum_balances(items: list[dict[str, Any]]) -> float:
    return sum(float(item.get("value") or 0.0) for item in items)


def _cash_currency_bucket(currency: str | None) -> str:
    normalized = (currency or "").upper()
    if normalized in {"USD", "SGD", "HKD", "INR"}:
        return normalized
    return "Other"


def _cash_currency_value_map(items: list[dict[str, Any]]) -> dict[str, float]:
    grouped = {"USD": 0.0, "SGD": 0.0, "HKD": 0.0, "INR": 0.0, "Other": 0.0}
    for item in items:
        grouped[_cash_currency_bucket(item.get("currency"))] += float(item.get("value") or 0.0)
    return grouped


def _cash_currency_breakdown(
    current_balances: list[dict[str, Any]],
    snapshot_balances: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    current_values = _cash_currency_value_map(current_balances)
    snapshot_values = _cash_currency_value_map(snapshot_balances)
    items: list[dict[str, Any]] = []
    for currency in ("USD", "SGD", "HKD", "INR", "Other"):
        current_value = current_values.get(currency, 0.0)
        snapshot_value = snapshot_values.get(currency, 0.0)
        delta_abs = current_value - snapshot_value
        items.append(
            {
                "currency": currency,
                "current_value": current_value,
                "snapshot_value": snapshot_value,
                "delta_abs": delta_abs,
                "delta_pct": (delta_abs / snapshot_value) if snapshot_value > 0 else None,
            }
        )
    return items


def _stablecoin_cash_balances(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> list[dict[str, Any]]:
    rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              WHERE as_of_date <= :as_of_date
              GROUP BY wallet_id
            )
            SELECT SUM(i.value_usd) AS total_usd
            FROM crypto_wallet_snapshots s
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            JOIN crypto_wallets w ON w.id = s.wallet_id
            JOIN crypto_wallet_snapshot_items i ON i.snapshot_id = s.id
            WHERE w.status = 'active'
              AND """
            + account_scope_sql("w")
            + """
              AND UPPER(COALESCE(i.symbol, '')) IN ('USDC', 'USDT')
            """
        ),
        {"as_of_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()
    total_usd = sum(float(row.get("total_usd") or 0.0) for row in rows)
    if total_usd <= 0:
        return []
    usd_rate = get_rates(anchor_ts, base_currency, {"USD"}).get("USD", 1.0)
    return [{"currency": "USD", "value": total_usd * usd_rate}]


def _cash_trend(
    db: Session,
    month_start: datetime,
    base_currency: str,
    current_user_id: int,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for candidate_month in _month_window(month_start, months=6):
        anchor = _anchor_ts(candidate_month)
        as_of = _effective_as_of(db, anchor, current_user_id)
        value = None
        if as_of is not None:
            value = _sum_balances(
                _cash_balances(db, anchor, base_currency, current_user_id)
                + _stablecoin_cash_balances(db, anchor, base_currency, current_user_id)
            )
        points.append({"month": candidate_month.strftime("%Y-%m"), "value": value})
    return points


def _cash_balances(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> List[Dict[str, Any]]:
    q = text("""
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND """
            + account_scope_sql("acc")
            + """
          GROUP BY p.account_id
        )
        SELECT
          a.quote_currency AS currency,
          p.cost_basis_base AS value
        FROM positions p
        JOIN latest l ON l.account_id = p.account_id AND l.as_of = p.as_of
        JOIN assets a ON a.id = p.asset_id
        WHERE a.asset_class = 'CASH'
    """)
    rows = db.execute(q, {"anchor_ts": anchor_ts, "current_user_id": current_user_id}).mappings().all()
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


def _cash_deposits(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    buckets: Dict[str, float] = {}

    cash_rows = db.execute(
        text(
            """
            WITH latest AS (
              SELECT p.account_id, MAX(p.as_of) AS as_of
              FROM positions p
              JOIN accounts scoped_acc ON scoped_acc.id = p.account_id
              WHERE p.as_of <= :anchor_ts
                AND """
            + account_scope_sql("scoped_acc")
            + """
              GROUP BY p.account_id
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
              AND """
            + account_scope_sql("acc")
            + """
            """
        ),
        {"anchor_ts": anchor_ts, "current_user_id": current_user_id},
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
              AND """
            + account_scope_sql("w")
            + """
              AND UPPER(COALESCE(i.symbol, '')) IN ('USDC', 'USDT')
            GROUP BY i.chain
            """
        ),
        {"as_of_date": anchor_ts.date(), "current_user_id": current_user_id},
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


def _cashflow(db: Session, start: datetime, end: datetime, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    q = text(
        """
        SELECT
          t.type,
          t.amount,
          t.currency
        FROM transactions t
        JOIN accounts a ON a.id = t.account_id
        WHERE t.ts >= :start AND t.ts < :end
          AND """
        + account_scope_sql("a")
        + """
        """
    )
    rows = db.execute(q, {"start": start, "end": end, "current_user_id": current_user_id}).mappings().all()
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


def _compute_net_worth_changes(
    db: Session,
    month_start: datetime,
    as_of: datetime | None,
    current_value: float,
    base_currency: str,
    compare_set: set[str],
    current_user_id: int,
    value_selector: Callable[[Dict[str, float]], float] = lambda nw: nw["total"],
) -> Dict[str, Dict[str, Any]]:
    changes: Dict[str, Dict[str, Any]] = {}

    def _delta(label: str, other_month_start: datetime):
        other_anchor = _anchor_ts(other_month_start)
        other_as_of = _effective_as_of(db, other_anchor, current_user_id)
        other_nw = _networth_components(db, other_anchor, base_currency, current_user_id)
        prev_value = value_selector(other_nw)

        abs_change = current_value - prev_value
        pct_change = (abs_change / prev_value) if prev_value > 0 else None

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

    return changes


def _compute_component_changes(
    db: Session,
    month_start: datetime,
    as_of: datetime | None,
    current_components: Dict[str, float],
    base_currency: str,
    current_user_id: int,
) -> Dict[str, Dict[str, Any]]:
    prior_month_start = _add_months(month_start, -1)
    prior_anchor = _anchor_ts(prior_month_start)
    prior_as_of = _effective_as_of(db, prior_anchor, current_user_id)
    prior_components = _networth_components(db, prior_anchor, base_currency, current_user_id)

    out: Dict[str, Dict[str, Any]] = {}
    for key in ("cash", "stocks_funds", "crypto"):
        current_value = current_components[key]
        prior_value = prior_components[key]
        abs_change = current_value - prior_value
        out[key] = {
            "abs": abs_change,
            "pct": (abs_change / prior_value) if prior_value > 0 else None,
            "current_as_of": as_of.isoformat() if as_of else None,
            "compare_as_of": prior_as_of.isoformat() if prior_as_of else None,
            "compare_month": prior_month_start.strftime("%Y-%m"),
        }
    return out


def _platform_allocation(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> dict:
    rows = _synthetic_position_rows(db, anchor_ts, current_user_id)
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    price_map = _latest_price_map(
        db,
        anchor_ts,
        {
            int(r["asset_id"])
            for r in rows
            if r.get("asset_id") is not None and str(r.get("asset_class") or "").upper() in {"STOCK", "FUND"}
        },
    )
    wallet_total = db.execute(
        text(
            """
            WITH latest AS (
              SELECT s.wallet_id, MAX(s.as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots s
              JOIN crypto_wallets w ON w.id = s.wallet_id
              WHERE s.as_of_date <= :as_of_date
                AND w.status = 'active'
                AND """
            + account_scope_sql("w")
            + """
              GROUP BY s.wallet_id
            )
            SELECT SUM(s.total_usd) AS total_usd
            FROM crypto_wallet_snapshots s
            JOIN latest l ON l.wallet_id = s.wallet_id AND l.as_of_date = s.as_of_date
            """
        ),
        {"as_of_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().one()
    wallet_usd = float(wallet_total["total_usd"]) if wallet_total and wallet_total["total_usd"] else 0.0
    currencies = {
        (price_map[int(r["asset_id"])]["currency"] if r.get("asset_id") in price_map else r["quote_currency"])
        for r in rows
        if r.get("quote_currency") or r.get("asset_id") in price_map
    }
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    if wallet_usd:
        currencies.add("USD")
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[tuple, float] = {}
    for r in rows:
        asset_class = str(r.get("asset_class") or "").upper()
        if asset_class == "CRYPTO":
            continue
        asset_id = r.get("asset_id")
        latest_price = price_map.get(int(asset_id), {}).get("price") if asset_id is not None else None
        quote_currency = price_map.get(int(asset_id), {}).get("currency") if asset_id is not None else None
        cur = (quote_currency or r.get("quote_currency") or base_currency).upper()
        quantity = float(r["quantity"]) if r.get("quantity") is not None else None
        if asset_class in ("STOCK", "FUND") and quantity is not None and latest_price is not None:
            value_local = quantity * float(latest_price)
        else:
            value_local = float(r.get("cost_basis_base") or 0.0)
        value = value_local * rates.get(cur, 1.0)
        key = (r.get("platform") or "UNKNOWN", r.get("platform_type"), r.get("platform_country"))
        buckets[key] = buckets.get(key, 0.0) + value
    for row in canonical_nav_rows:
        nav_currency = str(row.get("base_currency") or base_currency).upper()
        value = float(row.get("total_nav_base") or 0.0) * rates.get(nav_currency, 1.0)
        key = (row.get("platform") or "UNKNOWN", row.get("platform_type"), row.get("country"))
        buckets[key] = buckets.get(key, 0.0) + value
    if wallet_usd:
        buckets[("CRYPTO", "WALLET_PROVIDER", None)] = buckets.get(("CRYPTO", "WALLET_PROVIDER", None), 0.0) + (
            wallet_usd * rates.get("USD", 1.0)
        )
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
    return {"as_of": anchor_ts.isoformat(), "total": total, "items": items}


def _stock_exposure(db: Session, anchor_ts: datetime, base_currency: str, current_user_id: int) -> dict:
    q = text(
        """
        WITH latest AS (
          SELECT p.account_id, MAX(p.as_of) AS as_of
          FROM positions p
          JOIN accounts acc ON acc.id = p.account_id
          WHERE p.as_of <= :anchor_ts
            AND NOT EXISTS (
              SELECT 1
              FROM broker_accounts ba
              JOIN portfolio_nav_snapshots ns ON ns.broker_account_id = ba.id
              WHERE ba.legacy_account_id = p.account_id
                AND ns.report_date <= :anchor_date
                AND ns.authority_status = 'authoritative'
            )
            AND """
            + account_scope_sql("acc")
            + """
          GROUP BY p.account_id
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
          COALESCE(NULLIF(a.platform, ''), pl.code) AS platform,
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
          AND """
        + account_scope_sql("a")
        + """
        """
    )
    rows = db.execute(
        q,
        {"anchor_ts": anchor_ts, "anchor_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    if not rows and not canonical_nav_rows:
        return {"as_of": None, "base_currency": base_currency, "total": 0.0, "by_country": [], "by_platform": []}
    currencies = {r["quote_currency"] for r in rows if r["quote_currency"]}
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
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
    for row in canonical_nav_rows:
        nav_currency = str(row.get("base_currency") or base_currency).upper()
        value = (float(row.get("total_nav_base") or 0.0) - float(row.get("cash_base") or 0.0)) * rates.get(nav_currency, 1.0)
        if value <= 0:
            continue
        platform = row.get("platform") or "UNKNOWN"
        country = row.get("country") or "UNKNOWN"
        total += value
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


@router.get("/bootstrap", response_model=BootstrapResponse)
def dashboard_bootstrap(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Lean first-paint payload: net worth + exposure totals only.

    Skips geography, top_holdings, cashflow, and comparisons so the hero card
    and stock/crypto/cash exposure cards render on first paint.
    """
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    current_state = _current_networth_state(db, base_currency, current_user.id)
    current_stock_data = _stock_exposure(db, current_state["anchor"], base_currency, current_user.id)
    as_of, boundary_exact, freshness_status = _snapshot_freshness(db, anchor, current_user.id)
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of

    nw = _networth_components(db, anchor, base_currency, current_user.id)
    stock_data = _stock_exposure(db, anchor, base_currency, current_user.id)

    cash_percent = round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0
    snapshot_day = _configured_snapshot_day()

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "current_net_worth_as_of": current_state["anchor"].isoformat(),
        "current_net_worth": current_state["net_worth"],
        "current_net_worth_freshness": current_state["freshness"],
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "net_worth": _serialize_net_worth(nw),
        "current_stock_exposure_total": current_stock_data["total"],
        "current_crypto_exposure_total": current_state["net_worth"]["crypto"],
        "current_cash_percent": current_state["cash_percent"],
        "stock_exposure_total": stock_data["total"],
        "crypto_exposure_total": nw["crypto"],
        "cash_percent": cash_percent,
    }


@router.get("/net-worth-change", response_model=NetWorthChangeResponse)
def dashboard_net_worth_change(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("prev_month,prev_year", description="Comma-separated: prev_month,prev_year"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    as_of, boundary_exact, freshness_status = _snapshot_freshness(db, anchor, current_user.id)
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of
    nw = _networth_components(db, anchor, base_currency, current_user.id)
    compare_set = {c.strip() for c in compare.split(",") if c.strip()}
    changes = _compute_net_worth_changes(
        db=db,
        month_start=month_start,
        as_of=as_of,
        current_value=nw["total"],
        base_currency=base_currency,
        compare_set=compare_set,
        current_user_id=current_user.id,
    )
    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "net_worth_change": changes if changes else None,
    }


@router.get("/summary", response_model=DashboardSummaryResponse)
def dashboard_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    compare: str = Query("", description="Comma-separated: prev_month,prev_year"),
    skip_networth: bool = Query(False, description="When True, skip net-worth computation and omit net_worth/net_worth_as_of/net_worth_change from response"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    # Calendar month window for cashflow
    month_start = _parse_month(month)
    month_end = _add_months(month_start, 1)

    # Snapshot anchor + effective snapshot timestamp
    anchor = _completed_snapshot_anchor_ts(month_start)
    snapshot_day = _configured_snapshot_day()
    top_holdings_limit = _summary_top_holdings_limit()

    if skip_networth:
        nw = _networth_components(db, anchor, base_currency, current_user.id)
        geo = _geography(db, anchor, nw["total"], base_currency, current_user.id)
        top = _top_holdings(db, anchor, nw["total"], base_currency, current_user.id, limit=top_holdings_limit)
        cash_balances = _cash_balances(db, anchor, base_currency, current_user.id)
        cf = _cashflow(db, month_start, month_end, base_currency, current_user.id)
        cash_percent = round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0
        return JSONResponse(content={
            "as_of_month": month,
            "base_currency": base_currency,
            "snapshot_day": snapshot_day,
            "geography": geo,
            "cash_flow": cf,
            "top_holdings": top,
            "cash_balances": cash_balances,
            "cash_percent": cash_percent,
        })

    as_of, boundary_exact, freshness_status = _snapshot_freshness(db, anchor, current_user.id)
    current_state = _current_networth_state(db, base_currency, current_user.id)
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of

    nw = _networth_components(db, anchor, base_currency, current_user.id)
    geo = _geography(db, anchor, nw["total"], base_currency, current_user.id)
    top = _top_holdings(db, anchor, nw["total"], base_currency, current_user.id, limit=top_holdings_limit)
    cash_balances = _cash_balances(db, anchor, base_currency, current_user.id)
    cf = _cashflow(db, month_start, month_end, base_currency, current_user.id)

    compare_set = {c.strip() for c in compare.split(",") if c.strip()}
    changes = _compute_net_worth_changes(
        db=db,
        month_start=month_start,
        as_of=as_of,
        current_value=nw["total"],
        base_currency=base_currency,
        compare_set=compare_set,
        current_user_id=current_user.id,
    )
    component_changes = (
        _compute_component_changes(
            db=db,
            month_start=month_start,
            as_of=as_of,
            current_components=nw,
            base_currency=base_currency,
            current_user_id=current_user.id,
        )
        if "prev_month" in compare_set
        else None
    )
    top_movers = None
    if "prev_month" in compare_set:
        prev_month_start = _add_months(month_start, -1)
        prev_anchor = _anchor_ts(prev_month_start)
        prev_components = _networth_components(db, prev_anchor, base_currency, current_user.id)
        prev_top = _top_holdings(
            db,
            prev_anchor,
            prev_components["total"],
            base_currency,
            current_user.id,
            limit=max(top_holdings_limit, 250),
        )
        top_movers = _top_movers_from_holdings(top, prev_top, prev_month_start.strftime("%Y-%m"))

    # Compute cash_percent
    cash_percent = round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "current_net_worth_as_of": current_state["anchor"].isoformat(),
        "current_net_worth": current_state["net_worth"],
        "current_net_worth_freshness": current_state["freshness"],
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "net_worth": _serialize_net_worth(nw),
        "geography": geo,
        "cash_flow": cf,
        "top_holdings": top,
        "cash_balances": cash_balances,
        "net_worth_change": changes if changes else None,
        "net_worth_component_change": component_changes,
        "top_movers": top_movers,
        "cash_percent": cash_percent,
    }


@router.get("/stock-holdings", response_model=StockHoldingsResponse)
def stock_holdings_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    current_anchor = _current_anchor_ts()
    snapshot_day = _configured_snapshot_day()
    top_holdings_limit = _summary_top_holdings_limit()
    as_of = _effective_as_of(db, anchor, current_user.id)
    current_holdings_as_of = _positions_coverage_as_of(db, current_anchor, current_user.id)
    reporting_as_of = anchor if as_of is not None else None
    boundary_exact = as_of == anchor if as_of is not None else False
    freshness_status = "exact" if boundary_exact else ("synthetic" if as_of is not None else "missing")
    current_nw = _networth_components(db, current_anchor, base_currency, current_user.id)
    top = [
        row
        for row in _top_holdings(db, current_anchor, current_nw["total"], base_currency, current_user.id, limit=top_holdings_limit)
        if str(row.get("asset_class") or "").upper() in {"STOCK", "FUND"}
    ]
    current_stock_exposure = _stock_exposure(db, current_anchor, base_currency, current_user.id)
    snapshot_stock_exposure = _stock_exposure(db, anchor, base_currency, current_user.id)
    geography_breakdown = _stock_geography_breakdown(current_stock_exposure, snapshot_stock_exposure)
    platform_breakdown = _stock_platform_breakdown(current_stock_exposure, snapshot_stock_exposure)
    quote_freshness_summary = _quote_freshness_summary(top)

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "current_holdings_as_of": current_holdings_as_of.isoformat() if current_holdings_as_of else None,
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": as_of.isoformat() if as_of else None,
        "net_worth_boundary_at": anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "top_holdings": top,
        "geography_breakdown": geography_breakdown,
        "platform_breakdown": platform_breakdown,
        "stock_current_total": current_stock_exposure["total"],
        "stock_snapshot_total": snapshot_stock_exposure["total"],
        "quote_freshness_summary": quote_freshness_summary,
    }


@router.get("/platform-allocation", response_model=PlatformAllocationOut)
def platform_allocation(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor, current_user.id)
    payload = _platform_allocation(db, anchor, base_currency, current_user.id)
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
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _anchor_ts(month_start)
    current_anchor = _current_anchor_ts()
    payload = _cash_deposits(db, current_anchor, base_currency, current_user.id)
    snapshot_balances = _cash_balances(db, anchor, base_currency, current_user.id) + _stablecoin_cash_balances(
        db, anchor, base_currency, current_user.id
    )
    current_balances = _cash_balances(db, current_anchor, base_currency, current_user.id) + _stablecoin_cash_balances(
        db, current_anchor, base_currency, current_user.id
    )
    current_total = _sum_balances(current_balances)
    snapshot_total = _sum_balances(snapshot_balances)
    delta_abs = current_total - snapshot_total
    return CashDepositsOut(
        total=payload["total"],
        items=[CashDepositsItem(**item) for item in payload["items"]],
        as_of_month=month,
        base_currency=base_currency,
        snapshot_day=_configured_snapshot_day(),
        current_cash_as_of=_iso_value(_positions_coverage_as_of(db, current_anchor, current_user.id)),
        snapshot_cash_as_of=_iso_value(_effective_as_of(db, anchor, current_user.id)),
        current_total=current_total,
        snapshot_total=snapshot_total,
        delta_abs=delta_abs,
        delta_pct=(delta_abs / snapshot_total) if snapshot_total > 0 else None,
        trend=[MiniTrendPoint(**point) for point in _cash_trend(db, month_start, base_currency, current_user.id)],
        currency_breakdown=[
            CashCurrencyBreakdownItem(**item)
            for item in _cash_currency_breakdown(current_balances, snapshot_balances)
        ],
    )


@router.get("/stock-exposure", response_model=StockExposureOut)
def stock_exposure(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor, current_user.id)
    payload = _stock_exposure(db, anchor, base_currency, current_user.id)
    return StockExposureOut(
        as_of=as_of.isoformat() if as_of else None,
        base_currency=base_currency,
        total=payload["total"],
        by_country=[StockExposureItem(**item) for item in payload["by_country"]],
        by_platform=[StockExposureItem(**item) for item in payload["by_platform"]],
    )


@router.get("/geography-exposure", response_model=GeographyExposureOut)
def geography_exposure(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    month_start = _parse_month(month)
    anchor = _anchor_ts(month_start)
    as_of = _effective_as_of(db, anchor, current_user.id)
    payload = _geography_exposure(db, anchor, base_currency, current_user.id)
    return GeographyExposureOut(
        as_of=as_of.isoformat() if as_of else None,
        base_currency=base_currency,
        total=payload["total"],
        items=[GeographyExposureItem(**item) for item in payload["items"]],
    )
