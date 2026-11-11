"""The "This month" bridge (#240, D-60): what moved net worth from the last
month-end close to the figure Overview shows.

    start + new money + markets + FX + dividends/interest + cash kept + catch-up + unexplained = end

- **start** is the completed month-end Overview's "vs last month" compares with
  (``_month_view_compare_month_start``, D-24), valued like that month's History
  point (statement prices, ``_networth_components``).
- **end** is Overview's headline (D-55): live "now" for the open (or a future)
  month, that month's month-end for a past month (``_month_view_anchor``).
- The **period** runs from the start anchor to the end: a past month's calendar
  month (with SNAPSHOT_DAY=1), month to date for the open month. Flows count by
  the user's calendar (``_transaction_in_month_window``, #211) and convert at
  the rate of their own date (D-30).

Every line is computed from what is recorded; what can't be is said (``status``,
``reason``) and lands in ``unexplained``, which is ``end - start - sum(lines)``:
the lines always add up, and the residual is shown, never hidden. Its known
parts (trades with no cash record, crypto moved in or out of wallets, card
balances that don't match card transactions, holdings the statement totals
don't cover) are named, the rest is "other".

**Catch-up** (#329, D-81): the start is the month-end close History shows, and each
account's part of it is its newest figure at that anchor, which can be months old (a
bank balance from July, a holdings statement from August). The end then includes every
change since, but the period's lines only count the period's own flows, so earlier
months landed in Unexplained. An account whose starting figure is more than
CATCH_UP_STALE_DAYS older than the period's start gets its own Catch-up part: a cash
account's change less its own transactions in the period, a holdings statement's
change in quantity. The start itself is never changed (it is the contract figure).

**Newly tracked** (#330, D-82): a wallet or account whose first data falls in the period
is new to the app, not money moving: its balance is on its own line (a new account's,
less its own transactions in the period). **Staking rewards**: a rebasing staking token
(stETH) whose quantity grows by at most STAKING_MAX_GROWTH is income, in Dividends &
interest, not "crypto moved".

**Items** (#332): every part of Catch-up, Newly tracked and Unexplained lists what it is
made of (which holding, account, card, token), largest first, with a reason and, where
there is something to do, a link. A part's items add up to it (a "rest" item when the
list is cut at ITEMS_MAX).

The position, NAV, cash and wallet facts are read through the canonical read
layer (D-56), the same readers net worth uses, so start and end are exactly the
contract figures (D-58). The flow lines read the same rows as the Cash flow and
Dividends pages.
"""
from __future__ import annotations

from decimal import Decimal

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.portfolio.canonical_reads import canonical_position_rows_by_legacy_account
from app.portfolio.ledger_dividends import LEDGER_CODES, ledger_covered_since
from app.portfolio.position_pricing import price_position
from app.routers.dividends import _covered_by_ledger
from app.routers.spending import _build_row_rate_map, _cash_flow_bucket, _cash_flow_rows, _row_base_amount
from app.valuation import clock, fx, move_causes
from app.valuation.clock import (
    _anchor_ts,
    _completed_snapshot_month_start,
    _configured_snapshot_day,
    _date_only,
    _is_snapshot_anchor,
    _iso_value,
    _local_date,
    _month_view_anchor,
    _month_view_compare_month_start,
    _transaction_in_month_window,
)
from app.valuation.facts import _networth_components, _serialize_net_worth
from app.valuation.history import baseline_missing
from app.valuation.prices import _canonical_base_currency, _latest_prices_for_positions
from app.valuation.state import _cash_positions, _effective_as_of, _wallet_valuation
from app.valuation.money import D, ONE, ZERO, D_or_none, dsum, float_edge

# IBKR Statement of Funds codes for money paid in or taken out, and for interest.
LEDGER_DEPOSIT_CODES = frozenset({"DEP", "WITH", "DEPOSIT", "WITHDRAWAL"})
LEDGER_INTEREST_CODES = frozenset({"CINT", "DINT"})
# A deposit into a broker is a move between your own accounts when another of your
# accounts has a TRANSFER of the opposite amount, same currency, this many days apart.
TRANSFER_MATCH_DAYS = 5
TRANSFER_MATCH_TOLERANCE = Decimal("0.01")
# What a card's liability counts (app.valuation.facts._credit_card_liability_details).
CARD_LIABILITY_TYPES = frozenset({"EXPENSE", "FEE", "TAX", "INTEREST", "TRANSFER", "INCOME"})
STOCK_CLASSES = frozenset({"STOCK", "FUND"})
# A holding's value may imply an FX rate this far from the stored one (an IBKR
# statement converts at its own date's rate); further off, the value doesn't match
# its quantity x price and the stored rate is used instead.
RATE_TOLERANCE = Decimal("0.01")
_EPS = Decimal("1e-9")
# The line's "N holding(s) without a price" note counts holdings whose unsplit change is
# at least this much in the base currency (dust tokens that lost their quote don't).
UNSPLIT_COUNT_MIN = Decimal(1)
# A change in quantity at least this big (base currency) is listed as a trade.
TRADE_MIN = Decimal(1)
# An account's starting figure older than this before the period's start is stale: its
# change over the period includes earlier months, shown as Catch-up (#329, D-81).
CATCH_UP_STALE_DAYS = 7
# Rebasing staking tokens: their quantity grows with the rewards (#330, D-82). Growth over
# this share of the starting quantity is a deposit or a move, not rewards.
STAKING_REBASING_SYMBOLS = frozenset({"STETH", "EETH"})
STAKING_MAX_GROWTH = Decimal("0.02")
# A part lists at most this many items (#332); the rest add up into one "rest" item.
ITEMS_MAX = 8
ITEM_MIN = Decimal("0.5")


@dataclass
class _Holding:
    """One holding at one anchor, in the base currency: value = quantity * price * rate."""

    mover_key: tuple
    asset_id: Optional[int]
    symbol: str
    name: Optional[str]
    asset_class: str
    platform: Optional[str]
    account_id: Optional[int]
    quantity: Optional[Decimal]
    price: Optional[Decimal]  # in the currency it is quoted in
    value: Decimal
    fx_rate: Optional[Decimal] = None  # base currency per unit of the price's currency, at the anchor
    price_currency: Optional[str] = None  # the currency ``price`` is in
    as_of: Optional[date] = None  # the statement date the holding comes from (#289)
    fallback_reason: Optional[str] = None  # D-21: why a live view used the statement price (#289)

    def __post_init__(self) -> None:
        # Decimal throughout (#360): whatever the caller passed (a float rate, a live price).
        self.quantity = D_or_none(self.quantity)
        self.price = D_or_none(self.price)
        self.value = D(self.value)
        self.fx_rate = D_or_none(self.fx_rate)

    def rate(self) -> Optional[Decimal]:
        """Base currency per unit of the price's currency: the rate the value itself
        implies (value / (quantity * price): an IBKR statement's own conversion, on
        its own date), unless that is over RATE_TOLERANCE from the stored rate at the
        anchor (D-30): then the value doesn't match its own quantity x price, the
        stored rate is used and the difference shows as a gap (``_split``)."""
        if self.quantity is None or self.price is None:
            return None
        local = self.quantity * self.price
        if abs(local) < _EPS:
            return None
        implied = self.value / local
        if self.fx_rate is not None and self.fx_rate > 0 and abs(implied / self.fx_rate - ONE) > RATE_TOLERANCE:
            return self.fx_rate
        return implied

    def is_empty(self) -> bool:
        return abs(self.value) < _EPS and not (self.quantity or ZERO)


@dataclass
class _Split:
    price: Decimal = ZERO
    fx: Decimal = ZERO
    quantity: Decimal = ZERO
    unsplit: Decimal = ZERO  # a change that can't be split (no price or quantity on one side)
    # The part of the change in value that quantity x price x rate doesn't give: a
    # statement value that differs from its own quantity x price (or IBKR's rate
    # from the stored one). value1 - value0 = price + fx + quantity + unsplit + gap.
    gap: Decimal = ZERO

    @property
    def total(self) -> Decimal:
        return self.price + self.fx + self.quantity + self.unsplit + self.gap


def _split(start: Optional[_Holding], end: Optional[_Holding]) -> _Split:
    """end.value - start.value as price, FX and quantity effects:
    price = q0 (p1 - p0) r1, FX = q0 p0 (r1 - r0), quantity = (q1 - q0) p1 r1,
    and the gap between the values and q p r at either end (zero when each value is
    its quantity x price x rate)."""
    if start is not None and start.is_empty():
        start = None
    if end is not None and end.is_empty():
        end = None
    if start is None and end is None:
        return _Split()
    if start is None:
        assert end is not None
        return _Split(quantity=end.value)
    if end is None:
        return _Split(quantity=-start.value)
    r0, r1 = start.rate(), end.rate()
    if r0 is None and r1 is None:
        return _Split(unsplit=end.value - start.value)
    if r0 is None or r1 is None:
        # Priced on one side only (e.g. no quote at the month-end): a change in
        # quantity is still a quantity effect, at the priced side's price and rate;
        # the rest (the unpriced side's value) can't be split.
        if start.quantity is None or end.quantity is None:
            return _Split(unsplit=end.value - start.value)
        priced = end if r1 is not None else start
        rate = r1 if r1 is not None else r0
        assert rate is not None and priced.price is not None
        quantity = (D(end.quantity) - D(start.quantity)) * priced.price * rate
        return _Split(quantity=quantity, unsplit=end.value - start.value - quantity)
    q0, p0 = D(start.quantity), D(start.price)
    q1, p1 = D(end.quantity), D(end.price)
    gap = (end.value - q1 * p1 * r1) - (start.value - q0 * p0 * r0)
    return _Split(price=q0 * (p1 - p0) * r1, fx=q0 * p0 * (r1 - r0), quantity=(q1 - q0) * p1 * r1, gap=gap)


@dataclass
class HoldingChange:
    """One holding (per account) from the start anchor to the end, and its split."""

    key: tuple
    start: Optional[_Holding]
    end: Optional[_Holding]
    split: _Split

    @property
    def held(self) -> _Holding:
        held = self.end or self.start
        assert held is not None
        return held


def holding_changes(start: Mapping[tuple, _Holding], end: Mapping[tuple, _Holding]) -> list[HoldingChange]:
    """Every holding at either anchor, with its change split (``_split``)."""
    return [
        HoldingChange(key, start.get(key), end.get(key), _split(start.get(key), end.get(key)))
        for key in sorted(set(start) | set(end), key=repr)
    ]


@dataclass
class AssetChange:
    """One asset's change across its accounts: what the bridge's movers and trades,
    and the Stocks page's change per holding (#251), are read from. ``unsplit``
    includes the gap (a value that isn't its own quantity x price x rate), so
    end_value - start_value = price + FX + quantity + unsplit."""

    mover_key: tuple
    asset_id: Optional[int]
    symbol: str
    name: Optional[str]
    asset_class: str
    platform: Optional[str]
    start_value: Decimal = ZERO
    end_value: Decimal = ZERO
    price_effect: Decimal = ZERO
    quantity_effect: Decimal = ZERO
    fx_effect: Decimal = ZERO
    unsplit: Decimal = ZERO
    cash_recorded: bool = False
    held_at_start: bool = False
    held_at_end: bool = False
    start_quantity: Optional[Decimal] = None
    end_quantity: Optional[Decimal] = None
    start_price: Optional[Decimal] = None
    end_price: Optional[Decimal] = None
    price_currency: Optional[str] = None
    start_rate: Optional[Decimal] = None
    end_rate: Optional[Decimal] = None

    @property
    def change(self) -> Decimal:
        return self.end_value - self.start_value

    @property
    def market_effect(self) -> Decimal:
        return self.price_effect + self.fx_effect

    @property
    def side(self) -> str:
        """held | new (not held at the start) | sold (held at the start, not at the end)."""
        if self.held_at_start and not self.held_at_end:
            return "sold"
        if self.held_at_end and not self.held_at_start:
            return "new"
        return "held"


def _add_quantity(total: Optional[Decimal], quantity: Optional[Decimal]) -> Optional[Decimal]:
    if quantity is None:
        return total
    return quantity if total is None else total + quantity


def asset_changes(changes: Iterable[HoldingChange], cash_accounts: Iterable[int] = ()) -> Dict[tuple, AssetChange]:
    """The holdings' changes added up per asset (``mover_key``), across accounts."""
    recorded = set(cash_accounts)
    out: Dict[tuple, AssetChange] = {}
    for change in changes:
        h0, h1, split, held = change.start, change.end, change.split, change.held
        asset = out.setdefault(held.mover_key, AssetChange(
            mover_key=held.mover_key,
            asset_id=held.asset_id,
            symbol=held.symbol,
            name=held.name,
            asset_class=held.asset_class,
            platform=held.platform,
        ))
        asset.start_value += h0.value if h0 else ZERO
        asset.end_value += h1.value if h1 else ZERO
        asset.price_effect += split.price
        asset.quantity_effect += split.quantity
        asset.fx_effect += split.fx
        asset.unsplit += split.unsplit + split.gap
        if held.account_id is not None and held.account_id in recorded:
            asset.cash_recorded = True
        if h0 is not None and not h0.is_empty():
            asset.held_at_start = True
            asset.start_quantity = _add_quantity(asset.start_quantity, h0.quantity)
            if asset.start_price is None:
                asset.start_price, asset.start_rate = h0.price, h0.rate()
        if h1 is not None and not h1.is_empty():
            asset.held_at_end = True
            asset.end_quantity = _add_quantity(asset.end_quantity, h1.quantity)
            if asset.end_price is None:
                asset.end_price, asset.end_rate = h1.price, h1.rate()
        if asset.price_currency is None:
            asset.price_currency = (h1.price_currency if h1 else None) or (h0.price_currency if h0 else None)
        if not asset.name and held.name:
            asset.name = held.name
    return out


# ─── Holdings at an anchor ───────────────────────────────────────────────────


def _stock_holdings(
    db: Session, anchor: datetime, base_currency: str, current_user_id: int, *, live: bool
) -> Dict[tuple, _Holding]:
    """Every stock/fund holding (IBKR's too) priced as net worth prices it at this
    anchor (D-21: quotes in a live view, the statement otherwise), per account."""
    rows = canonical_position_rows_by_legacy_account(
        db, current_user_id=current_user_id, anchor_date=anchor.date(), include_nav_accounts=True
    )
    rows = [row for row in rows if str(row.get("asset_class") or "").upper() in STOCK_CLASSES]
    quotes = _latest_prices_for_positions(db, anchor, rows, enabled=live)
    currencies = {_canonical_base_currency(row, base_currency) for row in rows}
    currencies.update(str(q["currency"]).upper() for q in quotes.values() if q.get("currency"))
    currencies.update(str(row["quote_currency"]).upper() for row in rows if row.get("quote_currency"))
    rates = fx.get_rates(anchor, base_currency, currencies) if currencies else {}
    out: Dict[tuple, _Holding] = {}
    for row in rows:
        priced = price_position(row, quotes if live else None, rates, base_currency)
        price_currency = row.get("quote_currency")
        if priced.quote is not None:
            price = priced.quote.get("price")
            price_currency = priced.quote.get("currency") or price_currency
        elif priced.valued_at_cost:
            price = None  # valued at its cost: no market price to split
        else:
            price = row.get("snapshot_market_price")
        fx_rate = rates.get(str(price_currency).upper()) if price_currency else None
        symbol = str(row.get("symbol") or "UNKNOWN")
        asset_key: Any = int(row["asset_id"]) if row.get("asset_id") is not None else symbol.upper()
        account_id = int(row["account_id"]) if row.get("account_id") is not None else None
        key = (account_id, row.get("broker_account_id"), asset_key)
        quantity = D(row["quantity"]) if row.get("quantity") is not None else None
        report_date = _date_only(row.get("report_date"))
        held = out.get(key)
        if held is None:
            out[key] = _Holding(
                mover_key=("STOCK", asset_key),
                asset_id=int(row["asset_id"]) if row.get("asset_id") is not None else None,
                symbol=symbol,
                name=row.get("name"),
                asset_class=str(row.get("asset_class") or "STOCK").upper(),
                platform=row.get("platform"),
                account_id=account_id,
                quantity=quantity,
                price=D(price) if price is not None else None,
                value=priced.value,
                fx_rate=fx_rate,
                price_currency=str(price_currency).upper() if price_currency else None,
                as_of=report_date,
                fallback_reason=priced.fallback_reason,
            )
        else:  # two rows for one holding: add them up (the price stays, the rate follows)
            held.value += priced.value
            held.quantity = None if held.quantity is None or quantity is None else held.quantity + quantity
            if report_date is not None and (held.as_of is None or report_date > held.as_of):
                held.as_of = report_date
    return out


def stock_asset_changes(
    db: Session, current_user_id: int, base_currency: str, start_anchor: datetime, end_anchor: datetime, *, live: bool
) -> Dict[tuple, AssetChange]:
    """Each stock/fund's change from the start anchor (statement prices) to the end
    (quotes when ``live``), split as the bridge splits it: what the Stocks page's
    change per holding reads (#251), so its rows add up to the bridge's stocks parts."""
    stocks0 = _stock_holdings(db, start_anchor, base_currency, current_user_id, live=False)
    stocks1 = _stock_holdings(db, end_anchor, base_currency, current_user_id, live=live)
    return asset_changes(holding_changes(stocks0, stocks1))


def stock_mover_key(asset_id: Any, symbol: Any) -> tuple:
    """The ``mover_key`` of a stock/fund holding row (``_stock_holdings``)."""
    return ("STOCK", int(asset_id) if asset_id is not None else str(symbol or "UNKNOWN").upper())


def _crypto_holdings(
    db: Session, anchor: datetime, base_currency: str, current_user_id: int, *, live: bool
) -> tuple[Dict[tuple, _Holding], Decimal]:
    """Each token across the active wallets (quantity, USD price) at this anchor, from
    the wallet valuation net worth uses; and that valuation's total in base currency."""
    valuation = _wallet_valuation(db, anchor, current_user_id, price_overlay=live)
    usd = D(fx.get_rates(anchor, base_currency, {"USD"}).get("USD"))
    amounts: Dict[str, tuple[Decimal, Decimal]] = {}
    for item in valuation.get("items", []):
        symbol = str(item.get("symbol") or "UNKNOWN").upper()
        quantity, value_usd = amounts.get(symbol, (ZERO, ZERO))
        amounts[symbol] = (
            quantity + (D(item.get("normalized_amount")) if item.get("value_usd") is not None else ZERO),  # #331
            value_usd + D(item.get("value_usd")),
        )
    out: Dict[tuple, _Holding] = {}
    for symbol, (quantity, value_usd) in amounts.items():
        out[("CRYPTO", symbol)] = _Holding(
            mover_key=("CRYPTO", symbol),
            asset_id=None,
            symbol=symbol,
            name=symbol,
            asset_class="CRYPTO",
            platform="CRYPTO",
            account_id=None,
            quantity=quantity if abs(quantity) > _EPS else None,
            price=(value_usd / quantity) if abs(quantity) > _EPS else None,
            value=value_usd * usd,
            fx_rate=usd or None,
            price_currency="USD",
        )
    return out, D(valuation.get("total_usd")) * usd


# ─── Catch-up: starting figures older than the period (#329, D-81) ───────────


def _short_date(day: date) -> str:
    """4 Jul, or 4 Jul 2025 outside ``year``'s calendar year: labels only."""
    return f"{day.day} {day.strftime('%b')}"


def _account_names(db: Session, current_user_id: int) -> Dict[int, str]:
    rows = db.execute(
        text("SELECT a.id, a.name FROM accounts a WHERE " + account_scope_sql("a")),
        {"current_user_id": current_user_id},
    ).all()
    return {int(row[0]): str(row[1] or f"Account {row[0]}") for row in rows}


def _cash_by_account(
    db: Session, anchor: datetime, base_currency: str, current_user_id: int
) -> Dict[int, tuple[Decimal, Optional[date], str]]:
    """Each account's cash balance at the anchor (kind ``balance`` only: an IBKR NAV's
    cash moves with its trades and ledger, which the lines read): value in base, its
    newest as-of date, its kind."""
    out: Dict[int, tuple[Decimal, Optional[date], str]] = {}
    for entry in _cash_positions(db, anchor, base_currency, current_user_id):
        if entry.get("account_id") is None:
            continue
        account_id = int(entry["account_id"])
        value, as_of, kind = out.get(account_id, (ZERO, None, str(entry.get("kind") or "balance")))
        day = _date_only(entry.get("as_of_date"))
        if day is not None and (as_of is None or day > as_of):
            as_of = day
        if str(entry.get("kind") or "balance") != "balance":
            kind = str(entry.get("kind"))
        out[account_id] = (value + D(entry["value"]), as_of, kind)
    return out


def _period_cash_by_account(
    db: Session, current_user_id: int, base_currency: str, start: datetime, end: datetime
) -> Dict[int, Decimal]:
    """Every non-card account's transactions in the period, all types, in base (each at
    its own date's rate, D-30): what moved its balance within the period."""
    rows = [dict(row) for row in _cash_flow_rows(db, start, end, current_user_id)]
    rates = _build_row_rate_map(rows, base_currency)
    out: Dict[int, Decimal] = {}
    for row in rows:
        if str(row.get("account_type") or "").upper() == "CREDIT_CARD":
            continue
        if not _transaction_in_month_window(row["ts"], start, end):
            continue
        account_id = int(row["account_id"])
        out[account_id] = out.get(account_id, ZERO) + D(_row_base_amount(row, base_currency, rates))
    return out


@dataclass
class CatchUp:
    """One account whose starting figure is older than the period: its part of the
    period's change that belongs to earlier months."""

    account_id: int
    kind: str  # cash | holdings
    label: str
    since: date
    until: Optional[date]
    amount: Decimal


def _stale(as_of: Optional[date], period_start: date) -> bool:
    return as_of is not None and (period_start - as_of).days > CATCH_UP_STALE_DAYS


def cash_catch_up(
    db: Session,
    current_user_id: int,
    base_currency: str,
    start: datetime,
    end: datetime,
    *,
    skip_accounts: Iterable[int] = (),
    names: Optional[Mapping[int, str]] = None,
) -> list[CatchUp]:
    """Cash accounts whose starting balance is stale (and has a newer one at the end):
    their change over the period less their own transactions in it."""
    skip = set(skip_accounts)
    start0 = _cash_by_account(db, start, base_currency, current_user_id)
    end1 = _cash_by_account(db, end, base_currency, current_user_id)
    period_rows: Optional[Dict[int, Decimal]] = None
    out: list[CatchUp] = []
    for account_id, (value0, as_of0, kind) in sorted(start0.items()):
        if account_id in skip or kind != "balance" or not _stale(as_of0, start.date()):
            continue
        value1, as_of1, _kind = end1.get(account_id, (value0, as_of0, kind))
        if as_of1 is None or as_of0 is None or as_of1 <= as_of0:
            continue  # no newer balance: nothing from earlier months arrived
        if period_rows is None:
            period_rows = _period_cash_by_account(db, current_user_id, base_currency, start, end)
        amount = (value1 - value0) - period_rows.get(account_id, ZERO)
        name = (names or {}).get(account_id, f"Account {account_id}")
        out.append(CatchUp(
            account_id=account_id,
            kind="cash",
            label=f"{name}: balance of {_short_date(as_of0)} → {_short_date(as_of1)}",
            since=as_of0,
            until=as_of1,
            amount=amount,
        ))
    return out


def stale_holdings_accounts(
    start: Mapping[tuple, _Holding], end: Mapping[tuple, _Holding], period_start: date
) -> Dict[int, tuple[date, Optional[date]]]:
    """Accounts whose holdings at the start come from a statement older than the period
    and that have a newer statement at the end: account -> (start statement, end statement)."""
    def _dates(holdings: Mapping[tuple, _Holding]) -> Dict[int, date]:
        out: Dict[int, date] = {}
        for holding in holdings.values():
            if holding.account_id is None or holding.as_of is None:
                continue
            if holding.account_id not in out or holding.as_of > out[holding.account_id]:
                out[holding.account_id] = holding.as_of
        return out

    first, last = _dates(start), _dates(end)
    return {
        account_id: (as_of0, last.get(account_id))
        for account_id, as_of0 in first.items()
        if _stale(as_of0, period_start) and last.get(account_id) is not None and last[account_id] > as_of0
    }


# ─── Newly tracked: first data in the period (#330, D-82) ────────────────────


@dataclass
class NewlyTracked:
    key: str  # wallet:<id> | cash:<account> | holdings:<account>
    label: str
    first: Optional[date]
    amount: Decimal
    detail: list[tuple[str, Decimal]]  # (token or holding, value in base), largest first


def new_wallets(db: Session, current_user_id: int, period_start: date) -> Dict[str, tuple[str, date]]:
    """Active wallets whose first snapshot is after the period's start: id -> (label, first day)."""
    from app.crypto.valuation import wallet_scope_sql  # local: avoids a cycle at import

    rows = db.execute(
        text(
            """
            SELECT w.id, w.label, w.chain, MIN(s.as_of_date) AS first_day
            FROM crypto_wallets w
            JOIN crypto_wallet_snapshots s ON s.wallet_id = w.id
            WHERE """ + wallet_scope_sql("w") + """
            GROUP BY w.id, w.label, w.chain
            """
        ),
        {"current_user_id": current_user_id},
    ).mappings().all()
    out: Dict[str, tuple[str, date]] = {}
    for row in rows:
        first = _date_only(row["first_day"])
        if first is not None and first > period_start:
            label = str(row["label"] or "").strip() or f"{str(row['chain'] or 'Crypto').capitalize()} wallet"
            out[str(row["id"])] = (label, first)
    return out


def newly_tracked_wallets(
    db: Session, current_user_id: int, base_currency: str, start: datetime, end: datetime, *, live: bool
) -> list[NewlyTracked]:
    """Each wallet first seen in the period, with its value at the end (the end's wallet
    valuation, USD at the end's rate) and its tokens."""
    wallets = new_wallets(db, current_user_id, start.date())
    if not wallets:
        return []
    valuation = _wallet_valuation(db, end, current_user_id, price_overlay=live)
    usd = D(fx.get_rates(end, base_currency, {"USD"}).get("USD"))
    tokens: Dict[str, Dict[str, Decimal]] = {}
    for item in valuation.get("items", []):
        wallet_id = str(item.get("wallet_id"))
        if wallet_id not in wallets:
            continue
        symbol = str(item.get("symbol") or "UNKNOWN").upper()
        per = tokens.setdefault(wallet_id, {})
        per[symbol] = per.get(symbol, ZERO) + D(item.get("value_usd")) * usd
    out = []
    for wallet_id, (label, first) in sorted(wallets.items(), key=lambda kv: kv[1][1]):
        per = tokens.get(wallet_id, {})
        detail = sorted(per.items(), key=lambda kv: -abs(kv[1]))
        out.append(NewlyTracked(f"wallet:{wallet_id}", f"{label}: first seen {_short_date(first)}", first,
                                dsum(per.values()), detail))
    return out


def newly_tracked_cash(
    db: Session,
    current_user_id: int,
    base_currency: str,
    start: datetime,
    end: datetime,
    *,
    skip_accounts: Iterable[int] = (),
    names: Optional[Mapping[int, str]] = None,
) -> list[NewlyTracked]:
    """Cash accounts with no balance at the start and one at the end: that balance less
    their own transactions in the period (those are already in the lines)."""
    skip = set(skip_accounts)
    start0 = _cash_by_account(db, start, base_currency, current_user_id)
    end1 = _cash_by_account(db, end, base_currency, current_user_id)
    fresh = [a for a, (_v, _d, kind) in end1.items() if a not in start0 and a not in skip and kind == "balance"]
    if not fresh:
        return []
    rows = _period_cash_by_account(db, current_user_id, base_currency, start, end)
    out = []
    for account_id in sorted(fresh):
        value, first, _kind = end1[account_id]
        name = (names or {}).get(account_id, f"Account {account_id}")
        label = f"{name}: first balance {_short_date(first)}" if first else f"{name}: first balance"
        out.append(NewlyTracked(f"cash:{account_id}", label, first, value - rows.get(account_id, ZERO), []))
    return out


def newly_tracked_holdings_accounts(start: Mapping[tuple, _Holding], end: Mapping[tuple, _Holding]) -> set[int]:
    """Accounts with holdings at the end and none at the start."""
    before = {h.account_id for h in start.values() if h.account_id is not None and not h.is_empty()}
    return {h.account_id for h in end.values() if h.account_id is not None and h.account_id not in before}


def staking_reward(change: "HoldingChange") -> Decimal:
    """A rebasing staking token's quantity growth (#330): rewards, when held at both ends
    and growing by at most STAKING_MAX_GROWTH; else 0."""
    h0, h1 = change.start, change.end
    if h0 is None or h1 is None or h0.symbol.upper() not in STAKING_REBASING_SYMBOLS:
        return ZERO
    q0, q1 = h0.quantity or ZERO, h1.quantity or ZERO
    if q0 <= _EPS or q1 <= q0 or (q1 - q0) / q0 > STAKING_MAX_GROWTH:
        return ZERO
    return change.split.quantity


# ─── Items: what each part is made of (#332) ─────────────────────────────────


def _unsplit_reason(change: "HoldingChange", period_start: date) -> str:
    h0, h1 = change.start, change.end
    if h0 is not None and h0.rate() is None and (h1 is None or h1.rate() is not None):
        return f"no price at the start ({_short_date(period_start)})" if h0.quantity else "no quantity at the start"
    if h1 is not None and h1.rate() is None:
        return "no price now" if h1.quantity else "no quantity now"
    return "no price or quantity on either side"


def _card_items(
    db: Session,
    current_user_id: int,
    base_currency: str,
    start: datetime,
    end: datetime,
    flows: "_Flows",
    names: Mapping[int, str],
    total: Decimal,
) -> list[Dict[str, Any]]:
    """Each card's share of the card part: what it owes less at the end than at the start,
    less its transactions in the period, and why (#332)."""
    from app.valuation.facts import _credit_card_liability_details  # local: avoids a cycle

    owed0 = {int(c["account_id"]): c for c in _credit_card_liability_details(db, start, base_currency, current_user_id)}
    owed1 = {int(c["account_id"]): c for c in _credit_card_liability_details(db, end, base_currency, current_user_id)}
    last_tx = {
        int(row[0]): _date_only(row[1])
        for row in db.execute(
            text(
                "SELECT t.account_id, MAX(t.ts) FROM transactions t JOIN accounts a ON a.id = t.account_id "
                "WHERE a.account_type = 'CREDIT_CARD' AND " + account_scope_sql("a") + " GROUP BY t.account_id"
            ),
            {"current_user_id": current_user_id},
        ).all()
    }
    rows = []
    for card in sorted(set(owed0) | set(owed1)):
        c0, c1 = owed0.get(card, {}), owed1.get(card, {})
        amount = -(D(c1.get("value")) - D(c0.get("value"))) - flows.card_activity_by_account.get(card, ZERO)
        method = c1.get("method") or c0.get("method")
        if method == "transactions":
            newest = last_tx.get(card)
            reason = "no statement balance: estimated from this month's transactions"
            if newest is not None and newest < start.date():
                reason += f", and its transactions end {_short_date(newest)}"
            reason += ". Enter its statement balance"
        elif method == "running":
            as_of = _date_only(c1.get("as_of_date") or c0.get("as_of_date"))
            reason = f"statement balance of {_short_date(as_of)} plus transactions since" if as_of else "statement balance"
        else:
            reason = str(method or "")
        rows.append(_item(names.get(card, f"Card {card}"), amount, reason, "/liabilities"))
    return _items(rows, total)


def _uncounted_rows(
    db: Session, current_user_id: int, base_currency: str, start: datetime, end: datetime, names: Mapping[int, str]
) -> list[Dict[str, Any]]:
    """Bank transactions in the period that no line counts (transfers, excluded categories):
    with no matching other side, they stay in Other. Per account and category (#332)."""
    rows = [dict(row) for row in _cash_flow_rows(db, start, end, current_user_id)]
    rates = _build_row_rate_map(rows, base_currency)
    in_window = {
        row.get("transaction_id") for row in rows if _transaction_in_month_window(row["ts"], start, end)
    }
    totals: Dict[tuple, Decimal] = {}
    reasons: Dict[tuple, str] = {}
    for row in rows:
        if str(row.get("account_type") or "").upper() in {"CREDIT_CARD", "BROKER"}:
            continue
        if not _transaction_in_month_window(row["ts"], start, end):
            continue
        if _is_dividend_row(row) or _cash_flow_bucket(row) in {"income", "expense"}:
            continue
        # Both sides of a move between the user's own accounts in the period cancel out
        # (#339): not a cause of anything.
        if row.get("own_transfer") == "pair" and row.get("own_transfer_partner_id") in in_window:
            continue
        category = str(row.get("resolved_category") or row.get("type") or "Uncategorized")
        if row.get("own_transfer"):
            partner_day = row.get("own_transfer_partner_day")
            category = "own-account transfer"
            reason = (
                f"between your own accounts; the other side is dated {_short_date(partner_day)}, outside the period"
                if partner_day else
                "between your own accounts; the other account's side isn't uploaded"
            )
        else:
            reason = "not counted as income or spending; no other side recorded in your accounts"
        key = (int(row["account_id"]), category)
        totals[key] = totals.get(key, ZERO) + D(_row_base_amount(row, base_currency, rates))
        reasons[key] = reason
    return [
        _item(f"{names.get(account_id, f'Account {account_id}')}: {category}", amount, reasons[(account_id, category)])
        for (account_id, category), amount in totals.items()
    ]


# ─── Flows in the period ─────────────────────────────────────────────────────


def _is_dividend_row(row: Dict[str, Any]) -> bool:
    """The rows the Dividends page reads from `transactions` (its SQL filter)."""
    code = str(row.get("resolved_category_code") or "").lower()
    category = str(row.get("raw_category") or "").lower()
    return (
        code in {"income_dividends", "taxes_withholding"}
        or "dividend" in category
        or "withholding" in category
        or category == "brokerage::tax"
    )


def _is_interest_row(row: Dict[str, Any]) -> bool:
    code = str(row.get("resolved_category_code") or "").lower()
    categories = f"{row.get('raw_category') or ''} {row.get('resolved_category') or ''}".lower()
    return code == "income_interest" or "interest" in categories


def _ledger_window_dates(start: datetime, end: datetime) -> tuple[date, date]:
    """[first, last) dates of date-only flows in the period, by the same rule as
    ``_card_transaction_in_window``: from the start anchor's date, before a date
    anchor's date, or through today for a live end."""
    first = start.date()
    last = end.date() if _is_snapshot_anchor(end) else _local_date(end) + timedelta(days=1)
    return first, last


def _ledger_rows(db: Session, current_user_id: int, first: date, last: date) -> list[Dict[str, Any]]:
    """Broker cash ledger lines (IBKR Flex Statement of Funds) for dividends,
    withholding, interest and deposits/withdrawals with an activity date in [first, last)."""
    codes = sorted(LEDGER_CODES | LEDGER_INTEREST_CODES | LEDGER_DEPOSIT_CODES)
    params: Dict[str, Any] = {f"code{i}": code for i, code in enumerate(codes)}
    rows = db.execute(
        text(
            f"""
            SELECT l.id, l.activity_date, l.amount, l.currency,
                   UPPER(COALESCE(l.activity_code, '')) AS code,
                   ba.legacy_account_id AS account_id
            FROM portfolio_cash_ledger_entries l
            JOIN broker_accounts ba ON ba.id = l.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE l.activity_date >= :first AND l.activity_date < :last
              AND UPPER(COALESCE(l.activity_code, '')) IN ({", ".join(f":{key}" for key in params)})
              AND """
            + account_scope_sql("acc")
            + """
            ORDER BY l.activity_date, l.id
            """
        ),
        {**params, "first": first, "last": last, "current_user_id": current_user_id},
    ).mappings().all()
    return [dict(row) for row in rows]


def _linked_transaction_ids(db: Session, current_user_id: int, ids: Iterable[int]) -> set[int]:
    """Of ``ids``, those in a transfer link whose two sides are both the user's."""
    wanted = sorted({int(i) for i in ids})
    if not wanted:
        return set()
    params: Dict[str, Any] = {f"t{i}": tid for i, tid in enumerate(wanted)}
    placeholders = ", ".join(f":{key}" for key in params)
    rows = db.execute(
        text(
            f"""
            SELECT tl.from_transaction_id, tl.to_transaction_id
            FROM transfer_links tl
            JOIN transactions tf ON tf.id = tl.from_transaction_id
            JOIN accounts af ON af.id = tf.account_id
            JOIN transactions tt ON tt.id = tl.to_transaction_id
            JOIN accounts at2 ON at2.id = tt.account_id
            WHERE (tl.from_transaction_id IN ({placeholders}) OR tl.to_transaction_id IN ({placeholders}))
              AND """
            + account_scope_sql("af")
            + " AND "
            + account_scope_sql("at2")
        ),
        {**params, "current_user_id": current_user_id},
    ).mappings().all()
    linked = {int(row["from_transaction_id"]) for row in rows} | {int(row["to_transaction_id"]) for row in rows}
    return linked & set(wanted)


@dataclass
class _Flows:
    income: Decimal = ZERO  # Cash flow's income, without dividends and interest
    spending: Decimal = ZERO  # Cash flow's expenses (positive)
    dividends: Decimal = ZERO  # net of withholding, as the Dividends page
    interest: Decimal = ZERO
    new_money_in: Decimal = ZERO
    new_money_out: Decimal = ZERO  # negative
    internal_moves: Decimal = ZERO  # deposits into brokers from your own accounts (not counted)
    internal_count: int = 0
    card_activity: Decimal = ZERO  # every card transaction a card's liability counts
    card_activity_by_account: Dict[int, Decimal] = field(default_factory=dict)  # the same, per card (#332)
    transaction_count: int = 0


def _flows(
    db: Session, current_user_id: int, base_currency: str, start: datetime, end: datetime, ledger_accounts: set[int]
) -> _Flows:
    out = _Flows()
    slack = timedelta(days=TRANSFER_MATCH_DAYS)
    # The Cash flow page's rows (its classification, D-30 rates), over the period plus
    # a few days either side to find the other side of a transfer.
    rows = [dict(row) for row in _cash_flow_rows(db, start - slack, end + slack, current_user_id)]
    rates_by_date = _build_row_rate_map(rows, base_currency)
    in_period = [row for row in rows if _transaction_in_month_window(row["ts"], start, end)]
    covered = ledger_covered_since(db, current_user_id)
    out.transaction_count = len(in_period)

    for row in in_period:
        amount = D(_row_base_amount(row, base_currency, rates_by_date))
        if str(row.get("account_type") or "").upper() == "CREDIT_CARD" and str(row["type"]).upper() in CARD_LIABILITY_TYPES:
            out.card_activity += amount
            card = int(row["account_id"])
            out.card_activity_by_account[card] = out.card_activity_by_account.get(card, ZERO) + amount
        if _is_dividend_row(row):
            # The Dividends page's rule: a ledger-covered account's dividends come
            # from the ledger, so its transaction rows are skipped, not counted twice.
            if not _covered_by_ledger(row, covered):
                out.dividends += amount
            continue
        bucket = _cash_flow_bucket(row)
        if bucket == "income":
            if _is_interest_row(row):
                out.interest += amount
            else:
                out.income += amount
        elif bucket == "expense":
            out.spending += -amount

    # A card payment seen only on the paying bank account (#308) lowers the card's liability
    # like a payment in the card's own file, so it is card activity too (the bank row itself
    # is a move between the user's accounts, not spending).
    from app.valuation.card_payments import missing_bank_payments

    for payment in missing_bank_payments(db, current_user_id):
        day_ts = datetime.combine(payment.day, datetime.min.time(), tzinfo=timezone.utc)
        if not _transaction_in_month_window(day_ts, start, end):
            continue
        rates: Mapping[str, Decimal] = fx.get_rates_by_date([payment.day], base_currency, {payment.currency}).get(
            fx.rate_date(payment.day), {}
        )
        paid = D(payment.amount) * D(rates.get(payment.currency))
        out.card_activity += paid
        out.card_activity_by_account[payment.card_account_id] = (
            out.card_activity_by_account.get(payment.card_account_id, ZERO) + paid
        )

    first, last = _ledger_window_dates(start, end)
    ledger = _ledger_rows(db, current_user_id, first, last)
    ledger_rates: Mapping[date, Mapping[str, Decimal]] = fx.get_rates_by_date(
        [row["activity_date"] for row in ledger], base_currency, {str(row["currency"]).upper() for row in ledger}
    ) if ledger else {}

    def _ledger_base(row: Dict[str, Any]) -> Decimal:
        rates: Mapping[str, Decimal] = ledger_rates.get(fx.rate_date(row["activity_date"]), {})
        return D(row["amount"]) * D(rates.get(str(row["currency"]).upper()))

    # Money into or out of a broker: the ledger's deposits/withdrawals, and TRANSFER
    # rows on broker accounts the ledger doesn't cover.
    candidates: list[Dict[str, Any]] = []
    for row in ledger:
        code = row["code"]
        if code in LEDGER_CODES:
            out.dividends += _ledger_base(row)
        elif code in LEDGER_INTEREST_CODES:
            out.interest += _ledger_base(row)
        elif code in LEDGER_DEPOSIT_CODES:
            candidates.append({
                "transaction_id": None,
                "account_id": int(row["account_id"]),
                "currency": str(row["currency"]).upper(),
                "amount": D(row["amount"]),
                "day": _date_only(row["activity_date"]),
                "base": _ledger_base(row),
            })
    for row in in_period:
        if str(row["type"]).upper() != "TRANSFER" or str(row.get("account_type") or "").upper() != "BROKER":
            continue
        if int(row["account_id"]) in ledger_accounts:
            continue
        candidates.append({
            "transaction_id": int(row["transaction_id"]),
            "account_id": int(row["account_id"]),
            "currency": str(row["currency"] or base_currency).upper(),
            "amount": D(row["amount"]),
            "day": clock._transaction_date(row["ts"]),
            "base": D(_row_base_amount(row, base_currency, rates_by_date)),
        })

    linked = _linked_transaction_ids(db, current_user_id, [c["transaction_id"] for c in candidates if c["transaction_id"]])
    pool = [row for row in rows if str(row["type"]).upper() == "TRANSFER"]
    used: set[int] = set()
    for candidate in candidates:
        internal = candidate["transaction_id"] in linked
        if not internal:
            for row in pool:
                tid = int(row["transaction_id"])
                if tid in used or tid == candidate["transaction_id"] or int(row["account_id"]) == candidate["account_id"]:
                    continue
                if str(row["currency"] or base_currency).upper() != candidate["currency"]:
                    continue
                if abs(D(row["amount"]) + candidate["amount"]) > TRANSFER_MATCH_TOLERANCE:
                    continue
                day = clock._transaction_date(row["ts"])
                if candidate["day"] is None or abs((day - candidate["day"]).days) > TRANSFER_MATCH_DAYS:
                    continue
                used.add(tid)
                internal = True
                break
        if internal:
            out.internal_moves += candidate["base"]
            out.internal_count += 1
        elif candidate["base"] >= 0:
            out.new_money_in += candidate["base"]
        else:
            out.new_money_out += candidate["base"]
    return out


# ─── The bridge ──────────────────────────────────────────────────────────────


def _part(key: str, label: str, amount: Decimal, items: Optional[list[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return {"key": key, "label": label, "amount": amount, "items": items or []}


def _item(label: str, amount: Optional[Decimal], reason: Optional[str] = None, link: Optional[str] = None) -> Dict[str, Any]:
    return {"label": label, "amount": amount, "reason": reason, "link": link}


def _items(rows: Iterable[Dict[str, Any]], total: Optional[Decimal] = None, rest: str = "Rest") -> list[Dict[str, Any]]:
    """Items largest first, at most ITEMS_MAX, those under ITEM_MIN left out; with
    ``total``, a last item for whatever the listed ones don't cover, so they add up to it."""
    kept = sorted(
        (row for row in rows if row["amount"] is None or abs(row["amount"]) >= ITEM_MIN),
        key=lambda row: -abs(row["amount"] or ZERO),
    )[:ITEMS_MAX]
    if total is not None:
        left = total - sum(row["amount"] or ZERO for row in kept)
        if abs(left) >= ITEM_MIN:
            kept.append(_item(rest, left))
    return kept


def _note(key: str, label: str, amount: Optional[Decimal] = None) -> Dict[str, Any]:
    return {"key": key, "label": label, "amount": amount}


def _add_realised_note(
    lines: list[Dict[str, Any]],
    db: Session,
    current_user_id: int,
    base_currency: str,
    start_anchor: datetime,
    end_anchor: datetime,
) -> None:
    """Markets' realised/unrealised split (#293, D-78), as a note so the line's total is
    unchanged: Markets is price moves on what's held across the period (unrealised); a
    sale's gain vs its cost is a different measure, named here with its amount."""
    from app.portfolio.realised import realised_summary  # local: avoids a cycle via pages

    first = start_anchor.date()
    last = end_anchor.date() if end_anchor.date() == first else (end_anchor - timedelta(microseconds=1)).date()
    summary = realised_summary(db, current_user_id, base_currency, first, last)
    month = summary["month"]
    if not month["sales"]:
        return
    for line in lines:
        if line["key"] != "markets":
            continue
        for part in line.get("parts") or []:
            if part["key"] == "stocks":
                part["label"] = "Stocks & funds: price moves on what you hold (unrealised)"
        label = f"Realised on {month['sales']} sale(s), vs their cost"
        if month["cost_unknown"]:
            label += f"; {month['cost_unknown']} with no known cost left out"
        if month["fx_missing_currencies"]:
            label += f"; no rate for {', '.join(month['fx_missing_currencies'])}: left out"
        line.setdefault("notes", []).append(_note("realised", label, month["realised"]))


def _line(
    key: str,
    label: str,
    amount: Decimal,
    *,
    status: str = "ok",
    reason: Optional[str] = None,
    parts: Optional[list[Dict[str, Any]]] = None,
    notes: Optional[list[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "amount": amount,
        "status": status,
        "reason": reason,
        "parts": parts or [],
        "notes": notes or [],
    }


def _platform_list(platforms: Iterable[Optional[str]]) -> str:
    return ", ".join(sorted({_platform_label(p) for p in platforms}))


def _platform_label(platform: Optional[str]) -> str:
    """DBS_VICKERS -> "DBS Vickers" (a short all-caps word stays a code)."""
    words = [w for w in str(platform or "").replace("-", "_").split("_") if w]
    if not words:
        return "Unknown"
    return " ".join(w.upper() if (w.isupper() and len(w) <= 4) or w.upper() in {"IBKR", "HSBC", "OCBC", "POSB"} else w.capitalize() for w in words)


def _cash_fx(
    db: Session, current_user_id: int, base_currency: str, start: datetime, end: datetime
) -> Decimal:
    """The start's foreign-currency cash revalued from the start's rates to the end's."""
    by_currency: Dict[str, Decimal] = {}
    for entry in _cash_positions(db, start, base_currency, current_user_id):
        by_currency[entry["currency"]] = by_currency.get(entry["currency"], ZERO) + D(entry["value"])
    foreign = {c for c in by_currency if c != base_currency.upper()}
    if not foreign:
        return ZERO
    r0 = fx.get_rates(start, base_currency, foreign)
    r1 = fx.get_rates(end, base_currency, foreign)
    total = ZERO
    for currency in foreign:
        a, b = r0.get(currency, ZERO), r1.get(currency, ZERO)
        if a > 0 and b > 0:
            total += by_currency[currency] * (D(b) / D(a) - ONE)
    return total


def _not_updated(db: Session, current_user_id: int, base_currency: str, end: datetime, since: date) -> list[str]:
    """Sources whose newest data at the end is from the start or earlier: they can't
    show any of the period's change."""
    newest: Dict[str, date] = {}

    def _see(label: str, value: Any) -> None:
        day = _date_only(value)
        if day is not None and (label not in newest or day > newest[label]):
            newest[label] = day

    for entry in _cash_positions(db, end, base_currency, current_user_id):
        _see(_platform_label(entry.get("platform")), entry.get("as_of_date"))
    rows = canonical_position_rows_by_legacy_account(
        db, current_user_id=current_user_id, anchor_date=end.date(), include_nav_accounts=True
    )
    for row in rows:
        _see(_platform_label(row.get("platform")), row.get("report_date"))
    return sorted(label for label, day in newest.items() if day <= since)


@float_edge
def month_bridge(
    db: Session, current_user_id: int, month: str, month_start: datetime, base_currency: str, movers_limit: int = 3
) -> Dict[str, Any]:
    end_anchor, is_live = _month_view_anchor(month_start)
    start_month = _month_view_compare_month_start(month_start)
    start_anchor = _anchor_ts(start_month)
    base_currency = base_currency.upper()

    start_nw = _networth_components(db, start_anchor, base_currency, current_user_id)
    end_nw = _networth_components(db, end_anchor, base_currency, current_user_id, price_overlay=is_live)
    start_as_of = _effective_as_of(db, start_anchor, current_user_id)
    end_as_of = _effective_as_of(db, end_anchor, current_user_id)

    # Holdings: each one's change split into price, FX and quantity.
    stocks0 = _stock_holdings(db, start_anchor, base_currency, current_user_id, live=False)
    stocks1 = _stock_holdings(db, end_anchor, base_currency, current_user_id, live=is_live)
    crypto0, crypto_total0 = _crypto_holdings(db, start_anchor, base_currency, current_user_id, live=False)
    crypto1, crypto_total1 = _crypto_holdings(db, end_anchor, base_currency, current_user_id, live=is_live)

    # Accounts whose cash is recorded (an IBKR NAV, or a cash balance at either end):
    # a trade there is a move between the holding and its cash, not a cause.
    cash_accounts = {
        int(entry["account_id"])
        for anchor in (start_anchor, end_anchor)
        for entry in _cash_positions(db, anchor, base_currency, current_user_id)
        if entry.get("account_id") is not None
    }
    ledger_accounts = set(ledger_covered_since(db, current_user_id))

    stock_price = stock_fx = ZERO
    untracked_trades = ZERO
    untracked_platforms: set[Optional[str]] = set()
    unsplit = ZERO
    unsplit_count = 0
    valuation_gap = ZERO

    # Holdings statements older than the period (#329): their quantity changes up to the
    # newer statement are catch-up, not this period's untracked trades.
    stale_holdings = stale_holdings_accounts(stocks0, stocks1, start_anchor.date())
    holdings_catch_up: Dict[int, Decimal] = {}
    # Accounts whose first holdings statement falls in the period (#330): new to the app.
    new_holdings_accounts = newly_tracked_holdings_accounts(stocks0, stocks1)
    holdings_new: Dict[int, list[tuple[str, Decimal]]] = {}
    # What each Unexplained part is made of (#332).
    catch_up_rows: Dict[int, list[Dict[str, Any]]] = {}
    untracked_rows: list[Dict[str, Any]] = []
    unsplit_rows: list[Dict[str, Any]] = []
    gap_rows: list[Dict[str, Any]] = []
    moved_rows: list[Dict[str, Any]] = []

    stock_changes = holding_changes(stocks0, stocks1)
    for holding in stock_changes:
        split, held = holding.split, holding.held
        stock_price += split.price
        stock_fx += split.fx
        valuation_gap += split.gap
        if split.gap:
            gap_rows.append(_item(f"{held.symbol} ({_platform_label(held.platform)})", split.gap,
                                  "statement value differs from quantity × price × rate"))
        if split.unsplit:
            unsplit += split.unsplit
            unsplit_count += int(abs(split.unsplit) >= UNSPLIT_COUNT_MIN)
            unsplit_rows.append(_item(f"{held.symbol} ({_platform_label(held.platform)})", split.unsplit,
                                      _unsplit_reason(holding, start_anchor.date())))
        if split.quantity and (held.account_id is None or held.account_id not in cash_accounts):
            side = "bought" if split.quantity > 0 else "sold"
            if held.account_id is not None and held.account_id in new_holdings_accounts:
                holdings_new.setdefault(held.account_id, []).append((held.symbol, split.quantity))
            elif held.account_id is not None and held.account_id in stale_holdings:
                holdings_catch_up[held.account_id] = holdings_catch_up.get(held.account_id, ZERO) + split.quantity
                catch_up_rows.setdefault(held.account_id, []).append(_item(held.symbol, split.quantity, side))
            else:
                untracked_trades += split.quantity
                untracked_platforms.add(held.platform)
                untracked_rows.append(_item(f"{held.symbol} ({_platform_label(held.platform)})", split.quantity,
                                            f"{side}; no cash record at {_platform_label(held.platform)}"))

    crypto_price = crypto_fx = crypto_moved = ZERO
    staking = ZERO
    staking_symbols: set[str] = set()
    crypto_changes = holding_changes(crypto0, crypto1)
    for holding in crypto_changes:
        split = holding.split
        crypto_price += split.price
        crypto_fx += split.fx
        reward = staking_reward(holding)
        if reward:
            staking += reward
            staking_symbols.add(holding.held.symbol)
        crypto_moved += split.quantity - reward
        valuation_gap += split.gap
        if split.unsplit:
            unsplit += split.unsplit
            unsplit_count += int(abs(split.unsplit) >= UNSPLIT_COUNT_MIN)
            unsplit_rows.append(_item(holding.held.symbol, split.unsplit, _unsplit_reason(holding, start_anchor.date())))
        if split.quantity - reward:
            moved_rows.append(_item(holding.held.symbol, split.quantity - reward,
                                    "more held" if split.quantity - reward > 0 else "less held"))

    # What the statement totals hold beyond the holdings split above (e.g. an IBKR
    # NAV's other asset types), at either end.
    holdings_gap = (
        (end_nw["stocks_funds"] - start_nw["stocks_funds"])
        - (sum(h.value for h in stocks1.values()) - sum(h.value for h in stocks0.values()))
        + (end_nw["crypto"] - start_nw["crypto"])
        - (crypto_total1 - crypto_total0)
    )

    cash_fx = _cash_fx(db, current_user_id, base_currency, start_anchor, end_anchor)
    flows = _flows(db, current_user_id, base_currency, start_anchor, end_anchor, ledger_accounts)

    # Brokers whose money in and out isn't recorded anywhere.
    no_cash_record = sorted(
        {_platform_label(h.platform) for h in (*stocks0.values(), *stocks1.values())
         if h.account_id is None or h.account_id not in cash_accounts}
    )

    period = "month to date" if is_live else "this month"
    lines: list[Dict[str, Any]] = []

    new_money = flows.new_money_in + flows.new_money_out
    new_money_notes = []
    if flows.internal_count:
        new_money_notes.append(_note(
            "internal_transfers",
            f"{flows.internal_count} transfer(s) from your own accounts to a broker: not new money",
            flows.internal_moves,
        ))
    lines.append(_line(
        "new_money",
        "New money in",
        new_money,
        status="partial" if no_cash_record else "ok",
        reason=(
            f"No cash record for {', '.join(no_cash_record)}: money paid in or taken out there is in Unexplained"
            if no_cash_record else None
        ),
        parts=[_part("deposits", "Deposits", flows.new_money_in), _part("withdrawals", "Withdrawals", flows.new_money_out)],
        notes=new_money_notes,
    ))

    lines.append(_line(
        "markets",
        "Markets",
        stock_price + crypto_price,
        status="partial" if unsplit_count else "ok",
        reason=(
            f"{unsplit_count} holding(s) without a price or quantity: their change is in Unexplained"
            if unsplit_count else None
        ),
        parts=[_part("stocks", "Stocks & funds", stock_price), _part("crypto", "Crypto", crypto_price)],
    ))

    fx_flags = fx.fx_status()
    lines.append(_line(
        "fx",
        "FX",
        stock_fx + crypto_fx + cash_fx,
        status="partial" if fx_flags.get("fx_incomplete") else "ok",
        reason=(
            f"No exchange rate for {', '.join(fx_flags.get('fx_missing_currencies') or [])}: left out (never 1.0)"
            if fx_flags.get("fx_incomplete") else None
        ),
        parts=[
            _part("stocks", "Stocks & funds", stock_fx),
            _part("crypto", "Crypto (USD)", crypto_fx),
            _part("cash", "Foreign-currency cash", cash_fx),
        ],
    ))

    income_parts = [_part("dividends", "Dividends (net of withholding)", flows.dividends), _part("interest", "Interest", flows.interest)]
    if abs(staking) >= 0.005:
        income_parts.append(_part("staking", f"Staking rewards ({', '.join(sorted(staking_symbols))})", staking))
    lines.append(_line(
        "dividends_interest",
        "Dividends, interest & staking" if abs(staking) >= 0.005 else "Dividends & interest",
        flows.dividends + flows.interest + staking,
        parts=income_parts,
    ))

    lines.append(_line(
        "cash_kept",
        "Cash kept",
        flows.income - flows.spending,
        status="ok" if flows.transaction_count else "unavailable",
        reason=None if flows.transaction_count else f"No transactions imported for {period}",
        parts=[_part("income", "Income", flows.income), _part("spending", "Spending", -flows.spending)],
    ))

    names = _account_names(db, current_user_id)
    catch_ups = cash_catch_up(
        db, current_user_id, base_currency, start_anchor, end_anchor,
        skip_accounts=ledger_accounts, names=names,
    )
    for account_id, amount in sorted(holdings_catch_up.items()):
        since, until = stale_holdings[account_id]
        name = names.get(account_id, f"Account {account_id}")
        catch_ups.append(CatchUp(
            account_id=account_id,
            kind="holdings",
            label=f"{name}: bought or sold between the {_short_date(since)} and "
                  f"{_short_date(until) if until else 'newest'} statements",
            since=since,
            until=until,
            amount=amount,
        ))
    if catch_ups:
        lines.append(_line(
            "catch_up",
            "Catch-up since last statement",
            dsum(c.amount for c in catch_ups),
            reason=(
                "These accounts' starting figures are older than this period, so their newer data "
                "also covers earlier months: that part is here, not in this period's lines"
            ),
            parts=[
                _part(
                    f"{c.kind}:{c.account_id}", c.label, c.amount,
                    _items(catch_up_rows.get(c.account_id, []), c.amount) if c.kind == "holdings" else [],
                )
                for c in catch_ups
            ],
        ))

    newly: list[NewlyTracked] = newly_tracked_wallets(
        db, current_user_id, base_currency, start_anchor, end_anchor, live=is_live
    )
    crypto_moved -= dsum(n.amount for n in newly)
    if newly:
        moved_rows.append(_item("In newly tracked wallets", -dsum(n.amount for n in newly), "on the Newly tracked line"))
    newly += newly_tracked_cash(
        db, current_user_id, base_currency, start_anchor, end_anchor, skip_accounts=ledger_accounts, names=names,
    )
    for account_id, held_rows in sorted(holdings_new.items()):
        name = names.get(account_id, f"Account {account_id}")
        first = max((h.as_of for h in stocks1.values() if h.account_id == account_id and h.as_of), default=None)
        newly.append(NewlyTracked(
            f"holdings:{account_id}",
            f"{name}: first statement {_short_date(first)}" if first else f"{name}: first statement",
            first,
            dsum(amount for _symbol, amount in held_rows),
            sorted(held_rows, key=lambda kv: -abs(kv[1])),
        ))
    if newly:
        lines.append(_line(
            "newly_tracked",
            "Newly tracked",
            dsum(n.amount for n in newly),
            reason="Wallets and accounts first added in this period: their balance is new to the app, not money in or out",
            parts=[
                _part(n.key, n.label, n.amount, _items((_item(symbol, value) for symbol, value in n.detail), n.amount))
                for n in newly
            ],
        ))

    change = end_nw["total"] - start_nw["total"]
    explained = sum(line["amount"] for line in lines)
    residual = change - explained

    liabilities_change = end_nw["liabilities"] - start_nw["liabilities"]
    card_balances = -liabilities_change - flows.card_activity
    if abs(holdings_gap) >= ITEM_MIN:
        gap_rows.append(_item(
            "Statement totals beyond the holdings listed", holdings_gap,
            "e.g. an IBKR statement's accrued interest and dividends, which aren't holdings",
        ))
    parts = [
        _part(
            "untracked_trades",
            f"Bought or sold with no cash record ({_platform_list(untracked_platforms)})"
            if untracked_platforms else "Bought or sold with no cash record",
            untracked_trades,
            _items(untracked_rows, untracked_trades),
        ),
        _part("crypto_moved", "Crypto moved into or out of wallets", crypto_moved, _items(moved_rows, crypto_moved)),
        _part(
            "card_balances", "Card balances not matched by card transactions", card_balances,
            _card_items(db, current_user_id, base_currency, start_anchor, end_anchor, flows, names, card_balances),
        ),
        _part("holdings_unsplit", "Holdings without a price or quantity", unsplit, _items(unsplit_rows, unsplit)),
        _part(
            "statement_gap", "Statement values that differ from quantity x price x rate", valuation_gap + holdings_gap,
            _items(gap_rows, valuation_gap + holdings_gap),
        ),
    ]
    parts = [p for p in parts if abs(p["amount"]) >= 0.005]
    other = residual - sum(p["amount"] for p in parts)
    parts.append(_part(
        "other",
        "Other: balances and transactions on different dates, transfers with one side recorded, fees",
        other,
        _items(
            _uncounted_rows(db, current_user_id, base_currency, start_anchor, end_anchor, names),
            other,
            rest="Rest: balances and flows on different dates (e.g. a broker's cash vs its recorded flows)",
        ),
    ))
    notes = []
    stale = _not_updated(db, current_user_id, base_currency, end_anchor, start_anchor.date())
    if stale:
        notes.append(_note("not_updated", f"No data after {start_anchor.date().isoformat()}: {', '.join(stale)}"))
    unexplained = _line(
        "unexplained",
        "Unexplained",
        residual,
        reason="What the lines above can't account for; its known parts are listed",
        parts=parts,
        notes=notes,
    )

    # Movers rank what the market did to each holding (price + FX). Buying or selling
    # isn't a gain or a loss (a sale where the cash is recorded moves the money to cash),
    # so a change in quantity is listed apart, under trades.
    mover_rows: list[Dict[str, Any]] = []
    trade_rows: list[Dict[str, Any]] = []
    for asset in asset_changes([*stock_changes, *crypto_changes], cash_accounts).values():
        mover: Dict[str, Any] = {
            "asset_id": asset.asset_id,
            "symbol": asset.symbol,
            "name": asset.name,
            "asset_class": asset.asset_class,
            "start_value": asset.start_value,
            "end_value": asset.end_value,
            "price_effect": asset.price_effect,
            "quantity_effect": asset.quantity_effect,
            "fx_effect": asset.fx_effect,
            "change": asset.change,
        }
        quantity = asset.quantity_effect
        if abs(quantity) >= TRADE_MIN:
            crypto = asset.asset_class == "CRYPTO"
            trade_rows.append({
                "asset_id": asset.asset_id,
                "symbol": asset.symbol,
                "name": asset.name,
                "asset_class": asset.asset_class,
                "amount": quantity,
                "side": ("moved_in" if quantity > 0 else "moved_out") if crypto else ("bought" if quantity > 0 else "sold"),
                "cash_recorded": asset.cash_recorded,
            })
        market = asset.market_effect
        mover["market_effect"] = market
        if abs(market) < 0.005 and abs(asset.unsplit) < 0.005:
            continue
        effects = {"price": asset.price_effect, "fx": asset.fx_effect}
        dominant = max(effects, key=lambda name: abs(effects[name]))
        mover["cause"] = "unknown" if abs(asset.unsplit) > abs(market) else dominant
        mover["_rank"] = max(abs(market), abs(asset.unsplit))
        mover_rows.append(mover)
    mover_rows.sort(key=lambda m: (-m["_rank"], str(m["symbol"]).lower()))
    for mover in mover_rows:
        mover.pop("_rank")
    trade_rows.sort(key=lambda t: (-abs(t["amount"]), str(t["symbol"]).lower()))

    end_month = month_start if is_live else _completed_snapshot_month_start(month_start)
    causes = move_causes.move_causes(
        db,
        current_user_id,
        base_currency=base_currency,
        start_anchor=start_anchor,
        end_anchor=end_anchor,
        start_total=start_nw["total"],
        end_total=end_nw["total"],
        start_holdings=[*stocks0.values(), *crypto0.values()],
        end_holdings=[*stocks1.values(), *crypto1.values()],
        fx_flags=fx.fx_status(),
        baseline_missing=baseline_missing(start_as_of, start_nw["total"]),
    )
    _add_realised_note(lines, db, current_user_id, base_currency, start_anchor, end_anchor)
    return {
        "as_of_month": month,
        "base_currency": base_currency,
        "snapshot_day": _configured_snapshot_day(),
        "is_live": is_live,
        "period_start": start_anchor.date().isoformat(),
        "period_end": end_anchor.isoformat(),
        "start": {
            "month": start_month.strftime("%Y-%m"),
            "boundary_at": start_anchor.isoformat(),
            "as_of": _iso_value(start_as_of),
            "value": start_nw["total"],
            "net_worth": _serialize_net_worth(start_nw),
            "baseline_missing": baseline_missing(start_as_of, start_nw["total"]),
        },
        "end": {
            "month": end_month.strftime("%Y-%m"),
            "boundary_at": end_anchor.isoformat(),
            "as_of": _iso_value(end_as_of),
            "value": end_nw["total"],
            "net_worth": _serialize_net_worth(end_nw),
            "baseline_missing": False,
        },
        "change": change,
        "lines": lines,
        "unexplained": unexplained,
        "liabilities_change": liabilities_change,
        "movers": mover_rows[:movers_limit],
        "trades": trade_rows[:movers_limit],
        "move_causes": causes,
        **fx.fx_status(),
    }
