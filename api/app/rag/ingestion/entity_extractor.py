"""
Entity and concept extractor for RAG chunks (Issue 170).

Three-phase deterministic, alias-driven extraction:
  Phase 1 — Entity alias scan (regex boundary rules)
  Phase 2 — Capitalized surface form matching
  Phase 3 — Concept alias scan

Extraction is non-fatal: callers must wrap in try/except.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

EXTRACTOR_VERSION = "v1"
REGISTRY_VERSION = "2026-05-27"


# ── Regex for capitalized surface forms (imported from intent_router pattern) ─

_CAPITALIZED_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4}|[A-Z]{2,}(?:\s+[A-Z]{2,})*)\b"
)


# ── Pattern compilation ───────────────────────────────────────────────────────

def _compile_alias_pattern(alias: str, alias_type: Optional[str] = None) -> re.Pattern:
    """
    Compile a regex pattern for an alias with custom boundary rules.

    Rules:
    - Short tickers (alias_type='ticker', len <= 2): require non-alphanumeric on both sides.
    - Aliases with special chars (. / ' -): use re.escape + (?<![\\w]) / (?![\\w]) lookarounds.
    - Standard aliases: (?<![\\w.]) prefix, (?![\\w.]) suffix.
    """
    _SPECIAL = set("./'-")
    has_special = any(c in _SPECIAL for c in alias)

    if alias_type == "ticker" and len(alias) <= 2:
        # Strict boundary: surrounded by non-alphanumeric on both sides
        escaped = re.escape(alias)
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)

    if has_special:
        escaped = re.escape(alias)
        return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)

    # Standard boundary — neither preceded/followed by word char or dot
    escaped = re.escape(alias)
    return re.compile(rf"(?<![\w.]){escaped}(?![\w.])", re.IGNORECASE)


def _build_alias_patterns(
    aliases: list[tuple[str, str, Optional[str]]]
) -> dict[str, tuple[re.Pattern, str]]:
    """
    Build a dict of lowercase_alias -> (compiled_pattern, id) from
    a list of (alias, id, alias_type) tuples.
    """
    patterns: dict[str, tuple[re.Pattern, str]] = {}
    for alias, record_id, alias_type in aliases:
        lower = alias.lower()
        try:
            pat = _compile_alias_pattern(lower, alias_type=alias_type)
            patterns[lower] = (pat, record_id)
        except re.error as exc:
            log.warning("Failed to compile pattern for alias %r: %s", alias, exc)
    return patterns


# ── Registry loading ──────────────────────────────────────────────────────────

def _load_entity_alias_patterns(db: Session) -> dict[str, tuple[re.Pattern, str]]:
    """Load active entity aliases and return compiled patterns."""
    from sqlalchemy import text
    rows = db.execute(
        text("SELECT alias, entity_id, alias_type FROM rag_entity_aliases WHERE is_active = TRUE")
    ).fetchall()
    return _build_alias_patterns([(row[0], row[1], row[2]) for row in rows])


def _load_concept_alias_patterns(db: Session) -> dict[str, tuple[re.Pattern, str]]:
    """Load active concept aliases and return compiled patterns."""
    from sqlalchemy import text
    rows = db.execute(
        text("SELECT alias, concept_id, NULL FROM rag_concept_aliases WHERE is_active = TRUE")
    ).fetchall()
    return _build_alias_patterns([(row[0], row[1], None) for row in rows])


# ── Upsert helpers ────────────────────────────────────────────────────────────

def _upsert_chunk_entity(
    db: Session,
    chunk_id: str,
    entity_id: str,
    surface_text: Optional[str],
    confidence: float,
    extractor: str,
) -> None:
    from sqlalchemy import text
    db.execute(
        text(
            """
            INSERT INTO rag_chunk_entities (chunk_id, entity_id, surface_text, confidence, extractor)
            VALUES (:chunk_id, :entity_id, :surface_text, :confidence, :extractor)
            ON CONFLICT (chunk_id, entity_id) DO NOTHING
            """
        ),
        {
            "chunk_id": str(chunk_id),
            "entity_id": entity_id,
            "surface_text": surface_text,
            "confidence": confidence,
            "extractor": extractor,
        },
    )


def _upsert_chunk_concept(
    db: Session,
    chunk_id: str,
    concept_id: str,
    surface_text: Optional[str],
    confidence: float,
    extractor: str,
) -> None:
    from sqlalchemy import text
    db.execute(
        text(
            """
            INSERT INTO rag_chunk_concepts (chunk_id, concept_id, surface_text, confidence, extractor)
            VALUES (:chunk_id, :concept_id, :surface_text, :confidence, :extractor)
            ON CONFLICT (chunk_id, concept_id) DO NOTHING
            """
        ),
        {
            "chunk_id": str(chunk_id),
            "concept_id": concept_id,
            "surface_text": surface_text,
            "confidence": confidence,
            "extractor": extractor,
        },
    )


# ── Core extraction ───────────────────────────────────────────────────────────

def extract_entities_and_concepts(
    chunk_id: str,
    chunk_text: str,
    db: Session,
    *,
    entity_patterns: Optional[dict[str, tuple[re.Pattern, str]]] = None,
    concept_patterns: Optional[dict[str, tuple[re.Pattern, str]]] = None,
) -> dict[str, int]:
    """
    Run three-phase extraction against chunk_text.

    Returns dict with keys: entities_extracted_count, concepts_extracted_count.

    Pre-compiled patterns may be passed to avoid reloading the registry per chunk.
    """
    if entity_patterns is None:
        entity_patterns = _load_entity_alias_patterns(db)
    if concept_patterns is None:
        concept_patterns = _load_concept_alias_patterns(db)

    text_lower = chunk_text.lower()
    found_entities: set[str] = set()
    found_concepts: set[str] = set()

    # Phase 1: Entity alias scan
    for alias, (pattern, entity_id) in entity_patterns.items():
        if pattern.search(text_lower):
            _upsert_chunk_entity(
                db, chunk_id, entity_id, alias, 1.0, "alias_registry"
            )
            found_entities.add(entity_id)

    # Phase 2: Capitalized surface form matching
    alias_dict = {alias: eid for alias, (_, eid) in entity_patterns.items()}
    for match in _CAPITALIZED_ENTITY_RE.finditer(chunk_text):
        span = match.group(0).lower()
        if span in alias_dict:
            entity_id = alias_dict[span]
            if entity_id not in found_entities:
                _upsert_chunk_entity(
                    db, chunk_id, entity_id, match.group(0), 0.8, "surface_form"
                )
                found_entities.add(entity_id)

    # Phase 3: Concept alias scan
    for alias, (pattern, concept_id) in concept_patterns.items():
        if pattern.search(text_lower):
            _upsert_chunk_concept(
                db, chunk_id, concept_id, alias, 1.0, "concept_alias_registry"
            )
            found_concepts.add(concept_id)

    return {
        "entities_extracted_count": len(found_entities),
        "concepts_extracted_count": len(found_concepts),
    }


# ── Public ingestion hook ─────────────────────────────────────────────────────

def extract_and_store_chunk_annotations(
    chunk_id: str,
    chunk_text: str,
    db: Session,
    *,
    entity_patterns: Optional[dict[str, tuple[re.Pattern, str]]] = None,
    concept_patterns: Optional[dict[str, tuple[re.Pattern, str]]] = None,
) -> dict[str, Any]:
    """
    Run extraction and update chunk.metadata_json.

    Called from the ingestion pipeline after chunk persistence.
    Never raises — all exceptions are caught and logged at WARNING.
    """
    from sqlalchemy import text as sa_text

    counts = extract_entities_and_concepts(
        chunk_id,
        chunk_text,
        db,
        entity_patterns=entity_patterns,
        concept_patterns=concept_patterns,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    db.execute(
        sa_text(
            """
            UPDATE rag_chunks
            SET metadata_json = metadata_json || jsonb_build_object(
                'extraction_attempted', TRUE,
                'entities_extracted_count', :entities_count,
                'concepts_extracted_count', :concepts_count,
                'entity_concept_extractor_version', :extractor_version,
                'entity_concept_registry_version', :registry_version,
                'entity_concept_extracted_at', :extracted_at
            )
            WHERE id = :chunk_id
            """
        ),
        {
            "chunk_id": str(chunk_id),
            "entities_count": counts["entities_extracted_count"],
            "concepts_count": counts["concepts_extracted_count"],
            "extractor_version": EXTRACTOR_VERSION,
            "registry_version": REGISTRY_VERSION,
            "extracted_at": now_iso,
        },
    )

    return counts


def should_skip_chunk(chunk_metadata: dict) -> bool:
    """
    Return True if a chunk's stored extractor/registry versions match the current
    values and extraction has been attempted. Used by backfill to skip stale chunks.
    """
    return (
        chunk_metadata.get("extraction_attempted") is True
        and chunk_metadata.get("entity_concept_extractor_version") == EXTRACTOR_VERSION
        and chunk_metadata.get("entity_concept_registry_version") == REGISTRY_VERSION
    )
