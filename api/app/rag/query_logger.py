"""
Query audit trail logger for the RAG retrieval pipeline.

Logs every query and its evidence to rag_queries and rag_query_evidence.
Logging is fire-and-forget (non-blocking) when RAG_EVAL_LOG_QUERIES=1.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def _logging_enabled() -> bool:
    return os.getenv("RAG_EVAL_LOG_QUERIES", "1") == "1"


def log_query(
    db: Session,
    query_text: str,
    mode: str,
    *,
    intent: Optional[dict[str, Any]] = None,
    evidence_chunks: Optional[list[dict[str, Any]]] = None,
    answer_text: Optional[str] = None,
    latency_ms: Optional[int] = None,
    retrieval_config: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    Log a query and its evidence chunks to the audit trail.

    Returns the new query_id string, or None if logging is disabled or fails.
    Failures are swallowed so the calling code path is never interrupted.
    """
    if not _logging_enabled():
        return None
    try:
        # Import here to avoid circular imports at module load time.
        from app.models.rag import RagQuery, RagQueryEvidence

        query_row = RagQuery(
            query_text=query_text,
            mode=mode,
            intent_json=intent or {},
            retrieval_config=retrieval_config or {},
            answer_text=answer_text,
            latency_ms=latency_ms,
        )
        db.add(query_row)
        db.flush()  # Populate query_row.id before writing evidence rows.

        for rank, chunk in enumerate(evidence_chunks or [], start=1):
            ev = RagQueryEvidence(
                query_id=str(query_row.id),
                chunk_id=str(chunk.get("chunk_id", "")),
                rank=rank,
                cosine_distance=chunk.get("cosine_distance"),
                reranker_score=chunk.get("reranker_score"),
                rrf_score=chunk.get("rrf_score"),
                ts_rank=chunk.get("ts_rank"),
                is_golden=bool(chunk.get("is_golden", False)),
            )
            db.add(ev)

        db.commit()
        return str(query_row.id)
    except Exception as exc:
        log.warning("query logging failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None
