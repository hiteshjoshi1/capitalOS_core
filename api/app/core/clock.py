"""The app's notion of "today" (#141).

The container clock runs in UTC, but the owner's day runs in the app timezone
(``TZ``, default ``Asia/Singapore``, the same default the dashboard anchors and
schedulers use). Between 00:00 and 08:00 Singapore time ``date.today()`` in a
UTC container is still yesterday, so anything that dates a fact by "today"
asks this module instead.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_APP_TZ = "Asia/Singapore"


def app_timezone() -> ZoneInfo:
    """The app timezone from ``TZ``; an unset or unknown value means Asia/Singapore."""
    name = (os.getenv("TZ") or "").strip().lstrip(":")
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return ZoneInfo(DEFAULT_APP_TZ)


def app_now(now: datetime | None = None) -> datetime:
    """Now in the app timezone, tz-aware (``now`` is for tests; naive means UTC)."""
    instant = now or datetime.now(tz=timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(app_timezone())


def app_today(now: datetime | None = None) -> date:
    """Today's date in the app timezone (``now`` is for tests; naive means UTC)."""
    return app_now(now).date()
