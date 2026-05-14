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
        assert s.table_html is None
        assert s.table is None
        assert s.caption is None
        assert s.notes is None
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
            table_html="<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>",
            table={
                "caption": "Simple table",
                "header_rows": [[
                    {"text": "A", "rowspan": 1, "colspan": 1, "is_header": True},
                    {"text": "B", "rowspan": 1, "colspan": 1, "is_header": True},
                ]],
                "body_rows": [[
                    {"text": "1", "rowspan": 1, "colspan": 1, "is_header": False},
                    {"text": "2", "rowspan": 1, "colspan": 1, "is_header": False},
                ]],
                "footer_rows": [],
                "notes": ["Amounts in millions"],
            },
            caption="Simple table",
            notes=["Amounts in millions"],
        )
        assert s.content_type == "table"
        assert "| A | B |" in s.table_markdown
        assert s.table_rows == [["A", "B"], ["1", "2"]]
        assert s.table_html is not None
        assert s.table is not None
        assert s.caption == "Simple table"
        assert s.notes == ["Amounts in millions"]

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

    def test_complex_table_preserves_sections_spans_caption_and_notes(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            """
            <h2>Insurance underwriting results</h2>
            <table>
              <caption>Insurance underwriting results</caption>
              <thead>
                <tr>
                  <th rowspan="2">Year</th>
                  <th colspan="2">Premiums</th>
                </tr>
                <tr>
                  <th>Gross</th>
                  <th>Net</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>1991</td>
                  <td>123</td>
                  <td>110</td>
                </tr>
              </tbody>
              <tfoot>
                <tr><td colspan="3">Amounts in millions</td></tr>
              </tfoot>
            </table>
            """
        )
        result = parse_html_structured(html)
        table_section = next(s for s in result.sections if s.content_type == "table")
        assert table_section.caption == "Insurance underwriting results"
        assert table_section.notes == ["Amounts in millions"]
        assert table_section.table_html is not None
        assert '<caption>Insurance underwriting results</caption>' in table_section.table_html
        assert table_section.table is not None
        assert len(table_section.table["header_rows"]) == 2
        assert table_section.table["header_rows"][0][0] == {
            "text": "Year",
            "rowspan": 2,
            "colspan": 1,
            "is_header": True,
        }
        assert table_section.table["header_rows"][0][1] == {
            "text": "Premiums",
            "rowspan": 1,
            "colspan": 2,
            "is_header": True,
        }
        assert table_section.table["body_rows"][0][0]["text"] == "1991"
        assert table_section.table_rows == [
            ["Year", "Premiums", ""],
            ["", "Gross", "Net"],
            ["1991", "123", "110"],
            ["Amounts in millions", "", ""],
        ]

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

    def test_word_style_html_infers_headings_and_preserves_inline_html(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<title>Chairman's Letter - 1998</title>"
            "<p align='center'><b>BERKSHIRE HATHAWAY INC.</b></p>"
            "<p align='center'><b>To the Shareholders of Berkshire Hathaway Inc. :</b></p>"
            "<p>Our gain in net worth during 1998 was <b>$25.9 billion</b>.</p>"
        )
        result = parse_html_structured(html)
        assert result.doc_metadata["title"] == "Chairman's Letter - 1998"
        heading_sections = [s for s in result.sections if s.content_type == "heading"]
        assert [section.heading for section in heading_sections] == [
            "BERKSHIRE HATHAWAY INC.",
            "To the Shareholders of Berkshire Hathaway Inc. :",
        ]
        text_section = next(s for s in result.sections if s.content_type == "text")
        assert text_section.html == "Our gain in net worth during 1998 was <b>$25.9 billion</b>."

    def test_legacy_html_table_uses_td_header_rows(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<table>"
            "<tr><td></td><td><b>Investments Per Share</b></td><td><b>Pre-tax Earnings Per Share</b></td></tr>"
            "<tr><td>Year</td><td>1968</td><td>2.87</td></tr>"
            "<tr><td>1978</td><td>465</td><td>12.85</td></tr>"
            "</table>"
        )
        result = parse_html_structured(html)
        table_section = next(s for s in result.sections if s.content_type == "table")
        assert table_section.table is not None
        assert len(table_section.table["header_rows"]) == 1
        assert [cell["text"] for cell in table_section.table["header_rows"][0]] == [
            "Investments Per Share",
            "Pre-tax Earnings Per Share",
        ]
        assert table_section.table["body_rows"][0][0]["text"] == "Year"
        assert table_section.table_html is not None
        assert "<thead>" in table_section.table_html

    def test_layout_table_is_treated_as_container_not_data_table(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<table><tr><td>"
            "<p align='center'><b>BERKSHIRE HATHAWAY INC.</b></p>"
            "<p>To the Shareholders of Berkshire Hathaway Inc.:</p>"
            "<table>"
            "<tr><td></td><td><b>1999</b></td><td><b>1998</b></td></tr>"
            "<tr><td>Investments</td><td>58,848</td><td>47,647</td></tr>"
            "</table>"
            "</td></tr></table>"
        )
        result = parse_html_structured(html)
        headings = [section.heading for section in result.sections if section.content_type == 'heading']
        tables = [section for section in result.sections if section.content_type == 'table']
        assert headings == ["BERKSHIRE HATHAWAY INC."]
        assert len(tables) == 1
        assert tables[0].table is not None
        assert tables[0].table["header_rows"][0][0]["text"] == "1999"
        assert tables[0].table["body_rows"][0][0]["text"] == "Investments"

    def test_prose_layout_table_becomes_paragraph_content(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<table><tr><td>"
            "<p>Our gain in net worth during 1999 was $358 million, which increased per-share book value by 0.5%.</p>"
            "<p>The numbers on the facing page show just how poor our 1999 record was.</p>"
            "</td></tr></table>"
        )
        result = parse_html_structured(html)
        tables = [section for section in result.sections if section.content_type == 'table']
        paragraphs = [section for section in result.sections if section.content_type == 'text']
        assert tables == []
        assert len(paragraphs) == 2
        assert paragraphs[0].content.startswith('Our gain in net worth during 1999')

    def test_preformatted_html_body_is_preserved_as_text(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<p align='center'><b>BERKSHIRE HATHAWAY INC.</b></p>"
            "<pre><i>To the Stockholders of Berkshire Hathaway Inc.:</i>\n\nOperating earnings in 1977 were moderately better than anticipated.</pre>"
        )
        result = parse_html_structured(html)
        headings = [section.heading for section in result.sections if section.content_type == 'heading']
        paragraphs = [section for section in result.sections if section.content_type == 'text']
        assert headings == ['BERKSHIRE HATHAWAY INC.']
        assert len(paragraphs) == 1
        assert paragraphs[0].content.startswith('To the Stockholders of Berkshire Hathaway Inc.:')
        assert paragraphs[0].html is not None
        assert '<i>To the Stockholders of Berkshire Hathaway Inc.:</i>' in paragraphs[0].html

    def test_preformatted_html_table_chunk_is_promoted_to_table_section(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<p align='center'><b>BERKSHIRE HATHAWAY INC.</b></p>"
            "<pre>To the Shareholders of Berkshire Hathaway Inc.:\n\n"
            "No. of Shares                                           Cost       Market\n"
            "-------------                                        ----------  ----------\n"
            "                                                         (000s omitted)\n\n"
            "    690,975    Affiliated Publications, Inc. .......  $  3,516    $  32,908\n"
            "    740,400    American Broadcasting Companies, Inc.    44,416       46,738\n"
            "</pre>"
        )
        result = parse_html_structured(html)
        headings = [section.heading for section in result.sections if section.content_type == 'heading']
        paragraphs = [section for section in result.sections if section.content_type == 'text']
        tables = [section for section in result.sections if section.content_type == 'table']

        assert headings == ['BERKSHIRE HATHAWAY INC.']
        assert len(paragraphs) == 1
        assert paragraphs[0].content.startswith('To the Shareholders of Berkshire Hathaway Inc.:')
        assert len(tables) == 1
        assert tables[0].table is not None
        assert [cell['text'] for cell in tables[0].table['header_rows'][0][:3]] == [
            'No. of Shares',
            'Cost',
            'Market',
        ]
        assert tables[0].table['body_rows'][0][0]['text'] == '690,975'
        assert tables[0].table['body_rows'][0][1]['text'] == 'Affiliated Publications, Inc.'
        assert tables[0].table['body_rows'][0][2]['text'] == '$ 3,516'
        assert tables[0].table['body_rows'][0][3]['text'] == '$ 32,908'

    def test_split_preformatted_html_table_chunks_merge_headers_and_wrapped_labels(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<pre>"
            "(000s omitted)\n"
            "                                 ------------------------------------------\n"
            "                                                         Berkshire's Share\n"
            "                                                          of Net Earnings\n"
            "                                                         (after taxes and\n"
            "                                   Pre-Tax Earnings     minority interests)\n"
            "                                 -------------------    -------------------\n"
            "                                   1987       1986        1987       1986\n\n"
            "Operating Earnings:\n"
            "  Insurance Group:\n"
            "    Underwriting ............... $(55,429)  $(55,844)   $(20,696)  $(29,864)\n"
            "  Interest on Debt and\n"
            "     Pre-Payment Penalty .......  (11,474)   (23,891)    (5,905)   (12,213)\n"
            "</pre>"
        )

        result = parse_html_structured(html)
        tables = [section for section in result.sections if section.content_type == 'table']
        assert len(tables) == 1
        table = tables[0].table
        assert table is not None
        assert [cell['text'] for cell in table['header_rows'][-1][:4]] == ['1987', '1986', '1987', '1986']
        assert table['body_rows'][0][0]['text'] == 'Underwriting'
        assert table['body_rows'][0][1]['text'] == '$(55,429)'
        assert table['body_rows'][1][0]['text'] == 'Interest on Debt and Pre-Payment Penalty'
        assert table['body_rows'][1][4]['text'] == '(12,213)'

    def test_preformatted_html_table_keeps_dates_inside_row_labels(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<pre>"
            "                                 ------------------------------------------\n"
            "                                                         Berkshire's Share\n"
            "                                                          of Net Earnings\n"
            "                                   Pre-Tax Earnings     minority interests)\n"
            "                                 -------------------    -------------------\n"
            "                                   1987       1986        1987       1986\n"
            "  Fechheimer (Acquired 6/3/86)     13,332      8,400       6,580      3,792\n"
            "  Kirby                            22,408     20,218      12,891     10,508\n"
            "</pre>"
        )

        result = parse_html_structured(html)
        tables = [section for section in result.sections if section.content_type == 'table']
        assert len(tables) == 1
        table = tables[0].table
        assert table is not None
        assert table['body_rows'][0][0]['text'] == 'Fechheimer (Acquired 6/3/86)'
        assert [cell['text'] for cell in table['body_rows'][0][1:5]] == ['13,332', '8,400', '6,580', '3,792']

    def test_preformatted_html_table_keeps_wide_numeric_rows_despite_trailing_prose(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<pre>"
            "Net Earnings\n"
            "Earnings Before Income Taxes              After Tax\n"
            "Total                                    Berkshire Share Berkshire Share\n"
            "(in thousands of dollars)                1980    1979    1980    1979    1980    1979\n"
            "----------------------------             ------------------------------\n"
            "Underwriting ............                $ 6,738 $ 3,742 $ 6,737 $ 3,741 $ 3,637 $ 2,214\n"
            "Net Investment Income ...                30,939  24,224  30,927  24,216  25,607  20,106\n"
            "companies amounts to about $13 million. If translated dollar for dollar, the amount would be higher.\n"
            "</pre>"
        )

        result = parse_html_structured(html)
        tables = [section for section in result.sections if section.content_type == 'table']
        assert len(tables) == 1
        table = tables[0].table
        assert table is not None
        assert table['body_rows'][0][0]['text'] == 'Underwriting'
        assert [cell['text'] for cell in table['body_rows'][0][1:7]] == [
            '$ 6,738',
            '$ 3,742',
            '$ 6,737',
            '$ 3,741',
            '$ 3,637',
            '$ 2,214',
        ]

    def test_preformatted_html_table_keeps_footnote_markers_in_labels(self):
        from app.rag.ingestion.parser import parse_html_structured

        html = _html(
            "<pre>"
            "Net Earnings\n"
            "Earnings Before Income Taxes              After Tax\n"
            "Total                                    Berkshire Share Berkshire Share\n"
            "1984    1983    1984    1983    1984    1983\n"
            "----------------------------             ------------------------------\n"
            "Nebraska Furniture Mart(1)               14,511  3,812  11,609  3,049  5,917  1,521\n"
            "See's Candies                            26,644 27,411 26,644 24,526 13,380 12,212\n"
            "</pre>"
        )

        result = parse_html_structured(html)
        tables = [section for section in result.sections if section.content_type == 'table']
        assert len(tables) == 1
        table = tables[0].table
        assert table is not None
        assert table['body_rows'][0][0]['text'] == 'Nebraska Furniture Mart(1)'
        assert [cell['text'] for cell in table['body_rows'][0][1:7]] == [
            '14,511',
            '3,812',
            '11,609',
            '3,049',
            '5,917',
            '1,521',
        ]


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

    def test_unstructured_table_preserves_html_and_rich_structure(self, monkeypatch):
        import app.rag.ingestion.parser as parser_mod

        class _FakeTable:
            text = "Year Gross Net 1991 123 110"

            class metadata:
                text_as_html = (
                    "<table>"
                    "<caption>Insurance underwriting results</caption>"
                    "<thead><tr><th rowspan='2'>Year</th><th colspan='2'>Premiums</th></tr>"
                    "<tr><th>Gross</th><th>Net</th></tr></thead>"
                    "<tbody><tr><td>1991</td><td>123</td><td>110</td></tr></tbody>"
                    "</table>"
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
        table_section = next(s for s in result.sections if s.content_type == "table")
        assert table_section.table_html is not None
        assert "caption" in table_section.table_html
        assert table_section.table is not None
        assert len(table_section.table["header_rows"]) == 2
        assert table_section.table["header_rows"][0][1]["colspan"] == 2


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

        calls: list[dict[str, object]] = []

        class _FakeTable:
            text = "Year Value"

            class metadata:
                text_as_html = "<table><tr><th>Year</th><th>Value</th></tr><tr><td>2023</td><td>100</td></tr></table>"

        _FakeTable.__name__ = "Table"

        def fake_partition(file, strategy, **kwargs):
            calls.append({"strategy": strategy, **kwargs})
            return [_FakeTable()]

        monkeypatch.delenv("RAG_PARSER_BACKEND", raising=False)
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(parser_mod, "_unstructured_partition_pdf", fake_partition)

        parser_mod.parse_pdf_structured(_MINIMAL_PDF)
        assert calls == [{"strategy": "fast"}]

    def test_default_backend_retries_hi_res_when_fast_finds_no_tables(self, monkeypatch):
        import app.rag.ingestion.parser as parser_mod

        calls: list[dict[str, object]] = []

        class _FakeNarrative:
            text = "Narrative only"

            class metadata:
                pass

        class _FakeTable:
            text = "Year Gross Net 1991 123 110"

            class metadata:
                text_as_html = (
                    "<table><thead><tr><th rowspan='2'>Year</th><th colspan='2'>Premiums</th></tr>"
                    "<tr><th>Gross</th><th>Net</th></tr></thead>"
                    "<tbody><tr><td>1991</td><td>123</td><td>110</td></tr></tbody></table>"
                )

        _FakeNarrative.__name__ = "NarrativeText"
        _FakeTable.__name__ = "Table"

        def fake_partition(file, strategy, **kwargs):
            calls.append({"strategy": strategy, **kwargs})
            if strategy == "fast":
                return [_FakeNarrative()]
            return [_FakeTable()]

        monkeypatch.delenv("RAG_PARSER_BACKEND", raising=False)
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(parser_mod, "_unstructured_partition_pdf", fake_partition)

        result = parser_mod.parse_pdf_structured(_MINIMAL_PDF)

        table_section = next(section for section in result.sections if section.content_type == "table")
        assert calls == [
            {"strategy": "fast"},
            {"strategy": "hi_res", "infer_table_structure": True},
        ]
        assert table_section.table is not None
        assert len(table_section.table["header_rows"]) == 2

    def test_default_backend_retries_hi_res_when_fast_table_lacks_structured_html(self, monkeypatch):
        import app.rag.ingestion.parser as parser_mod

        calls: list[dict[str, object]] = []

        class _FastTable:
            text = "Year Gross Net 1991 123 110"

            class metadata:
                text_as_html = None

        class _HiResTable:
            text = "Year Gross Net 1991 123 110"

            class metadata:
                text_as_html = (
                    "<table><thead><tr><th rowspan='2'>Year</th><th colspan='2'>Premiums</th></tr>"
                    "<tr><th>Gross</th><th>Net</th></tr></thead>"
                    "<tbody><tr><td>1991</td><td>123</td><td>110</td></tr></tbody></table>"
                )

        _FastTable.__name__ = "Table"
        _HiResTable.__name__ = "Table"

        def fake_partition(file, strategy, **kwargs):
            calls.append({"strategy": strategy, **kwargs})
            if strategy == "fast":
                return [_FastTable()]
            return [_HiResTable()]

        monkeypatch.delenv("RAG_PARSER_BACKEND", raising=False)
        monkeypatch.setattr(parser_mod, "_UNSTRUCTURED_AVAILABLE", True)
        monkeypatch.setattr(parser_mod, "_unstructured_partition_pdf", fake_partition)

        result = parser_mod.parse_pdf_structured(_MINIMAL_PDF)

        table_section = next(section for section in result.sections if section.content_type == "table")
        assert calls == [
            {"strategy": "fast"},
            {"strategy": "hi_res", "infer_table_structure": True},
        ]
        assert table_section.table is not None
        assert len(table_section.table["header_rows"]) == 2

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
