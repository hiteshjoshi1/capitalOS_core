"""The app's notion of "today" (#141), per user (#202).

The container clock runs in UTC, but a user's day runs in their home timezone
(``user_preferences.timezone``, #202). Between 00:00 and 08:00 Singapore time
``date.today()`` in a UTC container is still yesterday, so anything that dates
a fact by "today" asks this module instead.

Which timezone:

- Inside a signed-in request, the request user's home timezone. The auth
  dependency binds it (``bind_request_timezone``) into a slot that
  ``RequestTimezoneMiddleware`` gives every HTTP/WebSocket request, so it holds
  for the whole request, including code running in the threadpool.
- In a background job working for one user, whatever ``use_timezone`` set.
- Otherwise (no user: health checks, schedulers, scripts), and for a user who
  has none, the app timezone: ``TZ``, default ``Asia/Singapore``.

Quote and FX date lookups don't use this (D-44): they stay on market/UTC dates.
"""

from __future__ import annotations

import functools
import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterator, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEFAULT_APP_TZ = "Asia/Singapore"


@functools.lru_cache(maxsize=1)
def _known_timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def normalize_timezone_name(name: Any) -> Optional[str]:
    """``name`` if it is a known IANA timezone name (e.g. ``America/New_York``),
    else None. Paths, empty strings and unknown names are rejected."""
    if not isinstance(name, str):
        return None
    candidate = name.strip()
    if not candidate or candidate not in _known_timezones():
        return None
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return candidate


def default_timezone_name() -> str:
    """The app timezone from ``TZ``; an unset or unknown value means Asia/Singapore."""
    name = (os.getenv("TZ") or "").strip().lstrip(":")
    if name:
        try:
            ZoneInfo(name)
            return name
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return DEFAULT_APP_TZ


@dataclass
class _TimezoneSlot:
    """Mutable, so a value bound in a threadpool dependency is seen by the
    endpoint (each threadpool call runs in a copy of the context, but the copy
    still points at this same object)."""

    name: Optional[str] = None


_slot: ContextVar[Optional[_TimezoneSlot]] = ContextVar("capitalos_user_timezone", default=None)


def current_timezone_name() -> str:
    """The timezone month logic uses right now (see the module docstring)."""
    slot = _slot.get()
    if slot is not None and slot.name:
        return slot.name
    return default_timezone_name()


def app_timezone() -> ZoneInfo:
    """The current user's timezone, or the app timezone when there is none."""
    return ZoneInfo(current_timezone_name())


def bind_request_timezone(name: Optional[str]) -> None:
    """Set the timezone for the rest of this request (called once the user is
    known). ``None`` or an invalid name means the app timezone."""
    resolved = normalize_timezone_name(name)
    slot = _slot.get()
    if slot is None:
        _slot.set(_TimezoneSlot(resolved))
    else:
        slot.name = resolved


@contextmanager
def use_timezone(name: Optional[str]) -> Iterator[None]:
    """Run a block in ``name``'s timezone (background work for one user, tests)."""
    token = _slot.set(_TimezoneSlot(normalize_timezone_name(name)))
    try:
        yield
    finally:
        _slot.reset(token)


class RequestTimezoneMiddleware:
    """Gives every HTTP and WebSocket request its own timezone slot, empty (the
    app timezone) until the auth dependency fills in the user's."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        token = _slot.set(_TimezoneSlot())
        try:
            await self.app(scope, receive, send)
        finally:
            _slot.reset(token)


def app_now(now: datetime | None = None) -> datetime:
    """Now in the current timezone, tz-aware (``now`` is for tests; naive means UTC)."""
    instant = now or datetime.now(tz=timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(app_timezone())


def app_today(now: datetime | None = None) -> date:
    """Today's date in the current timezone (``now`` is for tests; naive means UTC)."""
    return app_now(now).date()
