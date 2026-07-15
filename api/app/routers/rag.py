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

from collections import defaultdict
import logging
import threading
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth_context import CurrentUser, require_current_user
from app.db.session import SessionLocal, get_db
from app.models.ai_sage_chat import AISageChat
from app.models.rag import RagAuthor, RagDocument, RagIngestionJob, RagSource, RealtimeEvent
from app.rag.config import load_author_config, sync_authors_from_config
from app.rag.discovery import discover_sources_for_author
from app.rag.ingestion.fanout import build_fanout_preview
from app.rag.ingestion.events import (
    AUTHOR_INGESTION_TOPIC,
    publish_event,
    record_batch_event,
    record_source_event,
    serialize_event,
    serialize_job,
    serialize_source,
)
from app.rag.ingestion.pipeline import (
    bulk_ingest_author,
    preview_url_ingestion,
    run_manual_ingestion,
    run_url_ingestion,
)
from app.rag.ingestion.selector import SelectiveIngestionOptions
from app.rag.ingestion.source_presets import apply_source_preset
from app.rag.retrieval import (
    compare_retrieval_weighting,
    retrieve_similar_chunks,
    retrieve_with_constraints,
)
from app.rag.retrieval_weighting import weighting_feature_flag

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
    ingestion_config: Optional[dict[str, Any]] = None
    last_ingested_at: Optional[Any]
    created_at: Any

    model_config = {"from_attributes": True}


class RegisterSourceIn(BaseModel):
    author_id: str
    url: Optional[str] = None
    source_type: str = Field(..., pattern="^(html|pdf|text|manual)$")
    ingestion_config: Optional["IngestionConfigIn"] = None


class IngestUrlIn(BaseModel):
    source_id: str


class ValidateSourceIn(BaseModel):
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


class ValidationDocumentOut(BaseModel):
    key: str
    status: str
    title: Optional[str]
    author_id: Optional[str]
    source_section: Optional[str]
    parent_key: Optional[str]
    proposed_metadata: dict[str, Any]
    included_sections: list[str]
    extracted_char_count: int
    preview_text: str
    quality: dict[str, Any]
    failure_category: Optional[str] = None
    error: Optional[str] = None


class ValidationPreviewOut(BaseModel):
    source_id: str
    source_url: Optional[str]
    source_type: str
    ingestion_mode: str
    source_char_count: int
    document_count: int
    accepted_count: int
    rejected_count: int
    documents: list[ValidationDocumentOut]


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
    ingestion_config: Optional["IngestionConfigIn"] = Field(
        None,
        description="Optional deterministic fanout configuration persisted on each source before ingestion.",
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


class RetrieveCompareIn(BaseModel):
    query: str
    top_k: int = 5
    author_id: Optional[str] = None
    author_ids: Optional[list[str]] = None
    source_type: Optional[str] = None
    year_from: Optional[int] = None
    year_to: Optional[int] = None
    published_from: Optional[str] = None
    published_to: Optional[str] = None
    domains: Optional[list[str]] = None
    expertise_tags: Optional[list[str]] = None
    retrieval_mode: str = Field("hybrid", pattern="^(hybrid|dense_only|sparse_only)$")


class RetrieveCompareOut(BaseModel):
    query: str
    retrieval_mode: str
    weighting_feature_flag: str
    default_weighting_enabled: bool
    baseline_results: list[dict]
    weighted_results: list[dict]


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


class LogicalDocumentConfigIn(BaseModel):
    key: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    author_id: Optional[str] = None
    published_at: Optional[str] = None
    publication_year: Optional[int] = Field(None, ge=0, le=9999)
    venue: Optional[str] = None
    collection: Optional[str] = None
    canonical_work_id: Optional[str] = None
    canonical_status: Optional[str] = None
    canonical_metadata: dict[str, Any] = Field(default_factory=dict)
    dedupe_priority: Optional[int] = None
    source_section: Optional[str] = None
    note_taker: Optional[str] = None
    work_type: Optional[str] = None
    parent_key: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    selective_ingestion: Optional[SelectiveIngestionOptionsIn] = None


class SectionSplitMarkerIn(BaseModel):
    marker: str = Field(..., min_length=1)
    heading: str = Field(..., min_length=1)
    level: Optional[int] = Field(None, ge=1, le=6)


class SectionSplitRuleIn(BaseModel):
    match_heading: str = Field(..., min_length=1)
    markers: list[SectionSplitMarkerIn] = Field(..., min_length=1)


class FlatTextSplitMarkerIn(BaseModel):
    marker: str = Field(..., min_length=1)
    heading: str = Field(..., min_length=1)
    level: Optional[int] = Field(None, ge=1, le=6)


class IngestionConfigIn(BaseModel):
    mode: str = Field("single_work", pattern="^(single_work|fanout)$")
    documents: list[LogicalDocumentConfigIn] = Field(default_factory=list)
    section_splits: list[SectionSplitRuleIn] = Field(default_factory=list)
    split_markers: list[FlatTextSplitMarkerIn] = Field(default_factory=list)


class UpdateSourceIngestionConfigIn(BaseModel):
    ingestion_config: Optional[IngestionConfigIn] = None


class FanoutPreviewIn(BaseModel):
    author_id: str
    source_title: Optional[str] = None
    source_published_at: Optional[str] = None
    ingestion_config: Optional[IngestionConfigIn] = None


class LogicalDocumentPreviewOut(BaseModel):
    key: str
    title: Optional[str]
    author_id: Optional[str]
    published_at: Optional[str]
    publication_year: Optional[int]
    venue: Optional[str]
    collection: Optional[str]
    canonical_work_id: Optional[str]
    canonical_status: Optional[str]
    dedupe_priority: Optional[int]
    source_section: Optional[str]
    note_taker: Optional[str]
    work_type: Optional[str]
    parent_key: Optional[str]
    metadata: dict[str, Any]
    selective_ingestion: dict[str, Any]


class FanoutPreviewOut(BaseModel):
    mode: str
    document_count: int
    documents: list[LogicalDocumentPreviewOut]


class LibraryAuthorOut(BaseModel):
    id: str
    name: str
    document_count: int
    source_count: int
    collections: list[str]
    work_types: list[str]
    latest_document_at: Optional[str]
    photo_url: Optional[str] = None
    about_text: Optional[str] = None


class LibraryDocumentSummaryOut(BaseModel):
    id: str
    source_id: str
    title: str
    author_id: Optional[str]
    author_name: Optional[str]
    published_at: Optional[str]
    publication_year: Optional[int]
    publication_label: Optional[str]
    venue: Optional[str]
    collection: Optional[str]
    canonical_work_id: Optional[str]
    canonical_status: Optional[str]
    source_type: str
    source_url: Optional[str]
    work_type: Optional[str]
    source_section: Optional[str]
    metadata: dict[str, Any]
    char_count: int
    parent_document_id: Optional[str]
    parent_title: Optional[str]
    child_count: int


class LibrarySecondaryGroupOut(BaseModel):
    field: str
    label: str
    value: str
    document_count: int
    documents: list[LibraryDocumentSummaryOut]


class LibraryGroupOut(BaseModel):
    field: str
    label: str
    value: str
    document_count: int
    documents: list[LibraryDocumentSummaryOut]
    secondary_field: Optional[str] = None
    secondary_groups: list[LibrarySecondaryGroupOut] = Field(default_factory=list)


class LibraryGroupingOut(BaseModel):
    primary_field: Optional[str]
    secondary_field: Optional[str]
    available_fields: list[str]


class AuthorLibraryOut(BaseModel):
    author: LibraryAuthorOut
    grouping: LibraryGroupingOut
    groups: list[LibraryGroupOut]
    documents: list[LibraryDocumentSummaryOut]


class RelatedLibraryDocumentOut(BaseModel):
    id: str
    title: str
    author_id: Optional[str]
    author_name: Optional[str]
    publication_label: Optional[str]
    work_type: Optional[str]
    source_url: Optional[str]
    relationship: str


class LibraryDocumentDetailOut(BaseModel):
    id: str
    source_id: str
    title: str
    author_id: Optional[str]
    author_name: Optional[str]
    published_at: Optional[str]
    publication_year: Optional[int]
    publication_label: Optional[str]
    venue: Optional[str]
    collection: Optional[str]
    canonical_work_id: Optional[str]
    canonical_status: Optional[str]
    source_type: str
    source_url: Optional[str]
    work_type: Optional[str]
    source_section: Optional[str]
    metadata: dict[str, Any]
    char_count: int
    parent_document: Optional[RelatedLibraryDocumentOut]
    child_documents: list[RelatedLibraryDocumentOut]
    source_author_id: Optional[str]
    source_author_name: Optional[str]
    source_status: str
    created_at: Optional[str]


# ── Catalog / config ──────────────────────────────────────────────────────────


def _parse_iso_date(value: Optional[str], *, field_name: str) -> Optional[date]:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field_name} must be YYYY-MM-DD")


def _ingestion_config_to_dict(ingestion_config: Optional[IngestionConfigIn]) -> Optional[dict[str, Any]]:
    if ingestion_config is None:
        return None

    if ingestion_config.mode == "fanout" and not ingestion_config.documents:
        raise HTTPException(
            status_code=422,
            detail="ingestion_config.documents must contain at least one logical document when mode=fanout",
        )
    if ingestion_config.mode != "fanout" and ingestion_config.documents:
        raise HTTPException(
            status_code=422,
            detail="ingestion_config.documents may only be provided when mode=fanout",
        )

    seen_keys: set[str] = set()
    for document in ingestion_config.documents:
        key = document.key.strip()
        if key in seen_keys:
            raise HTTPException(status_code=422, detail=f"Duplicate logical document key '{key}' is not allowed")
        seen_keys.add(key)
    for document in ingestion_config.documents:
        if not document.parent_key:
            continue
        parent_key = document.parent_key.strip()
        if parent_key == document.key.strip():
            raise HTTPException(
                status_code=422,
                detail=f"Logical document '{document.key.strip()}' cannot reference itself as parent",
            )
        if parent_key not in seen_keys:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Logical document '{document.key.strip()}' references unknown parent '{parent_key}'"
                ),
            )

    documents: list[dict[str, Any]] = []
    for document in ingestion_config.documents:
        published_at = _parse_iso_date(
            document.published_at,
            field_name=f"ingestion_config.documents[{len(documents)}].published_at",
        )
        metadata = dict(document.metadata)
        if document.canonical_metadata:
            metadata["canonical_metadata"] = dict(document.canonical_metadata)

        payload: dict[str, Any] = {
            "key": document.key.strip(),
            "title": document.title.strip(),
            "author_id": document.author_id,
            "published_at": published_at.isoformat() if published_at else None,
            "publication_year": document.publication_year,
            "venue": document.venue,
            "collection": document.collection,
            "canonical_work_id": document.canonical_work_id,
            "canonical_status": document.canonical_status,
            "dedupe_priority": document.dedupe_priority,
            "source_section": document.source_section,
            "note_taker": document.note_taker,
            "work_type": document.work_type,
            "parent_key": document.parent_key.strip() if document.parent_key else None,
            "metadata": metadata,
        }
        if document.selective_ingestion is not None:
            payload["selective_options"] = document.selective_ingestion.to_selector_options().to_dict()
        documents.append({key: value for key, value in payload.items() if value not in (None, {}, [])})

    config_payload: dict[str, Any] = {"mode": ingestion_config.mode}
    if documents:
        config_payload["documents"] = documents
    if ingestion_config.section_splits:
        config_payload["section_splits"] = [
            {
                "match_heading": split.match_heading.strip(),
                "markers": [
                    {
                        "marker": marker.marker.strip(),
                        "heading": marker.heading.strip(),
                        **({"level": marker.level} if marker.level is not None else {}),
                    }
                    for marker in split.markers
                ],
            }
            for split in ingestion_config.section_splits
        ]
    if ingestion_config.split_markers:
        config_payload["split_markers"] = [
            {
                "marker": marker.marker.strip(),
                "heading": marker.heading.strip(),
                **({"level": marker.level} if marker.level is not None else {}),
            }
            for marker in ingestion_config.split_markers
        ]
    return config_payload


def _ensure_ingestion_config_authors_exist(
    db: Session,
    *,
    source_author_id: str,
    ingestion_config: Optional[dict[str, Any]],
) -> None:
    mode, preview_documents = build_fanout_preview(
        source_author_id=source_author_id,
        source_title=None,
        source_published_at=None,
        ingestion_config=ingestion_config,
    )
    author_ids = {source_author_id}
    if mode == "fanout":
        author_ids.update(document.author_id for document in preview_documents if document.author_id)
    for author_id in author_ids:
        if author_id and db.get(RagAuthor, author_id) is None:
            raise HTTPException(status_code=422, detail=f"Author '{author_id}' does not exist")


def _fanout_preview_out(
    *,
    source_author_id: str,
    source_title: Optional[str],
    source_published_at: Optional[date],
    ingestion_config: Optional[dict[str, Any]],
) -> FanoutPreviewOut:
    mode, preview_documents = build_fanout_preview(
        source_author_id=source_author_id,
        source_title=source_title,
        source_published_at=source_published_at,
        ingestion_config=ingestion_config,
    )
    return FanoutPreviewOut(
        mode=mode,
        document_count=len(preview_documents),
        documents=[
            LogicalDocumentPreviewOut(
                key=document.key,
                title=document.title,
                author_id=document.author_id,
                published_at=document.published_at.isoformat() if document.published_at else None,
                publication_year=document.publication_year,
                venue=document.venue,
                collection=document.collection,
                canonical_work_id=document.canonical_work_id,
                canonical_status=document.canonical_status,
                dedupe_priority=document.dedupe_priority,
                source_section=document.source_section,
                note_taker=document.note_taker,
                work_type=document.work_type,
                parent_key=document.parent_key,
                metadata=document.metadata,
                selective_ingestion=document.selective_options,
            )
            for document in preview_documents
        ],
    )


def _source_access_filter(current_user: CurrentUser):
    return or_(RagSource.user_id == current_user.id, RagSource.user_id.is_(None))


def _library_documents_query(db: Session, current_user: CurrentUser):
    return (
        db.query(RagDocument)
        .join(RagSource, RagDocument.source_id == RagSource.id)
        .filter(_source_access_filter(current_user))
        .options(
            joinedload(RagDocument.author),
            joinedload(RagDocument.source).joinedload(RagSource.author),
            joinedload(RagDocument.parent_document),
            selectinload(RagDocument.child_documents),
        )
    )


def _effective_author_id(doc: RagDocument) -> Optional[str]:
    return doc.author_id or (doc.source.author_id if doc.source else None)


def _effective_author_name(doc: RagDocument) -> Optional[str]:
    if doc.author and doc.author.name:
        return doc.author.name
    if doc.source and doc.source.author and doc.source.author.name:
        return doc.source.author.name
    return None


def _effective_author_model(doc: RagDocument) -> Optional[RagAuthor]:
    if doc.author is not None:
        return doc.author
    if doc.source and doc.source.author is not None:
        return doc.source.author
    return None


def _publication_label(doc: RagDocument) -> Optional[str]:
    if doc.published_at:
        return doc.published_at.isoformat()
    if doc.publication_year is not None:
        return str(doc.publication_year)
    return None


def _publication_group_label(doc: RagDocument) -> str:
    year = doc.publication_year or (doc.published_at.year if doc.published_at else None)
    return str(year) if year is not None else "Unknown"


def _publication_group_sort_key(label: str) -> tuple[int, int, str]:
    if label == "Unknown":
        return (1, 0, label)
    try:
        return (0, -int(label), label)
    except ValueError:
        return (0, 0, label)


def _source_type_label(doc: RagDocument) -> str:
    return doc.source.source_type if doc.source else "unknown"


def _source_url(doc: RagDocument) -> Optional[str]:
    return doc.source.url if doc.source else None


def _metadata_scalar(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return None


def _author_library_config() -> dict[str, dict[str, Any]]:
    try:
        config_data = load_author_config()
    except FileNotFoundError:
        return {}
    return {
        entry["id"]: entry
        for entry in config_data.get("authors", [])
        if isinstance(entry, dict) and entry.get("id")
    }


def _format_author_label(value: str) -> str:
    return value.replace("_", " ").strip()


def _author_photo_url(config_entry: Optional[dict[str, Any]]) -> Optional[str]:
    if not config_entry:
        return None
    return _metadata_scalar(
        config_entry.get("photo_url")
        or config_entry.get("photo")
        or config_entry.get("image_url")
        or config_entry.get("avatar_url")
    )


def _author_about_text(author: Optional[RagAuthor], config_entry: Optional[dict[str, Any]]) -> Optional[str]:
    if config_entry:
        explicit_about = _metadata_scalar(
            config_entry.get("about")
            or config_entry.get("about_text")
            or config_entry.get("bio")
            or config_entry.get("biography")
            or config_entry.get("summary")
        )
        if explicit_about:
            return explicit_about

    if author is None:
        return None

    parts: list[str] = []
    if author.role_type:
        parts.append(_format_author_label(author.role_type))

    domains = [_format_author_label(domain) for domain in (author.domains or [])[:2] if domain]
    expertise = [_format_author_label(tag) for tag in (author.expertise_tags or [])[:3] if tag]

    description = ""
    if parts and domains:
        description = f"{parts[0].capitalize()} focused on {', '.join(domains)}."
    elif parts:
        description = f"{parts[0].capitalize()}."
    elif domains:
        description = f"Focus areas: {', '.join(domains)}."

    if expertise:
        expertise_text = f"Themes: {', '.join(expertise)}."
        return " ".join(part for part in [description, expertise_text] if part).strip()
    return description or None


def _group_candidate_values(doc: RagDocument) -> dict[str, str]:
    metadata = doc.metadata_json or {}
    values: dict[str, str] = {}

    standard_candidates = {
        "collection": doc.collection,
        "corpus_section": metadata.get("corpus_section") or metadata.get("section"),
        "work_class": metadata.get("work_class") or metadata.get("document_class"),
        "work_type": doc.work_type,
        "venue": doc.venue,
        "source_type": _source_type_label(doc),
        "canonical_status": doc.canonical_status,
    }
    for field, raw_value in standard_candidates.items():
        normalized = _metadata_scalar(raw_value)
        if normalized:
            values[field] = normalized

    for key, raw_value in metadata.items():
        if key in {"canonical_metadata", "selective_options"} or key in values:
            continue
        normalized = _metadata_scalar(raw_value)
        if normalized:
            values[key] = normalized
    return values


def _meaningful_group_fields(documents: list[RagDocument]) -> list[str]:
    stats: dict[str, dict[str, Any]] = {}
    preferred_order = [
        "collection",
        "corpus_section",
        "work_class",
        "work_type",
        "venue",
        "source_type",
        "canonical_status",
    ]
    for doc in documents:
        for field, value in _group_candidate_values(doc).items():
            entry = stats.setdefault(field, {"coverage": 0, "values": set(), "counts": defaultdict(int)})
            entry["coverage"] += 1
            entry["values"].add(value)
            entry["counts"][value] += 1

    ordered_fields: list[str] = []
    for field in preferred_order:
        entry = stats.get(field)
        if (
            entry
            and entry["coverage"] >= 2
            and len(entry["values"]) >= 2
            and max(entry["counts"].values(), default=0) >= 2
        ):
            ordered_fields.append(field)

    dynamic_fields = sorted(
        (
            field
            for field, entry in stats.items()
            if field not in preferred_order
            and entry["coverage"] >= 2
            and len(entry["values"]) >= 2
            and max(entry["counts"].values(), default=0) >= 2
        ),
        key=lambda field: (-int(stats[field]["coverage"]), field),
    )
    ordered_fields.extend(dynamic_fields)
    return ordered_fields


def _select_primary_group_field(documents: list[RagDocument]) -> Optional[str]:
    labels = {_publication_label(doc) for doc in documents if _publication_label(doc)}
    if len(labels) >= 2:
        return "publication_year"
    fields = _meaningful_group_fields(documents)
    return fields[0] if fields else None


def _select_secondary_group_field(documents: list[RagDocument]) -> Optional[str]:
    labels = {_publication_label(doc) for doc in documents if _publication_label(doc)}
    if len(documents) < 2 or len(labels) < 2:
        return None
    return "publication_year"


def _document_sort_key(doc: RagDocument) -> tuple[int, str, str]:
    year = doc.publication_year or (doc.published_at.year if doc.published_at else 0)
    date_value = doc.published_at.isoformat() if doc.published_at else ""
    title = (doc.title or "").lower()
    return (-year, date_value, title)


def _document_char_count(doc: RagDocument) -> int:
    metadata = doc.metadata_json or {}
    value = metadata.get("char_count")
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _document_summary_out(doc: RagDocument) -> LibraryDocumentSummaryOut:
    parent_title = None
    if doc.parent_document is not None:
        parent_title = (doc.parent_document.title or "").strip() or "Untitled document"
    return LibraryDocumentSummaryOut(
        id=str(doc.id),
        source_id=str(doc.source_id),
        title=(doc.title or "").strip() or "Untitled document",
        author_id=_effective_author_id(doc),
        author_name=_effective_author_name(doc),
        published_at=doc.published_at.isoformat() if doc.published_at else None,
        publication_year=doc.publication_year,
        publication_label=_publication_label(doc),
        venue=doc.venue,
        collection=doc.collection,
        canonical_work_id=doc.canonical_work_id,
        canonical_status=doc.canonical_status,
        source_type=_source_type_label(doc),
        source_url=_source_url(doc),
        work_type=doc.work_type,
        source_section=doc.source_section,
        metadata=doc.metadata_json or {},
        char_count=_document_char_count(doc),
        parent_document_id=str(doc.parent_document_id) if doc.parent_document_id else None,
        parent_title=parent_title,
        child_count=len(doc.child_documents),
    )


def _related_document_out(doc: RagDocument, *, relationship: str) -> RelatedLibraryDocumentOut:
    return RelatedLibraryDocumentOut(
        id=str(doc.id),
        title=(doc.title or "").strip() or "Untitled document",
        author_id=_effective_author_id(doc),
        author_name=_effective_author_name(doc),
        publication_label=_publication_label(doc),
        work_type=doc.work_type,
        source_url=_source_url(doc),
        relationship=relationship,
    )


def _build_library_groups(documents: list[RagDocument]) -> tuple[list[LibraryGroupOut], LibraryGroupingOut]:
    primary_field = _select_primary_group_field(documents)
    available_fields = _meaningful_group_fields(documents)
    if primary_field == "publication_year" and "publication_year" not in available_fields:
        available_fields = ["publication_year", *available_fields]
    if primary_field is None:
        return [], LibraryGroupingOut(primary_field=None, secondary_field=None, available_fields=available_fields)

    grouped: dict[str, list[RagDocument]] = defaultdict(list)
    for doc in documents:
        if primary_field == "publication_year":
            label = _publication_group_label(doc)
        else:
            label = _group_candidate_values(doc).get(primary_field) or "Other"
        grouped[label].append(doc)

    groups: list[LibraryGroupOut] = []
    secondary_field_used: Optional[str] = None
    if primary_field == "publication_year":
        ordered_labels = sorted(grouped.keys(), key=_publication_group_sort_key)
    else:
        ordered_labels = sorted(grouped.keys(), key=lambda value: (value == "Other", value.lower()))
    for label in ordered_labels:
        docs_in_group = sorted(grouped[label], key=_document_sort_key)
        secondary_field = None if primary_field == "publication_year" else _select_secondary_group_field(docs_in_group)
        secondary_groups: list[LibrarySecondaryGroupOut] = []
        if secondary_field:
            secondary_field_used = secondary_field
            by_label: dict[str, list[RagDocument]] = defaultdict(list)
            for doc in docs_in_group:
                by_label[_publication_label(doc) or "Unknown"].append(doc)
            secondary_groups = [
                LibrarySecondaryGroupOut(
                    field=secondary_field,
                    label=year_label,
                    value=year_label,
                    document_count=len(group_docs),
                    documents=[_document_summary_out(group_doc) for group_doc in sorted(group_docs, key=_document_sort_key)],
                )
                for year_label, group_docs in sorted(
                    by_label.items(),
                    key=lambda item: (item[0] == "Unknown", item[0]),
                )
            ]
        groups.append(
            LibraryGroupOut(
                field=primary_field,
                label=label,
                value=label,
                document_count=len(docs_in_group),
                documents=[_document_summary_out(doc) for doc in docs_in_group],
                secondary_field=secondary_field,
                secondary_groups=secondary_groups,
            )
        )

    grouping = LibraryGroupingOut(
        primary_field=primary_field,
        secondary_field=secondary_field_used,
        available_fields=available_fields,
    )
    return groups, grouping


@router.get("/library/authors", response_model=list[LibraryAuthorOut])
def list_library_authors(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    documents = _library_documents_query(db, current_user).all()
    author_config = _author_library_config()
    by_author: dict[str, dict[str, Any]] = {}
    for doc in documents:
        author_id = _effective_author_id(doc)
        if not author_id:
            continue
        author = _effective_author_model(doc)
        entry = by_author.setdefault(
            author_id,
            {
                "id": author_id,
                "name": _effective_author_name(doc) or author_id,
                "document_count": 0,
                "source_ids": set(),
                "collections": set(),
                "work_types": set(),
                "latest_document_at": None,
                "author": author,
            },
        )
        entry["document_count"] += 1
        entry["source_ids"].add(str(doc.source_id))
        if doc.collection:
            entry["collections"].add(doc.collection)
        if doc.work_type:
            entry["work_types"].add(doc.work_type)
        if doc.created_at and (
            entry["latest_document_at"] is None or doc.created_at > entry["latest_document_at"]
        ):
            entry["latest_document_at"] = doc.created_at

    return [
        LibraryAuthorOut(
            id=entry["id"],
            name=entry["name"],
            document_count=entry["document_count"],
            source_count=len(entry["source_ids"]),
            collections=sorted(entry["collections"]),
            work_types=sorted(entry["work_types"]),
            latest_document_at=entry["latest_document_at"].isoformat() if entry["latest_document_at"] else None,
            photo_url=_author_photo_url(author_config.get(entry["id"])),
            about_text=_author_about_text(entry["author"], author_config.get(entry["id"])),
        )
        for entry in sorted(by_author.values(), key=lambda item: item["name"].lower())
    ]


@router.get("/library/authors/{author_id}", response_model=AuthorLibraryOut)
def get_author_library(
    author_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    author_config = _author_library_config()
    documents = (
        _library_documents_query(db, current_user)
        .filter(func.coalesce(RagDocument.author_id, RagSource.author_id) == author_id)
        .all()
    )
    if not documents:
        raise HTTPException(status_code=404, detail=f"No corpus found for author '{author_id}'.")

    ordered_documents = sorted(documents, key=_document_sort_key)
    groups, grouping = _build_library_groups(ordered_documents)
    latest_document_at = max(
        (doc.created_at for doc in ordered_documents if doc.created_at is not None),
        default=None,
    )
    author = _effective_author_model(ordered_documents[0])
    return AuthorLibraryOut(
        author=LibraryAuthorOut(
            id=author_id,
            name=_effective_author_name(ordered_documents[0]) or author_id,
            document_count=len(ordered_documents),
            source_count=len({str(doc.source_id) for doc in ordered_documents}),
            collections=sorted({doc.collection for doc in ordered_documents if doc.collection}),
            work_types=sorted({doc.work_type for doc in ordered_documents if doc.work_type}),
            latest_document_at=latest_document_at.isoformat() if latest_document_at else None,
            photo_url=_author_photo_url(author_config.get(author_id)),
            about_text=_author_about_text(author, author_config.get(author_id)),
        ),
        grouping=grouping,
        groups=groups,
        documents=[_document_summary_out(doc) for doc in ordered_documents],
    )


@router.get("/library/documents/{document_id}", response_model=LibraryDocumentDetailOut)
def get_library_document(
    document_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    try:
        uuid.UUID(document_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid document_id UUID")

    document = (
        db.query(RagDocument)
        .join(RagSource, RagDocument.source_id == RagSource.id)
        .filter(RagDocument.id == document_id)
        .filter(_source_access_filter(current_user))
        .options(
            joinedload(RagDocument.author),
            joinedload(RagDocument.source).joinedload(RagSource.author),
            joinedload(RagDocument.parent_document).joinedload(RagDocument.author),
            joinedload(RagDocument.parent_document).joinedload(RagDocument.source).joinedload(RagSource.author),
            selectinload(RagDocument.child_documents).joinedload(RagDocument.author),
            selectinload(RagDocument.child_documents).joinedload(RagDocument.source).joinedload(RagSource.author),
        )
        .first()
    )
    if document is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    parent_document = (
        _related_document_out(document.parent_document, relationship="parent")
        if document.parent_document is not None
        else None
    )
    return LibraryDocumentDetailOut(
        id=str(document.id),
        source_id=str(document.source_id),
        title=(document.title or "").strip() or "Untitled document",
        author_id=_effective_author_id(document),
        author_name=_effective_author_name(document),
        published_at=document.published_at.isoformat() if document.published_at else None,
        publication_year=document.publication_year,
        publication_label=_publication_label(document),
        venue=document.venue,
        collection=document.collection,
        canonical_work_id=document.canonical_work_id,
        canonical_status=document.canonical_status,
        source_type=_source_type_label(document),
        source_url=_source_url(document),
        work_type=document.work_type,
        source_section=document.source_section,
        metadata=document.metadata_json or {},
        char_count=_document_char_count(document),
        parent_document=parent_document,
        child_documents=[
            _related_document_out(child, relationship="child")
            for child in sorted(document.child_documents, key=_document_sort_key)
        ],
        source_author_id=document.source.author_id if document.source else None,
        source_author_name=document.source.author.name if document.source and document.source.author else None,
        source_status=document.source.status if document.source else "unknown",
        created_at=document.created_at.isoformat() if document.created_at else None,
    )


class ResearchAiSageStatsOut(BaseModel):
    chats_total: int
    chats_today: int


class ResearchAuthorCorpusStatsOut(BaseModel):
    author_count: int
    document_count: int


class ResearchIngestionQueueStatsOut(BaseModel):
    running_count: int
    queued_count: int
    failed_count: int
    last_job_at: Optional[str] = None


class ResearchSummaryOut(BaseModel):
    ai_sage: ResearchAiSageStatsOut
    author_corpus: ResearchAuthorCorpusStatsOut
    ingestion_queue: ResearchIngestionQueueStatsOut


def _research_coerce_dt(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _research_relative_time_label(occurred_at: datetime) -> str:
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - occurred_at
    seconds = max(0, delta.total_seconds())
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        minutes = max(1, int(seconds // 60))
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = int(seconds // 86400)
    if days == 1:
        return "Yesterday"
    return f"{days} days ago"


@router.get("/research-summary", response_model=ResearchSummaryOut)
def research_summary(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    """Aggregate stats + recent-activity feed for the Research section overview page."""
    now = datetime.now(tz=timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    chats = (
        db.query(AISageChat)
        .filter(AISageChat.owner_user_id == current_user.id)
        .order_by(AISageChat.last_activity_at.desc())
        .all()
    )
    chats_today = sum(1 for chat in chats if _research_coerce_dt(chat.created_at) >= today_start)

    documents = _library_documents_query(db, current_user).all()
    author_ids = {_effective_author_id(doc) for doc in documents if _effective_author_id(doc)}

    running_count = (
        db.query(RagIngestionJob)
        .filter(RagIngestionJob.user_id == current_user.id, RagIngestionJob.status == "running")
        .count()
    )
    queued_count = (
        db.query(RagIngestionJob)
        .filter(RagIngestionJob.user_id == current_user.id, RagIngestionJob.status.in_(["pending", "queued"]))
        .count()
    )
    failed_count = (
        db.query(RagIngestionJob)
        .filter(RagIngestionJob.user_id == current_user.id, RagIngestionJob.status == "failed")
        .count()
    )
    last_job = (
        db.query(RagIngestionJob)
        .filter(RagIngestionJob.user_id == current_user.id)
        .order_by(RagIngestionJob.created_at.desc())
        .first()
    )
    last_job_at = (
        _research_relative_time_label(_research_coerce_dt(last_job.created_at)) if last_job is not None else None
    )

    return ResearchSummaryOut(
        ai_sage=ResearchAiSageStatsOut(chats_total=len(chats), chats_today=chats_today),
        author_corpus=ResearchAuthorCorpusStatsOut(author_count=len(author_ids), document_count=len(documents)),
        ingestion_queue=ResearchIngestionQueueStatsOut(
            running_count=running_count,
            queued_count=queued_count,
            failed_count=failed_count,
            last_job_at=last_job_at,
        ),
    )


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
            ingestion_config=s.ingestion_config or None,
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
    ingestion_config = _ingestion_config_to_dict(body.ingestion_config)
    ingestion_config, _ = apply_source_preset(
        author_id=body.author_id,
        url=body.url,
        ingestion_config=ingestion_config,
        selective_options=None,
    )
    _ensure_ingestion_config_authors_exist(db, source_author_id=body.author_id, ingestion_config=ingestion_config)

    source = RagSource(
        user_id=current_user.id,
        author_id=body.author_id,
        url=body.url,
        source_type=body.source_type,
        status="pending",
        ingestion_config=ingestion_config,
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
        ingestion_config=source.ingestion_config or None,
        last_ingested_at=source.last_ingested_at,
        created_at=source.created_at,
    )


@router.patch("/sources/{source_id}/ingestion-config", response_model=SourceOut)
def update_source_ingestion_config(
    source_id: str,
    body: UpdateSourceIngestionConfigIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    source = _get_source_or_404(source_id, db, current_user)
    ingestion_config = _ingestion_config_to_dict(body.ingestion_config)
    _ensure_ingestion_config_authors_exist(db, source_author_id=source.author_id, ingestion_config=ingestion_config)
    source.ingestion_config = ingestion_config
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
        ingestion_config=source.ingestion_config or None,
        last_ingested_at=source.last_ingested_at,
        created_at=source.created_at,
    )


@router.post("/fanout/preview", response_model=FanoutPreviewOut)
def preview_fanout_config(
    body: FanoutPreviewIn,
    db: Session = Depends(get_db),
):
    author = db.get(RagAuthor, body.author_id)
    if not author:
        raise HTTPException(status_code=404, detail=f"Author '{body.author_id}' not found.")
    source_published_at = _parse_iso_date(body.source_published_at, field_name="source_published_at")
    ingestion_config = _ingestion_config_to_dict(body.ingestion_config)
    _ensure_ingestion_config_authors_exist(db, source_author_id=body.author_id, ingestion_config=ingestion_config)
    return _fanout_preview_out(
        source_author_id=body.author_id,
        source_title=body.source_title,
        source_published_at=source_published_at,
        ingestion_config=ingestion_config,
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
            RagSource.author_id == author_id,
            RagSource.url.isnot(None),
            (RagSource.user_id == current_user.id) | (RagSource.user_id.is_(None)),
        ).all()
        if s.url
    }

    new_sources: list[RagSource] = []
    requeued_sources: list[RagSource] = []
    skipped = 0
    batch_id = str(uuid.uuid4())
    submitted_selective_opts = body.selective_ingestion.to_selector_options().to_dict() if body.selective_ingestion else None
    submitted_ingestion_config = _ingestion_config_to_dict(body.ingestion_config)
    for url in body.urls:
        url = url.strip()
        if not url:
            continue
        ingestion_config, selective_opts_dict = apply_source_preset(
            author_id=author_id,
            url=url,
            ingestion_config=submitted_ingestion_config,
            selective_options=submitted_selective_opts,
        )
        _ensure_ingestion_config_authors_exist(db, source_author_id=author_id, ingestion_config=ingestion_config)
        existing = existing_sources_by_url.get(url)
        if existing is not None:
            db.expire_all()
            existing = db.get(RagSource, existing.id) or existing
            existing.source_type = body.source_type
            existing.status = "queued"
            existing.selective_options = selective_opts_dict
            existing.ingestion_config = ingestion_config
            requeued_sources.append(existing)
            continue
        source = RagSource(
            user_id=current_user.id,
            author_id=author_id,
            url=url,
            source_type=body.source_type,
            status="queued",
            selective_options=selective_opts_dict,
            ingestion_config=ingestion_config,
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
            ingestion_config=s.ingestion_config or None,
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


@router.post("/ingest/validate", response_model=ValidationPreviewOut, status_code=200)
def validate_url_source(
    body: ValidateSourceIn,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_current_user),
):
    source = _get_source_or_404(body.source_id, db, current_user)
    if not source.url:
        raise HTTPException(status_code=422, detail="Source has no URL. Use POST /rag/ingest/manual.")

    preview = preview_url_ingestion(source, db)
    return ValidationPreviewOut(
        source_id=str(source.id),
        source_url=source.url,
        source_type=str(preview["source_type"]),
        ingestion_mode=str(preview["ingestion_mode"]),
        source_char_count=int(preview["source_char_count"]),
        document_count=len(preview["documents"]),
        accepted_count=int(preview["accepted_count"]),
        rejected_count=int(preview["rejected_count"]),
        documents=[ValidationDocumentOut(**document) for document in preview["documents"]],
    )


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
                ingestion_config=serialized.get("ingestion_config"),
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
        "author_id": doc.author_id,
        "parent_document_id": str(doc.parent_document_id) if doc.parent_document_id else None,
        "source_document_index": doc.source_document_index,
        "title": doc.title,
        "published_at": doc.published_at.isoformat() if doc.published_at else None,
        "publication_year": doc.publication_year,
        "venue": doc.venue,
        "collection": doc.collection,
        "canonical_work_id": doc.canonical_work_id,
        "canonical_status": doc.canonical_status,
        "dedupe_priority": doc.dedupe_priority,
        "source_section": doc.source_section,
        "note_taker": doc.note_taker,
        "work_type": doc.work_type,
        "metadata_json": doc.metadata_json or {},
        "char_count": _document_char_count(doc),
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


@router.post("/retrieve-compare", response_model=RetrieveCompareOut)
def retrieve_compare(body: RetrieveCompareIn, db: Session = Depends(get_db)):
    comparison = compare_retrieval_weighting(
        body.query,
        db,
        top_k=body.top_k,
        author_id=body.author_id,
        author_ids=body.author_ids,
        source_type=body.source_type,
        domains=body.domains,
        expertise_tags=body.expertise_tags,
        year_from=body.year_from,
        year_to=body.year_to,
        published_from=body.published_from,
        published_to=body.published_to,
        retrieval_mode=body.retrieval_mode,
    )
    comparison["weighting_feature_flag"] = weighting_feature_flag()
    return RetrieveCompareOut(**comparison)


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


class QueryAuditListItemOut(BaseModel):
    id: str
    query_text: str
    mode: Optional[str]
    latency_ms: Optional[int]
    created_at: Any
    evidence_count: int
    retrieval_config: dict[str, Any] = Field(default_factory=dict)


class QueryAuditEvidenceOut(BaseModel):
    id: str
    rank: int
    chunk_id: str
    cosine_distance: Optional[float] = None
    reranker_score: Optional[float] = None
    rrf_score: Optional[float] = None
    ts_rank: Optional[float] = None
    is_golden: bool
    document_id: Optional[str] = None
    parent_document_id: Optional[str] = None
    source_type: Optional[str] = None
    source_section: Optional[str] = None
    title: Optional[str] = None
    text: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueryAuditDetailOut(BaseModel):
    id: str
    query_text: str
    mode: Optional[str]
    intent: dict[str, Any] = Field(default_factory=dict)
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    answer_text: Optional[str] = None
    latency_ms: Optional[int] = None
    created_at: Any
    evidence: list[QueryAuditEvidenceOut]


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


@router.get("/query-audit", response_model=list[QueryAuditListItemOut])
def list_query_audit(
    limit: int = Query(20, ge=1, le=100),
    mode: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    from app.models.rag import RagQuery

    query = db.query(RagQuery).options(selectinload(RagQuery.evidence)).order_by(RagQuery.created_at.desc())
    if mode:
        query = query.filter(RagQuery.mode == mode)
    rows = query.limit(limit).all()
    return [
        QueryAuditListItemOut(
            id=str(row.id),
            query_text=row.query_text,
            mode=row.mode,
            latency_ms=row.latency_ms,
            created_at=row.created_at,
            evidence_count=len(row.evidence or []),
            retrieval_config=row.retrieval_config or {},
        )
        for row in rows
    ]


@router.get("/query-audit/{query_id}", response_model=QueryAuditDetailOut)
def get_query_audit(query_id: str, db: Session = Depends(get_db)):
    from app.models.rag import RagChunk, RagQuery, RagQueryEvidence

    row = (
        db.query(RagQuery)
        .options(
            selectinload(RagQuery.evidence)
            .selectinload(RagQueryEvidence.chunk)
            .selectinload(RagChunk.document)
            .selectinload(RagDocument.source)
        )
        .filter(RagQuery.id == query_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Query audit '{query_id}' not found")

    evidence_rows = sorted(row.evidence or [], key=lambda evidence: evidence.rank)
    evidence = []
    for item in evidence_rows:
        chunk = item.chunk
        document = chunk.document if chunk is not None else None
        source = document.source if document is not None else None
        evidence.append(
            QueryAuditEvidenceOut(
                id=str(item.id),
                rank=item.rank,
                chunk_id=str(item.chunk_id),
                cosine_distance=item.cosine_distance,
                reranker_score=item.reranker_score,
                rrf_score=item.rrf_score,
                ts_rank=item.ts_rank,
                is_golden=item.is_golden,
                document_id=str(document.id) if document is not None else None,
                parent_document_id=str(document.parent_document_id) if document is not None and document.parent_document_id else None,
                source_type=source.source_type if source is not None else None,
                source_section=document.source_section if document is not None else None,
                title=document.title if document is not None else None,
                text=chunk.text if chunk is not None else None,
                metadata=(chunk.metadata_json or {}) if chunk is not None else {},
            )
        )

    return QueryAuditDetailOut(
        id=str(row.id),
        query_text=row.query_text,
        mode=row.mode,
        intent=row.intent_json or {},
        retrieval_config=row.retrieval_config or {},
        answer_text=row.answer_text,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
        evidence=evidence,
    )


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
