"""
RAG API router — Phase 1: ingestion foundation.

Endpoints:
  Catalog / config
    GET  /rag/authors
    POST /rag/authors/sync-config
    GET  /rag/sources
    POST /rag/sources

  Ingestion
    POST /rag/ingest/url
    POST /rag/ingest/manual
    POST /rag/ingest/retry/{source_id}
    GET  /rag/ingest/jobs
    GET  /rag/documents/{document_id}

  Retrieval smoke
    POST /rag/retrieve-smoke
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.rag import RagAuthor, RagDocument, RagIngestionJob, RagSource
from app.rag.config import sync_authors_from_config
from app.rag.ingestion.pipeline import run_manual_ingestion, run_url_ingestion
from app.rag.retrieval import retrieve_similar_chunks

log = logging.getLogger(__name__)
router = APIRouter(prefix="/rag", tags=["rag"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class AuthorOut(BaseModel):
    id: str
    name: str
    enabled: bool
    domains: list[str]
    expertise_tags: list[str]
    overall_weight: float
    role_type: Optional[str]

    model_config = {"from_attributes": True}


class SyncConfigOut(BaseModel):
    authors_created: int
    authors_updated: int
    total: int


class SourceOut(BaseModel):
    id: str
    author_id: str
    url: Optional[str]
    source_type: str
    status: str
    hash: Optional[str]
    last_ingested_at: Optional[Any]
    created_at: Any

    model_config = {"from_attributes": True}


class RegisterSourceIn(BaseModel):
    author_id: str
    url: Optional[str] = None
    source_type: str = Field(..., pattern="^(html|pdf|text|manual)$")


class IngestUrlIn(BaseModel):
    source_id: str


class IngestManualIn(BaseModel):
    author_id: str
    text: str
    title: Optional[str] = None
    published_at: Optional[str] = None  # YYYY-MM-DD
    source_type: str = "manual"


class JobOut(BaseModel):
    id: str
    source_id: str
    status: str
    failure_category: Optional[str]
    error: Optional[str]
    stats_json: dict
    started_at: Optional[Any]
    finished_at: Optional[Any]
    created_at: Any

    model_config = {"from_attributes": True}


class RetrieveSmokeIn(BaseModel):
    query: str
    top_k: int = 5
    author_id: Optional[str] = None
    source_type: Optional[str] = None


class RetrieveSmokeOut(BaseModel):
    query: str
    results: list[dict]


# ── Catalog / config ──────────────────────────────────────────────────────────


@router.get("/authors", response_model=list[AuthorOut])
def list_authors(
    enabled_only: bool = Query(False, description="Filter to enabled authors only"),
    db: Session = Depends(get_db),
):
    """Return all authors in the registry."""
    q = db.query(RagAuthor)
    if enabled_only:
        q = q.filter(RagAuthor.enabled == True)  # noqa: E712
    return q.order_by(RagAuthor.name).all()


@router.post("/authors/sync-config", response_model=SyncConfigOut)
def sync_authors(db: Session = Depends(get_db)):
    """
    Upsert authors from config/rag_authors.yaml into the database.
    Safe to call repeatedly — idempotent per author id.
    """
    try:
        result = sync_authors_from_config(db)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return result


@router.get("/sources", response_model=list[SourceOut])
def list_sources(
    author_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Return registered sources, optionally filtered by author or status."""
    q = db.query(RagSource)
    if author_id:
        q = q.filter(RagSource.author_id == author_id)
    if status:
        q = q.filter(RagSource.status == status)
    sources = q.order_by(RagSource.created_at.desc()).all()
    return [
        SourceOut(
            id=str(s.id),
            author_id=s.author_id,
            url=s.url,
            source_type=s.source_type,
            status=s.status,
            hash=s.hash,
            last_ingested_at=s.last_ingested_at,
            created_at=s.created_at,
        )
        for s in sources
    ]


@router.post("/sources", response_model=SourceOut, status_code=201)
def register_source(body: RegisterSourceIn, db: Session = Depends(get_db)):
    """Register a new source URL for an author (does not trigger ingestion)."""
    author = db.get(RagAuthor, body.author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{body.author_id}' not found. Run sync-config first.")

    source = RagSource(
        author_id=body.author_id,
        url=body.url,
        source_type=body.source_type,
        status="pending",
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return SourceOut(
        id=str(source.id),
        author_id=source.author_id,
        url=source.url,
        source_type=source.source_type,
        status=source.status,
        hash=source.hash,
        last_ingested_at=source.last_ingested_at,
        created_at=source.created_at,
    )


# ── Ingestion ─────────────────────────────────────────────────────────────────


def _get_source_or_404(source_id: str, db: Session) -> RagSource:
    # Validate UUID format
    try:
        uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid source_id UUID format")
    source = db.get(RagSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return source


@router.post("/ingest/url", response_model=JobOut, status_code=202)
def ingest_url(body: IngestUrlIn, db: Session = Depends(get_db)):
    """
    Trigger URL ingestion for a registered source.

    The pipeline fetches, parses, chunks, embeds, and persists the content.
    If the URL cannot be fetched, use POST /rag/ingest/manual instead.
    """
    source = _get_source_or_404(body.source_id, db)
    if not source.url:
        raise HTTPException(status_code=422, detail="Source has no URL. Use POST /rag/ingest/manual.")

    job = run_url_ingestion(source, db)
    db.commit()
    return _job_out(job)


@router.post("/ingest/manual", response_model=JobOut, status_code=202)
def ingest_manual(body: IngestManualIn, db: Session = Depends(get_db)):
    """
    Ingest manually supplied text for an author.

    Use this when:
    - The URL cannot be automatically fetched (paywall, JS-rendered, PDF download restriction).
    - You are uploading pre-extracted text from a PDF or Word document.
    - You are pasting cleaned text from any source.

    A new source row is created automatically (source_type = manual).
    """
    author = db.get(RagAuthor, body.author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{body.author_id}' not found. Run sync-config first.")

    source = RagSource(
        author_id=body.author_id,
        url=None,
        source_type=body.source_type,
        status="pending",
    )
    db.add(source)
    db.flush()

    published_at = None
    if body.published_at:
        from datetime import date

        try:
            published_at = date.fromisoformat(body.published_at)
        except ValueError:
            raise HTTPException(status_code=422, detail="published_at must be YYYY-MM-DD")

    job = run_manual_ingestion(
        source,
        body.text,
        db,
        title=body.title,
        published_at=published_at,
    )
    db.commit()
    return _job_out(job)


@router.post("/ingest/manual/upload", response_model=JobOut, status_code=202)
async def ingest_manual_upload(
    author_id: str = Form(...),
    title: Optional[str] = Form(None),
    published_at: Optional[str] = Form(None),
    file: UploadFile = File(..., description="Plain text (.txt) or pre-extracted PDF text file"),
    db: Session = Depends(get_db),
):
    """
    Upload a text file for manual ingestion.

    Accepts .txt files or any file whose content is plain text.
    For PDF files, extract the text first (e.g. using pdftotext) then upload
    the resulting .txt file, or use POST /rag/ingest/url with a direct PDF URL.
    """
    author = db.get(RagAuthor, author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{author_id}' not found.")

    raw = await file.read()
    try:
        text = raw.decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not decode file: {exc}")

    source = RagSource(
        author_id=author_id,
        url=None,
        source_type="manual",
        status="pending",
    )
    db.add(source)
    db.flush()

    from datetime import date as _date

    pa = None
    if published_at:
        try:
            pa = _date.fromisoformat(published_at)
        except ValueError:
            raise HTTPException(status_code=422, detail="published_at must be YYYY-MM-DD")

    job = run_manual_ingestion(source, text, db, title=title or file.filename, published_at=pa)
    db.commit()
    return _job_out(job)


@router.post("/ingest/retry/{source_id}", response_model=JobOut, status_code=202)
def retry_ingestion(source_id: str, db: Session = Depends(get_db)):
    """Re-run ingestion for a previously failed source."""
    source = _get_source_or_404(source_id, db)
    if not source.url:
        raise HTTPException(
            status_code=422,
            detail="Source has no URL; cannot retry URL ingestion. Use POST /rag/ingest/manual.",
        )
    source.status = "pending"
    job = run_url_ingestion(source, db)
    db.commit()
    return _job_out(job)


@router.get("/ingest/jobs", response_model=list[JobOut])
def list_jobs(
    source_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List ingestion jobs, optionally filtered by source or status."""
    q = db.query(RagIngestionJob)
    if source_id:
        try:
            uuid.UUID(source_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid source_id UUID")
        q = q.filter(RagIngestionJob.source_id == source_id)
    if status:
        q = q.filter(RagIngestionJob.status == status)
    jobs = q.order_by(RagIngestionJob.created_at.desc()).limit(limit).all()
    return [_job_out(j) for j in jobs]


@router.get("/documents/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    """Return document metadata and chunk count for a given document ID."""
    try:
        uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid document_id UUID")
    doc = db.get(RagDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    return {
        "id": str(doc.id),
        "source_id": str(doc.source_id),
        "title": doc.title,
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "char_count": len(doc.clean_text or ""),
        "chunk_count": len(doc.chunks),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


# ── Retrieval smoke ───────────────────────────────────────────────────────────


@router.post("/retrieve-smoke", response_model=RetrieveSmokeOut)
def retrieve_smoke(body: RetrieveSmokeIn, db: Session = Depends(get_db)):
    """
    Semantic retrieval smoke test.

    Embeds the query and returns the top-k most similar stored chunks with
    full citation-ready metadata.  Confirms that:
    - The corpus was embedded and stored correctly.
    - Vector similarity search returns relevant results.
    - Metadata lineage is intact.

    This is not a full answer-generation endpoint.
    """
    results = retrieve_similar_chunks(
        body.query,
        db,
        top_k=body.top_k,
        author_id=body.author_id,
        source_type=body.source_type,
    )
    return RetrieveSmokeOut(
        query=body.query,
        results=[r.as_dict() for r in results],
    )


# ── Private helpers ───────────────────────────────────────────────────────────


def _job_out(job: RagIngestionJob) -> JobOut:
    return JobOut(
        id=str(job.id),
        source_id=str(job.source_id),
        status=job.status,
        failure_category=job.failure_category,
        error=job.error,
        stats_json=job.stats_json or {},
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )
