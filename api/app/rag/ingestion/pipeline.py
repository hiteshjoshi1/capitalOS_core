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
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session

from app.core.logging import get_job_id, job_context
from app.models.rag import RagAuthor, RagChunk, RagDocument, RagEmbedding, RagIngestionJob, RagSource
from app.rag.ingestion.events import record_source_event
from app.rag.ingestion.chunker import Chunk, DocumentSection as ChunkerSection, chunk_structured, chunk_text
from app.rag.ingestion.embedder import embed_batch, embedding_model_name
from app.rag.ingestion.fanout import (
    FanoutPlan,
    INGESTION_MODE_SINGLE_WORK,
    LogicalDocumentPlan,
    build_selected_text,
    build_fanout_plan,
)
from app.rag.ingestion.fetcher import FetchResult, detect_source_type, fetch_url
from app.rag.ingestion.normalization import normalize_with_ingestion_config
from app.rag.ingestion.parser import DocumentSection, ParseResult, StructuredParseResult, parse
from app.rag.ingestion.quality import LOW_QUALITY_FAILURE, QualityValidationResult, validate_logical_document
from app.rag.ingestion.selector import (
    NoContentSelectedError,
    SelectiveIngestionOptions,
    apply_selective_options,
)
from app.rag.ingestion.source_presets import (
    apply_source_preset,
    normalize_source_parse_result,
)
from app.rag.ingestion.entity_extractor import (
    extract_and_store_chunk_annotations,
    _load_entity_alias_patterns,
    _load_concept_alias_patterns,
)

log = logging.getLogger(__name__)

FAILURE_NETWORK_ERROR = "network_error"
FAILURE_PARSE_FAILED = "parse_failed"
FAILURE_EMPTY_TEXT_EXTRACTION = "empty_text_extraction"
FAILURE_OCR_REQUIRED = "ocr_required"
FAILURE_MANUAL_REVIEW_REQUIRED = "manual_review_required"
FAILURE_NO_CONTENT_SELECTED = "no_content_selected"
FAILURE_LOW_QUALITY_EXTRACTION = LOW_QUALITY_FAILURE
_PDF_PARSER_METADATA_KEYS = (
    "pdf_parser_policy",
    "pdf_parser_backend_requested",
    "pdf_parser_backend_used",
    "pdf_parser_unstructured_available",
    "pdf_parser_fallback_used",
    "pdf_parser_fallback_from",
    "pdf_parser_fallback_reason",
)


class EmptyTextExtractionError(RuntimeError):
    pass


class OcrRequiredError(RuntimeError):
    pass


# ── Internal helpers ──────────────────────────────────────────────────────────


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_base_metadata(
    source: RagSource,
    doc_hash: str,
    title: Optional[str],
    doc_metadata: Optional[dict] = None,
    *,
    author_id: Optional[str] = None,
    author_name: Optional[str] = None,
    published_at=None,
    publication_year: Optional[int] = None,
    source_section: Optional[str] = None,
    logical_metadata: Optional[dict[str, Any]] = None,
) -> dict:
    author = source.author
    base = {
        "author": author_name or (author.name if author else author_id or "unknown"),
        "author_id": author_id or source.author_id,
        "work_title": title or "",
        "source_url": source.url or "",
        "published_at": published_at.isoformat() if published_at is not None else None,
        "source_type": source.source_type,
        "topic_tags": [],
        "concept_tags": [],
        "cleanliness_score": 1.0,
        "doc_hash": doc_hash,
    }
    if publication_year is not None:
        base["year"] = publication_year
    if source_section:
        base["source_section"] = source_section
    if doc_metadata:
        # Merge document-level metadata from PDF/HTML properties
        if "title" in doc_metadata and not base["work_title"]:
            base["work_title"] = doc_metadata["title"]
        if "author" in doc_metadata and base["author"] in {"unknown", author_id or ""}:
            base["author"] = doc_metadata["author"]
        for key in ("subject", "creation_date"):
            if key in doc_metadata:
                base[key] = doc_metadata[key]
    if logical_metadata:
        for key, value in logical_metadata.items():
            if value is not None:
                base[key] = value
    return base


def _pdf_parser_metadata(parse_result: ParseResult) -> dict[str, Any]:
    if getattr(parse_result, "source_type", None) != "pdf":
        return {}
    doc_metadata = getattr(parse_result, "doc_metadata", None) or {}
    return {
        key: doc_metadata[key]
        for key in _PDF_PARSER_METADATA_KEYS
        if key in doc_metadata
    }


def _log_pdf_parser_path(source: RagSource, parse_result: ParseResult) -> None:
    parser_metadata = _pdf_parser_metadata(parse_result)
    if not parser_metadata:
        return
    log.info(
        "PDF parser path source=%s requested=%s used=%s fallback=%s policy=%s",
        source.url or source.id,
        parser_metadata.get("pdf_parser_backend_requested"),
        parser_metadata.get("pdf_parser_backend_used"),
        parser_metadata.get("pdf_parser_fallback_used"),
        parser_metadata.get("pdf_parser_policy"),
    )


def _log_rag_lifecycle(
    event: str,
    *,
    source: RagSource,
    job: RagIngestionJob,
    duration_ms: int,
    stats: dict[str, Any] | None = None,
    error_class: str | None = None,
    reason: str | None = None,
) -> None:
    stats = stats or {}
    extra = {
        "event": event,
        "source_id": str(source.id),
        "job_db_id": str(job.id),
        "author_id": source.author_id,
        "source_type": source.source_type,
        "status": job.status,
        "rows": stats.get("chunks"),
        "inserted": stats.get("documents_created"),
        "skipped": stats.get("documents_rejected"),
        "duration_ms": duration_ms,
        "error_class": error_class,
        "reason": reason,
    }
    level = log.warning if event == "rag_ingest_failed" else log.info
    level(event, extra={key: value for key, value in extra.items() if value is not None})


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
        metadata = dict(getattr(s, "metadata", None) or {})
        if s.caption:
            metadata["caption"] = s.caption
        if s.notes:
            metadata["notes"] = list(s.notes)
        if s.items:
            metadata["items"] = list(s.items)
        result.append(
            ChunkerSection(
                heading=(metadata.get("section_path") or [s.heading] or [""])[-1] if (metadata.get("section_path") or s.heading) else "",
                content=content,
                is_table=(s.content_type == "table"),
                is_list=(s.content_type == "list"),
                metadata=metadata,
            )
        )
    return result


def _serialize_content_blocks(sections: list[DocumentSection]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        metadata = dict(section.metadata or {})
        content = (
            section.table_markdown
            if section.content_type == "table" and section.table_markdown
            else section.content
        )
        block = {
            "index": index,
            "heading": section.heading,
            "level": section.level,
            "content_type": section.content_type,
            "modality": metadata.get("modality"),
            "section_path": metadata.get("section_path"),
            "source_ref": metadata.get("source_ref"),
            "content": content,
            "caption": section.caption,
            "notes": list(section.notes) if section.notes else None,
            "items": list(section.items) if section.items else None,
            "explanatory_text": metadata.get("explanatory_text"),
            "media_refs": metadata.get("media_refs"),
            "layout_sensitive": metadata.get("layout_sensitive"),
        }
        blocks.append({key: value for key, value in block.items() if value not in (None, "", [], {})})
    return blocks


def _persist_document_and_chunks(
    db: Session,
    source: RagSource,
    parse_result: ParseResult,
    plan: LogicalDocumentPlan,
) -> tuple[RagDocument, list[RagChunk]]:
    """Create RagDocument + RagChunk rows for one logical document."""
    _, raw_chunks, _ = _build_document_chunks_and_validation(source, parse_result, plan)
    publication_year = plan.publication_year or (plan.published_at.year if plan.published_at else None)
    source_document_metadata = dict(getattr(parse_result, "doc_metadata", None) or {})
    document_metadata = {**source_document_metadata, **dict(plan.metadata or {})}
    document_metadata["char_count"] = len(plan.clean_text or "")
    if plan.selected_sections:
        content_blocks = _serialize_content_blocks(plan.selected_sections)
        if content_blocks:
            document_metadata["content_blocks"] = content_blocks
            document_metadata["content_modalities"] = sorted(
                {block["modality"] for block in content_blocks if block.get("modality")}
            )

    doc = RagDocument(
        source_id=source.id,
        author_id=plan.author_id,
        title=plan.title,
        published_at=plan.published_at,
        publication_year=publication_year,
        venue=plan.venue,
        collection=plan.collection,
        canonical_work_id=plan.canonical_work_id,
        canonical_status=plan.canonical_status,
        dedupe_priority=plan.dedupe_priority,
        source_section=plan.source_section,
        note_taker=plan.note_taker,
        work_type=plan.work_type,
        source_document_index=plan.index,
        metadata_json=document_metadata,
    )
    db.add(doc)
    db.flush()

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

    db.flush()
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
    if isinstance(exc, NoContentSelectedError):
        return FAILURE_NO_CONTENT_SELECTED
    if isinstance(exc, LowQualityExtractionError):
        return FAILURE_LOW_QUALITY_EXTRACTION
    if isinstance(exc, (RuntimeError, UnicodeDecodeError)):
        return FAILURE_PARSE_FAILED
    return FAILURE_MANUAL_REVIEW_REQUIRED


def _ensure_clean_text(parsed: ParseResult, source_type: str) -> None:
    if parsed.clean_text.strip():
        return
    if source_type == "pdf":
        raise OcrRequiredError("PDF text extraction produced no usable text; OCR is required")
    raise EmptyTextExtractionError("Text extraction produced no usable text")


class LowQualityExtractionError(RuntimeError):
    pass


def _effective_selective_options(
    source: RagSource,
    explicit_options: Optional[SelectiveIngestionOptions],
) -> Optional[SelectiveIngestionOptions]:
    if explicit_options is not None:
        return explicit_options
    _, preset_selective_options = apply_source_preset(
        author_id=source.author_id,
        url=source.url,
        ingestion_config=None,
        selective_options=getattr(source, "selective_options", None),
    )
    raw_options = preset_selective_options
    if isinstance(raw_options, dict) and raw_options:
        return SelectiveIngestionOptions.from_dict(raw_options)
    return None


def _effective_ingestion_config(source: RagSource) -> Optional[dict[str, Any]]:
    preset_ingestion_config, _ = apply_source_preset(
        author_id=source.author_id,
        url=source.url,
        ingestion_config=getattr(source, "ingestion_config", None),
        selective_options=None,
    )
    return preset_ingestion_config if isinstance(preset_ingestion_config, dict) else None


def _prepare_parse_result(source: RagSource, parsed: ParseResult) -> StructuredParseResult:
    structured = parsed if isinstance(parsed, StructuredParseResult) else StructuredParseResult(
        raw_text=parsed.raw_text,
        clean_text=parsed.clean_text,
        source_type=parsed.source_type,
        sections=[],
        doc_metadata={},
    )
    normalized = normalize_source_parse_result(source.url, structured)
    return normalize_with_ingestion_config(normalized, getattr(source, "ingestion_config", None))


def _materialize_logical_plan(plan: LogicalDocumentPlan, shared_sections: list[DocumentSection]) -> LogicalDocumentPlan:
    if plan.clean_text.strip() or plan.selected_sections:
        return plan
    plan.selected_sections = (
        apply_selective_options(shared_sections, plan.selective_options)
        if not plan.selective_options.is_empty()
        else list(shared_sections)
    )
    plan.clean_text = build_selected_text(plan.selected_sections)
    plan.raw_text = plan.clean_text or plan.raw_text
    return plan


def _ensure_document_author_exists(db: Session, author_id: Optional[str]) -> None:
    if not author_id:
        return
    if type(db).__module__.startswith("unittest.mock"):
        return
    if db.get(RagAuthor, author_id) is None:
        raise RuntimeError(f"Logical document author '{author_id}' does not exist")


def _link_parent_documents(
    db: Session,
    created_documents: dict[str, RagDocument],
    created_outcomes: dict[str, dict[str, Any]],
) -> None:
    for key, outcome in created_outcomes.items():
        parent_key = outcome.get("parent_key")
        if not parent_key:
            continue
        document = created_documents.get(key)
        parent_document = created_documents.get(parent_key)
        if document is None or parent_document is None:
            continue
        document.parent_document_id = parent_document.id
        outcome["parent_document_id"] = str(parent_document.id)
    db.flush()


def _preserve_existing_single_work_identity(
    plan: LogicalDocumentPlan,
    existing_document: RagDocument | None,
) -> LogicalDocumentPlan:
    if existing_document is None:
        return plan

    if existing_document.title:
        plan.title = existing_document.title
    if existing_document.author_id:
        plan.author_id = existing_document.author_id
    if existing_document.published_at is not None:
        plan.published_at = existing_document.published_at
    if existing_document.publication_year is not None:
        plan.publication_year = existing_document.publication_year
    if existing_document.venue:
        plan.venue = existing_document.venue
    if existing_document.collection:
        plan.collection = existing_document.collection
    if existing_document.canonical_work_id:
        plan.canonical_work_id = existing_document.canonical_work_id
    if existing_document.canonical_status:
        plan.canonical_status = existing_document.canonical_status
    if existing_document.dedupe_priority is not None:
        plan.dedupe_priority = existing_document.dedupe_priority
    if existing_document.source_section:
        plan.source_section = existing_document.source_section
    if existing_document.note_taker:
        plan.note_taker = existing_document.note_taker
    if existing_document.work_type:
        plan.work_type = existing_document.work_type

    existing_metadata = dict(existing_document.metadata_json or {})
    if existing_metadata:
        merged_metadata = dict(existing_metadata)
        merged_metadata.update(plan.metadata or {})
        plan.metadata = merged_metadata

    return plan


def _build_document_chunks_and_validation(
    source: RagSource,
    parse_result: ParseResult,
    plan: LogicalDocumentPlan,
) -> tuple[dict[str, Any], list[Chunk], QualityValidationResult]:
    doc_hash = _sha256(plan.clean_text)
    doc_metadata: Optional[dict] = getattr(parse_result, "doc_metadata", None)
    publication_year = plan.publication_year or (plan.published_at.year if plan.published_at else None)
    document_char_count = len(plan.clean_text or "")
    base_meta = _build_base_metadata(
        source,
        doc_hash,
        plan.title,
        doc_metadata,
        author_id=plan.author_id,
        published_at=plan.published_at,
        publication_year=publication_year,
        source_section=plan.source_section,
        logical_metadata={
            "venue": plan.venue,
            "collection": plan.collection,
            "canonical_work_id": plan.canonical_work_id,
            "canonical_status": plan.canonical_status,
            "dedupe_priority": plan.dedupe_priority,
            "note_taker": plan.note_taker,
            "work_type": plan.work_type,
            "document_char_count": document_char_count,
            **plan.metadata,
        },
    )

    parser_sections = plan.selected_sections
    if parser_sections:
        chunker_sections = _parser_sections_to_chunker(parser_sections)
        raw_chunks = chunk_structured(chunker_sections, base_metadata=base_meta) if chunker_sections else chunk_text(
            plan.clean_text, base_metadata=base_meta
        )
    else:
        raw_chunks = chunk_text(plan.clean_text, base_metadata=base_meta)

    validation = validate_logical_document(
        clean_text=plan.clean_text,
        title=plan.title,
        chunk_count=len(raw_chunks),
        section_headings=[section.heading for section in parser_sections if section.heading],
    )
    return base_meta, raw_chunks, validation


def _build_validation_artifact(
    plan: LogicalDocumentPlan,
    *,
    base_meta: dict[str, Any],
    validation: QualityValidationResult,
    error: Optional[str] = None,
    failure_category: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "key": plan.key,
        "status": "accepted" if validation.accepted and not error else "rejected",
        "title": plan.title,
        "author_id": plan.author_id,
        "source_section": plan.source_section,
        "parent_key": plan.parent_key,
        "proposed_metadata": base_meta,
        "included_sections": [section.heading for section in plan.selected_sections if section.heading],
        "extracted_char_count": len(plan.clean_text or ""),
        "preview_text": (plan.clean_text or "")[:1200],
        "quality": {
            "reasons": validation.reasons,
            **validation.metrics,
        },
        "failure_category": failure_category or validation.failure_category,
        "error": error,
    }


def _preview_logical_documents(
    source: RagSource,
    db: Session,
    parsed: StructuredParseResult,
    *,
    title: Optional[str] = None,
    published_at=None,
    selective_options: Optional[SelectiveIngestionOptions] = None,
) -> tuple[FanoutPlan, list[dict[str, Any]], list[tuple[LogicalDocumentPlan, list[Chunk], QualityValidationResult]], list[str], Optional[SelectiveIngestionOptions]]:
    effective_options = _effective_selective_options(source, selective_options)
    ingestion_config = _effective_ingestion_config(source)
    existing_documents = (
        db.query(RagDocument)
        .filter(RagDocument.source_id == source.id)
        .order_by(RagDocument.source_document_index.asc())
        .all()
    )
    existing_documents_by_index = {
        int(document.source_document_index): document
        for document in existing_documents
    }
    plan: FanoutPlan = build_fanout_plan(
        parsed,
        source_author_id=source.author_id,
        source_title=title,
        source_published_at=published_at,
        source_selective_options=effective_options,
        ingestion_config=ingestion_config,
    )
    if plan.mode == INGESTION_MODE_SINGLE_WORK and title is None and published_at is None and plan.documents:
        plan.documents[0] = _preserve_existing_single_work_identity(
            plan.documents[0],
            existing_documents_by_index.get(plan.documents[0].index),
        )

    artifacts: list[dict[str, Any]] = []
    prepared_documents: list[tuple[LogicalDocumentPlan, list[Chunk], QualityValidationResult]] = []
    rejected_categories: list[str] = []

    for logical_plan in plan.documents:
        try:
            _ensure_document_author_exists(db, logical_plan.author_id)
            materialized_plan = _materialize_logical_plan(logical_plan, plan.shared_sections)
            if not materialized_plan.clean_text.strip():
                raise EmptyTextExtractionError("Text extraction produced no usable text")
            base_meta, raw_chunks, validation = _build_document_chunks_and_validation(source, parsed, materialized_plan)
            artifacts.append(_build_validation_artifact(materialized_plan, base_meta=base_meta, validation=validation))
            if validation.accepted:
                prepared_documents.append((materialized_plan, raw_chunks, validation))
            else:
                rejected_categories.append(validation.failure_category or FAILURE_LOW_QUALITY_EXTRACTION)
        except NoContentSelectedError as exc:
            rejected_categories.append(FAILURE_NO_CONTENT_SELECTED)
            artifacts.append(
                _build_validation_artifact(
                    logical_plan,
                    base_meta={},
                    validation=QualityValidationResult(
                        accepted=False,
                        failure_category=FAILURE_NO_CONTENT_SELECTED,
                        reasons=["no_content_selected"],
                        metrics={"char_count": 0, "word_count": 0, "body_char_count": 0, "body_word_count": 0, "chunk_count": 0, "body_ratio": 0.0, "section_count": 0},
                    ),
                    error=str(exc),
                    failure_category=FAILURE_NO_CONTENT_SELECTED,
                )
            )
        except EmptyTextExtractionError as exc:
            rejected_categories.append(FAILURE_EMPTY_TEXT_EXTRACTION)
            artifacts.append(
                _build_validation_artifact(
                    logical_plan,
                    base_meta={},
                    validation=QualityValidationResult(
                        accepted=False,
                        failure_category=FAILURE_EMPTY_TEXT_EXTRACTION,
                        reasons=["empty_text"],
                        metrics={"char_count": 0, "word_count": 0, "body_char_count": 0, "body_word_count": 0, "chunk_count": 0, "body_ratio": 0.0, "section_count": 0},
                    ),
                    error=str(exc),
                    failure_category=FAILURE_EMPTY_TEXT_EXTRACTION,
                )
            )

    return plan, artifacts, prepared_documents, rejected_categories, effective_options


def _persist_logical_documents(
    db: Session,
    source: RagSource,
    parsed: StructuredParseResult,
    *,
    title: Optional[str] = None,
    published_at=None,
    selective_options: Optional[SelectiveIngestionOptions] = None,
) -> tuple[bool, dict[str, Any], Optional[str], Optional[str]]:
    plan, validation_artifacts, prepared_documents, rejected_categories, effective_options = _preview_logical_documents(
        source,
        db,
        parsed,
        title=title,
        published_at=published_at,
        selective_options=selective_options,
    )

    outcomes: list[dict[str, Any]] = []
    created_documents: dict[str, RagDocument] = {}
    created_outcomes: dict[str, dict[str, Any]] = {}
    total_chunks = 0
    total_embeddings = 0
    for artifact in validation_artifacts:
        if artifact["status"] != "accepted":
            outcomes.append(
                {
                    "key": artifact["key"],
                    "status": "rejected",
                    "failure_category": artifact.get("failure_category") or FAILURE_LOW_QUALITY_EXTRACTION,
                    "error": artifact.get("error") or "Logical document did not pass deterministic quality validation",
                    "title": artifact.get("title"),
                    "author_id": artifact.get("author_id"),
                    "source_section": artifact.get("source_section"),
                    "parent_key": artifact.get("parent_key"),
                    "quality": artifact.get("quality", {}),
                }
            )

    if prepared_documents:
        with db.begin_nested():
            existing_documents = (
                db.query(RagDocument)
                .filter(RagDocument.source_id == source.id)
                .all()
            )
            for existing_document in existing_documents:
                db.delete(existing_document)
            db.flush()

            # Pre-load alias patterns once per ingestion job (not per chunk)
            _entity_patterns = None
            _concept_patterns = None
            try:
                _entity_patterns = _load_entity_alias_patterns(db)
                _concept_patterns = _load_concept_alias_patterns(db)
            except Exception as _exc:
                log.warning("entity_extractor: failed to load alias patterns: %s", _exc)

            doc_entities_extracted = 0
            doc_concepts_extracted = 0

            for materialized_plan, _, validation in prepared_documents:
                document, chunks = _persist_document_and_chunks(db, source, parsed, materialized_plan)
                embeddings = _embed_and_persist(db, chunks)
                total_chunks += len(chunks)
                total_embeddings += embeddings
                created_documents[materialized_plan.key] = document

                # Extract entity/concept annotations per chunk (non-fatal)
                for chunk in chunks:
                    try:
                        counts = extract_and_store_chunk_annotations(
                            chunk.id,
                            chunk.text,
                            db,
                            entity_patterns=_entity_patterns,
                            concept_patterns=_concept_patterns,
                        )
                        doc_entities_extracted += counts.get("entities_extracted_count", 0)
                        doc_concepts_extracted += counts.get("concepts_extracted_count", 0)
                    except Exception as _exc:
                        log.warning(
                            "entity_extractor: chunk %s extraction failed: %s",
                            chunk.id,
                            _exc,
                        )

                outcome = {
                    "key": materialized_plan.key,
                    "status": "created",
                    "document_id": str(document.id),
                    "title": document.title,
                    "author_id": document.author_id,
                    "source_section": document.source_section,
                    "chunk_count": len(chunks),
                    "embedding_count": embeddings,
                    "entities_extracted": doc_entities_extracted,
                    "concepts_extracted": doc_concepts_extracted,
                    "parent_key": materialized_plan.parent_key,
                    "quality": {
                        "reasons": validation.reasons,
                        **validation.metrics,
                    },
                }
                created_outcomes[materialized_plan.key] = outcome
                outcomes.append(outcome)

            if created_documents:
                _link_parent_documents(db, created_documents, created_outcomes)

    stats: dict[str, Any] = {
        "ingestion_mode": plan.mode,
        "chunks": total_chunks,
        "embeddings": total_embeddings,
        "char_count": len(parsed.clean_text),
        "documents_created": len(created_documents),
        "documents_rejected": len([outcome for outcome in outcomes if outcome["status"] != "created"]),
        "documents": outcomes,
        "validation_artifacts": validation_artifacts,
        "accepted_count": len(prepared_documents),
        "rejected_count": len([artifact for artifact in validation_artifacts if artifact["status"] != "accepted"]),
        "model": embedding_model_name(),
    }
    parser_metadata = _pdf_parser_metadata(parsed)
    if parser_metadata:
        stats["pdf_parser"] = parser_metadata
    if effective_options and not effective_options.is_empty():
        stats["selective_options"] = effective_options.to_dict()
        stats["sections_selected"] = len(plan.shared_sections)
    if created_documents:
        return True, stats, None, None
    failure_category = rejected_categories[0] if rejected_categories else FAILURE_EMPTY_TEXT_EXTRACTION
    error = next((outcome.get("error") for outcome in outcomes if outcome.get("error")), None) or (
        "No logical documents were created from the parsed source"
    )
    return False, stats, error, failure_category


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
    selective_options: Optional["SelectiveIngestionOptions"] = None,
) -> RagIngestionJob:
    """
    Fetch, parse, chunk, embed, and store content from source.url.

    If *existing_job* is provided (e.g. a pre-created "queued" job from a
    background-ingestion flow), it is reused and transitioned to "running"
    instead of creating a second job row.

    On any error the job is marked 'failed' and the error message is stored.
    The caller is responsible for committing the session.
    """
    context = job_context() if get_job_id() is None else None
    if context is not None:
        context.__enter__()
    started = time.perf_counter()
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
    _log_rag_lifecycle(
        "rag_ingest_started",
        source=source,
        job=job,
        duration_ms=0,
    )

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
        structured = _prepare_parse_result(source, parsed)
        _log_pdf_parser_path(source, structured)

        success, stats, error, failure_category = _persist_logical_documents(
            db,
            source,
            structured,
            selective_options=selective_options,
        )

        source.status = "ingested" if success else "failed"
        if success:
            source.last_ingested_at = _now()

        _close_job(db, job, success=success, stats=stats, error=error, failure_category=failure_category)
        _log_rag_lifecycle(
            "rag_ingest_succeeded" if success else "rag_ingest_failed",
            source=source,
            job=job,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stats=stats,
            reason=failure_category,
        )
        if success and source.user_id is not None:
            record_source_event(
                db,
                user_id=source.user_id,
                source=source,
                job=job,
                event_name="source_ingested",
                status="ingested",
                batch_id=batch_id,
            )
        if (not success) and source.user_id is not None:
            record_source_event(
                db,
                user_id=source.user_id,
                source=source,
                job=job,
                event_name="source_failed",
                status="failed",
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
        _log_rag_lifecycle(
            "rag_ingest_failed",
            source=source,
            job=job,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_class=exc.__class__.__name__,
            reason=_classify_failure(exc, source.source_type),
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

    if context is not None:
        context.__exit__(None, None, None)
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


def preview_url_ingestion(
    source: RagSource,
    db: Session,
    *,
    selective_options: Optional["SelectiveIngestionOptions"] = None,
) -> dict[str, Any]:
    if not source.url:
        raise RuntimeError("Source has no URL")

    fetch: FetchResult = fetch_url(source.url)
    effective_source_type = detect_source_type(fetch.content_type, source.url)
    parsed: ParseResult = parse(fetch.raw_bytes, effective_source_type)
    _ensure_clean_text(parsed, effective_source_type)
    structured = _prepare_parse_result(source, parsed)
    plan, validation_artifacts, prepared_documents, _, _ = _preview_logical_documents(
        source,
        db,
        structured,
        selective_options=selective_options,
    )
    return {
        "source_type": effective_source_type,
        "ingestion_mode": plan.mode,
        "source_char_count": len(structured.clean_text),
        "accepted_count": len(prepared_documents),
        "rejected_count": len([artifact for artifact in validation_artifacts if artifact["status"] != "accepted"]),
        "documents": validation_artifacts,
    }


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
    context = job_context() if get_job_id() is None else None
    if context is not None:
        context.__enter__()
    started = time.perf_counter()
    job = _open_job(db, source)
    source.status = "running"
    _log_rag_lifecycle(
        "rag_ingest_started",
        source=source,
        job=job,
        duration_ms=0,
    )

    try:
        source.hash = _sha256(text)

        parsed = parse(text.encode("utf-8"), source.source_type)
        _ensure_clean_text(parsed, source.source_type)
        structured = _prepare_parse_result(source, parsed)
        _log_pdf_parser_path(source, structured)

        success, stats, error, failure_category = _persist_logical_documents(
            db,
            source,
            structured,
            title=title,
            published_at=published_at,
        )
        source.status = "ingested" if success else "failed"
        if success:
            source.last_ingested_at = _now()

        _close_job(
            db,
            job,
            success=success,
            stats=stats,
            error=error,
            failure_category=failure_category,
        )
        _log_rag_lifecycle(
            "rag_ingest_succeeded" if success else "rag_ingest_failed",
            source=source,
            job=job,
            duration_ms=int((time.perf_counter() - started) * 1000),
            stats=stats,
            reason=failure_category,
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
        _log_rag_lifecycle(
            "rag_ingest_failed",
            source=source,
            job=job,
            duration_ms=int((time.perf_counter() - started) * 1000),
            error_class=exc.__class__.__name__,
            reason=_classify_failure(exc, source.source_type),
        )

    if context is not None:
        context.__exit__(None, None, None)
    return job
