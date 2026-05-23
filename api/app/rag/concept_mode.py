"""
Concept Mode — AI Sage single-query flow.

Takes one natural language concept question and returns a structured response:
  - query
  - best_passages (evidence, inspectable on demand)
  - critique (optional pushback)
  - evidence_sufficient
  - weak_evidence_note (honest signal when corpus grounding is thin)
"""

from __future__ import annotations

import json
import logging
import re
import textwrap
import time
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.rag.author_selection import SelectedAuthor, select_authors
from app.rag.inference import (
    create_inference_client,
    create_routing_client,
    inference_available,
    inference_model,
    logged_chat_completion,
    routing_available,
    routing_model,
)
from app.rag.intent_router import QueryIntent, parse_intent
from app.rag.query import EvidenceChunk, _author_entries, _enrich_chunks
from app.rag.reranker import rerank as _cross_encoder_rerank
from app.rag.reranker import reranker_available, reranker_input_mode, reranker_provider_name
from app.rag.retrieval import (
    RetrievedChunk,
    build_retrieval_query_plan,
    deliver_parent_sections,
    expand_chunks_with_context,
    reciprocal_rank_fusion,
    retrieval_hardening_enabled,
    retrieve_keyword_chunks,
    retrieve_similar_chunks,
    suppress_near_duplicates,
    trace_retrieval_chunks,
    trace_retrieval_payload,
)
from app.rag.retrieval_weighting import (
    apply_weight_to_score,
    metadata_weighting_enabled,
    ranking_sort_key,
)

log = logging.getLogger(__name__)


def _env_flag_enabled(name: str, *, default: bool = False) -> bool:
    import os

    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default

def _critique_enabled() -> bool:
    """Check AI_SAGE_CRITIQUE_ENABLED env toggle. Defaults to disabled."""
    return _env_flag_enabled("AI_SAGE_CRITIQUE_ENABLED", default=False)


def _trace_chunks(stage: str, query: str, chunks: list[RetrievedChunk], *, limit: int = 8) -> None:
    trace_retrieval_chunks(f"ai_sage_{stage}", query, chunks, limit=limit)


def _with_display_context(
    anchor_chunks: list[RetrievedChunk],
    expanded_chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    expanded_by_id = {chunk.chunk_id: chunk for chunk in expanded_chunks}
    display_chunks: list[RetrievedChunk] = []

    for chunk in anchor_chunks:
        expanded = expanded_by_id.get(chunk.chunk_id)
        metadata = dict(chunk.metadata_json or {})
        metadata["document_id"] = chunk.document_id
        metadata["score_type"] = "reranked" if chunk.reranker_score is not None else "retrieved"
        if chunk.base_score is not None:
            metadata["base_score"] = chunk.base_score
        if chunk.weighted_score is not None:
            metadata["ranking_score"] = chunk.weighted_score
        elif chunk.base_score is not None:
            metadata["ranking_score"] = chunk.base_score
        metadata["anchor_text"] = chunk.text
        metadata["expanded_context_applied"] = False
        if chunk.reranker_score is not None:
            metadata["reranker_score"] = chunk.reranker_score
        if chunk.rrf_score is not None:
            metadata["rrf_score"] = chunk.rrf_score
        if chunk.ts_rank is not None:
            metadata["ts_rank"] = chunk.ts_rank
        if expanded and expanded.text != chunk.text:
            expanded_meta = expanded.metadata_json or {}
            metadata["context_text"] = expanded.text
            metadata["expanded_context_applied"] = True
            metadata["context_chunk_indices"] = expanded_meta.get("context_chunk_indices")
            metadata["anchor_chunk_index"] = expanded_meta.get("anchor_chunk_index", chunk.chunk_index)
            metadata["context_window"] = expanded_meta.get("context_window")
        display_chunks.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                metadata_json=metadata,
                cosine_distance=chunk.cosine_distance,
                ts_rank=chunk.ts_rank,
                rrf_score=chunk.rrf_score,
                reranker_score=chunk.reranker_score,
            )
        )
    return display_chunks


def _clean_query_for_keyword_search(
    query: str,
    *,
    author_ids: list[str] | None = None,
    topic_entities: list[str] | None = None,
    year_from: Optional[str] = None,
    year_to: Optional[str] = None,
) -> str:
    """Strip author names & year numbers from query for keyword search.

    These are already handled as SQL WHERE filters.  Leaving them in the
    tsquery causes AND-conjunction mismatches (e.g. a chunk about Munger
    authored by Buffett won't match ``'buffett' & 'munger'`` if the chunk
    text only contains "Munger").

    Instead, extract the *semantic core* of the question and append any
    topic_entities so keyword search is focused on the subject matter.
    """
    source_author_names: list[str] = []
    if author_ids:
        try:
            from app.rag.intent_router import _KNOWN_AUTHORS

            source_author_names = [
                name.title()
                for name, aid in _KNOWN_AUTHORS.items()
                if aid in set(author_ids)
            ]
        except Exception:
            source_author_names = []
    q = query
    # Remove year numbers that are used as date filters before planner cleanup.
    for yr in [year_from, year_to]:
        if yr:
            q = re.sub(r"\b" + re.escape(str(yr)) + r"\b", " ", q)
    plan = build_retrieval_query_plan(
        q,
        source_author_ids=author_ids,
        source_author_names=source_author_names,
        topic_entities=topic_entities,
    )
    return plan.content_query or query  # fall back to original if nothing left

_CONCEPT_TOP_K_AUTHORS = 5
_CONCEPT_TOP_K_CHUNKS = 12
_MIN_CHUNKS_FOR_CONFIDENCE = 2
_SINGLE_AUTHOR_SUMMARY_CHUNKS = 10
_BROAD_RETRIEVAL_MULTIPLIER = 4
_BROAD_RETRIEVAL_MIN = 24
_BROAD_RETRIEVAL_MAX = 60
_BROAD_RETRIEVAL_MIN_PER_SUB_QUERY = 8
_RERANK_PER_DOCUMENT_CAP = 2
_CONTEXT_EXPANSION_WINDOW = 2
_CONTEXT_EXPANSION_MAX_CHARS = 1800
_RERANKER_COMPACT_CONTEXT_MAX_CHARS = 900
_RERANKER_BLEND_ALPHA = 0.45


# ── Data shapes ───────────────────────────────────────────────────────────────


@dataclass
class ConceptQueryResult:
    query: str
    best_passages: list[dict[str, Any]]
    critique: Optional[str]
    evidence_sufficient: bool
    weak_evidence_note: Optional[str]
    intent: Optional[dict[str, Any]] = None
    constraints_relaxed: bool = False
    constraint_relaxation_reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "best_passages": self.best_passages,
            "critique": self.critique,
            "evidence_sufficient": self.evidence_sufficient,
            "weak_evidence_note": self.weak_evidence_note,
            "intent": self.intent,
            "constraints_relaxed": self.constraints_relaxed,
            "constraint_relaxation_reason": self.constraint_relaxation_reason,
        }


def _llm_critique(query: str, passages: list[str]) -> str:
    passages_block = "\n\n---\n\n".join(passages[:_SINGLE_AUTHOR_SUMMARY_CHUNKS]) or "No corpus evidence available."
    prompt = textwrap.dedent(f"""
        You are providing a critique of the following corpus-grounded answer context.

        Question: {query}

        Corpus passages:
        ---
        {passages_block}
        ---

        Instructions:
        - Write 2-4 sentences of genuine pushback.
        - Identify what the retrieved evidence may miss, overstate, or leave unresolved.
        - Point out where the corpus grounding might be limited, biased, or context-dependent.
        - Do not be ritually pessimistic — make the critique substantive and specific.
        - If the evidence is balanced, say so briefly and explain what would still stress-test it.
    """).strip()

    client = create_inference_client()
    response = logged_chat_completion(
        client=client,
        model=inference_model(),
        purpose="concept_critique",
        logger=log,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=300,
    )
    return response.choices[0].message.content or ""


# ── Fallback helpers ──────────────────────────────────────────────────────────


def _retrieve_with_intent_fallback(
    query: str,
    db: Session,
    *,
    top_k: int,
    author_ids: list[str] | None,
    source_type: Optional[str],
    year_from: Optional[str],
    year_to: Optional[str],
    strict: bool = False,
    keyword_query: Optional[str] = None,
) -> tuple[list[RetrievedChunk], bool, Optional[str]]:
    """
    Apply source/date intent as preferences first, not zero-result traps.

    When ``strict=True``, runs the query once with full constraints and
    returns whatever comes back (even if empty).  No silent relaxation.

    When ``strict=False`` (default), retrieval tries the most constrained
    query first, then progressively relaxes source/date filters if the
    corpus does not support them.

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
    hardening_active = retrieval_hardening_enabled()

    # Convert year strings to int for the new retrieval signature
    year_from_int: Optional[int] = int(year_from) if year_from is not None else None
    year_to_int: Optional[int] = int(year_to) if year_to is not None else None

    # Use cleaned keyword query for sparse search to avoid AND-conjunction mismatches
    kw_q = keyword_query or query
    dense_q = kw_q if hardening_active else query

    if strict:
        # Strict mode: execute once with full constraints, no fallback
        chunks = retrieve_similar_chunks(
            dense_q,
            db,
            top_k=top_k,
            author_ids=author_ids if author_ids else None,
            source_type=source_type,
            year_from=year_from_int,
            year_to=year_to_int,
        )
        if retrieval_mode == "hybrid":
            sparse = retrieve_keyword_chunks(
                kw_q,
                db,
                top_k=top_k,
                author_ids=author_ids if author_ids else None,
                source_type=source_type,
                year_from=year_from_int,
                year_to=year_to_int,
                hardening_enabled=hardening_active,
            )
            if sparse:
                chunks = reciprocal_rank_fusion(chunks, sparse)[:top_k]
        return chunks, False, None

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
            dense_q,
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
                    kw_q,
                    db,
                    top_k=top_k,
                    author_ids=author_ids if author_ids else None,
                    source_type=attempt["source_type"],
                    year_from=attempt["year_from"],
                    year_to=attempt["year_to"],
                    hardening_enabled=hardening_active,
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

    When the intent carries explicit date or source constraints, retrieval
    runs in strict mode (no silent relaxation).  Otherwise, progressive
    fallback is used so that thin metadata doesn't cause zero-result traps.

    Returns:
      - list[RetrievedChunk]: deduplicated candidate chunks
      - bool: whether any constraints were relaxed
      - Optional[str]: reason for relaxation (None if exact constraints satisfied)
    """
    import os as _os

    # source_type is intentionally NOT used as a retrieval filter (issue-146).
    # Users saying "in letters" want the best results with source highlighted,
    # not a reduced candidate set. Source filtering can be added as a future
    # explicit re-query feature.
    candidates: list[RetrievedChunk] = []
    retrieval_mode = _os.getenv("RAG_RETRIEVAL_MODE", "hybrid")
    any_relaxed = False
    relaxation_reason: Optional[str] = None

    # Use strict mode when the user gave explicit date constraints
    has_explicit_constraints = bool(intent.date_from or intent.date_to)

    # Build cleaned keyword query: strip author names and years already used as filters
    kw_query = _clean_query_for_keyword_search(
        query,
        author_ids=author_ids,
        topic_entities=intent.topic_entities if intent.topic_entities else None,
        year_from=intent.date_from,
        year_to=intent.date_to,
    )
    retrieval_plan = build_retrieval_query_plan(
        query,
        source_author_ids=author_ids,
        source_author_names=intent.author_names,
        topic_entities=intent.topic_entities if intent.topic_entities else None,
    )
    trace_retrieval_payload(
        "ai_sage_retrieval_query_plan",
        {
            **retrieval_plan.as_dict(),
            "keyword_query_used": kw_query,
            "author_ids_filter": author_ids,
            "broad_top_k": broad_top_k,
            "has_explicit_constraints": has_explicit_constraints,
        },
    )

    if intent.sub_queries:
        per_sub_k = max(
            broad_top_k // len(intent.sub_queries),
            _BROAD_RETRIEVAL_MIN_PER_SUB_QUERY,
        )
        trace_retrieval_payload(
            "ai_sage_sub_query_plan",
            {
                "query": query,
                "sub_queries": intent.sub_queries,
                "per_sub_k": per_sub_k,
            },
        )
        for sub_query in intent.sub_queries:
            sub_kw = _clean_query_for_keyword_search(
                sub_query,
                author_ids=author_ids,
                topic_entities=intent.topic_entities if intent.topic_entities else None,
                year_from=intent.date_from,
                year_to=intent.date_to,
            )
            sub_chunks, sub_relaxed, sub_reason = _retrieve_with_intent_fallback(
                sub_query,
                db,
                top_k=per_sub_k,
                source_type=None,
                year_from=intent.date_from,
                year_to=intent.date_to,
                author_ids=author_ids if author_ids else None,
                strict=has_explicit_constraints,
                keyword_query=sub_kw,
            )
            candidates.extend(sub_chunks)
            trace_retrieval_chunks(
                "ai_sage_sub_query_candidates",
                sub_query,
                sub_chunks,
                extra={"keyword_query": sub_kw, "constraints_relaxed": sub_relaxed, "relaxation_reason": sub_reason},
            )
            if sub_relaxed:
                any_relaxed = True
                relaxation_reason = sub_reason
    else:
        candidates, any_relaxed, relaxation_reason = _retrieve_with_intent_fallback(
            query,
            db,
            top_k=broad_top_k,
            source_type=None,
            year_from=intent.date_from,
            year_to=intent.date_to,
            author_ids=author_ids if author_ids else None,
            strict=has_explicit_constraints,
            keyword_query=kw_query,
        )
        trace_retrieval_chunks(
            "ai_sage_initial_candidate_pool",
            query,
            candidates,
            extra={
                "keyword_query": kw_query,
                "constraints_relaxed": any_relaxed,
                "relaxation_reason": relaxation_reason,
            },
        )

    topic_focus_query = _topic_focus_query(intent.topic_entities)
    if topic_focus_query and topic_focus_query.lower() not in {query.lower(), kw_query.lower()}:
        topic_chunks, topic_relaxed, topic_reason = _retrieve_with_intent_fallback(
            topic_focus_query,
            db,
            top_k=max(_BROAD_RETRIEVAL_MIN_PER_SUB_QUERY, broad_top_k // 2),
            source_type=None,
            year_from=intent.date_from,
            year_to=intent.date_to,
            author_ids=author_ids if author_ids else None,
            strict=has_explicit_constraints,
            keyword_query=topic_focus_query,
        )
        candidates.extend(topic_chunks)
        trace_retrieval_chunks(
            "ai_sage_topic_focus_candidates",
            topic_focus_query,
            topic_chunks,
            extra={"constraints_relaxed": topic_relaxed, "relaxation_reason": topic_reason},
        )
        if topic_relaxed:
            any_relaxed = True
            relaxation_reason = topic_reason

    if not candidates and author_ids and not _query_mentions_author_alias(query, intent.author_ids):
        open_chunks, _open_relaxed, _open_reason = _retrieve_with_intent_fallback(
            query,
            db,
            top_k=broad_top_k,
            source_type=None,
            year_from=intent.date_from,
            year_to=intent.date_to,
            author_ids=None,
            strict=has_explicit_constraints,
            keyword_query=kw_query,
        )
        candidates.extend(open_chunks)
        if open_chunks:
            any_relaxed = True
            relaxation_reason = "No results under selected-author candidates; selected author filter removed."
        trace_retrieval_chunks(
            "ai_sage_open_corpus_fallback_candidates",
            query,
            open_chunks,
            extra={
                "keyword_query": kw_query,
                "removed_author_ids_filter": author_ids,
                "constraints_relaxed": bool(open_chunks),
                "relaxation_reason": relaxation_reason,
            },
        )

    deduped = _dedupe_chunks_by_id(candidates)
    if intent.topic_entities:
        deduped.sort(key=lambda chunk: _topic_candidate_pool_sort_key(chunk, topic_entities=intent.topic_entities))
    elif retrieval_mode == "hybrid":
        # Sort by RRF score (descending) when available, else by cosine_distance
        deduped.sort(key=lambda c: -(c.rrf_score or 0.0) if c.rrf_score is not None else c.cosine_distance)
    else:
        deduped.sort(key=lambda c: c.cosine_distance)
    final_candidates = deduped[:broad_top_k]
    trace_retrieval_chunks(
        "ai_sage_deduped_candidate_pool",
        query,
        final_candidates,
        extra={
            "raw_candidate_count": len(candidates),
            "deduped_count": len(deduped),
            "returned_count": len(final_candidates),
            "constraints_relaxed": any_relaxed,
            "relaxation_reason": relaxation_reason,
        },
    )
    return final_candidates, any_relaxed, relaxation_reason


def _query_mentions_author_alias(query: str, author_ids: list[str] | None) -> bool:
    if not author_ids:
        return False
    try:
        from app.rag.intent_router import _KNOWN_AUTHORS
    except Exception:
        return False

    author_id_set = set(author_ids)
    lowered = query.lower()
    for alias, author_id in _KNOWN_AUTHORS.items():
        if author_id not in author_id_set:
            continue
        if re.search(r"\b" + re.escape(alias.lower()) + r"\b", lowered):
            return True
    return False


_HEURISTIC_STOPWORDS = {
    "about",
    "does",
    "from",
    "have",
    "into",
    "just",
    "more",
    "over",
    "said",
    "says",
    "say",
    "than",
    "that",
    "them",
    "they",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}


def _source_author_terms(intent: QueryIntent) -> set[str]:
    if intent.query_type != "single_author":
        return set()
    terms: set[str] = set()
    for author_name in intent.author_names:
        for token in re.findall(r"[a-z0-9]+", str(author_name).lower()):
            if len(token) >= 3:
                terms.add(token)
    for author_id in intent.author_ids:
        for token in re.findall(r"[a-z0-9]+", str(author_id).replace("_", " ").lower()):
            if len(token) >= 3:
                terms.add(token)
    return terms


def _topic_focus_query(topic_entities: list[str] | None) -> str:
    parts = [str(entity).strip() for entity in (topic_entities or []) if isinstance(entity, str) and entity.strip()]
    return " ".join(parts).strip()


def _topic_entity_match_counts(text: str, *, topic_entities: list[str] | None = None) -> tuple[int, int]:
    normalized_text = str(text or "").lower()
    phrases = [
        phrase.strip().lower()
        for phrase in (topic_entities or [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    phrase_hits = sum(1 for phrase in phrases if phrase in normalized_text)
    tokens = {
        token
        for phrase in phrases
        for token in re.findall(r"[a-z0-9]+", phrase)
        if len(token) >= 2
    }
    token_hits = sum(1 for token in tokens if token in normalized_text)
    return phrase_hits, token_hits


def _topic_candidate_pool_sort_key(chunk: RetrievedChunk, *, topic_entities: list[str] | None = None) -> tuple[int, int, float]:
    phrase_hits, token_hits = _topic_entity_match_counts(getattr(chunk, "text", ""), topic_entities=topic_entities)
    if chunk.rrf_score is not None:
        retrieval_score = float(chunk.rrf_score)
    else:
        retrieval_score = 1.0 - float(getattr(chunk, "cosine_distance", 1.0) or 1.0)
    return (-phrase_hits, -token_hits, -retrieval_score)


def _query_keywords(
    query: str,
    *,
    topic_entities: list[str] | None = None,
    ignored_terms: set[str] | None = None,
) -> set[str]:
    ignored = {token for token in (ignored_terms or set()) if token}
    keywords = {
        w
        for w in re.findall(r"[a-z0-9]+", query.lower())
        if len(w) >= 3 and w not in _HEURISTIC_STOPWORDS and w not in ignored
    }
    for entity in topic_entities or []:
        for token in re.findall(r"[a-z0-9]+", str(entity).lower()):
            if len(token) >= 2 and token not in ignored:
                keywords.add(token)
    return keywords


def _expanded_chunks_for_selection(
    selected_chunks: list[RetrievedChunk],
    expanded_by_chunk_id: dict[str, RetrievedChunk],
) -> list[RetrievedChunk]:
    return [expanded_by_chunk_id.get(chunk.chunk_id, chunk) for chunk in selected_chunks]


def _heuristic_rank_candidates(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    topic_entities: list[str] | None = None,
    source_author_terms: set[str] | None = None,
    expanded_by_chunk_id: dict[str, RetrievedChunk] | None = None,
) -> list[RetrievedChunk]:
    """
    Fallback ranking when rerank model is unavailable.

    Uses simple lexical overlap over query intent + retrieval similarity.
    """
    keywords = _query_keywords(
        query,
        topic_entities=topic_entities,
        ignored_terms=source_author_terms,
    )
    entity_phrases = [
        phrase.strip().lower()
        for phrase in (topic_entities or [])
        if isinstance(phrase, str) and phrase.strip()
    ]
    entity_tokens = {
        token
        for phrase in entity_phrases
        for token in re.findall(r"[a-z0-9]+", phrase)
        if len(token) >= 2
    }

    def score(chunk: RetrievedChunk) -> tuple[int, float]:
        scoring_chunk = (expanded_by_chunk_id or {}).get(chunk.chunk_id, chunk)
        text = str(getattr(scoring_chunk, "text", "") or "").lower()
        overlap = sum(1 for kw in keywords if kw in text)
        entity_phrase_hits = sum(1 for phrase in entity_phrases if phrase in text)
        entity_token_hits = sum(1 for token in entity_tokens if token in text)
        topic_bias = 0
        if entity_phrases:
            if entity_phrase_hits > 0:
                topic_bias += 200 + (entity_phrase_hits * 80)
            elif entity_token_hits > 0:
                topic_bias += 80 + (entity_token_hits * 20)
            else:
                topic_bias -= 120
        similarity = getattr(chunk, "similarity", None)
        if not isinstance(similarity, (int, float)):
            cosine_distance = getattr(chunk, "cosine_distance", 1.0)
            similarity = 1.0 - float(cosine_distance if isinstance(cosine_distance, (int, float)) else 1.0)
        return topic_bias + (overlap * 10) + (entity_phrase_hits * 15) + (entity_token_hits * 6), float(similarity)

    weighting_active = metadata_weighting_enabled()
    for chunk in candidates:
        lexical_score, similarity = score(chunk)
        base_score = float(lexical_score) + float(similarity)
        decision = apply_weight_to_score(
            getattr(chunk, "metadata_json", None),
            base_score=base_score,
            enabled=weighting_active,
        )
        chunk.base_score = decision.base_score
        chunk.metadata_weight = decision.weight
        chunk.weighted_score = decision.weighted_score
        chunk.corpus_class = decision.corpus_class
        chunk.weighting_applied = decision.enabled and abs(decision.weight - 1.0) > 1e-9
    return sorted(candidates, key=ranking_sort_key)


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
    response = logged_chat_completion(
        client=client,
        model=routing_model(),
        purpose="routing_rerank_fallback",
        logger=log,
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
                return sorted(selected, key=ranking_sort_key)
        else:
            overflow.append(chunk)

    for chunk in overflow:
        if len(selected) >= top_k:
            break
        selected.append(chunk)
    if overflow:
        log.info(
            "ai_sage_trace stage=diversity_cap top_k=%d per_document_cap=%d overflow=%d",
            top_k,
            per_document_cap,
            len(overflow),
        )
    return sorted(selected[:top_k], key=ranking_sort_key)


def _compact_reranker_text(anchor: RetrievedChunk, expanded: RetrievedChunk | None = None) -> str:
    metadata = _chunk_meta(anchor)
    header_parts = [
        str(metadata.get(key) or "").strip()
        for key in ("document_title", "title", "section_path", "section_heading", "heading")
        if str(metadata.get(key) or "").strip()
    ]
    header = " | ".join(dict.fromkeys(header_parts))
    body = str(getattr(expanded or anchor, "text", "") or "")
    max_chars = _RERANKER_COMPACT_CONTEXT_MAX_CHARS
    try:
        import os

        max_chars = max(300, int(os.getenv("RAG_RERANKER_COMPACT_CONTEXT_MAX_CHARS", str(max_chars))))
    except Exception:
        max_chars = _RERANKER_COMPACT_CONTEXT_MAX_CHARS
    body = body[:max_chars].strip()
    if header:
        return f"{header}\n\n{body}".strip()
    return body


def _reranker_passages_for_mode(
    candidates: list[RetrievedChunk],
    *,
    input_mode: str,
    expanded_by_chunk_id: dict[str, RetrievedChunk] | None = None,
) -> tuple[list[RetrievedChunk], list[str]]:
    expanded_lookup = expanded_by_chunk_id or {}
    if input_mode == "expanded_context":
        inputs = [expanded_lookup.get(candidate.chunk_id, candidate) for candidate in candidates]
        return inputs, [str(getattr(chunk, "text", "") or "") for chunk in inputs]
    if input_mode == "compact_context":
        inputs = [expanded_lookup.get(candidate.chunk_id, candidate) for candidate in candidates]
        passages = [
            _compact_reranker_text(candidate, expanded_lookup.get(candidate.chunk_id))
            for candidate in candidates
        ]
        return inputs, passages
    return candidates, [str(getattr(chunk, "text", "") or "") for chunk in candidates]


def _cross_encoder_fusion_mode() -> str:
    try:
        import os

        raw = os.getenv("RAG_RERANKER_FUSION_MODE", "adaptive").strip().lower()
    except Exception:
        raw = "adaptive"
    aliases = {
        "adaptive": "adaptive",
        "adaptive_blend": "adaptive",
        "pure": "pure",
        "replace": "pure",
        "reranker": "pure",
        "blend": "conditional_blend",
        "blended": "conditional_blend",
        "conditional": "conditional_blend",
        "conditional_blend": "conditional_blend",
    }
    return aliases.get(raw, "adaptive")


def _query_allows_aggressive_rerank(query: str) -> bool:
    normalized = re.sub(r"\s+", " ", query.lower()).strip()
    if not normalized:
        return False
    if re.search(r"\bviews?\s+on\b", normalized):
        return False
    if re.search(r"\brelat(?:e|es|ed|ing)?\s+to\b|\brelationship\s+between\b", normalized):
        return True
    has_list_shape = bool(re.search(r"\b(what are|what were|list|highlight|summari[sz]e)\b", normalized))
    has_broad_concept = bool(
        re.search(
            r"\b(main|best|major|key|important|mental\s+models?|principles|lessons|ideas|frameworks|examples)\b",
            normalized,
        )
    )
    if has_list_shape and has_broad_concept:
        return True
    return False


def _apply_cross_encoder_scores(
    candidates: list[RetrievedChunk],
    heuristic_ranked: list[RetrievedChunk],
    results: list[Any],
    *,
    query: str = "",
) -> list[RetrievedChunk]:
    result_by_index = {
        int(getattr(result, "index")): float(getattr(result, "relevance_score", 0.0) or 0.0)
        for result in results
        if 0 <= int(getattr(result, "index", -1)) < len(candidates)
    }
    if not result_by_index:
        return heuristic_ranked

    requested_fusion_mode = _cross_encoder_fusion_mode()
    fusion_mode = requested_fusion_mode
    if requested_fusion_mode == "adaptive":
        fusion_mode = "pure" if _query_allows_aggressive_rerank(query) else "conditional_blend"
    heuristic_rank_by_id = {chunk.chunk_id: rank for rank, chunk in enumerate(heuristic_ranked)}
    candidate_count = max(len(candidates), 1)
    weighting_active = metadata_weighting_enabled()

    if fusion_mode == "pure":
        ce_ordered_indices = sorted(result_by_index, key=lambda idx: -result_by_index[idx])
        ranked: list[RetrievedChunk] = []
        seen_ids: set[str] = set()
        for idx in ce_ordered_indices:
            chunk = candidates[idx]
            chunk.reranker_score = result_by_index[idx]
            decision = apply_weight_to_score(
                getattr(chunk, "metadata_json", None),
                base_score=chunk.reranker_score,
                enabled=weighting_active,
            )
            chunk.base_score = decision.base_score
            chunk.metadata_weight = decision.weight
            chunk.weighted_score = decision.weighted_score
            chunk.corpus_class = decision.corpus_class
            chunk.weighting_applied = decision.enabled and abs(decision.weight - 1.0) > 1e-9
            diagnostics = dict(getattr(chunk, "metadata_json", None) or {})
            diagnostics["reranker_fusion"] = {
                "mode": "pure",
                "requested_mode": requested_fusion_mode,
                "reranker_score": round(chunk.reranker_score, 6),
                "aggressive_query": _query_allows_aggressive_rerank(query),
            }
            chunk.metadata_json = diagnostics
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                ranked.append(chunk)
        for chunk in heuristic_ranked:
            if chunk.chunk_id not in seen_ids:
                ranked.append(chunk)
        return sorted(ranked, key=ranking_sort_key)

    alpha = _RERANKER_BLEND_ALPHA
    try:
        import os

        alpha = min(0.8, max(0.0, float(os.getenv("RAG_RERANKER_BLEND_ALPHA", str(alpha)))))
    except Exception:
        alpha = _RERANKER_BLEND_ALPHA

    ranked = list(heuristic_ranked)
    reranker_rank_by_index = {
        int(getattr(result, "index")): rank
        for rank, result in enumerate(results)
        if 0 <= int(getattr(result, "index", -1)) < len(candidates)
    }
    for idx, chunk in enumerate(candidates):
        heuristic_rank = heuristic_rank_by_id.get(chunk.chunk_id, candidate_count - 1)
        heuristic_component = 1.0 - (heuristic_rank / candidate_count)
        reranker_rank = reranker_rank_by_index.get(idx, candidate_count - 1)
        reranker_component = 1.0 - (reranker_rank / candidate_count)
        reranker_score = result_by_index.get(idx, 0.0)
        blended = ((1.0 - alpha) * heuristic_component) + (alpha * reranker_component)
        final_score = max(heuristic_component, blended)
        chunk.reranker_score = reranker_score
        chunk.base_score = final_score
        decision = apply_weight_to_score(
            getattr(chunk, "metadata_json", None),
            base_score=final_score,
            enabled=weighting_active,
        )
        chunk.metadata_weight = decision.weight
        chunk.weighted_score = decision.weighted_score
        chunk.corpus_class = decision.corpus_class
        chunk.weighting_applied = decision.enabled and abs(decision.weight - 1.0) > 1e-9
        diagnostics = dict(getattr(chunk, "metadata_json", None) or {})
        diagnostics["reranker_fusion"] = {
            "mode": "conditional_blend",
            "requested_mode": requested_fusion_mode,
            "heuristic_rank": heuristic_rank + 1,
            "heuristic_component": round(heuristic_component, 6),
            "reranker_rank": reranker_rank + 1,
            "reranker_component": round(reranker_component, 6),
            "reranker_score": round(reranker_score, 6),
            "blend_alpha": round(alpha, 4),
            "final_score": round(final_score, 6),
            "aggressive_query": _query_allows_aggressive_rerank(query),
        }
        chunk.metadata_json = diagnostics
    return sorted(ranked, key=ranking_sort_key)


def _rerank_candidate_chunks(
    query: str,
    candidates: list[RetrievedChunk],
    *,
    top_k: int,
    topic_entities: list[str] | None = None,
    source_author_terms: set[str] | None = None,
    expanded_by_chunk_id: dict[str, RetrievedChunk] | None = None,
) -> list[RetrievedChunk]:
    if not candidates:
        return []
    if top_k <= 0:
        return []

    heuristic_ranked = _heuristic_rank_candidates(
        query,
        candidates,
        topic_entities=topic_entities,
        source_author_terms=source_author_terms,
        expanded_by_chunk_id=expanded_by_chunk_id,
    )
    ranked = heuristic_ranked
    trace_retrieval_chunks(
        "ai_sage_heuristic_rerank",
        query,
        heuristic_ranked,
        extra={
            "candidate_count": len(candidates),
            "topic_entities": topic_entities,
            "source_author_terms_removed_from_keywords": sorted(source_author_terms or set()),
        },
    )

    # Tier 1: dedicated cross-encoder reranker (preferred — fast, deterministic, no JSON)
    if reranker_available():
        try:
            input_mode = reranker_input_mode()
            provider_name = reranker_provider_name()
            reranker_inputs, passages = _reranker_passages_for_mode(
                candidates,
                input_mode=input_mode,
                expanded_by_chunk_id=expanded_by_chunk_id,
            )
            trace_retrieval_chunks("ai_sage_cross_encoder_reranker_input", query, reranker_inputs)
            trace_retrieval_payload(
                "ai_sage_cross_encoder_reranker_config",
                {
                    "query": query,
                    "provider": provider_name,
                    "input_mode": input_mode,
                    "candidate_count": len(candidates),
                },
            )
            results = _cross_encoder_rerank(query, passages, top_k=len(candidates))
            if results:
                trace_retrieval_payload(
                    "ai_sage_cross_encoder_scores",
                    {
                        "query": query,
                        "scores": [
                            {"input_rank": r.index + 1, "score": round(float(r.relevance_score), 6)}
                            for r in results[:20]
                        ],
                    },
                )
                log.info(
                    "ai_sage_trace stage=cross_encoder_rerank provider=%s input_mode=%s query=%r top_scores=%s",
                    provider_name,
                    input_mode,
                    query[:120],
                    json.dumps(
                        [
                            {"index": r.index, "score": round(float(r.relevance_score), 6)}
                            for r in results[:10]
                        ]
                    ),
                )
                ranked = _apply_cross_encoder_scores(candidates, heuristic_ranked, results, query=query)
                trace_retrieval_chunks("ai_sage_cross_encoder_reranked", query, ranked)
                log.debug("cross-encoder reranked %d candidates", len(candidates))
        except Exception as exc:
            log.warning("cross-encoder reranking failed; falling back: %s", exc)
            trace_retrieval_payload(
                "ai_sage_cross_encoder_reranker_failed",
                {"query": query, "error": str(exc), "fallback": "heuristic"},
            )
    else:
        trace_retrieval_payload(
            "ai_sage_reranker_skipped",
            {"query": query, "reason": "cross_encoder_not_configured", "fallback": "heuristic"},
        )

    # Tier 2: LLM-prompt reranking — DISABLED (issue-146: reshuffles results poorly)
    # Falls through to Tier 3 heuristic when no cross-encoder is available.

    # Tier 3: heuristic (keyword overlap + cosine similarity) — already set as default above

    selected = _select_diverse_top_chunks(ranked, top_k=min(top_k, len(candidates)))
    trace_retrieval_chunks(
        "ai_sage_reranked_selected",
        query,
        selected,
        limit=top_k,
        extra={"input_count": len(candidates), "selected_count": len(selected)},
    )
    return selected


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
    trace_retrieval_payload(
        "ai_sage_intent",
        {
            "query": query,
            "query_type": intent.query_type,
            "author_ids": intent.author_ids,
            "author_names": intent.author_names,
            "source_types": intent.source_types,
            "date_from": intent.date_from,
            "date_to": intent.date_to,
            "topic_entities": intent.topic_entities,
            "sub_queries": intent.sub_queries,
        },
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
    trace_retrieval_payload(
        "ai_sage_selected_authors",
        {
            "query": query,
            "selected_authors": author_entries,
        },
    )

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
    hardening_active = retrieval_hardening_enabled()
    _trace_chunks("candidate_pool", query, candidate_chunks)
    expanded_candidate_chunks = expand_chunks_with_context(
        candidate_chunks,
        db,
        window_size=_CONTEXT_EXPANSION_WINDOW,
        max_chars=_CONTEXT_EXPANSION_MAX_CHARS,
        only_when_needed=False,
    )
    expanded_candidate_map = {chunk.chunk_id: chunk for chunk in expanded_candidate_chunks}
    winning_chunks = _rerank_candidate_chunks(
        query,
        candidate_chunks,
        top_k=min(top_k_chunks, len(candidate_chunks)),
        topic_entities=intent.topic_entities,
        source_author_terms=_source_author_terms(intent),
        expanded_by_chunk_id=expanded_candidate_map,
    )
    _trace_chunks("reranked", query, winning_chunks)
    expanded_chunks = _expanded_chunks_for_selection(winning_chunks, expanded_candidate_map)
    duplicates_suppressed: list[dict[str, Any]] = []
    if hardening_active:
        expanded_chunks = deliver_parent_sections(expanded_chunks, db, only_when_needed=False)
        _trace_chunks("parent_child_delivery", query, expanded_chunks)
        expanded_chunks, duplicates_suppressed = suppress_near_duplicates(expanded_chunks)
        trace_retrieval_payload(
            "ai_sage_duplicate_suppression",
            {
                "query": query,
                "kept_count": len(expanded_chunks),
                "duplicates_suppressed_count": len(duplicates_suppressed),
                "duplicates_suppressed": duplicates_suppressed,
            },
        )
        kept_chunk_ids = {chunk.chunk_id for chunk in expanded_chunks}
        winning_chunks = [chunk for chunk in winning_chunks if chunk.chunk_id in kept_chunk_ids]
    _trace_chunks("expanded_for_display", query, expanded_chunks)
    display_chunks = _with_display_context(winning_chunks, expanded_chunks)
    evidence: list[EvidenceChunk] = _enrich_chunks(display_chunks, db, author_map)

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
            "The ranked passages below are based on limited evidence and should be read cautiously."
        )

    best_passages = [e.as_dict() for e in evidence]

    # 3. Critique — disabled by default, optionally computed from the retrieved evidence.
    critique: Optional[str] = None
    if best_passages and _critique_enabled() and inference_available():
        try:
            critique = _llm_critique(
                query,
                [chunk.text for chunk in expanded_chunks[:_SINGLE_AUTHOR_SUMMARY_CHUNKS]],
            )
        except Exception as exc:
            log.warning("LLM critique failed: %s", exc)

    result = ConceptQueryResult(
        query=query,
        best_passages=best_passages,
        critique=critique,
        evidence_sufficient=evidence_sufficient,
        weak_evidence_note=weak_evidence_note,
        intent=intent.as_dict(),
        constraints_relaxed=_constraints_relaxed,
        constraint_relaxation_reason=_relaxation_reason,
    )
    try:
        from app.rag.query_logger import log_query

        evidence_dicts = [
            {
                "chunk_id": e.get("chunk_id", ""),
                "cosine_distance": 1.0 - e.get("similarity", 0.0),
                "reranker_score": (e.get("metadata") or {}).get("reranker_score"),
                "rrf_score": (e.get("metadata") or {}).get("rrf_score"),
                "ts_rank": (e.get("metadata") or {}).get("ts_rank"),
            }
            for e in best_passages
        ]
        log_query(
            db,
            query,
            "concept",
            intent=intent.as_dict(),
            evidence_chunks=evidence_dicts,
            answer_text=(best_passages[0].get("text") if best_passages else weak_evidence_note),
            latency_ms=int((time.monotonic() - _t0) * 1000),
            retrieval_config={
                "top_k_chunks": top_k_chunks,
                "top_k_authors": top_k_authors,
                "retrieval_hardening_enabled": hardening_active,
                "parent_child_delivery_enabled": hardening_active,
                "duplicates_suppressed": duplicates_suppressed,
                "duplicates_suppressed_count": len(duplicates_suppressed),
            },
        )
    except Exception as _exc:
        log.debug("concept audit log skipped: %s", _exc)
    return result
