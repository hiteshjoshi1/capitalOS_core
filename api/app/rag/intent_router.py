"""
Pre-retrieval intent routing for AI Sage.

Converts a natural-language user query into a structured QueryIntent that
drives author selection and retrieval.  Uses a cheap, configurable routing
model when available; falls back to a pure-Python text parser.

The routing model is controlled by ROUTING_LLM_MODEL (separate from the
main INFERENCE_LLM_MODEL) so it can be set to a fast/cheap model such as
Qwen or Gemini Flash through OpenRouter.
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Source type aliases ───────────────────────────────────────────────────────

_SOURCE_TYPE_MAP: dict[str, str] = {
    "letter": "text",
    "letters": "text",
    "shareholder letter": "text",
    "annual letter": "text",
    "memo": "text",
    "essay": "text",
    "annual report": "pdf",
    "report": "pdf",
    "transcript": "text",
    "speech": "text",
    "html": "html",
    "pdf": "pdf",
}

# Normalized source_type values understood by retrieval.py
_KNOWN_SOURCE_TYPES = {"text", "html", "pdf", "manual"}

# ── Output-shape keywords ─────────────────────────────────────────────────────

_OUTPUT_SHAPES = (
    "investment advice",
    "investing philosophy",
    "life advice",
    "life lessons",
    "mental model",
    "aphorisms",
    "aphorism",
    "quotes",
    "quote",
    "maxims",
    "maxim",
    "principles",
    "framework",
)

# ── Known-author name patterns ────────────────────────────────────────────────
# Lower-cased display names → author_id.  Extend as needed; the text parser
# matches these case-insensitively so no need to list every casing variant.

_KNOWN_AUTHORS: dict[str, str] = {
    "warren buffett": "warren_buffett",
    "buffett": "warren_buffett",
    "charlie munger": "charlie_munger",
    "munger": "charlie_munger",
    "nick sleep": "nick_sleep",
    "sleep": "nick_sleep",
    "peter lynch": "peter_lynch",
    "lynch": "peter_lynch",
    "howard marks": "howard_marks",
    "marks": "howard_marks",
    "bill ackman": "bill_ackman",
    "ackman": "bill_ackman",
    "michael burry": "michael_burry",
    "burry": "michael_burry",
    "ray dalio": "ray_dalio",
    "dalio": "ray_dalio",
    "seth klarman": "seth_klarman",
    "klarman": "seth_klarman",
    "joel greenblatt": "joel_greenblatt",
    "greenblatt": "joel_greenblatt",
    "david einhorn": "david_einhorn",
    "einhorn": "david_einhorn",
    "li lu": "li_lu",
    "mohnish pabrai": "mohnish_pabrai",
    "pabrai": "mohnish_pabrai",
    "john templeton": "john_templeton",
    "templeton": "john_templeton",
    "ben graham": "ben_graham",
    "benjamin graham": "ben_graham",
    "graham": "ben_graham",
    "george soros": "george_soros",
    "soros": "george_soros",
}

# Longest-first so "warren buffett" matches before "buffett"
_KNOWN_AUTHOR_PATTERNS = sorted(_KNOWN_AUTHORS.keys(), key=len, reverse=True)


# ── Data shape ────────────────────────────────────────────────────────────────


@dataclass
class QueryIntent:
    """Structured intent extracted from a user query."""

    # Ordered list of unique author_ids detected in the query.
    author_ids: list[str] = field(default_factory=list)
    # Raw author names as detected (for display / debugging).
    author_names: list[str] = field(default_factory=list)
    # Normalised source_type values (matching retrieval.py constants).
    source_types: list[str] = field(default_factory=list)
    # Year strings, e.g. "2020", "2015".
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    # Characterises the desired answer format.
    output_shape: Optional[str] = None
    # "single_author" | "multi_author" | "open"
    query_type: str = "open"
    # Non-empty when the query naturally decomposes into focused sub-asks.
    sub_queries: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "author_ids": self.author_ids,
            "author_names": self.author_names,
            "source_types": self.source_types,
            "date_from": self.date_from,
            "date_to": self.date_to,
            "output_shape": self.output_shape,
            "query_type": self.query_type,
            "sub_queries": self.sub_queries,
        }


# ── Text-based (no-LLM) parser ────────────────────────────────────────────────


def _extract_authors(query: str) -> tuple[list[str], list[str]]:
    """Return (author_ids, display_names) found in query, deduped in order."""
    q = query.lower()
    seen_ids: list[str] = []
    seen_names: list[str] = []
    for name in _KNOWN_AUTHOR_PATTERNS:
        if re.search(r"\b" + re.escape(name) + r"\b", q):
            aid = _KNOWN_AUTHORS[name]
            if aid not in seen_ids:
                seen_ids.append(aid)
                seen_names.append(name.title())
    return seen_ids, seen_names


def _extract_source_types(query: str) -> list[str]:
    """Detect source-type constraints from query text."""
    q = query.lower()
    found: list[str] = []
    seen: set[str] = set()
    # Check multi-word phrases first
    for phrase in sorted(_SOURCE_TYPE_MAP.keys(), key=len, reverse=True):
        if phrase in q:
            normalised = _SOURCE_TYPE_MAP[phrase]
            if normalised in _KNOWN_SOURCE_TYPES and normalised not in seen:
                found.append(normalised)
                seen.add(normalised)
    return found


def _extract_dates(query: str) -> tuple[Optional[str], Optional[str]]:
    """Extract (date_from, date_to) year strings from query text."""
    # "2020 to 2025", "2015 through 2020", "between 2010 and 2020"
    m = re.search(
        r"\b((?:19|20)\d{2})\s*(?:to|through|–|-|and)\s*((?:19|20)\d{2})\b",
        query,
        re.IGNORECASE,
    )
    if m:
        return m.group(1), m.group(2)

    # "from 2018", "since 2019", "after 2015"
    m2 = re.search(r"\b(?:from|since|after)\s+((?:19|20)\d{2})\b", query, re.IGNORECASE)
    if m2:
        return m2.group(1), None

    # "before 2020", "until 2021"
    m3 = re.search(r"\b(?:before|until)\s+((?:19|20)\d{2})\b", query, re.IGNORECASE)
    if m3:
        return None, m3.group(1)

    # "in 2020" or "2020 letters" — single year
    m4 = re.search(r"\bin\s+((?:19|20)\d{2})\b", query, re.IGNORECASE)
    if m4:
        yr = m4.group(1)
        return yr, yr

    return None, None


def _extract_output_shape(query: str) -> Optional[str]:
    q = query.lower()
    for shape in _OUTPUT_SHAPES:
        if shape in q:
            return shape
    return None


def _decompose_sub_queries(query: str) -> list[str]:
    """
    Return a list of sub-queries if the original query clearly contains
    multiple distinct asks.  A query is considered multi-part when it has:
    - multiple question marks, or
    - explicit connective "and also" / "as well as"

    Returns [] if the query is a single ask.
    """
    # Multiple question marks
    parts = [p.strip() for p in re.split(r"\?+", query) if p.strip()]
    if len(parts) > 1:
        return [p + "?" for p in parts]

    # "and also" / "as well as"
    split_re = re.compile(
        r"\s+(?:and also|as well as|additionally|furthermore)\s+",
        re.IGNORECASE,
    )
    parts2 = [p.strip() for p in split_re.split(query) if p.strip()]
    if len(parts2) > 1:
        return parts2

    return []


def parse_intent_from_text(query: str) -> QueryIntent:
    """
    Pure-Python intent parser — no LLM required.

    Handles:
    - Explicit author name detection
    - Source-type constraints (letter, PDF, etc.)
    - Date range / single-year constraints
    - Output-shape intent
    - Single vs multi-author vs open classification
    - Basic sub-query decomposition
    """
    author_ids, author_names = _extract_authors(query)
    source_types = _extract_source_types(query)
    date_from, date_to = _extract_dates(query)
    output_shape = _extract_output_shape(query)
    sub_queries = _decompose_sub_queries(query)

    if len(author_ids) == 1:
        query_type = "single_author"
    elif len(author_ids) > 1:
        query_type = "multi_author"
    else:
        query_type = "open"

    return QueryIntent(
        author_ids=author_ids,
        author_names=author_names,
        source_types=source_types,
        date_from=date_from,
        date_to=date_to,
        output_shape=output_shape,
        query_type=query_type,
        sub_queries=sub_queries,
    )


# ── LLM-based parser ──────────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = textwrap.dedent("""
    You are a query-intent parser for a financial knowledge retrieval system.
    Extract structured intent from the user query and return ONLY valid JSON.
    Do not include any explanation or markdown fences.

    JSON schema:
    {
      "author_names": ["string"],        // explicit author names mentioned
      "source_types": ["string"],        // e.g. ["letter", "annual_report", "pdf"]
      "date_from": "YYYY" | null,        // earliest year, or null
      "date_to": "YYYY" | null,          // latest year, or null
      "output_shape": "string" | null,   // e.g. "aphorisms", "life advice", or null
      "query_type": "single_author" | "multi_author" | "open",
      "sub_queries": ["string"]          // decomposed sub-asks, or []
    }

    Rules:
    - query_type is "single_author" when the question is about exactly one explicitly
      named author and comparison with other authors is NOT requested.
    - query_type is "multi_author" when the question explicitly names or compares
      two or more authors.
    - query_type is "open" when no author is explicitly named.
    - Do NOT add authors that are not explicitly mentioned in the query.
    - If uncertain, preserve the user's wording — do not broaden scope.
""").strip()


def _parse_intent_with_llm(query: str) -> Optional[QueryIntent]:
    """
    Call the routing model to extract structured intent.
    Returns None if the call fails or returns unparseable output.
    """
    from app.rag.inference import routing_model, create_routing_client, routing_available

    if not routing_available():
        return None

    try:
        client = create_routing_client()
        model = routing_model()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        raw = (response.choices[0].message.content or "").strip()
        # Strip accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        data: dict[str, Any] = json.loads(raw)
    except Exception as exc:
        log.warning("routing LLM intent parse failed: %s", exc)
        return None

    # Map raw author names → author_ids using the known-author table
    raw_names: list[str] = data.get("author_names") or []
    author_ids: list[str] = []
    author_names: list[str] = []
    for name in raw_names:
        aid = _KNOWN_AUTHORS.get(name.lower())
        if aid and aid not in author_ids:
            author_ids.append(aid)
            author_names.append(name)
        elif name and name not in author_names:
            # Unknown author but keep the name for downstream display
            author_names.append(name)

    # Normalise source types
    raw_sources: list[str] = data.get("source_types") or []
    source_types: list[str] = []
    seen_src: set[str] = set()
    for s in raw_sources:
        normalised = _SOURCE_TYPE_MAP.get(s.lower()) or (s if s in _KNOWN_SOURCE_TYPES else None)
        if normalised and normalised not in seen_src:
            source_types.append(normalised)
            seen_src.add(normalised)

    query_type = data.get("query_type", "open")
    if query_type not in {"single_author", "multi_author", "open"}:
        query_type = "open"

    return QueryIntent(
        author_ids=author_ids,
        author_names=author_names,
        source_types=source_types,
        date_from=data.get("date_from") or None,
        date_to=data.get("date_to") or None,
        output_shape=data.get("output_shape") or None,
        query_type=query_type,
        sub_queries=list(data.get("sub_queries") or []),
    )


# ── Public API ────────────────────────────────────────────────────────────────


def parse_intent(query: str) -> QueryIntent:
    """
    Parse the user query into a structured QueryIntent.

    Attempts the LLM routing model first; falls back to the text parser
    if the model is unavailable or returns an error.
    """
    llm_intent = _parse_intent_with_llm(query)
    if llm_intent is not None:
        return llm_intent
    return parse_intent_from_text(query)
