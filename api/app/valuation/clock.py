"""Clock and snapshot anchors for valuation: one rule, one timezone per user
(#143, #130 finding 1.10, #202).

- **The timezone** is the request user's home timezone
  (``user_preferences.timezone``, #202), else the app timezone (``TZ``,
  default Asia/Singapore); see ``app.core.clock``. Background History refreshes
  run each user in their own (``app.valuation.history``).
- **Now** is ``_current_anchor_ts()``: the instant in that timezone, frozen
  for one request (#147). **Today** is its date (``_app_today``).
- A month's **anchor** is the date SNAPSHOT_DAY of the next month (clamped to
  the month's length), carried as 00:00 UTC of that date: readers use its date
  (snapshots ``report_date <= anchor date``, inclusive). Card transactions are
  the exception (``_card_transaction_in_window``): they count before midnight
  of the anchor date *in the user's timezone*; a date-only timestamp (stored
  as 00:00 UTC, as statement imports write them) is that calendar date and is
  compared by date (#202). Spending and dashboard cash-flow months use the
  same rule (``_transaction_in_month_window``, ``_transaction_month_key``,
  #211): midnight to midnight in the user's timezone.
- An anchor has **passed** (its month is completed) once today, in the user's
  timezone, is on or after its date (``_anchor_passed``). Dashboard snapshot
  views, the live comparisons, History and its dirty marks
  (``app.wealth_rollup_dirty``) all use this one rule, so on the 1st before
  08:00 SGT (still the previous day in UTC) they agree that last month is done.
- The **open month** is today's month in the user's timezone.
- Quote and FX date lookups are not affected (D-44): market/UTC dates.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException

from app.core.clock import app_now, app_timezone
from app.valuation_cache import request_memo


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
    """Now, in the app's timezone. Frozen for the length of a request (#147),
    so every "live" value in one response is taken at the same instant."""
    tz = app_timezone()
    return request_memo(
        ("dashboard._current_anchor_ts", str(tz)),
        lambda: app_now().replace(microsecond=0),
    )


def _local_date(instant: datetime) -> date:
    """The app-timezone date of ``instant`` (naive means UTC)."""
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(app_timezone()).date()


def _local_midnight(day: date) -> datetime:
    """00:00 of ``day`` in the current timezone, as a UTC instant."""
    return datetime.combine(day, time(0), tzinfo=app_timezone()).astimezone(timezone.utc)


def _is_utc_midnight(instant: datetime) -> bool:
    utc = instant.astimezone(timezone.utc) if instant.tzinfo is not None else instant
    return (utc.hour, utc.minute, utc.second, utc.microsecond) == (0, 0, 0, 0)


def _is_snapshot_anchor(anchor_ts: datetime) -> bool:
    """Whether ``anchor_ts`` is a date anchor (00:00 UTC, as ``_anchor_ts``
    carries them) rather than a live instant."""
    offset = anchor_ts.utcoffset() if anchor_ts.tzinfo is not None else timedelta(0)
    return offset == timedelta(0) and _is_utc_midnight(anchor_ts)


def _card_transaction_in_window(ts: datetime, start_day: date, anchor_ts: datetime) -> bool:
    """Whether a card transaction at ``ts`` is in the window that starts on
    ``start_day`` and ends at ``anchor_ts``, by the user's calendar (#202).

    - A date-only ``ts`` (00:00 UTC: statement rows carry just a date) is its
      calendar date: in the window when ``start_day <= date`` and the date is
      before a date anchor's date, or on/before today for a live anchor.
    - A timed ``ts`` is an instant: in the window from midnight of
      ``start_day`` in the user's timezone up to midnight of a date anchor's
      date in the user's timezone, or up to the live instant.
    """
    ts = _normalize_ts(ts) or ts
    snapshot = _is_snapshot_anchor(anchor_ts)
    if _is_utc_midnight(ts):
        day = ts.astimezone(timezone.utc).date()
        if day < start_day:
            return False
        if snapshot:
            return day < anchor_ts.astimezone(timezone.utc).date()
        return day <= _local_date(anchor_ts)
    if ts < _local_midnight(start_day):
        return False
    if snapshot:
        return ts < _local_midnight(anchor_ts.astimezone(timezone.utc).date())
    return ts < anchor_ts


def _transaction_date(ts: Any) -> date:
    """The user's calendar date of a transaction timestamp (#202, #211): a
    date-only ``ts`` (00:00 UTC) is that date; a timed one is the date of the
    instant in the user's timezone. For a month window this is the same rule
    as ``_card_transaction_in_window`` with a date anchor."""
    normalized = _normalize_ts(ts)
    if normalized is None:
        raise ValueError(f"not a timestamp: {ts!r}")
    if _is_utc_midnight(normalized):
        return normalized.astimezone(timezone.utc).date()
    return _local_date(normalized)


def _transaction_month_key(ts: Any) -> str:
    """'YYYY-MM' of ``_transaction_date(ts)``: the month a transaction counts in."""
    return _transaction_date(ts).strftime("%Y-%m")


def _transaction_in_month_window(ts: Any, start: datetime, end: datetime) -> bool:
    """Whether a transaction counts in the calendar window [start, end) (month
    starts, 00:00 UTC as ``_parse_month`` gives them) by the user's calendar:
    spending and cash flow (#211) use the card-month rule (#202)."""
    return _card_transaction_in_window(ts, start.astimezone(timezone.utc).date(), end)


def _transaction_query_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """SQL bounds for a calendar window: a day of slack either side (local
    midnight is within 14 hours of UTC midnight); ``_transaction_in_month_window``
    then decides each row."""
    return start - timedelta(days=1), end + timedelta(days=1)


def _app_today() -> date:
    """Today in the app timezone: the date of ``_current_anchor_ts()``."""
    return _local_date(_current_anchor_ts())


def _anchor_passed(anchor_ts: datetime, today: Optional[date] = None) -> bool:
    """Whether a snapshot anchor has passed: its date is today or earlier, in
    the app timezone. The one completion rule (see the module docstring)."""
    return anchor_ts.date() <= (today if today is not None else _app_today())


def _month_start_of(day: date) -> datetime:
    """The month start (00:00 UTC, like ``_parse_month``) of ``day``'s month."""
    return datetime(day.year, day.month, 1, tzinfo=timezone.utc)


def _previous_update_anchor_ts(anchor_ts: datetime) -> datetime:
    """One day before anchor_ts. Combined with the fact that price/NAV lookups
    already resolve to "latest available at-or-before this anchor" (see
    _latest_price_map, _effective_as_of), this yields the correct "since last
    update" comparison point even when data is several days stale — both anchors
    then resolve to the same underlying data point and the delta is correctly 0.
    """
    return anchor_ts - timedelta(days=1)


def _completed_snapshot_month_start(month_start: datetime) -> datetime:
    """The month whose anchor a snapshot view of `month_start` actually uses.

    A month whose own anchor has passed is "closed" and uses itself. The open
    (current) month's anchor is still in the future, so it reports the previous
    month's completed anchor instead (#133).
    """
    if _anchor_passed(_anchor_ts(month_start)):
        return month_start
    return _add_months(month_start, -1)


def _completed_snapshot_anchor_ts(month_start: datetime) -> datetime:
    return _anchor_ts(_completed_snapshot_month_start(month_start))


def _latest_completed_month_start(now: datetime) -> datetime:
    """The latest month (UTC month start) whose anchor has passed at `now`.

    Normally the month before `now`'s month (in the app timezone); one further
    back while `now` is before SNAPSHOT_DAY (that month-end's anchor hasn't
    passed yet).
    """
    today = _local_date(now)
    month_start = _add_months(_month_start_of(today), -1)
    while not _anchor_passed(_anchor_ts(month_start), today):
        month_start = _add_months(month_start, -1)
    return month_start


def _effective_anchor_for_month(month_start: datetime) -> tuple[datetime, bool]:
    """The anchor a "browse holdings as of {month}" view should use, and whether
    it's live. The current (or any future) calendar month shows live data — the
    freshest computable state, matching every other "current" view in the app.
    Any past month shows that month's own completed snapshot boundary, not "now".
    """
    current_anchor = _current_anchor_ts()
    if _is_open_or_future_month(month_start):
        return current_anchor, True
    return _anchor_ts(month_start), False


def _month_view_anchor(month_start: datetime) -> tuple[datetime, bool]:
    """The anchor a page that follows the selected month reads its breakdowns
    at (Overview, #223), and whether it's live. The open (or a future) month is
    live "now", like its headline. A past month is the same completed snapshot
    boundary as that month's net worth (``_completed_snapshot_anchor_ts``), so
    the hero, the allocation and the positions all show one month-end.

    Unlike ``_effective_anchor_for_month`` it never returns an anchor that hasn't
    passed: last month, before SNAPSHOT_DAY, reads the month-end before it,
    exactly as its net worth does.
    """
    if _is_open_or_future_month(month_start):
        return _current_anchor_ts(), True
    return _completed_snapshot_anchor_ts(month_start), False


def _month_view_compare_month_start(month_start: datetime) -> datetime:
    """The month a month view's "vs last month" compares with (#232): the
    completed month-end before the figures shown, as Overview's headline does
    (D-24). Live: the latest completed month-end; a past month: the completed
    month-end before the one ``_month_view_anchor`` reads. With SNAPSHOT_DAY=1
    this is always the calendar month before ``month_start``; with a later
    SNAPSHOT_DAY, before that day, it is one month earlier, like the anchor."""
    if _is_open_or_future_month(month_start):
        return _latest_completed_month_start(_current_anchor_ts())
    return _add_months(_completed_snapshot_month_start(month_start), -1)


def _is_open_or_future_month(month_start: datetime) -> bool:
    """Whether ``month_start``'s month is today's month (app timezone) or later."""
    today = _app_today()
    return (month_start.year, month_start.month) >= (today.year, today.month)


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


def _month_window(end_month_start: datetime, months: int = 6) -> list[datetime]:
    return [_add_months(end_month_start, offset) for offset in range(-(months - 1), 1)]


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


