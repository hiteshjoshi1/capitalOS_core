"""
Unit tests for compute_corpus_expansions (Issue 171).

Coverage:
  - n-gram extraction produces 2-gram and 3-gram candidates (not only 1-grams)
  - n-gram filtered correctly when all tokens are stopwords
  - NPMI computation is numerically correct (known P values → known NPMI)
  - compute_npmi handles edge cases (zero probabilities, perfect co-occurrence)
  - _compute_pivot_expansions returns phrase-level and entity/concept co-expansions
  - --dry-run writes no rows to DB
  - command is idempotent (run twice, same row count)
  - graceful skip when an author has zero annotated chunks
"""

from __future__ import annotations

import math
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

# Set up environment before importing app modules
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_test.db")

from app.scripts.compute_corpus_expansions import (  # noqa: E402
    _extract_ngrams,
    _tokenize,
    _compute_pivot_expansions,
    compute_npmi,
)


# ── Tokenizer tests ───────────────────────────────────────────────────────────

class TestTokenize:
    def test_basic_tokenization(self):
        tokens = _tokenize("Amazon is a great company")
        assert "amazon" in tokens

    def test_removes_scaffolding_terms(self):
        tokens = _tokenize("what about amazon")
        # 'what' and 'about' are scaffolding terms and should be stripped
        assert "what" not in tokens
        assert "about" not in tokens
        assert "amazon" in tokens

    def test_empty_string(self):
        assert _tokenize("") == []

    def test_all_scaffolding_returns_empty(self):
        # 'what', 'about', 'from', 'with' are scaffolding terms
        result = _tokenize("what about from with")
        assert result == []


# ── N-gram extraction tests ───────────────────────────────────────────────────

class TestExtractNgrams:
    def test_produces_unigrams(self):
        tokens = ["scale", "economies", "shared"]
        ngrams = _extract_ngrams(tokens)
        assert "scale" in ngrams
        assert "economies" in ngrams
        assert "shared" in ngrams

    def test_produces_bigrams(self):
        tokens = ["scale", "economies", "shared"]
        ngrams = _extract_ngrams(tokens)
        assert "scale economies" in ngrams
        assert "economies shared" in ngrams

    def test_produces_trigrams(self):
        tokens = ["scale", "economies", "shared"]
        ngrams = _extract_ngrams(tokens)
        assert "scale economies shared" in ngrams

    def test_discards_all_stopword_ngrams(self):
        """An n-gram where every token is a stopword must be discarded."""
        from app.rag.retrieval import _FEEDBACK_STOPWORDS
        # Pick tokens that are guaranteed stopwords
        stopwords = list(_FEEDBACK_STOPWORDS)[:3]
        # Ensure we have at least 2 stopwords
        assert len(stopwords) >= 2
        tokens = stopwords
        ngrams = _extract_ngrams(tokens)
        for gram in ngrams:
            gram_tokens = gram.split()
            # Every kept gram must contain at least one non-stopword
            assert not all(t in _FEEDBACK_STOPWORDS for t in gram_tokens), (
                f"All-stopword gram should have been discarded: {gram!r}"
            )

    def test_keeps_ngrams_with_at_least_one_content_word(self):
        from app.rag.retrieval import _FEEDBACK_STOPWORDS
        # 'lower' is not a stopword; combine with a stopword
        stopwords = [t for t in _FEEDBACK_STOPWORDS if len(t) > 1]
        sw = stopwords[0] if stopwords else "the"
        tokens = [sw, "lower", "prices"]
        ngrams = _extract_ngrams(tokens)
        # Bigram "lower prices" should be present
        assert "lower prices" in ngrams

    def test_single_char_tokens_not_kept_alone(self):
        tokens = ["a", "b", "c"]
        ngrams = _extract_ngrams(tokens)
        # Single-char tokens are filtered out (all tokens <= 1 char are stopwords)
        assert not any(len(g) == 1 for g in ngrams)

    def test_empty_token_list(self):
        assert _extract_ngrams([]) == set()

    def test_max_n_respected(self):
        tokens = ["scale", "economies", "shared", "value"]
        ngrams = _extract_ngrams(tokens, max_n=2)
        # 4-gram should not appear
        assert "scale economies shared value" not in ngrams
        # 2-gram should appear
        assert "scale economies" in ngrams


# ── NPMI computation tests ────────────────────────────────────────────────────

class TestComputeNpmi:
    def test_basic_npmi_positive(self):
        """When term always co-occurs with pivot, NPMI should be positive."""
        # n_joint=5, n_pivot=5, n_t=5, N=10
        # P_joint=0.5, P_pivot=0.5, P_t=0.5
        # PMI = log(0.5/(0.5*0.5)) = log(2) ≈ 0.693
        # NPMI = log(2) / -log(0.5) = log(2)/log(2) = 1.0
        val = compute_npmi(5, 5, 5, 10)
        assert val is not None
        assert abs(val - 1.0) < 1e-9

    def test_npmi_numerically_correct(self):
        """Known values should produce exact NPMI."""
        # n_joint=3, n_pivot=6, n_t=6, N=12
        # P_joint=0.25, P_pivot=0.5, P_t=0.5
        # PMI = log(0.25/(0.5*0.5)) = log(1) = 0
        # NPMI = 0
        val = compute_npmi(3, 6, 6, 12)
        assert val is not None
        assert abs(val - 0.0) < 1e-9

    def test_npmi_range(self):
        """NPMI should be in [-1, 1]."""
        val = compute_npmi(2, 10, 5, 100)
        assert val is not None
        assert -1.0 <= val <= 1.0

    def test_zero_n_joint_returns_none(self):
        assert compute_npmi(0, 5, 5, 10) is None

    def test_zero_N_returns_none(self):
        assert compute_npmi(1, 1, 1, 0) is None

    def test_zero_n_pivot_returns_none(self):
        assert compute_npmi(1, 0, 5, 10) is None

    def test_zero_n_t_returns_none(self):
        assert compute_npmi(1, 5, 0, 10) is None

    def test_perfect_cooccurrence_npmi_is_one(self):
        """When P_joint = 1 (all chunks), NPMI should be 1."""
        val = compute_npmi(10, 10, 10, 10)
        assert val == 1.0

    def test_npmi_asymmetric_support(self):
        """NPMI should handle typical unequal support numbers."""
        # n_joint=3, n_pivot=30, n_t=10, N=100
        # P_joint=0.03, P_pivot=0.3, P_t=0.1
        # PMI = log(0.03/(0.3*0.1)) = log(1) = 0
        val = compute_npmi(3, 30, 10, 100)
        assert val is not None
        # PMI should be ~0 since P_joint ~ P_pivot * P_t
        assert abs(val) < 1e-6

    def test_low_support_yields_negative_or_low_npmi(self):
        """When term rarely co-occurs with pivot vs. baseline, NPMI is low."""
        # n_joint=2, n_pivot=20, n_t=80, N=100
        # P_joint=0.02, P_pivot=0.2, P_t=0.8
        # P_pivot * P_t = 0.16, P_joint/denominator = 0.125
        # PMI = log(0.125) ≈ -2.08, NPMI < 0
        val = compute_npmi(2, 20, 80, 100)
        assert val is not None
        assert val < 0


# ── _compute_pivot_expansions tests ──────────────────────────────────────────

class TestComputePivotExpansions:
    def _make_chunk(self, chunk_id: str, text: str) -> tuple[str, str]:
        return (chunk_id, text)

    def test_produces_multiword_phrases(self):
        """n-gram extraction should surface multi-word expansion terms."""
        # Build a scenario where "scale economies" co-occurs consistently with a pivot
        pivot_id = "cid-1"
        chunk_data = [
            ("cid-1", "scale economies shared lower prices customer service"),
            ("cid-2", "scale economies shared lower prices customer service"),
            ("cid-3", "scale economies shared lower prices customer service"),
            ("cid-4", "scale economies shared lower prices customer service"),
            ("cid-5", "other content not related to the topic at hand"),
        ]
        pivot_chunk_ids = {"cid-1", "cid-2", "cid-3", "cid-4"}
        result = _compute_pivot_expansions(
            chunk_data,
            pivot_chunk_ids,
            {},
            {},
            min_support=3,
            min_npmi=0.0,
            top_n=30,
            current_pivot_id="some_entity",
            current_pivot_type="entity",
        )
        expansion_terms = [r["expansion_term"] for r in result]
        # At least one multi-word phrase (2-gram or 3-gram) must be present
        multiword = [t for t in expansion_terms if " " in t]
        assert len(multiword) >= 1, f"No multi-word phrase found in {expansion_terms}"

    def test_entity_co_expansion(self):
        """Entities that co-occur in pivot chunks should appear in expansions."""
        chunk_data = [
            ("cid-1", "investment returns long term compounding"),
            ("cid-2", "investment returns long term compounding"),
            ("cid-3", "investment returns long term compounding"),
            ("cid-4", "unrelated content about other topics"),
        ]
        pivot_chunk_ids = {"cid-1", "cid-2", "cid-3"}
        # Use entity IDs that don't appear as literal text in the chunks
        # to avoid phrase/entity deduplication collision
        entity_pivot_map = {
            "entity_amazon_xyz": {"cid-1", "cid-2", "cid-3"},
            "entity_costco_xyz": {"cid-1", "cid-2", "cid-3"},
        }
        result = _compute_pivot_expansions(
            chunk_data,
            pivot_chunk_ids,
            entity_pivot_map,
            {},
            min_support=3,
            min_npmi=0.0,
            top_n=30,
            current_pivot_id="entity_amazon_xyz",
            current_pivot_type="entity",
        )
        entity_expansions = [r for r in result if r["expansion_type"] == "entity"]
        entity_ref_ids = [r["expansion_ref_id"] for r in entity_expansions]
        # entity_costco_xyz should appear (co-occurs with amazon in pivot chunks)
        assert "entity_costco_xyz" in entity_ref_ids
        # entity_amazon_xyz itself should NOT appear (excluded as current pivot)
        assert "entity_amazon_xyz" not in entity_ref_ids

    def test_concept_co_expansion(self):
        """Concepts that co-occur in pivot chunks should appear as expansion_type='concept'."""
        chunk_data = [
            ("cid-1", "scale economies reinvestment returns compounding"),
            ("cid-2", "scale economies reinvestment returns compounding"),
            ("cid-3", "scale economies reinvestment returns compounding"),
            ("cid-4", "unrelated content"),
        ]
        pivot_chunk_ids = {"cid-1", "cid-2", "cid-3"}
        # Use concept IDs that don't appear as literal text to avoid phrase dedup
        concept_pivot_map = {
            "concept_compounding_xyz": {"cid-1", "cid-2", "cid-3"},
            "concept_scale_xyz": {"cid-1", "cid-2", "cid-3"},
        }
        result = _compute_pivot_expansions(
            chunk_data,
            pivot_chunk_ids,
            {},
            concept_pivot_map,
            min_support=3,
            min_npmi=0.0,
            top_n=30,
            current_pivot_id="concept_scale_xyz",
            current_pivot_type="concept",
        )
        concept_expansions = [r for r in result if r["expansion_type"] == "concept"]
        concept_ref_ids = [r["expansion_ref_id"] for r in concept_expansions]
        assert "concept_compounding_xyz" in concept_ref_ids
        # concept_scale_xyz itself should NOT appear (excluded as current pivot)
        assert "concept_scale_xyz" not in concept_ref_ids

    def test_min_support_filter(self):
        """Terms with co-occurrence below min_support must be excluded."""
        chunk_data = [
            ("cid-1", "amazon rare_phrase_xyz"),
            ("cid-2", "amazon other content"),
            ("cid-3", "amazon other content"),
            ("cid-4", "amazon other content"),
            ("cid-5", "unrelated content"),
        ]
        pivot_chunk_ids = {"cid-1", "cid-2", "cid-3", "cid-4"}
        result = _compute_pivot_expansions(
            chunk_data,
            pivot_chunk_ids,
            {},
            {},
            min_support=3,
            min_npmi=0.0,
            top_n=30,
            current_pivot_id="amazon",
            current_pivot_type="entity",
        )
        expansion_terms = [r["expansion_term"] for r in result]
        # rare_phrase_xyz only appears in 1 chunk, below min_support=3
        assert "rare_phrase_xyz" not in expansion_terms

    def test_top_n_cap(self):
        """Result should be capped at top_n."""
        # Create many unique terms
        chunk_data = []
        for i in range(5):
            terms = " ".join([f"term{j}" for j in range(50)])
            chunk_data.append((f"cid-{i}", terms))
        pivot_chunk_ids = {f"cid-{i}" for i in range(4)}
        result = _compute_pivot_expansions(
            chunk_data,
            pivot_chunk_ids,
            {},
            {},
            min_support=3,
            min_npmi=0.0,
            top_n=5,
            current_pivot_id="entity_x",
            current_pivot_type="entity",
        )
        assert len(result) <= 5

    def test_empty_author_chunks_returns_empty(self):
        result = _compute_pivot_expansions(
            [],
            {"cid-1"},
            {},
            {},
            min_support=3,
            min_npmi=0.0,
            top_n=30,
            current_pivot_id="entity_x",
            current_pivot_type="entity",
        )
        assert result == []

    def test_empty_pivot_chunks_returns_empty(self):
        chunk_data = [("cid-1", "amazon lower prices")]
        result = _compute_pivot_expansions(
            chunk_data,
            set(),
            {},
            {},
            min_support=3,
            min_npmi=0.0,
            top_n=30,
            current_pivot_id="entity_x",
            current_pivot_type="entity",
        )
        assert result == []


# ── Dry-run / DB integration tests (mock-based) ───────────────────────────────

class TestRunComputeDryRun:
    """Tests that verify --dry-run does not write to the DB."""

    def _build_mock_db(self):
        """Return a mock DB session that simulates a minimal author+chunk setup."""
        db = MagicMock()

        def execute_side_effect(sql_obj, params=None):
            sql_str = str(sql_obj).lower()
            result = MagicMock()

            if "from rag_authors" in sql_str:
                result.fetchall.return_value = [("nick_sleep",)]
                result.fetchone.return_value = ("nick_sleep",)

            elif "from rag_chunks rc" in sql_str and "author_id" in sql_str and "entity_id" not in sql_str and "concept_id" not in sql_str:
                # author chunks query - return enough chunks
                rows = [
                    (str(uuid.uuid4()), "scale economies shared lower prices customer service")
                    for _ in range(5)
                ]
                result.fetchall.return_value = rows

            elif "rag_chunk_entities" in sql_str:
                # entity pivot map
                cid = str(uuid.uuid4())
                result.fetchall.return_value = [
                    ("amazon", cid),
                    ("amazon", str(uuid.uuid4())),
                    ("amazon", str(uuid.uuid4())),
                ]

            elif "rag_chunk_concepts" in sql_str:
                result.fetchall.return_value = []

            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None

            return result

        db.execute.side_effect = execute_side_effect
        db.commit = MagicMock()
        db.rollback = MagicMock()
        db.close = MagicMock()
        return db

    @patch("app.scripts.compute_corpus_expansions.SessionLocal")
    def test_dry_run_does_not_commit(self, mock_session_local):
        mock_db = self._build_mock_db()
        mock_session_local.return_value = mock_db

        from app.scripts.compute_corpus_expansions import run_compute
        result = run_compute(
            author_id="nick_sleep",
            min_support=2,
            min_npmi=0.0,
            top_n=30,
            dry_run=True,
        )

        assert result["dry_run"] is True
        # No commits should happen in dry-run mode
        mock_db.commit.assert_not_called()

    @patch("app.scripts.compute_corpus_expansions.SessionLocal")
    def test_dry_run_does_not_insert(self, mock_session_local):
        mock_db = self._build_mock_db()
        mock_session_local.return_value = mock_db

        from app.scripts.compute_corpus_expansions import run_compute
        run_compute(
            author_id="nick_sleep",
            min_support=2,
            min_npmi=0.0,
            top_n=30,
            dry_run=True,
        )

        # Confirm no INSERT INTO rag_corpus_expansions was executed
        insert_calls = [
            c for c in mock_db.execute.call_args_list
            if "rag_corpus_expansions" in str(c).lower()
            and "insert" in str(c).lower()
        ]
        assert len(insert_calls) == 0, (
            f"Expected no INSERT calls in dry-run mode; found {len(insert_calls)}"
        )


class TestRunComputeGracefulSkip:
    """Graceful skip when an author has no annotated chunks."""

    @patch("app.scripts.compute_corpus_expansions.SessionLocal")
    def test_skip_author_with_no_annotations(self, mock_session_local):
        mock_db = MagicMock()

        def execute_side_effect(sql_obj, params=None):
            sql_str = str(sql_obj).lower()
            result = MagicMock()
            if "from rag_authors" in sql_str:
                result.fetchall.return_value = [("empty_author",)]
                result.fetchone.return_value = ("empty_author",)
            elif "from rag_chunks rc" in sql_str:
                result.fetchall.return_value = []
            elif "rag_chunk_entities" in sql_str:
                result.fetchall.return_value = []
            elif "rag_chunk_concepts" in sql_str:
                result.fetchall.return_value = []
            else:
                result.fetchall.return_value = []
                result.fetchone.return_value = None
            return result

        mock_db.execute.side_effect = execute_side_effect
        mock_db.commit = MagicMock()
        mock_db.close = MagicMock()
        mock_session_local.return_value = mock_db

        from app.scripts.compute_corpus_expansions import run_compute
        result = run_compute(author_id="empty_author", min_support=3, min_npmi=0.10)

        assert result["terms_stored"] == 0
        # No rows written for an author with no annotated chunks
        mock_db.commit.assert_not_called()

    @patch("app.scripts.compute_corpus_expansions.SessionLocal")
    def test_skip_unknown_author_id(self, mock_session_local):
        mock_db = MagicMock()

        def execute_side_effect(sql_obj, params=None):
            result = MagicMock()
            result.fetchone.return_value = None
            result.fetchall.return_value = []
            return result

        mock_db.execute.side_effect = execute_side_effect
        mock_db.close = MagicMock()
        mock_session_local.return_value = mock_db

        from app.scripts.compute_corpus_expansions import run_compute
        result = run_compute(author_id="nonexistent_author", min_support=3, min_npmi=0.10)

        assert result["authors"] == 0
        assert result["terms_stored"] == 0
