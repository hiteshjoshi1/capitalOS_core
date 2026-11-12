"""Inbox items about the money itself, not the data plumbing (#410, UX U29, D-114).

Four checks, each cheap and each with one action:
- **month_closed_stale**: the latest completed month closed while a source's newest data
  was stale for it (History's per-month freshness, D-29). Its figures are partly carried.
- **concentration**: the largest single holding is above CONCENTRATION_PCT of net worth
  (Risk's top holdings, live for the open month).
- **unusual_move**: the latest completed month's net-worth change is far outside the
  usual: at least UNUSUAL_MOVE_FACTOR times the median monthly change of the year before
  it, and at least UNUSUAL_MOVE_MIN_PCT of the month's starting net worth.
- **recurring_new** / **recurring_up**: a card charge that repeats monthly and first
  appeared within the last two months, or one this month above its usual amount by at
  least RECURRING_UP_PCT (and RECURRING_UP_MIN in base currency).

Thresholds are module constants, overridable by the environment variables of the same
name (``INBOX_<NAME>``); none are stored per user yet.
"""
from __future__ import annotations

import os
from datetime import datetime
from statistics import median
from typing import Any, Callable, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser
from app.schemas.inbox import InboxAction, InboxItem


def _env_number(name: str, default: float) -> float:
    try:
        return float(os.getenv(f"INBOX_{name}", ""))
    except ValueError:
        return default


CONCENTRATION_PCT = _env_number("CONCENTRATION_PCT", 25.0)
UNUSUAL_MOVE_FACTOR = _env_number("UNUSUAL_MOVE_FACTOR", 3.0)
UNUSUAL_MOVE_MIN_PCT = _env_number("UNUSUAL_MOVE_MIN_PCT", 5.0)
UNUSUAL_MOVE_HISTORY = 12  # months of changes the "usual" is taken from (at least 3 needed)
RECURRING_NEW_MONTHS = 2
RECURRING_UP_PCT = _env_number("RECURRING_UP_PCT", 25.0)
RECURRING_UP_MIN = _env_number("RECURRING_UP_MIN", 10.0)
RECURRING_MIN = 5.0  # charges below this (base currency) are never alerted


def _money(amount: float, currency: str) -> str:
    prefix = {"SGD": "S$ ", "USD": "US$ "}.get(currency.upper(), f"{currency.upper()} ")
    return f"{'-' if amount < 0 else ''}{prefix}{abs(amount):,.0f}"


def _open_month() -> str:
    from app.valuation.clock import _app_today

    return _app_today().strftime("%Y-%m")


def _month_start(month: str) -> datetime:
    from app.valuation.clock import _parse_month

    return _parse_month(month)


def _month_name(month: str) -> str:
    return datetime.strptime(month + "-01", "%Y-%m-%d").strftime("%b %Y")


def month_closed_items(db: Session, user: CurrentUser, base: str) -> list[InboxItem]:
    from app.valuation.clock import _anchor_ts, _current_anchor_ts, _latest_completed_month_start
    from app.valuation.history import _wealth_rollup_row

    month_start = _latest_completed_month_start(_current_anchor_ts())
    month = month_start.strftime("%Y-%m")
    row = _wealth_rollup_row(db, _anchor_ts(month_start), base, user.id)
    stale = [e for e in row["source_freshness"] if e.get("status") in ("stale", "missing")]
    if not stale:
        return []
    names = ", ".join(
        f"{_platform(e['platform'])} ({datetime.fromisoformat(e['as_of']).strftime('%-d %b')})" for e in stale[:4]
    ) + (f" and {len(stale) - 4} more" if len(stale) > 4 else "")
    return [InboxItem(
        id=f"month_closed_stale:{month}",
        kind="month_closed_stale",
        severity="medium",
        title=f"{_month_name(month)} closed with stale data",
        detail=f"Newest data from {names}: that month's figures carry older balances. Upload the statements to fix it.",
        action=InboxAction(label="Open sources", route="/operations/sources"),
    )]


def _platform(code: Optional[str]) -> str:
    from app.valuation.bridge import _platform_label

    return "Crypto wallets" if str(code or "").upper() == "CRYPTO" else _platform_label(code)


def concentration_items(db: Session, user: CurrentUser, base: str) -> list[InboxItem]:
    from app.valuation import pages

    month = _open_month()
    summary = pages.risk_summary(db, user.id, month, _month_start(month), base)
    top = summary.get("top_holdings") or []
    if not top:
        return []
    largest = top[0]
    share = float(largest.get("percent_of_networth") or 0)
    if share < CONCENTRATION_PCT:
        return []
    symbol = str(largest.get("symbol") or "Your largest holding")
    return [InboxItem(
        id=f"concentration:{symbol}",
        kind="concentration",
        severity="low",
        title=f"{symbol} is {share:.0f}% of your net worth",
        detail=f"Above your {CONCENTRATION_PCT:.0f}% threshold for one holding.",
        action=InboxAction(label="Open Risk", route="/risk"),
    )]


def unusual_move_items(db: Session, user: CurrentUser, base: str) -> list[InboxItem]:
    rows = db.execute(text(
        "SELECT month, total FROM wealth_monthly_rollups WHERE user_id = :u AND base_currency = :b ORDER BY month"
    ), {"u": user.id, "b": base.upper()}).mappings().all()
    from app.valuation.clock import _current_anchor_ts, _latest_completed_month_start

    latest = _latest_completed_month_start(_current_anchor_ts()).strftime("%Y-%m")
    totals = [(str(r["month"]), float(r["total"])) for r in rows if str(r["month"]) <= latest]
    item = unusual_move(totals, base)
    return [item] if item and totals and totals[-1][0] == latest else []


def unusual_move(totals: list[tuple[str, float]], base: str) -> Optional[InboxItem]:
    """The last month's change if it's far outside the year before it (see the module doc)."""
    if len(totals) < 5:
        return None
    changes = [b - a for (_, a), (_, b) in zip(totals, totals[1:])]
    last, history = changes[-1], [abs(c) for c in changes[:-1][-UNUSUAL_MOVE_HISTORY:]]
    start = totals[-2][1]
    if len(history) < 3 or start <= 0:
        return None
    usual = median(history)
    if abs(last) < UNUSUAL_MOVE_FACTOR * usual or abs(last) / start * 100 < UNUSUAL_MOVE_MIN_PCT:
        return None
    month = totals[-1][0]
    direction = "up" if last > 0 else "down"
    return InboxItem(
        id=f"unusual_move:{month}",
        kind="unusual_move",
        severity="low",
        title=f"Net worth {direction} {_money(abs(last), base)} in {_month_name(month)}",
        detail=f"{abs(last) / start * 100:.0f}% of the month's start, about {abs(last) / usual:.0f}× a usual month "
               f"({_money(usual, base)}). See what moved it.",
        action=InboxAction(label="Open History", route="/wealth/history"),
    )


def recurring_items(db: Session, user: CurrentUser, base: str) -> list[InboxItem]:
    from app.routers.spending import RECURRING_LOOKBACK_MONTHS, _credit_card_recurring_payments
    from app.valuation.clock import _add_months, _month_end

    month = _open_month()
    month_start = _month_start(month)
    payments = _credit_card_recurring_payments(
        db, user.id, month, base, _add_months(month_start, -(RECURRING_LOOKBACK_MONTHS - 1)), _month_end(month_start)
    )
    return [item for item in (recurring_item(p, base) for p in payments) if item is not None]


def recurring_item(payment: Any, base: str) -> Optional[InboxItem]:
    amount = float(payment.current_month_amount)
    typical = float(payment.typical_amount or 0)
    if amount < RECURRING_MIN:
        return None
    merchant = str(payment.merchant_counterparty)
    key = f"{payment.account_id}:{merchant.lower()}"
    if int(payment.months_present) <= RECURRING_NEW_MONTHS:
        return InboxItem(
            id=f"recurring_new:{key}",
            kind="recurring_new",
            severity="low",
            title=f"New recurring charge: {merchant}",
            detail=f"{_money(amount, base)} this month on {payment.card_name}; it repeats {payment.cadence}.",
            action=InboxAction(label="Open card", route="/liabilities"),
        )
    if typical > 0 and amount >= typical * (1 + RECURRING_UP_PCT / 100) and amount - typical >= RECURRING_UP_MIN:
        return InboxItem(
            id=f"recurring_up:{key}",
            kind="recurring_up",
            severity="low",
            title=f"{merchant} charged more than usual",
            detail=f"{_money(amount, base)} this month vs a usual {_money(typical, base)} on {payment.card_name}.",
            action=InboxAction(label="Open card", route="/liabilities"),
        )
    return None


CHECKS: list[Callable[[Session, CurrentUser, str], list[InboxItem]]] = [
    month_closed_items,
    concentration_items,
    unusual_move_items,
    recurring_items,
]


def insight_items(db: Session, user: CurrentUser, base: str, safe: Callable[[Callable[[], Any], Any], Any]) -> list[InboxItem]:
    """Every check above; one failing doesn't hide the others (``safe`` is the inbox's guard)."""
    out: list[InboxItem] = []
    for check in CHECKS:
        out.extend(safe(lambda check=check: check(db, user, base), []))
    return out

