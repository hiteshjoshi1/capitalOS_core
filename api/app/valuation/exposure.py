"""Exposure: platform allocation and geography of gross assets (#144: both
split the same cash, stocks/funds and crypto net worth adds up), and net worth
by currency (#253)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.portfolio.canonical_reads import canonical_position_rows_by_legacy_account, latest_authoritative_nav_by_legacy_account
from app.valuation import fx
from app.valuation.facts import _credit_card_liability_details
from app.valuation.holdings import _stock_exposure
from app.valuation.prices import (
    _canonical_base_currency,
    _canonical_position_value,
    _latest_prices_for_positions,
    _nav_live_context,
    _nav_live_price_deltas,
)
from app.valuation.state import CASH_KIND_BALANCE, _cash_positions, _wallet_valuation
from app.valuation_cache import valuation_cached

# USD stablecoins: cash in US dollars wherever exposure is split (geography: US
# cash; currency exposure: USD). The list /crypto/stablecoins names (D-57).
_STABLECOIN_SYMBOLS = {"USDC", "USDT"}
# The currency exposure bucket for crypto other than stablecoins: not a currency.
CRYPTO_EXPOSURE_KEY = "CRYPTO"


@valuation_cached(shared=True, date_args=("anchor_ts",))
def _geography(
    db: Session,
    anchor_ts: datetime,
    total: float,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> List[Dict[str, Any]]:
    """The summary's geography: per country, its share of gross assets (cash,
    stocks/funds and crypto). The same split as _geography_exposure at the same
    anchor, so the values add up to net worth + liabilities and the percents to
    100 (#144: crypto was missing and the shares were of net worth). ``total``
    (net worth) only says whether there is anything to split."""
    if total <= 0:
        return []
    exposure = _geography_exposure(db, anchor_ts, base_currency, current_user_id, price_overlay=price_overlay)
    return [
        {"country": item["country"], "value": item["total"], "percent": item["percent"]}
        for item in exposure["items"]
    ]

def _blank_geo_country_bucket() -> Dict[str, float]:
    return {"stocks_funds": 0.0, "cash": 0.0, "crypto": 0.0}


@valuation_cached(shared=True, date_args=("anchor_ts",))
def _geography_exposure(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> Dict[str, Any]:
    """Gross assets at ``anchor_ts`` by country: stocks/funds (_stock_exposure),
    cash (_cash_positions, net-worth scope) and crypto (the wallet valuation net
    worth uses; stablecoins shown as US cash). The total is net worth's cash +
    stocks/funds + crypto at the same anchor and price mode (#144)."""
    stock_payload = _stock_exposure(db, anchor_ts, base_currency, current_user_id, price_overlay=price_overlay)
    rates = fx.get_rates(anchor_ts, base_currency, {"USD"})
    usd_rate = rates.get("USD", 0.0)

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

    for entry in _cash_positions(db, anchor_ts, base_currency, current_user_id):
        _bucket(entry.get("country") or "UNKNOWN")["cash"] += float(entry["value"])

    valuation = _wallet_valuation(db, anchor_ts, current_user_id, price_overlay=price_overlay)
    wallet_usd = float(valuation.get("total_usd") or 0.0)
    stable_usd = sum(
        float(item.get("value_usd") or 0.0)
        for item in valuation.get("items", [])
        if str(item.get("symbol") or "").upper() in _STABLECOIN_SYMBOLS
    )
    if wallet_usd:
        us_bucket = _bucket("US")
        us_bucket["cash"] += stable_usd * usd_rate
        us_bucket["crypto"] += (wallet_usd - stable_usd) * usd_rate

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
    nav_live_rows, nav_live_prices, nav_live_currencies = _nav_live_context(
        db, anchor_ts, current_user_id, base_currency, enabled=price_overlay
    )
    # Cash of accounts not valued by a NAV (a NAV account's cash is in its NAV
    # total below): the same entries net worth adds up (#144).
    cash_entries = [
        entry
        for entry in _cash_positions(db, anchor_ts, base_currency, current_user_id)
        if entry["kind"] == CASH_KIND_BALANCE
    ]
    wallet_usd = float(_wallet_valuation(db, anchor_ts, current_user_id, price_overlay=price_overlay)["total_usd"] or 0.0)
    currencies = {_canonical_base_currency(row, base_currency) for row in canonical_pos_rows}
    currencies.update(str(price["currency"]).upper() for price in latest_prices.values() if price.get("currency"))
    currencies.update(row["base_currency"] for row in canonical_nav_rows if row.get("base_currency"))
    currencies.update(nav_live_currencies)
    if wallet_usd:
        currencies.add("USD")
    rates = fx.get_rates(anchor_ts, base_currency, currencies)
    nav_deltas = _nav_live_price_deltas(nav_live_rows, nav_live_prices, rates, base_currency)
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
        value = float(row.get("total_nav_base") or 0.0) * rates.get(nav_currency, 0.0)
        value += nav_deltas.get(int(row["legacy_account_id"]), 0.0) if row.get("legacy_account_id") is not None else 0.0
        key = (row.get("platform") or "UNKNOWN", row.get("platform_type"), row.get("country"))
        buckets[key] = buckets.get(key, 0.0) + value
    for entry in cash_entries:
        key = (entry.get("platform") or "UNKNOWN", entry.get("platform_type"), entry.get("country"))
        buckets[key] = buckets.get(key, 0.0) + float(entry["value"])
    if wallet_usd:
        buckets[("CRYPTO", "WALLET_PROVIDER", None)] = buckets.get(("CRYPTO", "WALLET_PROVIDER", None), 0.0) + (
            wallet_usd * rates.get("USD", 0.0)
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



def _currency_exposure(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
    *,
    price_overlay: bool = False,
) -> Dict[str, Any]:
    """Net worth at ``anchor_ts`` by currency (#253): stocks/funds by the currency
    each holding is denominated in (_stock_exposure's split; an IBKR NAV by its
    holdings' currencies), cash by the currency it is held in (_cash_positions,
    net-worth scope), USD stablecoins as USD, other crypto as one ``CRYPTO``
    bucket (not a currency), less each card's liability in the card's currency.
    The same parts, anchor and price mode as _networth_components, so the values
    add up to net worth; ``percent`` is the share of net worth."""
    buckets: Dict[str, Dict[str, float]] = {}

    def _add(currency: str | None, part: str, value: float) -> None:
        key = str(currency or base_currency).upper()
        bucket = buckets.setdefault(
            key, {"cash": 0.0, "stocks_funds": 0.0, "stablecoins": 0.0, "crypto": 0.0, "liabilities": 0.0}
        )
        bucket[part] += value

    stock_payload = _stock_exposure(db, anchor_ts, base_currency, current_user_id, price_overlay=price_overlay)
    for row in stock_payload["by_currency"]:
        _add(row["key"], "stocks_funds", float(row.get("value") or 0.0))

    for entry in _cash_positions(db, anchor_ts, base_currency, current_user_id):
        _add(entry.get("currency"), "cash", float(entry["value"]))

    valuation = _wallet_valuation(db, anchor_ts, current_user_id, price_overlay=price_overlay)
    wallet_usd = float(valuation.get("total_usd") or 0.0)
    if wallet_usd:
        usd_rate = fx.get_rates(anchor_ts, base_currency, {"USD"}).get("USD", 0.0)
        stable_usd = sum(
            float(item.get("value_usd") or 0.0)
            for item in valuation.get("items", [])
            if str(item.get("symbol") or "").upper() in _STABLECOIN_SYMBOLS
        )
        if stable_usd:
            _add("USD", "stablecoins", stable_usd * usd_rate)
        if wallet_usd - stable_usd:
            _add(CRYPTO_EXPOSURE_KEY, "crypto", (wallet_usd - stable_usd) * usd_rate)

    for card in _credit_card_liability_details(db, anchor_ts, base_currency, current_user_id):
        if card["value"]:
            _add(card.get("currency"), "liabilities", float(card["value"]))

    items: List[Dict[str, Any]] = []
    for currency, parts in buckets.items():
        value = parts["cash"] + parts["stocks_funds"] + parts["stablecoins"] + parts["crypto"] - parts["liabilities"]
        if abs(value) < 1e-9 and not any(parts.values()):
            continue
        items.append({"currency": currency, **parts, "value": value})
    total = sum(item["value"] for item in items)
    items.sort(key=lambda row: (-row["value"], row["currency"]))
    for row in items:
        row["percent"] = round((row["value"] / total) * 100, 2) if total > 0 else 0.0
    return {"base_currency": base_currency, "total": total, "items": items}
