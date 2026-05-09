"""
Tests for Issue 139 — Advanced Document Parsing.

Coverage:
  - DocumentSection and StructuredParseResult dataclasses
  - parse_html_structured(): heading hierarchy, table extraction, list detection
  - parse_pdf_structured(): fallback to pdfminer when unstructured absent
  - parse() dispatcher: returns StructuredParseResult for all source types
  - RAG_PARSER_BACKEND env var respected
  - PDF metadata extraction
  - Backward compatibility: clean_text always present
  - Pipeline integration: doc_metadata merges into base_metadata
"""

from __future__ import annotations

import io
import os
import struct
import textwrap
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_test.db")
os.environ.setdefault("RAG_EMBEDDING_MOCK", "1")
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _html(body: str) -> bytes:
    return f"<html><body>{body}</body></html>".encode()


# Minimal valid PDF bytes (1-page, 1-word text body)
_MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n190\n%%EOF"
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Dataclass shapes
# ─────────────────────────────────────────────────────────────────────────────


class TestDataclasses:
    def test_document_section_fields(self):
        from app.rag.ingestion.parser import DocumentSection

        s = DocumentSection(heading="Intro", level=1, content="Some text", content_type="text")
        assert s.heading == "Intro"
        assert s.level == 1
        assert s.content == "Some text"
        assert s.content_type == "text"
        assert s.table_markdown is None
        assert s.table_rows is None
        assert s.items is None

    def test_document_section_table(self):
        from app.rag.ingestion.parser import DocumentSection

        s = DocumentSection(
            heading=None,
            level=2,
            content="A B",
            content_type="table",
            table_markdown="| A | B |\n|---|---|\n| 1 | 2 |",
            table_rows=[["A", "B"], ["1", "2"]],
        )
        assert s.content_type == "table"
        assert "| A | B |" in s.table_markdown
        assert s.table_rows == [["A", "B"], ["1", "2"]]

    def test_structured_parse_result_fields(self):
        from app.rag.ingestion.parser import StructuredParseResult

        r = StructuredParseResult(raw_text="raw", clean_text="clean", source_type="html")
        assert r.raw_text == "raw"
        assert r.clean_text == "clean"
        assert r.source_type == "html"
        assert r.sections == []
        assert r.doc_metadata == {}

    def test_structured_result_is_backward_compat(self):
        """StructuredParseResult exposes same fields as ParseResult."""
        from app.rag.ingestion.parser import ParseResult, StructuredParseResult

        r = StructuredParseResult(raw_text="r", clean_text="c", source_type="text")
        # Duck-type check — should satisfy any code using ParseResult fields
        for attr in ("raw_text", "clean_text", "source_type"):
            assert hasattr(r, attr)


# ─────────────────────────────────────────────────────────────────────────────
# 2. parse() dispatcher always returns StructuredParseResult
# ─────────────────────────────────────────────────────────────────────────────


class TestParseDispatcher:
    def test_parse_text_returns_structured(self):
        from app.rag.ingestion.parser import StructuredParseResult, parse

        result = parse(b"Hello world", "text")
        assert isinstance(result, StructuredParseResult)
        assert result.source_type == "text"
        assert result.clean_text == "Hello world"

    def test_parse_manual_returns_structured(self):
        from app.rag.ingestion.parser import StructuredParseResult, parse

        result = parse(b"Manual content", "manual")
        assert isinstance(result, StructuredParseResult)
        assert "Manual content" in result.clean_text

    def test_parse_html_returns_structured(self):
        from app.rag.ingestion.parser import StructuredParseResult, parse

        result = parse(_html("<p>Hello</p>"), "html")
        assert isinstance(result, StructuredParseResult)
        assert result.source_type == "html"


# ─────────────────────────────────────────────────────────────────────────────
# 3. HTML structured parsing
# ─────────────────────────────────────────────────────────────────────────────


class TestHtmlStructuredParser:
    def test_heading_creates_sections(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html("<h1>Chapter One</h1><p>Some text here.</p>")
        result = parse_html_structured(html)
        headings = [s.heading for s in result.sections]
        assert "Chapter One" in headings

    def test_heading_hierarchy(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<h1>Top</h1><p>Intro</p>"
            "<h2>Sub A</h2><p>Details about A.</p>"
            "<h2>Sub B</h2><p>Details about B.</p>"
        )
        result = parse_html_structured(html)
        levels = {s.heading: s.level for s in result.sections if s.heading}
        assert levels.get("Top") == 1
        assert levels.get("Sub A") == 2
        assert levels.get("Sub B") == 2

    def test_table_extracted_as_markdown(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<h2>Financials</h2>"
            "<table><tr><th>Year</th><th>Value</th></tr>"
            "<tr><td>2023</td><td>100</td></tr>"
            "<tr><td>2024</td><td>200</td></tr></table>"
        )
        result = parse_html_structured(html)
        table_sections = [s for s in result.sections if s.content_type == "table"]
        assert len(table_sections) >= 1
        md = table_sections[0].table_markdown
        assert md is not None
        assert "Year" in md
        assert "Value" in md
        assert "|" in md  # markdown table format
        assert table_sections[0].table_rows == [["Year", "Value"], ["2023", "100"], ["2024", "200"]]

    def test_table_markdown_has_separator_row(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<table><tr><th>A</th><th>B</th></tr>"
            "<tr><td>1</td><td>2</td></tr></table>"
        )
        result = parse_html_structured(html)
        table_sections = [s for s in result.sections if s.content_type == "table"]
        assert table_sections
        md = table_sections[0].table_markdown
        lines = md.splitlines()
        # Line 0: header, line 1: separator (--- pattern)
        assert "---" in lines[1]

    def test_list_extracted(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html("<h2>Key Points</h2><ul><li>Alpha</li><li>Beta</li></ul>")
        result = parse_html_structured(html)
        list_sections = [s for s in result.sections if "list" in s.content_type]
        assert list_sections[0].items == ["Alpha", "Beta"]

    def test_blockquote_extracted(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html("<h2>Transcript</h2><blockquote>Stay rational under pressure.</blockquote>")
        result = parse_html_structured(html)
        quote_sections = [s for s in result.sections if s.content_type == "quote"]
        assert quote_sections[0].content == "Stay rational under pressure."

    def test_text_manual_sections_preserve_paragraphs_lists_and_quotes(self):
        from app.rag.ingestion.parser import parse

        payload = b"## Notes\n\nFirst paragraph.\n\n- Alpha\n- Beta\n\n> Stay patient."
        result = parse(payload, "manual")
        assert [section.content_type for section in result.sections] == ["heading", "text", "list", "quote"]
        assert result.sections[2].items == ["Alpha", "Beta"]
        assert result.sections[3].content == "Stay patient."

    def test_clean_text_always_populated(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html("<h1>Title</h1><p>Body content here.</p>")
        result = parse_html_structured(html)
        assert result.clean_text.strip()

    def test_noise_tags_removed(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<nav>Navigation menu</nav>"
            "<p>Real content</p>"
            "<footer>Footer text</footer>"
        )
        result = parse_html_structured(html)
        assert "Navigation menu" not in result.clean_text
        assert "Footer text" not in result.clean_text
        assert "Real content" in result.clean_text

    def test_source_type_html(self):
        from app.rag.ingestion.parser import parse_html_structured

        result = parse_html_structured(_html("<p>test</p>"))
        assert result.source_type == "html"

    def test_fallback_when_bs4_unavailable(self, monkeypatch):
        """When BS4 is unavailable, parse_html is called and wrapped."""
        import app.rag.ingestion.parser as parser_mod

        monkeypatch.setattr(parser_mod, "_BS4_AVAILABLE", False)
        # parse_html raises RuntimeError when BS4 unavailable
        with pytest.raises(RuntimeError, match="beautifulsoup4"):
            parser_mod.parse_html_structured(_html("<p>test</p>"))

    def test_multiple_tables(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<h1>Report</h1>"
            "<table><tr><th>X</th></tr><tr><td>1</td></tr></table>"
            "<p>Some text</p>"
            "<table><tr><th>Y</th></tr><tr><td>2</td></tr></table>"
        )
        result = parse_html_structured(html)
        table_sections = [s for s in result.sections if s.content_type == "table"]
        assert len(table_sections) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 4. PDF structured parsing — fallback path
# ─────────────────────────────────────────────────────────────────────────────


class TestPdfStructuredParser:
    def test_returns_structured_result(self):
        from app.rag.ingestion.parser import StructuredParseResult, parse_pdf_structured

        result = parse_pdf_structured(_MINIMAL_PDF)
        assert isinstance(result, StructuredParseResult)
        assert result.source_type == "pdf"

    def test_clean_text_always_set(self):
        from app.rag.ingestion.parser import parse_pdf_structured

        result = parse_pdf_structured(_MINIMAL_PDF)
        # clean_text may be empty for minimal PDF but must not be None
        assert result.clean_text is not None

    def test_doc_metadata_is_dict(self):
        from app.rag.ingestion.parser import parse_pdf_structured

        result = parse_pdf_structured(_MINIMAL_PDF)
        assert isinstance(result.doc_metadata, dict)

    def test_pdfminer_backend_forced(self, monkeypatch):
        """RAG_PARSER_BACKEND=pdfminer forces flat pdfminer path."""
        import app.rag.ingestion.parser as parser_mod

        monkeypatch.setenv("RAG_PARSER_BACKEND", "pdfminer")
        result = parser_mod.parse_pdf_structured(_MINIMAL_PDF)
        assert isinstance(result, parser_mod.StructuredParseResult)
        assert result.sections == []  # pdfminer path has no sections

    def test_unstructured_fallback_on_error(self, monkeypatch):
        """If unstructured raises, fall back to pdfminer gracefully."""
        import app.rag.ingestion.parser as parser_mod

        monkeypatch.setenv("RAG_PARSER_BACKEND", "unstructured")
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(
            parser_mod,
            "_unstructured_partition_pdf",
            MagicMock(side_effect=RuntimeError("boom")),
        )
        result = parser_mod.parse_pdf_structured(_MINIMAL_PDF)
        assert isinstance(result, parser_mod.StructuredParseResult)
        # Falls back cleanly — no exception raised
        assert result.source_type == "pdf"

    def test_unstructured_sections_extracted(self, monkeypatch):
        """When unstructured returns elements, sections are created."""
        import app.rag.ingestion.parser as parser_mod

        class _FakeTitle:
            text = "Investment Philosophy"

            class metadata:
                pass

        class _FakeNarrative:
            text = "We focus on long-term value."

            class metadata:
                pass

        monkeypatch.setenv("RAG_PARSER_BACKEND", "unstructured")
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(
            parser_mod,
            "_unstructured_partition_pdf",
            MagicMock(return_value=[_FakeTitle(), _FakeNarrative()]),
        )
        # Patch type names
        _FakeTitle.__name__ = "Title"
        _FakeNarrative.__name__ = "NarrativeText"

        result = parser_mod.parse_pdf_structured(_MINIMAL_PDF)
        assert result.sections
        headings = [s.heading for s in result.sections]
        assert "Investment Philosophy" in headings

    def test_unstructured_table_markdown(self, monkeypatch):
        """Table elements from unstructured get converted to markdown."""
        import app.rag.ingestion.parser as parser_mod

        class _FakeTable:
            text = "Year Value"

            class metadata:
                text_as_html = (
                    "<table><tr><th>Year</th><th>Value</th></tr>"
                    "<tr><td>2023</td><td>100</td></tr></table>"
                )

        _FakeTable.__name__ = "Table"

        monkeypatch.setenv("RAG_PARSER_BACKEND", "unstructured")
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(
            parser_mod,
            "_unstructured_partition_pdf",
            MagicMock(return_value=[_FakeTable()]),
        )

        result = parser_mod.parse_pdf_structured(_MINIMAL_PDF)
        table_sections = [s for s in result.sections if s.content_type == "table"]
        assert table_sections
        assert "Year" in table_sections[0].table_markdown
        assert "|" in table_sections[0].table_markdown
        assert table_sections[0].table_rows == [["Year", "Value"], ["2023", "100"]]


# ─────────────────────────────────────────────────────────────────────────────
# 5. PDF metadata extraction
# ─────────────────────────────────────────────────────────────────────────────


class TestPdfMetadata:
    def test_extract_returns_dict(self):
        from app.rag.ingestion.parser import _extract_pdf_metadata

        meta = _extract_pdf_metadata(_MINIMAL_PDF)
        assert isinstance(meta, dict)

    def test_extract_does_not_raise_on_bad_pdf(self):
        from app.rag.ingestion.parser import _extract_pdf_metadata

        meta = _extract_pdf_metadata(b"not a pdf")
        assert isinstance(meta, dict)

    def test_extract_with_mocked_pdfminer(self, monkeypatch):
        """Simulate pdfminer returning author/title metadata."""
        import app.rag.ingestion.parser as parser_mod

        fake_doc = MagicMock()
        fake_doc.info = [{"Title": b"Berkshire 2024", "Author": b"Warren Buffett"}]
        fake_parser_instance = MagicMock()

        monkeypatch.setattr(parser_mod, "_PDFMINER_META_AVAILABLE", True)
        monkeypatch.setattr(parser_mod, "_PDFParser", MagicMock(return_value=fake_parser_instance))
        monkeypatch.setattr(parser_mod, "_PDFDocument", MagicMock(return_value=fake_doc))

        meta = parser_mod._extract_pdf_metadata(_MINIMAL_PDF)
        assert meta.get("title") == "Berkshire 2024"
        assert meta.get("author") == "Warren Buffett"


# ─────────────────────────────────────────────────────────────────────────────
# 6. RAG_PARSER_BACKEND configuration
# ─────────────────────────────────────────────────────────────────────────────


class TestParserBackendConfig:
    def test_default_backend_uses_unstructured_when_available(self, monkeypatch):
        import app.rag.ingestion.parser as parser_mod

        called_with = {}

        def fake_partition(file, strategy):
            called_with["strategy"] = strategy
            return []

        monkeypatch.delenv("RAG_PARSER_BACKEND", raising=False)
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(parser_mod, "_unstructured_partition_pdf", fake_partition)

        parser_mod.parse_pdf_structured(_MINIMAL_PDF)
        assert called_with.get("strategy") == "fast"

    def test_pdfminer_backend_skips_unstructured(self, monkeypatch):
        import app.rag.ingestion.parser as parser_mod

        partition_called = []

        def fake_partition(file, strategy):
            partition_called.append(True)
            return []

        monkeypatch.setenv("RAG_PARSER_BACKEND", "pdfminer")
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(parser_mod, "_unstructured_partition_pdf", fake_partition)

        parser_mod.parse_pdf_structured(_MINIMAL_PDF)
        assert not partition_called  # unstructured must NOT be called


# ─────────────────────────────────────────────────────────────────────────────
# 7. Pipeline integration — doc_metadata flows into chunk metadata
# ─────────────────────────────────────────────────────────────────────────────


class TestPipelineStructuredIntegration:
    """Verify pipeline uses StructuredParseResult correctly."""

    def _make_source(self, db_session):
        from app.models.rag import RagAuthor, RagSource

        author = RagAuthor(
            id="test-author-parser",
            name="Test Author",
            enabled=True,
            domains=[],
            expertise_tags=[],
            overall_weight=1.0,
            config_source="test",
        )
        db_session.add(author)
        db_session.flush()

        source = RagSource(
            id="test-source-parser",
            author_id="test-author-parser",
            source_type="text",
            status="pending",
        )
        db_session.add(source)
        db_session.flush()
        return source

    def test_doc_metadata_enriches_base_metadata(self):
        from app.rag.ingestion.pipeline import _build_base_metadata

        # Simulate a RagSource with an author
        mock_source = MagicMock()
        mock_source.author = MagicMock()
        mock_source.author.name = "unknown"
        mock_source.author_id = "x"
        mock_source.url = "http://example.com"
        mock_source.source_type = "pdf"

        doc_meta = {"title": "Berkshire 2024", "author": "Warren Buffett", "subject": "Annual Letter"}
        base = _build_base_metadata(mock_source, "abc123", None, doc_meta)
        assert base["work_title"] == "Berkshire 2024"
        assert base["author"] == "Warren Buffett"
        assert base.get("subject") == "Annual Letter"

    def test_doc_metadata_does_not_override_explicit_title(self):
        from app.rag.ingestion.pipeline import _build_base_metadata

        mock_source = MagicMock()
        mock_source.author = MagicMock()
        mock_source.author.name = "unknown"
        mock_source.author_id = "x"
        mock_source.url = ""
        mock_source.source_type = "pdf"

        base = _build_base_metadata(mock_source, "hash", "Explicit Title", {"title": "PDF Title"})
        # Explicit title wins
        assert base["work_title"] == "Explicit Title"

    def test_sections_produce_section_heading_in_chunk_metadata(self):
        """chunk_structured() sets section_heading in each chunk's metadata."""
        from app.rag.ingestion.chunker import DocumentSection as CS, chunk_structured

        sections = [
            CS(heading="Capital Allocation", content="We allocate capital prudently."),
            CS(heading="Insurance Operations", content="Our insurance float generates returns."),
        ]
        chunks = chunk_structured(sections)
        headings = {c.metadata_json.get("section_heading") for c in chunks}
        assert "Capital Allocation" in headings
        assert "Insurance Operations" in headings

    def test_parse_text_wraps_to_structured(self):
        """parse() for 'text' returns StructuredParseResult with paragraph sections."""
        from app.rag.ingestion.parser import StructuredParseResult, parse

        result = parse(b"Some text content", "text")
        assert isinstance(result, StructuredParseResult)
        assert len(result.sections) == 1
        assert result.sections[0].content_type == "text"
        assert result.doc_metadata == {}
