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
from html import escape
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
    table_html: Optional[str] = None
    table: Optional[dict[str, Any]] = None
    caption: Optional[str] = None
    notes: Optional[list[str]] = None
    items: Optional[list[str]] = None
    html: Optional[str] = None
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
    table = _table_tag_to_structured(table_tag)
    return _structured_table_to_rows(table) if table else []


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
    table = _table_tag_to_structured(table_tag)
    rows = _structured_table_to_rows(table) if table else []
    if not rows:
        return table_tag.get_text(separator=" ", strip=True)
    return _rows_to_markdown(rows)


def _bs4_table_to_rows(table_tag: Any) -> list[list[str]]:
    return _table_tag_to_rows(table_tag)


def _parse_span(value: Any) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _make_structured_cell(text: str, *, is_header: bool = False) -> dict[str, Any]:
    return {
        "text": _normalize_table_text(text),
        "rowspan": 1,
        "colspan": 1,
        "is_header": is_header,
    }


def _normalize_table_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalize_inline_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


_ALLOWED_INLINE_HTML_TAGS = {"a", "b", "br", "em", "i", "span", "strong", "sub", "sup", "u"}
_ALLOWED_INLINE_HTML_ATTRS = {
    "a": {"href", "title"},
}
_NUMERICISH_TEXT_RE = re.compile(r"^[\s$€£¥(+-]*\d[\d,]*(?:\.\d+)?%?\)?$")


def _sanitize_inline_html(fragment_html: str | None) -> str | None:
    if not _BS4_AVAILABLE or not fragment_html:
        return None
    soup = BeautifulSoup(fragment_html, "html.parser")
    for tag in soup.find_all(True):
        name = tag.name.lower()
        if name not in _ALLOWED_INLINE_HTML_TAGS:
            tag.unwrap()
            continue
        allowed_attrs = _ALLOWED_INLINE_HTML_ATTRS.get(name, set())
        for attr_name in list(tag.attrs):
            if attr_name not in allowed_attrs:
                del tag.attrs[attr_name]
        if name == "a":
            href = str(tag.get("href") or "").strip()
            if href and not re.match(r"^(https?:|mailto:|/)", href, flags=re.IGNORECASE):
                del tag.attrs["href"]
    html = "".join(str(child) for child in soup.contents).strip()
    return html or None


def _tag_inner_html(tag: Any) -> str | None:
    return _sanitize_inline_html("".join(str(child) for child in tag.contents))


def _tag_is_centered(tag: Any) -> bool:
    align = str(tag.get("align") or "").strip().lower()
    style = str(tag.get("style") or "").strip().lower()
    return align == "center" or "text-align:center" in style or "text-align: center" in style


def _tag_is_emphasized(tag: Any) -> bool:
    if tag.find(["b", "strong", "u"]):
        return True
    style = str(tag.get("style") or "").strip().lower()
    return "font-weight:bold" in style or "font-weight: bold" in style


def _text_looks_numericish(text: str) -> bool:
    normalized = _normalize_inline_text(text)
    if not normalized:
        return False
    return bool(_NUMERICISH_TEXT_RE.fullmatch(normalized))


def _looks_like_heading_text(text: str) -> bool:
    normalized = _normalize_inline_text(text)
    if not normalized or len(normalized) > 180:
        return False
    word_count = len(normalized.split())
    if word_count > 18:
        return False
    if normalized.endswith((".", "!", "?", ";")) and word_count > 8:
        return False
    return True


def _infer_html_heading_level(tag: Any, text: str) -> int:
    normalized = _normalize_inline_text(text)
    uppercaseish = normalized.upper() == normalized and any(char.isalpha() for char in normalized)
    if _tag_is_centered(tag) and uppercaseish and len(normalized.split()) <= 6:
        return 1
    return 2


def _is_semantic_heading_block(tag: Any, text: str) -> bool:
    if tag.name.lower() in _HEADING_TAGS:
        return True
    normalized = _normalize_inline_text(text)
    if not _looks_like_heading_text(normalized):
        return False
    uppercaseish = normalized.upper() == normalized and any(char.isalpha() for char in normalized)
    titleish = normalized == normalized.title()
    emphasized = _tag_is_emphasized(tag)
    centered = _tag_is_centered(tag)
    colon_heading = normalized.endswith(":") and len(normalized.split()) <= 12
    return (centered and (emphasized or uppercaseish or titleish)) or (emphasized and (uppercaseish or titleish or colon_heading))


def _table_cell_from_tag(cell_tag: Any, *, default_is_header: bool = False) -> dict[str, Any]:
    scope = str(cell_tag.get("scope") or "").strip().lower()
    return {
        "text": _normalize_table_text(cell_tag.get_text(separator=" ", strip=True)),
        "rowspan": _parse_span(cell_tag.get("rowspan")),
        "colspan": _parse_span(cell_tag.get("colspan")),
        "is_header": default_is_header or cell_tag.name.lower() == "th" or scope in {"col", "row", "colgroup", "rowgroup"},
    }


def _table_row_from_tag(row_tag: Any, *, default_is_header: bool = False) -> list[dict[str, Any]]:
    cells = [
        _table_cell_from_tag(cell, default_is_header=default_is_header)
        for cell in row_tag.find_all(["th", "td"], recursive=False)
    ]
    return [cell for cell in cells if cell["text"] or cell["rowspan"] > 1 or cell["colspan"] > 1]


def _row_tag_looks_like_header(row_tag: Any) -> bool:
    cells = row_tag.find_all(["th", "td"], recursive=False)
    if not cells:
        return False
    texts = [_normalize_inline_text(cell.get_text(separator=" ", strip=True)) for cell in cells]
    non_empty = [text for text in texts if text]
    if not non_empty:
        return False
    if all(cell.name.lower() == "th" for cell in cells):
        return True
    year_like_count = sum(1 for text in non_empty if re.fullmatch(r"(?:19|20)\d{2}", text))
    numericish_count = sum(1 for text in non_empty if _text_looks_numericish(text))
    emphasized_count = sum(
        1
        for cell in cells
        if _normalize_inline_text(cell.get_text(separator=" ", strip=True)) and _tag_is_emphasized(cell)
    )
    has_span = any(
        _parse_span(cell.get("colspan")) > 1 or _parse_span(cell.get("rowspan")) > 1
        for cell in cells
    )
    if numericish_count == 0:
        return True
    if year_like_count >= 2 and numericish_count == len(non_empty):
        return True
    if has_span and numericish_count <= 1:
        return True
    return emphasized_count == len(non_empty) and numericish_count <= 1


def _split_direct_table_rows(table_tag: Any) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]]]:
    row_tags = table_tag.find_all("tr", recursive=False)
    if not row_tags:
        return [], []
    header_count = 0
    for index, row_tag in enumerate(row_tags[:3]):
        if not _row_tag_looks_like_header(row_tag):
            break
        header_count = index + 1
    if header_count == 0 and len(row_tags) >= 2:
        first_row_texts = [
            _normalize_inline_text(cell.get_text(separator=" ", strip=True))
            for cell in row_tags[0].find_all(["th", "td"], recursive=False)
        ]
        second_row_texts = [
            _normalize_inline_text(cell.get_text(separator=" ", strip=True))
            for cell in row_tags[1].find_all(["th", "td"], recursive=False)
        ]
        if first_row_texts and any(text and not _text_looks_numericish(text) for text in first_row_texts) and any(_text_looks_numericish(text) for text in second_row_texts):
            header_count = 1
    header_rows = [
        _table_row_from_tag(row_tag, default_is_header=True)
        for row_tag in row_tags[:header_count]
    ]
    body_rows = [
        _table_row_from_tag(row_tag)
        for row_tag in row_tags[header_count:]
    ]
    return [row for row in header_rows if row], [row for row in body_rows if row]


def _looks_like_layout_table(table_tag: Any) -> bool:
    nested_tables = table_tag.find_all("table")
    nested_table_count = sum(1 for nested in nested_tables if nested is not table_tag)
    direct_rows = table_tag.find_all("tr", recursive=False)
    if not direct_rows:
        tbody = table_tag.find("tbody", recursive=False)
        if tbody is not None:
            direct_rows = tbody.find_all("tr", recursive=False)
    direct_cells: list[Any] = []
    for row in direct_rows:
        direct_cells.extend(row.find_all(["td", "th"], recursive=False))
    cell_texts = [_normalize_inline_text(cell.get_text(separator=" ", strip=True)) for cell in direct_cells]
    prose_cell_count = sum(1 for text in cell_texts if len(text.split()) >= 20 and re.search(r"[.!?;:]", text))
    text_length = len(_normalize_inline_text(table_tag.get_text(separator=" ", strip=True)))
    if prose_cell_count >= 1 and len(direct_rows) <= 4:
        return True
    if len(cell_texts) <= 3 and text_length >= 1000:
        return True
    if nested_table_count == 0:
        return False
    if direct_rows and len(direct_rows) <= 2 and nested_table_count >= 1:
        return True
    if direct_cells and len(direct_cells) <= 2 and nested_table_count >= 1:
        return True
    return text_length >= 1200


def _split_preformatted_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for raw_line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        if line.strip():
            current.append(line)
            continue
        if current:
            chunks.append("\n".join(current).strip())
            current = []
    if current:
        chunks.append("\n".join(current).strip())
    return chunks


def _normalize_preformatted_table_line(line: str) -> str:
    return re.sub(r"([\$€£¥§])\s{2,}(?=\d)", r"\1 ", line.expandtabs(4).rstrip())


_PREFORMATTED_VALUE_RE = re.compile(
    r"(?:[\$€£¥§]?\s*(?:\(\d[\d,]*(?:\.\d+)?%?\)|-?\d[\d,]*(?:\.\d+)?%?|--+))"
)


def _is_preformatted_rule_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and all(char in {"-", "=", " "} for char in stripped)


def _is_preformatted_note_line(line: str) -> bool:
    normalized = _normalize_table_text(line)
    return bool(normalized) and bool(
        re.search(r"\b(?:omitted|amounts?\s+in|millions?|source:)\b", normalized, flags=re.IGNORECASE)
    )


def _is_year_like_value(text: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", _normalize_table_text(text)))


def _parse_preformatted_header_cells(line: str) -> list[str]:
    return [
        _normalize_table_text(cell)
        for cell in re.split(r"\s{2,}", line.strip())
        if _normalize_table_text(cell)
    ]


def _split_preformatted_cells(line: str) -> list[str]:
    return [
        _normalize_table_text(cell)
        for cell in re.split(r"\s{2,}", line.strip())
        if _normalize_table_text(cell)
    ]


def _clean_preformatted_label(label: str) -> str:
    cleaned = _normalize_table_text(label)
    cleaned = re.sub(r"\s*\.{2,}\s*$", "", cleaned).strip()
    return cleaned


def _preformatted_inferred_value_count(line: str) -> int:
    matches = list(_PREFORMATTED_VALUE_RE.finditer(line))
    if not matches:
        return 0

    count = 0
    index = 0
    while index < len(matches):
        run_end = index
        while run_end + 1 < len(matches):
            separator = line[matches[run_end].end() : matches[run_end + 1].start()].strip()
            if separator in {"/", "-"}:
                run_end += 1
                continue
            break
        if run_end > index:
            index = run_end + 1
            continue
        count += 1
        index += 1
    return count


def _infer_preformatted_expected_value_count(lines: list[str], *, separator_index: int) -> int:
    split_value_counts: list[int] = []
    candidate_value_counts: list[int] = []
    for index, line in enumerate(lines):
        if index == separator_index or _is_preformatted_rule_line(line) or _is_preformatted_note_line(line):
            continue
        normalized_line = _normalize_table_text(line)
        if normalized_line.endswith(":"):
            continue
        split_value_count = sum(1 for cell in _split_preformatted_cells(line) if _text_looks_numericish(cell))
        if split_value_count:
            split_value_counts.append(split_value_count)
        value_count = _preformatted_inferred_value_count(line)
        if value_count:
            candidate_value_counts.append(value_count)

    if split_value_counts:
        return max(split_value_counts)
    if not candidate_value_counts:
        return 0
    return max(candidate_value_counts)


def _parse_preformatted_data_row(
    line: str,
    *,
    expected_value_count: int,
    pending_prefixes: list[str] | None = None,
) -> list[str] | None:
    split_cells = _split_preformatted_cells(line)
    pending_text = _normalize_table_text(" ".join(part for part in (pending_prefixes or []) if part))

    if split_cells and expected_value_count > 0:
        numeric_count = sum(1 for cell in split_cells if _text_looks_numericish(cell))
        if numeric_count == expected_value_count:
            if _text_looks_numericish(split_cells[0]) and len(split_cells) >= expected_value_count + 1:
                label = _clean_preformatted_label(split_cells[1]) if len(split_cells) > 1 else ""
                if pending_text:
                    label = _normalize_table_text(f"{pending_text} {label}" if label else pending_text)
                return [split_cells[0], label] + split_cells[2:]

            label = _clean_preformatted_label(split_cells[0])
            if pending_text:
                label = _normalize_table_text(f"{pending_text} {label}" if label else pending_text)
            return [label] + split_cells[1:]

    matches = list(_PREFORMATTED_VALUE_RE.finditer(line))
    if not matches:
        return None

    if (
        expected_value_count >= 2
        and len(matches) >= expected_value_count
        and not line[: matches[0].start()].strip()
    ):
        first_token = _normalize_table_text(matches[0].group(0))
        between_first_second = _clean_preformatted_label(line[matches[0].end() : matches[1].start()])
        trailing_values = [_normalize_table_text(match.group(0)) for match in matches[1:]][-(expected_value_count - 1) :]
        if between_first_second:
            label = _normalize_table_text(f"{pending_text} {between_first_second}" if pending_text else between_first_second)
            return [first_token, label] + trailing_values
        if pending_text:
            return [first_token, pending_text] + trailing_values
        return [first_token] + trailing_values

    if expected_value_count > 0 and len(matches) >= expected_value_count:
        matches = matches[-expected_value_count:]
    prefix = line[: matches[0].start()]
    label = _clean_preformatted_label(prefix)
    if pending_text:
        label = _normalize_table_text(f"{pending_text} {label}" if label else pending_text)
    values = [_normalize_table_text(match.group(0)) for match in matches]
    if not label and not any(values):
        return None
    return [label] + values


def _build_preformatted_table(cells_by_row: list[list[str]], *, header_rows_count: int = 0, notes: list[str] | None = None) -> dict[str, Any] | None:
    rows = [row for row in cells_by_row if any(cell for cell in row)]
    if len(rows) < 2:
        return None
    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    header_rows = [
        [_make_structured_cell(cell, is_header=True) for cell in row]
        for row in normalized_rows[:header_rows_count]
    ]
    body_rows = [
        [_make_structured_cell(cell) for cell in row]
        for row in normalized_rows[header_rows_count:]
    ]
    if not body_rows:
        return None
    return {
        "caption": None,
        "header_rows": header_rows,
        "body_rows": body_rows,
        "footer_rows": [],
        "notes": list(notes or []),
    }


def _preformatted_table_from_chunk(chunk: str) -> dict[str, Any] | None:
    lines = [_normalize_preformatted_table_line(line) for line in chunk.splitlines() if line.strip()]
    if len(lines) < 3:
        return None

    separator_index = next(
        (
            index
            for index, line in enumerate(lines)
            if len(list(re.finditer(r"-{3,}", line))) >= 2
        ),
        -1,
    )
    if separator_index >= 0:
        expected_value_count = _infer_preformatted_expected_value_count(
            lines,
            separator_index=separator_index,
        )

        header_rows: list[list[str]] = []
        body_rows: list[list[str]] = []
        notes: list[str] = []
        pending_prefixes: list[str] = []
        data_started = False

        for index, line in enumerate(lines):
            if index == separator_index or _is_preformatted_rule_line(line):
                continue

            normalized_line = _normalize_table_text(line)
            value_matches = list(_PREFORMATTED_VALUE_RE.finditer(line))
            value_texts = [_normalize_table_text(match.group(0)) for match in value_matches]
            value_count = len(value_matches)
            all_years = bool(value_texts) and all(_is_year_like_value(value) for value in value_texts)

            if not data_started:
                if _is_preformatted_note_line(line) or normalized_line.endswith(":"):
                    notes.append(normalized_line)
                    continue
                if value_count == 0:
                    header_cells = _parse_preformatted_header_cells(line)
                    if header_cells:
                        header_rows.append(header_cells)
                    continue
                if all_years:
                    header_cells = _parse_preformatted_header_cells(line)
                    if header_cells:
                        header_rows.append(header_cells)
                    continue
                if expected_value_count and value_count >= expected_value_count:
                    data_started = True
                else:
                    header_cells = _parse_preformatted_header_cells(line)
                    if header_cells:
                        header_rows.append(header_cells)
                    continue

            if _is_preformatted_note_line(line):
                notes.append(normalized_line)
                continue
            if value_count == 0:
                if normalized_line.endswith(":"):
                    notes.append(normalized_line)
                else:
                    pending_prefixes.append(_clean_preformatted_label(normalized_line))
                continue

            parsed_row = _parse_preformatted_data_row(
                line,
                expected_value_count=expected_value_count,
                pending_prefixes=pending_prefixes,
            )
            pending_prefixes = []
            if parsed_row:
                body_rows.append(parsed_row)

        if pending_prefixes:
            notes.extend(prefix for prefix in pending_prefixes if prefix)

        return _build_preformatted_table(header_rows + body_rows, header_rows_count=len(header_rows), notes=notes)

    split_rows: list[list[str]] = []
    for line in lines:
        cells = [_normalize_table_text(cell) for cell in re.split(r"\s{2,}", line.strip()) if _normalize_table_text(cell)]
        if len(cells) >= 2:
            split_rows.append(cells)
    if len(split_rows) < 3:
        return None

    numeric_value_rows = sum(
        1
        for row in split_rows
        if any(_text_looks_numericish(cell) for cell in row[1:])
    )
    max_cells = max((len(row) for row in split_rows), default=0)
    if numeric_value_rows < 2 and max_cells < 4:
        return None

    first_row = split_rows[0]
    header_rows_count = 1 if sum(_text_looks_numericish(cell) for cell in first_row) < len(first_row) else 0
    return _build_preformatted_table(split_rows, header_rows_count=header_rows_count)


def _chunk_has_preformatted_table_separator(chunk: str) -> bool:
    return any(len(list(re.finditer(r"-{3,}", line))) >= 2 for line in chunk.splitlines())


def _chunk_looks_like_preformatted_table_continuation(chunk: str) -> bool:
    candidate_lines = [_normalize_preformatted_table_line(line) for line in chunk.splitlines() if line.strip()]
    if len(candidate_lines) < 1:
        return False
    multi_cell_rows = 0
    for line in candidate_lines:
        cells = [_normalize_table_text(cell) for cell in re.split(r"\s{2,}", line.strip()) if _normalize_table_text(cell)]
        if len(cells) >= 2 and any(_text_looks_numericish(cell) for cell in cells[1:]):
            multi_cell_rows += 1
    return multi_cell_rows >= 1


def _merge_preformatted_table_chunks(chunks: list[str]) -> list[str]:
    if len(chunks) < 2:
        return chunks

    merged: list[str] = []
    index = 0
    while index < len(chunks):
        current = chunks[index]
        while index + 1 < len(chunks):
            combined = f"{current}\n\n{chunks[index + 1]}"
            current_is_tableish = _chunk_has_preformatted_table_separator(current) or _chunk_looks_like_preformatted_table_continuation(current)
            if current_is_tableish and _preformatted_table_from_chunk(combined):
                current = combined
                index += 1
                continue
            if _chunk_has_preformatted_table_separator(current) and _chunk_looks_like_preformatted_table_continuation(chunks[index + 1]):
                current = combined
                index += 1
                continue
            break
        merged.append(current)
        index += 1
    return merged


def _preformatted_tag_to_sections(
    pre_tag: Any,
    *,
    current_heading: Optional[str],
    current_level: int,
) -> list[DocumentSection]:
    chunks = _merge_preformatted_table_chunks(_split_preformatted_chunks(pre_tag.get_text("\n", strip=False)))
    if not chunks:
        return []

    chunk_tables = [_preformatted_table_from_chunk(chunk) for chunk in chunks]
    if not any(chunk_tables):
        text = _normalize_inline_text(pre_tag.get_text(separator=" ", strip=True))
        if not text:
            return []
        return [
            DocumentSection(
                heading=None,
                level=current_level + 1,
                content=text,
                content_type="text",
                html=_tag_inner_html(pre_tag),
                metadata={"heading_context": current_heading} if current_heading else {},
            )
        ]

    sections: list[DocumentSection] = []
    for chunk, table in zip(chunks, chunk_tables):
        if table:
            table_md, table_rows, table_html, structured_table, caption, notes = _table_payload_from_structured(
                table,
                chunk,
            )
            sections.append(
                DocumentSection(
                    heading=None,
                    level=current_level + 1,
                    content=_normalize_inline_text(chunk),
                    content_type="table",
                    table_markdown=table_md,
                    table_rows=table_rows,
                    table_html=table_html,
                    table=structured_table,
                    caption=caption,
                    notes=notes,
                    metadata={
                        **({"heading_context": current_heading} if current_heading else {}),
                        "_parser_source": "html",
                    },
                )
            )
            continue

        text = _normalize_inline_text(chunk)
        if not text:
            continue
        sections.append(
            DocumentSection(
                heading=None,
                level=current_level + 1,
                content=text,
                content_type="text",
                metadata={"heading_context": current_heading} if current_heading else {},
            )
        )
    return sections


def _table_rows_from_container(container: Any, *, default_is_header: bool = False) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for tr in container.find_all("tr", recursive=False):
        cells = _table_row_from_tag(tr, default_is_header=default_is_header)
        if cells:
            rows.append(cells)
    return rows


def _derive_table_notes(
    footer_rows: list[list[dict[str, Any]]],
    *,
    column_count: int,
) -> list[str]:
    notes: list[str] = []
    for row in footer_rows:
        if not row:
            continue
        text = _normalize_table_text(" ".join(str(cell.get("text") or "") for cell in row))
        if not text:
            continue
        total_span = sum(_parse_span(cell.get("colspan")) for cell in row)
        if len(row) == 1 or total_span >= max(column_count, 1):
            notes.append(text)
            continue
        if re.match(r"^(note|notes|\*|amounts?\s+in)\b", text, flags=re.IGNORECASE):
            notes.append(text)
    return notes


def _structured_table_column_count(table: dict[str, Any] | None) -> int:
    if not table:
        return 0
    max_cols = 0
    for group_name in ("header_rows", "body_rows", "footer_rows"):
        for row in table.get(group_name) or []:
            width = sum(_parse_span(cell.get("colspan")) for cell in row)
            max_cols = max(max_cols, width)
    return max_cols


def _structured_table_to_rows(table: dict[str, Any] | None) -> list[list[str]]:
    if not table:
        return []

    flattened: list[list[str]] = []
    pending_rowspans: dict[int, int] = {}
    grouped_rows = [
        *(table.get("header_rows") or []),
        *(table.get("body_rows") or []),
        *(table.get("footer_rows") or []),
    ]

    for row in grouped_rows:
        flat_row: list[str] = []
        col_index = 0

        def _consume_pending() -> None:
            nonlocal col_index
            while pending_rowspans.get(col_index, 0) > 0:
                flat_row.append("")
                pending_rowspans[col_index] -= 1
                if pending_rowspans[col_index] <= 0:
                    pending_rowspans.pop(col_index, None)
                col_index += 1

        _consume_pending()
        for cell in row:
            _consume_pending()
            text = str(cell.get("text") or "")
            colspan = _parse_span(cell.get("colspan"))
            rowspan = _parse_span(cell.get("rowspan"))
            flat_row.append(text)
            for _ in range(colspan - 1):
                flat_row.append("")
            if rowspan > 1:
                for span_col in range(col_index, col_index + colspan):
                    pending_rowspans[span_col] = max(pending_rowspans.get(span_col, 0), rowspan - 1)
            col_index += colspan
        _consume_pending()
        flattened.append(flat_row)

    if not flattened:
        return []
    width = max(len(row) for row in flattened)
    return [row + [""] * (width - len(row)) for row in flattened]


def _render_structured_table_html(table: dict[str, Any]) -> str:
    parts = ["<table>"]
    caption = _normalize_table_text(str(table.get("caption") or ""))
    if caption:
        parts.append(f"<caption>{escape(caption)}</caption>")

    def _render_group(tag_name: str, rows: list[list[dict[str, Any]]]) -> None:
        if not rows:
            return
        parts.append(f"<{tag_name}>")
        for row in rows:
            parts.append("<tr>")
            for cell in row:
                cell_tag = "th" if cell.get("is_header") else "td"
                attrs: list[str] = []
                rowspan = _parse_span(cell.get("rowspan"))
                colspan = _parse_span(cell.get("colspan"))
                if rowspan > 1:
                    attrs.append(f' rowspan="{rowspan}"')
                if colspan > 1:
                    attrs.append(f' colspan="{colspan}"')
                if cell_tag == "th":
                    attrs.append(' scope="col"')
                parts.append(f"<{cell_tag}{''.join(attrs)}>{escape(str(cell.get('text') or ''))}</{cell_tag}>")
            parts.append("</tr>")
        parts.append(f"</{tag_name}>")

    _render_group("thead", table.get("header_rows") or [])
    _render_group("tbody", table.get("body_rows") or [])
    _render_group("tfoot", table.get("footer_rows") or [])
    parts.append("</table>")
    return "".join(parts)


def _table_tag_to_structured(table_tag: Any) -> dict[str, Any] | None:
    caption_tag = table_tag.find("caption", recursive=False)
    caption = _normalize_table_text(caption_tag.get_text(separator=" ", strip=True)) if caption_tag else None
    header_rows = _table_rows_from_container(table_tag.find("thead", recursive=False), default_is_header=True) if table_tag.find("thead", recursive=False) else []
    body_rows: list[list[dict[str, Any]]] = []
    for tbody in table_tag.find_all("tbody", recursive=False):
        body_rows.extend(_table_rows_from_container(tbody))
    footer_rows: list[list[dict[str, Any]]] = []
    for tfoot in table_tag.find_all("tfoot", recursive=False):
        footer_rows.extend(_table_rows_from_container(tfoot))

    inferred_header, inferred_body = _split_direct_table_rows(table_tag)
    if inferred_header and not header_rows:
        header_rows = inferred_header
    body_rows.extend(inferred_body)

    if not header_rows and not body_rows and not footer_rows:
        return None

    table = {
        "caption": caption,
        "header_rows": header_rows,
        "body_rows": body_rows,
        "footer_rows": footer_rows,
        "notes": [],
    }
    table["notes"] = _derive_table_notes(
        footer_rows,
        column_count=_structured_table_column_count(table),
    )
    return table


def _table_payload_from_structured(table: dict[str, Any] | None, fallback_text: str) -> tuple[str | None, list[list[str]] | None, str | None, dict[str, Any] | None, str | None, list[str] | None]:
    if not table:
        text = _normalize_table_text(fallback_text)
        return (text or None, None, None, None, None, None)
    rows = _structured_table_to_rows(table)
    markdown = _rows_to_markdown(rows) if rows else None
    caption = str(table.get("caption") or "").strip() or None
    notes = [str(note).strip() for note in table.get("notes") or [] if str(note).strip()]
    return (
        markdown,
        rows or None,
        _render_structured_table_html(table),
        table,
        caption,
        notes or None,
    )


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
            markdown, _, _, _, _, _ = _table_payload_from_structured(
                _table_tag_to_structured(table),
                table.get_text(separator=" ", strip=True),
            )
            return markdown or table.get_text(separator=" ", strip=True)
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
            return _table_tag_to_rows(table)
    except Exception:
        pass
    return _markdown_table_to_rows(table_html)


def _html_table_to_structured(table_html: str) -> dict[str, Any] | None:
    if not _BS4_AVAILABLE or not table_html:
        return None
    try:
        soup = BeautifulSoup(table_html, "html.parser")
        table = soup.find("table")
        if table:
            return _table_tag_to_structured(table)
    except Exception:
        return None
    return None


def _table_has_spans(table: dict[str, Any] | None) -> bool:
    if not table:
        return False
    for group_name in ("header_rows", "body_rows", "footer_rows"):
        for row in table.get(group_name) or []:
            for cell in row:
                if _parse_span(cell.get("rowspan")) > 1 or _parse_span(cell.get("colspan")) > 1:
                    return True
    return False


def _unstructured_table_fidelity_score(element: Any) -> int:
    if type(element).__name__ != "Table":
        return 0

    score = 1
    table_html = getattr(getattr(element, "metadata", None), "text_as_html", None)
    if table_html and "<table" in table_html.lower():
        score += 2

    structured = _html_table_to_structured(table_html) if table_html else None
    if structured:
        score += 2
        if structured.get("header_rows"):
            score += 1
        if structured.get("body_rows"):
            score += 1
        if structured.get("footer_rows"):
            score += 1
        if structured.get("caption"):
            score += 1
        if _table_has_spans(structured):
            score += 1

    return score


def _elements_table_fidelity_score(elements: list) -> int:
    return sum(_unstructured_table_fidelity_score(element) for element in elements)


def _elements_need_hi_res_table_inference(elements: list) -> bool:
    table_elements = [element for element in elements if type(element).__name__ == "Table"]
    if not table_elements:
        return True
    return any(_unstructured_table_fidelity_score(element) < 6 for element in table_elements)


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
_BLOCK_TAGS = _HEADING_TAGS | {"blockquote", "center", "div", "ol", "p", "pre", "table", "ul"}
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
        if name == "table":
            if _looks_like_layout_table(node):
                for child in node.children:
                    _visit(child)
            else:
                visited.add(id(node))
                results.append((name, node))
        elif name in _HEADING_TAGS | {"p", "pre", "ul", "ol", "blockquote"}:
            visited.add(id(node))
            results.append((name, node))
        elif name in {"div", "center"}:
            direct_meaningful_children = [
                child for child in node.find_all(_BLOCK_TAGS, recursive=False)
                if getattr(child, "name", None) and child.name.lower() not in {"div", "center"}
            ]
            if direct_meaningful_children:
                for child in node.children:
                    _visit(child)
            else:
                text = _normalize_inline_text(node.get_text(separator=" ", strip=True))
                if text:
                    visited.add(id(node))
                    results.append(("p", node))
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
        text = el.get_text(separator=" ", strip=True)
        html = _tag_inner_html(el)
        if tag_name == "table":
            table_md, table_rows, table_html, table, caption, notes = _table_payload_from_structured(
                _table_tag_to_structured(el),
                el.get_text(separator=" ", strip=True),
            )
            sections.append(
                DocumentSection(
                    heading=None,
                    level=current_level + 1,
                    content=el.get_text(separator=" ", strip=True),
                    content_type="table",
                    table_markdown=table_md,
                    table_rows=table_rows,
                    table_html=table_html,
                    table=table,
                    caption=caption,
                    notes=notes,
                    metadata={
                        **({"heading_context": current_heading} if current_heading else {}),
                        "_parser_source": "html",
                    },
                )
            )
        elif tag_name in _HEADING_TAGS or _is_semantic_heading_block(el, text):
            current_heading = _normalize_inline_text(text)
            current_level = int(tag_name[1]) if tag_name in _HEADING_TAGS else _infer_html_heading_level(el, text)
            sections.append(
                DocumentSection(
                    heading=current_heading,
                    level=current_level,
                    content="",
                    content_type="heading",
                    html=html,
                )
            )
        elif tag_name == "pre":
            sections.extend(
                _preformatted_tag_to_sections(
                    el,
                    current_heading=current_heading,
                    current_level=current_level,
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
            if text:
                sections.append(
                    DocumentSection(
                        heading=None,
                        level=current_level + 1,
                        content=text,
                        content_type="quote",
                        html=html,
                        metadata={"heading_context": current_heading} if current_heading else {},
                    )
                )
        else:
            if text:
                sections.append(
                    DocumentSection(
                        heading=None,
                        level=current_level + 1,
                        content=text,
                        content_type="text",
                        html=html,
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
        doc_metadata={"title": _normalize_inline_text(soup.title.get_text(" ", strip=True))} if soup.title else {},
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
            table_structured = _html_table_to_structured(table_html) if table_html else None
            table_md, table_rows, sanitized_table_html, table, caption, notes = _table_payload_from_structured(
                table_structured,
                el.text or "",
            )
            if not table_md:
                table_md = (el.text or "").strip() or None
            sections.append(
                DocumentSection(
                    heading=None,
                    level=current_level + 1,
                    content=el.text or "",
                    content_type="table",
                    table_markdown=table_md,
                    table_rows=table_rows or (_html_table_to_rows(table_html) if table_html else _markdown_table_to_rows(table_md)),
                    table_html=sanitized_table_html,
                    table=table,
                    caption=caption,
                    notes=notes,
                    metadata={
                        **({"heading_context": current_heading} if current_heading else {}),
                        "_parser_source": "pdf",
                    },
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


def _has_unstructured_table_elements(elements: list) -> bool:
    return any(type(el).__name__ == "Table" for el in elements)


def _partition_pdf_with_unstructured(raw_bytes: bytes) -> list:
    last_successful: list | None = None
    last_error: Exception | None = None
    fast_elements: list | None = None
    fast_score = -1

    try:
        fast_elements = _unstructured_partition_pdf(file=io.BytesIO(raw_bytes), strategy="fast")
        last_successful = fast_elements
        fast_score = _elements_table_fidelity_score(fast_elements)
        if not _elements_need_hi_res_table_inference(fast_elements):
            return fast_elements
    except Exception as exc:
        last_error = exc

    try:
        hi_res_elements = _unstructured_partition_pdf(
            file=io.BytesIO(raw_bytes),
            strategy="hi_res",
            infer_table_structure=True,
        )
        last_successful = hi_res_elements
        hi_res_score = _elements_table_fidelity_score(hi_res_elements)
        if fast_elements is None or hi_res_score >= fast_score:
            return hi_res_elements
        return fast_elements
    except Exception as exc:
        last_error = exc

    if last_successful is not None:
        return last_successful
    if last_error is not None:
        raise last_error
    return []


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
            elements = _partition_pdf_with_unstructured(raw_bytes)
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
