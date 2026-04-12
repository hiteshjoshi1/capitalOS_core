"""
Company Thesis Mode — AI Sage thesis pressure testing flow.

Takes a company thesis, partial view, or investment concern and returns a
structured pressure-tested response:

  - thesis_question:       the extracted thesis / question
  - pushback_questions:    non-obvious questions that stress-test the thesis
  - missing_information:   blind spots and gaps in the current thesis
  - key_facts:             live-researched facts relevant to the thesis
  - author_views:          distinct per-author corpus-grounded perspectives
  - synthesis:             cross-author synthesis
  - critique:              genuine critical pushback
  - updated_thesis_view:   what got stronger, weaker, unresolved
  - live_sources:          live web/company research sources used
  - follow_up_questions:   new questions surfaced (NOT recursively researched)
  - best_passages:         corpus evidence (inspectable)
  - evidence_sufficient:   bool
  - weak_evidence_note:    Optional[str]

Live research is controlled by WEB_RESEARCH_ENABLED env var (default: 1).
In test mode (RAG_EMBEDDING_MOCK=1) live research is automatically disabled.
"""

from __future__ import annotations

import json
import logging
import os
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.rag.author_selection import SelectedAuthor, select_authors
from app.rag.concept_mode import (
    AuthorView,
    _llm_author_view,
    _template_author_view,
    _template_synthesis,
)
from app.rag.inference import create_inference_client, inference_available, inference_model
from app.rag.query import EvidenceChunk, _author_entries, _enrich_chunks
from app.rag.retrieval import RetrievedChunk, retrieve_similar_chunks

log = logging.getLogger(__name__)

_THESIS_TOP_K_AUTHORS = 5
_THESIS_TOP_K_CHUNKS = 12
_MIN_CHUNKS_FOR_CONFIDENCE = 2
_CHUNKS_PER_AUTHOR_VIEW = 4
_MAX_LIVE_SOURCES = 5

# ── Thesis classification keywords ────────────────────────────────────────────

_THESIS_STRONG_TRIGGERS = [
    "thesis",
    "pressure test",
    "pressure-test",
    "weak point",
    "blind spot",
    "pushback",
    "missing question",
    "what would buffett",
    "what would munger",
    "what would nick sleep",
    "worry about",
    "what are the risks",
    "bull case",
    "bear case",
    "long thesis",
    "short thesis",
    "investment thesis",
    "poke holes",
    "devil's advocate",
    "steelman",
    "challenge my",
    "what am i missing",
    "here is my thesis",
    "my thesis on",
    "my view on",
]

# Context phrases only match when the query STARTS with them,
# because they indicate the user is asserting a view ("I think X")
# rather than asking conceptually ("How should I think about X").
_THESIS_START_PHRASES = [
    "i think",
    "i believe",
    "i'm long",
    "i'm short",
    "i am long",
    "i am short",
]


# ── Data shapes ───────────────────────────────────────────────────────────────


@dataclass
class LiveSource:
    url: str
    title: str
    snippet: str
    source_type: str  # "web" | "filing" | "transcript"

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "source_type": self.source_type,
        }


@dataclass
class UpdatedThesisView:
    stronger: list[str] = field(default_factory=list)
    weaker: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stronger": self.stronger,
            "weaker": self.weaker,
            "unresolved": self.unresolved,
        }


@dataclass
class ThesisQueryResult:
    query: str
    mode: str
    # Concept mode shared fields
    best_passages: list[dict[str, Any]]
    author_views: list[dict[str, Any]]
    synthesis: Optional[str]
    critique: Optional[str]
    suggested_readings: list[dict[str, Any]]
    evidence_sufficient: bool
    weak_evidence_note: Optional[str]
    # Thesis-mode specific fields
    thesis_question: Optional[str]
    pushback_questions: list[str]
    missing_information: list[str]
    key_facts: list[str]
    updated_thesis_view: Optional[dict[str, Any]]
    live_sources: list[dict[str, Any]]
    follow_up_questions: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "mode": self.mode,
            "best_passages": self.best_passages,
            "author_views": self.author_views,
            "synthesis": self.synthesis,
            "critique": self.critique,
            "suggested_readings": self.suggested_readings,
            "evidence_sufficient": self.evidence_sufficient,
            "weak_evidence_note": self.weak_evidence_note,
            "thesis_question": self.thesis_question,
            "pushback_questions": self.pushback_questions,
            "missing_information": self.missing_information,
            "key_facts": self.key_facts,
            "updated_thesis_view": self.updated_thesis_view,
            "live_sources": self.live_sources,
            "follow_up_questions": self.follow_up_questions,
        }


# ── Thesis classification ─────────────────────────────────────────────────────


def classify_query_as_thesis(query: str) -> bool:
    """
    Determine whether a query is a company-thesis pressure-test request.

    Returns True if the query looks like a thesis/company-focused prompt.
    Uses a heuristic approach that is fast and LLM-free.

    Strong triggers match anywhere in the query (unambiguous thesis signals).
    Start phrases only match at the beginning, to avoid false positives like
    "How should I think about network effects?" matching "i think".
    """
    q_lower = query.lower().strip()

    # Strong signals: any of these keywords alone signals thesis mode
    for trigger in _THESIS_STRONG_TRIGGERS:
        if trigger in q_lower:
            return True

    # Start phrases: match only when the query opens with one of these,
    # indicating the user is asserting a view (not asking how to think)
    for phrase in _THESIS_START_PHRASES:
        if q_lower.startswith(phrase):
            return True

    return False


# ── Live research ─────────────────────────────────────────────────────────────


def _live_research_enabled() -> bool:
    """Live research is disabled in test mode (RAG_EMBEDDING_MOCK=1) or explicitly disabled."""
    if os.getenv("RAG_EMBEDDING_MOCK", "0") == "1":
        return False
    return os.getenv("WEB_RESEARCH_ENABLED", "1").strip() != "0"


def fetch_company_research(query: str, max_results: int = _MAX_LIVE_SOURCES) -> list[LiveSource]:
    """
    Fetch live company/web research for a thesis query.

    When WEB_RESEARCH_ENABLED is set and live research is available, returns
    a list of live sources. Returns an empty list on failure or in test mode.

    This function is designed to be mockable in tests.
    """
    if not _live_research_enabled():
        log.debug("Live research disabled; skipping fetch.")
        return []

    try:
        return _ddg_search(query, max_results)
    except Exception as exc:
        log.warning("Live research fetch failed: %s", exc)
        return []


def _ddg_search(query: str, max_results: int) -> list[LiveSource]:
    """
    Perform a DuckDuckGo Instant Answer search for company research.

    Uses DuckDuckGo's /html endpoint to scrape top results.
    Falls back gracefully if httpx is unavailable or search fails.
    """
    try:
        import httpx
    except ImportError:
        log.warning("httpx not available; skipping live research.")
        return []

    # DuckDuckGo HTML search — lightweight and no API key required
    search_url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; CapitalOS-Research/1.0)",
    }
    params = {"q": f"{query} company fundamentals earnings SEC filing", "kl": "us-en"}

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(search_url, data=params, headers=headers, follow_redirects=True)
            if response.status_code != 200:
                return []

            html = response.text
            return _parse_ddg_results(html, max_results)
    except Exception as exc:
        log.warning("DuckDuckGo search error: %s", exc)
        return []


def _parse_ddg_results(html: str, max_results: int) -> list[LiveSource]:
    """Parse DuckDuckGo HTML results into LiveSource objects."""
    sources: list[LiveSource] = []

    # Simple regex-based extraction from DDG HTML
    result_pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([^<]+)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    for match in result_pattern.finditer(html):
        url, title, snippet_raw = match.groups()
        snippet = re.sub(r"<[^>]+>", "", snippet_raw).strip()
        title = title.strip()

        if not url.startswith("http"):
            continue

        # Classify source type
        source_type = "web"
        if "sec.gov" in url or "edgar" in url.lower():
            source_type = "filing"
        elif any(kw in url.lower() for kw in ["transcript", "earnings", "investor"]):
            source_type = "transcript"

        sources.append(
            LiveSource(
                url=url,
                title=title,
                snippet=snippet[:400],
                source_type=source_type,
            )
        )

        if len(sources) >= max_results:
            break

    return sources


# ── LLM helpers ───────────────────────────────────────────────────────────────


def _parse_json_response(raw: str, fallback: dict) -> dict:
    """Parse a JSON response from the LLM, with fallback on failure."""
    text = (raw or "").strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to extract JSON from markdown fence
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass
    # Try to find raw JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            pass
    return fallback


def _llm_thesis_analysis(
    query: str,
    author_views: list[AuthorView],
    evidence_passages: list[str],
    live_source_snippets: list[str],
) -> dict:
    """
    Single LLM call that performs full thesis analysis.

    Returns a structured dict with all thesis-mode fields.
    Batches the full analysis into one call to minimize API latency.
    """
    views_block = "\n\n".join(
        f"{av.author_name}: {av.view}" for av in author_views
    ) or "No author views available."

    corpus_block = "\n\n---\n\n".join(evidence_passages[:6]) or "No corpus evidence available."

    live_block = "\n\n".join(live_source_snippets[:5]) or "No live research available."

    prompt = textwrap.dedent(f"""
        You are a senior investment analyst performing a rigorous thesis pressure test.

        The user's input (thesis, question, or concern):
        {query}

        Author perspectives from the thinker corpus:
        ---
        {views_block}
        ---

        Supporting corpus evidence:
        ---
        {corpus_block}
        ---

        Live research snippets (from web/filings):
        ---
        {live_block}
        ---

        Perform a thorough thesis pressure test. Return a JSON object with exactly these keys:

        {{
          "thesis_question": "A single clear sentence restating the user's core thesis or question.",
          "pushback_questions": [
            "3-5 non-obvious questions that genuinely stress-test the thesis.",
            "Each question should identify a specific assumption or risk the user may not have considered."
          ],
          "missing_information": [
            "2-4 specific pieces of data or analysis the user needs but doesn't have."
          ],
          "key_facts": [
            "3-5 specific facts from the live research or corpus that are most relevant to this thesis."
          ],
          "synthesis": "3-5 sentence synthesis of how the author perspectives relate to this thesis.",
          "critique": "2-4 sentences of genuine critical pushback on the thesis itself.",
          "updated_thesis_view": {{
            "stronger": ["1-3 things that look stronger after this analysis."],
            "weaker": ["1-3 things that look weaker after this analysis."],
            "unresolved": ["1-3 key questions that remain open."]
          }},
          "follow_up_questions": [
            "2-3 new questions the user should explore next (do not answer these now)."
          ]
        }}

        Instructions:
        - Be specific and non-generic. Generic company overviews are not useful.
        - Pushback questions must identify real assumptions in the thesis.
        - If live research is unavailable, acknowledge that in key_facts.
        - The updated_thesis_view must clearly separate what got stronger vs weaker.
        - Do NOT recursively research the follow_up_questions — just surface them.
        - Return ONLY valid JSON. No prose, no markdown fences.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1200,
    )
    raw = response.choices[0].message.content or ""
    return _parse_json_response(raw, _fallback_thesis_analysis(query))


def _fallback_thesis_analysis(query: str) -> dict:
    """Deterministic fallback when LLM is unavailable."""
    return {
        "thesis_question": query,
        "pushback_questions": [
            "What evidence would change your view on this thesis?",
            "What assumptions are you making about the competitive environment?",
            "How does this thesis hold if the macro environment shifts significantly?",
        ],
        "missing_information": [
            "Recent earnings and guidance from management",
            "Competitive position relative to peers",
            "Capital allocation history and return on invested capital",
        ],
        "key_facts": [
            "Live research was not available; key facts should be sourced manually.",
        ],
        "synthesis": (
            "The author corpus provides relevant mental models for evaluating this thesis. "
            "Review each author view above for their distinct framing of the key questions."
        ),
        "critique": (
            "Without live company data, this thesis analysis relies on corpus-grounded principles. "
            "Verify the assumptions above against current filings and earnings transcripts."
        ),
        "updated_thesis_view": {
            "stronger": ["Core thesis assumptions align with known investment principles."],
            "weaker": ["Specific company facts need verification before conviction can increase."],
            "unresolved": ["Key competitive dynamics and management quality remain open questions."],
        },
        "follow_up_questions": [
            "What does the most recent earnings call say about management's capital allocation priorities?",
            "How has the competitive moat changed over the last three years?",
        ],
    }


# ── Core function ─────────────────────────────────────────────────────────────


def execute_thesis_query(
    query: str,
    db: Session,
    *,
    top_k_chunks: int = _THESIS_TOP_K_CHUNKS,
    top_k_authors: int = _THESIS_TOP_K_AUTHORS,
) -> ThesisQueryResult:
    """
    Execute a company-thesis mode query for AI Sage.

    Auto-selects relevant authors, retrieves corpus evidence, optionally fetches
    live company research, then generates a structured pressure-test response.

    The user never needs to specify authors, research modes, or internal controls.
    """
    # 1. Author selection
    selected: list[SelectedAuthor] = select_authors(query, db, top_k=top_k_authors)
    author_entries = _author_entries(selected, db)
    author_map = {e["author_id"]: e["name"] for e in author_entries}

    # 2. Retrieve corpus evidence
    selected_ids = [a.author_id for a in selected]
    raw_chunks: list[RetrievedChunk] = retrieve_similar_chunks(
        query,
        db,
        top_k=top_k_chunks,
        author_ids=selected_ids if selected_ids else None,
    )
    evidence: list[EvidenceChunk] = _enrich_chunks(raw_chunks, db, author_map)

    evidence_sufficient = len(evidence) >= _MIN_CHUNKS_FOR_CONFIDENCE
    weak_evidence_note: Optional[str] = None
    if not evidence:
        weak_evidence_note = (
            "The author corpus does not contain passages strongly relevant to this company thesis. "
            "The analysis below relies on first-principles reasoning from the thinker corpus."
        )
    elif not evidence_sufficient:
        weak_evidence_note = (
            "Corpus evidence for this thesis is thin. "
            "Author perspectives are based on limited passages and should be read cautiously."
        )

    best_passages = [e.as_dict() for e in evidence]

    # 3. Build per-author chunk map
    author_chunk_map: dict[str, list[str]] = {}
    for chunk in evidence:
        author_chunk_map.setdefault(chunk.author_id, []).append(chunk.text)

    # 4. Generate per-author views
    author_views: list[AuthorView] = []
    for entry in author_entries:
        a_id = entry["author_id"]
        a_name = entry["name"]
        passages_for_author = author_chunk_map.get(a_id, [])

        if not passages_for_author and not evidence_sufficient:
            continue

        key_passages = [p[:280] for p in passages_for_author[:2]]
        worldview = entry.get("worldview", "")
        key_maxims = entry.get("key_maxims") or []

        if inference_available() and passages_for_author:
            try:
                view_text = _llm_author_view(
                    query, a_name, worldview or "", key_maxims, passages_for_author
                )
            except Exception as exc:
                log.warning("LLM author view failed for %s: %s", a_id, exc)
                view_text = _template_author_view(a_name, worldview, key_maxims, passages_for_author)
        else:
            view_text = _template_author_view(a_name, worldview, key_maxims, passages_for_author)

        author_views.append(
            AuthorView(
                author_id=a_id,
                author_name=a_name,
                view=view_text,
                key_passages=key_passages,
            )
        )

    # 5. Fetch live company research
    live_sources: list[LiveSource] = fetch_company_research(query)

    # 6. Full thesis analysis (LLM or fallback)
    evidence_passages = [chunk.text for chunk in evidence]
    live_snippets = [s.snippet for s in live_sources]

    synthesis: Optional[str] = None
    thesis_question: Optional[str] = None
    pushback_questions: list[str] = []
    missing_information: list[str] = []
    key_facts: list[str] = []
    updated_thesis_view: Optional[dict[str, Any]] = None
    follow_up_questions: list[str] = []
    critique: Optional[str] = None

    if inference_available():
        try:
            analysis = _llm_thesis_analysis(query, author_views, evidence_passages, live_snippets)
        except Exception as exc:
            log.warning("LLM thesis analysis failed: %s", exc)
            analysis = _fallback_thesis_analysis(query)
    else:
        analysis = _fallback_thesis_analysis(query)

    thesis_question = analysis.get("thesis_question") or query
    pushback_questions = analysis.get("pushback_questions") or []
    missing_information = analysis.get("missing_information") or []
    key_facts = analysis.get("key_facts") or []
    synthesis = analysis.get("synthesis")
    critique = analysis.get("critique")
    follow_up_questions = analysis.get("follow_up_questions") or []

    raw_utv = analysis.get("updated_thesis_view")
    if isinstance(raw_utv, dict):
        updated_thesis_view = UpdatedThesisView(
            stronger=raw_utv.get("stronger") or [],
            weaker=raw_utv.get("weaker") or [],
            unresolved=raw_utv.get("unresolved") or [],
        ).as_dict()

    # 7. Fallback synthesis when LLM is unavailable
    if not synthesis and author_views:
        synthesis = _template_synthesis(author_views)

    # 8. Suggested readings (top corpus passages per author)
    from app.rag.concept_mode import SuggestedReading
    suggested_readings: list[SuggestedReading] = []
    seen_authors: set[str] = set()
    for chunk in evidence:
        if chunk.author_id not in seen_authors:
            seen_authors.add(chunk.author_id)
            suggested_readings.append(
                SuggestedReading(
                    author_id=chunk.author_id,
                    author_name=chunk.author_name,
                    passage=chunk.text[:400],
                    source_url=str(chunk.metadata.get("source_url") or "") or None,
                    reason=f"Top-matched corpus passage from {chunk.author_name} relevant to this thesis.",
                )
            )
        if len(suggested_readings) >= 3:
            break

    return ThesisQueryResult(
        query=query,
        mode="thesis",
        best_passages=best_passages,
        author_views=[av.as_dict() for av in author_views],
        synthesis=synthesis,
        critique=critique,
        suggested_readings=[sr.as_dict() for sr in suggested_readings],
        evidence_sufficient=evidence_sufficient,
        weak_evidence_note=weak_evidence_note,
        thesis_question=thesis_question,
        pushback_questions=pushback_questions,
        missing_information=missing_information,
        key_facts=key_facts,
        updated_thesis_view=updated_thesis_view,
        live_sources=[s.as_dict() for s in live_sources],
        follow_up_questions=follow_up_questions,
    )
