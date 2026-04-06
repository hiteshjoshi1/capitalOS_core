"""
RAG source discovery service.

Reads discovery_seeds from config/rag_authors.yaml and extracts child source
URLs from archive/index pages. Registers discovered URLs into rag_sources.

Design rules:
- Deterministic and config/rule-driven (not LLM-driven).
- Discovery and ingestion are separate phases.
- Deduplicates URLs before inserting into rag_sources.
- Supports prefer_type rule: when both PDF and HTML variants of the same
  effective URL exist, keep the preferred type and drop the other.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import requests

from app.rag.ingestion.fetcher import decode_response_bytes

log = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 30
MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB for archive pages


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class DiscoveredSource:
    url: str
    source_type: str  # pdf | html | text


@dataclass
class DiscoverySeed:
    url: str
    seed_type: str = "archive_page"   # archive_page | direct_source
    link_patterns: list[str] = field(default_factory=list)
    base_url: Optional[str] = None
    domain_filter: Optional[str] = None
    prefer_type: Optional[str] = None  # pdf | html — prefer this type when duplicates exist
    source_type: Optional[str] = None  # for direct_source seeds


@dataclass
class DiscoveryResult:
    author_id: str
    seed_url: str
    discovered: list[DiscoveredSource]
    registered: int
    skipped_duplicate: int
    errors: list[str] = field(default_factory=list)


# ── URL helpers ───────────────────────────────────────────────────────────────


def _normalize_url(url: str) -> str:
    """Remove fragments and normalise trailing slashes for deduplication."""
    parsed = urlparse(url)
    # Drop fragment
    normalised = urlunparse(parsed._replace(fragment=""))
    return normalised.rstrip("/")


def _url_stem(url: str) -> str:
    """
    Return the URL without its extension.

    Used to detect duplicate variants (e.g., foo.pdf vs foo.html).
    """
    path = urlparse(url).path
    dot = path.rfind(".")
    if dot > 0:
        path_no_ext = path[:dot]
    else:
        path_no_ext = path
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=path_no_ext, fragment=""))


def _detect_source_type_from_url(url: str, content_type: str = "") -> str:
    """Determine source type from URL extension and optional content-type."""
    lower = url.lower()
    ct = content_type.lower()
    if "pdf" in ct or lower.endswith(".pdf"):
        return "pdf"
    if "html" in ct or lower.endswith((".htm", ".html")):
        return "html"
    if "text" in ct or lower.endswith(".txt"):
        return "text"
    return "html"  # default for unfamiliar archive links


# ── Link extraction ───────────────────────────────────────────────────────────


def _extract_links_from_html(html_bytes: bytes, page_url: str, base_url: Optional[str]) -> list[str]:
    """Extract all href links from an HTML page, resolving relative URLs."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        raise RuntimeError("beautifulsoup4 is required for source discovery. pip install beautifulsoup4")

    effective_base = base_url or page_url
    html = html_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        absolute = urljoin(effective_base, href)
        links.append(absolute)
    return links


def _apply_domain_filter(links: list[str], domain_filter: Optional[str]) -> list[str]:
    """Keep only links whose netloc contains domain_filter."""
    if not domain_filter:
        return links
    return [u for u in links if domain_filter in urlparse(u).netloc]


def _apply_pattern_filter(links: list[str], patterns: list[str]) -> list[str]:
    """Keep links matching at least one regex pattern (if patterns are given)."""
    if not patterns:
        return links
    compiled = [re.compile(p) for p in patterns]
    return [u for u in links if any(rx.search(u) for rx in compiled)]


# ── Preference deduplication ─────────────────────────────────────────────────


def apply_prefer_type(
    sources: list[DiscoveredSource],
    prefer_type: Optional[str],
) -> list[DiscoveredSource]:
    """
    When prefer_type is set, collapse duplicate URL stems:
    - If both PDF and HTML variants of the same stem exist, keep only the preferred type.
    - Otherwise keep all variants.

    Returns deduplicated list.
    """
    if not prefer_type:
        # Plain deduplication by normalised URL only
        seen: set[str] = set()
        result: list[DiscoveredSource] = []
        for src in sources:
            norm = _normalize_url(src.url)
            if norm not in seen:
                seen.add(norm)
                result.append(src)
        return result

    # Group by URL stem
    by_stem: dict[str, list[DiscoveredSource]] = {}
    for src in sources:
        stem = _url_stem(_normalize_url(src.url))
        by_stem.setdefault(stem, []).append(src)

    result = []
    for stem, variants in by_stem.items():
        if len(variants) == 1:
            result.append(variants[0])
            continue
        # Multiple variants for the same stem — apply preference
        preferred = [v for v in variants if v.source_type == prefer_type]
        if preferred:
            result.append(preferred[0])
        else:
            result.append(variants[0])  # fallback: take first

    return result


# ── Seed processing ───────────────────────────────────────────────────────────


def _process_seed(seed: DiscoverySeed) -> tuple[list[DiscoveredSource], list[str]]:
    """
    Process a single discovery seed.

    Returns (discovered_sources, errors).
    """
    errors: list[str] = []

    if seed.seed_type == "direct_source":
        # The URL itself is the source — no archive fetching needed
        source_type = seed.source_type or _detect_source_type_from_url(seed.url)
        return [DiscoveredSource(url=seed.url, source_type=source_type)], errors

    # Archive/index page — fetch and extract child links
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; CapitalOS-RAG/1.0; +https://github.com/capitalos)",
            # Some sites return brotli/zstd-compressed HTML that this runtime
            # does not transparently decode. Request identity encoding so the
            # extracted archive page is parseable deterministically.
            "Accept-Encoding": "identity",
        }
        with httpx.Client(follow_redirects=True, timeout=FETCH_TIMEOUT_SECONDS, headers=headers) as client:
            response = client.get(seed.url)
            if response.status_code >= 400:
                errors.append(f"HTTP {response.status_code} fetching archive page {seed.url}")
                return [], errors
            try:
                raw = decode_response_bytes(response)[:MAX_CONTENT_BYTES]
                content_type = response.headers.get("content-type", "text/html")
            except Exception:
                fallback = requests.get(seed.url, headers=headers, timeout=FETCH_TIMEOUT_SECONDS, allow_redirects=True)
                if fallback.status_code >= 400:
                    errors.append(f"HTTP {fallback.status_code} fetching archive page {seed.url}")
                    return [], errors
                raw = fallback.content[:MAX_CONTENT_BYTES]
                content_type = fallback.headers.get("content-type", "text/html")
    except Exception as exc:
        errors.append(f"Network error fetching {seed.url}: {exc}")
        return [], errors

    # If the archive page itself is a PDF (unusual but possible), treat as direct
    if "pdf" in content_type.lower():
        return [DiscoveredSource(url=seed.url, source_type="pdf")], errors

    links = _extract_links_from_html(raw, seed.url, seed.base_url)
    links = _apply_domain_filter(links, seed.domain_filter)
    links = _apply_pattern_filter(links, seed.link_patterns)

    sources = [
        DiscoveredSource(url=lnk, source_type=_detect_source_type_from_url(lnk))
        for lnk in links
    ]

    sources = apply_prefer_type(sources, seed.prefer_type)
    return sources, errors


# ── Config parsing ────────────────────────────────────────────────────────────


def _parse_seeds_from_config(author_cfg: dict) -> list[DiscoverySeed]:
    """Parse discovery_seeds list from a single author config dict."""
    raw = author_cfg.get("discovery_seeds", [])
    seeds: list[DiscoverySeed] = []
    for entry in raw:
        seed = DiscoverySeed(
            url=entry["url"],
            seed_type=entry.get("seed_type", "archive_page"),
            link_patterns=entry.get("link_patterns", []),
            base_url=entry.get("base_url"),
            domain_filter=entry.get("domain_filter"),
            prefer_type=entry.get("prefer_type"),
            source_type=entry.get("source_type"),
        )
        seeds.append(seed)
    return seeds


# ── DB helpers ────────────────────────────────────────────────────────────────


def _existing_urls_for_author(author_id: str, db) -> set[str]:
    """Return the set of normalised URLs already registered for this author."""
    from app.models.rag import RagSource

    rows = db.query(RagSource.url).filter(
        RagSource.author_id == author_id,
        RagSource.url.isnot(None),
    ).all()
    return {_normalize_url(r.url) for r in rows if r.url}


def _register_sources(
    author_id: str,
    sources: list[DiscoveredSource],
    existing_urls: set[str],
    db,
) -> tuple[int, int]:
    """
    Insert new rag_sources rows; skip duplicates.

    Returns (registered_count, skipped_count).
    """
    from app.models.rag import RagSource

    registered = 0
    skipped = 0
    for src in sources:
        norm = _normalize_url(src.url)
        if norm in existing_urls:
            skipped += 1
            continue
        row = RagSource(
            author_id=author_id,
            url=src.url,
            source_type=src.source_type,
            status="pending",
        )
        db.add(row)
        existing_urls.add(norm)  # track within this call
        registered += 1
    return registered, skipped


# ── Public API ────────────────────────────────────────────────────────────────


def discover_sources_for_author(
    author_id: str,
    author_cfg: dict,
    db,
) -> list[DiscoveryResult]:
    """
    Discover child source URLs for an author from their config discovery_seeds.

    For each seed:
    - If seed_type == direct_source, register the URL directly.
    - If seed_type == archive_page, fetch the page, extract links, filter,
      deduplicate, apply prefer_type rule, then register to rag_sources.

    Returns a list of DiscoveryResult (one per seed).
    The caller is responsible for db.commit().
    """
    seeds = _parse_seeds_from_config(author_cfg)
    if not seeds:
        return []

    existing_urls = _existing_urls_for_author(author_id, db)
    results: list[DiscoveryResult] = []

    for seed in seeds:
        log.info("Discovering sources for %s from seed %s", author_id, seed.url)
        discovered, errors = _process_seed(seed)

        registered, skipped = _register_sources(author_id, discovered, existing_urls, db)
        results.append(
            DiscoveryResult(
                author_id=author_id,
                seed_url=seed.url,
                discovered=discovered,
                registered=registered,
                skipped_duplicate=skipped,
                errors=errors,
            )
        )

    return results
