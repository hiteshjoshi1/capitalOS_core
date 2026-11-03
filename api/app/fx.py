"""FX rates (#139): a local rate table, read with a bounded lookback.

Valuations convert with ``get_rates`` (one date) or ``get_rates_by_date`` (many
dates, e.g. dividend flows). Both read the local ``fx_rates`` table (plus IBKR's
statement rates in ``portfolio_fx_rates``) and only ask a provider when the table
has nothing recent enough for a date; whatever a provider returns is stored, so
the next request, and the next process, reads it locally.

Rules:

- A stored row means: 1 ``base`` is worth ``rate`` units of ``quote`` on
  ``rate_date``. Any pair is derived through a shared base on the same date
  (Frankfurter rows are EUR-based, open.er-api rows USD-based, IBKR rows are
  ``from -> to``).
- For a date D the reader takes the latest row on or before D. A row within
  ``FX_LOOKBACK_DAYS`` (default 7) is current. An older one (up to
  ``FX_STALE_MAX_DAYS``, default 366) is still used, but the currency is
  reported as *stale*. With nothing at all, the currency is *missing*: it is left
  out of the result (never 1.0), and callers convert it to 0, i.e. the value is
  excluded and the response says so.
- The base currency is always 1.0.
- Providers: Frankfurter (dated ECB rates; one call per date range for every
  currency), open.er-api (latest only, so it is used for today and stored under
  its own date, never under a historical one), then ``FX_FALLBACK_RATES``.
  ``FX_DISABLE_REMOTE=1`` turns the providers off: only stored rates are used.
- A provider answer is cached in-process for ``FX_CACHE_TTL_SECONDS``; a failure
  for ``FX_NEGATIVE_CACHE_SECONDS`` (default 60), so an outage costs one timeout
  per minute, not one per conversion.

Every missing or stale currency met while serving a request is recorded for that
request (``fx_status``), so the response can say its totals are incomplete, and
the request's valuations stay out of the shared cache (``mark_degraded``).
"""
from __future__ import annotations

import bisect
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Iterator, Optional

import httpx
from sqlalchemy import bindparam, text

from app.valuation_cache import mark_degraded

logger = logging.getLogger("capitalos.fx")


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


_TTL_SECONDS = _env_int("FX_CACHE_TTL_SECONDS", 86400, 1)
_NEGATIVE_TTL_SECONDS = _env_int("FX_NEGATIVE_CACHE_SECONDS", 60, 0)


def lookback_days() -> int:
    return _env_int("FX_LOOKBACK_DAYS", 7, 0)


def stale_max_days() -> int:
    return _env_int("FX_STALE_MAX_DAYS", 366, 0)


# For a date in the last lookback window, a stored row older than this asks the
# provider whether something newer exists (weekends: Friday's rate is the latest).
_REFRESH_AFTER_DAYS = 3

# Lower is preferred when two derivations exist for the same date.
_SOURCE_PRIORITY = {"frankfurter": 0, "ibkr": 1, "open.er-api": 2}

# Keys: ("rate", date, base, currency) -> (stored_at, ttl, FxQuote | None);
#       ("provider", name, start, end) -> (stored_at, ok).
_CACHE: dict[tuple, tuple[float, Any, Any]] = {}

_FETCH_LOCKS: dict[tuple, threading.Lock] = {}
_FETCH_LOCKS_GUARD = threading.Lock()


def _fetch_lock(key: tuple) -> threading.Lock:
    with _FETCH_LOCKS_GUARD:
        lock = _FETCH_LOCKS.get(key)
        if lock is None:
            lock = _FETCH_LOCKS[key] = threading.Lock()
        return lock


def remote_enabled() -> bool:
    return os.getenv("FX_DISABLE_REMOTE", "0") != "1"


# ─── Results ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FxQuote:
    """Value of 1 unit of a currency in the base, and where it came from."""

    value: float
    source: str
    rate_date: date
    age_days: int  # days between the rate's date and the date asked for
    stale: bool


class FxRates(dict):
    """``{currency: value of 1 unit in base}``. A currency with no rate at all is
    not a key (``missing``); ``quotes`` says each rate's source and age."""

    def __init__(
        self,
        base: str,
        values: Dict[str, float],
        quotes: Optional[Dict[str, FxQuote]] = None,
        missing: Iterable[str] = (),
    ) -> None:
        super().__init__(values)
        self.base = base
        self.quotes: Dict[str, FxQuote] = dict(quotes or {})
        self.missing: set[str] = set(missing)

    @property
    def stale(self) -> set[str]:
        return {currency for currency, quote in self.quotes.items() if quote.stale}

    @property
    def complete(self) -> bool:
        return not self.missing and not self.stale


# ─── Per-request notes ───────────────────────────────────────────────────────


@dataclass
class FxNotes:
    missing: set[str] = field(default_factory=set)
    stale: set[str] = field(default_factory=set)


_notes: ContextVar[Optional[FxNotes]] = ContextVar("capitalos_fx_notes", default=None)


@contextmanager
def fx_notes_scope() -> Iterator[FxNotes]:
    notes = FxNotes()
    token = _notes.set(notes)
    try:
        yield notes
    finally:
        _notes.reset(token)


class FxNotesMiddleware:
    """Gives every HTTP request its own FxNotes (read back by ``fx_status``)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        with fx_notes_scope():
            await self.app(scope, receive, send)


def _note(rates: FxRates) -> None:
    if rates.complete:
        return
    mark_degraded()
    notes = _notes.get()
    if notes is not None:
        notes.missing.update(rates.missing)
        notes.stale.update(rates.stale)


def fx_status() -> Dict[str, Any]:
    """Additive response fields: did this request value anything without a rate
    (excluded from totals) or with a rate older than the lookback?"""
    notes = _notes.get()
    missing = sorted(notes.missing) if notes else []
    stale = sorted(notes.stale - notes.missing) if notes else []
    return {
        "fx_incomplete": bool(missing),
        "fx_missing_currencies": missing,
        "fx_stale_currencies": stale,
    }


# ─── Providers ───────────────────────────────────────────────────────────────


def _http_get_json(url: str, params: Optional[dict] = None) -> dict:
    # Checked here as well, against the env itself, so tests (which set it)
    # can never reach a real provider even if a fake is missing.
    if os.getenv("FX_DISABLE_REMOTE", "0") == "1":
        raise RuntimeError("FX_DISABLE_REMOTE=1: FX providers are off")
    resp = httpx.get(url, params=params, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def _fetch_frankfurter(start: date, end: date) -> dict[date, dict[str, float]]:
    """ECB rates per business day in [start, end], EUR-based: {day: {quote: rate}}."""
    path = start.isoformat() if start == end else f"{start.isoformat()}..{end.isoformat()}"
    data = _http_get_json(f"https://api.frankfurter.app/{path}", {"from": "EUR"})
    raw = data.get("rates") or {}
    out: dict[date, dict[str, float]] = {}
    if raw and all(isinstance(v, dict) for v in raw.values()):
        for day, table in raw.items():
            out[date.fromisoformat(day)] = {k.upper(): float(v) for k, v in table.items()}
    elif raw and data.get("date"):
        out[date.fromisoformat(str(data["date"]))] = {k.upper(): float(v) for k, v in raw.items()}
    return out


def _fetch_erapi() -> tuple[date, dict[str, float]]:
    """Latest rates, USD-based, with the date they are for."""
    data = _http_get_json("https://open.er-api.com/v6/latest/USD")
    stamp = data.get("time_last_update_unix")
    day = (
        datetime.fromtimestamp(int(stamp), tz=timezone.utc).date()
        if stamp
        else datetime.now(tz=timezone.utc).date()
    )
    return day, {k.upper(): float(v) for k, v in (data.get("rates") or {}).items()}


def _store_rows(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    from app.db.session import engine

    stmt = text(
        """
        INSERT INTO fx_rates (rate_date, base, quote, rate, source, fetched_at)
        VALUES (:rate_date, :base, :quote, :rate, :source, :fetched_at)
        ON CONFLICT (rate_date, base, quote) DO UPDATE SET
          rate = excluded.rate, source = excluded.source, fetched_at = excluded.fetched_at
        WHERE fx_rates.rate <> excluded.rate
        RETURNING rate_date
        """
    )
    changed: list[date] = []
    with engine.begin() as conn:
        for row in rows:
            hit = conn.execute(stmt, row).first()
            if hit is not None:
                changed.append(_as_rate_date(hit[0]))
        if changed:
            # A new or corrected rate for a past date changes stored History
            # months from that date on (#138); today's rate marks nothing.
            from app.wealth_rollup_dirty import mark_rollups_dirty

            mark_rollups_dirty(conn, min(changed), reason="fx")  # type: ignore[arg-type]
    return len(rows)


def _as_rate_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _provider_once(name: str, start: date, end: date, fetch: Any) -> tuple[bool, list[dict[str, Any]]]:
    """Run one provider fetch for a range unless it ran recently (success: TTL,
    failure: negative TTL) and store what it returned. Returns whether it
    answered, plus its rows when they could not be stored (the store is
    best-effort: a fetched rate is still used if the write fails)."""
    key = ("provider", name, start, end)

    def _cached() -> Optional[tuple[bool, list[dict[str, Any]]]]:
        hit = _CACHE.get(key)
        if hit is None:
            return None
        stored_at, ok, unstored = hit
        ttl = _TTL_SECONDS if ok else _NEGATIVE_TTL_SECONDS
        return (ok, unstored or []) if time.time() - stored_at < ttl else None

    cached = _cached()
    if cached is not None:
        return cached
    with _fetch_lock(key):
        cached = _cached()
        if cached is not None:
            return cached
        unstored: list[dict[str, Any]] = []
        try:
            rows = fetch()
            ok = bool(rows)
        except Exception as exc:  # noqa: BLE001 - any provider failure means "no answer"
            logger.warning(
                "fx_provider_failed",
                extra={"event": "fx_provider_failed", "provider": name, "error_class": exc.__class__.__name__},
            )
            rows, ok = [], False
        if rows:
            try:
                _store_rows(rows)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "fx_store_write_failed",
                    extra={"event": "fx_store_write_failed", "provider": name, "error_class": exc.__class__.__name__},
                )
                unstored = rows
        _CACHE[key] = (time.time(), ok, unstored)
        return ok, unstored


def fill_rates(start: date, end: date, *, include_latest: bool = False) -> dict[str, tuple[bool, list[dict[str, Any]]]]:
    """Fetch [start, end] from Frankfurter (and, with ``include_latest``, today's
    open.er-api table) into fx_rates. Returns, per provider, whether it answered
    and any rows that could not be stored."""
    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    def _frankfurter() -> list[dict[str, Any]]:
        return [
            {"rate_date": day.isoformat(), "base": "EUR", "quote": quote, "rate": rate, "source": "frankfurter", "fetched_at": fetched_at}
            for day, table in _fetch_frankfurter(start, end).items()
            for quote, rate in table.items()
            if rate and rate > 0 and quote != "EUR"
        ]

    def _erapi() -> list[dict[str, Any]]:
        day, table = _fetch_erapi()
        return [
            {"rate_date": day.isoformat(), "base": "USD", "quote": quote, "rate": rate, "source": "open.er-api", "fetched_at": fetched_at}
            for quote, rate in table.items()
            if rate and rate > 0 and quote != "USD"
        ]

    result = {"frankfurter": _provider_once("frankfurter", start, end, _frankfurter)}
    if include_latest:
        today = datetime.now(tz=timezone.utc).date()
        result["open.er-api"] = _provider_once("open.er-api", today, today, _erapi)
    return result


def fill_daily() -> dict[str, bool]:
    """The scheduled fill: the last lookback window from Frankfurter plus today's
    open.er-api table (for currencies the ECB doesn't publish)."""
    today = datetime.now(tz=timezone.utc).date()
    for key in [k for k in _CACHE if k[0] == "provider"]:
        _CACHE.pop(key, None)  # a scheduled run always asks again
    result = fill_rates(today - timedelta(days=max(lookback_days(), 1)), today, include_latest=True)
    return {name: ok for name, (ok, _unstored) in result.items()}


def last_fill_at() -> Optional[datetime]:
    """When fx_rates last received a provider row for a recent date (within the
    lookback), i.e. when the daily fill last ran (None if never)."""
    from app.db.session import engine

    recent = (datetime.now(tz=timezone.utc).date() - timedelta(days=max(lookback_days(), 1))).isoformat()
    with engine.connect() as conn:
        value = conn.execute(
            text("SELECT MAX(fetched_at) FROM fx_rates WHERE rate_date >= :recent"), {"recent": recent}
        ).scalar()
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


# ─── Reading the store ───────────────────────────────────────────────────────


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dataclass
class _Rows:
    """Stored rows by date: {day: {(base, quote): (rate, source)}}."""

    by_day: dict[date, dict[tuple[str, str], tuple[float, str]]] = field(default_factory=dict)
    days: list[date] = field(default_factory=list)

    def add(self, day: date, base: str, quote: str, rate: float, source: str) -> None:
        table = self.by_day.setdefault(day, {})
        existing = table.get((base, quote))
        if existing is None or _SOURCE_PRIORITY.get(source, 9) < _SOURCE_PRIORITY.get(existing[1], 9):
            table[(base, quote)] = (rate, source)

    def finish(self) -> None:
        self.days = sorted(self.by_day)


def _query(sql: str, params: dict) -> list[Any]:
    """One read on its own connection; a failure (e.g. a table not migrated yet)
    is logged and reads as "no rows", so a page never fails over FX."""
    from app.db.session import engine

    try:
        with engine.connect() as conn:
            return list(conn.execute(text(sql).bindparams(bindparam("currencies", expanding=True)), params))
    except Exception as exc:  # noqa: BLE001
        logger.warning("fx_store_read_failed", extra={"event": "fx_store_read_failed", "error_class": exc.__class__.__name__})
        return []


def _load_rows(lo: date, hi: date, currencies: set[str]) -> _Rows:
    rows = _Rows()
    params = {"lo": lo.isoformat(), "hi": hi.isoformat(), "currencies": sorted(currencies)}
    for row in _query(
        """
        SELECT rate_date, base, quote, rate, source FROM fx_rates
        WHERE rate_date BETWEEN :lo AND :hi
          AND (quote IN :currencies OR base IN :currencies)
        """,
        params,
    ):
        if row[3] is not None and float(row[3]) > 0:
            rows.add(_as_date(row[0]), str(row[1]).upper(), str(row[2]).upper(), float(row[3]), str(row[4]))
    for row in _query(
        """
        SELECT report_date, from_currency, to_currency, rate FROM portfolio_fx_rates
        WHERE report_date BETWEEN :lo AND :hi
          AND (to_currency IN :currencies OR from_currency IN :currencies)
        """,
        params,
    ):
        if row[3] is not None and float(row[3]) > 0:
            # IBKR statement rates: 1 from_currency = rate to_currency.
            rows.add(_as_date(row[0]), str(row[1]).upper(), str(row[2]).upper(), float(row[3]), "ibkr")
    rows.finish()
    return rows


def _value_on(table: dict[tuple[str, str], tuple[float, str]], base: str, sym: str) -> Optional[tuple[float, str]]:
    """Value of 1 ``sym`` in ``base`` from one day's rows, via any shared base."""
    best: Optional[tuple[int, float, str]] = None
    pivots = {b for b, _q in table} | {base, sym}
    for pivot in pivots:
        to_base = (1.0, "") if pivot == base else table.get((pivot, base))
        to_sym = (1.0, "") if pivot == sym else table.get((pivot, sym))
        if to_base is None or to_sym is None:
            continue
        source = to_base[1] or to_sym[1]
        priority = max(_SOURCE_PRIORITY.get(to_base[1], -1), _SOURCE_PRIORITY.get(to_sym[1], -1))
        if best is None or priority < best[0]:
            best = (priority, to_base[0] / to_sym[0], source)
    return (best[1], best[2]) if best else None


def _find(rows: _Rows, base: str, sym: str, target: date, oldest: date) -> Optional[tuple[date, float, str]]:
    """Latest day in [oldest, target] that values ``sym`` in ``base``."""
    idx = bisect.bisect_right(rows.days, target)
    while idx > 0:
        idx -= 1
        day = rows.days[idx]
        if day < oldest:
            return None
        found = _value_on(rows.by_day[day], base, sym)
        if found:
            return day, found[0], found[1]
    return None


def _fallback_rates_from_env() -> dict[str, dict[str, float]]:
    raw = os.getenv("FX_FALLBACK_RATES", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict[str, float]] = {}
    for base, mapping in data.items():
        if not isinstance(mapping, dict):
            continue
        out[base.upper()] = {k.upper(): float(v) for k, v in mapping.items()}
    return out


def rate_date(value: Any) -> date:
    """The date rates are looked up for: the value's UTC date, capped at today."""
    today = datetime.now(tz=timezone.utc).date()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        day = value.astimezone(timezone.utc).date()
    else:
        day = _as_date(value)
    return min(day, today)


# ─── Public API ──────────────────────────────────────────────────────────────


def get_rates_by_date(dates: Iterable[Any], base: str, symbols: Iterable[str]) -> Dict[date, FxRates]:
    """``{date: FxRates}`` for each date (datetimes are reduced to their UTC date,
    capped at today). One store read for the whole range and at most one provider
    call per range, so converting many flows by their own date stays cheap."""
    base = base.upper()
    symbols_set = {str(s).upper() for s in symbols if s}
    symbols_set.discard(base)
    targets = sorted({rate_date(d) for d in dates})
    if not targets:
        return {}

    now = time.time()
    found: dict[tuple[date, str], Optional[FxQuote]] = {}
    todo: set[tuple[date, str]] = set()
    for day in targets:
        for sym in symbols_set:
            hit = _CACHE.get(("rate", day, base, sym))
            if hit is not None and now - hit[0] < hit[1]:
                found[(day, sym)] = hit[2]
            else:
                todo.add((day, sym))

    if todo:
        _resolve(todo, base, found)

    out: Dict[date, FxRates] = {}
    for day in targets:
        values = {base: 1.0}
        quotes: Dict[str, FxQuote] = {}
        missing: set[str] = set()
        for sym in symbols_set:
            quote = found.get((day, sym))
            if quote is None:
                missing.add(sym)
            else:
                values[sym] = quote.value
                quotes[sym] = quote
        rates = FxRates(base, values, quotes, missing)
        _note(rates)
        out[day] = rates
    return out


def get_rates(date_value: Any, base: str, symbols: Iterable[str]) -> FxRates:
    """{currency: value of 1 unit in base} on one date (see the module docstring).
    A currency without any rate is left out and listed in ``.missing``."""
    day = rate_date(date_value)
    by_date = get_rates_by_date([day], base, symbols)
    return by_date[day]


def _resolve(todo: set[tuple[date, str]], base: str, found: dict[tuple[date, str], Optional[FxQuote]]) -> None:
    lookback = lookback_days()
    today = datetime.now(tz=timezone.utc).date()
    days = sorted({day for day, _ in todo})
    syms = {sym for _, sym in todo}
    currencies = syms | {base}

    def _attempt(rows: _Rows, pairs: set[tuple[date, str]], oldest_days: int) -> set[tuple[date, str]]:
        """Fill ``found`` for pairs resolvable within ``oldest_days``; returns the
        pairs a provider might improve (nothing current, or a recent date whose
        newest row is a few days old)."""
        wanted: set[tuple[date, str]] = set()
        for day, sym in pairs:
            hit = _find(rows, base, sym, day, day - timedelta(days=oldest_days))
            if hit is None:
                wanted.add((day, sym))
                continue
            rate_day, value, source = hit
            age = (day - rate_day).days
            found[(day, sym)] = FxQuote(value, source, rate_day, age, age > lookback)
            if age > lookback or (day >= today - timedelta(days=lookback) and age > _REFRESH_AFTER_DAYS):
                wanted.add((day, sym))
        return wanted

    lo = days[0] - timedelta(days=lookback)
    rows = _load_rows(lo, days[-1], currencies)
    wanted = _attempt(rows, todo, lookback)

    if wanted and remote_enabled():
        want_days = sorted({day for day, _ in wanted})
        answered = fill_rates(
            want_days[0] - timedelta(days=lookback),
            want_days[-1],
            include_latest=want_days[-1] >= today,
        )
        if any(ok for ok, _unstored in answered.values()):
            rows = _load_rows(lo, days[-1], currencies)
            for _ok, unstored in answered.values():
                for row in unstored:
                    if row["quote"] in currencies or row["base"] in currencies:
                        rows.add(_as_date(row["rate_date"]), row["base"], row["quote"], float(row["rate"]), row["source"])
            rows.finish()
            wanted = _attempt(rows, wanted, lookback)

    # Nothing within the lookback: an older stored rate, flagged stale.
    unresolved = {pair for pair in wanted if found.get(pair) is None}
    if unresolved:
        old_lo = min(day for day, _ in unresolved) - timedelta(days=stale_max_days())
        older = _load_rows(old_lo, days[-1], currencies)
        _attempt(older, unresolved, stale_max_days())

    # Last resort: FX_FALLBACK_RATES (static, configured by the owner).
    fallback = _fallback_rates_from_env().get(base, {})
    for day, sym in todo:
        if found.get((day, sym)) is None and fallback.get(sym):
            found[(day, sym)] = FxQuote(1.0 / fallback[sym], "env", day, 0, False)

    stored_at = time.time()
    for day, sym in todo:
        quote = found.get((day, sym))
        settled = quote is not None and not quote.stale and (day, sym) not in wanted
        ttl = _TTL_SECONDS if settled or (quote is not None and quote.source == "env") else _NEGATIVE_TTL_SECONDS
        _CACHE[("rate", day, base, sym)] = (stored_at, ttl, quote)
