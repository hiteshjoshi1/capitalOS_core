"""
Content parser for RAG ingestion.

Supports three source types:
  - html  : strip tags, extract visible text with BeautifulSoup (structure-preserving)
  - pdf   : extract text with unstructured.io (preferred) or pdfminer.six (fallback)
  - text  : pass-through with minimal cleaning

Structured parsers return a StructuredParseResult with sections and doc_metadata
in addition to the flat raw_text / clean_text fields retained for backward compat.

Backend selection:
  RAG_PARSER_BACKEND=unstructured  (default when unstructured is installed)
  RAG_PARSER_BACKEND=pdfminer      (forces flat pdfminer fallback)
"""

import io
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ── Optional dependency guards ────────────────────────────────────────────────
try:
    from bs4 import BeautifulSoup  # type: ignore

    _BS4_AVAILABLE = True
except ImportError:
    _BS4_AVAILABLE = False

try:
    from pdfminer.high_level import extract_text as pdf_extract_text  # type: ignore

    _PDFMINER_AVAILABLE = True
except ImportError:
    _PDFMINER_AVAILABLE = False

try:
    from pdfminer.pdfparser import PDFParser as _PDFParser  # type: ignore
    from pdfminer.pdfdocument import PDFDocument as _PDFDocument  # type: ignore

    _PDFMINER_META_AVAILABLE = True
except ImportError:
    _PDFMINER_META_AVAILABLE = False

try:
    from unstructured.partition.pdf import partition_pdf as _unstructured_partition_pdf  # type: ignore
    from unstructured.partition.html import partition_html as _unstructured_partition_html  # type: ignore

    _UNSTRUCTURED_AVAILABLE = True
except ImportError:
    _UNSTRUCTURED_AVAILABLE = False
    # Define stubs so tests can monkeypatch these names even when unstructured is absent
    def _unstructured_partition_pdf(*args: Any, **kwargs: Any) -> list:  # type: ignore[misc]
        raise RuntimeError("unstructured is not installed")

    def _unstructured_partition_html(*args: Any, **kwargs: Any) -> list:  # type: ignore[misc]
        raise RuntimeError("unstructured is not installed")


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ParseResult:
    raw_text: str
    clean_text: str
    source_type: str


@dataclass
class DocumentSection:
    """A single logical section extracted from a document."""

    heading: Optional[str]          # Section heading text (None if before any heading)
    level: int                       # Heading level: 1=top, 2=sub, etc.
    content: str                     # Section body text (flat string)
    content_type: str                # "text" | "table" | "list"
    table_markdown: Optional[str] = None  # Markdown table when content_type=="table"


@dataclass
class StructuredParseResult:
    """Parse result with preserved document structure.

    Backward-compatible: raw_text, clean_text, source_type match ParseResult.
    Adds sections (list of DocumentSection) and doc_metadata (dict).
    """

    raw_text: str
    clean_text: str
    source_type: str
    sections: list = field(default_factory=list)          # list[DocumentSection]
    doc_metadata: dict = field(default_factory=dict)      # title, author, date, …


# ── Cleaning helpers ──────────────────────────────────────────────────────────

def _clean_whitespace(text: str) -> str:
    """Collapse excessive blank lines and trailing spaces."""
    lines = text.splitlines()
    cleaned = []
    blank_run = 0
    for line in lines:
        stripped = line.rstrip()
        if stripped == "":
            blank_run += 1
            if blank_run <= 1:  # allow at most 1 consecutive blank line
                cleaned.append("")
        else:
            blank_run = 0
            cleaned.append(stripped)
    return "\n".join(cleaned).strip()


def _remove_boilerplate(text: str) -> str:
    """Remove common web boilerplate patterns."""
    patterns = [
        r"Cookie Policy.*?(\n|$)",
        r"Privacy Policy.*?(\n|$)",
        r"Accept All Cookies.*?(\n|$)",
        r"Subscribe to our newsletter.*?(\n|$)",
    ]
    for p in patterns:
        text = re.sub(p, "", text, flags=re.IGNORECASE)
    return text


# ── Table conversion helpers ──────────────────────────────────────────────────

def _bs4_table_to_markdown(table_tag: Any) -> str:
    """Convert a BeautifulSoup <table> element to a markdown table string."""
    rows = []
    for tr in table_tag.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)

    if not rows:
        return table_tag.get_text(separator=" ", strip=True)

    # Normalise column count
    max_cols = max(len(r) for r in rows)
    padded = [r + [""] * (max_cols - len(r)) for r in rows]

    lines = ["| " + " | ".join(padded[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _html_table_to_markdown(table_html: str) -> str:
    """Convert an HTML table string (from unstructured metadata) to markdown."""
    if not _BS4_AVAILABLE or not table_html:
        return table_html or ""
    try:
        soup = BeautifulSoup(table_html, "html.parser")
        table = soup.find("table")
        if table:
            return _bs4_table_to_markdown(table)
    except Exception:
        pass
    return table_html


# ── PDF metadata extraction ───────────────────────────────────────────────────

def _extract_pdf_metadata(raw_bytes: bytes) -> dict[str, Any]:
    """Extract document-level metadata from PDF properties using pdfminer."""
    if not _PDFMINER_META_AVAILABLE:
        return {}
    try:
        buf = io.BytesIO(raw_bytes)
        parser = _PDFParser(buf)
        doc = _PDFDocument(parser)
        if not doc.info:
            return {}
        info = doc.info[0]

        def _decode(val: Any) -> str:
            if isinstance(val, bytes):
                try:
                    return val.decode("utf-16-be").strip("\x00") if val.startswith(b"\xfe\xff") else val.decode("latin-1", errors="replace")
                except Exception:
                    return str(val)
            return str(val) if val else ""

        metadata: dict[str, Any] = {}
        if info.get("Title"):
            metadata["title"] = _decode(info["Title"])
        if info.get("Author"):
            metadata["author"] = _decode(info["Author"])
        if info.get("Subject"):
            metadata["subject"] = _decode(info["Subject"])
        if info.get("CreationDate"):
            metadata["creation_date"] = _decode(info["CreationDate"])
        return metadata
    except Exception:
        return {}


# ── Structured HTML parser ────────────────────────────────────────────────────

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = _HEADING_TAGS | {"p", "table", "ul", "ol", "pre", "blockquote", "li"}
_NOISE_TAGS = ["script", "style", "nav", "footer", "header", "aside", "form"]


def _walk_html_blocks(soup_root: Any) -> list[tuple[str, Any]]:
    """
    Walk a BeautifulSoup tree and yield (tag_name, element) for block-level
    elements in document order, avoiding double-counting nested containers.
    """
    visited: set[int] = set()
    results: list[tuple[str, Any]] = []

    def _visit(node: Any) -> None:
        if not hasattr(node, "name") or node.name is None:
            return
        name = node.name.lower()
        if id(node) in visited:
            return
        if name in _BLOCK_TAGS:
            visited.add(id(node))
            results.append((name, node))
        else:
            for child in node.children:
                _visit(child)

    for child in soup_root.children:
        _visit(child)

    return results


def parse_html_structured(raw_bytes: bytes) -> StructuredParseResult:
    """
    Parse HTML preserving heading hierarchy and extracting tables as markdown.

    Uses BeautifulSoup with heading detection.  Falls back to flat extraction
    if BS4 is not available.
    """
    if not _BS4_AVAILABLE:
        result = parse_html(raw_bytes)
        return StructuredParseResult(
            raw_text=result.raw_text,
            clean_text=result.clean_text,
            source_type="html",
            sections=[],
            doc_metadata={},
        )

    html = raw_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(_NOISE_TAGS):
        tag.decompose()

    sections: list[DocumentSection] = []
    current_heading: Optional[str] = None
    current_level: int = 1
    current_parts: list[str] = []
    current_type: str = "text"

    def _flush() -> None:
        nonlocal current_heading, current_level, current_parts, current_type
        if current_parts or current_heading is not None:
            sections.append(
                DocumentSection(
                    heading=current_heading,
                    level=current_level,
                    content="\n".join(current_parts).strip(),
                    content_type=current_type,
                    table_markdown=None,
                )
            )
        current_heading = None
        current_level = 1
        current_parts = []
        current_type = "text"

    body = soup.find("body") or soup
    for tag_name, el in _walk_html_blocks(body):
        if tag_name in _HEADING_TAGS:
            _flush()
            current_heading = el.get_text(strip=True)
            current_level = int(tag_name[1])
        elif tag_name == "table":
            _flush()
            table_md = _bs4_table_to_markdown(el)
            sections.append(
                DocumentSection(
                    heading=None,
                    level=current_level + 1,
                    content=el.get_text(separator=" ", strip=True),
                    content_type="table",
                    table_markdown=table_md,
                )
            )
        elif tag_name in ("ul", "ol"):
            for li in el.find_all("li", recursive=False):
                current_parts.append(f"- {li.get_text(strip=True)}")
            current_type = "list"
        elif tag_name == "li":
            current_parts.append(f"- {el.get_text(strip=True)}")
            current_type = "list"
        else:
            text = el.get_text(separator=" ", strip=True)
            if text:
                current_parts.append(text)

    _flush()

    raw_text = soup.get_text(separator="\n")
    clean_text = _remove_boilerplate(_clean_whitespace(raw_text))

    return StructuredParseResult(
        raw_text=raw_text,
        clean_text=clean_text,
        source_type="html",
        sections=sections,
        doc_metadata={},
    )


# ── Structured PDF parser ─────────────────────────────────────────────────────

_UNSTRUCTURED_SKIP_TYPES = frozenset({"Header", "Footer", "PageNumber", "PageBreak"})


def _unstructured_elements_to_sections(elements: list) -> list[DocumentSection]:
    """Group unstructured elements into DocumentSection objects."""
    sections: list[DocumentSection] = []
    current_heading: Optional[str] = None
    current_level: int = 1
    current_parts: list[str] = []

    def _flush() -> None:
        nonlocal current_heading, current_level, current_parts
        if current_parts or current_heading is not None:
            sections.append(
                DocumentSection(
                    heading=current_heading,
                    level=current_level,
                    content="\n".join(current_parts).strip(),
                    content_type="text",
                    table_markdown=None,
                )
            )
        current_heading = None
        current_level = 1
        current_parts = []

    for el in elements:
        el_type = type(el).__name__
        if el_type in _UNSTRUCTURED_SKIP_TYPES:
            continue

        if el_type == "Title":
            _flush()
            current_heading = el.text.strip()
        elif el_type == "Table":
            _flush()
            table_html = getattr(getattr(el, "metadata", None), "text_as_html", None)
            table_md = _html_table_to_markdown(table_html) if table_html else (el.text or "")
            sections.append(
                DocumentSection(
                    heading=None,
                    level=current_level + 1,
                    content=el.text or "",
                    content_type="table",
                    table_markdown=table_md,
                )
            )
        elif el_type == "ListItem":
            current_parts.append(f"- {el.text}")
        else:
            if el.text:
                current_parts.append(el.text)

    _flush()
    return sections


def parse_pdf_structured(raw_bytes: bytes) -> StructuredParseResult:
    """
    Parse PDF preserving section headings and extracting tables as markdown.

    Uses unstructured.io when available (RAG_PARSER_BACKEND != 'pdfminer').
    Falls back to pdfminer flat extraction with empty sections.
    """
    backend = os.environ.get("RAG_PARSER_BACKEND", "unstructured").lower()
    doc_metadata = _extract_pdf_metadata(raw_bytes)

    if _UNSTRUCTURED_AVAILABLE and backend != "pdfminer":
        try:
            buf = io.BytesIO(raw_bytes)
            elements = _unstructured_partition_pdf(file=buf, strategy="fast")
            sections = _unstructured_elements_to_sections(elements)
            raw_text = "\n".join(el.text for el in elements if el.text)
            clean_text = _clean_whitespace(raw_text)
            return StructuredParseResult(
                raw_text=raw_text,
                clean_text=clean_text,
                source_type="pdf",
                sections=sections,
                doc_metadata=doc_metadata,
            )
        except Exception:
            pass  # fall through to pdfminer

    # Fallback: pdfminer flat extraction
    result = parse_pdf(raw_bytes)
    return StructuredParseResult(
        raw_text=result.raw_text,
        clean_text=result.clean_text,
        source_type="pdf",
        sections=[],
        doc_metadata=doc_metadata,
    )


# ── Legacy flat parsers (preserved for backward compat) ──────────────────────

def parse_html(raw_bytes: bytes) -> ParseResult:
    if not _BS4_AVAILABLE:
        raise RuntimeError(
            "beautifulsoup4 is required for HTML parsing. "
            "Install it with: pip install beautifulsoup4"
        )
    html = raw_bytes.decode("utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")

    # Remove script/style/nav/footer noise
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    raw_text = soup.get_text(separator="\n")
    clean = _remove_boilerplate(_clean_whitespace(raw_text))
    return ParseResult(raw_text=raw_text, clean_text=clean, source_type="html")


def parse_pdf(raw_bytes: bytes) -> ParseResult:
    if not _PDFMINER_AVAILABLE:
        raise RuntimeError(
            "pdfminer.six is required for PDF parsing. "
            "Install it with: pip install pdfminer.six"
        )
    buf = io.BytesIO(raw_bytes)
    raw_text = pdf_extract_text(buf)
    clean = _clean_whitespace(raw_text)
    return ParseResult(raw_text=raw_text, clean_text=clean, source_type="pdf")


def parse_text(raw_bytes_or_str: Any) -> ParseResult:
    if isinstance(raw_bytes_or_str, bytes):
        raw_text = raw_bytes_or_str.decode("utf-8", errors="replace")
    else:
        raw_text = str(raw_bytes_or_str)
    clean = _clean_whitespace(raw_text)
    return ParseResult(raw_text=raw_text, clean_text=clean, source_type="text")


# ── Main dispatcher ───────────────────────────────────────────────────────────

def parse(raw_bytes: bytes, source_type: str) -> StructuredParseResult:
    """
    Dispatch to the correct structure-preserving parser based on source_type.

    Always returns a StructuredParseResult (which carries raw_text, clean_text,
    source_type for backward compat plus sections and doc_metadata).

    Args:
        raw_bytes:   Raw content bytes (or text encoded as bytes).
        source_type: One of 'html', 'pdf', 'text', 'manual'.

    Returns:
        StructuredParseResult with raw_text, clean_text, sections, doc_metadata.
    """
    if source_type == "pdf":
        return parse_pdf_structured(raw_bytes)
    if source_type == "html":
        return parse_html_structured(raw_bytes)
    # text, manual, or unknown → plain text pass-through wrapped in StructuredParseResult
    flat = parse_text(raw_bytes)
    return StructuredParseResult(
        raw_text=flat.raw_text,
        clean_text=flat.clean_text,
        source_type=flat.source_type,
        sections=[],
        doc_metadata={},
    )
