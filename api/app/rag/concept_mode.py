"""
Concept Mode — AI Sage single-query flow.

Takes one natural language concept question and returns a structured response:
  - query
  - best_passages (evidence, inspectable on demand)
  - author_views (distinct per-author perspectives grounded in corpus)
  - synthesis (cross-author synthesis)
  - critique (pushback to prevent false confidence)
  - suggested_readings (best next passages from the corpus)
  - evidence_sufficient
  - weak_evidence_note (honest signal when corpus grounding is thin)

The LLM path produces richer output; the no-LLM fallback is always honest.
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.rag.author_selection import SelectedAuthor, select_authors
from app.rag.inference import (
    create_inference_client,
    create_routing_client,
    inference_available,
    inference_model,
    routing_available,
    routing_model,
)
from app.rag.intent_router import QueryIntent, parse_intent
from app.rag.query import EvidenceChunk, _author_entries, _enrich_chunks
from app.rag.reranker import rerank as _cross_encoder_rerank
from app.rag.reranker import reranker_available
from app.rag.retrieval import (
    RetrievedChunk,
    expand_chunks_with_context,
    reciprocal_rank_fusion,
    retrieve_keyword_chunks,
    retrieve_similar_chunks,
)

log = logging.getLogger(__name__)

_CONCEPT_TOP_K_AUTHORS = 5
_CONCEPT_TOP_K_CHUNKS = 12
_MIN_CHUNKS_FOR_CONFIDENCE = 2
_CHUNKS_PER_AUTHOR_VIEW = 4
_SUGGESTED_READINGS_COUNT = 3
_BROAD_RETRIEVAL_MULTIPLIER = 4
_BROAD_RETRIEVAL_MIN = 24
_BROAD_RETRIEVAL_MAX = 60
_BROAD_RETRIEVAL_MIN_PER_SUB_QUERY = 8
_RERANK_PER_DOCUMENT_CAP = 2
_CONTEXT_EXPANSION_WINDOW = 2
_CONTEXT_EXPANSION_MAX_CHARS = 1800


# ── Data shapes ───────────────────────────────────────────────────────────────


@dataclass
class AuthorView:
    author_id: str
    author_name: str
    view: str
    key_passages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "author_id": self.author_id,
            "author_name": self.author_name,
            "view": self.view,
            "key_passages": self.key_passages,
        }


@dataclass
class SuggestedReading:
    author_id: str
    author_name: str
    passage: str
    source_url: Optional[str]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "author_id": self.author_id,
            "author_name": self.author_name,
            "passage": self.passage,
            "source_url": self.source_url,
            "reason": self.reason,
        }


@dataclass
class ConceptQueryResult:
    query: str
    best_passages: list[dict[str, Any]]
    author_views: list[dict[str, Any]]
    synthesis: Optional[str]
    critique: Optional[str]
    suggested_readings: list[dict[str, Any]]
    evidence_sufficient: bool
    weak_evidence_note: Optional[str]
    intent: Optional[dict[str, Any]] = None
    constraints_relaxed: bool = False
    constraint_relaxation_reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "best_passages": self.best_passages,
            "author_views": self.author_views,
            "synthesis": self.synthesis,
            "critique": self.critique,
            "suggested_readings": self.suggested_readings,
            "evidence_sufficient": self.evidence_sufficient,
            "weak_evidence_note": self.weak_evidence_note,
            "intent": self.intent,
            "constraints_relaxed": self.constraints_relaxed,
            "constraint_relaxation_reason": self.constraint_relaxation_reason,
        }


# ── LLM helpers ───────────────────────────────────────────────────────────────


def _llm_author_view(
    query: str,
    author_name: str,
    author_worldview: str,
    key_maxims: list[str],
    passages: list[str],
) -> str:
    joined = "\n\n---\n\n".join(passages[:_CHUNKS_PER_AUTHOR_VIEW])
    maxims_str = "; ".join(key_maxims[:4]) if key_maxims else "not specified"

    prompt = textwrap.dedent(f"""
        You are writing a short, distinct perspective on a concept question as {author_name} would frame it.

        The user's question: {query}

        {author_name}'s worldview: {author_worldview or "not specified"}
        {author_name}'s key maxims: {maxims_str}

        Relevant passages from {author_name}'s corpus:
        ---
        {joined}
        ---

        Instructions:
        - Write 2-4 sentences expressing how {author_name} specifically would think about this question.
        - Use language and framing that reflects their worldview and corpus — not generic finance.
        - Ground every claim in what the passages support. Do not speculate.
        - If the passages do not support a clear view, say so honestly in 1-2 sentences.
        - Do NOT start with "{author_name} would say..." — just write their perspective directly.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=300,
    )
    return response.choices[0].message.content or ""


def _llm_synthesis(query: str, author_views: list[AuthorView]) -> str:
    views_block = "\n\n".join(
        f"{av.author_name}: {av.view}" for av in author_views
    )

    prompt = textwrap.dedent(f"""
        You are synthesizing multiple thinker perspectives on a concept question.

        Question: {query}

        Author perspectives:
        ---
        {views_block}
        ---

        Instructions:
        - Write a 3-5 sentence synthesis that captures the most important agreements and contrasts.
        - Preserve meaningful distinctions — do not flatten differences into one generic answer.
        - Make clear where these thinkers align and where they diverge.
        - Do not invent views not present in the perspectives above.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=400,
    )
    return response.choices[0].message.content or ""


def _llm_critique(query: str, synthesis: str, author_views: list[AuthorView]) -> str:
    views_block = "\n\n".join(
        f"{av.author_name}: {av.view}" for av in author_views
    )

    prompt = textwrap.dedent(f"""
        You are providing a critique of the following synthesis and author perspectives on a concept question.

        Question: {query}

        Author perspectives:
        ---
        {views_block}
        ---

        Synthesis:
        {synthesis}

        Instructions:
        - Write 2-4 sentences of genuine pushback.
        - Identify what the perspectives collectively miss, overstate, or leave unresolved.
        - Point out where the corpus-grounded views might be limited, biased, or context-dependent.
        - Do not be ritually pessimistic — make the critique substantive and specific.
        - If the synthesis is sound and the perspectives are well-balanced, say so briefly and explain what would stress-test them.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    return response.choices[0].message.content or ""


def _llm_suggested_readings(
    query: str,
    chunks: list[EvidenceChunk],
    count: int = _SUGGESTED_READINGS_COUNT,
) -> str:
    """Ask LLM to pick the best next-step passages from the corpus evidence."""
    if not chunks:
        return ""

    passages_block = "\n\n".join(
        f"[{i+1}] {c.author_name}: {c.text[:300]}"
        for i, c in enumerate(chunks[:10])
    )

    prompt = textwrap.dedent(f"""
        A user asked: {query}

        Below are evidence passages from the author corpus.
        Pick the {count} passages that would best help the user go deeper on this topic.

        Passages:
        ---
        {passages_block}
        ---

        Return ONLY a JSON array of integers (1-based indices) in order of recommendation quality.
        Example: [3, 1, 7]
        No other text.
    """).strip()

    client = create_inference_client()
    response = client.chat.completions.create(
        model=inference_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=50,
    )
    raw = (response.choices[0].message.content or "").strip()

    import json
    import re
    try:
        indices = json.loads(raw)
    except Exception:
        m = re.search(r"\[.*?\]", raw)
        try:
            indices = json.loads(m.group()) if m else []
        except Exception:
            indices = []

    valid = [i - 1 for i in indices if isinstance(i, int) and 1 <= i <= len(chunks)]
    return valid[:count]


# ── Fallback helpers ──────────────────────────────────────────────────────────


def _template_author_view(
    author_name: str,
    worldview: Optional[str],
    key_maxims: list[str],
    passages: list[str],
) -> str:
    parts: list[str] = []
    if worldview:
        parts.append(worldview)
    if key_maxims:
        parts.append("Key principles: " + "; ".join(key_maxims[:3]) + ".")
    if passages:
        snippet = passages[0][:200].replace("\n", " ").strip()
        parts.append(f'From corpus: "{snippet}..."')
    if not parts:
        return f"{author_name}'s corpus was matched but does not yield a strong view on this question."
    return " ".join(parts)


def _template_synthesis(author_views: list[AuthorView]) -> str:
    if not author_views:
        return "No author views could be assembled for synthesis."
    names = ", ".join(av.author_name for av in author_views)
    return (
        f"The perspectives from {names} converge on some principles while diverging on emphasis. "
        "Review each author view above for their distinct framing."
    )


def _retrieve_with_intent_fallback(
    query: str,
    db: Session,
    *,
    top_k: int,
    author_ids: list[str] | None,
    source_type: Optional[str],
    year_from: Optional[str],
    year_to: Optional[str],
) -> tuple[list[RetrievedChunk], bool, Optional[str]]:
    """
    Apply source/date intent as preferences first, not zero-result traps.

    Retrieval tries the most constrained query first, then progressively relaxes
    source/date filters if the corpus does not support them.

    Returns a 3-tuple of:
      - list[RetrievedChunk]: the resulting chunks
      - bool: whether constraints were relaxed
      - Optional[str]: reason for relaxation (None if no relaxation occurred)

    When RAG_RETRIEVAL_MODE=hybrid (the default), each successful dense retrieval
    attempt is augmented with sparse keyword retrieval and combined via RRF.
    This preserves the intent-fallback contract while adding hybrid recall.
    """
    import os as _os

    retrieval_mode = _os.getenv("RAG_RETRIEVAL_MODE", "hybrid")

    # Convert year strings to int for the new retrieval signature
    year_from_int: Optional[int] = int(year_from) if year_from is not None else None
    year_to_int: Optional[int] = int(year_to) if year_to is not None else None

    attempts: list[dict[str, Any]] = []
    seen: set[tuple[Optional[str], Optional[int], Optional[int]]] = set()

    def add_attempt(
        *,
        source_type_attempt: Optional[str],
        year_from_attempt: Optional[int],
        year_to_attempt: Optional[int],
    ) -> None:
        key = (source_type_attempt, year_from_attempt, year_to_attempt)
        if key in seen:
            return
        seen.add(key)
        attempts.append(
            {
                "source_type": source_type_attempt,
                "year_from": year_from_attempt,
                "year_to": year_to_attempt,
            }
        )

    add_attempt(
        source_type_attempt=source_type,
        year_from_attempt=year_from_int,
        year_to_attempt=year_to_int,
    )
    if source_type is not None:
        add_attempt(
            source_type_attempt=None,
            year_from_attempt=year_from_int,
            year_to_attempt=year_to_int,
        )
    if year_from_int is not None or year_to_int is not None:
        add_attempt(
            source_type_attempt=source_type,
            year_from_attempt=None,
            year_to_attempt=None,
        )
    if source_type is not None or year_from_int is not None or year_to_int is not None:
        add_attempt(
            source_type_attempt=None,
            year_from_attempt=None,
            year_to_attempt=None,
        )

    for attempt in attempts:
        chunks = retrieve_similar_chunks(
            query,
            db,
            top_k=top_k,
            author_ids=author_ids if author_ids else None,
            source_type=attempt["source_type"],
            year_from=attempt["year_from"],
            year_to=attempt["year_to"],
        )
        if chunks:
            was_relaxed = attempt != attempts[0]
            relaxation_reason: Optional[str] = None
            if was_relaxed:
                relaxed_source = attempt["source_type"] != source_type
                relaxed_date = attempt["year_from"] != year_from_int or attempt["year_to"] != year_to_int
                parts: list[str] = []
                if relaxed_source:
                    parts.append("source_type filter removed")
                if relaxed_date:
                    parts.append("year range filter removed")
                relaxation_reason = "No results under exact constraints; " + ", ".join(parts) + "."
                log.info(
                    "intent retrieval fallback applied for query=%r source_type=%r year_from=%r year_to=%r",
                    query[:120],
                    attempt["source_type"],
                    attempt["year_from"],
                    attempt["year_to"],
                )
            if retrieval_mode == "hybrid":
                sparse = retrieve_keyword_chunks(
                    query,
                    db,
                    top_k=top_k,
                    author_ids=author_ids if author_ids else None,
                    source_type=attempt["source_type"],
                    year_from=attempt["year_from"],
                    year_to=attempt["year_to"],
                )
                if sparse:
                    chunks = reciprocal_rank_fusion(chunks, sparse)[:top_k]
            return chunks, was_relaxed, relaxation_reason

    return [], False, None


def _dedupe_chunks_by_id(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    deduped: list[RetrievedChunk] = []
    seen_ids: set[str] = set()
    for chunk in chunks:
        if chunk.chunk_id in seen_ids:
            continue
        seen_ids.add(chunk.chunk_id)
        deduped.append(chunk)
    return deduped


def _collect_candidate_chunks(
    query: str,
    db: Session,
    *,
    intent: QueryIntent,
    author_ids: list[str] | None,
    broad_top_k: int,
) -> tuple[list[RetrievedChunk], bool, Optional[str]]:
    """Retrieve a broad, deduplicated candidate pool before reranking.

    Always routes through _retrieve_with_intent_fallback() to preserve
    source/date constraint-relaxation semantics. When RAG_RETRIEVAL_MODE=hybrid
    (the default), each fallback attempt also fetches sparse keyword results and
    combines them via Reciprocal Rank Fusion internally.

    Returns:
      - list[RetrievedChunk]: deduplicated candidate chunks
      - bool: whether any constraints were relaxed
      - Optional[str]: reason for relaxation (None if exact constraints satisfied)
    """
    import os as _os

    source_type_filter = intent.source_types[0] if intent.source_types else None
    candidates: list[RetrievedChunk] = []
    retrieval_mode = _os.getenv("RAG_RETRIEVAL_MODE", "hybrid")
    any_relaxed = False
    relaxation_reason: Optional[str] = None

    if intent.sub_queries:
        per_sub_k = max(
            broad_top_k // len(intent.sub_queries),
            _BROAD_RETRIEVAL_MIN_PER_SUB_QUERY,
        )
        for sub_query in intent.sub_queries:
            sub_chunks, sub_relaxed, sub_reason = _retrieve_with_intent_fallback(
                sub_query,
                db,
                top_k=per_sub_k,
                source_type=source_type_filter,
                year_from=intent.date_from,
                year_to=intent.date_to,
                author_ids=author_ids if author_ids else None,
            )
            candidates.extend(sub_chunks)
            if sub_relaxed:
                any_relaxed = True
                relaxation_reason = sub_reason
    else:
        candidates, any_relaxed, relaxation_reason = _retrieve_with_intent_fallback(
            query,
            db,
            top_k=broad_top_k,
            source_type=source_type_filter,
            year_from=intent.date_from,
            year_to=intent.date_to,
            author_ids=author_ids if author_ids else None,
        )

    deduped = _dedupe_chunks_by_id(candidates)
    if retrieval_mode == "hybrid":
        # Sort by RRF score (descending) when available, else by cosine_distance
        deduped.sort(key=lambda c: -(c.rrf_score or 0.0) if c.rrf_score is not None else c.cosine_distance)
    else:
        deduped.sort(key=lambda c: c.cosine_distance)
    return deduped[:broad_top_k], any_relaxed, relaxation_reason


def _query_keywords(query: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) >= 3}


def _heuristic_rank_candidates(
    query: str,
    candidates: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """
    Fallback ranking when rerank model is unavailable.

    Uses simple lexical overlap over query intent + retrieval similarity.
    """
    keywords = _query_keywords(query)

    def score(chunk: RetrievedChunk) -> tuple[int, float]:
        text = str(getattr(chunk, "text", "") or "").lower()
        overlap = sum(1 for kw in keywords if kw in text)
        similarity = getattr(chunk, "similarity", None)
        if not isinstance(similarity, (int, float)):
            cosine_distance = getattr(chunk, "cosine_distance", 1.0)
            similarity = 1.0 - float(cosine_distance if isinstance(cosine_distance, (int, float)) else 1.0)
        return overlap, float(similarity)

    ranked = sorted(
        candidates,
        key=lambda c: (-score(c)[0], -score(c)[1], c.cosine_distance),
    )
    return ranked


def _chunk_meta(chunk: RetrievedChunk) -> dict[str, Any]:
    metadata = getattr(chunk, "metadata_json", None)
    return metadata if isinstance(metadata, dict) else {}


def _llm_rerank_candidate_indices(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    keep_count: int,
) -> list[int]:
    """Use the cheap routing model to rerank candidate evidence by full-query intent."""
    if not candidates or keep_count <= 0:
        return []

    candidate_block = "\n\n".join(
        (
            f"[{i+1}] author={_chunk_meta(c).get('author_name') or _chunk_meta(c).get('author_id') or 'unknown'} "
            f"document={getattr(c, 'document_id', '')} idx={getattr(c, 'chunk_index', -1)}\n"
            f"{str(getattr(c, 'text', '') or '')[:420]}"
        )
        for i, c in enumerate(candidates)
    )
    prompt = textwrap.dedent(f"""
        Task: rerank evidence passages for semantic relevance to the full user query.

        User query:
        {query}

        Candidate passages:
        ---
        {candidate_block}
        ---

        Instructions:
        - Pick the {keep_count} most relevant passages for answering the full query intent.
        - Favor semantic relevance over keyword matching.
        - Prefer diversity when many passages repeat the same motif.
        - Return ONLY a JSON array of 1-based indices.
        Example: [4, 2, 10]
    """).strip()

    client = create_routing_client()
    response = client.chat.completions.create(
        model=routing_model(),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=180,
    )
    raw = (response.choices[0].message.content or "").strip()

    try:
        parsed = json.loads(raw)
    except Exception:
        m = re.search(r"\[.*?\]", raw, re.DOTALL)
        parsed = json.loads(m.group()) if m else []

    if not isinstance(parsed, list):
        return []
    valid = [i - 1 for i in parsed if isinstance(i, int) and 1 <= i <= len(candidates)]
    return valid[:keep_count]


def _select_diverse_top_chunks(
    ranked_chunks: list[RetrievedChunk],
    *,
    top_k: int,
    per_document_cap: int = _RERANK_PER_DOCUMENT_CAP,
) -> list[RetrievedChunk]:
    """Prevent one document/chunk-family from dominating the final evidence pack."""
    if top_k <= 0:
        return []

    selected: list[RetrievedChunk] = []
    overflow: list[RetrievedChunk] = []
    by_document: dict[str, int] = {}

    for chunk in ranked_chunks:
        document_id = str(getattr(chunk, "document_id", ""))
        count = by_document.get(document_id, 0)
        if count < per_document_cap:
            selected.append(chunk)
            by_document[document_id] = count + 1
            if len(selected) >= top_k:
                return selected
        else:
            overflow.append(chunk)

    for chunk in overflow:
        if len(selected) >= top_k:
            break
        selected.append(chunk)
    return selected[:top_k]


def _rerank_candidate_chunks(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    top_k: int,
) -> list[RetrievedChunk]:
    if not candidates:
        return []
    if top_k <= 0:
        return []

    heuristic_ranked = _heuristic_rank_candidates(query, candidates)
    ranked = heuristic_ranked

    # Tier 1: dedicated cross-encoder reranker (preferred — fast, deterministic, no JSON)
    if reranker_available():
        try:
            passages = [str(getattr(c, "text", "") or "") for c in candidates]
            results = _cross_encoder_rerank(query, passages, top_k=len(candidates))
            if results:
                ce_ranked: list[RetrievedChunk] = []
                seen_ids: set[str] = set()
                for r in results:
                    chunk = candidates[r.index]
                    if chunk.chunk_id not in seen_ids:
                        seen_ids.add(chunk.chunk_id)
                        ce_ranked.append(chunk)
                for chunk in heuristic_ranked:
                    if chunk.chunk_id not in seen_ids:
                        ce_ranked.append(chunk)
                ranked = ce_ranked
                log.debug("cross-encoder reranked %d candidates", len(candidates))
        except Exception as exc:
            log.warning("cross-encoder reranking failed; falling back: %s", exc)

    # Tier 2: deprecated LLM-prompt reranking (kept as fallback when no cross-encoder)
    elif routing_available():
        try:
            indices = _llm_rerank_candidate_indices(query, candidates, keep_count=min(top_k, len(candidates)))
            if indices:
                llm_ranked: list[RetrievedChunk] = []
                seen_ids_llm: set[str] = set()
                for idx in indices:
                    chunk = candidates[idx]
                    if chunk.chunk_id not in seen_ids_llm:
                        seen_ids_llm.add(chunk.chunk_id)
                        llm_ranked.append(chunk)
                for chunk in heuristic_ranked:
                    if chunk.chunk_id not in seen_ids_llm:
                        llm_ranked.append(chunk)
                ranked = llm_ranked
        except Exception as exc:
            log.warning("LLM candidate reranking failed; using heuristic rank: %s", exc)

    # Tier 3: heuristic (keyword overlap + cosine similarity) — already set as default above

    return _select_diverse_top_chunks(ranked, top_k=min(top_k, len(candidates)))


# ── Core function ─────────────────────────────────────────────────────────────


def execute_concept_query(
    query: str,
    db: Session,
    *,
    top_k_chunks: int = _CONCEPT_TOP_K_CHUNKS,
    top_k_authors: int = _CONCEPT_TOP_K_AUTHORS,
) -> ConceptQueryResult:
    """
    Execute a concept-mode query for AI Sage.

    Runs a pre-retrieval intent-routing step to detect author/source/date
    constraints before selecting authors and retrieving passages.  This
    prevents author drift for single-author questions and narrows retrieval
    when the user specifies source types or date ranges.

    Degrades gracefully when the corpus is thin or LLM is unavailable.
    """
    _t0 = time.monotonic()
    # 0. Parse intent — lightweight, uses cheap routing model or text parser
    intent: QueryIntent = parse_intent(query)
    log.debug(
        "intent: query_type=%s authors=%s sources=%s dates=%s/%s sub_queries=%d",
        intent.query_type,
        intent.author_ids,
        intent.source_types,
        intent.date_from,
        intent.date_to,
        len(intent.sub_queries),
    )

    # 1. Author selection — constrained by intent
    if intent.query_type == "single_author" and intent.author_ids:
        # Pin to the single detected author; ignore top_k_authors
        selected: list[SelectedAuthor] = select_authors(
            query,
            db,
            author_id=intent.author_ids[0],
            top_k=1,
        )
        if not selected:
            # Author not in DB — fall back to scored open selection
            log.debug(
                "single_author %s not found in DB, falling back to open selection",
                intent.author_ids[0],
            )
            selected = select_authors(query, db, top_k=top_k_authors)
    else:
        selected = select_authors(
            query, db, top_k=top_k_authors
        )

    author_entries = _author_entries(selected, db)
    author_map = {e["author_id"]: e["name"] for e in author_entries}

    # 2. Retrieve broad candidate evidence before reranking/context expansion
    selected_ids = [a.author_id for a in selected]
    broad_top_k = min(
        _BROAD_RETRIEVAL_MAX,
        max(top_k_chunks * _BROAD_RETRIEVAL_MULTIPLIER, _BROAD_RETRIEVAL_MIN),
    )
    candidate_chunks = _collect_candidate_chunks(
        query,
        db,
        intent=intent,
        author_ids=selected_ids,
        broad_top_k=broad_top_k,
    )
    # Unpack the tuple returned by _collect_candidate_chunks
    if isinstance(candidate_chunks, tuple):
        candidate_chunks, _constraints_relaxed, _relaxation_reason = candidate_chunks
    else:
        _constraints_relaxed, _relaxation_reason = False, None
    winning_chunks = _rerank_candidate_chunks(
        query,
        candidate_chunks,
        top_k=min(top_k_chunks, len(candidate_chunks)),
    )
    expanded_chunks = expand_chunks_with_context(
        winning_chunks,
        db,
        window_size=_CONTEXT_EXPANSION_WINDOW,
        max_chars=_CONTEXT_EXPANSION_MAX_CHARS,
    )
    evidence: list[EvidenceChunk] = _enrich_chunks(expanded_chunks, db, author_map)

    log.debug(
        "concept evidence pipeline sizes: candidates=%d winners=%d expanded=%d",
        len(candidate_chunks),
        len(winning_chunks),
        len(expanded_chunks),
    )

    evidence_sufficient = len(evidence) >= _MIN_CHUNKS_FOR_CONFIDENCE
    weak_evidence_note: Optional[str] = None
    if not evidence:
        weak_evidence_note = (
            "The author corpus does not contain passages strongly relevant to this question. "
            "The answer below is limited and may not reflect the authors' views accurately."
        )
    elif not evidence_sufficient:
        weak_evidence_note = (
            "Evidence from the corpus is thin for this question. "
            "The author views below are based on limited passages and should be read cautiously."
        )

    best_passages = [e.as_dict() for e in evidence]

    # 3. Build per-author chunk map
    author_chunk_map: dict[str, list[str]] = {}
    for chunk in evidence:
        author_chunk_map.setdefault(chunk.author_id, []).append(chunk.text)

    # 4. Generate author views
    author_views: list[AuthorView] = []
    for entry in author_entries:
        a_id = entry["author_id"]
        a_name = entry["name"]
        passages_for_author = author_chunk_map.get(a_id, [])

        # Skip authors with zero corpus grounding
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

    # 5. Synthesis
    synthesis: Optional[str] = None
    if author_views:
        if inference_available():
            try:
                synthesis = _llm_synthesis(query, author_views)
            except Exception as exc:
                log.warning("LLM synthesis failed: %s", exc)
                synthesis = _template_synthesis(author_views)
        else:
            synthesis = _template_synthesis(author_views)

    # 6. Critique
    critique: Optional[str] = None
    if synthesis and author_views and inference_available():
        try:
            critique = _llm_critique(query, synthesis, author_views)
        except Exception as exc:
            log.warning("LLM critique failed: %s", exc)

    # 7. Suggested readings
    suggested_readings: list[SuggestedReading] = []
    if evidence:
        if inference_available() and len(evidence) > _SUGGESTED_READINGS_COUNT:
            try:
                indices = _llm_suggested_readings(query, evidence, _SUGGESTED_READINGS_COUNT)
                for idx in indices:
                    chunk = evidence[idx]
                    reason = f"Strong corpus passage from {chunk.author_name} relevant to '{query[:60]}'"
                    suggested_readings.append(
                        SuggestedReading(
                            author_id=chunk.author_id,
                            author_name=chunk.author_name,
                            passage=chunk.text[:400],
                            source_url=str(chunk.metadata.get("source_url") or "") or None,
                            reason=reason,
                        )
                    )
            except Exception as exc:
                log.warning("LLM suggested readings failed: %s", exc)

        if not suggested_readings:
            # Fallback: top distinct-author chunks
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
                            reason=f"Top-matched passage from {chunk.author_name} for this concept.",
                        )
                    )
                if len(suggested_readings) >= _SUGGESTED_READINGS_COUNT:
                    break

    result = ConceptQueryResult(
        query=query,
        best_passages=best_passages,
        author_views=[av.as_dict() for av in author_views],
        synthesis=synthesis,
        critique=critique,
        suggested_readings=[sr.as_dict() for sr in suggested_readings],
        evidence_sufficient=evidence_sufficient,
        weak_evidence_note=weak_evidence_note,
        intent=intent.as_dict(),
        constraints_relaxed=_constraints_relaxed,
        constraint_relaxation_reason=_relaxation_reason,
    )
    try:
        from app.rag.query_logger import log_query

        evidence_dicts = [
            {"chunk_id": e.get("chunk_id", ""), "cosine_distance": 1.0 - e.get("similarity", 0.0)}
            for e in best_passages
        ]
        log_query(
            db,
            query,
            "concept",
            intent=intent.as_dict(),
            evidence_chunks=evidence_dicts,
            answer_text=synthesis,
            latency_ms=int((time.monotonic() - _t0) * 1000),
            retrieval_config={"top_k_chunks": top_k_chunks, "top_k_authors": top_k_authors},
        )
    except Exception as _exc:
        log.debug("concept audit log skipped: %s", _exc)
    return result
