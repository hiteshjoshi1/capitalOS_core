"""
Corpus-local expansion index builder (Issue 171).

For every (author, entity) and (author, concept) pair with sufficient chunk
coverage, compute NPMI co-occurrence statistics from the annotated corpus and
store the top expansion terms in ``rag_corpus_expansions``.

Usage:
    python -m app.scripts.compute_corpus_expansions [options]

Flags:
    --author-id ID    Limit computation to one author (default: all authors).
    --min-support N   Minimum co-occurrence count (default: 3).
    --min-npmi F      Minimum NPMI threshold (default: 0.10).
    --top-n N         Max expansion terms per pivot (default: 30).
    --dry-run         Print counts without writing to DB.
"""

from __future__ import annotations

import argparse
import logging
import math
import re
from collections import defaultdict
from typing import Optional

from sqlalchemy import text

from app.db.session import SessionLocal
from app.rag.retrieval import _FEEDBACK_STOPWORDS, _normalize_content_query

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


# ── N-gram helpers ─────────────────────────────────────────────────────────────

def _tokenize(text_str: str) -> list[str]:
    """Normalize chunk text and return a list of tokens using the existing normalizer."""
    normalized = _normalize_content_query(text_str)
    return normalized.split() if normalized else []


def _extract_ngrams(tokens: list[str], max_n: int = 3) -> set[str]:
    """Generate all 1/2/3-gram strings from a token list.

    An n-gram is kept only when at least one of its tokens is NOT a stopword.
    N-grams that consist entirely of stopwords or single-character tokens
    are discarded.
    """
    ngrams: set[str] = set()
    n = len(tokens)
    for size in range(1, max_n + 1):
        for i in range(n - size + 1):
            gram_tokens = tokens[i : i + size]
            # Keep the n-gram only if at least one token is a meaningful non-stopword
            if all(t in _FEEDBACK_STOPWORDS or len(t) <= 1 for t in gram_tokens):
                continue
            ngrams.add(" ".join(gram_tokens))
    return ngrams


# ── NPMI math ──────────────────────────────────────────────────────────────────

def compute_npmi(n_joint: int, n_pivot: int, n_t: int, N: int) -> Optional[float]:
    """Return the Normalised PMI for a (pivot, term) co-occurrence triple.

    Returns None when the computation is mathematically undefined (zero
    marginal probability or zero joint probability).

    Formula:
        P_joint = n_joint / N
        P_pivot = n_pivot / N
        P_t     = n_t     / N
        PMI     = log(P_joint / (P_pivot * P_t))
        NPMI    = PMI / -log(P_joint)       → range [-1, 1]

    Edge case: when P_joint = 1 (every chunk contains both), -log(P_joint) = 0.
    NPMI is defined as 1.0 in this degenerate case.
    """
    if N <= 0 or n_joint <= 0 or n_pivot <= 0 or n_t <= 0:
        return None
    p_joint = n_joint / N
    p_pivot = n_pivot / N
    p_t = n_t / N
    denominator = p_pivot * p_t
    if denominator <= 0:
        return None
    pmi = math.log(p_joint / denominator)
    log_p_joint = math.log(p_joint)
    if log_p_joint == 0:
        # Perfect co-occurrence: NPMI = 1
        return 1.0
    return pmi / (-log_p_joint)


# ── Core computation ───────────────────────────────────────────────────────────

def _load_author_ids(db, author_id: Optional[str] = None) -> list[str]:
    if author_id:
        row = db.execute(
            text("SELECT id FROM rag_authors WHERE id = :id"), {"id": author_id}
        ).fetchone()
        if row is None:
            log.warning("[expansion] author_id=%s not found; skipping", author_id)
            return []
        return [author_id]
    rows = db.execute(text("SELECT id FROM rag_authors ORDER BY id")).fetchall()
    return [r[0] for r in rows]


def _load_author_chunks(db, author_id: str) -> list[tuple[str, str]]:
    """Return list of (chunk_id, text) for all chunks of this author."""
    rows = db.execute(
        text(
            """
            SELECT rc.id, rc.text
            FROM rag_chunks rc
            JOIN rag_documents rd ON rd.id = rc.document_id
            WHERE rd.author_id = :author_id
            """
        ),
        {"author_id": author_id},
    ).fetchall()
    return [(str(r[0]), r[1] or "") for r in rows]


def _load_pivot_chunk_ids(db, author_id: str, pivot_type: str) -> dict[str, set[str]]:
    """Return {pivot_id: set(chunk_id)} for all pivots of this author."""
    result: dict[str, set[str]] = defaultdict(set)
    if pivot_type == "entity":
        rows = db.execute(
            text(
                """
                SELECT rce.entity_id, rce.chunk_id
                FROM rag_chunk_entities rce
                JOIN rag_chunks rc ON rc.id = rce.chunk_id
                JOIN rag_documents rd ON rd.id = rc.document_id
                WHERE rd.author_id = :author_id
                """
            ),
            {"author_id": author_id},
        ).fetchall()
    else:
        rows = db.execute(
            text(
                """
                SELECT rcc.concept_id, rcc.chunk_id
                FROM rag_chunk_concepts rcc
                JOIN rag_chunks rc ON rc.id = rcc.chunk_id
                JOIN rag_documents rd ON rd.id = rc.document_id
                WHERE rd.author_id = :author_id
                """
            ),
            {"author_id": author_id},
        ).fetchall()
    for pivot_id, chunk_id in rows:
        result[pivot_id].add(str(chunk_id))
    return result


def _compute_pivot_expansions(
    author_chunks: list[tuple[str, str]],
    pivot_chunk_ids: set[str],
    all_entity_pivot_ids: dict[str, set[str]],
    all_concept_pivot_ids: dict[str, set[str]],
    *,
    min_support: int,
    min_npmi: float,
    top_n: int,
    current_pivot_id: str,
    current_pivot_type: str,
) -> list[dict]:
    """Compute expansion terms for a single (author, pivot_type, pivot_id) triple.

    Returns a list of dicts ready for insertion, sorted by NPMI descending,
    capped at top_n.
    """
    N = len(author_chunks)
    if N == 0 or not pivot_chunk_ids:
        return []

    n_pivot = len(pivot_chunk_ids)

    # Build {chunk_id: set(ngrams)} and {chunk_id: ngrams list for text match}
    chunk_ngrams: dict[str, set[str]] = {}
    for chunk_id, chunk_text in author_chunks:
        tokens = _tokenize(chunk_text)
        chunk_ngrams[chunk_id] = _extract_ngrams(tokens)

    pivot_ngrams_union: set[str] = set()
    for cid in pivot_chunk_ids:
        pivot_ngrams_union |= chunk_ngrams.get(cid, set())

    # For each candidate n-gram term, count occurrences across author and pivot chunks.
    # Iterate over sorted terms to ensure deterministic ordering when NPMI values tie.
    phrase_scores: list[dict] = []

    for term in sorted(pivot_ngrams_union):
        n_joint = sum(1 for cid in pivot_chunk_ids if term in chunk_ngrams.get(cid, set()))
        if n_joint < min_support:
            continue
        n_t = sum(1 for cid, _ in author_chunks if term in chunk_ngrams.get(cid, set()))
        npmi_val = compute_npmi(n_joint, n_pivot, n_t, N)
        if npmi_val is None or npmi_val < min_npmi:
            continue
        phrase_scores.append(
            {
                "expansion_term": term,
                "expansion_type": "phrase",
                "expansion_ref_id": None,
                "support_count": n_joint,
                "npmi": npmi_val,
            }
        )

    # Entity co-expansion — iterate in sorted order for determinism
    for entity_id, entity_chunk_ids in sorted(all_entity_pivot_ids.items()):
        if entity_id == current_pivot_id and current_pivot_type == "entity":
            continue
        n_joint = len(pivot_chunk_ids & entity_chunk_ids)
        if n_joint < min_support:
            continue
        n_t = len(entity_chunk_ids)
        npmi_val = compute_npmi(n_joint, n_pivot, n_t, N)
        if npmi_val is None or npmi_val < min_npmi:
            continue
        phrase_scores.append(
            {
                "expansion_term": entity_id,
                "expansion_type": "entity",
                "expansion_ref_id": entity_id,
                "support_count": n_joint,
                "npmi": npmi_val,
            }
        )

    # Concept co-expansion — iterate in sorted order for determinism
    for concept_id, concept_chunk_ids in sorted(all_concept_pivot_ids.items()):
        if concept_id == current_pivot_id and current_pivot_type == "concept":
            continue
        n_joint = len(pivot_chunk_ids & concept_chunk_ids)
        if n_joint < min_support:
            continue
        n_t = len(concept_chunk_ids)
        npmi_val = compute_npmi(n_joint, n_pivot, n_t, N)
        if npmi_val is None or npmi_val < min_npmi:
            continue
        phrase_scores.append(
            {
                "expansion_term": concept_id,
                "expansion_type": "concept",
                "expansion_ref_id": concept_id,
                "support_count": n_joint,
                "npmi": npmi_val,
            }
        )

    # Deduplicate by expansion_term (keep highest NPMI)
    seen: dict[str, dict] = {}
    for row in phrase_scores:
        term = row["expansion_term"]
        if term not in seen or row["npmi"] > seen[term]["npmi"]:
            seen[term] = row

    # Sort by NPMI descending, then by expansion_term ascending to break ties
    # deterministically (ensures idempotent top-N selection across runs).
    ranked = sorted(seen.values(), key=lambda x: (-x["npmi"], x["expansion_term"]))
    return ranked[:top_n]


def _upsert_expansions(
    db,
    author_id: str,
    pivot_type: str,
    pivot_id: str,
    expansions: list[dict],
) -> int:
    """UPSERT expansion rows for one pivot. Returns number of rows written."""
    if not expansions:
        return 0
    written = 0
    for row in expansions:
        try:
            db.execute(text(f"SAVEPOINT sp_exp_{written}"))
        except Exception:
            pass
        try:
            db.execute(
                text(
                    """
                    INSERT INTO rag_corpus_expansions
                        (author_id, pivot_type, pivot_id, expansion_term,
                         expansion_type, expansion_ref_id, support_count, npmi, updated_at)
                    VALUES
                        (:author_id, :pivot_type, :pivot_id, :expansion_term,
                         :expansion_type, :expansion_ref_id, :support_count, :npmi, now())
                    ON CONFLICT (author_id, pivot_type, pivot_id, expansion_term)
                    DO UPDATE SET
                        expansion_type   = EXCLUDED.expansion_type,
                        expansion_ref_id = EXCLUDED.expansion_ref_id,
                        support_count    = EXCLUDED.support_count,
                        npmi             = EXCLUDED.npmi,
                        updated_at       = EXCLUDED.updated_at
                    """
                ),
                {
                    "author_id": author_id,
                    "pivot_type": pivot_type,
                    "pivot_id": pivot_id,
                    "expansion_term": row["expansion_term"],
                    "expansion_type": row["expansion_type"],
                    "expansion_ref_id": row.get("expansion_ref_id"),
                    "support_count": row["support_count"],
                    "npmi": row["npmi"],
                },
            )
            try:
                db.execute(text(f"RELEASE SAVEPOINT sp_exp_{written}"))
            except Exception:
                pass
            written += 1
        except Exception as exc:
            log.warning(
                "[expansion] upsert failed author=%s pivot=%s/%s term=%s: %s",
                author_id,
                pivot_type,
                pivot_id,
                row["expansion_term"],
                exc,
            )
            try:
                db.execute(text(f"ROLLBACK TO SAVEPOINT sp_exp_{written}"))
                db.execute(text(f"RELEASE SAVEPOINT sp_exp_{written}"))
            except Exception:
                pass
    return written


# ── Main runner ────────────────────────────────────────────────────────────────

def run_compute(
    *,
    author_id: Optional[str] = None,
    min_support: int = 3,
    min_npmi: float = 0.10,
    top_n: int = 30,
    dry_run: bool = False,
) -> dict:
    db = SessionLocal()
    total_authors = 0
    total_pivots = 0
    total_terms = 0

    try:
        author_ids = _load_author_ids(db, author_id)
        if not author_ids:
            log.info("[expansion] no authors found; nothing to compute")
            return {"authors": 0, "pivots": 0, "terms_stored": 0, "dry_run": dry_run}

        for aid in author_ids:
            author_chunks = _load_author_chunks(db, aid)
            if not author_chunks:
                log.info("[expansion] author=%s has no chunks; skipping", aid)
                continue

            # Load pivot maps for both entity and concept pivots for this author
            entity_pivot_map = _load_pivot_chunk_ids(db, aid, "entity")
            concept_pivot_map = _load_pivot_chunk_ids(db, aid, "concept")

            if not entity_pivot_map and not concept_pivot_map:
                log.info(
                    "[expansion] author=%s has no annotated chunks; skipping", aid
                )
                continue

            total_authors += 1
            author_terms = 0

            # Process entity pivots
            for pivot_id, pivot_chunk_ids in entity_pivot_map.items():
                if len(pivot_chunk_ids) < min_support:
                    continue
                expansions = _compute_pivot_expansions(
                    author_chunks,
                    pivot_chunk_ids,
                    entity_pivot_map,
                    concept_pivot_map,
                    min_support=min_support,
                    min_npmi=min_npmi,
                    top_n=top_n,
                    current_pivot_id=pivot_id,
                    current_pivot_type="entity",
                )
                print(
                    f"[expansion] author={aid}"
                    f"  entity={pivot_id}"
                    f"  pivot_chunks={len(pivot_chunk_ids)}"
                    f"  expansion_terms={len(expansions)}"
                )
                if not dry_run and expansions:
                    written = _upsert_expansions(db, aid, "entity", pivot_id, expansions)
                    db.commit()
                    author_terms += written
                    total_terms += written
                elif dry_run:
                    total_terms += len(expansions)
                total_pivots += 1

            # Process concept pivots
            for pivot_id, pivot_chunk_ids in concept_pivot_map.items():
                if len(pivot_chunk_ids) < min_support:
                    continue
                expansions = _compute_pivot_expansions(
                    author_chunks,
                    pivot_chunk_ids,
                    entity_pivot_map,
                    concept_pivot_map,
                    min_support=min_support,
                    min_npmi=min_npmi,
                    top_n=top_n,
                    current_pivot_id=pivot_id,
                    current_pivot_type="concept",
                )
                print(
                    f"[expansion] author={aid}"
                    f"  concept={pivot_id}"
                    f"  pivot_chunks={len(pivot_chunk_ids)}"
                    f"  expansion_terms={len(expansions)}"
                )
                if not dry_run and expansions:
                    written = _upsert_expansions(db, aid, "concept", pivot_id, expansions)
                    db.commit()
                    author_terms += written
                    total_terms += written
                elif dry_run:
                    total_terms += len(expansions)
                total_pivots += 1

        print(
            f"[expansion] DONE"
            f" authors={total_authors}"
            f" pivots={total_pivots}"
            f" terms_stored={total_terms}"
        )
        return {
            "authors": total_authors,
            "pivots": total_pivots,
            "terms_stored": total_terms,
            "dry_run": dry_run,
        }

    except Exception as exc:
        log.error("[expansion] fatal error: %s", exc)
        db.rollback()
        raise
    finally:
        db.close()


# ── CLI ────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute corpus-local NPMI expansion index for RAG retrieval."
    )
    parser.add_argument(
        "--author-id",
        type=str,
        default=None,
        help="Limit computation to one author (default: all).",
    )
    parser.add_argument(
        "--min-support",
        type=int,
        default=3,
        help="Minimum co-occurrence count to include a term (default: 3).",
    )
    parser.add_argument(
        "--min-npmi",
        type=float,
        default=0.10,
        help="Minimum NPMI threshold (default: 0.10).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=30,
        help="Max expansion terms per pivot (default: 30).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print counts without writing to DB.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_compute(
        author_id=args.author_id,
        min_support=args.min_support,
        min_npmi=args.min_npmi,
        top_n=args.top_n,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
