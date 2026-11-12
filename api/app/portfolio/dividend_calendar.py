"""Dividend calendar projection (#417, U17, D-117): a holding's dividends in a coming window.

Pure functions over per-share dividend events (market_dividend_events). In order of trust:

1. **announced**: the provider lists the next ex-date (and, mostly for US stocks, the pay date).
   Its amount isn't listed, so it's estimated like a projected one.
2. **projected**: from the holding's own past dividends. With a year of history, each one comes
   round again a year later with its own amount (keeps interim/final schedules apart); with less,
   the median gap between past ex-dates from the last one (a steady 20–400 day rhythm, at least
   two dividends). Nothing is projected for a holding that hasn't paid for over 400 days.
3. The caller adds **your payments** (the user's own dividend transactions a year back) for
   holdings with no provider events at all.

An announced or gap-projected amount per share is what the same dividend paid a year earlier
(within ±45 days), else the latest one. Money is Decimal.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median
from typing import Iterable, Optional

MIN_GAP_DAYS = 20
MAX_GAP_DAYS = 400
SAME_PERIOD_DAYS = 45
# Over a year without a dividend: treated as stopped, nothing projected.
STOPPED_DAYS = 400
# History spanning this long counts as a full year: project each dividend a year on.
YEAR_OF_HISTORY_DAYS = 300


@dataclass(frozen=True)
class PastDividend:
    ex_date: date
    amount_per_share: Decimal


@dataclass(frozen=True)
class Upcoming:
    ex_date: date
    pay_date: Optional[date]
    amount_per_share: Optional[Decimal]
    basis: str  # "announced" | "projected"


def _amount_for(ex_date: date, history: list[PastDividend]) -> Optional[Decimal]:
    """The same period's dividend a year earlier (±45 days), else the latest one."""
    if not history:
        return None
    target = ex_date - timedelta(days=365)
    near = [h for h in history if abs((h.ex_date - target).days) <= SAME_PERIOD_DAYS]
    if near:
        return min(near, key=lambda h: abs((h.ex_date - target).days)).amount_per_share
    return history[-1].amount_per_share


def typical_gap_days(history: list[PastDividend]) -> Optional[int]:
    """The median gap between past ex-dates, when there's a steady rhythm; else None."""
    dates = sorted({h.ex_date for h in history})
    if len(dates) < 2:
        return None
    gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
    if not gaps:
        return None
    gap = int(median(gaps))
    return gap if MIN_GAP_DAYS <= gap <= MAX_GAP_DAYS else None


def upcoming_dividends(
    history: Iterable[PastDividend],
    announced: Optional[tuple[date, Optional[date]]],
    *,
    start: date,
    end: date,
) -> list[Upcoming]:
    """Dividends with an ex-date in [start, end], oldest first."""
    past = sorted((h for h in history if h.amount_per_share > 0), key=lambda h: h.ex_date)
    out: list[Upcoming] = []
    if announced is not None:
        ex_date, pay_date = announced
        if start <= ex_date <= end:
            out.append(Upcoming(ex_date, pay_date, _amount_for(ex_date, past), "announced"))
    # A holding that hasn't paid for over STOPPED_DAYS is not projected (it may have stopped).
    if not past or (start - past[-1].ex_date).days > STOPPED_DAYS:
        return sorted(out, key=lambda u: u.ex_date)
    if (past[-1].ex_date - past[0].ex_date).days >= YEAR_OF_HISTORY_DAYS:
        # A year of history: each dividend comes round again a year later, with its own amount,
        # which keeps uneven schedules (interim/final, a special in one quarter) right.
        for item in past:
            if (start - item.ex_date).days > STOPPED_DAYS:
                continue
            next_date = add_months(item.ex_date, 12)
            if not (start <= next_date <= end):
                continue
            if any(abs((u.ex_date - next_date).days) <= SAME_PERIOD_DAYS for u in out):
                continue
            out.append(Upcoming(next_date, None, item.amount_per_share, "projected"))
        return sorted(out, key=lambda u: u.ex_date)
    gap = typical_gap_days(past)
    if gap is not None:
        anchor = max(
            [past[-1].ex_date] + ([announced[0]] if announced is not None else []),
        )
        next_date = anchor + timedelta(days=gap)
        # Catch up when the last known one is long past (a missed refresh).
        while next_date < start:
            next_date += timedelta(days=gap)
        while next_date <= end:
            # A projection close to the listed date is the same dividend.
            if not any(abs((u.ex_date - next_date).days) < gap // 2 for u in out):
                out.append(Upcoming(next_date, None, _amount_for(next_date, past), "projected"))
            next_date += timedelta(days=gap)
    return sorted(out, key=lambda u: u.ex_date)


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    return date(year, month, 28)
