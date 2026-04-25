"""
Tests for RAG source discovery and bulk ingestion (Issue 129).

Coverage:
  - Discovery seed parsing from config
  - Link extraction and filtering
  - URL deduplication
  - prefer_type rule (PDF over HTML)
  - direct_source seed type
  - Archive page fetch (mocked)
  - rag_sources registration and deduplication
  - discover_sources_for_author integration
  - bulk_ingest_author
  - Failure category reporting
  - New API endpoints: /rag/authors/{id}/discover, /rag/authors/{id}/bulk-ingest
  - Config includes full PRD seed author set
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


def _repo_config_path() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "config" / "rag_authors.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Config file not found: config/rag_authors.yaml")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rag_yaml_with_seeds(tmp_path_factory):
    """Minimal rag_authors.yaml with discovery_seeds for testing."""
    content = r"""
authors:
  - id: buffett_test
    name: Warren Buffett Test
    enabled: true
    domains: [investing]
    expertise_tags: [moat]
    overall_weight: 4.5
    role_type: investor
    reasoning_lens:
      focus: [capital allocation]
      avoid: [macro]
      biases: [prefers simplicity]
    discovery_seeds:
      - url: 'https://www.example.com/letters/'
        seed_type: archive_page
        link_patterns:
          - '.*ltr\.pdf$'
          - '.*[0-9]{4}ltr\.html$'
        base_url: 'https://www.example.com/letters/'
        domain_filter: example.com
        prefer_type: pdf

  - id: nick_test
    name: Nick Sleep Test
    enabled: true
    domains: [investing]
    expertise_tags: [scale]
    overall_weight: 3.5
    role_type: investor
    discovery_seeds:
      - url: "https://igyfoundation.org.uk/nomad.pdf"
        seed_type: direct_source
        source_type: pdf

  - id: no_seeds_author
    name: No Seeds Author
    enabled: true
    domains: [investing]
    expertise_tags: []
    overall_weight: 2.0
    role_type: investor
"""
    p = tmp_path_factory.mktemp("config") / "rag_authors.yaml"
    p.write_text(content)
    return str(p)


@pytest.fixture(scope="module")
def sqlite_session():
    """In-memory-style SQLite session with RAG tables."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_path = "/tmp/capitalos_discovery_test.db"
    try:
        os.remove(db_path)
    except FileNotFoundError:
        pass

    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    ddl = [
        """CREATE TABLE IF NOT EXISTS rag_authors (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            domains TEXT NOT NULL DEFAULT '[]', expertise_tags TEXT NOT NULL DEFAULT '[]',
            overall_weight REAL NOT NULL DEFAULT 1.0, role_type TEXT,
            config_source TEXT NOT NULL DEFAULT 'test',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS rag_author_cards (
            author_id TEXT PRIMARY KEY, focus_areas TEXT NOT NULL DEFAULT '[]',
            avoid_patterns TEXT NOT NULL DEFAULT '[]', biases TEXT NOT NULL DEFAULT '[]',
            prompt_adapter TEXT NOT NULL DEFAULT '{}', enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS rag_sources (
            id TEXT PRIMARY KEY, user_id INTEGER, author_id TEXT NOT NULL, url TEXT,
            source_type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            hash TEXT, selective_options TEXT, ingestion_config TEXT,
            raw_text TEXT, clean_text TEXT, last_ingested_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS rag_ingestion_jobs (
            id TEXT PRIMARY KEY, user_id INTEGER, source_id TEXT NOT NULL, batch_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            failure_category TEXT, error TEXT,
            stats_json TEXT NOT NULL DEFAULT '{}',
            started_at TIMESTAMP, finished_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS rag_documents (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL,
            author_id TEXT, parent_document_id TEXT, source_document_index INTEGER NOT NULL DEFAULT 0,
            title TEXT, published_at TEXT, publication_year INTEGER,
            venue TEXT, collection TEXT, canonical_work_id TEXT, canonical_status TEXT,
            dedupe_priority INTEGER, source_section TEXT, note_taker TEXT, work_type TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}', raw_text TEXT, clean_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS rag_chunks (
            id TEXT PRIMARY KEY, document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL, text TEXT NOT NULL,
            token_count INTEGER, metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        """CREATE TABLE IF NOT EXISTS rag_embeddings (
            chunk_id TEXT PRIMARY KEY, embedding TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT 'mock',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
    ]
    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))
        # Clean state at start of module to ensure isolation across runs
        for tbl in ["rag_embeddings", "rag_chunks", "rag_documents",
                    "rag_ingestion_jobs", "rag_sources", "rag_author_cards", "rag_authors"]:
            try:
                conn.execute(text(f"DELETE FROM {tbl}"))
            except Exception:
                pass

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session


# ── 1. Discovery seed parsing ─────────────────────────────────────────────────


class TestDiscoverySeedParsing:
    def test_parses_archive_page_seed(self):
        from app.rag.discovery import _parse_seeds_from_config

        author_cfg = {
            "discovery_seeds": [
                {
                    "url": "https://example.com/archive/",
                    "seed_type": "archive_page",
                    "link_patterns": [".*\\.pdf$"],
                    "domain_filter": "example.com",
                    "prefer_type": "pdf",
                }
            ]
        }
        seeds = _parse_seeds_from_config(author_cfg)
        assert len(seeds) == 1
        s = seeds[0]
        assert s.url == "https://example.com/archive/"
        assert s.seed_type == "archive_page"
        assert s.link_patterns == [".*\\.pdf$"]
        assert s.domain_filter == "example.com"
        assert s.prefer_type == "pdf"

    def test_parses_direct_source_seed(self):
        from app.rag.discovery import _parse_seeds_from_config

        author_cfg = {
            "discovery_seeds": [
                {
                    "url": "https://example.com/doc.pdf",
                    "seed_type": "direct_source",
                    "source_type": "pdf",
                }
            ]
        }
        seeds = _parse_seeds_from_config(author_cfg)
        assert len(seeds) == 1
        assert seeds[0].seed_type == "direct_source"
        assert seeds[0].source_type == "pdf"

    def test_empty_discovery_seeds_returns_empty(self):
        from app.rag.discovery import _parse_seeds_from_config

        seeds = _parse_seeds_from_config({"name": "no seeds"})
        assert seeds == []

    def test_multiple_seeds(self):
        from app.rag.discovery import _parse_seeds_from_config

        author_cfg = {
            "discovery_seeds": [
                {"url": "https://a.com/", "seed_type": "archive_page"},
                {"url": "https://b.com/doc.pdf", "seed_type": "direct_source"},
            ]
        }
        seeds = _parse_seeds_from_config(author_cfg)
        assert len(seeds) == 2


# ── 2. URL helpers ────────────────────────────────────────────────────────────


class TestUrlHelpers:
    def test_normalize_url_strips_fragment(self):
        from app.rag.discovery import _normalize_url

        assert _normalize_url("https://example.com/page#section") == "https://example.com/page"

    def test_normalize_url_strips_trailing_slash(self):
        from app.rag.discovery import _normalize_url

        assert _normalize_url("https://example.com/page/") == "https://example.com/page"

    def test_url_stem_strips_extension(self):
        from app.rag.discovery import _url_stem

        assert _url_stem("https://example.com/letters/2024ltr.pdf") == "https://example.com/letters/2024ltr"
        assert _url_stem("https://example.com/letters/2024ltr.html") == "https://example.com/letters/2024ltr"

    def test_url_stem_same_for_pdf_and_html_variant(self):
        from app.rag.discovery import _url_stem

        pdf_stem = _url_stem("https://example.com/letters/2024ltr.pdf")
        html_stem = _url_stem("https://example.com/letters/2024ltr.html")
        assert pdf_stem == html_stem

    def test_detect_source_type_pdf(self):
        from app.rag.discovery import _detect_source_type_from_url

        assert _detect_source_type_from_url("https://example.com/doc.pdf") == "pdf"

    def test_detect_source_type_html(self):
        from app.rag.discovery import _detect_source_type_from_url

        assert _detect_source_type_from_url("https://example.com/page.html") == "html"

    def test_detect_source_type_from_content_type(self):
        from app.rag.discovery import _detect_source_type_from_url

        assert _detect_source_type_from_url("https://example.com/resource", "application/pdf") == "pdf"


# ── 3. Link extraction and filtering ─────────────────────────────────────────


class TestLinkExtraction:
    def test_extract_links_from_simple_html(self):
        from app.rag.discovery import _extract_links_from_html

        html = b"""<html><body>
        <a href="https://example.com/2024ltr.pdf">2024 Letter</a>
        <a href="https://example.com/2023ltr.html">2023 Letter</a>
        <a href="mailto:info@example.com">Contact</a>
        </body></html>"""
        links = _extract_links_from_html(html, "https://example.com/", None)
        assert "https://example.com/2024ltr.pdf" in links
        assert "https://example.com/2023ltr.html" in links
        # mailto should be excluded
        assert not any("mailto:" in l for l in links)

    def test_extract_links_resolves_relative_urls(self):
        from app.rag.discovery import _extract_links_from_html

        html = b"""<html><body>
        <a href="letters/2024ltr.pdf">2024</a>
        </body></html>"""
        links = _extract_links_from_html(html, "https://example.com/letters/", None)
        assert any("2024ltr.pdf" in l for l in links)

    def test_domain_filter_removes_external_links(self):
        from app.rag.discovery import _apply_domain_filter

        links = [
            "https://example.com/doc.pdf",
            "https://other.com/page.html",
            "https://sub.example.com/file.pdf",
        ]
        filtered = _apply_domain_filter(links, "example.com")
        assert "https://example.com/doc.pdf" in filtered
        assert "https://other.com/page.html" not in filtered
        assert "https://sub.example.com/file.pdf" in filtered

    def test_pattern_filter_keeps_matching_links(self):
        from app.rag.discovery import _apply_pattern_filter

        links = [
            "https://example.com/2024ltr.pdf",
            "https://example.com/2023ltr.html",
            "https://example.com/about.html",
        ]
        filtered = _apply_pattern_filter(links, [".*ltr\\.pdf$", ".*ltr\\.html$"])
        assert "https://example.com/2024ltr.pdf" in filtered
        assert "https://example.com/2023ltr.html" in filtered
        assert "https://example.com/about.html" not in filtered

    def test_empty_patterns_returns_all(self):
        from app.rag.discovery import _apply_pattern_filter

        links = ["https://example.com/a.pdf", "https://example.com/b.html"]
        filtered = _apply_pattern_filter(links, [])
        assert len(filtered) == len(links)


# ── 4. prefer_type deduplication ─────────────────────────────────────────────


class TestPreferTypeDeduplication:
    def test_prefer_pdf_drops_html_variant(self):
        from app.rag.discovery import DiscoveredSource, apply_prefer_type

        sources = [
            DiscoveredSource(url="https://example.com/letters/2024ltr.pdf", source_type="pdf"),
            DiscoveredSource(url="https://example.com/letters/2024ltr.html", source_type="html"),
            DiscoveredSource(url="https://example.com/letters/2023ltr.pdf", source_type="pdf"),
        ]
        result = apply_prefer_type(sources, prefer_type="pdf")
        urls = [s.url for s in result]
        # Both years should appear but HTML variant of 2024 should be dropped
        assert len(result) == 2
        assert any("2024ltr.pdf" in u for u in urls)
        assert not any("2024ltr.html" in u for u in urls)
        assert any("2023ltr.pdf" in u for u in urls)

    def test_prefer_html_drops_pdf_variant(self):
        from app.rag.discovery import DiscoveredSource, apply_prefer_type

        sources = [
            DiscoveredSource(url="https://example.com/letters/2024ltr.pdf", source_type="pdf"),
            DiscoveredSource(url="https://example.com/letters/2024ltr.html", source_type="html"),
        ]
        result = apply_prefer_type(sources, prefer_type="html")
        assert len(result) == 1
        assert result[0].source_type == "html"

    def test_no_prefer_type_deduplicates_by_url(self):
        from app.rag.discovery import DiscoveredSource, apply_prefer_type

        sources = [
            DiscoveredSource(url="https://example.com/doc.pdf", source_type="pdf"),
            DiscoveredSource(url="https://example.com/doc.pdf", source_type="pdf"),  # exact duplicate
        ]
        result = apply_prefer_type(sources, prefer_type=None)
        assert len(result) == 1

    def test_no_duplicates_returns_all(self):
        from app.rag.discovery import DiscoveredSource, apply_prefer_type

        sources = [
            DiscoveredSource(url="https://example.com/a.pdf", source_type="pdf"),
            DiscoveredSource(url="https://example.com/b.pdf", source_type="pdf"),
        ]
        result = apply_prefer_type(sources, prefer_type="pdf")
        assert len(result) == 2

    def test_prefer_type_fallback_when_preferred_missing(self):
        """If preferred type not available for a stem, keep what we have."""
        from app.rag.discovery import DiscoveredSource, apply_prefer_type

        sources = [
            DiscoveredSource(url="https://example.com/letters/2022ltr.html", source_type="html"),
        ]
        result = apply_prefer_type(sources, prefer_type="pdf")
        assert len(result) == 1
        assert result[0].source_type == "html"


# ── 5. Direct source seed ─────────────────────────────────────────────────────


class TestDirectSourceSeed:
    def test_direct_source_returns_url_without_fetch(self):
        from app.rag.discovery import DiscoverySeed, _process_seed

        seed = DiscoverySeed(
            url="https://igyfoundation.org.uk/nomad.pdf",
            seed_type="direct_source",
            source_type="pdf",
        )
        sources, errors = _process_seed(seed)
        assert len(sources) == 1
        assert sources[0].url == "https://igyfoundation.org.uk/nomad.pdf"
        assert sources[0].source_type == "pdf"
        assert errors == []

    def test_direct_source_infers_type_from_url(self):
        from app.rag.discovery import DiscoverySeed, _process_seed

        seed = DiscoverySeed(
            url="https://example.com/doc.pdf",
            seed_type="direct_source",
        )
        sources, errors = _process_seed(seed)
        assert sources[0].source_type == "pdf"

    def test_direct_source_no_network_call(self):
        """Verify no HTTP requests are made for direct_source seeds."""
        from app.rag.discovery import DiscoverySeed, _process_seed

        seed = DiscoverySeed(url="https://example.com/file.pdf", seed_type="direct_source")
        with patch("httpx.Client") as mock_client:
            sources, _ = _process_seed(seed)
            mock_client.assert_not_called()
        assert len(sources) == 1


# ── 6. Archive page fetch (mocked) ───────────────────────────────────────────


class TestArchivePageFetch:
    def _make_mock_response(self, html_content: bytes, status_code: int = 200) -> MagicMock:
        resp = MagicMock()
        resp.status_code = status_code
        resp.content = html_content
        resp.headers = {"content-type": "text/html; charset=utf-8"}
        resp.url = "https://example.com/letters/"
        return resp

    def test_archive_page_discovers_pdf_links(self):
        from app.rag.discovery import DiscoverySeed, _process_seed

        html = b"""<html><body>
        <a href="2024ltr.pdf">2024</a>
        <a href="2023ltr.pdf">2023</a>
        <a href="about.html">About</a>
        </body></html>"""

        seed = DiscoverySeed(
            url="https://example.com/letters/",
            seed_type="archive_page",
            link_patterns=[".*ltr\\.pdf$"],
            base_url="https://example.com/letters/",
            domain_filter="example.com",
        )

        mock_resp = self._make_mock_response(html)
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client_instance):
            sources, errors = _process_seed(seed)

        assert errors == []
        urls = [s.url for s in sources]
        assert any("2024ltr.pdf" in u for u in urls)
        assert any("2023ltr.pdf" in u for u in urls)
        assert not any("about.html" in u for u in urls)

    def test_archive_page_http_error_recorded(self):
        from app.rag.discovery import DiscoverySeed, _process_seed

        seed = DiscoverySeed(url="https://example.com/archive/", seed_type="archive_page")
        mock_resp = self._make_mock_response(b"", status_code=404)
        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client_instance):
            sources, errors = _process_seed(seed)

        assert sources == []
        assert len(errors) == 1
        assert "404" in errors[0]

    def test_archive_page_network_error_recorded(self):
        import httpx

        from app.rag.discovery import DiscoverySeed, _process_seed

        seed = DiscoverySeed(url="https://example.com/archive/", seed_type="archive_page")

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.side_effect = httpx.ConnectError("connection refused")

        with patch("httpx.Client", return_value=mock_client_instance):
            sources, errors = _process_seed(seed)

        assert sources == []
        assert len(errors) == 1
        assert "Network error" in errors[0]

    def test_mixed_html_pdf_archive_with_prefer_pdf(self):
        """Buffett letters case: both PDF and HTML per year — prefer PDF."""
        from app.rag.discovery import DiscoverySeed, _process_seed

        html = b"""<html><body>
        <a href="2024ltr.pdf">2024 PDF</a>
        <a href="2024ltr.html">2024 HTML</a>
        <a href="2023ltr.pdf">2023 PDF</a>
        <a href="2023ltr.html">2023 HTML</a>
        </body></html>"""

        seed = DiscoverySeed(
            url="https://berkshirehathaway.com/letters/letters.html",
            seed_type="archive_page",
            link_patterns=[".*ltr\\.pdf$", ".*ltr\\.html$"],
            base_url="https://berkshirehathaway.com/letters/",
            domain_filter="berkshirehathaway.com",
            prefer_type="pdf",
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = html
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.url = seed.url

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client_instance):
            sources, errors = _process_seed(seed)

        assert errors == []
        # 2 years × 1 preferred type = 2 sources
        assert len(sources) == 2
        assert all(s.source_type == "pdf" for s in sources)


# ── 7. DB registration and deduplication ─────────────────────────────────────


class TestSourceRegistration:
    def test_register_new_sources(self, sqlite_session):
        from app.rag.discovery import DiscoveredSource, _register_sources

        Session = sqlite_session
        db = Session()
        try:
            # Seed author
            from sqlalchemy import text

            db.execute(
                text(
                    "INSERT OR IGNORE INTO rag_authors (id, name, enabled, domains, expertise_tags, overall_weight, config_source) "
                    "VALUES ('reg_test_author', 'Reg Test', 1, '[]', '[]', 1.0, 'test')"
                )
            )
            db.commit()

            sources = [
                DiscoveredSource(url="https://example.com/a.pdf", source_type="pdf"),
                DiscoveredSource(url="https://example.com/b.html", source_type="html"),
            ]
            registered, skipped = _register_sources("reg_test_author", sources, set(), db)
            db.commit()

            assert registered == 2
            assert skipped == 0
        finally:
            db.close()

    def test_register_skips_duplicates(self, sqlite_session):
        from app.rag.discovery import DiscoveredSource, _normalize_url, _register_sources

        Session = sqlite_session
        db = Session()
        try:
            from sqlalchemy import text

            db.execute(
                text(
                    "INSERT OR IGNORE INTO rag_authors (id, name, enabled, domains, expertise_tags, overall_weight, config_source) "
                    "VALUES ('dup_test_author', 'Dup Test', 1, '[]', '[]', 1.0, 'test')"
                )
            )
            db.commit()

            existing_url = "https://example.com/existing.pdf"
            sources = [
                DiscoveredSource(url=existing_url, source_type="pdf"),
                DiscoveredSource(url="https://example.com/new.pdf", source_type="pdf"),
            ]
            existing = {_normalize_url(existing_url)}
            registered, skipped = _register_sources("dup_test_author", sources, existing, db)
            db.commit()

            assert registered == 1
            assert skipped == 1
        finally:
            db.close()

    def test_existing_urls_for_author_returns_set(self, sqlite_session):
        from app.rag.discovery import _existing_urls_for_author

        Session = sqlite_session
        db = Session()
        try:
            from sqlalchemy import text

            db.execute(
                text(
                    "INSERT OR IGNORE INTO rag_authors (id, name, enabled, domains, expertise_tags, overall_weight, config_source) "
                    "VALUES ('existing_url_author', 'Existing URL Author', 1, '[]', '[]', 1.0, 'test')"
                )
            )
            import uuid

            src_id = str(uuid.uuid4())
            db.execute(
                text(
                    f"INSERT INTO rag_sources (id, author_id, url, source_type) "
                    f"VALUES ('{src_id}', 'existing_url_author', 'https://example.com/letter.pdf', 'pdf')"
                )
            )
            db.commit()

            urls = _existing_urls_for_author("existing_url_author", db)
            assert "https://example.com/letter.pdf" in urls
        finally:
            db.close()


# ── 8. discover_sources_for_author ───────────────────────────────────────────


class TestDiscoverSourcesForAuthor:
    def test_returns_empty_for_no_seeds(self, sqlite_session):
        from app.rag.discovery import discover_sources_for_author

        Session = sqlite_session
        db = Session()
        try:
            author_cfg = {"id": "no_seeds", "name": "No Seeds"}
            results = discover_sources_for_author("no_seeds", author_cfg, db)
            assert results == []
        finally:
            db.close()

    def test_direct_source_registered_without_fetch(self, sqlite_session):
        from app.rag.discovery import discover_sources_for_author

        Session = sqlite_session
        db = Session()
        try:
            from sqlalchemy import text

            db.execute(
                text(
                    "INSERT OR IGNORE INTO rag_authors (id, name, enabled, domains, expertise_tags, overall_weight, config_source) "
                    "VALUES ('ns_direct_test', 'Nick Sleep Direct', 1, '[]', '[]', 3.5, 'test')"
                )
            )
            db.commit()

            author_cfg = {
                "discovery_seeds": [
                    {
                        "url": "https://igyfoundation.org.uk/nomad_unique_001.pdf",
                        "seed_type": "direct_source",
                        "source_type": "pdf",
                    }
                ]
            }

            results = discover_sources_for_author("ns_direct_test", author_cfg, db)
            db.commit()

            assert len(results) == 1
            r = results[0]
            assert r.registered == 1
            assert r.skipped_duplicate == 0
            assert r.errors == []
        finally:
            db.close()

    def test_idempotent_second_call_skips_duplicates(self, sqlite_session):
        from app.rag.discovery import discover_sources_for_author

        Session = sqlite_session
        db = Session()
        try:
            from sqlalchemy import text

            db.execute(
                text(
                    "INSERT OR IGNORE INTO rag_authors (id, name, enabled, domains, expertise_tags, overall_weight, config_source) "
                    "VALUES ('idem_test_author', 'Idempotent Author', 1, '[]', '[]', 3.0, 'test')"
                )
            )
            db.commit()

            author_cfg = {
                "discovery_seeds": [
                    {
                        "url": "https://example.com/idem_doc_unique_002.pdf",
                        "seed_type": "direct_source",
                        "source_type": "pdf",
                    }
                ]
            }

            # First call
            results1 = discover_sources_for_author("idem_test_author", author_cfg, db)
            db.commit()

            # Second call (idempotent)
            results2 = discover_sources_for_author("idem_test_author", author_cfg, db)
            db.commit()

            assert results1[0].registered == 1
            assert results2[0].registered == 0
            assert results2[0].skipped_duplicate == 1
        finally:
            db.close()


# ── 9. bulk_ingest_author ────────────────────────────────────────────────────


class TestBulkIngestAuthor:
    def test_bulk_ingest_processes_pending_sources(self):
        """bulk_ingest_author runs url ingestion for each pending source."""
        from app.rag.ingestion.pipeline import bulk_ingest_author

        db = MagicMock()

        source1 = MagicMock()
        source1.id = "src-1"
        source1.url = "https://example.com/a.pdf"
        source1.source_type = "pdf"
        source1.status = "pending"
        source1.author = MagicMock(name="Test Author")

        source2 = MagicMock()
        source2.id = "src-2"
        source2.url = "https://example.com/b.pdf"
        source2.source_type = "pdf"
        source2.status = "pending"
        source2.author = MagicMock(name="Test Author")

        db.query.return_value.filter.return_value.all.return_value = [source1, source2]

        with patch("app.rag.ingestion.pipeline.run_url_ingestion") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            jobs = bulk_ingest_author("test_author", db)

        assert len(jobs) == 2
        assert mock_ingest.call_count == 2

    def test_bulk_ingest_empty_when_no_pending(self):
        from app.rag.ingestion.pipeline import bulk_ingest_author

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with patch("app.rag.ingestion.pipeline.run_url_ingestion") as mock_ingest:
            jobs = bulk_ingest_author("test_author", db)

        assert jobs == []
        mock_ingest.assert_not_called()

    def test_bulk_ingest_includes_failed_sources_by_default(self):
        from app.rag.ingestion.pipeline import bulk_ingest_author

        db = MagicMock()
        failed_source = MagicMock()
        failed_source.id = "src-fail"
        failed_source.url = "https://example.com/failed.pdf"
        failed_source.status = "failed"
        failed_source.author = MagicMock(name="Author")

        db.query.return_value.filter.return_value.all.return_value = [failed_source]

        with patch("app.rag.ingestion.pipeline.run_url_ingestion") as mock_ingest:
            mock_ingest.return_value = MagicMock()
            jobs = bulk_ingest_author("test_author", db)

        assert len(jobs) == 1

    def test_bulk_ingest_records_failure_category(self):
        """Each failed source ingestion still produces a job with failure_category."""
        from app.rag.ingestion.pipeline import bulk_ingest_author

        db = MagicMock()
        source = MagicMock()
        source.id = "src-x"
        source.url = "https://example.com/x.pdf"
        source.status = "pending"
        source.author = MagicMock(name="Author")

        db.query.return_value.filter.return_value.all.return_value = [source]

        failed_job = MagicMock()
        failed_job.status = "failed"
        failed_job.failure_category = "network_error"

        with patch("app.rag.ingestion.pipeline.run_url_ingestion", return_value=failed_job):
            jobs = bulk_ingest_author("test_author", db)

        assert jobs[0].failure_category == "network_error"


# ── 10. Failure category queryability ────────────────────────────────────────


class TestFailureCategoryReporting:
    def test_failure_categories_are_named_constants(self):
        from app.rag.ingestion.pipeline import (
            FAILURE_EMPTY_TEXT_EXTRACTION,
            FAILURE_MANUAL_REVIEW_REQUIRED,
            FAILURE_NETWORK_ERROR,
            FAILURE_OCR_REQUIRED,
            FAILURE_PARSE_FAILED,
        )

        cats = {
            FAILURE_NETWORK_ERROR,
            FAILURE_PARSE_FAILED,
            FAILURE_EMPTY_TEXT_EXTRACTION,
            FAILURE_OCR_REQUIRED,
            FAILURE_MANUAL_REVIEW_REQUIRED,
        }
        assert len(cats) == 5  # All distinct

    def test_network_exception_classifies_as_network_error(self):
        import httpx

        from app.rag.ingestion.pipeline import _classify_failure

        exc = httpx.ConnectError("timeout")
        assert _classify_failure(exc, "html") == "network_error"

    def test_empty_extraction_classifies_correctly(self):
        from app.rag.ingestion.pipeline import EmptyTextExtractionError, _classify_failure

        exc = EmptyTextExtractionError("no text")
        assert _classify_failure(exc, "html") == "empty_text_extraction"

    def test_ocr_required_classifies_correctly(self):
        from app.rag.ingestion.pipeline import OcrRequiredError, _classify_failure

        exc = OcrRequiredError("ocr needed")
        assert _classify_failure(exc, "pdf") == "ocr_required"


# ── 11. Config includes full PRD seed author set ─────────────────────────────


class TestPRDAuthorRegistry:
    PRD_AUTHOR_IDS = [
        "warren_buffett",
        "charlie_munger",
        "howard_marks",
        "ben_thompson",
        "nick_sleep",
        "michael_mauboussin",
        "byrne_hobart",
        "eugene_wei",
        "matt_levine",
        "christopher_bloomstran",
    ]

    def test_all_prd_authors_in_config(self, tmp_path, monkeypatch):
        """Verify all 10 PRD seed authors exist in config/rag_authors.yaml."""
        config_path = _repo_config_path()

        if not config_path.exists():
            pytest.skip(f"Config file not found at {config_path}")

        monkeypatch.setenv("RAG_AUTHORS_CONFIG", str(config_path))
        from app.rag.config import load_author_config

        data = load_author_config()
        author_ids = {a["id"] for a in data.get("authors", [])}

        missing = [aid for aid in self.PRD_AUTHOR_IDS if aid not in author_ids]
        assert missing == [], f"Missing PRD authors in config: {missing}"

    def test_discovery_seeds_present_for_key_authors(self, tmp_path, monkeypatch):
        """Check that key authors have discovery_seeds defined."""
        config_path = _repo_config_path()

        if not config_path.exists():
            pytest.skip(f"Config file not found at {config_path}")

        monkeypatch.setenv("RAG_AUTHORS_CONFIG", str(config_path))
        from app.rag.config import load_author_config

        data = load_author_config()
        authors_by_id = {a["id"]: a for a in data.get("authors", [])}

        # These authors should have discovery seeds
        for aid in ["warren_buffett", "howard_marks", "nick_sleep", "michael_mauboussin"]:
            author = authors_by_id.get(aid, {})
            seeds = author.get("discovery_seeds", [])
            assert len(seeds) > 0, f"Author {aid} has no discovery_seeds in config"

    def test_sync_config_loads_all_prd_authors(self, sqlite_session, tmp_path, monkeypatch):
        """sync_authors_from_config creates rows for all PRD seed authors."""
        config_path = _repo_config_path()

        if not config_path.exists():
            pytest.skip(f"Config file not found at {config_path}")

        monkeypatch.setenv("RAG_AUTHORS_CONFIG", str(config_path))

        Session = sqlite_session
        db = Session()
        try:
            from app.rag.config import sync_authors_from_config

            result = sync_authors_from_config(db)
            db.commit()

            assert result["total"] >= 10

            from sqlalchemy import text

            rows = db.execute(text("SELECT id FROM rag_authors")).fetchall()
            author_ids = {r[0] for r in rows}

            missing = [aid for aid in self.PRD_AUTHOR_IDS if aid not in author_ids]
            assert missing == [], f"Authors missing after sync: {missing}"
        finally:
            db.close()


# ── 12. API endpoint tests ────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def setup_rag_tables_discovery():
    """Ensure RAG tables exist for API tests in main test DB."""
    yield
    from sqlalchemy import create_engine, text

    engine = create_engine(
        "sqlite+pysqlite:////tmp/capitalos_test.db",
        connect_args={"check_same_thread": False},
    )
    with engine.begin() as conn:
        for table in [
            "rag_embeddings", "rag_chunks", "rag_documents",
            "rag_ingestion_jobs", "rag_sources", "rag_author_cards", "rag_authors",
        ]:
            try:
                conn.execute(text(f"DELETE FROM {table}"))
            except Exception:
                pass


@pytest.fixture
def api_client(rag_yaml_with_seeds):
    from fastapi.testclient import TestClient

    with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_with_seeds}):
        from app.main import app

        yield TestClient(app)


class TestDiscoverEndpoint:
    def _ensure_authors(self, client, rag_yaml_with_seeds):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_with_seeds}):
            client.post("/rag/authors/sync-config")

    def test_discover_unknown_author_404(self, api_client, rag_yaml_with_seeds):
        self._ensure_authors(api_client, rag_yaml_with_seeds)
        resp = api_client.post("/rag/authors/nonexistent_author/discover")
        assert resp.status_code == 404

    def test_discover_author_with_no_seeds(self, api_client, rag_yaml_with_seeds):
        self._ensure_authors(api_client, rag_yaml_with_seeds)
        resp = api_client.post("/rag/authors/no_seeds_author/discover")
        assert resp.status_code == 200
        body = resp.json()
        assert body["seeds_processed"] == 0
        assert body["total_registered"] == 0

    def test_discover_direct_source_author(self, api_client, rag_yaml_with_seeds):
        """nick_test has a direct_source seed — no HTTP fetch needed."""
        self._ensure_authors(api_client, rag_yaml_with_seeds)

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_with_seeds}):
            resp = api_client.post("/rag/authors/nick_test/discover")

        assert resp.status_code == 200
        body = resp.json()
        assert body["author_id"] == "nick_test"
        assert body["total_registered"] == 1
        assert body["total_skipped_duplicate"] == 0
        assert len(body["results"]) == 1

    def test_discover_idempotent(self, api_client, rag_yaml_with_seeds):
        """Second discover call for direct_source should skip duplicate."""
        self._ensure_authors(api_client, rag_yaml_with_seeds)

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_with_seeds}):
            r1 = api_client.post("/rag/authors/nick_test/discover")
            r2 = api_client.post("/rag/authors/nick_test/discover")

        assert r1.status_code == 200
        assert r2.status_code == 200
        # Second call should have 0 registered, skipped >= first registered
        body2 = r2.json()
        assert body2["total_registered"] == 0
        assert body2["total_skipped_duplicate"] >= 1

    def test_discover_archive_page_with_mocked_fetch(self, api_client, rag_yaml_with_seeds):
        """buffett_test has archive_page seed — mock the HTTP fetch."""
        self._ensure_authors(api_client, rag_yaml_with_seeds)

        html = b"""<html><body>
        <a href="2024ltr.pdf">2024</a>
        <a href="2024ltr.html">2024 HTML</a>
        <a href="2023ltr.pdf">2023</a>
        </body></html>"""

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = html
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.url = "https://www.example.com/letters/"

        mock_client_instance = MagicMock()
        mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
        mock_client_instance.__exit__ = MagicMock(return_value=False)
        mock_client_instance.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client_instance):
            with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_with_seeds}):
                resp = api_client.post("/rag/authors/buffett_test/discover")

        assert resp.status_code == 200
        body = resp.json()
        assert body["author_id"] == "buffett_test"
        # prefer_type=pdf: 2024 should have pdf variant only, 2023 is pdf only → 2 sources
        assert body["total_registered"] >= 2


class TestBulkIngestEndpoint:
    def _ensure_authors(self, client, rag_yaml_with_seeds):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_with_seeds}):
            client.post("/rag/authors/sync-config")

    def test_bulk_ingest_unknown_author_404(self, api_client, rag_yaml_with_seeds):
        self._ensure_authors(api_client, rag_yaml_with_seeds)
        resp = api_client.post("/rag/authors/nobody/bulk-ingest")
        assert resp.status_code == 404

    def test_bulk_ingest_no_pending_sources(self, api_client, rag_yaml_with_seeds):
        self._ensure_authors(api_client, rag_yaml_with_seeds)
        resp = api_client.post("/rag/authors/no_seeds_author/bulk-ingest")
        assert resp.status_code == 202
        body = resp.json()
        assert body["sources_processed"] == 0
        assert body["jobs"] == []

    def test_bulk_ingest_produces_jobs(self, api_client, rag_yaml_with_seeds):
        """After discovering nick_test's direct source, bulk-ingest should produce a job."""
        self._ensure_authors(api_client, rag_yaml_with_seeds)

        # Discover first
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_with_seeds}):
            api_client.post("/rag/authors/nick_test/discover")

        # Bulk ingest (will fail network — that's expected in unit test)
        with patch("app.rag.ingestion.pipeline.fetch_url") as mock_fetch:
            import httpx

            mock_fetch.side_effect = httpx.ConnectError("no network in test")
            resp = api_client.post("/rag/authors/nick_test/bulk-ingest")

        assert resp.status_code == 202
        body = resp.json()
        assert body["author_id"] == "nick_test"
        # sources_processed >= 1 (the source we discovered)
        assert body["sources_processed"] >= 1
        # All jobs should be "failed" with network_error category
        for job in body["jobs"]:
            assert job["status"] == "failed"
            assert job["failure_category"] == "network_error"

    def test_bulk_ingest_queryable_by_failure_category(self, api_client, rag_yaml_with_seeds):
        """After a failed bulk ingest, jobs are queryable by failure_category via /rag/ingest/jobs."""
        self._ensure_authors(api_client, rag_yaml_with_seeds)

        # Get all jobs, check for failure_category field
        resp = api_client.get("/rag/ingest/jobs?status=failed")
        assert resp.status_code == 200
        jobs = resp.json()
        for job in jobs:
            assert "failure_category" in job

    def test_bulk_ingest_invalid_statuses(self, api_client, rag_yaml_with_seeds):
        self._ensure_authors(api_client, rag_yaml_with_seeds)
        resp = api_client.post("/rag/authors/no_seeds_author/bulk-ingest?statuses=")
        assert resp.status_code == 422
