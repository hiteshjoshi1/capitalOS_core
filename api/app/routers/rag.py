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
import threading
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth_context import CurrentUser, require_current_user
from app.db.session import SessionLocal, get_db
from app.models.rag import RagAuthor, RagDocument, RagIngestionJob, RagSource, RealtimeEvent
from app.rag.config import load_author_config, sync_authors_from_config
from app.rag.discovery import discover_sources_for_author
from app.rag.ingestion.events import (
    AUTHOR_INGESTION_TOPIC,
    publish_event,
    record_batch_event,
    record_source_event,
    serialize_event,
    serialize_job,
    serialize_source,
)
from app.rag.ingestion.pipeline import bulk_ingest_author, run_manual_ingestion, run_url_ingestion
from app.rag.ingestion.selector import SelectiveIngestionOptions
from app.rag.retrieval import retrieve_similar_chunks, retrieve_with_constraints

log = logging.getLogger(__name__)
router = APIRouter(prefix="/rag", tags=["rag"], dependencies=[Depends(require_current_user)])


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
    author_name: Optional[str] = None
    url: Optional[str]
    source_type: str
    status: str
    hash: Optional[str]
    selective_options: Optional[dict] = None
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
    batch_id: Optional[str] = None
    status: str
    failure_category: Optional[str]
    error: Optional[str]
    stats_json: dict
    started_at: Optional[Any]
    finished_at: Optional[Any]
    created_at: Any

    model_config = {"from_attributes": True}


class CreateAuthorIn(BaseModel):
    id: str = Field(..., pattern="^[a-z0-9_-]+$", description="Unique slug for the author")
    name: str = Field(..., min_length=1)
    enabled: bool = True
    # Optional advanced fields
    domains: list[str] = Field(default_factory=list)
    expertise_tags: list[str] = Field(default_factory=list)
    overall_weight: float = Field(1.0, ge=0.0)
    role_type: Optional[str] = None


class SelectiveIngestionOptionsIn(BaseModel):
    """Optional selective-ingestion controls for HTML/text sources.

    All fields are optional.  When omitted the full source is ingested.

    - start_after:      Begin ingestion only after the first heading that
                        contains this string (case-insensitive substring match).
    - stop_before:      Stop ingesting when a heading matches this string.
    - include_headings: Include only sections whose heading matches any entry.
    - exclude_sections: Drop sections whose heading matches any entry.
    """

    start_after: Optional[str] = None
    stop_before: Optional[str] = None
    include_headings: list[str] = Field(default_factory=list)
    exclude_sections: list[str] = Field(default_factory=list)

    def to_selector_options(self) -> SelectiveIngestionOptions:
        return SelectiveIngestionOptions(
            start_after=self.start_after,
            stop_before=self.stop_before,
            include_headings=self.include_headings,
            exclude_sections=self.exclude_sections,
        )


class IngestUrlsBatchIn(BaseModel):
    urls: list[str] = Field(..., min_length=1, description="One or more URLs to register and ingest")
    source_type: str = Field("html", pattern="^(html|pdf|text)$")
    selective_ingestion: Optional[SelectiveIngestionOptionsIn] = Field(
        None,
        description="Optional selective-ingestion controls. Hidden by default in the UI.",
    )


class IngestUrlsBatchOut(BaseModel):
    author_id: str
    registered: int
    requeued_existing: int = 0
    skipped_duplicate: int
    jobs_queued: int
    sources: list[SourceOut]
    job_ids: list[str]


class RetrieveSmokeIn(BaseModel):
    query: str
    top_k: int = 5
    author_id: Optional[str] = None
    source_type: Optional[str] = None


class RetrieveSmokeOut(BaseModel):
    query: str
    results: list[dict]


class DiscoveryResultOut(BaseModel):
    seed_url: str
    discovered_count: int
    registered: int
    skipped_duplicate: int
    errors: list[str]


class DiscoverAuthorOut(BaseModel):
    author_id: str
    seeds_processed: int
    total_discovered: int
    total_registered: int
    total_skipped_duplicate: int
    results: list[DiscoveryResultOut]


class BulkIngestOut(BaseModel):
    author_id: str
    sources_processed: int
    jobs: list[JobOut]


class RealtimeEventOut(BaseModel):
    id: str
    topic: str
    event_name: str
    batch_id: Optional[str]
    author_id: Optional[str]
    source_id: Optional[str]
    job_id: Optional[str]
    status: Optional[str]
    created_at: Optional[str]
    payload: dict[str, Any]


class IngestionActivityOut(BaseModel):
    topic: str = AUTHOR_INGESTION_TOPIC
    sources: list[SourceOut]
    jobs: list[JobOut]
    events: list[RealtimeEventOut]


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


@router.post("/authors", response_model=AuthorOut, status_code=201)
def create_author(body: CreateAuthorIn, db: Session = Depends(get_db)):
    """
    Create a new author from the UI without editing config files.

    Required: id (slug), name, enabled.
    Optional advanced: domains, expertise_tags, overall_weight, role_type.
    Returns 409 if the author id already exists.
    """
    existing = db.get(RagAuthor, body.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Author '{body.id}' already exists.")

    author = RagAuthor(
        id=body.id,
        name=body.name,
        enabled=body.enabled,
        domains=body.domains,
        expertise_tags=body.expertise_tags,
        overall_weight=body.overall_weight,
        role_type=body.role_type,
        config_source="ui",
    )
    db.add(author)
    db.commit()
    db.refresh(author)
    return author


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
    current_user: CurrentUser = Depends(require_current_user),
):
    """Return registered sources, optionally filtered by author or status."""
    q = db.query(RagSource).filter(RagSource.user_id == current_user.id)
    if author_id:
        q = q.filter(RagSource.author_id == author_id)
    if status:
        q = q.filter(RagSource.status == status)
    sources = q.order_by(RagSource.created_at.desc()).all()
    return [
        SourceOut(
            id=str(s.id),
            author_id=s.author_id,
            author_name=s.author.name if s.author else None,
            url=s.url,
            source_type=s.source_type,
            status=s.status,
            hash=s.hash,
            selective_options=s.selective_options or None,
            last_ingested_at=s.last_ingested_at,
            created_at=s.created_at,
        )
        for s in sources
    ]


@router.post("/sources", response_model=SourceOut, status_code=201)
def register_source(
    body: RegisterSourceIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Register a new source URL for an author (does not trigger ingestion)."""
    author = db.get(RagAuthor, body.author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{body.author_id}' not found. Run sync-config first.")

    source = RagSource(
        user_id=current_user.id,
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
        author_name=source.author.name if source.author else None,
        url=source.url,
        source_type=source.source_type,
        status=source.status,
        hash=source.hash,
        selective_options=source.selective_options or None,
        last_ingested_at=source.last_ingested_at,
        created_at=source.created_at,
    )


# ── Ingestion ─────────────────────────────────────────────────────────────────


def _get_source_or_404(source_id: str, db: Session, current_user: CurrentUser) -> RagSource:
    # Validate UUID format
    try:
        uuid.UUID(source_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid source_id UUID format")
    source = db.get(RagSource, source_id)
    if not source or source.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return source


@router.post("/authors/{author_id}/ingest-urls", response_model=IngestUrlsBatchOut, status_code=202)
def ingest_urls_for_author(
    author_id: str,
    body: IngestUrlsBatchIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """
    Register one or more URLs for an author and kick off background ingestion.

    - Registers new URLs with queued ingestion jobs.
    - Re-queues existing URLs that are not already queued/running, updating
      their persisted selective-ingestion rules to the latest submitted values.
    - Skips URLs already queued/running to avoid duplicate in-flight jobs.
    - Spawns a background thread that processes URLs one at a time (explicit in logs).
    - Returns immediately with job IDs and source records for client polling.
    """
    author = db.get(RagAuthor, author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{author_id}' not found.")

    existing_sources_by_url: dict[str, RagSource] = {
        s.url: s for s in db.query(RagSource).filter(
            RagSource.user_id == current_user.id,
            RagSource.author_id == author_id,
            RagSource.url.isnot(None),
        ).all()
        if s.url
    }

    new_sources: list[RagSource] = []
    requeued_sources: list[RagSource] = []
    skipped = 0
    batch_id = str(uuid.uuid4())
    selective_opts_dict = body.selective_ingestion.to_selector_options().to_dict() if body.selective_ingestion else None
    for url in body.urls:
        url = url.strip()
        if not url:
            continue
        existing = existing_sources_by_url.get(url)
        if existing is not None:
            if existing.status in {"queued", "running"}:
                skipped += 1
                continue
            existing.source_type = body.source_type
            existing.status = "queued"
            existing.selective_options = selective_opts_dict
            requeued_sources.append(existing)
            continue
        source = RagSource(
            user_id=current_user.id,
            author_id=author_id,
            url=url,
            source_type=body.source_type,
            status="queued",
            selective_options=selective_opts_dict,
        )
        db.add(source)
        existing_sources_by_url[url] = source
        new_sources.append(source)

    db.flush()

    # Create queued job rows so clients can poll status immediately
    queued_sources = [*new_sources, *requeued_sources]
    queued_jobs: list[RagIngestionJob] = []
    queued_events: list[RealtimeEvent] = []
    for source in queued_sources:
        job = RagIngestionJob(
            user_id=current_user.id,
            source_id=source.id,
            batch_id=batch_id,
            status="queued",
        )
        db.add(job)
        queued_jobs.append(job)
        db.flush()
        queued_events.append(
            record_source_event(
                db,
                user_id=current_user.id,
                source=source,
                job=job,
                event_name="source_queued",
                status="queued",
                batch_id=batch_id,
            )
        )

    batch_submitted_event: RealtimeEvent | None = None
    if queued_sources:
        batch_submitted_event = record_batch_event(
            db,
            user_id=current_user.id,
            author=author,
            batch_id=batch_id,
            event_name="batch_submitted",
            status="submitted",
            source_count=len(queued_sources),
        )

    db.commit()
    for source in queued_sources:
        db.refresh(source)
    for job in queued_jobs:
        db.refresh(job)

    if batch_submitted_event is not None:
        publish_event(batch_submitted_event)
    for queued_event in queued_events:
        publish_event(queued_event)

    source_ids = [str(s.id) for s in queued_sources]
    job_ids = [str(j.id) for j in queued_jobs]

    if source_ids:
        thread = threading.Thread(
            target=_run_background_ingestion,
            args=(source_ids, batch_id, author_id, current_user.id),
            daemon=True,
            name=f"rag-ingest-{author_id}",
        )
        thread.start()
        log.info(
            "Background ingestion thread started: author=%s sources=%d",
            author_id,
            len(source_ids),
        )

    source_outs = [
        SourceOut(
            id=str(s.id),
            author_id=s.author_id,
            author_name=s.author.name if s.author else None,
            url=s.url,
            source_type=s.source_type,
            status=s.status,
            hash=s.hash,
            selective_options=s.selective_options or None,
            last_ingested_at=s.last_ingested_at,
            created_at=s.created_at,
        )
        for s in queued_sources
    ]

    return IngestUrlsBatchOut(
        author_id=author_id,
        registered=len(new_sources),
        requeued_existing=len(requeued_sources),
        skipped_duplicate=skipped,
        jobs_queued=len(queued_jobs),
        sources=source_outs,
        job_ids=job_ids,
    )


def _run_background_ingestion(
    source_ids: list[str],
    batch_id: str | None,
    author_id: str | None,
    user_id: int,
) -> None:
    """
    Background worker: ingest one source at a time using a fresh DB session.

    Each source is processed in sequence with explicit log entries.
    Uses its own SessionLocal to avoid reusing the request-scoped session.
    """
    for source_id in source_ids:
        db = SessionLocal()
        try:
            source = db.get(RagSource, source_id)
            if not source or source.user_id != user_id or not source.url:
                log.warning("Background ingestion: source %s not found or has no URL, skipping", source_id)
                continue

            log.info(
                "Background ingestion starting: source_id=%s url=%s author=%s",
                source_id,
                source.url,
                source.author_id,
            )

            # Transition any queued job to running; reuse it in run_url_ingestion
            # to avoid creating a duplicate job row.
            queued_job = (
                db.query(RagIngestionJob)
                .filter(
                    RagIngestionJob.source_id == source_id,
                    RagIngestionJob.status == "queued",
                )
                .order_by(RagIngestionJob.created_at.desc())
                .first()
            )

            job = run_url_ingestion(source, db, existing_job=queued_job, batch_id=batch_id)
            db.commit()
            if source.user_id is not None:
                events = (
                    db.query(RealtimeEvent)
                    .filter(
                        RealtimeEvent.user_id == source.user_id,
                        RealtimeEvent.source_id == source.id,
                        RealtimeEvent.job_id == job.id,
                        RealtimeEvent.event_name.in_(["source_running", "source_ingested", "source_failed"]),
                    )
                    .order_by(RealtimeEvent.created_at.asc())
                    .all()
                )
                for event in events:
                    publish_event(event)

            log.info(
                "Background ingestion complete: source_id=%s status=%s job=%s",
                source_id,
                source.status,
                job.id,
            )
        except Exception:
            log.exception("Background ingestion error for source %s", source_id)
            try:
                db.rollback()
            except Exception:
                pass
        finally:
            db.close()

    if batch_id and author_id:
        db = SessionLocal()
        try:
            author = db.get(RagAuthor, author_id)
            if author is None:
                return
            jobs = (
                db.query(RagIngestionJob)
                .filter(
                    RagIngestionJob.user_id == user_id,
                    RagIngestionJob.batch_id == batch_id,
                )
                .all()
            )
            completed_jobs = [job for job in jobs if job.status in {"done", "failed"}]
            failed_jobs = [job for job in completed_jobs if job.status == "failed"]
            event = record_batch_event(
                db,
                user_id=user_id,
                author=author,
                batch_id=batch_id,
                event_name="batch_completed",
                status="completed",
                source_count=len(jobs),
                completed_source_count=len(completed_jobs),
                failed_source_count=len(failed_jobs),
            )
            db.commit()
            publish_event(event)
        finally:
            db.close()


@router.post("/ingest/url", response_model=JobOut, status_code=202)
def ingest_url(
    body: IngestUrlIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """
    Trigger URL ingestion for a registered source.

    The pipeline fetches, parses, chunks, embeds, and persists the content.
    If the URL cannot be fetched, use POST /rag/ingest/manual instead.
    """
    source = _get_source_or_404(body.source_id, db, current_user)
    if not source.url:
        raise HTTPException(status_code=422, detail="Source has no URL. Use POST /rag/ingest/manual.")

    job = run_url_ingestion(source, db)
    db.commit()
    return _job_out(job)


@router.post("/ingest/manual", response_model=JobOut, status_code=202)
def ingest_manual(
    body: IngestManualIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
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
        user_id=current_user.id,
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
    current_user: CurrentUser = Depends(require_current_user),
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
        user_id=current_user.id,
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
def retry_ingestion(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Re-run ingestion asynchronously for a previously failed or stalled source."""
    source = _get_source_or_404(source_id, db, current_user)
    if not source.url:
        raise HTTPException(
            status_code=422,
            detail="Source has no URL; cannot retry URL ingestion. Use POST /rag/ingest/manual.",
        )
    source.status = "queued"
    batch_id = str(uuid.uuid4())

    job = RagIngestionJob(
        user_id=current_user.id,
        source_id=source.id,
        batch_id=batch_id,
        status="queued",
    )
    db.add(job)
    db.flush()
    batch_event = record_batch_event(
        db,
        user_id=current_user.id,
        author=source.author,
        batch_id=batch_id,
        event_name="batch_submitted",
        status="submitted",
        source_count=1,
    )
    queued_event = record_source_event(
        db,
        user_id=current_user.id,
        source=source,
        job=job,
        event_name="source_queued",
        status="queued",
        batch_id=batch_id,
    )
    db.commit()
    db.refresh(job)
    publish_event(batch_event)
    publish_event(queued_event)

    thread = threading.Thread(
        target=_run_background_ingestion,
        args=([str(source.id)], batch_id, source.author_id, current_user.id),
        daemon=True,
        name=f"rag-retry-{source_id}",
    )
    thread.start()
    log.info("Retry ingestion thread started: source_id=%s", source_id)

    return _job_out(job)


# ── Discovery ─────────────────────────────────────────────────────────────────


@router.post("/authors/{author_id}/discover", response_model=DiscoverAuthorOut, status_code=200)
def discover_author_sources(
    author_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """
    Discover child source URLs for an author from their config discovery_seeds.

    Reads the archive/index pages defined in config/rag_authors.yaml for the
    given author, extracts child links, deduplicates, applies prefer_type rules,
    and registers new sources in rag_sources (status=pending).

    Idempotent: already-registered URLs are skipped.
    Does not trigger ingestion — call POST /rag/authors/{author_id}/bulk-ingest
    after discovery to ingest all pending sources.
    """
    author = db.get(RagAuthor, author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{author_id}' not found. Run sync-config first.")

    try:
        config_data = load_author_config()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    author_cfgs = {a["id"]: a for a in config_data.get("authors", [])}
    author_cfg = author_cfgs.get(author_id, {})

    if not author_cfg.get("discovery_seeds"):
        return DiscoverAuthorOut(
            author_id=author_id,
            seeds_processed=0,
            total_discovered=0,
            total_registered=0,
            total_skipped_duplicate=0,
            results=[],
        )

    results = discover_sources_for_author(author_id, author_cfg, db, user_id=current_user.id)
    db.commit()

    result_outs = [
        DiscoveryResultOut(
            seed_url=r.seed_url,
            discovered_count=len(r.discovered),
            registered=r.registered,
            skipped_duplicate=r.skipped_duplicate,
            errors=r.errors,
        )
        for r in results
    ]

    return DiscoverAuthorOut(
        author_id=author_id,
        seeds_processed=len(results),
        total_discovered=sum(len(r.discovered) for r in results),
        total_registered=sum(r.registered for r in results),
        total_skipped_duplicate=sum(r.skipped_duplicate for r in results),
        results=result_outs,
    )


# ── Bulk ingestion ────────────────────────────────────────────────────────────


@router.post("/authors/{author_id}/bulk-ingest", response_model=BulkIngestOut, status_code=202)
def bulk_ingest_author_sources(
    author_id: str,
    statuses: str = Query("pending,failed", description="Comma-separated source statuses to ingest"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """
    Ingest all sources in pending or failed status for the given author.

    Runs URL-based ingestion for each matching source in sequence.
    Results (including failures) are recorded in rag_ingestion_jobs.

    Use ?statuses=pending,failed (default) to retry all unprocessed and failed sources.
    Use ?statuses=pending to ingest only freshly discovered sources.
    """
    author = db.get(RagAuthor, author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{author_id}' not found. Run sync-config first.")

    status_list = tuple(s.strip() for s in statuses.split(",") if s.strip())
    if not status_list:
        raise HTTPException(status_code=422, detail="statuses must be a non-empty comma-separated list")

    jobs = bulk_ingest_author(author_id, db, current_user_id=current_user.id, statuses=status_list)
    db.commit()

    return BulkIngestOut(
        author_id=author_id,
        sources_processed=len(jobs),
        jobs=[_job_out(j) for j in jobs],
    )


@router.get("/ingest/jobs", response_model=list[JobOut])
def list_jobs(
    source_id: Optional[str] = Query(None),
    author_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """List ingestion jobs, optionally filtered by source, author, or status."""
    q = db.query(RagIngestionJob).filter(RagIngestionJob.user_id == current_user.id)
    if source_id:
        try:
            uuid.UUID(source_id)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid source_id UUID")
        q = q.filter(RagIngestionJob.source_id == source_id)
    if author_id:
        q = q.join(RagSource, RagIngestionJob.source_id == RagSource.id).filter(
            RagSource.author_id == author_id
        )
    if status:
        q = q.filter(RagIngestionJob.status == status)
    jobs = q.order_by(RagIngestionJob.created_at.desc()).limit(limit).all()
    return [_job_out(j) for j in jobs]


@router.get("/ingest/activity", response_model=IngestionActivityOut)
def ingestion_activity(
    author_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    source_query = (
        db.query(RagSource)
        .filter(RagSource.user_id == current_user.id)
        .order_by(RagSource.created_at.desc())
    )
    if author_id:
        source_query = source_query.filter(RagSource.author_id == author_id)
    sources = source_query.limit(limit).all()

    job_query = (
        db.query(RagIngestionJob)
        .join(RagSource, RagIngestionJob.source_id == RagSource.id)
        .filter(RagIngestionJob.user_id == current_user.id)
        .order_by(RagIngestionJob.created_at.desc())
    )
    if author_id:
        job_query = job_query.filter(RagSource.author_id == author_id)
    jobs = job_query.limit(limit).all()

    event_query = (
        db.query(RealtimeEvent)
        .filter(
            RealtimeEvent.user_id == current_user.id,
            RealtimeEvent.topic == AUTHOR_INGESTION_TOPIC,
        )
        .order_by(RealtimeEvent.created_at.desc())
    )
    if author_id:
        event_query = event_query.filter(RealtimeEvent.author_id == author_id)
    events = event_query.limit(limit).all()

    return IngestionActivityOut(
        sources=[
            SourceOut(
                id=serialized["id"],
                author_id=serialized["author_id"],
                author_name=serialized["author_name"],
                url=serialized["url"],
                source_type=serialized["source_type"],
                status=serialized["status"],
                hash=serialized["hash"],
                selective_options=serialized.get("selective_options"),
                last_ingested_at=serialized["last_ingested_at"],
                created_at=serialized["created_at"],
            )
            for serialized in [serialize_source(source) for source in sources]
        ],
        jobs=[
            JobOut(
                id=serialized["id"],
                source_id=serialized["source_id"],
                batch_id=serialized["batch_id"],
                status=serialized["status"],
                failure_category=serialized["failure_category"],
                error=serialized["error"],
                stats_json=serialized["stats_json"],
                started_at=serialized["started_at"],
                finished_at=serialized["finished_at"],
                created_at=serialized["created_at"],
            )
            for serialized in [serialize_job(job) for job in jobs]
        ],
        events=[RealtimeEventOut(**serialize_event(event)) for event in events],
    )


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
        batch_id=str(job.batch_id) if job.batch_id else None,
        status=job.status,
        failure_category=job.failure_category,
        error=job.error,
        stats_json=job.stats_json or {},
        started_at=job.started_at,
        finished_at=job.finished_at,
        created_at=job.created_at,
    )


# ── Phase 2: Author wisdom profiles ───────────────────────────────────────────


class ProfileCitationOut(BaseModel):
    chunk_id: str
    citation_context: Optional[str]


class AuthorProfileOut(BaseModel):
    author_id: str
    author_name: str
    worldview: Optional[str]
    key_maxims: list[str]
    strengths: list[str]
    weaknesses: list[str]
    favored_decision_variables: list[str]
    anti_patterns: list[str]
    generation_model: str
    corpus_chunk_count: int
    generated_at: Optional[Any]
    citations: list[ProfileCitationOut]


class ProfileRefreshResultOut(BaseModel):
    author_id: str
    status: str
    chunk_count: Optional[int] = None
    error: Optional[str] = None


class RefreshProfilesOut(BaseModel):
    results: list[ProfileRefreshResultOut]
    total: int
    ok: int
    errors: int


@router.post("/authors/refresh-profiles", response_model=RefreshProfilesOut)
def refresh_profiles(db: Session = Depends(get_db)):
    """
    Generate or refresh author wisdom profiles for all enabled authors.

    Uses LLM synthesis when INFERENCE_LLM_PROVIDER / INFERENCE_LLM_API_KEY are configured; falls back to
    deterministic template synthesis otherwise.  Idempotent — safe to call
    repeatedly after new corpus ingestion.
    """
    from app.rag.wisdom import refresh_all_profiles

    results = refresh_all_profiles(db)
    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = len(results) - ok_count
    return RefreshProfilesOut(
        results=[ProfileRefreshResultOut(**r) for r in results],
        total=len(results),
        ok=ok_count,
        errors=err_count,
    )


@router.get("/authors/{author_id}/profile", response_model=AuthorProfileOut)
def get_author_profile(author_id: str, db: Session = Depends(get_db)):
    """
    Return the persisted wisdom profile for an author.

    Returns 404 if no profile has been generated yet.
    Run POST /rag/authors/refresh-profiles to generate profiles.
    """
    from app.models.rag import RagAuthorProfile

    author = db.get(RagAuthor, author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{author_id}' not found")

    profile = db.query(RagAuthorProfile).filter(RagAuthorProfile.author_id == author_id).first()
    if not profile:
        raise HTTPException(
            status_code=404,
            detail=f"No profile for '{author_id}'. Run POST /rag/authors/refresh-profiles first.",
        )

    citations = [
        ProfileCitationOut(chunk_id=str(c.chunk_id), citation_context=c.citation_context)
        for c in (profile.citations or [])
    ]

    return AuthorProfileOut(
        author_id=author_id,
        author_name=author.name,
        worldview=profile.worldview,
        key_maxims=list(profile.key_maxims or []),
        strengths=list(profile.strengths or []),
        weaknesses=list(profile.weaknesses or []),
        favored_decision_variables=list(profile.favored_decision_variables or []),
        anti_patterns=list(profile.anti_patterns or []),
        generation_model=profile.generation_model,
        corpus_chunk_count=profile.corpus_chunk_count,
        generated_at=profile.generated_at,
        citations=citations,
    )


# ── Phase 2: Full retrieval ────────────────────────────────────────────────────


class RetrieveIn(BaseModel):
    query: str
    top_k: int = 5
    author_id: Optional[str] = None
    author_ids: Optional[list[str]] = None
    source_type: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    published_from: Optional[str] = None   # YYYY-MM-DD
    published_to: Optional[str] = None     # YYYY-MM-DD
    strict_constraints: bool = True
    domains: Optional[list[str]] = None
    expertise_tags: Optional[list[str]] = None
    debug: bool = False


class RetrieveOut(BaseModel):
    query: str
    mode: str
    selected_authors: list[dict]
    evidence_chunks: list[dict]
    answer: Optional[str]
    missing_information: Optional[str]
    evidence_sufficient: bool
    # Constraint transparency fields (new in issue-145)
    constraints_requested: Optional[dict] = None
    constraints_applied: Optional[dict] = None
    constraints_relaxed: Optional[bool] = None
    constraint_relaxation_reason: Optional[str] = None
    diagnostics: Optional[dict] = None


@router.post("/retrieve", response_model=RetrieveOut)
def retrieve(body: RetrieveIn, db: Session = Depends(get_db)):
    """
    Semantic retrieval with author selection and citation-ready payloads.

    Performs dynamic author selection based on query relevance, then returns
    the top-k matching corpus chunks enriched with citation metadata.

    Constraint fields (author_ids, source_type, year_from, year_to,
    published_from, published_to) are strict by default: if the corpus
    returns zero results under the requested constraints the response
    returns an empty evidence list rather than silently broadening.

    Set strict_constraints=false to allow staged fallback.  Any relaxation
    is reported explicitly in constraints_relaxed / constraint_relaxation_reason.

    Set debug=true to include candidate count diagnostics.
    """
    # Check whether any explicit constraints were requested
    has_constraints = any([
        body.author_ids,
        body.source_type,
        body.year_from is not None,
        body.year_to is not None,
        body.published_from,
        body.published_to,
    ])

    if has_constraints:
        result = retrieve_with_constraints(
            body.query,
            db,
            top_k=body.top_k,
            author_id=body.author_id,
            author_ids=body.author_ids,
            source_type=body.source_type,
            year_from=body.year_from,
            year_to=body.year_to,
            published_from=body.published_from,
            published_to=body.published_to,
            domains=body.domains,
            expertise_tags=body.expertise_tags,
            strict_constraints=body.strict_constraints,
            debug=body.debug,
        )
        return {
            "query": body.query,
            "mode": "constrained_retrieve",
            "selected_authors": [],
            "evidence_chunks": [c.as_dict() for c in result.chunks],
            "answer": None,
            "missing_information": None if result.chunks else "No corpus evidence found matching the requested constraints.",
            "evidence_sufficient": len(result.chunks) > 0,
            "constraints_requested": result.constraints_requested,
            "constraints_applied": result.constraints_applied,
            "constraints_relaxed": result.constraints_relaxed,
            "constraint_relaxation_reason": result.constraint_relaxation_reason,
            "diagnostics": result.diagnostics,
        }

    # No constraints: use existing author-selection-based path
    from app.rag.query import execute_retrieve

    result_q = execute_retrieve(
        body.query,
        db,
        top_k=body.top_k,
        author_id=body.author_id,
        domains=body.domains,
        expertise_tags=body.expertise_tags,
    )
    out = result_q.as_dict()
    out.update({
        "constraints_requested": None,
        "constraints_applied": None,
        "constraints_relaxed": None,
        "constraint_relaxation_reason": None,
        "diagnostics": None,
    })
    return out


# ── Phase 2: Grounded query ────────────────────────────────────────────────────


class QueryIn(BaseModel):
    query: str
    top_k: int = 8
    author_id: Optional[str] = None
    domains: Optional[list[str]] = None
    expertise_tags: Optional[list[str]] = None


@router.post("/query", response_model=RetrieveOut)
def query_authors(body: QueryIn, db: Session = Depends(get_db)):
    """
    Author-aware grounded query.

    Dynamically selects relevant authors, retrieves corpus evidence, and
    synthesizes a grounded short answer. Uses LLM when INFERENCE_LLM_PROVIDER / INFERENCE_LLM_API_KEY are
    configured; returns an evidence summary otherwise.
    """
    from app.rag.query import execute_ask

    result = execute_ask(
        body.query,
        db,
        top_k=body.top_k,
        author_id=body.author_id,
        domains=body.domains,
        expertise_tags=body.expertise_tags,
    )
    return result.as_dict()


# ── Phase 2: Company context preparation ──────────────────────────────────────


class CompanyContextIn(BaseModel):
    company: str
    question: str
    top_k: int = 8


class CompanyContextOut(BaseModel):
    company: str
    question: str
    relevant_author_lenses: list[dict]
    evidence_pack: list[dict]
    evidence_sufficient: bool


@router.post("/analyze/company-context", response_model=CompanyContextOut)
def company_context(body: CompanyContextIn, db: Session = Depends(get_db)):
    """
    Prepare a company analysis context.

    Retrieves corpus evidence relevant to the company and question,
    returns the most relevant author lenses (with wisdom profile data
    if available), and structures an evidence pack for later reasoning.
    """
    from app.rag.query import execute_company_context

    result = execute_company_context(
        body.company,
        body.question,
        db,
        top_k=body.top_k,
    )
    return result.as_dict()
