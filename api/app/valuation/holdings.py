"""Holdings: the top holdings, movers between two anchors, and stock exposure
by country and platform."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, cast

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.portfolio.canonical_reads import canonical_position_rows_by_legacy_account, latest_authoritative_nav_by_legacy_account
from app.portfolio.position_pricing import price_position
from app.valuation import fx, prices
from app.valuation.clock import _add_months, _completed_snapshot_anchor_ts, _iso_value
from app.valuation.prices import (
    _canonical_base_currency,
    _canonical_position_value,
    _latest_prices_for_positions,
    _nav_live_price_deltas,
    _nav_row_live_price,
    _price_provider,
    _quote_freshness_status,
)
from app.valuation_cache import valuation_cached


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


@valuation_cached(shared=True, date_args=("anchor_ts",))
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
    rates = fx.get_rates(anchor_ts, base_currency, currencies)

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
                "quote_age_days": prices._quote_age_days(row.get("latest_trade_date")),
                "price_source": row.get("price_source"),
                "price_fallback_reason": row.get("price_fallback_reason"),
                "valued_at_cost": bool(row.get("valued_at_cost")),
                "price_provider": _price_provider(row.get("price_source")),
                "quote_freshness_status": _quote_freshness_status(row.get("latest_trade_date")),
                "price_basis": row.get("price_basis"),
                "exchange_code": row.get("exchange_code"),
            }
        if not agg[key].get("name") and row.get("name"):
            agg[key]["name"] = row.get("name")
        if not agg[key].get("exchange_code") and row.get("exchange_code"):
            agg[key]["exchange_code"] = row.get("exchange_code")
        agg[key]["value"] += value
        agg[key]["valued_at_cost"] = agg[key]["valued_at_cost"] or bool(row.get("valued_at_cost"))
        raw_quantity = row.get("quantity")
        quantity = float(raw_quantity) if raw_quantity is not None else None
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
        # Live view: the price job's quote when it's at least as recent as the
        # holding's statement (and within 2x of it); otherwise the statement
        # price, with the reason (D-21, #124; every holding since #144).
        priced = price_position(cr, latest_prices if price_overlay else None, rates, base_currency)
        price_row, price_fallback_reason, value = priced.quote, priced.fallback_reason, priced.value
        snapshot_price = cr.get("snapshot_market_price")
        latest_price = float(snapshot_price) if snapshot_price is not None else None
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
            "price_fallback_reason": price_fallback_reason,
            "valued_at_cost": priced.valued_at_cost,
            "price_basis": "quote" if price_row else "statement",
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

    usd_rate = rates.get("USD", 0.0)
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
        either = cast(Dict[str, Any], current or prior)  # the key came from one of the two
        symbol = either["symbol"]
        asset_class = either["asset_class"]
        asset_id = either.get("asset_id")
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


def _quote_freshness_summary(top_holdings: list[dict[str, Any]], *, is_live: bool = True) -> dict[str, Any]:
    summary: dict[str, Any] = {"fresh": 0, "stale": 0, "missing": 0}
    no_live_price = 0
    for holding in top_holdings:
        status = str(holding.get("quote_freshness_status") or "missing").lower()
        if status not in summary:
            status = "missing"
        summary[status] += 1
        # No live price (#224): no fresh quote from the price job, including a
        # holding priced only from its statement or an upload (#222).
        if holding.get("price_basis") != "quote" or status != "fresh":
            no_live_price += 1
    # Only a live view has "live" prices; a past month is valued at its statements.
    summary["no_live_price"] = no_live_price if is_live else None
    return summary


@valuation_cached(shared=True, date_args=("anchor_ts",))
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
    rates = fx.get_rates(anchor_ts, base_currency, currencies)
    nav_deltas = _nav_live_price_deltas(canonical_pos_rows, latest_prices, rates, base_currency)

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
        value = raw_stock_value * rates.get(nav_currency, 0.0) + nav_deltas.get(int(row["legacy_account_id"]), 0.0)
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
            if latest_prices:
                _quote, _reason, detail_value, _snapshot = _nav_row_live_price(detail, latest_prices, rates, base_currency)
            else:
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


