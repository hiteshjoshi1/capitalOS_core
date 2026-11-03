"""Sleep-proof scheduling for the in-app daily jobs (#112).

A plain cron job is unreliable on a laptop: the scheduler's timer doesn't
advance while the Docker VM is suspended, so after a wake it fires hours late,
and APScheduler then discards the late run (default misfire grace: 1 second).

Instead each job is a short *interval* check ("is a run due?"). A run is due
when the newest successful run finished before the most recent scheduled time.
The check runs every few minutes, so after a wake the job catches up within one
interval of awake time, and a run that already happened is never repeated.
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

# Applied to every scheduler: a late run is never discarded, a backlog of late
# runs collapses into one, and a job never overlaps itself.
JOB_DEFAULTS = {"misfire_grace_time": None, "coalesce": True, "max_instances": 1}

DEFAULT_CHECK_MINUTES = 5.0
DEFAULT_RETRY_MINUTES = 30.0


def _env_minutes(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(value, minimum)


def check_interval_minutes() -> float:
    """How often each job asks "is a run due?" (`SCHEDULER_CHECK_MINUTES`)."""
    return _env_minutes("SCHEDULER_CHECK_MINUTES", DEFAULT_CHECK_MINUTES, 1.0)


def retry_after() -> timedelta:
    """Minimum gap before retrying a due run whose last attempt failed
    (`SCHEDULER_RETRY_MINUTES`), so a broken provider isn't hit every check."""
    return timedelta(minutes=_env_minutes("SCHEDULER_RETRY_MINUTES", DEFAULT_RETRY_MINUTES, 1.0))


def parse_hhmm(raw: str | None, default: tuple[int, int]) -> tuple[int, int]:
    if not raw or ":" not in raw:
        return default
    h, m = raw.split(":", 1)
    try:
        hour, minute = int(h), int(m)
    except ValueError:
        return default
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return default
    return hour, minute


def coerce_utc(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def most_recent_due(now: datetime, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """The latest `hour:minute` in `tz` at or before `now`, in UTC."""
    local = now.astimezone(tz)
    day: date = local.date()
    if (local.hour, local.minute) < (hour, minute):
        day -= timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(timezone.utc)


def run_is_due(last_success: datetime | None, due: datetime) -> bool:
    return last_success is None or last_success < due


class RetryGate:
    """Remembers when a job last *attempted* a due run that didn't succeed, so
    the next attempt waits `retry_after()` instead of every check interval."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_failed_attempt: datetime | None = None

    def may_attempt(self, now: datetime) -> bool:
        with self._lock:
            last = self._last_failed_attempt
        return last is None or now - last >= retry_after()

    def record(self, now: datetime, *, succeeded: bool) -> None:
        with self._lock:
            self._last_failed_attempt = None if succeeded else now

    def reset(self) -> None:
        self.record(datetime.now(tz=timezone.utc), succeeded=True)
