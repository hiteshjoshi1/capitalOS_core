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
    content_type: str                # "heading" | "text" | "table" | "list" | "quote"
    table_markdown: Optional[str] = None  # Markdown table when content_type=="table"
    table_rows: Optional[list[list[str]]] = None
    items: Optional[list[str]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


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

def _table_tag_to_rows(table_tag: Any) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table_tag.find_all("tr"):
        cells = [td.get_text(separator=" ", strip=True) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    return rows


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    max_cols = max(len(row) for row in rows)
    padded = [row + [""] * (max_cols - len(row)) for row in rows]
    lines = ["| " + " | ".join(padded[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * max_cols) + " |")
    for row in padded[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _bs4_table_to_markdown(table_tag: Any) -> str:
    """Convert a BeautifulSoup <table> element to a markdown table string."""
    rows = _table_tag_to_rows(table_tag)
    if not rows:
        return table_tag.get_text(separator=" ", strip=True)
    return _rows_to_markdown(rows)


def _bs4_table_to_rows(table_tag: Any) -> list[list[str]]:
    return _table_tag_to_rows(table_tag)


def _markdown_table_to_rows(markdown: str) -> list[list[str]]:
    lines = [line.strip() for line in markdown.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    rows = []
    for index, line in enumerate(lines):
        if not line.startswith("|") or not line.endswith("|"):
            return []
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if index == 1 and all(re.fullmatch(r":?-{3,}:?", cell or "---") for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return []
    max_cols = max(len(row) for row in rows)
    return [row + [""] * (max_cols - len(row)) for row in rows]


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


def _html_table_to_rows(table_html: str) -> list[list[str]]:
    if not _BS4_AVAILABLE or not table_html:
        return []
    try:
        soup = BeautifulSoup(table_html, "html.parser")
        table = soup.find("table")
        if table:
            return _bs4_table_to_rows(table)
    except Exception:
        pass
    return _markdown_table_to_rows(table_html)


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
    current_level = 1

    body = soup.find("body") or soup
    for tag_name, el in _walk_html_blocks(body):
        if tag_name in _HEADING_TAGS:
            current_heading = el.get_text(strip=True)
            current_level = int(tag_name[1])
            sections.append(
                DocumentSection(
                    heading=current_heading,
                    level=current_level,
                    content="",
                    content_type="heading",
                )
            )
        elif tag_name == "table":
            table_md = _bs4_table_to_markdown(el)
            sections.append(
                DocumentSection(
                    heading=None,
                    level=current_level + 1,
                    content=el.get_text(separator=" ", strip=True),
                    content_type="table",
                    table_markdown=table_md,
                    table_rows=_bs4_table_to_rows(el),
                    metadata={"heading_context": current_heading} if current_heading else {},
                )
            )
        elif tag_name in ("ul", "ol"):
            items = [li.get_text(separator=" ", strip=True) for li in el.find_all("li", recursive=False)]
            if items:
                sections.append(
                    DocumentSection(
                        heading=None,
                        level=current_level + 1,
                        content="\n".join(f"- {item}" for item in items),
                        content_type="list",
                        items=items,
                        metadata={"heading_context": current_heading} if current_heading else {},
                    )
                )
        elif tag_name == "blockquote":
            text = el.get_text(separator=" ", strip=True)
            if text:
                sections.append(
                    DocumentSection(
                        heading=None,
                        level=current_level + 1,
                        content=text,
                        content_type="quote",
                        metadata={"heading_context": current_heading} if current_heading else {},
                    )
                )
        else:
            text = el.get_text(separator=" ", strip=True)
            if text:
                sections.append(
                    DocumentSection(
                        heading=None,
                        level=current_level + 1,
                        content=text,
                        content_type="text",
                        metadata={"heading_context": current_heading} if current_heading else {},
                    )
                )

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
    current_level = 1
    pending_list_items: list[str] = []

    def _flush_list() -> None:
        nonlocal pending_list_items
        if not pending_list_items:
            return
        sections.append(
            DocumentSection(
                heading=None,
                level=current_level + 1,
                content="\n".join(f"- {item}" for item in pending_list_items),
                content_type="list",
                items=list(pending_list_items),
                metadata={"heading_context": current_heading} if current_heading else {},
            )
        )
        pending_list_items = []

    for el in elements:
        el_type = type(el).__name__
        if el_type in _UNSTRUCTURED_SKIP_TYPES:
            continue

        if el_type == "Title":
            _flush_list()
            current_heading = el.text.strip()
            current_level = 1
            sections.append(
                DocumentSection(
                    heading=current_heading,
                    level=current_level,
                    content="",
                    content_type="heading",
                )
            )
        elif el_type == "Table":
            _flush_list()
            table_html = getattr(getattr(el, "metadata", None), "text_as_html", None)
            table_md = _html_table_to_markdown(table_html) if table_html else (el.text or "")
            sections.append(
                DocumentSection(
                    heading=None,
                    level=current_level + 1,
                    content=el.text or "",
                    content_type="table",
                    table_markdown=table_md,
                    table_rows=_html_table_to_rows(table_html) if table_html else _markdown_table_to_rows(table_md),
                    metadata={"heading_context": current_heading} if current_heading else {},
                )
            )
        elif el_type == "ListItem":
            if el.text:
                pending_list_items.append(el.text.strip())
        elif "Quote" in el_type:
            _flush_list()
            if el.text:
                sections.append(
                    DocumentSection(
                        heading=None,
                        level=current_level + 1,
                        content=el.text.strip(),
                        content_type="quote",
                        metadata={"heading_context": current_heading} if current_heading else {},
                    )
                )
        else:
            _flush_list()
            if el.text:
                sections.append(
                    DocumentSection(
                        heading=None,
                        level=current_level + 1,
                        content=el.text.strip(),
                        content_type="text",
                        metadata={"heading_context": current_heading} if current_heading else {},
                    )
                )

    _flush_list()
    return sections


def _text_block_to_section(block: str, current_heading: Optional[str], current_level: int) -> tuple[DocumentSection | None, Optional[str], int]:
    stripped = block.strip()
    if not stripped:
        return None, current_heading, current_level

    heading_match = re.fullmatch(r"(#{1,6})\s+(.+)", stripped)
    if heading_match:
        level = len(heading_match.group(1))
        heading = heading_match.group(2).strip()
        return (
            DocumentSection(
                heading=heading,
                level=level,
                content="",
                content_type="heading",
            ),
            heading,
            level,
        )

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    metadata = {"heading_context": current_heading} if current_heading else {}

    list_pattern = re.compile(r"^([-*+]\s+|\d+[.)]\s+)")
    if lines and all(list_pattern.match(line) for line in lines):
        items = [list_pattern.sub("", line, count=1).strip() for line in lines]
        return (
            DocumentSection(
                heading=None,
                level=current_level + 1,
                content="\n".join(f"- {item}" for item in items),
                content_type="list",
                items=items,
                metadata=metadata,
            ),
            current_heading,
            current_level,
        )

    if lines and all(line.startswith(">") for line in lines):
        quote = " ".join(line.lstrip(">").strip() for line in lines).strip()
        return (
            DocumentSection(
                heading=None,
                level=current_level + 1,
                content=quote,
                content_type="quote",
                metadata=metadata,
            ),
            current_heading,
            current_level,
        )

    paragraph = re.sub(r"\s+", " ", stripped).strip()
    return (
        DocumentSection(
            heading=None,
            level=current_level + 1,
            content=paragraph,
            content_type="text",
            metadata=metadata,
        ),
        current_heading,
        current_level,
    )


def parse_text_structured(raw_bytes_or_str: Any, *, source_type: str = "text") -> StructuredParseResult:
    flat = parse_text(raw_bytes_or_str)
    current_heading: Optional[str] = None
    current_level = 1
    sections: list[DocumentSection] = []
    for block in re.split(r"\n{2,}", flat.clean_text):
        section, current_heading, current_level = _text_block_to_section(block, current_heading, current_level)
        if section is not None:
            sections.append(section)
    return StructuredParseResult(
        raw_text=flat.raw_text,
        clean_text=flat.clean_text,
        source_type=source_type,
        sections=sections,
        doc_metadata={},
    )


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
    # text, manual, or unknown → structured text parsing with paragraph/list/quote support
    return parse_text_structured(raw_bytes, source_type="manual" if source_type == "manual" else "text")
