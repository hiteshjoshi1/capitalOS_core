"""
Ingestion pipeline orchestrator.

Ties together: fetch → parse → chunk → embed → persist.

Entry points:
  run_url_ingestion(source, db)    — for URL-based sources
  run_manual_ingestion(source, text, db) — for manually supplied text/docs
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.rag import RagChunk, RagDocument, RagEmbedding, RagIngestionJob, RagSource
from app.rag.ingestion.chunker import Chunk, chunk_text
from app.rag.ingestion.embedder import embed_batch, embedding_model_name
from app.rag.ingestion.fetcher import FetchResult, detect_source_type, fetch_url
from app.rag.ingestion.parser import ParseResult, parse

log = logging.getLogger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_base_metadata(source: RagSource, doc_hash: str, title: Optional[str]) -> dict:
    author = source.author
    return {
        "author": author.name if author else "unknown",
        "author_id": source.author_id,
        "work_title": title or "",
        "source_url": source.url or "",
        "published_at": None,  # caller can override per-document
        "source_type": source.source_type,
        "topic_tags": [],
        "concept_tags": [],
        "cleanliness_score": 1.0,
        "doc_hash": doc_hash,
    }


def _persist_document_and_chunks(
    db: Session,
    source: RagSource,
    parse_result: ParseResult,
    title: Optional[str] = None,
    published_at=None,
) -> tuple[RagDocument, list[RagChunk]]:
    """Create RagDocument + RagChunk rows; return both."""
    doc_hash = _sha256(parse_result.clean_text)

    doc = RagDocument(
        source_id=source.id,
        title=title,
        published_at=published_at,
        raw_text=parse_result.raw_text,
        clean_text=parse_result.clean_text,
    )
    db.add(doc)
    db.flush()  # populate doc.id

    base_meta = _build_base_metadata(source, doc_hash, title)
    raw_chunks: list[Chunk] = chunk_text(parse_result.clean_text, base_metadata=base_meta)

    orm_chunks: list[RagChunk] = []
    for rc in raw_chunks:
        orm_chunk = RagChunk(
            document_id=doc.id,
            chunk_index=rc.index,
            text=rc.text,
            token_count=rc.token_count,
            metadata_json=rc.metadata_json,
        )
        db.add(orm_chunk)
        orm_chunks.append(orm_chunk)

    db.flush()  # populate chunk IDs
    return doc, orm_chunks


def _embed_and_persist(db: Session, chunks: list[RagChunk]) -> int:
    """Generate and persist embeddings for chunks. Returns count stored."""
    if not chunks:
        return 0

    texts = [c.text for c in chunks]
    vectors = embed_batch(texts)
    model_name = embedding_model_name()

    for chunk, vector in zip(chunks, vectors):
        emb = RagEmbedding(chunk_id=chunk.id, embedding=vector, model=model_name)
        db.add(emb)

    db.flush()
    return len(chunks)


def _open_job(db: Session, source: RagSource) -> RagIngestionJob:
    job = RagIngestionJob(
        source_id=source.id,
        status="running",
        started_at=_now(),
    )
    db.add(job)
    db.flush()
    return job


def _close_job(
    db: Session,
    job: RagIngestionJob,
    *,
    success: bool,
    stats: dict,
    error: Optional[str] = None,
) -> None:
    job.status = "done" if success else "failed"
    job.error = error
    job.stats_json = stats
    job.finished_at = _now()
    db.flush()


# ── Public pipeline entry points ──────────────────────────────────────────────


def run_url_ingestion(source: RagSource, db: Session) -> RagIngestionJob:
    """
    Fetch, parse, chunk, embed, and store content from source.url.

    On any error the job is marked 'failed' and the error message is stored.
    The caller is responsible for committing the session.
    """
    job = _open_job(db, source)
    source.status = "fetched"

    try:
        log.info("Fetching %s", source.url)
        fetch: FetchResult = fetch_url(source.url)

        # Update source hash for deduplication
        source.hash = fetch.sha256
        source.source_type = detect_source_type(fetch.content_type, source.url)

        log.info("Parsing %s (%s)", source.url, source.source_type)
        parsed: ParseResult = parse(fetch.raw_bytes, source.source_type)

        doc, chunks = _persist_document_and_chunks(db, source, parsed)
        n_emb = _embed_and_persist(db, chunks)

        source.status = "ingested"
        source.last_ingested_at = _now()

        _close_job(
            db,
            job,
            success=True,
            stats={
                "chunks": len(chunks),
                "embeddings": n_emb,
                "char_count": len(parsed.clean_text),
                "model": embedding_model_name(),
            },
        )
    except Exception as exc:
        log.exception("Ingestion failed for source %s", source.id)
        source.status = "failed"
        _close_job(db, job, success=False, stats={}, error=str(exc))

    return job


def run_manual_ingestion(
    source: RagSource,
    text: str,
    db: Session,
    *,
    title: Optional[str] = None,
    published_at=None,
) -> RagIngestionJob:
    """
    Ingest user-supplied text (paste or pre-extracted document content).

    The caller provides the clean text directly; no HTTP fetch is performed.
    source.source_type should be set to 'manual' or 'text' before calling.
    The caller is responsible for committing the session.
    """
    job = _open_job(db, source)

    try:
        source.hash = _sha256(text)
        source.status = "fetched"

        from app.rag.ingestion.parser import parse_text

        parsed = parse_text(text)

        doc, chunks = _persist_document_and_chunks(
            db, source, parsed, title=title, published_at=published_at
        )
        n_emb = _embed_and_persist(db, chunks)

        source.status = "ingested"
        source.last_ingested_at = _now()

        _close_job(
            db,
            job,
            success=True,
            stats={
                "chunks": len(chunks),
                "embeddings": n_emb,
                "char_count": len(parsed.clean_text),
                "model": embedding_model_name(),
            },
        )
    except Exception as exc:
        log.exception("Manual ingestion failed for source %s", source.id)
        source.status = "failed"
        _close_job(db, job, success=False, stats={}, error=str(exc))

    return job
