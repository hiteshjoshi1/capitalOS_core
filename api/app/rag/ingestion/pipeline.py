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

import httpx
from sqlalchemy.orm import Session

from app.models.rag import RagChunk, RagDocument, RagEmbedding, RagIngestionJob, RagSource
from app.rag.ingestion.events import record_source_event
from app.rag.ingestion.chunker import Chunk, DocumentSection as ChunkerSection, chunk_structured, chunk_text
from app.rag.ingestion.embedder import embed_batch, embedding_model_name
from app.rag.ingestion.fetcher import FetchResult, detect_source_type, fetch_url
from app.rag.ingestion.parser import DocumentSection, ParseResult, StructuredParseResult, parse

log = logging.getLogger(__name__)

FAILURE_NETWORK_ERROR = "network_error"
FAILURE_PARSE_FAILED = "parse_failed"
FAILURE_EMPTY_TEXT_EXTRACTION = "empty_text_extraction"
FAILURE_OCR_REQUIRED = "ocr_required"
FAILURE_MANUAL_REVIEW_REQUIRED = "manual_review_required"


class EmptyTextExtractionError(RuntimeError):
    pass


class OcrRequiredError(RuntimeError):
    pass


# ── Internal helpers ──────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_base_metadata(source: RagSource, doc_hash: str, title: Optional[str], doc_metadata: Optional[dict] = None) -> dict:
    author = source.author
    base = {
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
    if doc_metadata:
        # Merge document-level metadata from PDF/HTML properties
        if "title" in doc_metadata and not base["work_title"]:
            base["work_title"] = doc_metadata["title"]
        if "author" in doc_metadata and base["author"] == "unknown":
            base["author"] = doc_metadata["author"]
        for key in ("subject", "creation_date"):
            if key in doc_metadata:
                base[key] = doc_metadata[key]
    return base


def _parser_sections_to_chunker(parser_sections: list) -> list[ChunkerSection]:
    """Convert parser DocumentSection objects to chunker DocumentSection format."""
    result: list[ChunkerSection] = []
    for s in parser_sections:
        # Use table_markdown as content for tables (more readable than raw text)
        content = (
            s.table_markdown
            if s.content_type == "table" and s.table_markdown
            else s.content
        )
        if not content:
            continue
        result.append(
            ChunkerSection(
                heading=s.heading or "",
                content=content,
                is_table=(s.content_type == "table"),
                is_list=(s.content_type == "list"),
            )
        )
    return result


def _persist_document_and_chunks(
    db: Session,
    source: RagSource,
    parse_result: ParseResult,
    title: Optional[str] = None,
    published_at=None,
) -> tuple[RagDocument, list[RagChunk]]:
    """Create RagDocument + RagChunk rows; return both."""
    doc_hash = _sha256(parse_result.clean_text)

    # Extract doc_metadata when available (StructuredParseResult)
    doc_metadata: Optional[dict] = getattr(parse_result, "doc_metadata", None)

    doc = RagDocument(
        source_id=source.id,
        title=title,
        published_at=published_at,
        raw_text=parse_result.raw_text,
        clean_text=parse_result.clean_text,
    )
    db.add(doc)
    db.flush()  # populate doc.id

    base_meta = _build_base_metadata(source, doc_hash, title, doc_metadata)

    # Use section-aware chunking when structured sections are available
    parser_sections = getattr(parse_result, "sections", None)
    if parser_sections:
        chunker_sections = _parser_sections_to_chunker(parser_sections)
        if chunker_sections:
            raw_chunks: list[Chunk] = chunk_structured(chunker_sections, base_metadata=base_meta)
        else:
            raw_chunks = chunk_text(parse_result.clean_text, base_metadata=base_meta)
    else:
        raw_chunks = chunk_text(parse_result.clean_text, base_metadata=base_meta)

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


def _classify_failure(exc: Exception, source_type: Optional[str]) -> str:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError)):
        return FAILURE_NETWORK_ERROR
    if isinstance(exc, ValueError) and "HTTP " in str(exc):
        return FAILURE_NETWORK_ERROR
    if isinstance(exc, OcrRequiredError):
        return FAILURE_OCR_REQUIRED
    if isinstance(exc, EmptyTextExtractionError):
        return FAILURE_EMPTY_TEXT_EXTRACTION
    if isinstance(exc, (RuntimeError, UnicodeDecodeError)):
        return FAILURE_PARSE_FAILED
    return FAILURE_MANUAL_REVIEW_REQUIRED


def _ensure_clean_text(parsed: ParseResult, source_type: str) -> None:
    if parsed.clean_text.strip():
        return
    if source_type == "pdf":
        raise OcrRequiredError("PDF text extraction produced no usable text; OCR is required")
    raise EmptyTextExtractionError("Text extraction produced no usable text")


def _open_job(db: Session, source: RagSource) -> RagIngestionJob:
    job = RagIngestionJob(
        user_id=source.user_id,
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
    failure_category: Optional[str] = None,
) -> None:
    job.status = "done" if success else "failed"
    job.error = error
    job.failure_category = failure_category
    job.stats_json = stats
    job.finished_at = _now()
    db.flush()


# ── Public pipeline entry points ──────────────────────────────────────────────


def run_url_ingestion(
    source: RagSource,
    db: Session,
    *,
    existing_job: Optional["RagIngestionJob"] = None,
    batch_id: str | None = None,
) -> RagIngestionJob:
    """
    Fetch, parse, chunk, embed, and store content from source.url.

    If *existing_job* is provided (e.g. a pre-created "queued" job from a
    background-ingestion flow), it is reused and transitioned to "running"
    instead of creating a second job row.

    On any error the job is marked 'failed' and the error message is stored.
    The caller is responsible for committing the session.
    """
    if existing_job is not None:
        from datetime import datetime, timezone
        job = existing_job
        job.user_id = source.user_id
        job.batch_id = batch_id or job.batch_id
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db.flush()
    else:
        job = _open_job(db, source)
        job.batch_id = batch_id
    source.status = "running"
    db.flush()

    if source.user_id is not None:
        record_source_event(
            db,
            user_id=source.user_id,
            source=source,
            job=job,
            event_name="source_running",
            status="running",
            batch_id=batch_id,
        )

    try:
        log.info("Fetching %s", source.url)
        fetch: FetchResult = fetch_url(source.url)

        # Update source hash for deduplication
        source.hash = fetch.sha256
        source.source_type = detect_source_type(fetch.content_type, source.url)

        log.info("Parsing %s (%s)", source.url, source.source_type)
        parsed: ParseResult = parse(fetch.raw_bytes, source.source_type)
        _ensure_clean_text(parsed, source.source_type)

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
        if source.user_id is not None:
            record_source_event(
                db,
                user_id=source.user_id,
                source=source,
                job=job,
                event_name="source_ingested",
                status="ingested",
                batch_id=batch_id,
            )
    except Exception as exc:
        log.exception("Ingestion failed for source %s", source.id)
        source.status = "failed"
        _close_job(
            db,
            job,
            success=False,
            stats={},
            error=str(exc),
            failure_category=_classify_failure(exc, source.source_type),
        )
        if source.user_id is not None:
            record_source_event(
                db,
                user_id=source.user_id,
                source=source,
                job=job,
                event_name="source_failed",
                status="failed",
                batch_id=batch_id,
            )

    return job


def bulk_ingest_author(
    author_id: str,
    db: Session,
    *,
    current_user_id: int | None = None,
    statuses: tuple[str, ...] = ("pending", "failed"),
) -> list[RagIngestionJob]:
    """
    Ingest all sources with a matching status for the given author.

    Only processes sources with a URL (url-based ingestion).
    Sources without a URL are skipped.

    Returns a list of RagIngestionJob (one per processed source).
    The caller is responsible for committing the session.
    """
    from sqlalchemy import and_

    sources = (
        db.query(RagSource)
        .filter(
            and_(
                RagSource.author_id == author_id,
                *(() if current_user_id is None else (RagSource.user_id == current_user_id,)),
                RagSource.status.in_(statuses),
                RagSource.url.isnot(None),
            )
        )
        .all()
    )

    jobs: list[RagIngestionJob] = []
    for source in sources:
        log.info("Bulk ingesting source %s (%s) for author %s", source.id, source.url, author_id)
        job = run_url_ingestion(source, db)
        jobs.append(job)

    return jobs


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
    source.status = "running"

    try:
        source.hash = _sha256(text)

        from app.rag.ingestion.parser import parse_text

        parsed = parse_text(text)
        _ensure_clean_text(parsed, source.source_type)

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
        _close_job(
            db,
            job,
            success=False,
            stats={},
            error=str(exc),
            failure_category=_classify_failure(exc, source.source_type),
        )

    return job
