"""
Semantic retrieval layer for RAG Phase 1 + Phase 2.

Provides semantic similarity search over stored embeddings using pgvector's
cosine distance operator (<=>).  Supports author, domain, and expertise-tag
filters for Phase 2 author-aware retrieval.

Returns citation-ready payloads with full metadata lineage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.rag.ingestion.embedder import embed_query

log = logging.getLogger(__name__)

SMOKE_DEFAULT_TOP_K = 5
DEFAULT_TOP_K = 5


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    text: str
    token_count: Optional[int]
    metadata_json: dict[str, Any]
    cosine_distance: float

    @property
    def similarity(self) -> float:
        """Cosine similarity (1 - distance)."""
        return round(1.0 - self.cosine_distance, 6)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "token_count": self.token_count,
            "similarity": self.similarity,
            "metadata": self.metadata_json,
        }


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
