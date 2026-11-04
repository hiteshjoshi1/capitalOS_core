"""Prices for holdings (D-21/D-42): the rule itself lives in
``app.portfolio.position_pricing``; this is how valuation applies it."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.portfolio.canonical_reads import canonical_position_rows_by_legacy_account
from app.portfolio.position_pricing import (
    IMPLAUSIBLE_QUOTE_RATIO,
    PRICE_FALLBACK_IMPLAUSIBLE,
    PRICE_FALLBACK_NO_QUOTE,
    PRICE_FALLBACK_OLDER_QUOTE,
    PositionPrice,
    latest_quotes,
    position_base_currency,
    price_position,
)
from app.valuation import fx
from app.valuation.clock import _iso_value, _normalize_ts


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


def _latest_price_map(db: Session, anchor_ts: datetime, asset_ids: set[int]) -> Dict[int, Dict[str, Any]]:
    """The price job's newest quote per asset on or before the anchor date, with a
    deterministic choice between sources (app.portfolio.position_pricing)."""
    return latest_quotes(db, anchor_ts.date(), frozenset(int(asset_id) for asset_id in asset_ids))


def _canonical_base_currency(row: Dict[str, Any], fallback: str) -> str:
    return position_base_currency(row, fallback)


def _canonical_position_value(
    row: Dict[str, Any],
    rates: Dict[str, float],
    fallback_currency: str,
    latest_prices: Dict[int, Dict[str, Any]] | None = None,
) -> float:
    """A holding's value: its statement value (market value, else cost), or in a
    live view (``latest_prices`` given) the price job's quote under D-21's rule,
    for every holding (#144). An empty ``latest_prices`` is the same as none."""
    return price_position(row, latest_prices or None, rates, fallback_currency).value


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


# ─── Live prices for holdings (D-21, #124; every holding since #144) ─────────
# The statement (IBKR's Flex report, an uploaded holdings file) is the source of
# truth for what is held. For the *price* of a holding in a live view, the price
# job's quote wins whenever it is at least as recent as the holding's report and
# within 2x of its statement value; otherwise the statement price stands, and
# the holding says why. The rule lives in app.portfolio.position_pricing.
IBKR_PRICE_FALLBACK_NO_QUOTE = PRICE_FALLBACK_NO_QUOTE
IBKR_PRICE_FALLBACK_OLDER_QUOTE = PRICE_FALLBACK_OLDER_QUOTE
IBKR_PRICE_FALLBACK_IMPLAUSIBLE = PRICE_FALLBACK_IMPLAUSIBLE
_IMPLAUSIBLE_QUOTE_RATIO = IMPLAUSIBLE_QUOTE_RATIO


def _live_position_price(
    row: Dict[str, Any],
    latest_prices: Dict[int, Dict[str, Any]],
    rates: Dict[str, float],
    base_currency: str,
) -> PositionPrice:
    """One holding in a live view, under D-21 (whichever platform holds it)."""
    return price_position(row, latest_prices or {}, rates, base_currency)


def _nav_row_live_price(
    row: Dict[str, Any],
    latest_prices: Dict[int, Dict[str, Any]],
    rates: Dict[str, float],
    base_currency: str,
) -> tuple[Optional[Dict[str, Any]], Optional[str], float, float]:
    """(quote to use or None, fallback reason or None, live value, statement value)."""
    priced = _live_position_price(row, latest_prices, rates, base_currency)
    return priced.quote, priced.fallback_reason, priced.value, priced.statement_value


def _nav_live_price_deltas(
    nav_position_rows: list[Dict[str, Any]],
    latest_prices: Dict[int, Dict[str, Any]],
    rates: Dict[str, float],
    base_currency: str,
) -> Dict[int, float]:
    """Per legacy account: (holdings at the price job's quotes) - (holdings at IBKR's
    statement prices), in base currency, to add to that account's NAV in live views."""
    deltas: Dict[int, float] = {}
    for row in nav_position_rows:
        if not row.get("has_nav_snapshot") or row.get("account_id") is None:
            continue
        if str(row.get("asset_class") or "").upper() not in {"STOCK", "FUND"}:
            continue
        quote, _reason, live_value, snapshot_value = _nav_row_live_price(row, latest_prices, rates, base_currency)
        if quote is None:
            continue
        account_id = int(row["account_id"])
        deltas[account_id] = deltas.get(account_id, 0.0) + (live_value - snapshot_value)
    return deltas


def _nav_live_context(
    db: Session,
    anchor_ts: datetime,
    current_user_id: int,
    base_currency: str,
    *,
    enabled: bool,
) -> tuple[list[Dict[str, Any]], Dict[int, Dict[str, Any]], set[str]]:
    """IBKR position rows, their latest quotes, and the currencies needed to value
    them; empty when not a live view."""
    if not enabled:
        return [], {}, set()
    rows = [
        row
        for row in canonical_position_rows_by_legacy_account(
            db,
            current_user_id=current_user_id,
            anchor_date=anchor_ts.date(),
            include_nav_accounts=True,
        )
        if row.get("has_nav_snapshot")
    ]
    prices = _latest_prices_for_positions(db, anchor_ts, rows, enabled=True)
    currencies = {_canonical_base_currency(row, base_currency) for row in rows}
    currencies.update(str(price["currency"]).upper() for price in prices.values() if price.get("currency"))
    return rows, prices, currencies


def _asset_market_values(
    db: Session,
    anchor_ts: datetime,
    base_currency: str,
    current_user_id: int,
) -> dict[int, float]:
    """Per asset: the market value of every stock/fund holding at ``anchor_ts``
    in ``base_currency``, priced like the live dashboard holdings (the yield
    denominator of the Dividends page)."""
    rows = canonical_position_rows_by_legacy_account(
        db,
        current_user_id=current_user_id,
        anchor_date=anchor_ts.date(),
        include_nav_accounts=True,
    )
    holding_rows = [
        row
        for row in rows
        if row.get("asset_id") is not None and str(row.get("asset_class") or "").upper() in {"STOCK", "FUND"}
    ]
    if not holding_rows:
        return {}
    # The same price rule as the dashboard's holdings (D-21 for every holding,
    # #144): the price job's quote when it's at least as recent as the holding's
    # statement and within 2x of it, else the statement value (market value, else cost).
    quotes = latest_quotes(db, anchor_ts.date(), frozenset(int(row["asset_id"]) for row in holding_rows))
    currencies = {position_base_currency(row, base_currency) for row in holding_rows}
    currencies.update(str(quote["currency"]).upper() for quote in quotes.values() if quote.get("currency"))
    currencies.update(str(row["quote_currency"]).upper() for row in holding_rows if row.get("quote_currency"))
    fx_rates = fx.get_rates(anchor_ts, base_currency, currencies)
    out: dict[int, float] = {}
    for row in holding_rows:
        asset = int(row["asset_id"])
        out[asset] = out.get(asset, 0.0) + price_position(row, quotes, fx_rates, base_currency).value
    return out
