from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, Iterable

import httpx

_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[float, dict[str, float]]] = {}
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


def _fetch_rates_frankfurter(date_key: str, base: str, symbols_set: set[str]) -> dict[str, float]:
    if not symbols_set:
        return {base: 1.0}
    to_param = ",".join(sorted(symbols_set))
    url = f"https://api.frankfurter.app/{date_key}"
    params = {"from": base, "to": to_param}
    resp = httpx.get(url, params=params, timeout=10, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json()
    return {k.upper(): float(v) for k, v in data.get("rates", {}).items()}


def _fetch_rates_erapi(base: str, symbols_set: set[str]) -> dict[str, float]:
    if not symbols_set:
        return {base: 1.0}
    url = f"https://open.er-api.com/v6/latest/{base}"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    rates = data.get("rates", {})
    return {k.upper(): float(v) for k, v in rates.items() if k.upper() in symbols_set}


def get_rates(date: datetime, base: str, symbols: Iterable[str]) -> Dict[str, float]:
    base = base.upper()
    symbols_set = {s.upper() for s in symbols if s}
    symbols_set.discard(base)
    if os.getenv("FX_DISABLE_REMOTE", "0") == "1":
        return {s: 1.0 for s in symbols_set | {base}}

    date_key = _normalize_date(date).date().isoformat()
    cache_key = (date_key, base, tuple(sorted(symbols_set)))
    cached = _CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _TTL_SECONDS:
        cached_rates = cached[1]
        return {s: cached_rates.get(s, 1.0) for s in symbols_set | {base}}

    raw_rates: dict[str, float] = {}
    try:
        raw_rates = _fetch_rates_frankfurter(date_key, base, symbols_set)
    except Exception:
        raw_rates = {}

    if not raw_rates:
        try:
            raw_rates = _fetch_rates_erapi(base, symbols_set)
        except Exception:
            raw_rates = {}

    if not raw_rates:
        fallback = _fallback_rates_from_env().get(base, {})
        if fallback:
            raw_rates = {k: v for k, v in fallback.items() if k in symbols_set}
    if not raw_rates:
        raise httpx.HTTPError("FX providers unavailable and no fallback rate available")
    # Frankfurter returns: 1 base = rate * symbol
    # We need symbol -> base, so invert.
    rates = {k: (1.0 / v) if v else 1.0 for k, v in raw_rates.items()}
    rates[base] = 1.0

    missing = symbols_set.difference(raw_rates.keys())
    if missing and base != "EUR" and raw_rates:
        # Fallback: fetch EUR rates and cross-convert if base or symbols missing.
        fallback_symbols = set(missing)
        fallback_symbols.add(base)
        try:
            eur_raw = _fetch_rates_frankfurter(date_key, "EUR", fallback_symbols)
        except Exception:
            eur_raw = {}
        base_rate = eur_raw.get(base)
        if base_rate:
            for sym in missing:
                sym_rate = eur_raw.get(sym)
                if sym_rate:
                    rates[sym] = base_rate / sym_rate

    _CACHE[cache_key] = (now, rates)
    return {s: rates.get(s, 1.0) for s in symbols_set | {base}}
