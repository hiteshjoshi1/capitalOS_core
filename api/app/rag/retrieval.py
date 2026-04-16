"""
Semantic retrieval layer for RAG Phase 1 + Phase 2.

Provides semantic similarity search over stored embeddings using pgvector's
cosine distance operator (<=>).  Supports author, domain, and expertise-tag
filters for Phase 2 author-aware retrieval.

Also provides sparse/keyword retrieval via Postgres full-text search
(tsvector/tsquery) and hybrid retrieval combining both via Reciprocal Rank
Fusion (RRF).

Returns citation-ready payloads with full metadata lineage.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.rag import RagChunk
from app.rag.ingestion.embedder import embed_query

log = logging.getLogger(__name__)

SMOKE_DEFAULT_TOP_K = 5
DEFAULT_TOP_K = 5

# ── Env-driven retrieval config ───────────────────────────────────────────────
_RETRIEVAL_MODE = os.getenv("RAG_RETRIEVAL_MODE", "hybrid")
_RRF_K = int(os.getenv("RAG_RETRIEVAL_RRF_K", "60"))
_DENSE_TOP_K_MULTIPLIER = int(os.getenv("RAG_RETRIEVAL_DENSE_TOP_K_MULTIPLIER", "3"))


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

    @property
    def similarity(self) -> float:
        """Cosine similarity (1 - distance)."""
        return round(1.0 - self.cosine_distance, 6)

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
        return d


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
    year_from: Optional[str] = None,
    year_to: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    Embed query and return the top-k most similar chunks.

    Filters:
      author_id      -- restrict to a single author's corpus
      author_ids     -- restrict to a selected set of authors
      source_type    -- restrict to 'html', 'pdf', 'text', or 'manual'
      domains        -- restrict to authors in these domain categories (Postgres only)
      expertise_tags -- restrict to authors with these expertise tags (Postgres only)
      year_from      -- restrict to chunks whose metadata_json->>'year' >= year_from
      year_to        -- restrict to chunks whose metadata_json->>'year' <= year_to

    Returns an empty list if no embeddings exist yet.
    """
    query_vector = embed_query(query)
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    where_clauses: list[str] = []
    params: dict[str, Any] = {"top_k": top_k, "query_vec": vector_literal}

    if author_id:
        where_clauses.append("rs.author_id = :author_id")
        params["author_id"] = author_id
    elif author_ids:
        author_id_conditions = " OR ".join(
            f"rs.author_id = :author_id_{i}" for i in range(len(author_ids))
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
    if year_from:
        where_clauses.append("(rc.metadata_json->>'year') >= :year_from")
        params["year_from"] = year_from
    if year_to:
        where_clauses.append("(rc.metadata_json->>'year') <= :year_to")
        params["year_to"] = year_to

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
            (re.embedding <=> CAST(:query_vec AS vector)) AS cosine_distance
        FROM rag_embeddings re
        JOIN rag_chunks    rc ON rc.id = re.chunk_id
        JOIN rag_documents rd ON rd.id = rc.document_id
        JOIN rag_sources   rs ON rs.id = rd.source_id
        JOIN rag_authors   ra ON ra.id = rs.author_id
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

    return [
        RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            metadata_json=dict(row["metadata_json"]) if row["metadata_json"] else {},
            cosine_distance=float(row["cosine_distance"]),
        )
        for row in rows
    ]


def expand_chunks_with_context(
    chunks: list[RetrievedChunk],
    db: Session,
    *,
    window_size: int = 2,
    max_chars: int = 1800,
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
    year_from: Optional[str] = None,
    year_to: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    Full-text search using Postgres tsvector/tsquery.

    Uses plainto_tsquery for safe query parsing (no injection risk).
    Returns an empty list on non-Postgres backends (e.g. SQLite in tests).

    Same filter parameters as retrieve_similar_chunks().
    """
    dialect_name = db.bind.dialect.name if db.bind else "unknown"
    if dialect_name != "postgresql":
        log.debug("retrieve_keyword_chunks: skipping FTS on non-Postgres dialect=%s", dialect_name)
        return []

    if not query or not query.strip():
        return []

    where_clauses: list[str] = ["rc.tsv @@ plainto_tsquery('english', :fts_query)"]
    params: dict[str, Any] = {"top_k": top_k, "fts_query": query}

    if author_id:
        where_clauses.append("rs.author_id = :author_id")
        params["author_id"] = author_id
    elif author_ids:
        author_id_conditions = " OR ".join(
            f"rs.author_id = :author_id_{i}" for i in range(len(author_ids))
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
    if year_from:
        where_clauses.append("(rc.metadata_json->>'year') >= :year_from")
        params["year_from"] = year_from
    if year_to:
        where_clauses.append("(rc.metadata_json->>'year') <= :year_to")
        params["year_to"] = year_to

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
            ts_rank(rc.tsv, plainto_tsquery('english', :fts_query)) AS ts_rank
        FROM rag_chunks    rc
        JOIN rag_documents rd ON rd.id = rc.document_id
        JOIN rag_sources   rs ON rs.id = rd.source_id
        JOIN rag_authors   ra ON ra.id = rs.author_id
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

    return [
        RetrievedChunk(
            chunk_id=str(row["chunk_id"]),
            document_id=str(row["document_id"]),
            chunk_index=row["chunk_index"],
            text=row["text"],
            token_count=row["token_count"],
            metadata_json=dict(row["metadata_json"]) if row["metadata_json"] else {},
            cosine_distance=1.0,  # no cosine distance for keyword results
            ts_rank=float(row["ts_rank"]),
        )
        for row in rows
    ]


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────


def reciprocal_rank_fusion(
    *result_lists: list[RetrievedChunk],
    k: int = _RRF_K,
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
    scores: dict[str, float] = {}
    chunk_map: dict[str, RetrievedChunk] = {}

    for result_list in result_lists:
        for rank, chunk in enumerate(result_list):
            chunk_id = chunk.chunk_id
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = chunk

    sorted_ids = sorted(scores.keys(), key=lambda cid: -scores[cid])

    combined: list[RetrievedChunk] = []
    for cid in sorted_ids:
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
                rrf_score=scores[cid],
            )
        )
    return combined


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
    year_from: Optional[str] = None,
    year_to: Optional[str] = None,
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
    mode = _RETRIEVAL_MODE
    fetch_k = top_k * _DENSE_TOP_K_MULTIPLIER

    common_kwargs: dict[str, Any] = {
        "author_id": author_id,
        "author_ids": author_ids,
        "source_type": source_type,
        "domains": domains,
        "expertise_tags": expertise_tags,
        "year_from": year_from,
        "year_to": year_to,
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

    combined = reciprocal_rank_fusion(dense_results, sparse_results, k=_RRF_K)
    return combined[:top_k]

