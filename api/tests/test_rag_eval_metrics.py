"""
Unit tests for RAG evaluation IR metrics.

Tests use known rankings with pre-computed expected scores to verify
correctness of NDCG@k, Recall@k, Precision@k, and MRR.
"""

from __future__ import annotations

import math
import pytest

from app.rag.eval.metrics import ndcg_at_k, recall_at_k, precision_at_k, mrr


# ── NDCG@k ────────────────────────────────────────────────────────────────────


class TestNdcgAtK:
    def test_perfect_ranking(self):
        """When the retrieval order matches the ideal order, NDCG should be 1.0."""
        retrieved = ["a", "b", "c"]
        golden = {"a": 3, "b": 2, "c": 1}
        assert ndcg_at_k(retrieved, golden, k=3) == pytest.approx(1.0, abs=1e-9)

    def test_reverse_ranking(self):
        """Worst possible order should produce NDCG < 1."""
        retrieved = ["c", "b", "a"]
        golden = {"a": 3, "b": 2, "c": 1}
        score = ndcg_at_k(retrieved, golden, k=3)
        assert 0.0 < score < 1.0

    def test_single_relevant_first(self):
        """One highly relevant result in position 1 gives NDCG=1.0."""
        retrieved = ["a", "x", "y"]
        golden = {"a": 3}
        assert ndcg_at_k(retrieved, golden, k=3) == pytest.approx(1.0, abs=1e-9)

    def test_single_relevant_second(self):
        """One highly relevant result in position 2 gives NDCG = 1/log2(3)."""
        retrieved = ["x", "a", "y"]
        golden = {"a": 3}
        # DCG = (2^3 - 1)/log2(3) = 7/1.585 ≈ 4.416
        # IDCG = (2^3 - 1)/log2(2) = 7/1 = 7
        expected = (7.0 / math.log2(3)) / 7.0
        assert ndcg_at_k(retrieved, golden, k=3) == pytest.approx(expected, rel=1e-6)

    def test_no_golden(self):
        assert ndcg_at_k(["a", "b"], {}, k=5) == 0.0

    def test_empty_retrieved(self):
        assert ndcg_at_k([], {"a": 2}, k=5) == 0.0

    def test_cutoff_respected(self):
        """Results beyond k should not contribute."""
        retrieved = ["x", "y", "a"]
        golden = {"a": 3}
        # 'a' is at rank 3, but k=2 — should not be seen.
        assert ndcg_at_k(retrieved, golden, k=2) == 0.0

    def test_mixed_relevance(self):
        """Known computation for mixed grades."""
        retrieved = ["a", "b", "c", "d"]
        golden = {"a": 2, "c": 1}
        # DCG: (2^2-1)/log2(2) + 0 + (2^1-1)/log2(4) = 3/1 + 1/2 = 3.5
        # IDCG: (2^2-1)/log2(2) + (2^1-1)/log2(3) = 3 + 0.6309 = 3.6309
        expected = 3.5 / (3.0 + 1.0 / math.log2(3))
        assert ndcg_at_k(retrieved, golden, k=4) == pytest.approx(expected, rel=1e-5)


# ── Recall@k ──────────────────────────────────────────────────────────────────


class TestRecallAtK:
    def test_all_found(self):
        assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == pytest.approx(1.0)

    def test_none_found(self):
        assert recall_at_k(["x", "y", "z"], {"a", "b"}, k=3) == pytest.approx(0.0)

    def test_partial_recall(self):
        assert recall_at_k(["a", "x", "z"], {"a", "b"}, k=3) == pytest.approx(0.5)

    def test_cutoff_excludes_relevant(self):
        assert recall_at_k(["x", "y", "a", "b"], {"a", "b"}, k=2) == pytest.approx(0.0)

    def test_empty_golden(self):
        assert recall_at_k(["a", "b"], set(), k=5) == 0.0

    def test_k_larger_than_list(self):
        assert recall_at_k(["a"], {"a", "b"}, k=100) == pytest.approx(0.5)


# ── Precision@k ───────────────────────────────────────────────────────────────


class TestPrecisionAtK:
    def test_all_relevant(self):
        assert precision_at_k(["a", "b", "c"], {"a", "b", "c"}, k=3) == pytest.approx(1.0)

    def test_none_relevant(self):
        assert precision_at_k(["x", "y"], {"a", "b"}, k=2) == pytest.approx(0.0)

    def test_half_relevant(self):
        assert precision_at_k(["a", "x"], {"a", "b"}, k=2) == pytest.approx(0.5)

    def test_empty_retrieved(self):
        assert precision_at_k([], {"a"}, k=5) == 0.0

    def test_empty_golden(self):
        assert precision_at_k(["a", "b"], set(), k=2) == 0.0

    def test_cutoff(self):
        assert precision_at_k(["a", "b", "x", "y"], {"a", "b"}, k=2) == pytest.approx(1.0)


# ── MRR ───────────────────────────────────────────────────────────────────────


class TestMrr:
    def test_first_relevant_at_rank_1(self):
        assert mrr(["a", "b", "c"], {"a"}) == pytest.approx(1.0)

    def test_first_relevant_at_rank_2(self):
        assert mrr(["x", "a", "c"], {"a"}) == pytest.approx(0.5)

    def test_first_relevant_at_rank_3(self):
        assert mrr(["x", "y", "a"], {"a"}) == pytest.approx(1 / 3)

    def test_no_relevant(self):
        assert mrr(["x", "y", "z"], {"a"}) == pytest.approx(0.0)

    def test_empty_retrieved(self):
        assert mrr([], {"a"}) == 0.0

    def test_empty_golden(self):
        assert mrr(["a", "b"], set()) == 0.0

    def test_multiple_relevant_uses_first(self):
        """MRR is based on the *first* relevant, not the highest-graded."""
        assert mrr(["x", "a", "b"], {"a", "b"}) == pytest.approx(0.5)
