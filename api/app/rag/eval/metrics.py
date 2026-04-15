"""
Standard Information Retrieval metrics for RAG evaluation.

All functions are pure (no DB dependency) and operate on lists of string IDs.

Grading scale for relevance_grade in rag_eval_golden:
  0 = irrelevant
  1 = partially relevant
  2 = relevant
  3 = highly relevant
"""

from __future__ import annotations

import math


def ndcg_at_k(
    retrieved_ids: list[str],
    golden: dict[str, int],
    k: int = 10,
) -> float:
    """
    Normalized Discounted Cumulative Gain at k.

    Args:
        retrieved_ids: Ordered list of chunk IDs returned by the retrieval system.
        golden: Mapping of chunk_id → relevance_grade (0-3). Chunks absent from
                this dict are treated as relevance_grade=0.
        k: Cut-off rank.

    Returns:
        NDCG@k in [0.0, 1.0].
    """
    if not retrieved_ids or not golden:
        return 0.0

    def dcg(ranked: list[str], grades: dict[str, int], cut: int) -> float:
        total = 0.0
        for i, chunk_id in enumerate(ranked[:cut], start=1):
            grade = grades.get(chunk_id, 0)
            total += (2 ** grade - 1) / math.log2(i + 1)
        return total

    ideal_ranked = sorted(golden.keys(), key=lambda cid: golden[cid], reverse=True)
    ideal = dcg(ideal_ranked, golden, k)
    if ideal == 0.0:
        return 0.0
    return dcg(retrieved_ids, golden, k) / ideal


def recall_at_k(
    retrieved_ids: list[str],
    golden_ids: set[str],
    k: int = 10,
) -> float:
    """
    Fraction of relevant passages found in the top-k retrieved results.

    Args:
        retrieved_ids: Ordered list of chunk IDs.
        golden_ids: Set of relevant chunk IDs (relevance_grade >= 1).
        k: Cut-off rank.

    Returns:
        Recall@k in [0.0, 1.0].
    """
    if not golden_ids:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(top_k & golden_ids) / len(golden_ids)


def precision_at_k(
    retrieved_ids: list[str],
    golden_ids: set[str],
    k: int = 10,
) -> float:
    """
    Fraction of the top-k retrieved results that are relevant.

    Args:
        retrieved_ids: Ordered list of chunk IDs.
        golden_ids: Set of relevant chunk IDs.
        k: Cut-off rank.

    Returns:
        Precision@k in [0.0, 1.0].
    """
    if not retrieved_ids or not golden_ids:
        return 0.0
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for cid in top_k if cid in golden_ids)
    return hits / len(top_k)


def mrr(
    retrieved_ids: list[str],
    golden_ids: set[str],
) -> float:
    """
    Mean Reciprocal Rank — reciprocal of the rank of the first relevant result.

    Args:
        retrieved_ids: Ordered list of chunk IDs.
        golden_ids: Set of relevant chunk IDs.

    Returns:
        MRR in (0.0, 1.0], or 0.0 if no relevant result is found.
    """
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in golden_ids:
            return 1.0 / rank
    return 0.0
