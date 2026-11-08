"""Realised P&L on sold positions (#293, D-78).

Per sale (a SELL fill in ``portfolio_trades`` of a stock, fund or option; FX conversions,
assetCategory CASH, are not positions):
- IBKR's own ``fifoPnlRealized`` for the fill when the Flex report gave one (kept in the
  trade's ``metadata_json``): source ``ibkr``;
- else FIFO over the account's fills of the same instrument, oldest first: proceeds net of
  commission minus the cost (price paid plus commission) of the lots it closes: ``fifo``;
- a sale that closes more than the known buys hold has no known cost: ``cost_unknown``,
  never 0, and it is left out of the totals.
Amounts are in the trade's currency and in the base currency at the trade date's rate
(D-30: no rate leaves the sale out of the base totals, named, never 1.0). The fill's own
IBKR rate (``fxRateToBase``) is used when the requested base is the account's base.
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Deque, Dict, Iterable, List, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import fx
from app.auth_context import account_scope_sql

NOT_POSITIONS = frozenset({"CASH"})
SOURCE_IBKR = "ibkr"
SOURCE_FIFO = "fifo"
SOURCE_COST_UNKNOWN = "cost_unknown"
_EPS = Decimal("1e-9")


@dataclass
class Fill:
    trade_id: int
    account_key: Any  # broker account
    instrument_key: Any
    trade_date: date
    side: str
    quantity: Decimal  # signed as reported; the side decides
    proceeds: Decimal  # negative for a buy, positive for a sale
    commission: Decimal  # usually negative
    currency: str
    symbol: Optional[str] = None
    platform: Optional[str] = None
    account_base: Optional[str] = None
    ibkr_realised: Optional[Decimal] = None
    fx_rate_to_base: Optional[Decimal] = None


@dataclass
class Sale:
    trade_id: int
    trade_date: date
    symbol: Optional[str]
    platform: Optional[str]
    quantity: float
    proceeds: float
    cost: Optional[float]
    realised: Optional[float]
    currency: str
    source: str
    realised_base: Optional[float] = None
    fx_missing: bool = False
    instrument_key: Any = None
    account_key: Any = None
    # The rate from the trade's currency to base (#313), so proceeds and cost can be shown
    # in base too. None when the realised figure has no base value (cost unknown, no rate).
    base_rate: Optional[float] = None


def _dec(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def realised_sales(fills: Iterable[Fill]) -> List[Sale]:
    """Every sale with its realised P&L in the trade's currency. Pure: no database.
    Fills are processed per (account, instrument), oldest first (date, then id)."""
    by_position: Dict[tuple, List[Fill]] = defaultdict(list)
    for fill in fills:
        by_position[(fill.account_key, fill.instrument_key)].append(fill)
    sales: List[Sale] = []
    for position_fills in by_position.values():
        lots: Deque[list[Decimal]] = deque()  # [quantity left, cost per unit]
        for fill in sorted(position_fills, key=lambda f: (f.trade_date, f.trade_id)):
            quantity = abs(fill.quantity)
            if quantity <= _EPS:
                continue
            side = fill.side.upper()
            if side == "BUY":
                cost = abs(fill.proceeds) + abs(fill.commission)
                lots.append([quantity, cost / quantity])
                continue
            if side != "SELL":
                continue
            # Close lots oldest first; a shortfall means part of the cost isn't known.
            remaining, cost = quantity, Decimal("0")
            while remaining > _EPS and lots:
                lot = lots[0]
                take = min(remaining, lot[0])
                cost += take * lot[1]
                lot[0] -= take
                remaining -= take
                if lot[0] <= _EPS:
                    lots.popleft()
            net_proceeds = fill.proceeds - abs(fill.commission)
            known = remaining <= _EPS
            if fill.ibkr_realised is not None:
                realised, source = fill.ibkr_realised, SOURCE_IBKR
                cost_out: Optional[Decimal] = net_proceeds - fill.ibkr_realised
            elif known:
                realised, source, cost_out = net_proceeds - cost, SOURCE_FIFO, cost
            else:
                realised, source, cost_out = None, SOURCE_COST_UNKNOWN, None
            sales.append(
                Sale(
                    trade_id=fill.trade_id,
                    trade_date=fill.trade_date,
                    symbol=fill.symbol,
                    platform=fill.platform,
                    quantity=float(quantity),
                    proceeds=float(net_proceeds),
                    cost=float(cost_out) if cost_out is not None else None,
                    realised=float(realised) if realised is not None else None,
                    currency=fill.currency,
                    source=source,
                    instrument_key=fill.instrument_key,
                    account_key=fill.account_key,
                )
            )
    return sorted(sales, key=lambda s: (s.trade_date, s.trade_id))


def to_base(sales: List[Sale], fills_by_id: Mapping[int, Fill], base_currency: str) -> None:
    """Fill each sale's ``realised_base`` at its trade date's rate (D-30), in place."""
    base = base_currency.upper()
    need = [s for s in sales if s.realised is not None]
    lookup = [
        s for s in need
        if s.currency.upper() != base
        and not (
            fills_by_id[s.trade_id].fx_rate_to_base is not None
            and (fills_by_id[s.trade_id].account_base or "").upper() == base
        )
    ]
    rates = fx.get_rates_by_date([s.trade_date for s in lookup], base, {s.currency for s in lookup}) if lookup else {}
    for sale in need:
        fill = fills_by_id[sale.trade_id]
        assert sale.realised is not None
        if sale.currency.upper() == base:
            sale.base_rate = 1.0
        elif fill.fx_rate_to_base is not None and (fill.account_base or "").upper() == base:
            sale.base_rate = float(fill.fx_rate_to_base)
        else:
            day_rates: Mapping[str, float] = rates.get(fx.rate_date(sale.trade_date)) or {}
            rate = day_rates.get(sale.currency.upper())
            if rate is None:
                sale.fx_missing = True
                continue
            sale.base_rate = float(rate)
        sale.realised_base = sale.realised * sale.base_rate


@dataclass
class Totals:
    realised_base: float = 0.0
    sales: int = 0
    cost_unknown: int = 0
    fx_missing_currencies: List[str] = field(default_factory=list)
    sources: Dict[str, int] = field(default_factory=dict)


def totals(sales: Iterable[Sale], start: date, end: date) -> Totals:
    """Sales dated start..end inclusive."""
    out = Totals()
    missing: set[str] = set()
    for sale in sales:
        if not (start <= sale.trade_date <= end):
            continue
        out.sales += 1
        out.sources[sale.source] = out.sources.get(sale.source, 0) + 1
        if sale.source == SOURCE_COST_UNKNOWN:
            out.cost_unknown += 1
        elif sale.fx_missing:
            missing.add(sale.currency.upper())
        elif sale.realised_base is not None:
            out.realised_base += sale.realised_base
    out.realised_base = round(out.realised_base, 2)
    out.fx_missing_currencies = sorted(missing)
    return out


def load_fills(db: Session, current_user_id: int, until: date) -> List[Fill]:
    rows = db.execute(
        text(
            f"""
            SELECT t.id, t.broker_account_id, t.broker_instrument_id, t.trade_date, t.side, t.quantity,
                   t.proceeds, t.commission, t.currency, t.metadata_json,
                   bi.symbol, bi.security_type, bi.broker_instrument_id AS conid,
                   ba.base_currency AS account_base, acc.platform
            FROM portfolio_trades t
            JOIN broker_accounts ba ON ba.id = t.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            LEFT JOIN broker_instruments bi ON bi.id = t.broker_instrument_id
            WHERE t.trade_date <= :until
              AND {account_scope_sql("acc")}
            """
        ),
        {"until": until, "current_user_id": current_user_id},
    ).mappings().all()
    fills: List[Fill] = []
    for row in rows:
        if str(row["security_type"] or "").upper() in NOT_POSITIONS:
            continue
        meta = row["metadata_json"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta or "{}")
            except ValueError:
                meta = {}
        meta = meta or {}
        ibkr = meta.get("fifo_pnl_realized")
        rate = meta.get("fx_rate_to_base")
        trade_date = row["trade_date"]
        if isinstance(trade_date, str):
            trade_date = date.fromisoformat(trade_date[:10])
        fills.append(
            Fill(
                trade_id=int(row["id"]),
                account_key=int(row["broker_account_id"]),
                instrument_key=row["broker_instrument_id"] or row["conid"] or row["symbol"],
                trade_date=trade_date,
                side=str(row["side"] or ""),
                quantity=_dec(row["quantity"]),
                proceeds=_dec(row["proceeds"]),
                commission=_dec(row["commission"]),
                currency=str(row["currency"] or "").upper(),
                symbol=row["symbol"],
                platform=row["platform"],
                account_base=row["account_base"],
                ibkr_realised=_dec(ibkr) if ibkr not in (None, "") else None,
                fx_rate_to_base=_dec(rate) if rate not in (None, "") else None,
            )
        )
    return fills


# ─── Any period, grouped by stock (#313) ───────────────────────────────────────
PERIOD_MONTH = "month"
PERIOD_YTD = "ytd"
PERIOD_LAST_YEAR = "last_year"
PERIOD_YEAR = "year"
PERIOD_RANGE = "range"
PERIODS = (PERIOD_MONTH, PERIOD_YTD, PERIOD_LAST_YEAR, PERIOD_YEAR, PERIOD_RANGE)


@dataclass
class Period:
    key: str
    start: date
    end: date  # inclusive, never after today
    label: str


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def resolve_period(
    key: str,
    *,
    today: date,
    month_start: date,
    month_end: date,
    year: Optional[int] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Period:
    """The dates a period covers, in the user's calendar (``today`` is the app's today in
    their timezone). Trade dates are IBKR's own dates, so no timezone shift applies to them.
    - month: the selected month (to today when it's the current one);
    - ytd: 1 Jan of today's year to today;
    - last_year: the whole previous calendar year;
    - year: that calendar year (to today for the current year);
    - range: start..end as given (end capped at today).
    Raises ValueError for an unknown key, a missing year or range, or start after end."""
    if key == PERIOD_MONTH:
        return Period(key, month_start, min(month_end, today), f"{_MONTHS[month_start.month - 1]} {month_start.year}")
    if key == PERIOD_YTD:
        return Period(key, date(today.year, 1, 1), today, f"{today.year} to date")
    if key == PERIOD_LAST_YEAR:
        y = today.year - 1
        return Period(key, date(y, 1, 1), date(y, 12, 31), str(y))
    if key == PERIOD_YEAR:
        if year is None:
            raise ValueError("year is required for period=year")
        if year > today.year:
            raise ValueError("year is in the future")
        return Period(key, date(year, 1, 1), min(date(year, 12, 31), today), f"{year} to date" if year == today.year else str(year))
    if key == PERIOD_RANGE:
        if start is None or end is None:
            raise ValueError("from and to are required for period=range")
        end = min(end, today)
        if start > end:
            raise ValueError("from is after to")
        return Period(key, start, end, f"{start.isoformat()} to {end.isoformat()}")
    raise ValueError(f"unknown period {key!r}")


def _sale_dict(s: Sale) -> Dict[str, Any]:
    return {
        "trade_date": s.trade_date.isoformat(),
        "symbol": s.symbol,
        "platform": s.platform,
        "quantity": s.quantity,
        "proceeds": round(s.proceeds, 2),
        "cost": round(s.cost, 2) if s.cost is not None else None,
        "realised": round(s.realised, 2) if s.realised is not None else None,
        "currency": s.currency,
        "realised_base": round(s.realised_base, 2) if s.realised_base is not None else None,
        "source": s.source,
        "fx_missing": s.fx_missing,
    }


def by_instrument(sales: Iterable[Sale], start: date, end: date) -> List[Dict[str, Any]]:
    """The period's sales grouped per instrument and account, biggest move first (by the
    size of the realised gain or loss in base). Proceeds and cost in base count only the
    sales whose gain is in the total (a known cost and a rate); the rest are counted and
    named per instrument. Instruments with nothing in the total sort last. Pure."""
    groups: Dict[tuple, Dict[str, Any]] = {}
    for sale in sales:
        if not (start <= sale.trade_date <= end):
            continue
        key = (sale.account_key, sale.instrument_key if sale.instrument_key is not None else sale.symbol)
        group = groups.get(key)
        if group is None:
            group = groups[key] = {
                "symbol": sale.symbol,
                "platform": sale.platform,
                "currency": sale.currency,
                "sales_count": 0,
                "quantity": 0.0,
                "realised_base": 0.0,
                "proceeds_base": 0.0,
                "cost_base": 0.0,
                "realised": 0.0,
                "in_total": 0,
                "cost_unknown": 0,
                "fx_missing": False,
                "sources": {},
                "first_sale": sale.trade_date.isoformat(),
                "last_sale": sale.trade_date.isoformat(),
                "sales": [],
            }
        group["sales_count"] += 1
        group["quantity"] += sale.quantity
        group["sources"][sale.source] = group["sources"].get(sale.source, 0) + 1
        group["last_sale"] = max(group["last_sale"], sale.trade_date.isoformat())
        group["sales"].append(_sale_dict(sale))
        if sale.source == SOURCE_COST_UNKNOWN:
            group["cost_unknown"] += 1
            continue
        if sale.realised is not None:
            group["realised"] += sale.realised
        if sale.fx_missing or sale.realised_base is None or sale.base_rate is None:
            group["fx_missing"] = group["fx_missing"] or sale.fx_missing
            continue
        group["in_total"] += 1
        group["realised_base"] += sale.realised_base
        group["proceeds_base"] += sale.proceeds * sale.base_rate
        group["cost_base"] += (sale.cost or 0.0) * sale.base_rate
    out = []
    for group in groups.values():
        for name in ("realised_base", "proceeds_base", "cost_base", "realised"):
            group[name] = round(group[name], 2)
        group["quantity"] = round(group["quantity"], 6)
        out.append(group)
    out.sort(key=lambda g: (g["in_total"] == 0, -abs(g["realised_base"]), g["symbol"] or ""))
    return out


def realised_summary(
    db: Session,
    current_user_id: int,
    base_currency: str,
    month_start: date,
    month_end: date,
    period: Optional[Period] = None,
) -> Dict[str, Any]:
    """The selected month's and its year-to-date realised P&L, with the month's sales;
    plus (#313) the chosen period's totals and its sales grouped per stock."""
    period = period or Period(PERIOD_MONTH, month_start, month_end, "")
    fills = load_fills(db, current_user_id, max(month_end, period.end))
    sales = realised_sales(fills)
    to_base(sales, {f.trade_id: f for f in fills}, base_currency)
    month = totals(sales, month_start, month_end)
    ytd = totals(sales, date(month_end.year, 1, 1), month_end)
    chosen = totals(sales, period.start, period.end)

    def _totals(t: Totals) -> Dict[str, Any]:
        return {
            "realised": t.realised_base,
            "sales": t.sales,
            "cost_unknown": t.cost_unknown,
            "fx_missing_currencies": t.fx_missing_currencies,
            "sources": t.sources,
        }

    years = sorted({s.trade_date.year for s in sales}, reverse=True)
    return {
        "base_currency": base_currency.upper(),
        "month": _totals(month),
        "year_to_date": _totals(ytd),
        "sales": [_sale_dict(s) for s in sales if month_start <= s.trade_date <= month_end],
        "period": {
            "key": period.key,
            "start": period.start.isoformat(),
            "end": period.end.isoformat(),
            "label": period.label,
        },
        "period_totals": _totals(chosen),
        "by_instrument": by_instrument(sales, period.start, period.end),
        "years_with_sales": years,
        "trades_from": trade_history_start(db, current_user_id),
        "platforms_without_trades": platforms_without_trades(db, current_user_id),
    }


def trade_history_start(db: Session, current_user_id: int) -> Optional[str]:
    """The earliest trade date the app holds for the user (#313): before it, no sales are known."""
    value = db.execute(
        text(
            f"""
            SELECT MIN(t.trade_date)
            FROM portfolio_trades t
            JOIN broker_accounts ba ON ba.id = t.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE {account_scope_sql("acc")}
            """
        ),
        {"current_user_id": current_user_id},
    ).scalar()
    if value is None:
        return None
    return value.isoformat()[:10] if hasattr(value, "isoformat") else str(value)[:10]


def platforms_without_trades(db: Session, current_user_id: int) -> List[str]:
    """Broker platforms the user holds (an open BROKER account) whose data has no trades,
    e.g. statements of holdings only (#313): no realised P&L can be shown for them."""
    rows = db.execute(
        text(
            f"""
            SELECT DISTINCT acc.platform
            FROM accounts acc
            WHERE acc.account_type = 'BROKER'
              AND acc.closed_on IS NULL
              AND acc.platform IS NOT NULL
              AND {account_scope_sql("acc")}
              AND NOT EXISTS (
                SELECT 1 FROM broker_accounts ba
                JOIN portfolio_trades t ON t.broker_account_id = ba.id
                WHERE ba.legacy_account_id = acc.id
              )
            ORDER BY acc.platform
            """
        ),
        {"current_user_id": current_user_id},
    ).scalars().all()
    return [str(platform) for platform in rows]
