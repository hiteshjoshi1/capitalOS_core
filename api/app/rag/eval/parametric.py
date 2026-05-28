"""
Structural recall eval suite for RAG entity/concept pool wiring (Issue 172).

These tests verify that the annotation-based retrieval pools are correctly wired:
  - entity_annotation_pool retrieves chunks annotated with the queried entity_id
  - concept_annotation_pool retrieves chunks annotated with the queried concept_id

IMPORTANT: These are structural wiring tests, NOT retrieval quality tests.
  - The gold set IS the annotation set — they prove the JOIN works, not semantic quality.
  - Results are reported separately under mode='structural_recall'.
  - They do NOT affect the no-regression gate thresholds on the hand-labeled golden set.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


@dataclass
class StructuralRecallCase:
    """Generated structural recall case with explicit author/pivot metadata."""

    query_text: str
    author_id: str
    pivot_type: str  # 'entity' or 'concept'
    pivot_id: str
    gold_chunk_ids: list[str]


@dataclass
class StructuralRecallResult:
    """Result for one structural recall test case."""

    query_text: str
    author_id: str
    pivot_type: str  # 'entity' or 'concept'
    pivot_id: str
    gold_chunk_ids: list[str]
    candidate_entity_pool_size: int = 0
    passed: bool = False
    failure_reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query_text,
            "author_id": self.author_id,
            "pivot_type": self.pivot_type,
            "pivot_id": self.pivot_id,
            "gold_chunk_count": len(self.gold_chunk_ids),
            "candidate_entity_pool_size": self.candidate_entity_pool_size,
            "passed": self.passed,
            "failure_reason": self.failure_reason,
        }


@dataclass
class StructuralRecallReport:
    """Aggregate report for a structural recall eval run."""

    total_tests: int
    passed: int
    failed: int
    authors_covered: list[str]
    results: list[StructuralRecallResult] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": "structural_recall",
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": round(self.passed / max(self.total_tests, 1), 4),
            "authors_covered": sorted(self.authors_covered),
            "results": [r.as_dict() for r in self.results],
        }


def generate_entity_structural_recall_tests(
    db: Session,
    *,
    min_chunks: int = 5,
) -> list[StructuralRecallCase]:
    """
    For each (author, entity) pair where annotation count >= min_chunks:
      - query: "What does {author_display_name} say about {entity_canonical_name}?"
      - gold_chunk_ids: all chunk_ids annotated with entity_id for this author.
    Mode: structural_recall. Not counted in quality eval.
    """
    try:
        rows = db.execute(
            text("""
                SELECT
                    COALESCE(rd.author_id, rs.author_id) AS author_id,
                    ra.name                               AS author_name,
                    rce.entity_id,
                    re.canonical_name                     AS entity_name,
                    COUNT(DISTINCT rce.chunk_id)          AS chunk_count
                FROM rag_chunk_entities rce
                JOIN rag_chunks rc       ON rc.id = rce.chunk_id
                JOIN rag_documents rd    ON rd.id = rc.document_id
                JOIN rag_sources rs      ON rs.id = rd.source_id
                JOIN rag_authors ra      ON ra.id = COALESCE(rd.author_id, rs.author_id)
                JOIN rag_entities re     ON re.id = rce.entity_id
                GROUP BY COALESCE(rd.author_id, rs.author_id), ra.name, rce.entity_id, re.canonical_name
                HAVING COUNT(DISTINCT rce.chunk_id) >= :min_chunks
                ORDER BY COUNT(DISTINCT rce.chunk_id) DESC
            """),
            {"min_chunks": min_chunks},
        ).fetchall()
    except Exception:
        log.debug("generate_entity_structural_recall_tests: DB query failed", exc_info=True)
        return []

    queries: list[StructuralRecallCase] = []
    for row in rows:
        author_id = row.author_id
        author_name = row.author_name or author_id
        entity_id = row.entity_id
        entity_name = row.entity_name or entity_id

        # Fetch all chunk IDs for this (author, entity) pair
        try:
            chunk_rows = db.execute(
                text("""
                    SELECT DISTINCT rce.chunk_id::text
                    FROM rag_chunk_entities rce
                    JOIN rag_chunks rc    ON rc.id = rce.chunk_id
                    JOIN rag_documents rd ON rd.id = rc.document_id
                    JOIN rag_sources rs   ON rs.id = rd.source_id
                    WHERE rce.entity_id = :entity_id
                      AND COALESCE(rd.author_id, rs.author_id) = :author_id
                """),
                {"entity_id": entity_id, "author_id": author_id},
            ).fetchall()
        except Exception:
            log.debug("generate_entity_structural_recall_tests: chunk fetch failed", exc_info=True)
            continue

        gold_chunk_ids = [r.chunk_id for r in chunk_rows]
        query_text = f"What does {author_name} say about {entity_name}?"
        queries.append(
            StructuralRecallCase(
                query_text=query_text,
                author_id=author_id,
                pivot_type="entity",
                pivot_id=entity_id,
                gold_chunk_ids=gold_chunk_ids,
            )
        )

    return queries


def generate_concept_structural_recall_tests(
    db: Session,
    *,
    min_chunks: int = 5,
) -> list[StructuralRecallCase]:
    """
    For each (author, concept) pair where annotation count >= min_chunks:
      - query: "What does {author_display_name} discuss about {concept_canonical_name}?"
      - gold_chunk_ids: all chunk_ids annotated with concept_id for this author.
    Mode: structural_recall. Not counted in quality eval.
    """
    try:
        rows = db.execute(
            text("""
                SELECT
                    COALESCE(rd.author_id, rs.author_id) AS author_id,
                    ra.name                               AS author_name,
                    rcc.concept_id,
                    rc2.canonical_name                    AS concept_name,
                    COUNT(DISTINCT rcc.chunk_id)          AS chunk_count
                FROM rag_chunk_concepts rcc
                JOIN rag_chunks rc       ON rc.id = rcc.chunk_id
                JOIN rag_documents rd    ON rd.id = rc.document_id
                JOIN rag_sources rs      ON rs.id = rd.source_id
                JOIN rag_authors ra      ON ra.id = COALESCE(rd.author_id, rs.author_id)
                JOIN rag_concepts rc2    ON rc2.id = rcc.concept_id
                GROUP BY COALESCE(rd.author_id, rs.author_id), ra.name, rcc.concept_id, rc2.canonical_name
                HAVING COUNT(DISTINCT rcc.chunk_id) >= :min_chunks
                ORDER BY COUNT(DISTINCT rcc.chunk_id) DESC
            """),
            {"min_chunks": min_chunks},
        ).fetchall()
    except Exception:
        log.debug("generate_concept_structural_recall_tests: DB query failed", exc_info=True)
        return []

    queries: list[StructuralRecallCase] = []
    for row in rows:
        author_id = row.author_id
        author_name = row.author_name or author_id
        concept_id = row.concept_id
        concept_name = row.concept_name or concept_id

        try:
            chunk_rows = db.execute(
                text("""
                    SELECT DISTINCT rcc.chunk_id::text
                    FROM rag_chunk_concepts rcc
                    JOIN rag_chunks rc    ON rc.id = rcc.chunk_id
                    JOIN rag_documents rd ON rd.id = rc.document_id
                    JOIN rag_sources rs   ON rs.id = rd.source_id
                    WHERE rcc.concept_id = :concept_id
                      AND COALESCE(rd.author_id, rs.author_id) = :author_id
                """),
                {"concept_id": concept_id, "author_id": author_id},
            ).fetchall()
        except Exception:
            log.debug("generate_concept_structural_recall_tests: chunk fetch failed", exc_info=True)
            continue

        gold_chunk_ids = [r.chunk_id for r in chunk_rows]
        query_text = f"What does {author_name} discuss about {concept_name}?"
        queries.append(
            StructuralRecallCase(
                query_text=query_text,
                author_id=author_id,
                pivot_type="concept",
                pivot_id=concept_id,
                gold_chunk_ids=gold_chunk_ids,
            )
        )

    return queries


def run_structural_recall_eval(db: Session) -> StructuralRecallReport:
    """
    Run the full structural recall eval: generate tests, call retrieve_by_entity_ids
    for each (author, entity) test, and assert candidate_entity_pool_size >= 3.

    This is a wiring test only — it does not measure semantic quality.
    """
    from app.rag.retrieval import retrieve_by_entity_ids, retrieve_by_concept_ids

    entity_tests = generate_entity_structural_recall_tests(db, min_chunks=5)
    concept_tests = generate_concept_structural_recall_tests(db, min_chunks=5)
    all_tests = entity_tests + concept_tests
    results: list[StructuralRecallResult] = []

    for case in entity_tests:
        if not case.gold_chunk_ids:
            continue

        # Call the entity pool and check candidate size
        pool_chunks = retrieve_by_entity_ids(
            [case.pivot_id],
            db,
            author_ids=[case.author_id] if case.author_id else None,
            top_k=50,
        )
        pool_size = len(pool_chunks)
        passed = pool_size >= 3
        failure_reason = None if passed else f"entity_pool_size={pool_size} < 3 (wiring failure)"

        results.append(
            StructuralRecallResult(
                query_text=case.query_text,
                author_id=case.author_id or "",
                pivot_type="entity",
                pivot_id=case.pivot_id,
                gold_chunk_ids=case.gold_chunk_ids,
                candidate_entity_pool_size=pool_size,
                passed=passed,
                failure_reason=failure_reason,
            )
        )

    for case in concept_tests:
        if not case.gold_chunk_ids:
            continue

        pool_chunks = retrieve_by_concept_ids(
            [case.pivot_id],
            db,
            author_ids=[case.author_id] if case.author_id else None,
            top_k=50,
        )
        pool_size = len(pool_chunks)
        passed = pool_size >= 3
        failure_reason = None if passed else f"concept_pool_size={pool_size} < 3 (wiring failure)"

        results.append(
            StructuralRecallResult(
                query_text=case.query_text,
                author_id=case.author_id or "",
                pivot_type="concept",
                pivot_id=case.pivot_id,
                gold_chunk_ids=case.gold_chunk_ids,
                candidate_entity_pool_size=pool_size,
                passed=passed,
                failure_reason=failure_reason,
            )
        )

    authors_covered = sorted({r.author_id for r in results if r.author_id})
    passed_count = sum(1 for r in results if r.passed)
    return StructuralRecallReport(
        total_tests=len(results),
        passed=passed_count,
        failed=len(results) - passed_count,
        authors_covered=authors_covered,
        results=results,
    )
