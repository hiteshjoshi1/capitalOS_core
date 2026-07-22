from __future__ import annotations

import httpx

from app.rag.ingestion import fetcher


def test_fetch_url_sends_self_identifying_user_agent(monkeypatch):
    """
    The fetcher identifies itself honestly as a bot (CapitalOS-RAG) rather than
    impersonating a browser. A prior attempt to spoof a Chrome User-Agent to
    work around a source host's 403 was reverted: it didn't actually bypass
    that host's bot detection (confirmed to be TLS-fingerprint/behavioral, not
    header-based), so there was no upside left to justify the reduced
    transparency of pretending to be a real browser.
    """
    captured_headers = {}

    class FakeClient:
        def __init__(self, *, follow_redirects, timeout, headers):
            captured_headers.update(headers)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url):
            return httpx.Response(
                200,
                headers={"content-type": "text/plain"},
                content=b"ok",
                request=httpx.Request("GET", url),
            )

    monkeypatch.setattr(fetcher.httpx, "Client", FakeClient)

    result = fetcher.fetch_url("https://example.com/report.txt")

    assert result.raw_bytes == b"ok"
    assert captured_headers["User-Agent"] == "Mozilla/5.0 (compatible; CapitalOS-RAG/1.0; +https://github.com/capitalos)"
    assert captured_headers["Accept-Encoding"] == "identity"
