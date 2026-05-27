"""
Backfill entity and concept annotations for existing RAG chunks (Issue 170).

Usage:
    python -m app.scripts.backfill_entity_concepts [options]

Flags:
    --dry-run           Print counts; do not write to DB.
    --author-id ID      Limit to one author's chunks.
    --batch-size N      Chunks per transaction (default: 200).
    --force             Reprocess chunks already at current extractor/registry version.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from app.db.session import SessionLocal
from app.rag.ingestion.entity_extractor import (
    EXTRACTOR_VERSION,
    REGISTRY_VERSION,
    _load_entity_alias_patterns,
    _load_concept_alias_patterns,
    extract_entities_and_concepts,
    should_skip_chunk,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _update_chunk_metadata(
    db,
    chunk_id: str,
    entities_count: int,
    concepts_count: int,
    now_iso: str,
) -> None:
    db.execute(
        text(
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
            "entities_count": entities_count,
            "concepts_count": concepts_count,
            "extractor_version": EXTRACTOR_VERSION,
            "registry_version": REGISTRY_VERSION,
            "extracted_at": now_iso,
        },
    )


def _build_chunk_query(author_id: Optional[str], offset: int, batch_size: int) -> tuple:
    """Return (sql_text, params) for fetching a batch of chunks."""
    if author_id:
        sql = text(
            """
            SELECT rc.id, rc.text, rc.metadata_json
            FROM rag_chunks rc
            JOIN rag_documents rd ON rd.id = rc.document_id
            WHERE rd.author_id = :author_id
            ORDER BY rc.id
            LIMIT :limit OFFSET :offset
            """
        )
        params = {"author_id": author_id, "limit": batch_size, "offset": offset}
    else:
        sql = text(
            """
            SELECT id, text, metadata_json
            FROM rag_chunks
            ORDER BY id
            LIMIT :limit OFFSET :offset
            """
        )
        params = {"limit": batch_size, "offset": offset}
    return sql, params


def run_backfill(
    *,
    dry_run: bool = False,
    author_id: Optional[str] = None,
    batch_size: int = 200,
    force: bool = False,
) -> dict:
    db = SessionLocal()
    try:
        entity_patterns = _load_entity_alias_patterns(db)
        concept_patterns = _load_concept_alias_patterns(db)
    except Exception as exc:
        log.error("Failed to load alias patterns: %s", exc)
        db.close()
        return {"error": str(exc)}

    total_processed = 0
    total_skipped = 0
    total_failed = 0
    total_entities = 0
    total_concepts = 0
    batch_num = 0
    offset = 0

    while True:
        sql, params = _build_chunk_query(author_id, offset, batch_size)

        try:
            rows = db.execute(sql, params).fetchall()
        except Exception as exc:
            log.error("Failed to fetch chunk batch at offset=%d: %s", offset, exc)
            break

        if not rows:
            break

        batch_num += 1
        batch_processed = 0
        batch_skipped = 0
        batch_failed = 0
        batch_entities = 0
        batch_concepts = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for row in rows:
            chunk_id = str(row[0])
            chunk_text = row[1] or ""
            chunk_meta = row[2] or {}
            if isinstance(chunk_meta, str):
                import json
                try:
                    chunk_meta = json.loads(chunk_meta)
                except Exception:
                    chunk_meta = {}

            if not force and should_skip_chunk(chunk_meta):
                batch_skipped += 1
                continue

            if dry_run:
                batch_processed += 1
                continue

            # Per-chunk savepoint for failure isolation
            try:
                db.execute(text(f"SAVEPOINT sp_chunk_{chunk_id.replace('-', '_')}"))
            except Exception:
                # Non-Postgres fallback: savepoints may not be supported; continue without
                pass

            try:
                counts = extract_entities_and_concepts(
                    chunk_id,
                    chunk_text,
                    db,
                    entity_patterns=entity_patterns,
                    concept_patterns=concept_patterns,
                )
                _update_chunk_metadata(
                    db,
                    chunk_id,
                    counts["entities_extracted_count"],
                    counts["concepts_extracted_count"],
                    now_iso,
                )
                try:
                    db.execute(text(f"RELEASE SAVEPOINT sp_chunk_{chunk_id.replace('-', '_')}"))
                except Exception:
                    pass
                batch_processed += 1
                batch_entities += counts["entities_extracted_count"]
                batch_concepts += counts["concepts_extracted_count"]
            except Exception as exc:
                log.warning("Chunk %s failed: %s", chunk_id, exc)
                try:
                    db.execute(text(f"ROLLBACK TO SAVEPOINT sp_chunk_{chunk_id.replace('-', '_')}"))
                    db.execute(text(f"RELEASE SAVEPOINT sp_chunk_{chunk_id.replace('-', '_')}"))
                except Exception:
                    pass
                batch_failed += 1

        if not dry_run:
            try:
                db.commit()
            except Exception as exc:
                log.error("Batch %d commit failed: %s", batch_num, exc)
                db.rollback()

        total_processed += batch_processed
        total_skipped += batch_skipped
        total_failed += batch_failed
        total_entities += batch_entities
        total_concepts += batch_concepts

        print(
            f"[backfill] batch={batch_num}"
            f"  processed={batch_processed}"
            f" entities={batch_entities}"
            f" concepts={batch_concepts}"
            f" skipped={batch_skipped}"
            f"  failed={batch_failed}"
        )

        offset += batch_size
        if len(rows) < batch_size:
            break

    db.close()

    summary = {
        "total_chunks": total_processed + total_skipped + total_failed,
        "total_entities": total_entities,
        "total_concepts": total_concepts,
        "skipped": total_skipped,
        "failed": total_failed,
        "dry_run": dry_run,
    }
    print(
        f"[backfill] DONE"
        f" total_chunks={summary['total_chunks']}"
        f" total_entities={total_entities}"
        f" total_concepts={total_concepts}"
        f" skipped={total_skipped}"
        f" failed={total_failed}"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill entity/concept annotations for RAG chunks."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts; do not write to DB.",
    )
    parser.add_argument(
        "--author-id",
        type=str,
        default=None,
        help="Limit backfill to chunks belonging to this author.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of chunks per transaction (default: 200).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess chunks even if already at current extractor/registry version.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_backfill(
        dry_run=args.dry_run,
        author_id=args.author_id,
        batch_size=args.batch_size,
        force=args.force,
    )


if __name__ == "__main__":
    main()
