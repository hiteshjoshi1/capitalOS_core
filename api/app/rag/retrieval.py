"""
Semantic retrieval layer for RAG Phase 1 + Phase 2.

Provides semantic similarity search over stored embeddings using pgvector's
cosine distance operator (<=>).  Supports author, domain, and expertise-tag
filters for Phase 2 author-aware retrieval.

Also provides sparse/keyword retrieval via Postgres full-text search
(tsvector/tsquery) and hybrid retrieval combining both via Reciprocal Rank
Fusion (RRF).

Returns citation-ready payloads with full metadata lineage.

Constraint-aware retrieval (Issue 145):
- retrieve_with_constraints(): strict no-fallback retrieval
- All retrieval paths accept year_from/year_to (int) and published_from/published_to (YYYY-MM-DD)
- Date filters prefer rag_documents.published_at where available (Postgres only)
- ConstrainedRetrievalResult exposes what constraints were applied vs requested
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.rag import RagChunk
from app.rag.ingestion.embedder import embed_query
from app.rag.retrieval_weighting import (
    apply_weight_to_score,
    merge_retrieval_metadata,
    metadata_weighting_enabled,
    ranking_sort_key,
    weighting_candidate_limit,
    weighting_feature_flag,
)

log = logging.getLogger(__name__)

SMOKE_DEFAULT_TOP_K = 5
DEFAULT_TOP_K = 5

# ── Env-driven retrieval config ───────────────────────────────────────────────
_RETRIEVAL_MODE = os.getenv("RAG_RETRIEVAL_MODE", "hybrid")
_RRF_K = int(os.getenv("RAG_RETRIEVAL_RRF_K", "60"))
_DENSE_TOP_K_MULTIPLIER = int(os.getenv("RAG_RETRIEVAL_DENSE_TOP_K_MULTIPLIER", "3"))


@dataclass
class ConstrainedRetrievalResult:
    """
    Result of a constraint-aware retrieval operation.

    Tracks which constraints were requested, which were actually applied,
    and whether any were relaxed (and why).  Diagnostics are opt-in via
    the ``debug`` parameter on ``retrieve_with_constraints()``.
    """

    chunks: list["RetrievedChunk"]
    constraints_requested: dict[str, Any]
    constraints_applied: dict[str, Any]
    constraints_relaxed: bool = False
    constraint_relaxation_reason: Optional[str] = None
    diagnostics: Optional[dict[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "constraints_requested": self.constraints_requested,
            "constraints_applied": self.constraints_applied,
            "constraints_relaxed": self.constraints_relaxed,
            "constraint_relaxation_reason": self.constraint_relaxation_reason,
            "evidence_chunks": [c.as_dict() for c in self.chunks],
        }
        if self.diagnostics is not None:
            d["diagnostics"] = self.diagnostics
        return d


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    token_count: Optional[int]
    metadata_json: dict[str, Any]
    cosine_distance: float
    ts_rank: Optional[float] = None
    rrf_score: Optional[float] = None
    reranker_score: Optional[float] = None
    metadata_weight: float = 1.0
    base_score: Optional[float] = None
    weighted_score: Optional[float] = None
    corpus_class: Optional[str] = None
    weighting_applied: bool = False

    @property
    def similarity(self) -> float:
        """Cosine similarity (1 - distance), or a normalized score for keyword/RRF results."""
        if self.cosine_distance < 1.0:
            return round(1.0 - self.cosine_distance, 6)
        # Keyword-only or RRF-merged chunk without dense score
        if self.rrf_score is not None:
            # RRF scores are small (typically 0.01-0.03); normalize to 0-1 range
            return round(min(self.rrf_score * 30, 1.0), 6)
        if self.ts_rank is not None:
            # ts_rank is typically 0-1 already but can exceed 1
            return round(min(self.ts_rank, 1.0), 6)
        return 0.0

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "token_count": self.token_count,
            "similarity": self.similarity,
            "metadata": self.metadata_json,
        }
        if self.ts_rank is not None:
            d["ts_rank"] = self.ts_rank
        if self.rrf_score is not None:
            d["rrf_score"] = self.rrf_score
        if self.reranker_score is not None:
            d["reranker_score"] = self.reranker_score
        if self.metadata_weight != 1.0:
            d["metadata_weight"] = self.metadata_weight
        if self.base_score is not None:
            d["base_score"] = self.base_score
        if self.weighted_score is not None:
            d["weighted_score"] = self.weighted_score
        if self.corpus_class is not None:
            d["corpus_class"] = self.corpus_class
        if self.weighting_applied:
            d["weighting_applied"] = True
        return d


def _should_expand_chunk_text(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if len(cleaned) < 280:
        return True
    if cleaned.endswith("...") or cleaned.endswith("…"):
        return True
    tail = cleaned[-30:]
    return not any(p in tail for p in ".!?")


def retrieve_similar_chunks(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    weighting_enabled: Optional[bool] = None,
) -> list[RetrievedChunk]:
    """
    Embed query and return the top-k most similar chunks.

    Filters:
      author_id      -- restrict to a single author's corpus
      author_ids     -- restrict to a selected set of authors
      source_type    -- restrict to 'html', 'pdf', 'text', or 'manual'
      domains        -- restrict to authors in these domain categories (Postgres only)
      expertise_tags -- restrict to authors with these expertise tags (Postgres only)
      year_from      -- restrict to chunks whose year >= year_from
                        (prefers rag_documents.published_at on Postgres,
                         falls back to metadata_json->>'year')
      year_to        -- restrict to chunks whose year <= year_to (same precedence)
      published_from -- restrict to documents with published_at >= published_from (YYYY-MM-DD)
      published_to   -- restrict to documents with published_at <= published_to (YYYY-MM-DD)

    Returns an empty list if no embeddings exist yet.
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    query_vector = embed_query(query)
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    where_clauses: list[str] = []
    params: dict[str, Any] = {
        "top_k": weighting_candidate_limit(top_k, enabled=weighting_active),
        "query_vec": vector_literal,
    }

    is_postgres = _is_postgres(db)

    if author_id:
        where_clauses.append("COALESCE(rd.author_id, rs.author_id) = :author_id")
        params["author_id"] = author_id
    elif author_ids:
        author_id_conditions = " OR ".join(
            f"COALESCE(rd.author_id, rs.author_id) = :author_id_{i}" for i in range(len(author_ids))
        )
        where_clauses.append(f"({author_id_conditions})")
        for i, selected_author_id in enumerate(author_ids):
            params[f"author_id_{i}"] = selected_author_id
    if source_type:
        where_clauses.append("rs.source_type = :source_type")
        params["source_type"] = source_type
    if domains:
        domain_conditions = " OR ".join(f":domain_{i} = ANY(ra.domains)" for i in range(len(domains)))
        where_clauses.append(f"({domain_conditions})")
        for i, d in enumerate(domains):
            params[f"domain_{i}"] = d
    if expertise_tags:
        tag_conditions = " OR ".join(f":tag_{i} = ANY(ra.expertise_tags)" for i in range(len(expertise_tags)))
        where_clauses.append(f"({tag_conditions})")
        for i, t in enumerate(expertise_tags):
            params[f"tag_{i}"] = t

    _apply_date_filters(where_clauses, params, is_postgres, year_from, year_to, published_from, published_to)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = text(
        f"""
        SELECT
            rc.id             AS chunk_id,
            rc.document_id,
            rc.chunk_index,
            rc.text,
            rc.token_count,
            rc.metadata_json,
            rd.collection,
            rd.canonical_status,
            rd.dedupe_priority,
            rd.work_type,
            rd.metadata_json AS document_metadata_json,
            (re.embedding <=> CAST(:query_vec AS vector)) AS cosine_distance
        FROM rag_embeddings re
        JOIN rag_chunks    rc ON rc.id = re.chunk_id
        JOIN rag_documents rd ON rd.id = rc.document_id
        JOIN rag_sources   rs ON rs.id = rd.source_id
        JOIN rag_authors   ra ON ra.id = COALESCE(rd.author_id, rs.author_id)
        {where_sql}
        ORDER BY cosine_distance ASC
        LIMIT :top_k
        """
    )

    try:
        rows = db.execute(sql, params).mappings().all()
    except Exception as exc:
        log.exception("retrieve_similar_chunks query failed: %s", exc)
        return []

    chunks = [
        RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            metadata_json=merge_retrieval_metadata(
                dict(row["metadata_json"]) if row["metadata_json"] else {},
                collection=row["collection"],
                canonical_status=row["canonical_status"],
                dedupe_priority=row["dedupe_priority"],
                work_type=row["work_type"],
                document_metadata=dict(row["document_metadata_json"]) if row["document_metadata_json"] else {},
            ),
            cosine_distance=float(row["cosine_distance"]),
        )
        for row in rows
    ]
    return _rank_chunks(chunks, top_k=top_k, stage="dense", weighting_enabled=weighting_active)


def expand_chunks_with_context(
    chunks: list[RetrievedChunk],
    db: Session,
    *,
    window_size: int = 2,
    max_chars: int = 1800,
    only_when_needed: bool = False,
) -> list[RetrievedChunk]:
    """
    Expand each winning chunk with neighboring chunks from the same document.

    This keeps the selected evidence set size stable while materially enriching
    each passage with surrounding context.
    """
    if not chunks or window_size < 1:
        return chunks

    expanded: list[RetrievedChunk] = []
    for chunk in chunks:
        if only_when_needed and not _should_expand_chunk_text(str(getattr(chunk, "text", "") or "")):
            expanded.append(chunk)
            continue
        try:
            neighbors = (
                db.query(RagChunk)
                .filter(
                    RagChunk.document_id == chunk.document_id,
                    RagChunk.chunk_index >= chunk.chunk_index - window_size,
                    RagChunk.chunk_index <= chunk.chunk_index + window_size,
                )
                .order_by(RagChunk.chunk_index.asc())
                .all()
            )
        except Exception as exc:
            log.warning("expand_chunks_with_context failed for chunk=%s: %s", chunk.chunk_id, exc)
            expanded.append(chunk)
            continue

        if not neighbors:
            expanded.append(chunk)
            continue

        merged_indices = [n.chunk_index for n in neighbors]
        merged_passages = [n.text.strip() for n in neighbors if (n.text or "").strip()]
        base_text = str(getattr(chunk, "text", "") or "")
        merged_text = "\n\n".join(merged_passages).strip() or base_text
        if max_chars > 0 and len(merged_text) > max_chars:
            merged_text = merged_text[: max_chars - 3].rstrip() + "..."

        summed_tokens = sum((n.token_count or 0) for n in neighbors)
        raw_metadata = getattr(chunk, "metadata_json", None)
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        metadata["context_window"] = window_size
        metadata["anchor_chunk_index"] = chunk.chunk_index
        metadata["context_chunk_indices"] = merged_indices

        expanded.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                text=merged_text,
                token_count=summed_tokens or chunk.token_count,
                metadata_json=metadata,
                cosine_distance=chunk.cosine_distance,
                ts_rank=chunk.ts_rank,
                rrf_score=chunk.rrf_score,
                reranker_score=chunk.reranker_score,
            )
        )

    return expanded


# ── Sparse (keyword) retrieval ────────────────────────────────────────────────


def retrieve_keyword_chunks(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    weighting_enabled: Optional[bool] = None,
) -> list[RetrievedChunk]:
    """
    Full-text search using Postgres tsvector/tsquery.

    Uses plainto_tsquery for safe query parsing (no injection risk).
    Returns an empty list on non-Postgres backends (e.g. SQLite in tests).

    Same filter parameters as retrieve_similar_chunks().
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    dialect_name = db.bind.dialect.name if db.bind else "unknown"
    if dialect_name != "postgresql":
        log.debug("retrieve_keyword_chunks: skipping FTS on non-Postgres dialect=%s", dialect_name)
        return []

    if not query or not query.strip():
        return []

    where_clauses: list[str] = ["rc.tsv @@ plainto_tsquery('english', :fts_query)"]
    params: dict[str, Any] = {
        "top_k": weighting_candidate_limit(top_k, enabled=weighting_active),
        "fts_query": query,
    }

    is_postgres = True  # already verified above

    if author_id:
        where_clauses.append("COALESCE(rd.author_id, rs.author_id) = :author_id")
        params["author_id"] = author_id
    elif author_ids:
        author_id_conditions = " OR ".join(
            f"COALESCE(rd.author_id, rs.author_id) = :author_id_{i}" for i in range(len(author_ids))
        )
        where_clauses.append(f"({author_id_conditions})")
        for i, aid in enumerate(author_ids):
            params[f"author_id_{i}"] = aid
    if source_type:
        where_clauses.append("rs.source_type = :source_type")
        params["source_type"] = source_type
    if domains:
        domain_conditions = " OR ".join(f":domain_{i} = ANY(ra.domains)" for i in range(len(domains)))
        where_clauses.append(f"({domain_conditions})")
        for i, d in enumerate(domains):
            params[f"domain_{i}"] = d
    if expertise_tags:
        tag_conditions = " OR ".join(f":tag_{i} = ANY(ra.expertise_tags)" for i in range(len(expertise_tags)))
        where_clauses.append(f"({tag_conditions})")
        for i, t in enumerate(expertise_tags):
            params[f"tag_{i}"] = t

    _apply_date_filters(where_clauses, params, is_postgres, year_from, year_to, published_from, published_to)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = text(
        f"""
        SELECT
            rc.id             AS chunk_id,
            rc.document_id,
            rc.chunk_index,
            rc.text,
            rc.token_count,
            rc.metadata_json,
            rd.collection,
            rd.canonical_status,
            rd.dedupe_priority,
            rd.work_type,
            rd.metadata_json AS document_metadata_json,
            ts_rank(rc.tsv, plainto_tsquery('english', :fts_query)) AS ts_rank
        FROM rag_chunks    rc
        JOIN rag_documents rd ON rd.id = rc.document_id
        JOIN rag_sources   rs ON rs.id = rd.source_id
        JOIN rag_authors   ra ON ra.id = COALESCE(rd.author_id, rs.author_id)
        {where_sql}
        ORDER BY ts_rank DESC
        LIMIT :top_k
        """
    )

    try:
        rows = db.execute(sql, params).mappings().all()
    except Exception as exc:
        log.exception("retrieve_keyword_chunks query failed: %s", exc)
        return []

    chunks = [
        RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            metadata_json=merge_retrieval_metadata(
                dict(row["metadata_json"]) if row["metadata_json"] else {},
                collection=row["collection"],
                canonical_status=row["canonical_status"],
                dedupe_priority=row["dedupe_priority"],
                work_type=row["work_type"],
                document_metadata=dict(row["document_metadata_json"]) if row["document_metadata_json"] else {},
            ),
            cosine_distance=1.0,  # no cosine distance for keyword results
            ts_rank=float(row["ts_rank"]),
        )
        for row in rows
    ]
    return _rank_chunks(chunks, top_k=top_k, stage="sparse", weighting_enabled=weighting_active)


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────


def reciprocal_rank_fusion(
    *result_lists: list[RetrievedChunk],
    k: int = _RRF_K,
    weighting_enabled: Optional[bool] = None,
) -> list[RetrievedChunk]:
    """
    Combine multiple ranked result lists using Reciprocal Rank Fusion (RRF).

    RRF score for document d = sum(1 / (k + rank_i(d))) for each ranked list i.
    Higher score = more relevant (ranked earlier across lists).

    Args:
        *result_lists: One or more ranked lists of RetrievedChunk.
        k: RRF constant (default 60). Controls how much early ranks dominate.

    Returns:
        Combined list sorted by descending RRF score, with rrf_score set.
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            chunk_id = chunk.chunk_id
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = chunk
    combined: list[RetrievedChunk] = []
    for cid, rrf_score in scores.items():
        chunk = chunk_map[cid]
        combined.append(
            RetrievedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                token_count=chunk.token_count,
                metadata_json=chunk.metadata_json,
                cosine_distance=chunk.cosine_distance,
                ts_rank=chunk.ts_rank,
                rrf_score=rrf_score,
                reranker_score=chunk.reranker_score,
            )
        )
    return _rank_chunks(combined, top_k=len(combined), stage="rrf", weighting_enabled=weighting_active)


# ── Hybrid retrieval ──────────────────────────────────────────────────────────


def retrieve_hybrid(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    weighting_enabled: Optional[bool] = None,
    retrieval_mode: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    Hybrid retrieval combining dense vector search and sparse keyword search.

    Fetches top_k * _DENSE_TOP_K_MULTIPLIER from each source, then combines
    via Reciprocal Rank Fusion (RRF) and returns the top_k results.

    Falls back to dense-only if keyword retrieval returns no results
    (e.g. non-Postgres backend or no FTS index yet).

    Controlled by RAG_RETRIEVAL_MODE env var:
      hybrid      — dense + sparse via RRF (default)
      dense_only  — dense vector search only
      sparse_only — sparse keyword search only
    """
    weighting_active = metadata_weighting_enabled(override=weighting_enabled)
    mode = retrieval_mode or _RETRIEVAL_MODE
    fetch_k = top_k * _DENSE_TOP_K_MULTIPLIER

    common_kwargs: dict[str, Any] = {
        "author_id": author_id,
        "author_ids": author_ids,
        "source_type": source_type,
        "domains": domains,
        "expertise_tags": expertise_tags,
        "year_from": year_from,
        "year_to": year_to,
        "published_from": published_from,
        "published_to": published_to,
        "weighting_enabled": weighting_active,
    }

    if mode == "dense_only":
        return retrieve_similar_chunks(query, db, top_k=top_k, **common_kwargs)

    if mode == "sparse_only":
        return retrieve_keyword_chunks(query, db, top_k=top_k, **common_kwargs)

    # hybrid (default)
    dense_results = retrieve_similar_chunks(query, db, top_k=fetch_k, **common_kwargs)
    sparse_results = retrieve_keyword_chunks(query, db, top_k=fetch_k, **common_kwargs)

    if not sparse_results:
        # Non-Postgres or no FTS data yet — fall back to dense only
        log.debug("retrieve_hybrid: sparse retrieval returned 0 results, using dense only")
        return dense_results[:top_k]

    combined = reciprocal_rank_fusion(
        dense_results,
        sparse_results,
        k=_RRF_K,
        weighting_enabled=weighting_active,
    )
    return combined[:top_k]


def compare_retrieval_weighting(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    retrieval_mode: Optional[str] = None,
) -> dict[str, Any]:
    common_kwargs: dict[str, Any] = {
        "top_k": top_k,
        "author_id": author_id,
        "author_ids": author_ids,
        "source_type": source_type,
        "domains": domains,
        "expertise_tags": expertise_tags,
        "year_from": year_from,
        "year_to": year_to,
        "published_from": published_from,
        "published_to": published_to,
        "retrieval_mode": retrieval_mode,
    }
    baseline = retrieve_hybrid(query, db, weighting_enabled=False, **common_kwargs)
    weighted = retrieve_hybrid(query, db, weighting_enabled=True, **common_kwargs)
    return {
        "query": query,
        "retrieval_mode": retrieval_mode or _RETRIEVAL_MODE,
        "weighting_feature_flag": weighting_feature_flag(),
        "default_weighting_enabled": metadata_weighting_enabled(),
        "baseline_results": [chunk.as_dict() for chunk in baseline],
        "weighted_results": [chunk.as_dict() for chunk in weighted],
    }


# ── Private helpers ───────────────────────────────────────────────────────────


def _is_postgres(db: Session) -> bool:
    """Return True when the session is connected to PostgreSQL."""
    try:
        return (db.bind.dialect.name if db.bind else "unknown") == "postgresql"
    except Exception:
        return False


def _rank_chunks(
    chunks: list[RetrievedChunk],
    *,
    top_k: int,
    stage: str,
    weighting_enabled: bool,
) -> list[RetrievedChunk]:
    if not chunks:
        return []

    for chunk in chunks:
        base_score = _base_score_for_stage(chunk, stage)
        decision = apply_weight_to_score(
            chunk.metadata_json,
            base_score=base_score,
            enabled=weighting_enabled,
        )
        chunk.base_score = decision.base_score
        chunk.metadata_weight = decision.weight
        chunk.weighted_score = decision.weighted_score
        chunk.corpus_class = decision.corpus_class
        chunk.weighting_applied = decision.enabled and abs(decision.weight - 1.0) > 1e-9

    ranked = sorted(chunks, key=ranking_sort_key)
    return ranked[:top_k]


def _base_score_for_stage(chunk: RetrievedChunk, stage: str) -> float:
    if stage == "dense":
        return max(0.0, 1.0 - float(chunk.cosine_distance))
    if stage == "sparse":
        return float(chunk.ts_rank or 0.0)
    if stage == "rrf":
        return float(chunk.rrf_score or 0.0)
    if stage == "rerank":
        if chunk.reranker_score is not None:
            return float(chunk.reranker_score)
        return _base_score_for_stage(chunk, "dense")
    return float(chunk.weighted_score or chunk.base_score or chunk.similarity)


def _apply_date_filters(
    where_clauses: list[str],
    params: dict[str, Any],
    is_postgres: bool,
    year_from: Optional[int],
    year_to: Optional[int],
    published_from: Optional[str],
    published_to: Optional[str],
) -> None:
    """
    Append date-related WHERE clauses and bind params in-place.

    On Postgres: prefers rd.published_at, then rd.publication_year for year filters.
    On SQLite: falls back to rd.publication_year and metadata_json->>'year'
                (published_from/published_to are ignored as SQLite has no
                native DATE column; that column is stored as TEXT).
    """
    if is_postgres:
        if year_from is not None:
            where_clauses.append(
                "("
                " (rd.published_at IS NOT NULL AND EXTRACT(YEAR FROM rd.published_at) >= :year_from)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NOT NULL AND rd.publication_year >= :year_from)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NULL AND (rc.metadata_json->>'year') >= :year_from_str)"
                ")"
            )
            params["year_from"] = year_from
            params["year_from_str"] = str(year_from)
        if year_to is not None:
            where_clauses.append(
                "("
                " (rd.published_at IS NOT NULL AND EXTRACT(YEAR FROM rd.published_at) <= :year_to)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NOT NULL AND rd.publication_year <= :year_to)"
                " OR (rd.published_at IS NULL AND rd.publication_year IS NULL AND (rc.metadata_json->>'year') <= :year_to_str)"
                ")"
            )
            params["year_to"] = year_to
            params["year_to_str"] = str(year_to)
        if published_from:
            where_clauses.append("rd.published_at >= :published_from")
            params["published_from"] = published_from
        if published_to:
            where_clauses.append("rd.published_at <= :published_to")
            params["published_to"] = published_to
    else:
        # SQLite: prefer the document column, then fall back to metadata_json->>'year'
        if year_from is not None:
            where_clauses.append(
                "(rd.publication_year IS NOT NULL AND rd.publication_year >= :year_from"
                " OR rd.publication_year IS NULL AND (rc.metadata_json->>'year') >= :year_from_str)"
            )
            params["year_from"] = year_from
            params["year_from_str"] = str(year_from)
        if year_to is not None:
            where_clauses.append(
                "(rd.publication_year IS NOT NULL AND rd.publication_year <= :year_to"
                " OR rd.publication_year IS NULL AND (rc.metadata_json->>'year') <= :year_to_str)"
            )
            params["year_to"] = year_to
            params["year_to_str"] = str(year_to)


# ── Constraint-aware retrieval ────────────────────────────────────────────────


def retrieve_with_constraints(
    query: str,
    db: Session,
    *,
    top_k: int = DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    author_ids: Optional[list[str]] = None,
    source_type: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    published_from: Optional[str] = None,
    published_to: Optional[str] = None,
    domains: Optional[list[str]] = None,
    expertise_tags: Optional[list[str]] = None,
    strict_constraints: bool = True,
    debug: bool = False,
) -> ConstrainedRetrievalResult:
    """
    Strict constraint-aware retrieval — no silent fallback.

    When ``strict_constraints=True`` (default), the query is executed once
    with the full set of requested filters.  If the corpus returns zero
    results the caller receives an empty chunk list and
    ``constraints_relaxed=False``.  The caller decides whether to retry
    with relaxed constraints.

    When ``strict_constraints=False``, the function performs staged
    fallback:
      1. Full constraints
      2. Drop source_type
      3. Drop year/date filters
      4. Fully unconstrained

    Each relaxation step is recorded in ``constraint_relaxation_reason``.

    The ``debug`` flag enables candidate count diagnostics in the response.
    """
    requested: dict[str, Any] = {
        "author_id": author_id,
        "author_ids": author_ids,
        "source_type": source_type,
        "year_from": year_from,
        "year_to": year_to,
        "published_from": published_from,
        "published_to": published_to,
        "domains": domains,
        "expertise_tags": expertise_tags,
    }
    # Prune None values for cleaner response output
    requested = {k: v for k, v in requested.items() if v is not None}

    common_base: dict[str, Any] = {
        "author_id": author_id,
        "author_ids": author_ids,
        "domains": domains,
        "expertise_tags": expertise_tags,
    }

    if strict_constraints:
        chunks = retrieve_hybrid(
            query,
            db,
            top_k=top_k,
            source_type=source_type,
            year_from=year_from,
            year_to=year_to,
            published_from=published_from,
            published_to=published_to,
            **common_base,
        )
        applied = dict(requested)
        diagnostics = {"candidate_count": len(chunks)} if debug else None
        return ConstrainedRetrievalResult(
            chunks=chunks,
            constraints_requested=requested,
            constraints_applied=applied,
            constraints_relaxed=False,
            constraint_relaxation_reason=None,
            diagnostics=diagnostics,
        )

    # Fallback mode: staged relaxation
    attempts: list[tuple[dict[str, Any], str]] = [
        (
            {"source_type": source_type, "year_from": year_from, "year_to": year_to,
             "published_from": published_from, "published_to": published_to},
            "full constraints",
        ),
        (
            {"source_type": None, "year_from": year_from, "year_to": year_to,
             "published_from": published_from, "published_to": published_to},
            "source_type relaxed",
        ),
        (
            {"source_type": source_type, "year_from": None, "year_to": None,
             "published_from": None, "published_to": None},
            "date/year filters relaxed",
        ),
        (
            {"source_type": None, "year_from": None, "year_to": None,
             "published_from": None, "published_to": None},
            "all filters relaxed",
        ),
    ]

    # Deduplicate attempt signatures
    seen_sigs: set[tuple] = set()
    deduped_attempts = []
    for attempt_filters, reason in attempts:
        sig = tuple(sorted(attempt_filters.items()))
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            deduped_attempts.append((attempt_filters, reason))

    for attempt_filters, reason in deduped_attempts:
        chunks = retrieve_hybrid(
            query,
            db,
            top_k=top_k,
            **attempt_filters,
            **common_base,
        )
        if chunks:
            is_first = (attempt_filters, reason) == deduped_attempts[0]
            applied = {k: v for k, v in {**attempt_filters, **common_base}.items() if v is not None}
            relaxation_reason: Optional[str] = None if is_first else f"No results under exact constraints; {reason}."
            if not is_first:
                log.info(
                    "retrieve_with_constraints: fallback applied query=%r reason=%r",
                    query[:120],
                    relaxation_reason,
                )
            diagnostics = {"candidate_count": len(chunks)} if debug else None
            return ConstrainedRetrievalResult(
                chunks=chunks,
                constraints_requested=requested,
                constraints_applied=applied,
                constraints_relaxed=not is_first,
                constraint_relaxation_reason=relaxation_reason,
                diagnostics=diagnostics,
            )

    # All attempts returned zero results
    applied_empty = {k: v for k, v in {**deduped_attempts[-1][0], **common_base}.items() if v is not None}
    return ConstrainedRetrievalResult(
        chunks=[],
        constraints_requested=requested,
        constraints_applied=applied_empty,
        constraints_relaxed=True,
        constraint_relaxation_reason="No results found even after full constraint relaxation.",
        diagnostics={"candidate_count": 0} if debug else None,
    )
