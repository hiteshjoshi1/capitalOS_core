from __future__ import annotations

import time
from typing import Any, Mapping

import httpx


def request_with_retry(
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    backoff_seconds: float = 0.5,
    timeout: int = 10,
    retry_statuses: set[int] | None = None,
    **kwargs: Any,
) -> httpx.Response:
    if retry_statuses is None:
        retry_statuses = {429, 500, 502, 503, 504}
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = httpx.request(method, url, timeout=timeout, **kwargs)
            if resp.status_code in retry_statuses:
                if attempt == max_attempts:
                    return resp
                time.sleep(backoff_seconds * attempt)
                continue
            return resp
        except Exception as exc:  # pragma: no cover - exercised via adapters tests
            last_exc = exc
            if attempt == max_attempts:
                break
            time.sleep(backoff_seconds * attempt)
    if last_exc:
        raise last_exc
    raise RuntimeError("request_with_retry failed without exception")


def json_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    json: Any | None = None,
    timeout: int = 10,
    max_attempts: int = 3,
) -> dict:
    resp = request_with_retry(
        method,
        url,
        headers=headers,
        params=params,
        json=json,
        timeout=timeout,
        max_attempts=max_attempts,
    )
    resp.raise_for_status()
    return resp.json()
