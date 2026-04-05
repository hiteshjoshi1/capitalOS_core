"""
Content parser for RAG ingestion.

Supports three source types:
  - html  : strip tags, extract visible text with BeautifulSoup
  - pdf   : extract text with pdfminer.six
  - text  : pass-through with minimal cleaning

All parsers return a ParseResult with raw_text and clean_text.
clean_text is safe to chunk and embed.
"""

import io
import re
from dataclasses import dataclass

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


@dataclass
class ParseResult:
    raw_text: str
    clean_text: str
    source_type: str


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


# ── Parsers ───────────────────────────────────────────────────────────────────

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


def parse_text(raw_bytes_or_str) -> ParseResult:
    if isinstance(raw_bytes_or_str, bytes):
        raw_text = raw_bytes_or_str.decode("utf-8", errors="replace")
    else:
        raw_text = str(raw_bytes_or_str)
    clean = _clean_whitespace(raw_text)
    return ParseResult(raw_text=raw_text, clean_text=clean, source_type="text")


def parse(raw_bytes: bytes, source_type: str) -> ParseResult:
    """
    Dispatch to the correct parser based on source_type.

    Args:
        raw_bytes: Raw content bytes (or text encoded as bytes).
        source_type: One of 'html', 'pdf', 'text', 'manual'.

    Returns:
        ParseResult with raw_text and clean_text.
    """
    if source_type == "pdf":
        return parse_pdf(raw_bytes)
    if source_type == "html":
        return parse_html(raw_bytes)
    # text, manual, or unknown → plain text pass-through
    return parse_text(raw_bytes)
