"""Which day an uploaded statement describes (#141).

An upload's snapshot is dated, in order of preference:

1. ``file``: a date the file itself states (statement period end, an
   "as on" / "as of" line above a holdings table, ...), read by the parser into
   ``parser_meta``;
2. ``user``: the ``as_of`` date sent with the upload (the UI pre-fills today
   and lets the user change it);
3. ``fallback``: today in the app timezone (an API client that sent neither).

The file wins over the user's date: the UI always sends a date (today unless
changed), so letting it win would re-date every correctly dated statement to
the upload day, which is the bug this fixes.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable, Literal

from app.core.clock import app_today

AsOfSource = Literal["file", "user", "fallback"]

# parser_meta keys that carry a file-stated date, most specific first.
FILE_DATE_KEYS = ("statement_period_end", "report_date", "statement_date", "as_of")


def coerce_date(value: Any) -> date | None:
    """A date from a date/datetime/ISO string; None when it isn't one."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).strip()).date()
    except (ValueError, TypeError):
        return None


def file_date_from_meta(parser_meta: dict[str, Any] | None) -> date | None:
    meta = parser_meta or {}
    for key in FILE_DATE_KEYS:
        found = coerce_date(meta.get(key))
        if found is not None:
            return found
    return None


def resolve_upload_as_of(
    parser_meta: dict[str, Any] | None,
    user_as_of: date | None = None,
    positions: Iterable[dict[str, Any]] | None = None,
) -> tuple[date, AsOfSource]:
    """The snapshot date for an upload and where it came from (see module doc).

    ``positions`` lets balance parsers that date the balance row itself (not
    ``parser_meta``) count as a file date.
    """
    found = file_date_from_meta(parser_meta)
    if found is None:
        for pos in positions or ():
            found = coerce_date(pos.get("as_of"))
            if found is not None:
                break
    if found is not None:
        return found, "file"
    if user_as_of is not None:
        return user_as_of, "user"
    return app_today(), "fallback"


def as_of_metadata(as_of: date, source: AsOfSource, user_as_of: date | None) -> dict[str, Any]:
    """What gets recorded on the import run / snapshot and shown in the upload result."""
    meta: dict[str, Any] = {"as_of_date": as_of.isoformat(), "as_of_source": source}
    if user_as_of is not None:
        meta["user_as_of"] = user_as_of.isoformat()
        if source == "file" and user_as_of != as_of:
            meta["as_of_note"] = (
                f"The file states {as_of.isoformat()}; that date was used instead of "
                f"the chosen {user_as_of.isoformat()}."
            )
    return meta


# --- Reading a stated date out of a statement's free text -------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"

# A label that says "the date this statement is as of". A bare "Date" counts
# only at the start of a cell ("Date : 01-Oct-2026"), never mid-text, so a
# column like "Purchase Date" can't match.
_LABEL = re.compile(
    r"(?:\bas\s+(?:on|of|at)\b|\bstatement\s+date\b|\breport\s+date\b|\bvaluation\s+date\b"
    r"|\bholdings?\s+date\b|\bposition\s+date\b|^\s*date\b)\s*[:\-]?\s*",
    re.IGNORECASE,
)

_DATE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b"), "dmy"),
    (re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[\s\-]+" + _MON + r"[\s\-,]+(\d{4})\b", re.IGNORECASE), "d_mon_y"),
    (re.compile(r"^" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b", re.IGNORECASE), "mon_d_y"),
]


def _parse_date_at_start(text: str) -> date | None:
    text = text.strip()
    for pattern, kind in _DATE_PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        try:
            if kind == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if kind == "dmy":
                # Day first: the brokers that ship these files (India, Singapore) write dates day-first.
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if kind == "d_mon_y":
                return date(int(m.group(3)), _MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
            if kind == "mon_d_y":
                return date(int(m.group(3)), _MONTHS[m.group(1).lower()[:3]], int(m.group(2)))
        except (ValueError, KeyError):
            return None
    return None


def parse_date_text(text: str) -> date | None:
    """A date written at the start of ``text`` (ISO, day-first numeric, or with a month name)."""
    return _parse_date_at_start(text)


def _labelled_date(text: str) -> date | None:
    for m in _LABEL.finditer(text):
        found = _parse_date_at_start(text[m.end():])
        if found is not None:
            return found
    return None


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return "" if text.lower() in ("nan", "nat", "none") else text


def find_stated_date(cells: Iterable[Any]) -> date | None:
    """The first labelled date in a sequence of cells / text fragments.

    The label and the date may sit in one cell ("Holdings as on 01/10/2026") or
    in neighbouring cells ("As on" | 2026-10-01). Unlabelled dates are ignored:
    a holdings sheet has other dates (purchase, maturity) that aren't its as-of.
    """
    texts = [t for t in (_cell_text(c) for c in cells) if t]
    for i, text in enumerate(texts):
        found = _labelled_date(text)
        if found is None and i + 1 < len(texts) and _LABEL.search(text) and _LABEL.sub("", text).strip() == "":
            # The cell is only a label: the date is the next cell.
            found = _parse_date_at_start(texts[i + 1])
        if found is not None:
            return found
    return None


_TAG = re.compile(r"<[^>]+>")


def html_text_fragments(path: str) -> list[str]:
    """The text between tags of an HTML export, in document order."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []
    raw = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    fragments = [frag.replace("&nbsp;", " ").strip() for frag in _TAG.split(raw)]
    return [" ".join(frag.split()) for frag in fragments if frag.strip()]


def preamble_cells(rows: Any, before_row: int | None) -> list[Any]:
    """The cells, row by row, of a header=None sheet frame above its header row."""
    cells: list[Any] = []
    for idx, row in rows.iterrows():
        if before_row is not None and int(idx) >= before_row:
            break
        cells.extend(row.tolist())
    return cells
