from __future__ import annotations

import os
from typing import Dict, Iterable

import time
import threading

from app.crypto.http import json_request, request_with_retry

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
DEFILLAMA_BASE = "https://coins.llama.fi"
_CACHE: dict[tuple[str, str], tuple[float, dict[str, float]]] = {}
_CACHE_TTL_SECONDS = int(os.getenv("COINGECKO_CACHE_TTL_SECONDS", "600"))
_CG_MIN_INTERVAL_SECONDS = float(os.getenv("COINGECKO_MIN_INTERVAL_SECONDS", "1.0"))
_CG_LAST_CALL: float = 0.0
_CG_LOCK = threading.Lock()
_LLAMA_MIN_INTERVAL_SECONDS = float(os.getenv("DEFILLAMA_MIN_INTERVAL_SECONDS", "0.25"))
_LLAMA_LAST_CALL: float = 0.0
_LLAMA_LOCK = threading.Lock()
_LOG = __import__("logging").getLogger("capitalos.crypto")

EVM_PLATFORM = {
    "ethereum": "ethereum",
    "base": "base",
    "arbitrum": "arbitrum-one",
    "optimism": "optimistic-ethereum",
    "mantle": "mantle",
    "scroll": "scroll",
}

LLAMA_CHAIN = {
    "ethereum": "ethereum",
    "base": "base",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "mantle": "mantle",
    "scroll": "scroll",
}

NATIVE_IDS = {
    "ETH": "ethereum",
    "SOL": "solana",
    "MNT": "mantle",
}


def _is_valid_contract(addr: str) -> bool:
    if not addr:
        return False
    if not addr.startswith("0x"):
        return False
    if len(addr) != 42:
        return False
    return True


def lookup_contract_metadata(chain: str, contract: str) -> dict | None:
    platform = EVM_PLATFORM.get(chain)
    if not platform:
        return None
    if not _is_valid_contract(contract.lower()):
        return None
    url = f"{_base_url()}/coins/{platform}/contract/{contract}"
    try:
        return json_request("GET", url, headers=_headers(), timeout=10)
    except Exception:
        return None


def _headers() -> dict:
    key = os.getenv("COINGECKO_API_KEY", "").strip()
    if not key or not _use_pro():
        return {}
    return {"x-cg-pro-api-key": key}


def _base_url() -> str:
    override = os.getenv("COINGECKO_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    if _use_pro():
        return "https://pro-api.coingecko.com/api/v3"
    return COINGECKO_BASE


def _use_pro() -> bool:
    flag = os.getenv("COINGECKO_USE_PRO", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return True
    return False


def _cached(key: tuple[str, str]) -> dict[str, float] | None:
    cached = _CACHE.get(key)
    if not cached:
        return None
    ts, data = cached
    if time.time() - ts > _CACHE_TTL_SECONDS:
        return None
    return data


def _set_cache(key: tuple[str, str], data: dict[str, float]) -> None:
    _CACHE[key] = (time.time(), data)


def _fetch_token_prices(url: str, params: dict) -> dict | None:
    _throttle_coingecko()
    resp = request_with_retry(
        "GET",
        url,
        params=params,
        headers=_headers(),
        timeout=10,
        max_attempts=4,
        backoff_seconds=1.0,
        retry_statuses={429},
    )
    if resp.status_code != 200:
        try:
            body = resp.text
        except Exception:
            body = ""
        _LOG.warning("coingecko_http_error status=%s body=%s", resp.status_code, body[:500])
        return None
    try:
        return resp.json()
    except Exception:
        return None


def price_by_contract(chain: str, contracts: Iterable[str]) -> Dict[str, float]:
    raw = [c.lower() for c in contracts if c]
    invalid = [c for c in raw if not _is_valid_contract(c)]
    unique = {c for c in raw if _is_valid_contract(c)}
    if not unique:
        if invalid:
            _LOG.warning("contracts_invalid", extra={"count": len(invalid)})
        return {}
    results = _defillama_price_by_contract(chain, unique)
    missing = {c for c in unique if c not in results}
    if missing:
        results.update(_coingecko_price_by_contract(chain, missing))
    return results


def _coingecko_price_by_contract(chain: str, contracts: Iterable[str]) -> Dict[str, float]:
    platform = EVM_PLATFORM.get(chain)
    if not platform:
        return {}
    unique = {c for c in contracts if _is_valid_contract(c)}
    if not unique:
        return {}
    results: Dict[str, float] = {}
    url = f"{_base_url()}/simple/token_price/{platform}"

    def fetch_chunk(chunk: list[str]) -> None:
        if not chunk:
            return
        chunk_key = ",".join(chunk)
        cache_key = ("contract", f"{platform}:{chunk_key}")
        cached = _cached(cache_key)
        if cached is not None:
            results.update(cached)
            return
        params = {"contract_addresses": chunk_key, "vs_currencies": "usd"}
        data = _fetch_token_prices(url, params)
        if data is None:
            _LOG.warning(
                "coingecko_chunk_failed",
                extra={"chain": chain, "count": len(chunk)},
            )
            if len(chunk) == 1:
                return
            mid = len(chunk) // 2
            fetch_chunk(chunk[:mid])
            fetch_chunk(chunk[mid:])
            return
        out: Dict[str, float] = {}
        for k, v in data.items():
            price = v.get("usd")
            if price is not None:
                out[k.lower()] = float(price)
        _set_cache(cache_key, out)
        results.update(out)

    contracts_list = list(unique)
    chunk_size = int(os.getenv("COINGECKO_CHUNK_SIZE", "20"))
    for idx in range(0, len(contracts_list), chunk_size):
        fetch_chunk(contracts_list[idx:idx + chunk_size])
    _LOG.info(
        "coingecko_contracts_priced",
        extra={"chain": chain, "requested": len(unique), "priced": len(results)},
    )
    return results


def price_by_mint(mints: Iterable[str]) -> Dict[str, float]:
    unique = {m.lower() for m in mints if m}
    if not unique:
        return {}
    results = _defillama_price_by_mint(unique)
    missing = {m for m in unique if m not in results}
    if missing:
        results.update(_coingecko_price_by_mint(missing))
    return results


def _coingecko_price_by_mint(mints: Iterable[str]) -> Dict[str, float]:
    unique = {m.lower() for m in mints if m}
    if not unique:
        return {}
    results: Dict[str, float] = {}
    url = f"{_base_url()}/simple/token_price/solana"

    def fetch_chunk(chunk: list[str]) -> None:
        if not chunk:
            return
        chunk_key = ",".join(chunk)
        cache_key = ("mint", chunk_key)
        cached = _cached(cache_key)
        if cached is not None:
            results.update(cached)
            return
        params = {"contract_addresses": chunk_key, "vs_currencies": "usd"}
        data = _fetch_token_prices(url, params)
        if data is None:
            if len(chunk) == 1:
                return
            mid = len(chunk) // 2
            fetch_chunk(chunk[:mid])
            fetch_chunk(chunk[mid:])
            return
        out: Dict[str, float] = {}
        for k, v in data.items():
            price = v.get("usd")
            if price is not None:
                out[k.lower()] = float(price)
        _set_cache(cache_key, out)
        results.update(out)

    mints_list = list(unique)
    chunk_size = int(os.getenv("COINGECKO_CHUNK_SIZE", "20"))
    for idx in range(0, len(mints_list), chunk_size):
        fetch_chunk(mints_list[idx:idx + chunk_size])
    return results


def price_by_symbol(symbol: str) -> float | None:
    coin_id = NATIVE_IDS.get(symbol.upper())
    if not coin_id:
        return None
    llama_price = _defillama_price_by_symbol(coin_id)
    if llama_price is not None:
        return llama_price
    return _coingecko_price_by_symbol(coin_id)


def _coingecko_price_by_symbol(coin_id: str) -> float | None:
    cache_key = ("symbol", coin_id)
    cached = _cached(cache_key)
    if cached is not None:
        return cached.get("usd")
    url = f"{_base_url()}/simple/price"
    params = {"ids": coin_id, "vs_currencies": "usd"}
    try:
        _throttle_coingecko()
        data = json_request("GET", url, params=params, headers=_headers(), timeout=10)
    except Exception:
        return None
    price = data.get(coin_id, {}).get("usd")
    if price is not None:
        _set_cache(cache_key, {"usd": float(price)})
        return float(price)
    return None


def _throttle_coingecko() -> None:
    global _CG_LAST_CALL
    if _CG_MIN_INTERVAL_SECONDS <= 0:
        return
    with _CG_LOCK:
        now = time.time()
        wait = _CG_MIN_INTERVAL_SECONDS - (now - _CG_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _CG_LAST_CALL = time.time()


def _throttle_defillama() -> None:
    global _LLAMA_LAST_CALL
    if _LLAMA_MIN_INTERVAL_SECONDS <= 0:
        return
    with _LLAMA_LOCK:
        now = time.time()
        wait = _LLAMA_MIN_INTERVAL_SECONDS - (now - _LLAMA_LAST_CALL)
        if wait > 0:
            time.sleep(wait)
        _LLAMA_LAST_CALL = time.time()


def _defillama_price_by_contract(chain: str, contracts: Iterable[str]) -> Dict[str, float]:
    llama_chain = LLAMA_CHAIN.get(chain)
    if not llama_chain:
        return {}
    unique = {c for c in contracts if _is_valid_contract(c)}
    if not unique:
        return {}
    coins = [f"{llama_chain}:{c}" for c in unique]
    prices = _defillama_prices(coins)
    out: Dict[str, float] = {}
    for c in unique:
        key = f"{llama_chain}:{c}"
        price = prices.get(key)
        if price is not None:
            out[c] = price
    _LOG.info(
        "defillama_contracts_priced",
        extra={"chain": chain, "requested": len(unique), "priced": len(out)},
    )
    return out


def _defillama_price_by_mint(mints: Iterable[str]) -> Dict[str, float]:
    unique = {m.lower() for m in mints if m}
    if not unique:
        return {}
    coins = [f"solana:{m}" for m in unique]
    prices = _defillama_prices(coins)
    out: Dict[str, float] = {}
    for m in unique:
        key = f"solana:{m}"
        price = prices.get(key)
        if price is not None:
            out[m] = price
    return out


def _defillama_price_by_symbol(coin_id: str) -> float | None:
    key = f"coingecko:{coin_id}"
    cache_key = ("llama_symbol", key)
    cached = _cached(cache_key)
    if cached is not None:
        return cached.get("usd")
    prices = _defillama_prices([key])
    price = prices.get(key)
    if price is not None:
        _set_cache(cache_key, {"usd": float(price)})
        return float(price)
    return None


def _defillama_prices(coins: Iterable[str]) -> Dict[str, float]:
    coins_list = [c for c in coins if c]
    if not coins_list:
        return {}
    results: Dict[str, float] = {}
    chunk_size = int(os.getenv("DEFILLAMA_CHUNK_SIZE", "50"))
    for idx in range(0, len(coins_list), chunk_size):
        chunk = coins_list[idx:idx + chunk_size]
        chunk_key = ",".join(chunk)
        cache_key = ("llama", chunk_key)
        cached = _cached(cache_key)
        if cached is not None:
            results.update(cached)
            continue
        url = f"{DEFILLAMA_BASE}/prices/current/{chunk_key}"
        _throttle_defillama()
        resp = request_with_retry(
            "GET",
            url,
            timeout=10,
            max_attempts=4,
            backoff_seconds=1.0,
            retry_statuses={429, 500, 502, 503, 504},
        )
        if resp.status_code != 200:
            _LOG.warning("defillama_http_error status=%s body=%s", resp.status_code, resp.text[:500])
            continue
        try:
            payload = resp.json()
        except Exception:
            continue
        coins_data = payload.get("coins", {}) if isinstance(payload, dict) else {}
        out: Dict[str, float] = {}
        for key, meta in coins_data.items():
            price = meta.get("price") if isinstance(meta, dict) else None
            if price is not None:
                out[key] = float(price)
        _set_cache(cache_key, out)
        results.update(out)
    return results
