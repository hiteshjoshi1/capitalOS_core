"""Clock and snapshot anchors for valuation (#143, #130 finding 1.10)."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException

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
    tz_name = os.getenv("TZ", "Asia/Singapore")
    return request_memo(
        ("dashboard._current_anchor_ts", tz_name),
        lambda: datetime.now(tz=ZoneInfo(tz_name)).replace(microsecond=0),
    )


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
    if _anchor_ts(month_start) <= _current_anchor_ts():
        return month_start
    return _add_months(month_start, -1)


def _completed_snapshot_anchor_ts(month_start: datetime) -> datetime:
    return _anchor_ts(_completed_snapshot_month_start(month_start))


def _latest_completed_month_start(now: datetime) -> datetime:
    """The latest month (UTC month start) whose anchor is at or before `now`.

    Normally the month before `now`'s month; one further back while `now` is
    before SNAPSHOT_DAY (that month-end's anchor hasn't passed yet).
    """
    month_start = _add_months(_parse_month(now.strftime("%Y-%m")), -1)
    while _anchor_ts(month_start) > now:
        month_start = _add_months(month_start, -1)
    return month_start


def _effective_anchor_for_month(month_start: datetime) -> tuple[datetime, bool]:
    """The anchor a "browse holdings as of {month}" view should use, and whether
    it's live. The current (or any future) calendar month shows live data — the
    freshest computable state, matching every other "current" view in the app.
    Any past month shows that month's own completed snapshot boundary, not "now".
    """
    current_anchor = _current_anchor_ts()
    current_month_start = current_anchor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start >= current_month_start:
        return current_anchor, True
    return _anchor_ts(month_start), False


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


