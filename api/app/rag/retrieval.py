"""
Retrieval smoke layer for RAG Phase 1.

Provides semantic similarity search over stored embeddings using pgvector's
cosine distance operator (<=>).  Returns citation-ready results so callers
can confirm the corpus was embedded and stored correctly.

This is a smoke/validation path, not a full answer-generation system.
Full lens/synthesis pipelines are out of scope for Phase 1.
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
        """Cosine similarity (1 − distance)."""
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
    top_k: int = SMOKE_DEFAULT_TOP_K,
    author_id: Optional[str] = None,
    source_type: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    Embed query and return the top-k most similar chunks.

    Optional filters:
      author_id   — restrict to a single author's corpus
      source_type — restrict to 'html', 'pdf', 'text', or 'manual'

    Returns an empty list if no embeddings exist yet.
    """
    query_vector = embed_query(query)
    vector_literal = "[" + ",".join(str(v) for v in query_vector) + "]"

    # Build optional WHERE clauses for metadata filters on the source.
    where_clauses = []
    params: dict[str, Any] = {"top_k": top_k, "query_vec": vector_literal}

    if author_id:
        where_clauses.append("rs.author_id = :author_id")
        params["author_id"] = author_id
    if source_type:
        where_clauses.append("rs.source_type = :source_type")
        params["source_type"] = source_type

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
