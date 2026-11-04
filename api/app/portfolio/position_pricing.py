"""One price rule for every holding (D-21, extended to all holdings by #144).

A holding's value comes from its own statement (the canonical position
snapshot: IBKR Flex, an uploaded holdings file). In a live view the price job's
quote replaces the statement price when the quote is

- at least as recent as the holding's own report date, and
- not over 2x off the statement value (a likely wrong symbol or currency).

Otherwise the statement value stands and the holding says why
(``no_quote`` | ``quote_older`` | ``quote_implausible``). A holding whose
statement has no market value is valued at its cost, flagged ``valued_at_cost``,
never at 0 (#130 finding 2.7).

The dashboard (net worth, holdings, allocation, exposure) and the dividend
yields all value holdings through here.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, NamedTuple, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.valuation_cache import valuation_cached

PRICE_FALLBACK_NO_QUOTE = "no_quote"  # the price job has no quote for it
PRICE_FALLBACK_OLDER_QUOTE = "quote_older"  # its newest quote predates the holding's statement
PRICE_FALLBACK_IMPLAUSIBLE = "quote_implausible"  # over 2x off the statement value
IMPLAUSIBLE_QUOTE_RATIO = 2.0


def _date_only(value: Any) -> Optional[date]:
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


@valuation_cached()
def latest_quotes(db: Session, anchor_date: date, asset_ids: frozenset[int]) -> dict[int, dict[str, Any]]:
    """Per asset: the price job's newest dated quote on or before ``anchor_date``.

    Ties on the trade date (one row per source) are broken deterministically:
    the most recently written row, then source name, then id (#130 2.6).
    """
    if not asset_ids:
        return {}
    ids = ",".join(str(int(asset_id)) for asset_id in sorted(asset_ids))
    rows = db.execute(
        text(
            f"""
            SELECT asset_id, price, currency, trade_date, source, provider_symbol, exchange_code
            FROM (
              SELECT p.asset_id, p.price, p.currency, p.trade_date, p.source, p.provider_symbol, p.exchange_code,
                     ROW_NUMBER() OVER (
                       PARTITION BY p.asset_id
                       ORDER BY p.trade_date DESC, p.ts DESC, p.source ASC, p.id DESC
                     ) AS rn
              FROM prices p
              WHERE p.trade_date IS NOT NULL
                AND p.trade_date <= :anchor_date
                AND p.asset_id IN ({ids})
            ) ranked
            WHERE rn = 1
            """
        ),
        {"anchor_date": anchor_date},
    ).mappings().all()
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


def position_base_currency(row: dict[str, Any], fallback: str) -> str:
    """The currency the snapshot's *_base amounts are in."""
    return str(row.get("account_base_currency") or row.get("account_currency") or fallback).upper()


def statement_value(row: dict[str, Any], rates: dict[str, float], fallback_currency: str) -> tuple[float, bool]:
    """(value in the target currency, valued_at_cost) from the holding's own statement:
    its market value, else its cost basis. A missing FX rate gives 0 (D-30: left out)."""
    currency = position_base_currency(row, fallback_currency)
    raw_value = row.get("snapshot_market_value_base")
    valued_at_cost = False
    if raw_value is None:
        raw_value = row.get("snapshot_cost_basis_base")
        if raw_value is None:
            raw_value = row.get("cost_basis_base")
        valued_at_cost = raw_value is not None
    return float(raw_value or 0.0) * rates.get(currency, 0.0), valued_at_cost


def quote_value(row: dict[str, Any], quote: dict[str, Any], rates: dict[str, float], fallback_currency: str) -> float:
    currency = str(quote.get("currency") or row.get("quote_currency") or fallback_currency).upper()
    return float(row.get("quantity") or 0.0) * float(quote["price"]) * rates.get(currency, 0.0)


class PositionPrice(NamedTuple):
    quote: Optional[dict[str, Any]]  # the quote used, or None (statement value)
    fallback_reason: Optional[str]  # why the statement value was used (live views only)
    value: float  # the value to show and add up
    statement_value: float  # the holding's statement value
    valued_at_cost: bool  # the value is the holding's cost (no market value, no usable quote)


def price_position(
    row: dict[str, Any],
    quotes: dict[int, dict[str, Any]] | None,
    rates: dict[str, float],
    fallback_currency: str,
) -> PositionPrice:
    """Value one holding. ``quotes`` is None outside live views: the statement
    value, no reason. In a live view (a dict, possibly empty): D-21, for every
    holding."""
    snapshot, at_cost = statement_value(row, rates, fallback_currency)
    if quotes is None:
        return PositionPrice(None, None, snapshot, snapshot, at_cost)
    asset_id = row.get("asset_id")
    quote = quotes.get(int(asset_id)) if asset_id is not None else None
    if not quote or quote.get("price") is None or row.get("quantity") is None:
        return PositionPrice(None, PRICE_FALLBACK_NO_QUOTE, snapshot, snapshot, at_cost)
    quote_date = _date_only(quote.get("trade_date"))
    report_date = _date_only(row.get("report_date"))
    if quote_date is not None and report_date is not None and quote_date < report_date:
        return PositionPrice(None, PRICE_FALLBACK_OLDER_QUOTE, snapshot, snapshot, at_cost)
    live = quote_value(row, quote, rates, fallback_currency)
    # The 2x sanity check compares with a market value; a cost basis can be
    # legitimately far from today's price.
    if not at_cost and snapshot > 0 and live > 0:
        ratio = live / snapshot
        if ratio > IMPLAUSIBLE_QUOTE_RATIO or ratio < 1 / IMPLAUSIBLE_QUOTE_RATIO:
            return PositionPrice(None, PRICE_FALLBACK_IMPLAUSIBLE, snapshot, snapshot, at_cost)
    return PositionPrice(quote, None, live, snapshot, False)
