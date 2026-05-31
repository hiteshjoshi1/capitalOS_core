"""
Tests for constraint-aware retrieval (Issue 145).

Coverage:
  - ConstrainedRetrievalResult dataclass shape
  - retrieve_with_constraints() strict mode: no fallback, zero results respected
  - retrieve_with_constraints() fallback mode: staged relaxation, reports reason
  - _apply_date_filters() helper: year_from/year_to/published_from/published_to
  - RetrieveIn schema: new constraint fields accepted and typed correctly
  - POST /rag/retrieve response includes constraint transparency metadata
  - concept_mode _retrieve_with_intent_fallback returns relaxation metadata tuple
  - _collect_candidate_chunks returns (chunks, relaxed, reason) tuple
  - ConceptQueryResult includes constraints_relaxed / constraint_relaxation_reason
  - Dense, sparse, hybrid all accept int year params without error
"""

from __future__ import annotations

import os
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_constraint_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_chunk(
    chunk_id: str,
    text: str = "sample text",
    cosine_distance: float = 0.2,
    metadata: Optional[dict] = None,
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
    )


# ── ConstrainedRetrievalResult shape ─────────────────────────────────────────


class TestConstrainedRetrievalResult:
    def test_as_dict_includes_constraint_metadata(self):
        from app.rag.retrieval import ConstrainedRetrievalResult

        chunks = [_make_chunk("c1")]
        result = ConstrainedRetrievalResult(
            chunks=chunks,
            constraints_requested={"year_from": 2020},
            constraints_applied={"year_from": 2020},
            constraints_relaxed=False,
            constraint_relaxation_reason=None,
        )
        d = result.as_dict()
        assert d["constraints_requested"] == {"year_from": 2020}
        assert d["constraints_applied"] == {"year_from": 2020}
        assert d["constraints_relaxed"] is False
        assert d["constraint_relaxation_reason"] is None
        assert len(d["evidence_chunks"]) == 1

    def test_as_dict_omits_diagnostics_when_none(self):
        from app.rag.retrieval import ConstrainedRetrievalResult

        result = ConstrainedRetrievalResult(
            chunks=[],
            constraints_requested={},
            constraints_applied={},
        )
        d = result.as_dict()
        assert "diagnostics" not in d

    def test_as_dict_includes_diagnostics_when_set(self):
        from app.rag.retrieval import ConstrainedRetrievalResult

        result = ConstrainedRetrievalResult(
            chunks=[],
            constraints_requested={"year_from": 2020},
            constraints_applied={"year_from": 2020},
            diagnostics={"candidate_count": 0},
        )
        d = result.as_dict()
        assert "diagnostics" in d
        assert d["diagnostics"]["candidate_count"] == 0

    def test_relaxed_result_surface_reason(self):
        from app.rag.retrieval import ConstrainedRetrievalResult

        result = ConstrainedRetrievalResult(
            chunks=[_make_chunk("c1")],
            constraints_requested={"year_from": 2020, "source_type": "letter"},
            constraints_applied={"year_from": 2020},
            constraints_relaxed=True,
            constraint_relaxation_reason="No results under exact constraints; source_type relaxed.",
        )
        d = result.as_dict()
        assert d["constraints_relaxed"] is True
        assert "source_type relaxed" in d["constraint_relaxation_reason"]


# ── retrieve_with_constraints strict mode ────────────────────────────────────


class TestRetrieveWithConstraintsStrict:
    def test_strict_mode_returns_zero_when_no_results(self):
        from app.rag.retrieval import retrieve_with_constraints

        with patch("app.rag.retrieval.retrieve_hybrid", return_value=[]) as mock_hybrid:
            db = MagicMock()
            result = retrieve_with_constraints(
                "Buffett on moats",
                db,
                top_k=5,
                year_from=2020,
                year_to=2025,
                strict_constraints=True,
            )

        assert result.chunks == []
        assert result.constraints_relaxed is False
        assert result.constraint_relaxation_reason is None
        # Only called once (no fallback)
        mock_hybrid.assert_called_once()

    def test_strict_mode_returns_chunks_when_results_exist(self):
        from app.rag.retrieval import retrieve_with_constraints

        chunks = [_make_chunk("c1"), _make_chunk("c2")]
        with patch("app.rag.retrieval.retrieve_hybrid", return_value=chunks):
            db = MagicMock()
            result = retrieve_with_constraints(
                "Buffett on moats",
                db,
                top_k=5,
                year_from=2020,
                year_to=2025,
                strict_constraints=True,
            )

        assert len(result.chunks) == 2
        assert result.constraints_relaxed is False

    def test_strict_mode_constraints_requested_recorded(self):
        from app.rag.retrieval import retrieve_with_constraints

        with patch("app.rag.retrieval.retrieve_hybrid", return_value=[]):
            db = MagicMock()
            result = retrieve_with_constraints(
                "capital allocation",
                db,
                top_k=5,
                year_from=2020,
                year_to=2025,
                source_type="letter",
                strict_constraints=True,
            )

        assert result.constraints_requested["year_from"] == 2020
        assert result.constraints_requested["year_to"] == 2025
        assert result.constraints_requested["source_type"] == "letter"

    def test_strict_mode_debug_includes_candidate_count(self):
        from app.rag.retrieval import retrieve_with_constraints

        chunks = [_make_chunk("c1")]
        with patch("app.rag.retrieval.retrieve_hybrid", return_value=chunks):
            db = MagicMock()
            result = retrieve_with_constraints(
                "moat analysis",
                db,
                top_k=5,
                year_from=2020,
                strict_constraints=True,
                debug=True,
            )

        assert result.diagnostics is not None
        assert result.diagnostics["candidate_count"] == 1

    def test_strict_mode_no_debug_omits_diagnostics(self):
        from app.rag.retrieval import retrieve_with_constraints

        with patch("app.rag.retrieval.retrieve_hybrid", return_value=[]):
            db = MagicMock()
            result = retrieve_with_constraints(
                "moat analysis",
                db,
                top_k=5,
                year_from=2020,
                strict_constraints=True,
                debug=False,
            )

        assert result.diagnostics is None


# ── retrieve_with_constraints fallback mode ──────────────────────────────────


class TestRetrieveWithConstraintsFallback:
    def test_fallback_mode_relaxes_when_no_exact_results(self):
        from app.rag.retrieval import retrieve_with_constraints

        chunks = [_make_chunk("fallback")]
        call_count = 0

        def hybrid_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call (full constraints) returns empty; second returns results
            if call_count == 1:
                return []
            return chunks

        with patch("app.rag.retrieval.retrieve_hybrid", side_effect=hybrid_side_effect):
            db = MagicMock()
            result = retrieve_with_constraints(
                "Buffett letters",
                db,
                top_k=5,
                source_type="letter",
                year_from=2020,
                strict_constraints=False,
            )

        assert result.constraints_relaxed is True
        assert result.constraint_relaxation_reason is not None
        assert len(result.chunks) == 1

    def test_fallback_mode_returns_exact_match_if_available(self):
        from app.rag.retrieval import retrieve_with_constraints

        chunks = [_make_chunk("exact")]

        with patch("app.rag.retrieval.retrieve_hybrid", return_value=chunks):
            db = MagicMock()
            result = retrieve_with_constraints(
                "Buffett letters",
                db,
                top_k=5,
                source_type="letter",
                year_from=2020,
                strict_constraints=False,
            )

        assert result.constraints_relaxed is False
        assert result.constraint_relaxation_reason is None

    def test_fallback_mode_returns_empty_after_all_attempts(self):
        from app.rag.retrieval import retrieve_with_constraints

        with patch("app.rag.retrieval.retrieve_hybrid", return_value=[]):
            db = MagicMock()
            result = retrieve_with_constraints(
                "obscure query",
                db,
                top_k=5,
                source_type="letter",
                year_from=2020,
                strict_constraints=False,
            )

        assert result.chunks == []
        assert result.constraints_relaxed is True
        assert result.constraint_relaxation_reason is not None

    def test_fallback_relaxation_reason_mentions_what_was_relaxed(self):
        from app.rag.retrieval import retrieve_with_constraints

        call_count = 0

        def hybrid_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                return []
            return [_make_chunk("relaxed")]

        with patch("app.rag.retrieval.retrieve_hybrid", side_effect=hybrid_side_effect):
            db = MagicMock()
            result = retrieve_with_constraints(
                "Buffett on Munger",
                db,
                top_k=5,
                source_type="letter",
                year_from=2020,
                year_to=2025,
                strict_constraints=False,
            )

        assert result.constraints_relaxed is True
        assert result.constraint_relaxation_reason is not None
        # Should contain some description of what was relaxed
        reason = result.constraint_relaxation_reason
        assert "source_type" in reason or "date" in reason or "relaxed" in reason.lower()


# ── _apply_date_filters helper ───────────────────────────────────────────────


class TestApplyDateFilters:
    def test_year_from_int_adds_clause_sqlite(self):
        from app.rag.retrieval import _apply_date_filters

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        _apply_date_filters(where_clauses, params, False, 2020, None, None, None)
        assert len(where_clauses) == 1
        assert "year_from_str" in params
        assert params["year_from_str"] == "2020"

    def test_year_to_int_adds_clause_sqlite(self):
        from app.rag.retrieval import _apply_date_filters

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        _apply_date_filters(where_clauses, params, False, None, 2025, None, None)
        assert len(where_clauses) == 1
        assert "year_to_str" in params
        assert params["year_to_str"] == "2025"

    def test_both_year_filters_sqlite(self):
        from app.rag.retrieval import _apply_date_filters

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        _apply_date_filters(where_clauses, params, False, 2020, 2025, None, None)
        assert len(where_clauses) == 2

    def test_no_filters_adds_nothing(self):
        from app.rag.retrieval import _apply_date_filters

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        _apply_date_filters(where_clauses, params, False, None, None, None, None)
        assert where_clauses == []
        assert params == {}

    def test_postgres_year_from_uses_published_at(self):
        from app.rag.retrieval import _apply_date_filters

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        _apply_date_filters(where_clauses, params, True, 2020, None, None, None)
        assert len(where_clauses) == 1
        assert "year_from" in params
        assert params["year_from"] == 2020
        assert "published_at" in where_clauses[0].lower()

    def test_postgres_published_from_adds_clause(self):
        from app.rag.retrieval import _apply_date_filters

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        _apply_date_filters(where_clauses, params, True, None, None, "2020-01-01", "2025-12-31")
        assert len(where_clauses) == 2
        assert params["published_from"] == "2020-01-01"
        assert params["published_to"] == "2025-12-31"

    def test_published_from_ignored_on_sqlite(self):
        """published_from/published_to are not applied on SQLite (no native Date semantics)."""
        from app.rag.retrieval import _apply_date_filters

        where_clauses: list[str] = []
        params: dict[str, Any] = {}
        _apply_date_filters(where_clauses, params, False, None, None, "2020-01-01", "2025-12-31")
        # On SQLite, published_from/to should be skipped
        assert where_clauses == []
        assert params == {}


# ── Dense/sparse/hybrid accept int year params ───────────────────────────────


class TestIntYearParamCompat:
    def test_retrieve_hybrid_accepts_int_year_params(self):
        from app.rag.retrieval import retrieve_hybrid

        dense = [_make_chunk("d1", text="Capital allocation is the most important decision a CEO makes for long-term business value creation.")]
        with patch("app.rag.retrieval.retrieve_similar_chunks", return_value=dense), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[]):
            db = MagicMock()
            # Should not raise TypeError even though year_from is int
            result = retrieve_hybrid("capital allocation", db, top_k=5, year_from=2020, year_to=2025)
        assert len(result) == 1

    def test_retrieve_similar_chunks_forwards_int_year_params(self):
        """retrieve_similar_chunks should forward int year params to _apply_date_filters."""
        from app.rag.retrieval import retrieve_similar_chunks

        with patch("app.rag.retrieval.embed_query", return_value=[0.0] * 1024), \
             patch.object(
                 type(MagicMock()),
                 "__iter__",
                 return_value=iter([]),
             ):
            db = MagicMock()
            db.bind.dialect.name = "sqlite"
            db.execute.return_value.mappings.return_value.all.return_value = []
            # Should not raise
            result = retrieve_similar_chunks(
                "test", db, top_k=5, year_from=2020, year_to=2025
            )
        assert result == []


# ── RetrieveIn schema ─────────────────────────────────────────────────────────


class TestRetrieveInSchema:
    def test_default_strict_constraints_is_true(self):
        from app.routers.rag import RetrieveIn

        body = RetrieveIn(query="test")
        assert body.strict_constraints is True

    def test_accepts_year_as_int(self):
        from app.routers.rag import RetrieveIn

        body = RetrieveIn(query="test", year_from=2020, year_to=2025)
        assert body.year_from == 2020
        assert body.year_to == 2025

    def test_accepts_source_type(self):
        from app.routers.rag import RetrieveIn

        body = RetrieveIn(query="test", source_type="letter")
        assert body.source_type == "letter"

    def test_accepts_author_ids_list(self):
        from app.routers.rag import RetrieveIn

        body = RetrieveIn(query="test", author_ids=["warren_buffett", "charlie_munger"])
        assert len(body.author_ids) == 2

    def test_accepts_published_date_strings(self):
        from app.routers.rag import RetrieveIn

        body = RetrieveIn(query="test", published_from="2020-01-01", published_to="2025-12-31")
        assert body.published_from == "2020-01-01"
        assert body.published_to == "2025-12-31"

    def test_debug_defaults_to_false(self):
        from app.routers.rag import RetrieveIn

        body = RetrieveIn(query="test")
        assert body.debug is False


# ── RetrieveOut schema ────────────────────────────────────────────────────────


class TestRetrieveOutSchema:
    def test_constraint_fields_are_optional(self):
        from app.routers.rag import RetrieveOut

        out = RetrieveOut(
            query="test",
            mode="retrieve",
            selected_authors=[],
            evidence_chunks=[],
            answer=None,
            missing_information=None,
            evidence_sufficient=False,
        )
        # All constraint fields should default to None
        assert out.constraints_requested is None
        assert out.constraints_applied is None
        assert out.constraints_relaxed is None
        assert out.constraint_relaxation_reason is None
        assert out.diagnostics is None


# ── concept_mode _retrieve_with_intent_fallback returns tuple ─────────────────


class TestRetrieveWithIntentFallbackTuple:
    def test_returns_tuple_of_three(self):
        from app.rag.concept_mode import _retrieve_with_intent_fallback

        with patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[_make_chunk("c1")]), \
             patch("app.rag.concept_mode.retrieve_keyword_chunks", return_value=[]):
            db = MagicMock()
            db.bind.dialect.name = "sqlite"
            result = _retrieve_with_intent_fallback(
                "capital allocation",
                db,
                top_k=5,
                author_ids=None,
                source_type=None,
                year_from=None,
                year_to=None,
            )

        assert isinstance(result, tuple)
        assert len(result) == 3
        chunks, was_relaxed, reason = result
        assert isinstance(chunks, list)
        assert isinstance(was_relaxed, bool)

    def test_no_relaxation_when_first_attempt_succeeds(self):
        from app.rag.concept_mode import _retrieve_with_intent_fallback

        with patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[_make_chunk("c1", text="Intrinsic value represents the discounted present value of future cash flows a business will generate over its lifetime.")]), \
             patch("app.rag.concept_mode.retrieve_keyword_chunks", return_value=[]):
            db = MagicMock()
            chunks, was_relaxed, reason = _retrieve_with_intent_fallback(
                "intrinsic value", db, top_k=5,
                author_ids=None, source_type="letter",
                year_from="2020", year_to="2025",
            )

        assert was_relaxed is False
        assert reason is None
        assert len(chunks) >= 1

    def test_relaxation_detected_when_fallback_occurs(self):
        from app.rag.concept_mode import _retrieve_with_intent_fallback

        call_count = 0

        def mock_retrieve(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return []  # first attempt fails
            return [_make_chunk("fallback_c", text="Intrinsic value represents the discounted present value of future cash flows a business will generate over its lifetime.")]

        with patch("app.rag.concept_mode.retrieve_similar_chunks", side_effect=mock_retrieve), \
             patch("app.rag.concept_mode.retrieve_keyword_chunks", return_value=[]):
            db = MagicMock()
            chunks, was_relaxed, reason = _retrieve_with_intent_fallback(
                "intrinsic value", db, top_k=5,
                author_ids=None, source_type="letter",
                year_from=None, year_to=None,
            )

        assert was_relaxed is True
        assert reason is not None
        assert len(chunks) >= 1

    def test_returns_empty_list_when_all_attempts_fail(self):
        from app.rag.concept_mode import _retrieve_with_intent_fallback

        with patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]), \
             patch("app.rag.concept_mode.retrieve_keyword_chunks", return_value=[]):
            db = MagicMock()
            chunks, was_relaxed, reason = _retrieve_with_intent_fallback(
                "test", db, top_k=5,
                author_ids=None, source_type=None,
                year_from=None, year_to=None,
            )

        assert chunks == []
        assert was_relaxed is False


# ── ConceptQueryResult constraint fields ─────────────────────────────────────


class TestConceptQueryResultConstraintFields:
    def test_default_values(self):
        from app.rag.concept_mode import ConceptQueryResult

        r = ConceptQueryResult(
            query="test",
            best_passages=[],
            critique=None,
            evidence_sufficient=False,
            weak_evidence_note=None,
        )
        assert r.constraints_relaxed is False
        assert r.constraint_relaxation_reason is None

    def test_as_dict_includes_constraint_fields(self):
        from app.rag.concept_mode import ConceptQueryResult

        r = ConceptQueryResult(
            query="test",
            best_passages=[],
            critique=None,
            evidence_sufficient=False,
            weak_evidence_note=None,
            constraints_relaxed=True,
            constraint_relaxation_reason="year filter removed",
        )
        d = r.as_dict()
        assert d["constraints_relaxed"] is True
        assert d["constraint_relaxation_reason"] == "year filter removed"


# ── Backward compatibility ────────────────────────────────────────────────────


class TestBackwardCompatibility:
    def test_retrieve_hybrid_still_works_without_new_params(self):
        """Callers that don't pass new params should still work."""
        from app.rag.retrieval import retrieve_hybrid

        dense = [_make_chunk("d1", text="Capital allocation is the most important decision a CEO makes for long-term business value creation.")]
        with patch("app.rag.retrieval.retrieve_similar_chunks", return_value=dense), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[]):
            db = MagicMock()
            result = retrieve_hybrid("capital allocation", db, top_k=5)
        assert len(result) == 1

    def test_retrieve_similar_chunks_still_works_without_new_params(self):
        """Old callers without year/date params should still work."""
        from app.rag.retrieval import retrieve_similar_chunks

        with patch("app.rag.retrieval.embed_query", return_value=[0.0] * 1024):
            db = MagicMock()
            db.bind.dialect.name = "sqlite"
            db.execute.return_value.mappings.return_value.all.return_value = []
            result = retrieve_similar_chunks("test", db, top_k=5)
        assert result == []
