from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Callable
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, account_scope_sql, allow_legacy_null_ownership, require_current_user
from app.crypto.valuation import latest_wallet_valuation
from app.db.session import get_db
from app.market_data.service import latest_status_by_exchange
from app.schemas.dashboard import (
    BootstrapResponse,
    CashDepositsItem,
    CashCurrencyBreakdownItem,
    CashDepositsOut,
    DashboardSummaryResponse,
    DataHubActivityItem,
    DataHubImportHealth,
    DataHubMarketData,
    DataHubSummaryResponse,
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
    TopMovers,
    WealthTimelineBackfillResponse,
    WealthTimelineResponse,
)
from app.fx import get_rates
from app.portfolio.ibkr_flex import latest_authoritative_nav_by_legacy_account
from app.portfolio.canonical_reads import (
    canonical_account_balance_rows,
    canonical_position_rows_by_legacy_account,
    canonical_snapshot_coverage_as_of,
    get_data_completeness_status,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"], dependencies=[Depends(require_current_user)])

_UPPERCASE_SOURCE_CODES = {"DBS", "OCBC", "UOB", "IBKR", "POSB", "CITI", "HSBC", "SCB"}


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
    tz = ZoneInfo(os.getenv("TZ", "Asia/Singapore"))
    return datetime.now(tz=tz).replace(microsecond=0)


def _completed_snapshot_anchor_ts(month_start: datetime) -> datetime:
    requested_anchor = _anchor_ts(month_start)
    if requested_anchor <= _current_anchor_ts():
        return requested_anchor
    return _anchor_ts(_add_months(month_start, -1))


def _effective_anchor_for_month(month_start: datetime) -> tuple[datetime, bool]:
    """The anchor a "browse holdings as of {month}" view should use, and whether
    it's live. The current (or any future) calendar month shows live data — the
    freshest computable state, matching every other "current" view in the app.
    Any past month shows that month's own completed snapshot boundary, not "now".
    """
    current_anchor = _current_anchor_ts()
    current_month_start = current_anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start >= current_month_start:
        return current_anchor, True
    return _anchor_ts(month_start), False


def _effective_as_of(db: Session, anchor_ts: datetime, current_user_id: int) -> Optional[datetime]:
    as_of = canonical_snapshot_coverage_as_of(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    return _normalize_ts(as_of)


def _normalize_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
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
    exact = as_of.date() == anchor_ts.date()
    return as_of, exact, ("exact" if exact else "synthetic")


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
    as_of = canonical_snapshot_coverage_as_of(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_cash=False,
    )
    return _normalize_ts(as_of)


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


def _canonical_base_currency(row: Dict[str, Any], fallback: str) -> str:
    return str(row.get("account_base_currency") or row.get("account_currency") or fallback).upper()


def _canonical_position_value(
    row: Dict[str, Any],
    rates: Dict[str, float],
    fallback_currency: str,
    latest_prices: Dict[int, Dict[str, Any]] | None = None,
) -> float:
    if latest_prices:
        asset_id = row.get("asset_id")
        quantity = row.get("quantity")
        price_row = latest_prices.get(int(asset_id)) if asset_id is not None else None
        if price_row and quantity is not None and price_row.get("price") is not None:
            price_currency = str(price_row.get("currency") or row.get("quote_currency") or fallback_currency).upper()
            return float(quantity or 0.0) * float(price_row["price"]) * rates.get(price_currency, 1.0)
    currency = _canonical_base_currency(row, fallback_currency)
    raw_value = row.get("snapshot_market_value_base")
    if raw_value is None:
        raw_value = row.get("cost_basis_base")
    return float(raw_value or 0.0) * rates.get(currency, 1.0)


def _latest_prices_for_positions(
    db: Session,
    anchor_ts: datetime,
    rows: list[Dict[str, Any]],
    *,
    enabled: bool,
) -> Dict[int, Dict[str, Any]]:
    if not enabled:
        return {}
    asset_ids = {int(row["asset_id"]) for row in rows if row.get("asset_id") is not None}
    return _latest_price_map(db, anchor_ts, asset_ids)


def _canonical_cash_value(row: Dict[str, Any], rates: Dict[str, float], fallback_currency: str) -> float:
    currency = _canonical_base_currency(row, fallback_currency)
    return float(row.get("balance_base") or 0.0) * rates.get(currency, 1.0)


def _card_liability_transaction_start(anchor_ts: datetime) -> datetime:
    month_start = anchor_ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if (
        anchor_ts.day == _configured_snapshot_day()
        and anchor_ts.hour == 0
        and anchor_ts.minute == 0
        and anchor_ts.second == 0
        and anchor_ts.microsecond == 0
    ):
        return _add_months(month_start, -1)
    return month_start


def _credit_card_liability_component(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> tuple[float, set[int]]:
    cards = db.execute(
        text(
            """
            SELECT
              a.id AS account_id,
              a.currency AS account_currency,
              COALESCE(cc.credit_limit, 0) AS credit_limit,
              cc.available_limit,
              cc.available_limit_as_of
            FROM accounts a
            LEFT JOIN credit_card_accounts cc ON cc.account_id = a.id
            WHERE a.account_type = 'CREDIT_CARD'
              AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    card_account_ids = {int(card["account_id"]) for card in cards}
    if not cards:
        return 0.0, set()

    transaction_start = _card_liability_transaction_start(anchor_ts)
    transaction_rows = db.execute(
        text(
            """
            SELECT t.account_id, t.amount, t.currency
            FROM transactions t
            JOIN accounts a ON a.id = t.account_id
            WHERE t.ts >= :start
              AND t.ts < :anchor
              AND a.account_type = 'CREDIT_CARD'
              AND t.type IN ('EXPENSE','FEE','TAX','INTEREST','TRANSFER','INCOME')
              AND """
            + account_scope_sql("a")
        ),
        {"start": transaction_start, "anchor": anchor_ts, "current_user_id": current_user_id},
    ).mappings().all()

    currencies = {
        str(card["account_currency"] or base_currency).upper()
        for card in cards
    }
    currencies.update(str(row["currency"] or base_currency).upper() for row in transaction_rows)
    rates = get_rates(anchor_ts, base_currency, currencies)

    transaction_outstanding: dict[int, float] = {}
    for row in transaction_rows:
        currency = str(row["currency"] or base_currency).upper()
        account_id = int(row["account_id"])
        transaction_outstanding[account_id] = (
            transaction_outstanding.get(account_id, 0.0)
            + (-float(row["amount"] or 0.0) * rates.get(currency, 1.0))
        )

    liability = 0.0
    for card in cards:
        account_id = int(card["account_id"])
        account_currency = str(card["account_currency"] or base_currency).upper()
        rate = rates.get(account_currency, 1.0)
        available_as_of = _normalize_ts(card["available_limit_as_of"])
        if (
            card["available_limit"] is not None
            and card["credit_limit"] is not None
            and available_as_of is not None
            and available_as_of <= anchor_ts
        ):
            outstanding = (
                float(card["credit_limit"] or 0.0)
                - float(card["available_limit"] or 0.0)
            ) * rate
        else:
            outstanding = transaction_outstanding.get(account_id, 0.0)
        liability += max(outstanding, 0.0)
    return liability, card_account_ids


_CASH_FRESHNESS_BALANCE_TYPES = {"cash", "broker_cash", "bank_cash", "stablecoin_cash"}


def _freshness_pair(items: list[tuple[str, Any]]) -> Dict[str, Any]:
    """Most-recent and stalest data point across a set of (label, date) pairs.

    Surfacing both instead of picking one aggregate means neither "your best
    account" nor "your worst account" is hidden from the freshness signal.
    """
    dated = [(label, _iso_value(value)) for label, value in items]
    dated = [(label, iso) for label, iso in dated if iso is not None]
    if not dated:
        return {
            "most_recent_at": None,
            "most_recent_label": None,
            "stalest_at": None,
            "stalest_label": None,
        }
    most_recent_label, most_recent_at = max(dated, key=lambda item: item[1])
    stalest_label, stalest_at = min(dated, key=lambda item: item[1])
    return {
        "most_recent_at": most_recent_at,
        "most_recent_label": most_recent_label,
        "stalest_at": stalest_at,
        "stalest_label": stalest_label,
    }


def _current_networth_state(db: Session, base_currency: str, current_user_id: int) -> Dict[str, Any]:
    anchor = _current_anchor_ts()
    components = _networth_components(db, anchor, base_currency, current_user_id, price_overlay=True)
    rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor.date(),
        include_nav_accounts=True,
    )
    asset_ids = {int(row["asset_id"]) for row in rows if row.get("asset_id") is not None}
    symbol_by_asset = {int(row["asset_id"]): row.get("symbol") for row in rows if row.get("asset_id") is not None}
    live_prices = _latest_price_map(db, anchor, asset_ids)
    stock_items = [
        (symbol_by_asset.get(asset_id) or "Unknown", info.get("trade_date"))
        for asset_id, info in live_prices.items()
    ]

    crypto_valuation = latest_wallet_valuation(db, current_user_id)
    crypto_items = [
        (
            wallet.get("label") or (wallet.get("address") or "")[:10] or wallet.get("chain") or "Wallet",
            wallet.get("as_of_date"),
        )
        for wallet in crypto_valuation.get("wallets", [])
        if wallet.get("as_of_date") is not None
    ]

    cash_rows = canonical_account_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor.date(),
    )
    cash_items = [
        (_display_source(row.get("platform")), row.get("as_of_date"))
        for row in cash_rows
        if str(row.get("balance_type") or "").lower() in _CASH_FRESHNESS_BALANCE_TYPES
    ]

    cash_percent = round((components["cash"] / components["total"]) * 100, 2) if components["total"] > 0 else 0.0
    return {
        "anchor": anchor,
        "net_worth": _serialize_net_worth(components),
        "cash_percent": cash_percent,
        "freshness": {
            "stocks": _freshness_pair(stock_items),
            "crypto": _freshness_pair(crypto_items),
            "cash": _freshness_pair(cash_items),
        },
    }


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


def _networth_components(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
    return_rows: bool = False,
) -> Dict[str, float] | tuple[Dict[str, float], Dict[str, Any]]:
    """Compute reporting net worth components from canonical snapshots only.

    When return_rows=True, also returns the raw canonical rows this call fetched
    (positions/nav/cash) so callers building a per-platform freshness breakdown
    (the wealth rollup) don't have to re-issue the same queries.
    """
    if anchor_ts is None:
        empty = {"cash": 0.0, "stocks_funds": 0.0, "crypto": 0.0, "liabilities": 0.0, "total": 0.0}
        if return_rows:
            return empty, {"positions": [], "nav": [], "cash": []}
        return empty
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    # Canonical position rows for non-NAV accounts (Sharekhan, DBS Vickers)
    canonical_pos_rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    canonical_cash_rows = canonical_account_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    latest_prices = _latest_prices_for_positions(db, anchor_ts, canonical_pos_rows, enabled=price_overlay)
    nav_account_ids = {
        int(row["legacy_account_id"])
        for row in canonical_nav_rows
        if row.get("legacy_account_id") is not None
    }
    currencies = {
        _canonical_base_currency(row, base_currency)
        for row in canonical_pos_rows
    }
    currencies.update(str(price["currency"]).upper() for price in latest_prices.values() if price.get("currency"))
    currencies.update(_canonical_base_currency(row, base_currency) for row in canonical_cash_rows)
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    currencies.add("USD")  # Include USD for crypto wallet conversions
    rates = get_rates(anchor_ts, base_currency, currencies)
    cash = 0.0
    stocks_funds = 0.0
    crypto = 0.0
    credit_card_liabilities, credit_card_account_ids = _credit_card_liability_component(
        db,
        anchor_ts,
        base_currency,
        current_user_id,
    )
    for r in canonical_pos_rows:
        asset_class = str(r["asset_class"] or "").upper()
        if asset_class in ("STOCK", "FUND"):
            stocks_funds += _canonical_position_value(r, rates, base_currency, latest_prices)
    for row in canonical_nav_rows:
        nav_currency = str(row["base_currency"] or base_currency).upper()
        rate = rates.get(nav_currency, 1.0)
        cash_base = float(row["cash_base"] or 0.0)
        total_nav_base = float(row["total_nav_base"] or 0.0)
        cash += cash_base * rate
        stocks_funds += (total_nav_base - cash_base) * rate
    for row in canonical_cash_rows:
        if row.get("account_id") is not None and int(row["account_id"]) in nav_account_ids:
            continue
        if row.get("account_id") is not None and int(row["account_id"]) in credit_card_account_ids:
            continue
        balance_type = str(row.get("balance_type") or "").lower()
        if balance_type not in {"cash", "broker_cash", "bank_cash", "credit_balance", "loan_balance", "stablecoin_cash"}:
            continue
        cash += _canonical_cash_value(row, rates, base_currency)
    if price_overlay:
        wallet_usd = float(latest_wallet_valuation(db, current_user_id)["total_usd"])
    else:
        wallet_usd = float(latest_wallet_valuation(db, current_user_id, as_of_date=anchor_ts.date())["total_usd"])
    if wallet_usd:
        usd_rate = rates.get("USD", 1.0)
        crypto += wallet_usd * usd_rate

    liabilities = credit_card_liabilities
    total = cash + stocks_funds + crypto - liabilities
    result = {
        "cash": cash,
        "stocks_funds": stocks_funds,
        "crypto": crypto,
        "liabilities": liabilities,
        "total": total,
    }
    if return_rows:
        return result, {
            "positions": canonical_pos_rows,
            "nav": canonical_nav_rows,
            "cash": canonical_cash_rows,
        }
    return result


# ─── Wealth Timeline rollups (Phase 2) ──────────────────────────────────────
#
# wealth_monthly_rollups pre-aggregates one net-worth snapshot per
# (user, month, base_currency) so the History page is a single indexed read
# instead of recomputing _networth_components per month on every request.
# Rows are written by _backfill_wealth_rollups, called from the timeline
# endpoints below — never computed inline by a GET.

_WEALTH_ROLLUP_CARRY_HORIZON_DAYS = 180
_DAILY_CADENCE_PLATFORMS = {"IBKR", "CRYPTO", "COINBASE"}
_DAILY_CADENCE_FRESH_DAYS = 3
_MANUAL_CADENCE_FRESH_DAYS = 31


def _platform_cadence_days(platform: str | None) -> int:
    return _DAILY_CADENCE_FRESH_DAYS if (platform or "").upper() in _DAILY_CADENCE_PLATFORMS else _MANUAL_CADENCE_FRESH_DAYS


def _freshness_bucket_and_days(
    as_of: date | None,
    anchor_date: date,
    cadence_days: int,
) -> tuple[str, Optional[int]]:
    """Bucket one source's staleness at a historical anchor: fresh/carried/missing.

    "stale" (a normally-daily source gone quiet) isn't distinguishable from
    "carried" with only a single as_of date, so daily and manual sources share
    this three-way bucket; the cadence threshold is what differs between them.
    """
    if as_of is None:
        return "missing", None
    days = (anchor_date - as_of).days
    if days < 0:
        return "missing", None
    if days <= cadence_days:
        return "fresh", days
    if days <= _WEALTH_ROLLUP_CARRY_HORIZON_DAYS:
        return "carried", days
    return "missing", days


def _platform_freshness_entries(
    rows: Dict[str, Any],
    anchor_date: date,
    crypto_as_of: Optional[date],
) -> list[dict[str, Any]]:
    nav_account_ids = {
        int(row["legacy_account_id"])
        for row in rows.get("nav", [])
        if row.get("legacy_account_id") is not None
    }
    latest_by_platform: Dict[str, date] = {}

    def _note(platform: Optional[str], value: Any) -> None:
        if value is None:
            return
        as_of = date.fromisoformat(value) if isinstance(value, str) else value
        key = platform or "UNKNOWN"
        if key not in latest_by_platform or as_of > latest_by_platform[key]:
            latest_by_platform[key] = as_of

    for row in rows.get("positions", []):
        _note(row.get("platform"), row.get("report_date"))
    for row in rows.get("nav", []):
        _note(row.get("platform"), row.get("report_date"))
    for row in rows.get("cash", []):
        if row.get("account_id") is not None and int(row["account_id"]) in nav_account_ids:
            continue
        _note(row.get("platform"), row.get("as_of_date"))

    entries: list[dict[str, Any]] = []
    for platform, as_of in latest_by_platform.items():
        status, days_old = _freshness_bucket_and_days(as_of, anchor_date, _platform_cadence_days(platform))
        entries.append({
            "platform": platform,
            "as_of": as_of.isoformat(),
            "days_old": days_old,
            "status": status,
        })
    if crypto_as_of is not None:
        status, days_old = _freshness_bucket_and_days(crypto_as_of, anchor_date, _DAILY_CADENCE_FRESH_DAYS)
        entries.append({
            "platform": "CRYPTO",
            "as_of": crypto_as_of.isoformat(),
            "days_old": days_old,
            "status": status,
        })
    entries.sort(key=lambda e: e["platform"])
    return entries


_FRESHNESS_STATUS_RANK = {"fresh": 0, "carried": 1, "stale": 2, "missing": 3}


def _worst_freshness_status(entries: list[dict[str, Any]]) -> str:
    if not entries:
        return "missing"
    return max((e["status"] for e in entries), key=lambda s: _FRESHNESS_STATUS_RANK.get(s, 3))


def _wealth_rollup_row(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> Dict[str, Any]:
    """Compute one month's rollup row. Snapshot-consistent values only
    (price_overlay=False) — the timeline never mixes live-priced "now" values
    into a historical point; "now" is rendered as a separate provisional marker."""
    components, rows = _networth_components(
        db, anchor_ts, base_currency, current_user_id, price_overlay=False, return_rows=True,
    )
    crypto_as_of = _crypto_snapshot_coverage_as_of(db, anchor_ts.date(), current_user_id)
    source_freshness = _platform_freshness_entries(rows, anchor_ts.date(), crypto_as_of)
    return {
        "anchor_date": anchor_ts.date(),
        "components": components,
        "source_freshness": source_freshness,
        "freshness_status": _worst_freshness_status(source_freshness),
    }


def _upsert_wealth_rollup(
    db: Session,
    current_user_id: int,
    month: str,
    base_currency: str,
    row: Dict[str, Any],
) -> None:
    components = row["components"]
    # SQLite (used by the test suite) has no JSONB type or NOW(); Postgres gets
    # the real cast, SQLite gets the plain bound string / a Python-side timestamp.
    is_postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
    json_cast = "CAST(:source_freshness AS JSONB)" if is_postgres else ":source_freshness"
    computed_at = datetime.now(tz=timezone.utc)
    db.execute(
        text(
            f"""
            INSERT INTO wealth_monthly_rollups
              (user_id, month, anchor_date, base_currency, total, cash, stocks_funds, crypto,
               liabilities, source_freshness, freshness_status, computed_at)
            VALUES
              (:user_id, :month, :anchor_date, :base_currency, :total, :cash, :stocks_funds, :crypto,
               :liabilities, {json_cast}, :freshness_status, :computed_at)
            ON CONFLICT (user_id, month, base_currency) DO UPDATE SET
              anchor_date = EXCLUDED.anchor_date,
              total = EXCLUDED.total,
              cash = EXCLUDED.cash,
              stocks_funds = EXCLUDED.stocks_funds,
              crypto = EXCLUDED.crypto,
              liabilities = EXCLUDED.liabilities,
              source_freshness = EXCLUDED.source_freshness,
              freshness_status = EXCLUDED.freshness_status,
              computed_at = EXCLUDED.computed_at
            """
        ),
        {
            "user_id": current_user_id,
            "month": month,
            "anchor_date": row["anchor_date"],
            "base_currency": base_currency,
            "total": components["total"],
            "cash": components["cash"],
            "stocks_funds": components["stocks_funds"],
            "crypto": components["crypto"],
            "liabilities": components["liabilities"],
            "source_freshness": json.dumps(row["source_freshness"]),
            "freshness_status": row["freshness_status"],
            "computed_at": computed_at,
        },
    )


def _backfill_wealth_rollups(
    db: Session,
    current_user_id: int,
    base_currency: str,
    months: int,
) -> int:
    current_month_start = _current_anchor_ts().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    written = 0
    for offset in range(-(months - 1), 1):
        month_start = _add_months(current_month_start, offset)
        anchor = _completed_snapshot_anchor_ts(month_start)
        row = _wealth_rollup_row(db, anchor, base_currency, current_user_id)
        _upsert_wealth_rollup(db, current_user_id, month_start.strftime("%Y-%m"), base_currency, row)
        written += 1
    db.commit()
    return written


def _timeline_upload_markers(
    db: Session,
    current_user_id: int,
    since_month_start: datetime,
) -> Dict[str, list[str]]:
    """Months where a manual statement import completed, for the timeline's
    upload-marker ticks. Keyed by 'YYYY-MM' -> list of platform codes."""
    rows = db.execute(
        text(
            """
            SELECT ij.platform, ij.created_at
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE ij.status = 'IMPORTED'
              AND ij.created_at >= :since
              AND """
            + account_scope_sql("a")
        ),
        {"since": since_month_start, "current_user_id": current_user_id},
    ).mappings().all()
    markers: Dict[str, set[str]] = {}
    for row in rows:
        created_at = _normalize_ts(row["created_at"])
        if created_at is None:
            continue
        month_key = created_at.strftime("%Y-%m")
        markers.setdefault(month_key, set()).add(str(row["platform"] or "").upper())
    return {month: sorted(platforms) for month, platforms in markers.items()}


def _geography(
    db: Session,
    anchor_ts: datetime,
    total: float,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> List[Dict[str, Any]]:
    if total <= 0:
        return []
    stock_payload = _stock_exposure(db, anchor_ts, base_currency, current_user_id, price_overlay=price_overlay)
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    canonical_cash_rows = canonical_account_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    nav_account_ids = {
        int(row["legacy_account_id"])
        for row in canonical_nav_rows
        if row.get("legacy_account_id") is not None
    }
    currencies = {_canonical_base_currency(row, base_currency) for row in canonical_cash_rows}
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[str, float] = {}
    for row in stock_payload["by_country"]:
        value = float(row.get("value") or 0.0)
        if value <= 0:
            continue
        country = row.get("key") or "UNKNOWN"
        buckets[country] = buckets.get(country, 0.0) + value
    for row in canonical_nav_rows:
        cash_base = float(row.get("cash_base") or 0.0)
        if cash_base <= 0:
            continue
        nav_currency = str(row.get("base_currency") or base_currency).upper()
        value = cash_base * rates.get(nav_currency, 1.0)
        country = row.get("country") or "UNKNOWN"
        buckets[country] = buckets.get(country, 0.0) + value
    for row in canonical_cash_rows:
        if row.get("account_id") is not None and int(row["account_id"]) in nav_account_ids:
            continue
        value = _canonical_cash_value(row, rates, base_currency)
        if value <= 0:
            continue
        country = row.get("platform_country") or "UNKNOWN"
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


def _geography_exposure(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> Dict[str, Any]:
    stock_payload = _stock_exposure(db, anchor_ts, base_currency, current_user_id, price_overlay=price_overlay)
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    canonical_cash_rows = canonical_account_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    nav_account_ids = {
        int(row["legacy_account_id"])
        for row in canonical_nav_rows
        if row.get("legacy_account_id") is not None
    }
    currencies = {_canonical_base_currency(row, base_currency) for row in canonical_cash_rows}
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    currencies.add("USD")
    rates = get_rates(anchor_ts, base_currency, currencies)
    usd_rate = rates.get("USD", 1.0)

    buckets: Dict[str, Dict[str, float]] = {}

    def _bucket(country: str) -> Dict[str, float]:
        if country not in buckets:
            buckets[country] = _blank_geo_country_bucket()
        return buckets[country]

    for row in stock_payload["by_country"]:
        value_base = float(row.get("value") or 0.0)
        if value_base <= 0:
            continue
        country = row.get("key") or "UNKNOWN"
        _bucket(country)["stocks_funds"] += value_base

    for row in canonical_nav_rows:
        cash_base = float(row.get("cash_base") or 0.0)
        if cash_base <= 0:
            continue
        nav_currency = str(row.get("base_currency") or base_currency).upper()
        value_base = cash_base * rates.get(nav_currency, 1.0)
        _bucket(row.get("country") or "UNKNOWN")["cash"] += value_base

    for row in canonical_cash_rows:
        if row.get("account_id") is not None and int(row["account_id"]) in nav_account_ids:
            continue
        value_base = _canonical_cash_value(row, rates, base_currency)
        if value_base <= 0:
            continue
        _bucket(row.get("platform_country") or "UNKNOWN")["cash"] += value_base

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
    *,
    price_overlay: bool = False,
) -> List[Dict[str, Any]]:
    if total <= 0:
        return []

    canonical_pos_rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_nav_accounts=True,
    )
    latest_prices = _latest_prices_for_positions(db, anchor_ts, canonical_pos_rows, enabled=price_overlay)
    crypto_rows = db.execute(
        text(
            """
            WITH latest_wallets AS (
              SELECT wallet_id, MAX(as_of_date) AS as_of_date
              FROM crypto_wallet_snapshots
              WHERE as_of_date <= :as_of_date
              GROUP BY wallet_id
            ),
            crypto_asset_fallback AS (
              SELECT
                LOWER(ca.symbol) AS symbol_key,
                ca.chain AS chain,
                MIN(ca.base_asset) AS base_asset
              FROM crypto_assets ca
              GROUP BY LOWER(ca.symbol), ca.chain
            )
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
            """
        ),
        {"as_of_date": anchor_ts.date(), "current_user_id": current_user_id},
    ).mappings().all()

    currencies = {_canonical_base_currency(row, base_currency) for row in canonical_pos_rows}
    currencies.update(str(price["currency"]).upper() for price in latest_prices.values() if price.get("currency"))
    currencies.add("USD")
    rates = get_rates(anchor_ts, base_currency, currencies)

    agg: Dict[tuple, Dict[str, Any]] = {}
    geo_bucket: Dict[tuple, Dict[str, float]] = {}
    platform_bucket: Dict[tuple, Dict[str, float]] = {}

    def _record(row: Dict[str, Any]) -> None:
        key = (row.get("asset_id"), row.get("symbol"), row.get("asset_class"))
        value = float(row.get("value") or 0.0)
        if value <= 0:
            return
        if key not in agg:
            agg[key] = {
                "asset_id": row.get("asset_id"),
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "asset_class": row.get("asset_class"),
                "value": 0.0,
                "quantity": 0.0,
                "avg_cost": None,
                "latest_price": row.get("latest_price"),
                "quote_currency": row.get("quote_currency"),
                "_avg_cost_numerator": 0.0,
                "_avg_cost_denominator": 0.0,
                "_has_quantity": False,
                "latest_trade_date": _iso_value(row.get("latest_trade_date")),
                "quote_age_days": _quote_age_days(row.get("latest_trade_date")),
                "price_source": row.get("price_source"),
                "price_provider": _price_provider(row.get("price_source")),
                "quote_freshness_status": _quote_freshness_status(row.get("latest_trade_date")),
                "exchange_code": row.get("exchange_code"),
            }
        if not agg[key].get("name") and row.get("name"):
            agg[key]["name"] = row.get("name")
        if not agg[key].get("exchange_code") and row.get("exchange_code"):
            agg[key]["exchange_code"] = row.get("exchange_code")
        agg[key]["value"] += value
        quantity = float(row.get("quantity")) if row.get("quantity") is not None else None
        if quantity is not None:
            agg[key]["quantity"] += quantity
            agg[key]["_has_quantity"] = True
            avg_cost = row.get("avg_cost")
            if avg_cost is not None and quantity > 0:
                agg[key]["_avg_cost_numerator"] += float(avg_cost) * quantity
                agg[key]["_avg_cost_denominator"] += quantity
        if agg[key]["latest_price"] is None and row.get("latest_price") is not None:
            agg[key]["latest_price"] = row.get("latest_price")
        geo = row.get("geo") or "UNKNOWN"
        platform = row.get("platform") or "UNKNOWN"
        geo_bucket.setdefault(key, {})[geo] = geo_bucket.setdefault(key, {}).get(geo, 0.0) + value
        platform_bucket.setdefault(key, {})[platform] = platform_bucket.setdefault(key, {}).get(platform, 0.0) + value

    for cr in canonical_pos_rows:
        asset_class = str(cr.get("asset_class") or "STOCK").upper()
        if asset_class not in {"STOCK", "FUND"}:
            continue
        quantity = float(cr.get("quantity") or 0.0)
        has_nav_snapshot = bool(cr.get("has_nav_snapshot"))
        avg_cost = cr.get("avg_cost")
        if has_nav_snapshot and cr.get("snapshot_cost_basis_local") is not None and quantity > 0:
            avg_cost = float(cr.get("snapshot_cost_basis_local") or 0.0) / quantity
        price_row = (
            latest_prices.get(int(cr["asset_id"]))
            if cr.get("asset_id") is not None and not has_nav_snapshot
            else None
        )
        value = _canonical_position_value(
            cr,
            rates,
            base_currency,
            None if has_nav_snapshot else latest_prices,
        )
        latest_price = float(cr.get("snapshot_market_price")) if cr.get("snapshot_market_price") is not None else None
        latest_trade_date = cr.get("report_date")
        price_source = "ibkr_flex" if has_nav_snapshot else "canonical_snapshot"
        quote_currency = str(cr.get("quote_currency")).upper() if cr.get("quote_currency") else None
        if price_row:
            latest_price = float(price_row["price"]) if price_row.get("price") is not None else latest_price
            latest_trade_date = price_row.get("trade_date") or latest_trade_date
            price_source = price_row.get("source") or price_source
            quote_currency = str(price_row.get("currency") or quote_currency).upper() if price_row.get("currency") or quote_currency else None
        _record({
            "asset_id": cr.get("asset_id"),
            "symbol": cr.get("symbol"),
            "name": cr.get("name"),
            "asset_class": asset_class,
            "value": value,
            "quantity": cr.get("quantity"),
            "avg_cost": avg_cost,
            "latest_price": latest_price,
            "quote_currency": quote_currency,
            "latest_trade_date": latest_trade_date,
            "price_source": price_source,
            "exchange_code": cr.get("exchange_code"),
            "geo": _infer_country(
                cr.get("symbol"),
                cr.get("home_country"),
                cr.get("platform"),
                cr.get("quote_currency"),
                cr.get("exchange_code"),
            ),
            "platform": cr.get("platform"),
        })

    usd_rate = rates.get("USD", 1.0)
    for row in crypto_rows:
        value = float(row.get("value") or 0.0) * usd_rate
        _record({
            "asset_id": None,
            "symbol": row.get("symbol"),
            "name": row.get("symbol"),
            "asset_class": "CRYPTO",
            "value": value,
            "quantity": None,
            "avg_cost": None,
            "latest_price": None,
            "quote_currency": "USD",
            "latest_trade_date": None,
            "price_source": None,
            "exchange_code": None,
            "geo": "US",
            "platform": "CRYPTO",
        })

    out = sorted(agg.values(), key=lambda x: x["value"], reverse=True)[:limit]
    for row in out:
        value = float(row["value"])
        den = float(row.pop("_avg_cost_denominator"))
        num = float(row.pop("_avg_cost_numerator"))
        has_quantity = bool(row.pop("_has_quantity"))
        row["quantity"] = row["quantity"] if has_quantity else None
        row["avg_cost"] = (num / den) if den > 0 else None
        row["percent_of_networth"] = round((value / total) * 100, 2)
        row["quote_age_days"] = int(row["quote_age_days"]) if row.get("quote_age_days") is not None else None
        key = (row["asset_id"], row["symbol"], row["asset_class"])
        geo = geo_bucket.get(key, {})
        platform = platform_bucket.get(key, {})
        row["geo"] = max(geo.items(), key=lambda x: x[1])[0] if geo else "UNKNOWN"
        row["platform"] = max(platform.items(), key=lambda x: x[1])[0] if platform else "UNKNOWN"
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


def _stock_trend(
    db: Session,
    month_start: datetime,
    base_currency: str,
    current_user_id: int,
    months: int = 6,
) -> list[dict[str, Any]]:
    trend_start = _add_months(month_start, -(months - 1))
    points: list[dict[str, Any]] = []
    for offset in range(months):
        point_month = _add_months(trend_start, offset)
        anchor = _completed_snapshot_anchor_ts(point_month)
        exposure = _stock_exposure(db, anchor, base_currency, current_user_id)
        total = float(exposure.get("total") or 0.0)
        points.append({
            "month": point_month.strftime("%Y-%m"),
            "value": total if total > 0 else None,
        })
    return points


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
    rows = canonical_account_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    if not rows:
        return []
    currencies = {_canonical_base_currency(row, base_currency) for row in rows}
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[str, float] = {}
    for row in rows:
        balance_type = str(row.get("balance_type") or "").lower()
        if balance_type not in {"cash", "broker_cash", "bank_cash", "credit_balance", "loan_balance", "stablecoin_cash"}:
            continue
        currency = str(row.get("currency") or base_currency).upper()
        value = _canonical_cash_value(row, rates, base_currency)
        buckets[currency] = buckets.get(currency, 0.0) + value
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

    cash_rows = canonical_account_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    cash_currencies = {_canonical_base_currency(row, base_currency) for row in cash_rows}
    cash_rates = get_rates(anchor_ts, base_currency, cash_currencies) if cash_currencies else {}
    for row in cash_rows:
        balance_type = str(row.get("balance_type") or "").lower()
        if balance_type not in {"cash", "broker_cash", "bank_cash", "credit_balance", "loan_balance", "stablecoin_cash"}:
            continue
        source = _display_source(row.get("platform"))
        value = _canonical_cash_value(row, cash_rates, base_currency)
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


def _platform_allocation(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> dict:
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    canonical_pos_rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    latest_prices = _latest_prices_for_positions(db, anchor_ts, canonical_pos_rows, enabled=price_overlay)
    canonical_cash_rows = canonical_account_balance_rows(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    nav_account_ids = {
        int(row["legacy_account_id"])
        for row in canonical_nav_rows
        if row.get("legacy_account_id") is not None
    }
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
    currencies = {_canonical_base_currency(row, base_currency) for row in canonical_pos_rows}
    currencies.update(str(price["currency"]).upper() for price in latest_prices.values() if price.get("currency"))
    currencies.update(_canonical_base_currency(row, base_currency) for row in canonical_cash_rows)
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    if wallet_usd:
        currencies.add("USD")
    rates = get_rates(anchor_ts, base_currency, currencies)
    buckets: Dict[tuple, float] = {}

    for row in canonical_pos_rows:
        asset_class = str(row.get("asset_class") or "").upper()
        if asset_class not in {"STOCK", "FUND"}:
            continue
        value = _canonical_position_value(row, rates, base_currency, latest_prices)
        key = (row.get("platform") or "UNKNOWN", row.get("platform_type"), row.get("platform_country"))
        buckets[key] = buckets.get(key, 0.0) + value
    for row in canonical_nav_rows:
        nav_currency = str(row.get("base_currency") or base_currency).upper()
        value = float(row.get("total_nav_base") or 0.0) * rates.get(nav_currency, 1.0)
        key = (row.get("platform") or "UNKNOWN", row.get("platform_type"), row.get("country"))
        buckets[key] = buckets.get(key, 0.0) + value
    for row in canonical_cash_rows:
        if row.get("account_id") is not None and int(row["account_id"]) in nav_account_ids:
            continue
        value = _canonical_cash_value(row, rates, base_currency)
        key = (row.get("platform") or "UNKNOWN", row.get("platform_type"), row.get("platform_country"))
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

def _stock_exposure(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> dict:
    canonical_nav_rows = latest_authoritative_nav_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
    )
    canonical_pos_rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_nav_accounts=True,
    )
    if not canonical_nav_rows and not canonical_pos_rows:
        return {"as_of": None, "base_currency": base_currency, "total": 0.0, "by_country": [], "by_platform": []}
    latest_prices = _latest_prices_for_positions(db, anchor_ts, canonical_pos_rows, enabled=price_overlay)
    currencies = {_canonical_base_currency(row, base_currency) for row in canonical_pos_rows}
    currencies.update(str(price["currency"]).upper() for price in latest_prices.values() if price.get("currency"))
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    rates = get_rates(anchor_ts, base_currency, currencies)

    by_country: Dict[str, float] = {}
    by_platform: Dict[str, float] = {}
    total = 0.0
    nav_position_rows_by_account: Dict[int, list[dict[str, Any]]] = {}
    for row in canonical_pos_rows:
        if not row.get("has_nav_snapshot"):
            continue
        account_id = row.get("account_id")
        if account_id is None:
            continue
        nav_position_rows_by_account.setdefault(int(account_id), []).append(row)

    for row in canonical_nav_rows:
        nav_currency = str(row.get("base_currency") or base_currency).upper()
        raw_stock_value = float(row.get("total_nav_base") or 0.0) - float(row.get("cash_base") or 0.0)
        value = raw_stock_value * rates.get(nav_currency, 1.0)
        if value <= 0:
            continue
        platform = row.get("platform") or "UNKNOWN"
        total += value
        by_platform[platform] = by_platform.get(platform, 0.0) + value

        detail_buckets: Dict[str, float] = {}
        detail_total = 0.0
        for detail in nav_position_rows_by_account.get(int(row["legacy_account_id"]), []):
            asset_class = str(detail.get("asset_class") or "STOCK").upper()
            if asset_class not in {"STOCK", "FUND"}:
                continue
            detail_value = _canonical_position_value(detail, rates, base_currency)
            if detail_value <= 0:
                continue
            country = _infer_country(
                detail.get("symbol"),
                detail.get("home_country"),
                platform,
                detail.get("quote_currency"),
                detail.get("exchange_code"),
            )
            detail_buckets[country] = detail_buckets.get(country, 0.0) + detail_value
            detail_total += detail_value
        if detail_total > 0:
            scale = value / detail_total
            for country, detail_value in detail_buckets.items():
                by_country[country] = by_country.get(country, 0.0) + (detail_value * scale)
        else:
            country = row.get("country") or "UNKNOWN"
            by_country[country] = by_country.get(country, 0.0) + value

    for row in canonical_pos_rows:
        if row.get("has_nav_snapshot"):
            continue
        asset_class = str(row.get("asset_class") or "STOCK").upper()
        if asset_class not in {"STOCK", "FUND"}:
            continue
        value = _canonical_position_value(row, rates, base_currency, latest_prices)
        if value <= 0:
            continue
        platform = row.get("platform") or "UNKNOWN"
        country = _infer_country(
            row.get("symbol"), row.get("home_country"), platform, row.get("quote_currency"), row.get("exchange_code")
        )
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
    current_stock_data = _stock_exposure(
        db,
        current_state["anchor"],
        base_currency,
        current_user.id,
        price_overlay=True,
    )
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


@router.post("/net-worth-timeline/backfill", response_model=WealthTimelineBackfillResponse)
def net_worth_timeline_backfill(
    months: int = Query(36, ge=1, le=120, description="How many trailing months to (re)compute"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """(Re)compute and upsert wealth_monthly_rollups for the trailing N months.

    Idempotent — safe to call repeatedly (e.g. after a new statement upload,
    or from a "Refresh history" action) since every row is an upsert keyed on
    (user, month, base_currency).
    """
    written = _backfill_wealth_rollups(db, current_user.id, base_currency, months)
    return {"months_written": written, "base_currency": base_currency}


@router.get("/net-worth-timeline", response_model=WealthTimelineResponse)
def net_worth_timeline(
    months: int = Query(24, ge=1, le=120),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Read-mostly: serves wealth_monthly_rollups directly (one indexed scan).

    Only the current, still-open month is opportunistically refreshed inline
    when stale — every earlier month is a pure read, so this endpoint never
    pays for a full historical recompute (see _backfill_wealth_rollups for
    that path, called explicitly by the frontend or an upload hook).
    """
    current_month_start = _current_anchor_ts().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    range_start = _add_months(current_month_start, -(months - 1))
    current_month_key = current_month_start.strftime("%Y-%m")

    existing_current = db.execute(
        text(
            "SELECT computed_at FROM wealth_monthly_rollups "
            "WHERE user_id = :user_id AND month = :month AND base_currency = :base_currency"
        ),
        {"user_id": current_user.id, "month": current_month_key, "base_currency": base_currency},
    ).mappings().first()
    computed_at = _normalize_ts(existing_current["computed_at"]) if existing_current else None
    needs_refresh = computed_at is None or (datetime.now(tz=timezone.utc) - computed_at) > timedelta(hours=6)
    if needs_refresh:
        anchor = _completed_snapshot_anchor_ts(current_month_start)
        row = _wealth_rollup_row(db, anchor, base_currency, current_user.id)
        _upsert_wealth_rollup(db, current_user.id, current_month_key, base_currency, row)
        db.commit()

    rollup_rows = db.execute(
        text(
            """
            SELECT month, anchor_date, total, cash, stocks_funds, crypto, liabilities,
                   source_freshness, freshness_status, computed_at
            FROM wealth_monthly_rollups
            WHERE user_id = :user_id AND base_currency = :base_currency AND month >= :from_month
            ORDER BY month ASC
            """
        ),
        {
            "user_id": current_user.id,
            "base_currency": base_currency,
            "from_month": range_start.strftime("%Y-%m"),
        },
    ).mappings().all()

    upload_markers = _timeline_upload_markers(db, current_user.id, range_start)

    points = []
    for row in rollup_rows:
        source_freshness = row["source_freshness"]
        if isinstance(source_freshness, str):
            source_freshness = json.loads(source_freshness)
        anchor_date = row["anchor_date"]
        points.append({
            "month": row["month"],
            "anchor_date": anchor_date if isinstance(anchor_date, str) else anchor_date.isoformat(),
            "total": float(row["total"]),
            "cash": float(row["cash"]),
            "stocks_funds": float(row["stocks_funds"]),
            "crypto": float(row["crypto"]),
            "liabilities": float(row["liabilities"]),
            "source_freshness": source_freshness,
            "freshness_status": row["freshness_status"],
            "computed_at": _iso_value(row["computed_at"]),
            "uploads": upload_markers.get(row["month"], []),
        })

    current_state = _current_networth_state(db, base_currency, current_user.id)

    return {
        "base_currency": base_currency,
        "points": points,
        "now": {
            **current_state["net_worth"],
            "as_of": current_state["anchor"].isoformat(),
        },
    }


@router.get("/net-worth-timeline/{month}/movers", response_model=TopMovers)
def net_worth_timeline_movers(
    month: str,
    base_currency: str = Query("SGD"),
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Top movers within holdings for one rollup month vs. the prior month —
    the drill-down's "what specifically moved" answer. Reuses the same
    holdings-diff logic /summary already uses for the current month, just
    parameterized by an arbitrary historical month; on-demand only (not
    stored), so it stays out of the timeline read path's hot loop.
    """
    month_start = _parse_month(month)
    anchor = _completed_snapshot_anchor_ts(month_start)
    prev_month_start = _add_months(month_start, -1)
    prev_anchor = _completed_snapshot_anchor_ts(prev_month_start)

    nw = _networth_components(db, anchor, base_currency, current_user.id)
    prev_nw = _networth_components(db, prev_anchor, base_currency, current_user.id)
    current_holdings = _top_holdings(db, anchor, nw["total"], base_currency, current_user.id, limit=250)
    prior_holdings = _top_holdings(db, prev_anchor, prev_nw["total"], base_currency, current_user.id, limit=250)
    return _top_movers_from_holdings(
        current_holdings, prior_holdings, prev_month_start.strftime("%Y-%m"), limit=limit
    )


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
        current_anchor = _current_anchor_ts()
        current_nw = _networth_components(db, current_anchor, base_currency, current_user.id, price_overlay=True)
        geo = _geography(
            db,
            current_anchor,
            current_nw["total"],
            base_currency,
            current_user.id,
            price_overlay=True,
        )
        top = _top_holdings(
            db,
            current_anchor,
            current_nw["total"],
            base_currency,
            current_user.id,
            limit=top_holdings_limit,
            price_overlay=True,
        )
        cash_balances = _cash_balances(db, current_anchor, base_currency, current_user.id)
        cf = _cashflow(db, month_start, month_end, base_currency, current_user.id)
        cash_percent = round((current_nw["cash"] / current_nw["total"]) * 100, 2) if current_nw["total"] > 0 else 0.0
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
    current_anchor = current_state["anchor"]
    current_nw = current_state["net_worth"]
    reporting_as_of = anchor if freshness_status in {"exact", "synthetic"} else as_of

    nw = _networth_components(db, anchor, base_currency, current_user.id)
    geo = _geography(
        db,
        current_anchor,
        current_nw["total"],
        base_currency,
        current_user.id,
        price_overlay=True,
    )
    top = _top_holdings(
        db,
        current_anchor,
        current_nw["total"],
        base_currency,
        current_user.id,
        limit=top_holdings_limit,
        price_overlay=True,
    )
    cash_balances = _cash_balances(db, current_anchor, base_currency, current_user.id)
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
        snapshot_top = _top_holdings(
            db,
            anchor,
            nw["total"],
            base_currency,
            current_user.id,
            limit=max(top_holdings_limit, 250),
        )
        prev_components = _networth_components(db, prev_anchor, base_currency, current_user.id)
        prev_top = _top_holdings(
            db,
            prev_anchor,
            prev_components["total"],
            base_currency,
            current_user.id,
            limit=max(top_holdings_limit, 250),
        )
        top_movers = _top_movers_from_holdings(snapshot_top, prev_top, prev_month_start.strftime("%Y-%m"))

    # Compute cash_percent
    cash_percent = round((nw["cash"] / nw["total"]) * 100, 2) if nw["total"] > 0 else 0.0

    # Data completeness indicators from canonical portfolio sources
    completeness_indicators = get_data_completeness_status(
        db, current_user_id=current_user.id, anchor_date=anchor.date()
    )

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
        "data_completeness_indicators": completeness_indicators if completeness_indicators else None,
    }


@router.get("/stock-holdings", response_model=StockHoldingsResponse)
def stock_holdings_summary(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    # "browse holdings as of {month}" — effective_anchor/is_live decide whether this
    # is live "now" data (current/future month) or a completed historical boundary.
    # stock_current_total/top_holdings/geography_breakdown/platform_breakdown are all
    # anchored to that same point; stock_snapshot_total is the PRIOR month, for a
    # stable "vs last month" comparison (not "vs whatever month happens to be picked").
    month_start = _parse_month(month)
    effective_anchor, is_live = _effective_anchor_for_month(month_start)
    compare_anchor = _anchor_ts(_add_months(month_start, -1))
    snapshot_day = _configured_snapshot_day()
    top_holdings_limit = _summary_top_holdings_limit()
    as_of = _effective_as_of(db, effective_anchor, current_user.id)
    holdings_as_of = _positions_coverage_as_of(db, effective_anchor, current_user.id)
    reporting_as_of = effective_anchor if as_of is not None else None
    boundary_exact = as_of.date() == effective_anchor.date() if as_of is not None else False
    freshness_status = "exact" if boundary_exact else ("synthetic" if as_of is not None else "missing")
    nw = _networth_components(db, effective_anchor, base_currency, current_user.id, price_overlay=is_live)
    top = [
        row
        for row in _top_holdings(
            db,
            effective_anchor,
            nw["total"],
            base_currency,
            current_user.id,
            limit=top_holdings_limit,
            price_overlay=is_live,
        )
        if str(row.get("asset_class") or "").upper() in {"STOCK", "FUND"}
    ]
    stock_exposure = _stock_exposure(
        db,
        effective_anchor,
        base_currency,
        current_user.id,
        price_overlay=is_live,
    )
    compare_stock_exposure = _stock_exposure(db, compare_anchor, base_currency, current_user.id)
    geography_breakdown = _stock_geography_breakdown(stock_exposure, compare_stock_exposure)
    platform_breakdown = _stock_platform_breakdown(stock_exposure, compare_stock_exposure)
    quote_freshness_summary = _quote_freshness_summary(top)
    trend = [MiniTrendPoint(**point) for point in _stock_trend(db, month_start, base_currency, current_user.id)]

    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": snapshot_day,
        "is_live": is_live,
        "compare_month": _add_months(month_start, -1).strftime("%Y-%m"),
        "current_holdings_as_of": holdings_as_of.isoformat() if holdings_as_of else None,
        "net_worth_as_of": reporting_as_of.isoformat() if reporting_as_of else None,
        "net_worth_snapshot_as_of": _iso_value(_effective_as_of(db, compare_anchor, current_user.id)),
        "net_worth_boundary_at": effective_anchor.isoformat(),
        "net_worth_boundary_exact": boundary_exact,
        "net_worth_freshness_status": freshness_status,
        "top_holdings": top,
        "geography_breakdown": geography_breakdown,
        "platform_breakdown": platform_breakdown,
        "stock_current_total": stock_exposure["total"],
        "stock_snapshot_total": compare_stock_exposure["total"],
        "quote_freshness_summary": quote_freshness_summary,
        "trend": trend,
    }


@router.get("/platform-allocation", response_model=PlatformAllocationOut)
def platform_allocation(
    month: str = Query(..., description="YYYY-MM"),
    base_currency: str = Query("SGD"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    _parse_month(month)
    anchor = _current_anchor_ts()
    as_of = _effective_as_of(db, anchor, current_user.id)
    payload = _platform_allocation(db, anchor, base_currency, current_user.id, price_overlay=True)
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
    # "browse cash as of {month}" — effective_anchor/is_live decide whether this is
    # live "now" data (current/future month) or a completed historical boundary.
    # The "Where cash sits" breakdown (payload/items) and current_total both follow
    # that same point; snapshot_total is the PRIOR month, for a stable "vs last
    # month" comparison (not "vs whatever month happens to be picked").
    month_start = _parse_month(month)
    effective_anchor, is_live = _effective_anchor_for_month(month_start)
    compare_anchor = _anchor_ts(_add_months(month_start, -1))
    payload = _cash_deposits(db, effective_anchor, base_currency, current_user.id)
    snapshot_balances = _cash_balances(db, compare_anchor, base_currency, current_user.id) + _stablecoin_cash_balances(
        db, compare_anchor, base_currency, current_user.id
    )
    current_balances = _cash_balances(db, effective_anchor, base_currency, current_user.id) + _stablecoin_cash_balances(
        db, effective_anchor, base_currency, current_user.id
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
        is_live=is_live,
        compare_month=_add_months(month_start, -1).strftime("%Y-%m"),
        current_cash_as_of=_iso_value(_effective_as_of(db, effective_anchor, current_user.id)),
        snapshot_cash_as_of=_iso_value(_effective_as_of(db, compare_anchor, current_user.id)),
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
    _parse_month(month)
    anchor = _current_anchor_ts()
    as_of = _positions_coverage_as_of(db, anchor, current_user.id)
    payload = _stock_exposure(db, anchor, base_currency, current_user.id, price_overlay=True)
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
    _parse_month(month)
    anchor = _current_anchor_ts()
    as_of = _effective_as_of(db, anchor, current_user.id)
    payload = _geography_exposure(db, anchor, base_currency, current_user.id, price_overlay=True)
    return GeographyExposureOut(
        as_of=as_of.isoformat() if as_of else None,
        base_currency=base_currency,
        total=payload["total"],
        items=[GeographyExposureItem(**item) for item in payload["items"]],
    )


def _wallet_scope_sql_for_summary(alias: str = "w") -> str:
    if allow_legacy_null_ownership():
        return f"({alias}.user_id = :current_user_id OR {alias}.user_id IS NULL)"
    return f"{alias}.user_id = :current_user_id"


def _relative_time_label(occurred_at: datetime) -> str:
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - occurred_at
    seconds = max(0, delta.total_seconds())
    if seconds < 3600:
        minutes = max(1, int(seconds // 60))
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


@router.get("/data-hub-summary", response_model=DataHubSummaryResponse)
def data_hub_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    account_rows = db.execute(
        text(
            """
            SELECT a.platform_id, a.currency
            FROM accounts a
            WHERE """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    linked_accounts = len(account_rows)
    platform_count = len({row[0] for row in account_rows if row[0] is not None})
    currency_count = len({row[1] for row in account_rows if row[1] is not None})

    pending_count_row = db.execute(
        text(
            """
            SELECT COUNT(*)
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE ij.status NOT IN ('IMPORTED', 'FAILED')
              AND """
            + account_scope_sql("a")
        ),
        {"current_user_id": current_user.id},
    ).fetchone()
    pending_count = int(pending_count_row[0]) if pending_count_row else 0

    last_import_row = db.execute(
        text(
            """
            SELECT ij.platform, ij.created_at
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE """
            + account_scope_sql("a")
            + """
            ORDER BY ij.created_at DESC
            LIMIT 1
            """
        ),
        {"current_user_id": current_user.id},
    ).fetchone()

    market_data_statuses = latest_status_by_exchange(db)
    fresh_total = sum(int(ex.get("diagnostics_summary", {}).get("fresh", 0)) for ex in market_data_statuses)
    stale_total = sum(int(ex.get("diagnostics_summary", {}).get("stale", 0)) for ex in market_data_statuses)

    wallet_rows = db.execute(
        text(
            "SELECT label, chain FROM crypto_wallets w WHERE w.status = 'active' AND "
            + _wallet_scope_sql_for_summary("w")
            + " ORDER BY w.verified_at DESC"
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    connected_wallet_labels = [row[0] or row[1] for row in wallet_rows]

    activity_rows: list[dict[str, Any]] = []
    import_activity = db.execute(
        text(
            """
            SELECT ij.platform, ij.original_filename, ij.created_at
            FROM import_jobs ij
            JOIN accounts a ON a.id = ij.account_id
            WHERE """
            + account_scope_sql("a")
            + """
            ORDER BY ij.created_at DESC
            LIMIT 5
            """
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    for platform, filename, created_at in import_activity:
        if created_at is None:
            continue
        activity_rows.append(
            {
                "kind": "import",
                "title": f"Imported {platform} statement",
                "meta": filename or "",
                "occurred_at": created_at,
            }
        )

    market_activity = db.execute(
        text(
            """
            SELECT exchange_code, provider, finished_at, upserted_rows
            FROM market_data_runs
            WHERE finished_at IS NOT NULL
            ORDER BY finished_at DESC
            LIMIT 5
            """
        )
    ).fetchall()
    for exchange_code, provider, finished_at, upserted_rows in market_activity:
        if finished_at is None:
            continue
        activity_rows.append(
            {
                "kind": "market_data",
                "title": f"Refreshed {exchange_code} market data",
                "meta": f"{upserted_rows or 0} quotes upserted · {provider}",
                "occurred_at": finished_at,
            }
        )

    platform_activity = db.execute(
        text(
            """
            SELECT name, platform_type, country, created_at
            FROM platforms
            WHERE created_at IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 5
            """
        )
    ).fetchall()
    for name, platform_type, country, created_at in platform_activity:
        if created_at is None:
            continue
        activity_rows.append(
            {
                "kind": "platform",
                "title": f"Added platform {name}",
                "meta": f"{platform_type.replace('_', ' ').title()} · {country}",
                "occurred_at": created_at,
            }
        )

    wallet_activity = db.execute(
        text(
            "SELECT label, chain, verified_at FROM crypto_wallets w WHERE w.status = 'active' AND verified_at IS NOT NULL AND "
            + _wallet_scope_sql_for_summary("w")
            + " ORDER BY w.verified_at DESC LIMIT 5"
        ),
        {"current_user_id": current_user.id},
    ).fetchall()
    for label, chain, verified_at in wallet_activity:
        if verified_at is None:
            continue
        activity_rows.append(
            {
                "kind": "wallet",
                "title": f"Connected {label or chain} wallet",
                "meta": chain,
                "occurred_at": verified_at,
            }
        )

    def _as_dt(value: Any) -> datetime:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    activity_rows.sort(key=lambda row: _as_dt(row["occurred_at"]), reverse=True)

    return DataHubSummaryResponse(
        linked_accounts=linked_accounts,
        platform_count=platform_count,
        currency_count=currency_count,
        import_health=DataHubImportHealth(
            pending_count=pending_count,
            last_import_platform=last_import_row[0] if last_import_row else None,
            last_import_at=_as_dt(last_import_row[1]).isoformat() if last_import_row and last_import_row[1] else None,
        ),
        market_data=DataHubMarketData(fresh=fresh_total, stale=stale_total),
        connected_wallet_count=len(connected_wallet_labels),
        connected_wallet_labels=connected_wallet_labels,
        recent_activity=[
            DataHubActivityItem(
                kind=row["kind"],
                title=row["title"],
                meta=row["meta"],
                occurred_at=_relative_time_label(_as_dt(row["occurred_at"])),
            )
            for row in activity_rows[:10]
        ],
    )
