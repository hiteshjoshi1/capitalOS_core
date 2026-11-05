"""Valuation caching (#147): don't recompute the same valuation over and over.

Two layers, both behind one decorator, ``valuation_cached``:

1. **Per request.** A GET request runs inside a ``RequestScope`` (set by
   ``ValuationCacheMiddleware`` through a contextvar, the same way the request
   id is bound). Within it, a cached helper called again with the same
   arguments returns the value it already computed. Outside a request
   (schedulers, scripts, POST/PUT/DELETE handlers) nothing is cached at all.

2. **Across requests** (``shared=True`` only). Results are also kept in a
   bounded, in-process LRU and reused by later requests while the data is
   unchanged. An entry is reused only when all of these still match:

   - the **data watermark**: a process-wide write generation, bumped whenever a
     transaction that wrote anything commits in this process, plus, on
     Postgres, the WAL insert position, which moves on any committed write by
     anyone (psql, restores, scripts in other containers). Read once per request,
     before the request's first cached computation;
   - the **day** and **timezone** (the UTC date, the request user's home
     timezone (#202) and today's date in it: "today" feeds quote ages, live
     anchors, open/completed months and FX dates);
   - the env settings that change results (snapshot day, ownership scope, ...);
   - its age is under ``VALUATION_CACHE_TTL_SECONDS`` (default 600), a safety net.

   Shared keys always contain ``current_user_id``, so one user's entry can't be
   served to another. A result computed while an FX rate was missing or stale
   (``mark_degraded``, #139) is not shared, so an FX outage isn't remembered.

Every hit returns a fresh copy (dicts/lists are cloned), so a caller mutating
its result can't change what the next caller sees.

``VALUATION_CACHE_ENABLED=0`` turns both layers off.
"""
from __future__ import annotations

import functools
import inspect
import os
import re
import threading
import time
from collections import OrderedDict
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterator, Optional, TypeVar
from zoneinfo import ZoneInfo

from sqlalchemy import event, text

from app.core.clock import current_timezone_name
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

F = TypeVar("F", bound=Callable[..., Any])

_MISSING = object()


def cache_enabled() -> bool:
    return os.getenv("VALUATION_CACHE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


def _ttl_seconds() -> float:
    try:
        return max(1.0, float(os.getenv("VALUATION_CACHE_TTL_SECONDS", "600")))
    except ValueError:
        return 600.0


def _max_entries() -> int:
    try:
        return max(16, int(os.getenv("VALUATION_CACHE_MAX_ENTRIES", "256")))
    except ValueError:
        return 256


# Env settings that change computed results. Part of every shared entry's stamp.
_RESULT_ENV_VARS = (
    "SNAPSHOT_DAY",
    "TZ",
    "QUOTE_STALE_DAYS",
    "AUTH_ALLOW_LEGACY_NULL_OWNERSHIP",
    "FX_DISABLE_REMOTE",
    "FX_FALLBACK_RATES",
    "FX_LOOKBACK_DAYS",
    "FX_STALE_MAX_DAYS",
    "DASHBOARD_TOP_HOLDINGS_LIMIT",
)


def _env_stamp() -> tuple[Optional[str], ...]:
    return tuple(os.getenv(name) for name in _RESULT_ENV_VARS)


def _day_stamp() -> tuple[date, str, date]:
    """UTC date, the request user's timezone (#202) and today's date in it: two
    users (or one user before and after changing timezone) never share an entry
    computed under another timezone's months."""
    tz_name = current_timezone_name()
    return datetime.now(tz=timezone.utc).date(), tz_name, datetime.now(tz=ZoneInfo(tz_name)).date()


# ─── Write generation ────────────────────────────────────────────────────────
# Bumped when a transaction that executed a write commits in this process: once
# just before the commit (engine "commit" event) and once after it (Session
# "after_commit"), so a request that read the generation between the two can't
# store pre-commit data under the post-commit generation.

_write_generation = 0
_generation_lock = threading.Lock()
_post_commit_bump = threading.local()
_WRITE_SQL = re.compile(r"\b(INSERT|UPDATE|DELETE|MERGE|TRUNCATE|CREATE|DROP|ALTER)\b", re.IGNORECASE)
_DIRTY_KEY = "capitalos_valuation_cache_dirty"


def bump_write_generation() -> None:
    global _write_generation
    with _generation_lock:
        _write_generation += 1


def write_generation() -> int:
    return _write_generation


@event.listens_for(Engine, "after_cursor_execute")
def _note_write(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
    if statement and _WRITE_SQL.search(statement):
        conn.info[_DIRTY_KEY] = True


@event.listens_for(Engine, "commit")
def _bump_on_commit(conn):  # noqa: ANN001
    if conn.info.pop(_DIRTY_KEY, False):
        bump_write_generation()
        _post_commit_bump.pending = True


@event.listens_for(Engine, "rollback")
def _clear_on_rollback(conn):  # noqa: ANN001
    conn.info.pop(_DIRTY_KEY, None)


@event.listens_for(Session, "after_begin")
def _reset_post_commit(session, transaction, connection):  # noqa: ANN001
    # A pending flag left by a commit outside any Session isn't this session's.
    _post_commit_bump.pending = False


@event.listens_for(Session, "after_commit")
def _bump_after_commit(session):  # noqa: ANN001
    if getattr(_post_commit_bump, "pending", False):
        _post_commit_bump.pending = False
        bump_write_generation()
        # A request that wrote and then reads again must see its own write.
        scope = _request_scope.get()
        if scope is not None:
            scope.memo.clear()
            scope.watermark = _MISSING


def _db_watermark(db: Any) -> Any:
    """Postgres: the WAL insert position, which moves on any committed write by
    anyone (a commit always inserts a WAL record). SQLite (tests): nothing beyond the in-process generation."""
    try:
        bind = db.get_bind()
        if bind.dialect.name != "postgresql":
            return None
        # The insert position, not pg_current_wal_lsn() (the write position):
        # a commit that wrote no data is flushed lazily, so the write position
        # can trail it by a wal_writer_delay.
        return db.execute(text("SELECT pg_current_wal_insert_lsn()::text")).scalar()
    except Exception:  # pragma: no cover - never let the cache break a request
        return _MISSING


# ─── Request scope ───────────────────────────────────────────────────────────


@dataclass
class RequestScope:
    memo: dict[tuple, Any] = field(default_factory=dict)
    watermark: Any = _MISSING
    degraded: bool = False


_request_scope: ContextVar[Optional[RequestScope]] = ContextVar("capitalos_valuation_scope", default=None)


@contextmanager
def request_scope() -> Iterator[RequestScope]:
    scope = RequestScope()
    token = _request_scope.set(scope)
    try:
        yield scope
    finally:
        _request_scope.reset(token)


def current_scope() -> Optional[RequestScope]:
    if not cache_enabled():
        return None
    return _request_scope.get()


def mark_degraded() -> None:
    """Called when a computation used incomplete inputs (e.g. a missing or stale
    FX rate): nothing computed in the rest of this request goes into the shared
    cache."""
    scope = _request_scope.get()
    if scope is not None:
        scope.degraded = True


def request_memo(key: tuple, compute: Callable[[], Any]) -> Any:
    """Per-request memo for values that are cheap to key but must not outlive
    the request (e.g. the request's frozen "now")."""
    scope = current_scope()
    if scope is None:
        return compute()
    if key not in scope.memo:
        scope.memo[key] = compute()
    return scope.memo[key]


class ValuationCacheMiddleware:
    """Gives every GET request its own RequestScope."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") not in {"GET", "HEAD"}:
            await self.app(scope, receive, send)
            return
        with request_scope():
            await self.app(scope, receive, send)


# ─── Shared LRU ──────────────────────────────────────────────────────────────


@dataclass
class _Entry:
    stamp: tuple
    stored_at: float
    value: Any


class _SharedCache:
    def __init__(self) -> None:
        self._data: "OrderedDict[tuple, _Entry]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple, stamp: tuple) -> Any:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(key)
            if entry is None or entry.stamp != stamp or now - entry.stored_at > _ttl_seconds():
                if entry is not None:
                    del self._data[key]
                self.misses += 1
                return _MISSING
            self._data.move_to_end(key)
            self.hits += 1
            return entry.value

    def put(self, key: tuple, stamp: tuple, value: Any) -> None:
        with self._lock:
            self._data[key] = _Entry(stamp=stamp, stored_at=time.monotonic(), value=value)
            self._data.move_to_end(key)
            limit = _max_entries()
            while len(self._data) > limit:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = 0
            self.misses = 0

    def __len__(self) -> int:
        return len(self._data)


shared_cache = _SharedCache()


class _KeyLocks:
    """One lock per key being computed, so concurrent requests needing the same
    value (Wealth Overview fires /bootstrap and /summary together) compute it
    once: the second waits and then finds it cached.

    Cached helpers call other cached helpers but never back up the chain, so
    lock waits can't form a cycle; the acquire still times out as a safety net,
    and then the value is just computed without the lock."""

    _TIMEOUT_SECONDS = 30.0

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[tuple, list] = {}  # key -> [lock, users]

    @contextmanager
    def hold(self, key: tuple) -> Iterator[None]:
        with self._guard:
            entry = self._locks.setdefault(key, [threading.Lock(), 0])
            entry[1] += 1
        acquired = entry[0].acquire(timeout=self._TIMEOUT_SECONDS)
        try:
            yield
        finally:
            if acquired:
                entry[0].release()
            with self._guard:
                entry[1] -= 1
                if entry[1] == 0:
                    del self._locks[key]


_key_locks = _KeyLocks()


def clear_shared_cache() -> None:
    shared_cache.clear()


def _stamp(scope: RequestScope, db: Any) -> tuple:
    if scope.watermark is _MISSING:
        scope.watermark = (write_generation(), _db_watermark(db))
    return (scope.watermark, _day_stamp(), _env_stamp())


# ─── Decorator ───────────────────────────────────────────────────────────────


def clone(value: Any) -> Any:
    """Copy containers so callers can't mutate a cached value. Leaves are
    immutable (str, numbers, Decimal, date/datetime, None)."""
    if isinstance(value, dict):
        return {k: clone(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clone(v) for v in value]
    if isinstance(value, tuple):
        return tuple(clone(v) for v in value)
    if isinstance(value, set):
        return set(value)
    return value


def _fx_date(value: datetime) -> date:
    """The date app.fx.get_rates looks rates up for at this anchor (it caps
    anchors at now); part of the key so two anchors on the same day but with
    different FX dates never share an entry."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return min(value, datetime.now(tz=timezone.utc)).date()


def _freeze(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return frozenset(value)
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    return value


def valuation_cached(
    *,
    shared: bool = False,
    date_args: tuple[str, ...] = (),
) -> Callable[[F], F]:
    """Cache a ``(db, ...)`` helper per request and, with ``shared=True``,
    across requests.

    ``date_args`` names datetime arguments the helper only uses through their
    date (anchors read as ``anchor.date()``, FX by date): they're keyed by date
    so a live "now" anchor reuses the value computed for the same day. Only list
    an argument here when that is true for everything the helper does with it.
    """

    def decorator(fn: F) -> F:
        signature = inspect.signature(fn)
        params = list(signature.parameters)
        if params[0] != "db":
            raise TypeError(f"{fn.__qualname__}: first parameter must be db")
        if shared and "current_user_id" not in params:
            raise TypeError(f"{fn.__qualname__}: shared caching needs current_user_id in the key")
        name = f"{fn.__module__}.{fn.__qualname__}"

        def _key(bound: inspect.BoundArguments) -> tuple:
            parts = []
            for param, value in bound.arguments.items():
                if param == "db":
                    continue
                if param in date_args and isinstance(value, datetime):
                    value = ("date", value.date(), _fx_date(value))
                parts.append((param, _freeze(value)))
            return (name, tuple(parts))

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            scope = current_scope()
            if scope is None:
                return fn(*args, **kwargs)
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            try:
                key = _key(bound)
                hash(key)
            except TypeError:  # unhashable argument: don't cache
                return fn(*args, **kwargs)
            if key in scope.memo:
                return clone(scope.memo[key])
            if not shared:
                value = fn(*args, **kwargs)
                scope.memo[key] = clone(value)
                return value
            stamp = _stamp(scope, bound.arguments["db"])
            cached = shared_cache.get(key, stamp)
            if cached is _MISSING:
                with _key_locks.hold(key):
                    cached = shared_cache.get(key, stamp)  # computed while we waited?
                    if cached is _MISSING:
                        value = fn(*args, **kwargs)
                        stored = clone(value)
                        scope.memo[key] = stored
                        if not scope.degraded and scope.watermark is not _MISSING and scope.watermark[1] is not _MISSING:
                            shared_cache.put(key, stamp, stored)
                        return value
            scope.memo[key] = cached
            return clone(cached)

        wrapper.__wrapped_uncached__ = fn  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
