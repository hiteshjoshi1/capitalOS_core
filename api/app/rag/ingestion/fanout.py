from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from app.rag.ingestion.parser import DocumentSection, StructuredParseResult
from app.rag.ingestion.selector import SelectiveIngestionOptions, apply_selective_options

INGESTION_MODE_SINGLE_WORK = "single_work"
INGESTION_MODE_FANOUT = "fanout"


def _parse_date(value: Any) -> Optional[date]:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@dataclass
class LogicalDocumentSpec:
    key: str
    title: Optional[str] = None
    author_id: Optional[str] = None
    published_at: Optional[date] = None
    publication_year: Optional[int] = None
    venue: Optional[str] = None
    collection: Optional[str] = None
    canonical_work_id: Optional[str] = None
    canonical_status: Optional[str] = None
    dedupe_priority: Optional[int] = None
    source_section: Optional[str] = None
    note_taker: Optional[str] = None
    work_type: Optional[str] = None
    parent_key: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    selective_options: SelectiveIngestionOptions = field(default_factory=SelectiveIngestionOptions)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], index: int) -> "LogicalDocumentSpec":
        key = str(payload.get("key") or f"document-{index}")
        known_keys = {
            "key",
            "title",
            "author_id",
            "published_at",
            "publication_year",
            "year",
            "venue",
            "collection",
            "canonical_work_id",
            "canonical_status",
            "dedupe_priority",
            "source_section",
            "note_taker",
            "work_type",
            "parent_key",
            "metadata",
            "selective_options",
        }
        metadata = dict(payload.get("metadata") or {})
        metadata.update({k: v for k, v in payload.items() if k not in known_keys and v is not None})
        year_value = payload.get("publication_year", payload.get("year"))
        return cls(
            key=key,
            title=payload.get("title"),
            author_id=payload.get("author_id"),
            published_at=_parse_date(payload.get("published_at")),
            publication_year=int(year_value) if year_value not in (None, "") else None,
            venue=payload.get("venue"),
            collection=payload.get("collection"),
            canonical_work_id=payload.get("canonical_work_id"),
            canonical_status=payload.get("canonical_status"),
            dedupe_priority=int(payload["dedupe_priority"]) if payload.get("dedupe_priority") is not None else None,
            source_section=payload.get("source_section"),
            note_taker=payload.get("note_taker"),
            work_type=payload.get("work_type"),
            parent_key=payload.get("parent_key"),
            metadata=metadata,
            selective_options=SelectiveIngestionOptions.from_dict(payload.get("selective_options") or {}),
        )


@dataclass
class LogicalDocumentPlan:
    key: str
    index: int
    title: Optional[str]
    author_id: Optional[str]
    published_at: Optional[date]
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
    selective_options: SelectiveIngestionOptions
    selected_sections: list[DocumentSection]
    raw_text: str
    clean_text: str


@dataclass
class FanoutPlan:
    mode: str
    shared_sections: list[DocumentSection]
    documents: list[LogicalDocumentPlan]


def build_selected_text(sections: list[DocumentSection]) -> str:
    parts: list[str] = []
    for section in sections:
        heading = (section.heading or "").strip()
        content = (section.table_markdown or section.content or "").strip()
        if heading:
            parts.append(heading)
        if content:
            parts.append(content)
    return "\n\n".join(part for part in parts if part).strip()


def build_fanout_plan(
    parsed: StructuredParseResult,
    *,
    source_author_id: str,
    source_title: Optional[str],
    source_published_at: Optional[date],
    source_selective_options: Optional[SelectiveIngestionOptions],
    ingestion_config: Optional[dict[str, Any]],
) -> FanoutPlan:
    sections = list(parsed.sections or [])
    if source_selective_options and not source_selective_options.is_empty():
        sections = apply_selective_options(sections, source_selective_options)

    config = dict(ingestion_config or {})
    mode = str(config.get("mode") or INGESTION_MODE_SINGLE_WORK)
    if mode != INGESTION_MODE_FANOUT:
        clean_text = build_selected_text(sections) if sections else parsed.clean_text.strip()
        raw_text = clean_text or parsed.raw_text.strip()
        return FanoutPlan(
            mode=INGESTION_MODE_SINGLE_WORK,
            shared_sections=sections,
            documents=[
                LogicalDocumentPlan(
                    key="document-0",
                    index=0,
                    title=source_title or parsed.doc_metadata.get("title"),
                    author_id=source_author_id,
                    published_at=source_published_at,
                    publication_year=source_published_at.year if source_published_at else None,
                    venue=None,
                    collection=None,
                    canonical_work_id=None,
                    canonical_status=None,
                    dedupe_priority=None,
                    source_section=None,
                    note_taker=None,
                    work_type=None,
                    parent_key=None,
                    metadata={},
                    selective_options=SelectiveIngestionOptions(),
                    selected_sections=sections,
                    raw_text=raw_text,
                    clean_text=clean_text,
                )
            ],
        )

    documents_payload = list(config.get("documents") or [])
    if not documents_payload:
        raise RuntimeError("Fanout ingestion requires at least one logical document definition")
    if not sections:
        raise RuntimeError("Fanout ingestion requires structured sections from the parsed source")

    planned_documents: list[LogicalDocumentPlan] = []
    for index, payload in enumerate(documents_payload):
        spec = LogicalDocumentSpec.from_dict(payload, index)
        planned_documents.append(
            LogicalDocumentPlan(
                key=spec.key,
                index=index,
                title=spec.title or parsed.doc_metadata.get("title"),
                author_id=spec.author_id or source_author_id,
                published_at=spec.published_at,
                publication_year=spec.publication_year or (spec.published_at.year if spec.published_at else None),
                venue=spec.venue,
                collection=spec.collection,
                canonical_work_id=spec.canonical_work_id,
                canonical_status=spec.canonical_status,
                dedupe_priority=spec.dedupe_priority,
                source_section=spec.source_section,
                note_taker=spec.note_taker,
                work_type=spec.work_type,
                parent_key=spec.parent_key,
                metadata=spec.metadata,
                selective_options=spec.selective_options,
                selected_sections=[],
                raw_text="",
                clean_text="",
            )
        )

    return FanoutPlan(mode=INGESTION_MODE_FANOUT, shared_sections=sections, documents=planned_documents)
