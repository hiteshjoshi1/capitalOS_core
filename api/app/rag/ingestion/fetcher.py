"""
URL fetcher for RAG ingestion.

Fetches content from HTTP/HTTPS URLs with configurable timeouts.
Returns raw bytes and detected content-type so the parser layer can decide
how to handle the content.

If the URL cannot be fetched (network unavailable, paywalled, etc.) the
caller should fall back to the manual ingestion path.
"""

import hashlib
from dataclasses import dataclass
from typing import Optional

import httpx

FETCH_TIMEOUT_SECONDS = 30
MAX_CONTENT_BYTES = 20 * 1024 * 1024  # 20 MB safety cap


@dataclass
class FetchResult:
    url: str
    content_type: str
    raw_bytes: bytes
    sha256: str
    status_code: int

    @classmethod
    def from_response(cls, response: httpx.Response) -> "FetchResult":
        raw = response.content[:MAX_CONTENT_BYTES]
        return cls(
            url=str(response.url),
            content_type=response.headers.get("content-type", "application/octet-stream"),
            raw_bytes=raw,
            sha256=hashlib.sha256(raw).hexdigest(),
            status_code=response.status_code,
        )


def fetch_url(url: str, timeout: float = FETCH_TIMEOUT_SECONDS) -> FetchResult:
    """
    Fetch a URL and return a FetchResult.

    Raises:
        httpx.HTTPError: on network/protocol errors.
        httpx.TimeoutException: if the request exceeds timeout.
        ValueError: if the HTTP status is not 2xx.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; CapitalOS-RAG/1.0; +https://github.com/capitalos)"
        )
    }
    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        response = client.get(url)
        if response.status_code >= 400:
            raise ValueError(f"HTTP {response.status_code} fetching {url}")
        return FetchResult.from_response(response)


def detect_source_type(content_type: str, url: str) -> str:
    """Heuristically detect source type from content-type and URL."""
    ct = content_type.lower()
    if "pdf" in ct or url.lower().endswith(".pdf"):
        return "pdf"
    if "html" in ct:
        return "html"
    if "text" in ct:
        return "text"
    # Fallback: guess from URL extension
    lower_url = url.lower()
    for ext, typ in [(".pdf", "pdf"), (".htm", "html"), (".html", "html"), (".txt", "text")]:
        if lower_url.endswith(ext):
            return typ
    return "html"
