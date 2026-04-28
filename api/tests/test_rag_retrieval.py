"""
Tests for hybrid dense+sparse retrieval (Issue 142).

Coverage:
  - reciprocal_rank_fusion() — pure Python, deterministic, no DB
  - retrieve_keyword_chunks() — skipped on non-Postgres backends
  - retrieve_hybrid() — falls back gracefully to dense on non-Postgres
  - RetrievedChunk.as_dict() includes rrf_score and ts_rank fields
  - Config env vars respected (RAG_RETRIEVAL_MODE)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_retrieval_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_chunk(
    chunk_id: str,
    text: str = "sample text",
    cosine_distance: float = 0.2,
    ts_rank: Optional[float] = None,
    rrf_score: Optional[float] = None,
    reranker_score: Optional[float] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Any:
    from app.rag.retrieval import RetrievedChunk

    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id="doc-1",
        chunk_index=0,
        text=text,
        token_count=10,
        metadata_json=metadata or {},
        cosine_distance=cosine_distance,
        ts_rank=ts_rank,
        rrf_score=rrf_score,
        reranker_score=reranker_score,
    )


# ── RRF tests (pure Python, no DB) ───────────────────────────────────────────


class TestReciprocalRankFusion:
    def test_single_list_preserves_order(self):
        from app.rag.retrieval import reciprocal_rank_fusion

        chunks = [_make_chunk("a"), _make_chunk("b"), _make_chunk("c")]
        result = reciprocal_rank_fusion(chunks)
        ids = [c.chunk_id for c in result]
        assert ids == ["a", "b", "c"]

    def test_two_lists_boost_shared_hits(self):
        from app.rag.retrieval import reciprocal_rank_fusion

        # "b" appears in both lists → should rank highest
        dense = [_make_chunk("a"), _make_chunk("b"), _make_chunk("c")]
        sparse = [_make_chunk("b"), _make_chunk("d"), _make_chunk("e")]
        result = reciprocal_rank_fusion(dense, sparse)
        assert result[0].chunk_id == "b", "chunk appearing in both lists should rank first"

    def test_rrf_scores_populated(self):
        from app.rag.retrieval import reciprocal_rank_fusion

        dense = [_make_chunk("a"), _make_chunk("b")]
        sparse = [_make_chunk("b"), _make_chunk("c")]
        result = reciprocal_rank_fusion(dense, sparse)
        for chunk in result:
            assert chunk.rrf_score is not None
            assert chunk.rrf_score > 0.0

    def test_empty_lists_returns_empty(self):
        from app.rag.retrieval import reciprocal_rank_fusion

        result = reciprocal_rank_fusion([], [])
        assert result == []

    def test_rrf_k_constant_affects_scores(self):
        from app.rag.retrieval import reciprocal_rank_fusion

        chunks = [_make_chunk("a")]
        result_k10 = reciprocal_rank_fusion(chunks, k=10)
        result_k100 = reciprocal_rank_fusion(chunks, k=100)
        # k=10 → 1/(10+1)=0.0909; k=100 → 1/(100+1)=0.0099
        assert result_k10[0].rrf_score > result_k100[0].rrf_score

    def test_deduplication_across_lists(self):
        from app.rag.retrieval import reciprocal_rank_fusion

        dense = [_make_chunk("x"), _make_chunk("y")]
        sparse = [_make_chunk("x"), _make_chunk("z")]
        result = reciprocal_rank_fusion(dense, sparse)
        ids = [c.chunk_id for c in result]
        assert len(ids) == len(set(ids)), "no duplicate chunk_ids in combined output"
        assert len(ids) == 3  # x, y, z

    def test_deterministic_output(self):
        from app.rag.retrieval import reciprocal_rank_fusion

        dense = [_make_chunk(f"d{i}") for i in range(5)]
        sparse = [_make_chunk(f"s{i}") for i in range(5)]
        run1 = [c.chunk_id for c in reciprocal_rank_fusion(dense, sparse)]
        run2 = [c.chunk_id for c in reciprocal_rank_fusion(dense, sparse)]
        assert run1 == run2


# ── RetrievedChunk shape tests ────────────────────────────────────────────────


class TestRetrievedChunkShape:
    def test_as_dict_includes_rrf_score_when_set(self):
        chunk = _make_chunk("c1", rrf_score=0.0123)
        d = chunk.as_dict()
        assert "rrf_score" in d
        assert d["rrf_score"] == pytest.approx(0.0123)

    def test_as_dict_omits_rrf_score_when_none(self):
        chunk = _make_chunk("c2")
        d = chunk.as_dict()
        assert "rrf_score" not in d

    def test_as_dict_includes_ts_rank_when_set(self):
        chunk = _make_chunk("c3", ts_rank=0.456)
        d = chunk.as_dict()
        assert "ts_rank" in d
        assert d["ts_rank"] == pytest.approx(0.456)

    def test_as_dict_omits_ts_rank_when_none(self):
        chunk = _make_chunk("c4")
        d = chunk.as_dict()
        assert "ts_rank" not in d

    def test_similarity_property(self):
        chunk = _make_chunk("c5", cosine_distance=0.3)
        assert chunk.similarity == pytest.approx(0.7, abs=1e-5)

    def test_as_dict_includes_reranker_score_when_set(self):
        chunk = _make_chunk("c6", reranker_score=0.8123)
        d = chunk.as_dict()
        assert d["reranker_score"] == pytest.approx(0.8123)


# ── retrieve_keyword_chunks tests ─────────────────────────────────────────────


class TestRetrieveKeywordChunks:
    def test_returns_empty_on_sqlite(self):
        """Keyword retrieval should return [] on non-Postgres backends."""
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.rag.retrieval import retrieve_keyword_chunks

        engine = create_engine(
            "sqlite+pysqlite:////tmp/capitalos_retrieval_keyword_test.db",
            connect_args={"check_same_thread": False},
        )
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
            result = retrieve_keyword_chunks("See's Candies", db, top_k=5)
            assert result == [], "expected empty list on SQLite"
        finally:
            db.close()
            engine.dispose()

    def test_returns_empty_for_blank_query(self):
        """Blank queries should return [] without DB error."""
        from unittest.mock import MagicMock

        from app.rag.retrieval import retrieve_keyword_chunks

        db = MagicMock()
        db.bind.dialect.name = "postgresql"
        result = retrieve_keyword_chunks("", db, top_k=5)
        assert result == []


# ── retrieve_hybrid tests ─────────────────────────────────────────────────────


class TestRetrieveHybrid:
    def test_falls_back_to_dense_on_sqlite(self):
        """On SQLite, hybrid should fall back to dense-only results."""
        from sqlalchemy import create_engine, text as sa_text
        from sqlalchemy.orm import sessionmaker

        from app.rag.retrieval import retrieve_hybrid

        engine = create_engine(
            "sqlite+pysqlite:////tmp/capitalos_hybrid_test.db",
            connect_args={"check_same_thread": False},
        )

        dense_chunks = [_make_chunk("dense1"), _make_chunk("dense2")]

        with patch("app.rag.retrieval.retrieve_similar_chunks", return_value=dense_chunks), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[]) as mock_kw:
            Session = sessionmaker(bind=engine)
            db = Session()
            try:
                result = retrieve_hybrid("capital allocation", db, top_k=2)
            finally:
                db.close()

        # When keyword returns empty, hybrid falls back to dense
        assert len(result) == 2
        assert result[0].chunk_id == "dense1"

    def test_dense_only_mode_skips_sparse(self):
        """dense_only mode should only call retrieve_similar_chunks."""
        from app.rag.retrieval import retrieve_hybrid

        dense_chunks = [_make_chunk("d1"), _make_chunk("d2")]

        with patch.dict(os.environ, {"RAG_RETRIEVAL_MODE": "dense_only"}), \
             patch("app.rag.retrieval._RETRIEVAL_MODE", "dense_only"), \
             patch("app.rag.retrieval.retrieve_similar_chunks", return_value=dense_chunks) as mock_dense, \
             patch("app.rag.retrieval.retrieve_keyword_chunks") as mock_kw:
            db = MagicMock()
            result = retrieve_hybrid("moat analysis", db, top_k=2)

        mock_dense.assert_called_once()
        mock_kw.assert_not_called()
        assert len(result) == 2

    def test_sparse_only_mode_skips_dense(self):
        """sparse_only mode should only call retrieve_keyword_chunks."""
        from app.rag.retrieval import retrieve_hybrid

        sparse_chunks = [_make_chunk("s1", ts_rank=0.8)]

        with patch("app.rag.retrieval._RETRIEVAL_MODE", "sparse_only"), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=sparse_chunks) as mock_kw, \
             patch("app.rag.retrieval.retrieve_similar_chunks") as mock_dense:
            db = MagicMock()
            result = retrieve_hybrid("float insurance", db, top_k=1)

        mock_kw.assert_called_once()
        mock_dense.assert_not_called()
        assert result[0].chunk_id == "s1"

    def test_hybrid_combines_via_rrf(self):
        """Hybrid mode should call both retrievers and use RRF combination."""
        from app.rag.retrieval import retrieve_hybrid

        dense_chunks = [_make_chunk("d1"), _make_chunk("d2"), _make_chunk("shared")]
        sparse_chunks = [_make_chunk("shared"), _make_chunk("s1"), _make_chunk("s2")]

        with patch("app.rag.retrieval._RETRIEVAL_MODE", "hybrid"), \
             patch("app.rag.retrieval.retrieve_similar_chunks", return_value=dense_chunks), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=sparse_chunks):
            db = MagicMock()
            result = retrieve_hybrid("See's Candies", db, top_k=5)

        # "shared" should rank highest (appears in both lists)
        ids = [c.chunk_id for c in result]
        assert "shared" in ids
        assert result[0].chunk_id == "shared"
        # No duplicates
        assert len(ids) == len(set(ids))
        # RRF scores are populated
        for chunk in result:
            assert chunk.rrf_score is not None

    def test_hybrid_top_k_limits_results(self):
        """retrieve_hybrid should return at most top_k results."""
        from app.rag.retrieval import retrieve_hybrid

        dense = [_make_chunk(f"d{i}") for i in range(10)]
        sparse = [_make_chunk(f"s{i}") for i in range(10)]

        with patch("app.rag.retrieval._RETRIEVAL_MODE", "hybrid"), \
             patch("app.rag.retrieval.retrieve_similar_chunks", return_value=dense), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=sparse):
            db = MagicMock()
            result = retrieve_hybrid("test query", db, top_k=5)

        assert len(result) <= 5

    def test_weighting_can_promote_higher_authority_chunks(self):
        """Metadata weighting softly promotes canonical material without filtering."""
        from app.rag.retrieval import retrieve_hybrid

        canonical = _make_chunk(
            "canonical",
            cosine_distance=0.15,
            metadata={"work_type": "talk", "canonical_status": "canonical", "dedupe_priority": 40},
        )
        notes = _make_chunk(
            "notes",
            cosine_distance=0.1,
            metadata={"work_type": "meeting_notes", "collection": "meeting notes"},
        )

        with patch("app.rag.retrieval._RETRIEVAL_MODE", "hybrid"), \
             patch("app.rag.retrieval.retrieve_similar_chunks", return_value=[notes, canonical]), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[notes, canonical]):
            db = MagicMock()
            result = retrieve_hybrid("capital allocation", db, top_k=2, weighting_enabled=True)

        assert [chunk.chunk_id for chunk in result] == ["canonical", "notes"]
        assert result[0].metadata_weight > 1.0
        assert result[1].metadata_weight < 1.0

    def test_weighting_missing_metadata_falls_back_to_baseline_scores(self):
        from app.rag.retrieval import retrieve_hybrid

        left = _make_chunk("left", cosine_distance=0.1)
        right = _make_chunk("right", cosine_distance=0.2)

        with patch("app.rag.retrieval._RETRIEVAL_MODE", "dense_only"), \
             patch("app.rag.retrieval.retrieve_similar_chunks", return_value=[left, right]):
            db = MagicMock()
            result = retrieve_hybrid("test", db, top_k=2, weighting_enabled=True)

        assert [chunk.chunk_id for chunk in result] == ["left", "right"]
        assert all(chunk.metadata_weight == pytest.approx(1.0) for chunk in result)


class TestMetadataWeightingHelpers:
    def test_merge_retrieval_metadata_includes_document_fields_and_hint(self):
        from app.rag.retrieval_weighting import merge_retrieval_metadata

        merged = merge_retrieval_metadata(
            {"author_id": "charlie_munger"},
            collection="annual meeting",
            canonical_status="canonical",
            dedupe_priority=75,
            work_type="talk",
            document_metadata={"retrieval_weight": 1.07},
        )

        assert merged["collection"] == "annual meeting"
        assert merged["canonical_status"] == "canonical"
        assert merged["dedupe_priority"] == 75
        assert merged["work_type"] == "talk"
        assert merged["retrieval_weight"] == pytest.approx(1.07)

    def test_apply_weight_to_score_defaults_to_neutral_when_metadata_missing(self):
        from app.rag.retrieval_weighting import apply_weight_to_score

        decision = apply_weight_to_score(None, base_score=0.8, enabled=True)
        assert decision.weight == pytest.approx(1.0)
        assert decision.weighted_score == pytest.approx(0.8)

    def test_apply_weight_to_score_downweights_reference_material(self):
        from app.rag.retrieval_weighting import apply_weight_to_score

        decision = apply_weight_to_score(
            {"work_type": "reference", "canonical_status": "reference"},
            base_score=0.9,
            enabled=True,
        )
        assert decision.corpus_class == "reference_material"
        assert decision.weight < 1.0
        assert decision.weighted_score < decision.base_score


# ── Filter compatibility tests ────────────────────────────────────────────────


class TestHybridFilterCompat:
    """Verify that all filter params are forwarded correctly."""

    def test_author_ids_forwarded_to_both_retrievers(self):
        from app.rag.retrieval import retrieve_hybrid

        with patch("app.rag.retrieval._RETRIEVAL_MODE", "hybrid"), \
             patch("app.rag.retrieval.retrieve_similar_chunks", return_value=[]) as mock_dense, \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[]) as mock_kw:
            db = MagicMock()
            retrieve_hybrid("test", db, top_k=5, author_ids=["warren_buffett"])

        _, dense_kwargs = mock_dense.call_args
        _, kw_kwargs = mock_kw.call_args
        assert dense_kwargs.get("author_ids") == ["warren_buffett"]
        assert kw_kwargs.get("author_ids") == ["warren_buffett"]

    def test_year_filters_forwarded(self):
        from app.rag.retrieval import retrieve_hybrid

        with patch("app.rag.retrieval._RETRIEVAL_MODE", "hybrid"), \
             patch("app.rag.retrieval.retrieve_similar_chunks", return_value=[]) as mock_dense, \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[]) as mock_kw:
            db = MagicMock()
            retrieve_hybrid("test", db, top_k=5, year_from="2000", year_to="2010")

        _, dense_kwargs = mock_dense.call_args
        _, kw_kwargs = mock_kw.call_args
        assert dense_kwargs.get("year_from") == "2000"
        assert dense_kwargs.get("year_to") == "2010"
        assert kw_kwargs.get("year_from") == "2000"
        assert kw_kwargs.get("year_to") == "2010"
