"""Income: dividends plus interest, by month and over comparable windows (#267).

The Income page (formerly Dividends) leads with totals that are steady enough to compare:
the last 12 months against the 12 before them, and the year to date against the same
dates a year earlier. Month-on-month is noisy for income (quarterly payers, annual
interest credits), so it is not the headline.

The rules are the ones the app already uses elsewhere, so the numbers agree:
- **Dividends**: the Dividends page's rows (`_fetch_dividend_rows`: `transactions` plus the
  IBKR cash ledger, net of withholding), converted at each payment date's rate (#139).
- **Interest**: the Overview "This month" bridge's rule (`app.valuation.bridge`): Cash
  flow income rows classified as interest (`income_interest`, or "interest" in the
  category), plus the broker ledger's CINT/DINT lines. Net: interest charged by a broker
  is negative. Card interest *charged* (type INTEREST) is spending, not income.

Windows are app-timezone dates, half-open ``[from, to)``. For the current month the end is
tomorrow (month to date), and every comparison window ends on the same day of its month,
so like is compared with like.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_context import account_scope_sql
from app.fx import get_rates_by_date, rate_date
from app.routers.dividends import _fetch_dividend_rows
from app.routers.spending import _build_row_rate_map, _cash_flow_bucket, _cash_flow_rows, _row_base_amount
from app.valuation import clock
from app.valuation.bridge import LEDGER_INTEREST_CODES, _is_dividend_row, _is_interest_row


@dataclass(frozen=True)
class IncomeItem:
    day: date  # app-timezone date
    kind: str  # "dividends" | "interest"
    amount: float  # base currency, signed (withholding and interest charged are negative)


def add_months(day: date, months: int) -> date:
    """``day`` moved by whole months, clamped to the month's last day (31 Mar - 1 → 28/29 Feb)."""
    index = day.year * 12 + (day.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(day.day, last))


def window_end(month: str, today: date) -> date:
    """Exclusive end of the selected month's income: its next 1st, or tomorrow when that is
    earlier (the current month, to date)."""
    year, mon = (int(part) for part in month.split("-"))
    next_first = date(year + (mon == 12), mon % 12 + 1, 1)
    return min(next_first, today + timedelta(days=1))


def _utc_midnight(day: date) -> datetime:
    return datetime.combine(day, time(0), tzinfo=timezone.utc)


def _dividend_items(db: Session, user_id: int, base: str, first: date, last: date) -> list[IncomeItem]:
    # A day of slack either side for the app timezone; each row is then placed by its local date.
    rows = _fetch_dividend_rows(db, _utc_midnight(first) - timedelta(days=1), _utc_midnight(last) + timedelta(days=1), user_id)
    if not rows:
        return []
    currencies = {(row.get("currency") or base).upper() for row in rows}
    rates = get_rates_by_date([row["ts"] for row in rows], base, currencies)
    out = []
    for row in rows:
        ts = row["ts"] if isinstance(row["ts"], datetime) else datetime.fromisoformat(str(row["ts"]))
        day = clock._local_date(ts)
        if not first <= day < last:
            continue
        currency = (row.get("currency") or base).upper()
        out.append(IncomeItem(day, "dividends", float(row.get("amount") or 0.0) * rates[rate_date(row["ts"])].get(currency, 0.0)))
    return out


def _interest_items(db: Session, user_id: int, base: str, first: date, last: date) -> list[IncomeItem]:
    rows = [
        dict(row)
        for row in _cash_flow_rows(db, _utc_midnight(first) - timedelta(days=1), _utc_midnight(last) + timedelta(days=1), user_id)
    ]
    wanted = []
    for row in rows:
        ts = row["ts"] if isinstance(row["ts"], datetime) else datetime.fromisoformat(str(row["ts"]))
        day = clock._local_date(ts)
        if not first <= day < last or _is_dividend_row(row):
            continue
        if _cash_flow_bucket(row) == "income" and _is_interest_row(row):
            wanted.append((day, row))
    out: list[IncomeItem] = []
    if wanted:
        rate_map = _build_row_rate_map([row for _, row in wanted], base)
        out.extend(IncomeItem(day, "interest", _row_base_amount(row, base, rate_map)) for day, row in wanted)

    codes = sorted(LEDGER_INTEREST_CODES)
    params: dict[str, Any] = {f"code{i}": code for i, code in enumerate(codes)}
    ledger = db.execute(
        text(
            f"""
            SELECT l.activity_date, l.amount, l.currency
            FROM portfolio_cash_ledger_entries l
            JOIN broker_accounts ba ON ba.id = l.broker_account_id
            JOIN accounts acc ON acc.id = ba.legacy_account_id
            WHERE l.activity_date >= :first AND l.activity_date < :last
              AND UPPER(COALESCE(l.activity_code, '')) IN ({", ".join(f":{key}" for key in params)})
              AND """
            + account_scope_sql("acc")
        ),
        {**params, "first": first, "last": last, "current_user_id": user_id},
    ).mappings().all()
    if ledger:
        ledger_rates: Mapping[date, Mapping[str, float]] = get_rates_by_date(
            [row["activity_date"] for row in ledger], base, {str(row["currency"]).upper() for row in ledger}
        )
        for row in ledger:
            day = row["activity_date"] if isinstance(row["activity_date"], date) else date.fromisoformat(str(row["activity_date"])[:10])
            rate = ledger_rates.get(rate_date(row["activity_date"]), {}).get(str(row["currency"]).upper(), 0.0)
            out.append(IncomeItem(day, "interest", float(row["amount"] or 0.0) * rate))
    return out


def income_items(db: Session, user_id: int, base: str, first: date, last: date) -> list[IncomeItem]:
    """Every dividend and interest amount with a local date in ``[first, last)``."""
    return _dividend_items(db, user_id, base, first, last) + _interest_items(db, user_id, base, first, last)


def window_totals(items: Iterable[IncomeItem], first: date, last: date) -> dict[str, Any]:
    dividends = sum(item.amount for item in items if item.kind == "dividends" and first <= item.day < last)
    interest = sum(item.amount for item in items if item.kind == "interest" and first <= item.day < last)
    return {
        "from_date": first.isoformat(),
        "to_date": (last - timedelta(days=1)).isoformat(),
        "dividends": dividends,
        "interest": interest,
        "total": dividends + interest,
    }


def change_pct(current: float, previous: float) -> float | None:
    """Fractional change, or None when there's nothing to compare with."""
    if abs(previous) < 1e-9:
        return None
    return (current - previous) / abs(previous)


def income_summary(db: Session, user_id: int, month: str, base: str, today: date | None = None) -> dict[str, Any]:
    today = today or clock._app_today()
    end = window_end(month, today)
    year, mon = (int(part) for part in month.split("-"))
    partial = end < date(year + (mon == 12), mon % 12 + 1, 1)

    first = add_months(end, -24)
    items = income_items(db, user_id, base, first, end)

    trailing = window_totals(items, add_months(end, -12), end)
    prior = window_totals(items, first, add_months(end, -12))
    ytd_start = date((end - timedelta(days=1)).year, 1, 1)
    ytd = window_totals(items, ytd_start, end)
    prior_ytd = window_totals(items, add_months(ytd_start, -12), add_months(end, -12))

    months = []
    for back in range(11, -1, -1):
        idx = year * 12 + (mon - 1) - back
        m_first = date(idx // 12, idx % 12 + 1, 1)
        m_last = min(add_months(m_first, 1), end)
        totals = window_totals(items, m_first, m_last)
        months.append({"month": m_first.strftime("%Y-%m"), **{k: totals[k] for k in ("dividends", "interest", "total")}})

    return {
        "month": month,
        "base_currency": base,
        "as_of": (end - timedelta(days=1)).isoformat(),
        "partial_month": partial,
        "trailing_12": trailing,
        "prior_12": prior,
        "trailing_12_change_pct": change_pct(trailing["total"], prior["total"]),
        "ytd": ytd,
        "prior_ytd": prior_ytd,
        "ytd_change_pct": change_pct(ytd["total"], prior_ytd["total"]),
        "months": months,
    }
