from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable

import httpx

from app.valuation_cache import mark_degraded

# Keys: ("rate", date, base, currency) -> (stored_at, rate);
#       ("table", provider, date, base) -> (stored_at, {currency: rate}).
_CACHE: dict[tuple, tuple[float, Any]] = {}
try:
    _TTL_SECONDS = max(1, int(os.getenv("FX_CACHE_TTL_SECONDS", "86400")))
except ValueError:
    _TTL_SECONDS = 86400
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

def _normalize_date(date: datetime) -> datetime:
    now = datetime.now(tz=timezone.utc)
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return min(date, now)


def _fetch_rates_frankfurter(date_key: str, base: str, symbols_set: set[str] | None = None) -> dict[str, float]:
    """1 base = rate x symbol, per currency. symbols_set=None asks for every
    currency the provider has (one call serves every currency for that date)."""
    if symbols_set is not None and not symbols_set:
        return {base: 1.0}
    url = f"https://api.frankfurter.app/{date_key}"
    params = {"from": base}
    if symbols_set is not None:
        params["to"] = ",".join(sorted(symbols_set))
    resp = httpx.get(url, params=params, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    return {k.upper(): float(v) for k, v in data.get("rates", {}).items()}


def _fetch_rates_erapi(base: str, symbols_set: set[str] | None = None) -> dict[str, float]:
    if symbols_set is not None and not symbols_set:
        return {base: 1.0}
    url = f"https://open.er-api.com/v6/latest/{base}"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    rates = data.get("rates", {})
    return {k.upper(): float(v) for k, v in rates.items() if symbols_set is None or k.upper() in symbols_set}


# ─── Provider tables (#147) ──────────────────────────────────────────────────
# A request asks for rates many times with different currency sets. The cache
# used to be keyed by the exact set, so each new set meant another provider call,
# and failures weren't cached, so an outage cost a timeout per call. Now each
# provider is asked once per (date, base) for *all* its currencies; that table is
# cached for FX_CACHE_TTL_SECONDS, and a failed or empty answer for
# FX_NEGATIVE_CACHE_SECONDS (default 60). Everything lives in _CACHE, so
# _CACHE.clear() resets it all.

try:
    _NEGATIVE_TTL_SECONDS = max(0, int(os.getenv("FX_NEGATIVE_CACHE_SECONDS", "60")))
except ValueError:
    _NEGATIVE_TTL_SECONDS = 60

_FETCH_LOCKS: dict[tuple, threading.Lock] = {}
_FETCH_LOCKS_GUARD = threading.Lock()


def _fetch_lock(key: tuple) -> threading.Lock:
    with _FETCH_LOCKS_GUARD:
        lock = _FETCH_LOCKS.get(key)
        if lock is None:
            lock = _FETCH_LOCKS[key] = threading.Lock()
        return lock


def _provider_table(provider: str, date_key: str, base: str) -> dict[str, float]:
    """{currency: 1 base in that currency} from one provider, or {} when it is
    down or has nothing (that is remembered for a minute)."""
    key = ("table", provider, date_key, base)

    def _cached() -> dict[str, float] | None:
        hit = _CACHE.get(key)
        if hit is None:
            return None
        stored_at, table = hit
        ttl = _TTL_SECONDS if table else _NEGATIVE_TTL_SECONDS
        return table if time.time() - stored_at < ttl else None

    table = _cached()
    if table is not None:
        return table
    with _fetch_lock(key):
        table = _cached()  # another request may have fetched it meanwhile
        if table is not None:
            return table
        try:
            if provider == "frankfurter":
                table = _fetch_rates_frankfurter(date_key, base)
            else:
                table = _fetch_rates_erapi(base)
        except Exception:
            table = {}
        table = {k: v for k, v in table.items() if k != base}
        _CACHE[key] = (time.time(), table)
        return table


def get_rates(date: datetime, base: str, symbols: Iterable[str]) -> Dict[str, float]:
    """{currency: value of 1 unit in base} for each symbol and the base.

    Per currency the source order is unchanged: Frankfurter (dated); when
    Frankfurter answered but lacks it, the EUR cross rate from Frankfurter;
    else open.er-api (latest); else FX_FALLBACK_RATES. If no requested currency
    resolves at all this raises, as before; otherwise an unresolved one is 1.0.
    """
    base = base.upper()
    symbols_set = {s.upper() for s in symbols if s}
    symbols_set.discard(base)
    if os.getenv("FX_DISABLE_REMOTE", "0") == "1":
        return {s: 1.0 for s in symbols_set | {base}}

    date_key = _normalize_date(date).date().isoformat()
    now = time.time()
    rates: dict[str, float] = {base: 1.0}
    missing: set[str] = set()
    for sym in symbols_set:
        cached = _CACHE.get(("rate", date_key, base, sym))
        if cached and now - cached[0] < _TTL_SECONDS:
            rates[sym] = cached[1]
        else:
            missing.add(sym)
    if not missing:
        return rates

    resolved: dict[str, float] = {}
    frankfurter = _provider_table("frankfurter", date_key, base) if missing else {}
    for sym in missing:
        if frankfurter.get(sym):
            resolved[sym] = 1.0 / frankfurter[sym]
    unresolved = missing - resolved.keys()
    if unresolved and frankfurter and base != "EUR":
        # Frankfurter answered but lacks these: cross-convert through EUR.
        eur = _provider_table("frankfurter", date_key, "EUR")
        base_rate = eur.get(base)
        if base_rate:
            for sym in list(unresolved):
                sym_rate = eur.get(sym)
                if sym_rate:
                    resolved[sym] = base_rate / sym_rate
        unresolved = missing - resolved.keys()
    if unresolved:
        erapi = _provider_table("erapi", date_key, base)
        for sym in unresolved:
            if erapi.get(sym):
                resolved[sym] = 1.0 / erapi[sym]
        unresolved = missing - resolved.keys()
    if unresolved:
        fallback = _fallback_rates_from_env().get(base, {})
        for sym in unresolved:
            if fallback.get(sym):
                resolved[sym] = 1.0 / fallback[sym]
        unresolved = missing - resolved.keys()

    if missing and not resolved and len(missing) == len(symbols_set):
        raise httpx.HTTPError("FX providers unavailable and no fallback rate available")
    stored_at = time.time()
    for sym, rate in resolved.items():
        _CACHE[("rate", date_key, base, sym)] = (stored_at, rate)
    rates.update(resolved)
    if unresolved:
        # An unresolved currency is valued at 1.0, as before (#139 revisits
        # that); keep a result built on it out of the shared valuation cache.
        mark_degraded()
        rates.update({sym: 1.0 for sym in unresolved})
    return rates
