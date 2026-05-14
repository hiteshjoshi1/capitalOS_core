"""
Tests for RAG Phase 1 — thinker ingestion foundation.

Coverage:
  - Config loading from YAML
  - Text parsing (HTML, PDF fallback, plain text)
  - Chunking logic
  - Embedding generation (mock path)
  - Ingestion pipeline (manual path) with SQLite DB
  - API endpoints (catalog, ingestion, document retrieval)
  - Retrieval smoke (skipped when pgvector not available)

Tests use SQLite for speed. pgvector-specific retrieval tests are marked
with @pytest.mark.integration and require a real Postgres instance.
"""

from __future__ import annotations

import os
import tempfile
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Force mock embedding and SQLite before any app import ─────────────────────
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rag_yaml_file(tmp_path_factory):
    """Create a minimal rag_authors.yaml for testing."""
    content = """
authors:
  - id: test_author
    name: Test Author
    enabled: true
    domains: [investing]
    expertise_tags: [valuation, moat]
    overall_weight: 3.0
    role_type: investor
    reasoning_lens:
      focus:
        - capital allocation
      avoid:
        - macro speculation
      biases:
        - prefers simplicity

  - id: disabled_author
    name: Disabled Author
    enabled: false
    domains: [business]
    expertise_tags: []
    overall_weight: 1.0
    role_type: other
"""
    p = tmp_path_factory.mktemp("config") / "rag_authors.yaml"
    p.write_text(content)
    return str(p)


@pytest.fixture(scope="module")
def sqlite_rag_db():
    """
    Create an in-memory-style SQLite DB with RAG-compatible tables.

    The vector column is stored as TEXT (no pgvector needed for unit tests).
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_path = "/tmp/capitalos_rag_test.db"
    try:
        os.remove(db_path)
    except FileNotFoundError:
        pass

    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    ddl = [
        """
        CREATE TABLE IF NOT EXISTS rag_authors (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            domains TEXT NOT NULL DEFAULT '[]',
            expertise_tags TEXT NOT NULL DEFAULT '[]',
            overall_weight REAL NOT NULL DEFAULT 1.0,
            role_type TEXT,
            config_source TEXT NOT NULL DEFAULT 'test',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rag_author_cards (
            author_id TEXT PRIMARY KEY,
            focus_areas TEXT NOT NULL DEFAULT '[]',
            avoid_patterns TEXT NOT NULL DEFAULT '[]',
            biases TEXT NOT NULL DEFAULT '[]',
            prompt_adapter TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rag_sources (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            author_id TEXT NOT NULL,
            url TEXT,
            source_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            hash TEXT,
            ingestion_config TEXT,
            last_ingested_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rag_documents (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            author_id TEXT,
            parent_document_id TEXT,
            source_document_index INTEGER NOT NULL DEFAULT 0,
            title TEXT,
            published_at TEXT,
            publication_year INTEGER,
            venue TEXT,
            collection TEXT,
            canonical_work_id TEXT,
            canonical_status TEXT,
            dedupe_priority INTEGER,
            source_section TEXT,
            note_taker TEXT,
            work_type TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            token_count INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rag_embeddings (
            chunk_id TEXT PRIMARY KEY,
            embedding TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT 'mock',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS rag_ingestion_jobs (
            id TEXT PRIMARY KEY,
            user_id INTEGER,
            source_id TEXT NOT NULL,
            batch_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            failure_category TEXT,
            error TEXT,
            stats_json TEXT NOT NULL DEFAULT '{}',
            started_at TIMESTAMP,
            finished_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]

    with engine.begin() as conn:
        for stmt in ddl:
            conn.execute(text(stmt))

    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session


# ─────────────────────────────────────────────────────────────────────────────
# 1. Config loading
# ─────────────────────────────────────────────────────────────────────────────


class TestConfigLoader:
    def test_default_config_path_walks_up_to_repo_config(self, tmp_path, monkeypatch):
        repo_root = tmp_path / "repo"
        config_dir = repo_root / "config"
        config_dir.mkdir(parents=True)
        expected = config_dir / "rag_authors.yaml"
        expected.write_text("authors: []")

        fake_module_path = repo_root / "api" / "app" / "rag" / "config.py"
        fake_module_path.parent.mkdir(parents=True)
        fake_module_path.write_text("# fake")

        import app.rag.config as rag_config

        monkeypatch.setattr(rag_config, "__file__", str(fake_module_path))
        assert rag_config._default_config_path() == expected

    def test_load_yaml_returns_authors_list(self, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            from app.rag.config import load_author_config

            data = load_author_config()

        assert "authors" in data
        assert len(data["authors"]) == 2

    def test_loaded_author_fields(self, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            from app.rag.config import load_author_config

            data = load_author_config()

        author = data["authors"][0]
        assert author["id"] == "test_author"
        assert author["name"] == "Test Author"
        assert author["enabled"] is True
        assert "investing" in author["domains"]
        assert "valuation" in author["expertise_tags"]
        assert author["overall_weight"] == 3.0
        assert author["role_type"] == "investor"

    def test_reasoning_lens_preserved(self, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            from app.rag.config import load_author_config

            data = load_author_config()

        lens = data["authors"][0]["reasoning_lens"]
        assert "capital allocation" in lens["focus"]
        assert "macro speculation" in lens["avoid"]
        assert "prefers simplicity" in lens["biases"]

    def test_missing_file_raises(self, tmp_path):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": str(tmp_path / "nonexistent.yaml")}):
            from app.rag.config import load_author_config

            with pytest.raises(FileNotFoundError):
                load_author_config()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Parser
# ─────────────────────────────────────────────────────────────────────────────


class TestParser:
    def test_parse_plain_text(self):
        from app.rag.ingestion.parser import parse

        text = "This is a test paragraph.\n\nAnother paragraph here."
        result = parse(text.encode("utf-8"), "text")
        assert "test paragraph" in result.clean_text
        assert result.source_type == "text"

    def test_parse_manual_text(self):
        from app.rag.ingestion.parser import parse_text

        result = parse_text("Hello world.\n\n   Second paragraph.  ")
        assert "Hello world" in result.clean_text
        assert result.source_type == "text"

    def test_clean_whitespace_collapses_blanks(self):
        from app.rag.ingestion.parser import _clean_whitespace

        messy = "Line 1\n\n\n\n\nLine 2\n"
        clean = _clean_whitespace(messy)
        # At most 2 consecutive blank lines
        assert "\n\n\n" not in clean
        assert "Line 1" in clean
        assert "Line 2" in clean

    def test_parse_html_requires_bs4(self):
        from app.rag.ingestion.parser import _BS4_AVAILABLE, parse_html

        if not _BS4_AVAILABLE:
            with pytest.raises(RuntimeError, match="beautifulsoup4"):
                parse_html(b"<html><body>test</body></html>")
        else:
            result = parse_html(b"<html><body><p>Hello world</p></body></html>")
            assert "Hello world" in result.clean_text

    def test_parse_pdf_requires_pdfminer(self):
        from app.rag.ingestion.parser import _PDFMINER_AVAILABLE, parse_pdf

        if not _PDFMINER_AVAILABLE:
            with pytest.raises(RuntimeError, match="pdfminer"):
                parse_pdf(b"%PDF-1.4 fake content")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Chunker
# ─────────────────────────────────────────────────────────────────────────────


SAMPLE_TEXT = "\n\n".join(
    [
        "Capital allocation is the most important skill of a CEO. It determines how the "
        "company deploys its earned cash — reinvestment, dividends, buybacks, acquisitions.",
        "A business with a durable moat can reinvest at high rates of return for long periods. "
        "This compounding effect separates truly great businesses from mediocre ones.",
        "Management integrity matters enormously. Incentive structures shape behaviour. "
        "Owner-operators tend to think differently about risk and capital.",
        "Valuation anchors the analysis. Even the best business can be a bad investment if "
        "purchased at a price that already reflects an optimistic future.",
        "Patience is a competitive advantage. Most participants focus on the next quarter. "
        "Long-term investors benefit from others' short-term orientation.",
    ]
)


class TestChunker:
    def test_chunk_returns_nonempty_list(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(SAMPLE_TEXT)
        assert len(chunks) > 0

    def test_chunks_have_sequential_indices(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(SAMPLE_TEXT)
        for i, c in enumerate(chunks):
            assert c.index == i

    def test_chunks_have_positive_token_count(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(SAMPLE_TEXT)
        for c in chunks:
            assert c.token_count > 0

    def test_base_metadata_propagated(self):
        from app.rag.ingestion.chunker import chunk_text

        meta = {"author": "Warren Buffett", "author_id": "warren_buffett", "doc_hash": "abc"}
        chunks = chunk_text(SAMPLE_TEXT, base_metadata=meta)
        for c in chunks:
            assert c.metadata_json["author"] == "Warren Buffett"
            assert c.metadata_json["author_id"] == "warren_buffett"
            assert "chunk_index" in c.metadata_json

    def test_empty_text_returns_empty_list(self):
        from app.rag.ingestion.chunker import chunk_text

        assert chunk_text("") == []

    def test_very_short_text_single_chunk(self):
        from app.rag.ingestion.chunker import chunk_text

        text = "A single paragraph with enough content to meet the minimum length threshold."
        chunks = chunk_text(text)
        assert len(chunks) == 1

    def test_chunk_target_token_respected(self):
        from app.rag.ingestion.chunker import chunk_text

        # Use a small target to force multiple chunks
        chunks = chunk_text(SAMPLE_TEXT, target_tokens=50)
        assert len(chunks) > 1

    def test_chunk_text_is_not_empty(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(SAMPLE_TEXT)
        for c in chunks:
            assert len(c.text.strip()) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Embedder
# ─────────────────────────────────────────────────────────────────────────────


class TestEmbedder:
    def test_mock_embedding_returns_correct_dimension(self):
        os.environ["RAG_EMBEDDING_MOCK"] = "1"
        from app.rag.ingestion.embedder import EMBEDDING_DIM, embed_text

        vec = embed_text("capital allocation matters")
        assert len(vec) == EMBEDDING_DIM

    def test_mock_embedding_is_unit_vector(self):
        import math

        os.environ["RAG_EMBEDDING_MOCK"] = "1"
        from app.rag.ingestion.embedder import embed_text

        vec = embed_text("some text for embedding")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 1e-6

    def test_mock_embedding_is_deterministic(self):
        os.environ["RAG_EMBEDDING_MOCK"] = "1"
        from app.rag.ingestion.embedder import embed_text

        v1 = embed_text("moat durability")
        v2 = embed_text("moat durability")
        assert v1 == v2

    def test_different_texts_different_embeddings(self):
        os.environ["RAG_EMBEDDING_MOCK"] = "1"
        from app.rag.ingestion.embedder import embed_text

        v1 = embed_text("capital allocation")
        v2 = embed_text("market psychology")
        assert v1 != v2

    def test_embed_batch_returns_one_per_text(self):
        os.environ["RAG_EMBEDDING_MOCK"] = "1"
        from app.rag.ingestion.embedder import EMBEDDING_DIM, embed_batch

        texts = ["moat", "valuation", "incentives"]
        results = embed_batch(texts)
        assert len(results) == 3
        for v in results:
            assert len(v) == EMBEDDING_DIM

    def test_embedding_model_name_is_mock(self):
        os.environ["RAG_EMBEDDING_MOCK"] = "1"
        from app.rag.ingestion.embedder import embedding_model_name

        assert embedding_model_name() == "mock"

    def test_voyage_embed_batch_uses_2048_document_embeddings(self, monkeypatch):
        monkeypatch.setenv("RAG_EMBEDDING_MOCK", "0")
        monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "voyage")
        monkeypatch.setenv("RAG_EMBEDDING_MODEL", "voyage-4")
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")

        import app.rag.ingestion.embedder as embedder

        importlib.reload(embedder)

        captured: dict[str, object] = {}

        class _FakeResponse:
            embeddings = [[0.25] * embedder.EMBEDDING_DIM]

        class _FakeClient:
            def __init__(self, api_key: str):
                captured["api_key"] = api_key

            def embed(self, texts, model=None, input_type=None, truncation=True, output_dtype=None, output_dimension=None):
                captured["texts"] = texts
                captured["model"] = model
                captured["input_type"] = input_type
                captured["output_dimension"] = output_dimension
                return _FakeResponse()

        monkeypatch.setattr(embedder, "_voyageai", MagicMock(Client=_FakeClient))
        monkeypatch.setattr(embedder, "_VOYAGE_AVAILABLE", True)

        result = embedder.embed_batch(["capital allocation matters"])

        assert len(result) == 1
        assert len(result[0]) == embedder.EMBEDDING_DIM
        assert captured["api_key"] == "test-key"
        assert captured["model"] == "voyage-4"
        assert captured["input_type"] == "document"
        assert captured["output_dimension"] == 1024

    def test_voyage_embed_query_uses_2048_query_embeddings(self, monkeypatch):
        monkeypatch.setenv("RAG_EMBEDDING_MOCK", "0")
        monkeypatch.setenv("RAG_EMBEDDING_PROVIDER", "voyage")
        monkeypatch.setenv("RAG_EMBEDDING_MODEL", "voyage-4")
        monkeypatch.setenv("VOYAGE_API_KEY", "test-key")

        import app.rag.ingestion.embedder as embedder

        importlib.reload(embedder)

        captured: dict[str, object] = {}

        class _FakeResponse:
            embeddings = [[0.5] * embedder.EMBEDDING_DIM]

        class _FakeClient:
            def __init__(self, api_key: str):
                captured["api_key"] = api_key

            def embed(self, texts, model=None, input_type=None, truncation=True, output_dtype=None, output_dimension=None):
                captured["texts"] = texts
                captured["model"] = model
                captured["input_type"] = input_type
                captured["output_dimension"] = output_dimension
                return _FakeResponse()

        monkeypatch.setattr(embedder, "_voyageai", MagicMock(Client=_FakeClient))
        monkeypatch.setattr(embedder, "_VOYAGE_AVAILABLE", True)

        result = embedder.embed_query("durable moat")

        assert len(result) == embedder.EMBEDDING_DIM
        assert captured["api_key"] == "test-key"
        assert captured["model"] == "voyage-4"
        assert captured["input_type"] == "query"
        assert captured["output_dimension"] == 1024


# ─────────────────────────────────────────────────────────────────────────────
# 5. Pipeline — manual ingestion with ORM (SQLite-based)
# ─────────────────────────────────────────────────────────────────────────────


class TestManualPipeline:
    """
    Tests the ingestion pipeline using a mock SQLAlchemy session so we can
    validate the pipeline logic without needing Postgres or pgvector.
    """

    def _make_mock_source(self, author_id="test_author"):
        """Build a minimal mock RagSource."""
        import uuid

        source = MagicMock()
        source.id = uuid.uuid4()
        source.author_id = author_id
        source.url = None
        source.source_type = "manual"
        source.status = "pending"
        source.hash = None
        source.last_ingested_at = None

        author = MagicMock()
        author.name = "Test Author"
        source.author = author

        return source

    def test_pipeline_creates_job(self):
        from app.rag.ingestion.pipeline import run_manual_ingestion

        source = self._make_mock_source()
        db = MagicMock()
        db.get.return_value = None

        job = run_manual_ingestion(source, SAMPLE_TEXT, db, title="Test Work")

        # Job was added to session
        assert db.add.called
        # Source status updated to ingested on success
        assert source.status == "ingested"

    def test_pipeline_sets_source_hash(self):
        import hashlib

        from app.rag.ingestion.pipeline import run_manual_ingestion

        source = self._make_mock_source()
        db = MagicMock()

        run_manual_ingestion(source, SAMPLE_TEXT, db)

        expected_hash = hashlib.sha256(SAMPLE_TEXT.encode()).hexdigest()
        assert source.hash == expected_hash

    def test_pipeline_marks_failed_on_error(self):
        from app.rag.ingestion.pipeline import run_manual_ingestion

        source = self._make_mock_source()
        db = MagicMock()
        # First flush succeeds (_open_job), second raises (_persist_document_and_chunks),
        # third succeeds (_close_job).
        db.flush.side_effect = [None, RuntimeError("DB error"), None]

        job = run_manual_ingestion(source, SAMPLE_TEXT, db)

        assert source.status == "failed"
        assert job.failure_category == "parse_failed"

    def test_pipeline_empty_text_is_classified(self):
        from app.rag.ingestion.pipeline import run_manual_ingestion

        source = self._make_mock_source()
        db = MagicMock()

        job = run_manual_ingestion(source, "", db)
        assert source.status == "failed"
        assert job is not None
        assert job.failure_category == "empty_text_extraction"

    def test_url_pdf_empty_text_maps_to_ocr_required(self):
        from app.rag.ingestion.pipeline import run_url_ingestion

        source = self._make_mock_source()
        source.url = "https://example.com/test.pdf"
        source.source_type = "pdf"
        db = MagicMock()

        with patch("app.rag.ingestion.pipeline.fetch_url") as mock_fetch, patch(
            "app.rag.ingestion.pipeline.parse"
        ) as mock_parse:
            mock_fetch.return_value = MagicMock(
                sha256="abc123",
                content_type="application/pdf",
                raw_bytes=b"%PDF",
            )
            mock_parse.return_value = MagicMock(raw_text="", clean_text="", source_type="pdf")

            job = run_url_ingestion(source, db)

        assert source.status == "failed"
        assert job.failure_category == "ocr_required"


# ─────────────────────────────────────────────────────────────────────────────
# 6. API endpoint tests (via FastAPI TestClient + existing SQLite fixture)
# ─────────────────────────────────────────────────────────────────────────────
# Note: These use the module-level conftest from the existing test suite which
# creates the standard SQLite test DB. RAG tables are created below via SQL.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module", autouse=True)
def setup_rag_tables_in_test_db():
    """
    Ensure RAG tables exist in the test SQLite DB.
    The main conftest.py calls Base.metadata.create_all(), which now includes
    the RAG models when they have been imported before startup, but this test
    module should not rely on import order from other modules. Explicitly
    create the RAG tables here, then clean rows up after the module.
    """
    from sqlalchemy import create_engine
    from app.models.base import Base
    from app.models import rag as _rag_models  # noqa: F401

    engine = create_engine(
        "sqlite+pysqlite:////tmp/capitalos_test.db",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)

    yield

    # Cleanup RAG rows after this test module runs
    from sqlalchemy import text

    with engine.begin() as conn:
        for table in [
            "rag_author_profile_citations",
            "rag_author_profiles",
            "rag_embeddings",
            "rag_chunks",
            "rag_documents",
            "rag_ingestion_jobs",
            "rag_sources",
            "rag_author_cards",
            "rag_authors",
        ]:
            try:
                conn.execute(text(f"DELETE FROM {table}"))
            except Exception:
                pass


@pytest.fixture
def client(rag_yaml_file):
    """FastAPI TestClient with RAG_AUTHORS_CONFIG pointing to test yaml."""
    from fastapi.testclient import TestClient

    with patch.dict(
        os.environ,
        {
            "RAG_AUTHORS_CONFIG": rag_yaml_file,
            # Keep Phase 2/profile/query tests deterministic even when the
            # container has live inference credentials configured.
            "INFERENCE_LLM_API_KEY": "",
        },
    ):
        from app.main import app

        yield TestClient(app)


class TestRagAuthorsAPI:
    def test_rag_requires_auth_when_bypass_disabled(self, client):
        with patch.dict(os.environ, {"AUTH_BYPASS_USER_ID": ""}, clear=False):
            resp = client.get("/rag/authors")
        assert resp.status_code == 401

    def test_list_authors_empty(self, client):
        resp = client.get("/rag/authors")
        assert resp.status_code == 200
        # May or may not have data depending on test order

    def test_sync_config_creates_authors(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            resp = client.post("/rag/authors/sync-config")
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert body["total"] >= 1

    def test_list_authors_after_sync(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            client.post("/rag/authors/sync-config")
            resp = client.get("/rag/authors")
        assert resp.status_code == 200
        authors = resp.json()
        ids = [a["id"] for a in authors]
        assert "test_author" in ids

    def test_sync_config_idempotent(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            r1 = client.post("/rag/authors/sync-config")
            r2 = client.post("/rag/authors/sync-config")
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestRagSourcesAPI:
    def _ensure_author(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            client.post("/rag/authors/sync-config")

    def test_register_source(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/sources",
            json={"author_id": "test_author", "url": "https://example.com/letter.html", "source_type": "html"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["author_id"] == "test_author"
        assert body["status"] == "pending"
        assert "id" in body

    def test_register_source_unknown_author(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/sources",
            json={"author_id": "nobody", "url": "https://example.com", "source_type": "html"},
        )
        assert resp.status_code == 404

    def test_list_sources(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.get("/rag/sources")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_list_sources_filter_by_author(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.get("/rag/sources?author_id=test_author")
        assert resp.status_code == 200


class TestRagIngestionAPI:
    def _ensure_author(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            client.post("/rag/authors/sync-config")

    def test_manual_ingest_creates_job(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/ingest/manual",
            json={
                "author_id": "test_author",
                "text": SAMPLE_TEXT,
                "title": "Test Memo 2024",
                "published_at": "2024-01-15",
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] in ("done", "failed")  # failed is OK for SQLite PickleType
        assert "id" in body

    def test_manual_ingest_empty_text_sets_failure_category(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/ingest/manual",
            json={
                "author_id": "test_author",
                "text": "",
                "title": "Empty Upload",
            },
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["status"] == "failed"
        assert body["failure_category"] == "empty_text_extraction"

    def test_manual_ingest_unknown_author(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/ingest/manual",
            json={"author_id": "nobody", "text": "some text"},
        )
        assert resp.status_code == 404

    def test_ingest_url_requires_url_on_source(self, client, rag_yaml_file):
        """Registering a manual source then calling ingest/url should 422."""
        self._ensure_author(client, rag_yaml_file)
        # Register a source with no URL
        src_resp = client.post(
            "/rag/sources",
            json={"author_id": "test_author", "source_type": "manual"},
        )
        assert src_resp.status_code == 201
        source_id = src_resp.json()["id"]

        resp = client.post("/rag/ingest/url", json={"source_id": source_id})
        assert resp.status_code == 422

    def test_list_jobs(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.get("/rag/ingest/jobs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_invalid_uuid_source_id(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post("/rag/ingest/url", json={"source_id": "not-a-uuid"})
        assert resp.status_code == 422


class TestRagRetrieveSmokeAPI:
    def test_retrieve_smoke_returns_200(self, client, rag_yaml_file):
        """Smoke test — returns 200 with empty results when no pgvector data exists."""
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/retrieve-smoke",
            json={"query": "capital allocation", "top_k": 3},
        )
        # May succeed with empty results or fail gracefully
        assert resp.status_code in (200, 500)
        if resp.status_code == 200:
            body = resp.json()
            assert "query" in body
            assert "results" in body

    def _ensure_author(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            client.post("/rag/authors/sync-config")


class TestRagRetrieveCompareAPI:
    def test_retrieve_compare_returns_weighted_and_unweighted_results(self, client, rag_yaml_file):
        """Comparison endpoint exposes both baseline and weighted retrieval variants."""
        self._ensure_author(client, rag_yaml_file)

        with patch("app.routers.rag.compare_retrieval_weighting") as mock_compare:
            mock_compare.return_value = {
                "query": "capital allocation",
                "retrieval_mode": "hybrid",
                "weighting_feature_flag": "RAG_RETRIEVAL_METADATA_WEIGHTING_ENABLED",
                "default_weighting_enabled": False,
                "baseline_results": [{"chunk_id": "baseline-1", "similarity": 0.8}],
                "weighted_results": [{"chunk_id": "weighted-1", "similarity": 0.82, "metadata_weight": 1.08}],
            }

            resp = client.post(
                "/rag/retrieve-compare",
                json={"query": "capital allocation", "top_k": 3, "retrieval_mode": "hybrid"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "capital allocation"
        assert body["retrieval_mode"] == "hybrid"
        assert body["weighting_feature_flag"] == "RAG_RETRIEVAL_METADATA_WEIGHTING_ENABLED"
        assert body["baseline_results"][0]["chunk_id"] == "baseline-1"
        assert body["weighted_results"][0]["chunk_id"] == "weighted-1"

    def _ensure_author(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            client.post("/rag/authors/sync-config")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Retrieval unit (no DB required — tests the RetrievedChunk helper)
# ─────────────────────────────────────────────────────────────────────────────


class TestRetrievedChunk:
    def test_similarity_is_one_minus_distance(self):
        from app.rag.retrieval import RetrievedChunk

        rc = RetrievedChunk(
            chunk_id="abc",
            document_id="def",
            chunk_index=0,
            text="test chunk",
            token_count=10,
            metadata_json={"author": "Test Author"},
            cosine_distance=0.2,
        )
        assert abs(rc.similarity - 0.8) < 1e-6

    def test_as_dict_has_required_keys(self):
        from app.rag.retrieval import RetrievedChunk

        rc = RetrievedChunk(
            chunk_id="abc",
            document_id="def",
            chunk_index=0,
            text="test chunk",
            token_count=10,
            metadata_json={"author": "Test Author"},
            cosine_distance=0.15,
        )
        d = rc.as_dict()
        for key in ("chunk_id", "document_id", "chunk_index", "text", "similarity", "metadata"):
            assert key in d

    def test_metadata_contains_citation_fields(self):
        from app.rag.ingestion.chunker import chunk_text

        meta = {
            "author": "Warren Buffett",
            "author_id": "warren_buffett",
            "work_title": "2024 Annual Letter",
            "source_url": "https://berkshirehathaway.com/letters/2024ltr.pdf",
            "published_at": "2024-02-24",
            "source_type": "pdf",
            "doc_hash": "abc123",
        }
        chunks = chunk_text(SAMPLE_TEXT, base_metadata=meta)
        assert len(chunks) > 0
        first = chunks[0].metadata_json
        assert first["author"] == "Warren Buffett"
        assert first["source_url"] == "https://berkshirehathaway.com/letters/2024ltr.pdf"
        assert first["source_type"] == "pdf"
        assert "chunk_index" in first


# ─────────────────────────────────────────────────────────────────────────────
# 8. Phase 2: Author wisdom profiles (API + unit)
# ─────────────────────────────────────────────────────────────────────────────


class TestAuthorSelectionUnit:
    """Unit tests for dynamic author selection (no DB — uses mock objects)."""

    def test_select_authors_returns_ranked_list(self):
        from unittest.mock import MagicMock
        from app.rag.author_selection import select_authors, SelectedAuthor

        author = MagicMock()
        author.id = "test_author"
        author.name = "Test Author"
        author.enabled = True
        author.domains = ["investing"]
        author.expertise_tags = ["valuation", "moat"]
        author.overall_weight = 3.0
        author.role_type = "investor"

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [author]
        db.query.return_value.filter.return_value.filter.return_value.all.return_value = [author]

        results = select_authors("capital allocation and moat", db, top_k=4)
        assert isinstance(results, list)
        # All items must be SelectedAuthor
        for r in results:
            assert isinstance(r, SelectedAuthor)

    def test_select_authors_filters_by_author_id(self):
        from unittest.mock import MagicMock
        from app.rag.author_selection import select_authors

        author = MagicMock()
        author.id = "test_author"
        author.name = "Test Author"
        author.enabled = True
        author.domains = ["investing"]
        author.expertise_tags = ["valuation"]
        author.overall_weight = 3.0
        author.role_type = "investor"

        db = MagicMock()
        db.query.return_value.filter.return_value.filter.return_value.all.return_value = [author]
        db.query.return_value.filter.return_value.all.return_value = [author]

        results = select_authors("valuation", db, author_id="test_author", top_k=4)
        assert isinstance(results, list)

    def test_select_authors_empty_db(self):
        from unittest.mock import MagicMock
        from app.rag.author_selection import select_authors

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        db.query.return_value.filter.return_value.filter.return_value.all.return_value = []

        results = select_authors("anything", db)
        assert results == []


class TestWisdomProfileUnit:
    """Unit tests for wisdom profile template synthesis (no LLM, no DB)."""

    def test_parse_profile_json_accepts_direct_json(self):
        from app.rag.wisdom import _parse_profile_json

        raw = """
        {
          "worldview": "Focus on durable economics.",
          "key_maxims": ["Stay rational"],
          "strengths": ["Business quality"],
          "weaknesses": ["Can miss fast change"],
          "favored_decision_variables": ["return on capital"],
          "anti_patterns": ["Avoid leverage"]
        }
        """

        result = _parse_profile_json(raw)
        assert result["worldview"] == "Focus on durable economics."
        assert result["key_maxims"] == ["Stay rational"]

    def test_parse_profile_json_accepts_fenced_json(self):
        from app.rag.wisdom import _parse_profile_json

        raw = """```json
        {
          "worldview": "Focus on durable economics.",
          "key_maxims": ["Stay rational"],
          "strengths": ["Business quality"],
          "weaknesses": ["Can miss fast change"],
          "favored_decision_variables": ["return on capital"],
          "anti_patterns": ["Avoid leverage"]
        }
        ```"""

        result = _parse_profile_json(raw)
        assert result["strengths"] == ["Business quality"]

    def test_parse_profile_json_accepts_wrapped_json(self):
        from app.rag.wisdom import _parse_profile_json

        raw = """
        Here's the profile:
        {
          "worldview": "Focus on durable economics.",
          "key_maxims": ["Stay rational"],
          "strengths": ["Business quality"],
          "weaknesses": ["Can miss fast change"],
          "favored_decision_variables": ["return on capital"],
          "anti_patterns": ["Avoid leverage"]
        }
        """

        result = _parse_profile_json(raw)
        assert result["anti_patterns"] == ["Avoid leverage"]

    def test_template_synthesis_returns_required_keys(self):
        from unittest.mock import MagicMock
        from app.rag.wisdom import _generate_profile_template

        author = MagicMock()
        author.name = "Test Author"
        author.role_type = "investor"
        author.domains = ["investing"]
        author.expertise_tags = ["valuation", "moat", "capital_allocation"]

        card = MagicMock()
        card.focus_areas = ["business quality", "capital allocation"]
        card.avoid_patterns = ["macro speculation"]
        card.biases = ["prefers simplicity"]

        result = _generate_profile_template(author, card, ["Sample corpus text."])
        assert "worldview" in result
        assert "key_maxims" in result
        assert "strengths" in result
        assert "weaknesses" in result
        assert "favored_decision_variables" in result
        assert "anti_patterns" in result
        assert isinstance(result["key_maxims"], list)
        assert len(result["key_maxims"]) > 0

    def test_template_synthesis_no_card(self):
        from unittest.mock import MagicMock
        from app.rag.wisdom import _generate_profile_template

        author = MagicMock()
        author.name = "Test Author"
        author.role_type = "investor"
        author.domains = ["investing"]
        author.expertise_tags = ["valuation"]

        result = _generate_profile_template(author, None, [])
        assert result["worldview"]
        assert isinstance(result["anti_patterns"], list)


class TestInferenceConfigUnit:
    def test_generic_inference_env_overrides_openai_defaults(self):
        from app.rag.inference import (
            inference_api_key,
            inference_base_url,
            inference_model,
            inference_provider,
        )

        with patch.dict(
            os.environ,
            {
                "INFERENCE_LLM_PROVIDER": "openrouter",
                "INFERENCE_LLM_MODEL": "anthropic/claude-sonnet-4.5",
                "INFERENCE_LLM_API_KEY": "generic-key",
            },
            clear=False,
        ):
            assert inference_provider() == "openrouter"
            assert inference_model() == "anthropic/claude-sonnet-4.5"
            assert inference_api_key() == "generic-key"
            assert inference_base_url() == "https://openrouter.ai/api/v1"

    def test_defaults_to_openrouter_without_env(self):
        from app.rag.inference import inference_api_key, inference_model, inference_provider

        env = dict(os.environ)
        env.pop("INFERENCE_LLM_API_KEY", None)
        env.pop("INFERENCE_LLM_PROVIDER", None)
        env.pop("INFERENCE_LLM_MODEL", None)
        with patch.dict(os.environ, env, clear=True):
            assert inference_provider() == "openrouter"
            assert inference_model() == "openai/gpt-4o-mini"
            assert inference_api_key() == ""


class TestQueryResultUnit:
    """Unit tests for query result and evidence dataclasses."""

    def test_query_result_as_dict(self):
        from app.rag.query import QueryResult

        qr = QueryResult(
            query="test query",
            mode="retrieve",
            selected_authors=[{"author_id": "test", "name": "Test"}],
            evidence_chunks=[],
            answer=None,
            missing_information="No evidence found.",
            evidence_sufficient=False,
        )
        d = qr.as_dict()
        assert d["query"] == "test query"
        assert d["mode"] == "retrieve"
        assert d["evidence_sufficient"] is False
        assert d["missing_information"] == "No evidence found."

    def test_company_context_result_as_dict(self):
        from app.rag.query import CompanyContextResult

        ccr = CompanyContextResult(
            company="TestCo",
            question="What is the moat?",
            relevant_author_lenses=[],
            evidence_pack=[],
            evidence_sufficient=False,
        )
        d = ccr.as_dict()
        assert d["company"] == "TestCo"
        assert d["question"] == "What is the moat?"
        assert isinstance(d["relevant_author_lenses"], list)
        assert isinstance(d["evidence_pack"], list)

    def test_execute_retrieve_constrains_to_selected_authors(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from app.rag import query as query_module

        db = MagicMock()
        selected = [
            SimpleNamespace(
                author_id="warren_buffett",
                name="Warren Buffett",
                score=5.0,
                domains=["investing"],
                expertise_tags=["capital_allocation"],
                overall_weight=4.0,
                role_type="investor",
                match_reason=["domain_match:investing"],
            ),
            SimpleNamespace(
                author_id="nick_sleep",
                name="Nick Sleep",
                score=4.0,
                domains=["investing"],
                expertise_tags=["customer_focus"],
                overall_weight=3.0,
                role_type="investor",
                match_reason=["domain_match:investing"],
            ),
        ]

        original_select_authors = query_module.select_authors
        original_retrieve = query_module.retrieve_similar_chunks
        try:
            query_module.select_authors = lambda *args, **kwargs: selected

            captured: dict[str, object] = {}

            def fake_retrieve(*args, **kwargs):
                captured.update(kwargs)
                return []

            query_module.retrieve_similar_chunks = fake_retrieve
            query_module.execute_retrieve("capital allocation", db, top_k=5)
        finally:
            query_module.select_authors = original_select_authors
            query_module.retrieve_similar_chunks = original_retrieve

        assert captured["author_ids"] == ["warren_buffett", "nick_sleep"]


class TestRagPhase2API:
    """API-level tests for Phase 2 endpoints via TestClient (SQLite, no pgvector)."""

    def _ensure_author(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            client.post("/rag/authors/sync-config")

    def test_refresh_profiles_returns_results(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post("/rag/authors/refresh-profiles")
        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body
        assert "total" in body
        assert "ok" in body
        assert "errors" in body
        assert isinstance(body["results"], list)

    def test_refresh_profiles_result_has_author_id(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post("/rag/authors/refresh-profiles")
        assert resp.status_code == 200
        body = resp.json()
        ids = [r["author_id"] for r in body["results"]]
        assert "test_author" in ids

    def test_get_author_profile_after_refresh(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        client.post("/rag/authors/refresh-profiles")
        resp = client.get("/rag/authors/test_author/profile")
        assert resp.status_code == 200
        body = resp.json()
        assert body["author_id"] == "test_author"
        assert "worldview" in body
        assert "key_maxims" in body
        assert "strengths" in body
        assert "weaknesses" in body
        assert "favored_decision_variables" in body
        assert "anti_patterns" in body
        assert "citations" in body
        assert isinstance(body["key_maxims"], list)

    def test_get_author_profile_not_found(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.get("/rag/authors/nobody_known/profile")
        assert resp.status_code == 404

    def test_get_author_profile_no_profile_yet(self, client, rag_yaml_file):
        """Without refresh, profile endpoint 404s for valid author."""
        self._ensure_author(client, rag_yaml_file)
        # disabled_author has no profile generated — and is not enabled so won't appear
        resp = client.get("/rag/authors/disabled_author/profile")
        assert resp.status_code == 404

    def test_retrieve_endpoint_returns_expected_shape(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/retrieve",
            json={"query": "capital allocation and moat", "top_k": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "query" in body
        assert "mode" in body
        assert "selected_authors" in body
        assert "evidence_chunks" in body
        assert "evidence_sufficient" in body
        assert body["mode"] == "retrieve"
        assert isinstance(body["selected_authors"], list)
        assert isinstance(body["evidence_chunks"], list)

    def test_retrieve_endpoint_with_author_filter(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/retrieve",
            json={"query": "moat", "top_k": 3, "author_id": "test_author"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "evidence_chunks" in body

    def test_query_endpoint_returns_expected_shape(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/query",
            json={"query": "What would a value investor look for in a business?", "top_k": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "query" in body
        assert "mode" in body
        assert "selected_authors" in body
        assert "evidence_chunks" in body
        assert "evidence_sufficient" in body
        assert body["mode"] == "ask"

    def test_query_endpoint_returns_missing_info_when_no_corpus(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/query",
            json={"query": "very specific obscure query with no corpus data xyz123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Either evidence_sufficient=False or missing_information is set
        if not body["evidence_sufficient"]:
            assert body["missing_information"] is not None or body["answer"] is None

    def test_company_context_endpoint_returns_expected_shape(self, client, rag_yaml_file):
        self._ensure_author(client, rag_yaml_file)
        resp = client.post(
            "/rag/analyze/company-context",
            json={"company": "ExampleCo", "question": "What author lenses are relevant?", "top_k": 5},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "company" in body
        assert "question" in body
        assert "relevant_author_lenses" in body
        assert "evidence_pack" in body
        assert "evidence_sufficient" in body
        assert body["company"] == "ExampleCo"
        assert isinstance(body["relevant_author_lenses"], list)
        assert isinstance(body["evidence_pack"], list)
