from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import Dict, Iterable

import httpx

_CACHE: dict[tuple[str, str], tuple[float, dict[str, float]]] = {}
_TTL_SECONDS = 900


def _static_rates() -> dict | None:
    raw = os.getenv("FX_STATIC_RATES", "")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_rates(date: datetime, base: str, symbols: Iterable[str]) -> Dict[str, float]:
    base = base.upper()
    symbols_set = {s.upper() for s in symbols if s}
    symbols_set.discard(base)

    static = _static_rates()
    if static and base in static:
        rates = {k.upper(): float(v) for k, v in static[base].items()}
        rates[base] = 1.0
        return {s: rates.get(s, 1.0) for s in symbols_set | {base}}

    date_key = date.date().isoformat()
    cache_key = (date_key, base)
    cached = _CACHE.get(cache_key)
    now = time.time()
    if cached and now - cached[0] < _TTL_SECONDS:
        cached_rates = cached[1]
        return {s: cached_rates.get(s, 1.0) for s in symbols_set | {base}}

    if not symbols_set:
        return {base: 1.0}

    to_param = ",".join(sorted(symbols_set))
    url = f"https://api.frankfurter.app/{date_key}"
    params = {"from": base, "to": to_param}

    resp = httpx.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    raw_rates = {k.upper(): float(v) for k, v in data.get("rates", {}).items()}
    # Frankfurter returns: 1 base = rate * symbol
    # We need symbol -> base, so invert.
    rates = {k: (1.0 / v) if v else 1.0 for k, v in raw_rates.items()}
    rates[base] = 1.0

    _CACHE[cache_key] = (now, rates)
    return {s: rates.get(s, 1.0) for s in symbols_set | {base}}
