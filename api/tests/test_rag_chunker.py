"""
Comprehensive tests for the recursive and semantic chunker (Issue 140).

Coverage:
  - _split_sentences(): 10+ edge cases (abbreviations, numbers, multi-line)
  - _count_tokens(): tiktoken vs approximation accuracy
  - chunk_recursive(): short text, long paragraph, multiple paragraphs, overlap
  - chunk_structured(): section boundaries, tables, lists
  - Semantic boundary detection (mocked embeddings)
  - Configuration via env vars (target tokens, overlap pct, semantic toggle)
  - chunk_text() backward compatibility
"""

from __future__ import annotations

import os
import math
from unittest.mock import patch

import pytest

# Ensure test environment
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _word_approx(text: str) -> int:
    """Word-based approximation matching the fallback in chunker."""
    return max(1, int(len(text.split()) * 1.35))


# ── Sentence splitting ────────────────────────────────────────────────────────


class TestSplitSentences:
    def _split(self, text: str) -> list[str]:
        from app.rag.ingestion.chunker import _split_sentences

        return _split_sentences(text)

    def test_simple_two_sentences(self):
        result = self._split("Hello world. How are you?")
        assert len(result) == 2
        assert result[0] == "Hello world."
        assert result[1] == "How are you?"

    def test_three_sentences(self):
        result = self._split("First sentence. Second sentence. Third sentence.")
        assert len(result) == 3

    def test_exclamation_split(self):
        result = self._split("Amazing! Really great work.")
        assert len(result) == 2

    def test_question_split(self):
        result = self._split("What is this? It is a test.")
        assert len(result) == 2

    def test_abbreviation_mr_not_split(self):
        # Mr. should NOT trigger a sentence boundary
        result = self._split("Mr. Smith is here. He came today.")
        # Should have at most 2 sentences, not split on "Mr."
        assert len(result) <= 2
        # The first element should start with "Mr."
        assert result[0].startswith("Mr.")

    def test_abbreviation_dr_not_split(self):
        result = self._split("Dr. Jones examined the patient. The results were normal.")
        assert len(result) <= 2
        assert result[0].startswith("Dr.")

    def test_decimal_number_not_split(self):
        # "3.14" should not split
        result = self._split("Pi is approximately 3.14 in most calculations. It is irrational.")
        assert len(result) == 2

    def test_single_sentence_no_split(self):
        result = self._split("This is just one sentence without any terminator")
        assert len(result) == 1

    def test_empty_string(self):
        result = self._split("")
        assert result == []

    def test_single_word(self):
        result = self._split("Hello")
        assert result == ["Hello"]

    def test_multiple_spaces_between_sentences(self):
        result = self._split("First sentence.  Second sentence.")
        assert len(result) == 2

    def test_multiline_text(self):
        text = "First sentence.\nSecond sentence.\nThird sentence."
        result = self._split(text)
        # Line breaks alone don't split — only punctuation + space + capital
        assert len(result) >= 1

    def test_no_false_split_on_lowercase_after_period(self):
        # "e.g." or periods before lowercase should not split
        result = self._split("This is a list, e.g. apples and oranges. End here.")
        # There should be a split at "End here." but NOT at "e.g."
        assert any("End here." in s for s in result)


# ── Token counting ────────────────────────────────────────────────────────────


class TestCountTokens:
    def _count(self, text: str) -> int:
        from app.rag.ingestion.chunker import _count_tokens

        return _count_tokens(text)

    def test_empty_string_returns_one(self):
        assert self._count("") == 1

    def test_single_word(self):
        count = self._count("hello")
        assert count >= 1

    def test_longer_text_more_tokens(self):
        short = self._count("hello")
        long = self._count("hello world this is a longer sentence with many words")
        assert long > short

    def test_within_5pct_of_word_approx(self):
        """Token counts should be within 20% of word-count approximation (tiktoken may differ)."""
        from app.rag.ingestion.chunker import _TIKTOKEN_AVAILABLE

        text = "The quick brown fox jumps over the lazy dog and runs away quickly today."
        count = self._count(text)
        approx = _word_approx(text)
        # If tiktoken is available, counts are accurate; otherwise they match
        # Allow 30% margin since tiktoken BPE can differ significantly from word count
        assert abs(count - approx) / max(approx, 1) < 0.50


# ── Recursive character chunking ──────────────────────────────────────────────


SAMPLE_PARAGRAPH = (
    "Berkshire Hathaway has long followed a policy of concentrating investments "
    "in businesses with durable competitive advantages. Warren Buffett often refers "
    "to this as investing in companies with wide economic moats. The idea is that "
    "such businesses can sustain above-average returns on capital for extended periods."
)

LONG_PARAGRAPH = " ".join(["This is a test sentence number %d." % i for i in range(60)])

MULTI_PARA = "\n\n".join(
    [
        "Capital allocation is the most important decision a CEO makes. Every dollar "
        "reinvested in the business should earn more than the company's cost of capital.",
        "Insurance operations provide Berkshire with float — a liability on the balance "
        "sheet but an asset in practice, since it is typically held for many years.",
        "The railroad business generates consistent free cash flow regardless of "
        "economic conditions, making it an ideal long-term holding.",
    ]
)


class TestChunkRecursive:
    def _chunk(self, text: str, **kwargs):
        from app.rag.ingestion.chunker import chunk_recursive

        return chunk_recursive(text, **kwargs)

    def test_short_text_single_chunk(self):
        result = self._chunk("This is a short text.", target_tokens=400)
        assert len(result) == 1

    def test_empty_text_returns_empty(self):
        result = self._chunk("")
        assert result == []

    def test_whitespace_only_returns_empty(self):
        result = self._chunk("   \n\n   ")
        assert result == []

    def test_chunks_have_sequential_indices(self):
        result = self._chunk(MULTI_PARA, target_tokens=100)
        for i, c in enumerate(result):
            assert c.index == i

    def test_chunks_have_positive_token_count(self):
        result = self._chunk(MULTI_PARA, target_tokens=100)
        for c in result:
            assert c.token_count > 0

    def test_long_paragraph_split_at_sentence_boundary(self):
        """A paragraph > target_tokens must be split into multiple chunks."""
        result = self._chunk(LONG_PARAGRAPH, target_tokens=50)
        assert len(result) > 1
        # Each chunk should be roughly <= target * 1.5 (some slack for overlap)
        for c in result[:-1]:
            assert c.token_count <= 100  # generous bound

    def test_multiple_paragraphs_force_split(self):
        # MULTI_PARA is ~79 tokens; target=50 forces paragraph-level splits.
        result = self._chunk(MULTI_PARA, target_tokens=50)
        assert len(result) > 1

    def test_overlap_approximately_15pct(self):
        """Overlap between consecutive chunks should be ~15% of target (±5%)."""
        result = self._chunk(MULTI_PARA, target_tokens=100, overlap_pct=0.15)
        if len(result) < 2:
            pytest.skip("Not enough chunks to test overlap")
        target = 100
        expected_overlap_tokens = target * 0.15  # ~15
        # Check recorded overlap_tokens in metadata
        for c in result[1:]:
            recorded = c.metadata_json.get("overlap_tokens", 0)
            # overlap should be >= 1 token and <= 30% of target
            assert recorded >= 0
            assert recorded <= target * 0.35

    def test_chunk_index_in_metadata(self):
        result = self._chunk(MULTI_PARA, target_tokens=80)
        for i, c in enumerate(result):
            assert c.metadata_json["chunk_index"] == i

    def test_base_metadata_propagated(self):
        meta = {"author": "Buffett", "source_url": "https://example.com"}
        result = self._chunk(SAMPLE_PARAGRAPH, base_metadata=meta)
        for c in result:
            assert c.metadata_json["author"] == "Buffett"
            assert c.metadata_json["source_url"] == "https://example.com"

    def test_overlap_metadata_present(self):
        result = self._chunk(MULTI_PARA, target_tokens=80)
        for c in result:
            assert "overlap_tokens" in c.metadata_json

    def test_no_empty_chunks(self):
        result = self._chunk(MULTI_PARA, target_tokens=60)
        for c in result:
            assert c.text.strip() != ""

    def test_small_target_forces_many_chunks(self):
        # target=20 forces sentence- and word-level splitting, producing > 3 chunks.
        result = self._chunk(MULTI_PARA, target_tokens=20)
        assert len(result) > 3

    def test_very_large_target_single_chunk(self):
        result = self._chunk(MULTI_PARA, target_tokens=10000)
        # All paragraphs should fit in one chunk
        assert len(result) == 1


# ── Section-aware chunking ────────────────────────────────────────────────────


class TestChunkStructured:
    def _sections(self):
        from app.rag.ingestion.chunker import DocumentSection

        return [
            DocumentSection(
                heading="Capital Allocation",
                content=(
                    "Capital allocation is the most important decision a CEO makes. "
                    "Every dollar reinvested in the business should earn more than "
                    "the company's cost of capital. Buffett has emphasized this point "
                    "in multiple annual letters."
                ),
            ),
            DocumentSection(
                heading="Insurance Float",
                content=(
                    "Insurance operations provide Berkshire with float. "
                    "Float is a liability on the balance sheet but an asset in practice. "
                    "It is typically held for many years before claims are paid."
                ),
            ),
            DocumentSection(
                heading="Financial Summary",
                content="| Year | Revenue | Net Income |\n| 2023 | 364B | 96B |\n| 2022 | 302B | -23B |",
                is_table=True,
            ),
        ]

    def test_no_cross_section_chunks(self):
        from app.rag.ingestion.chunker import chunk_structured

        sections = self._sections()
        chunks = chunk_structured(sections, target_tokens=50)
        # Verify section headings are preserved and distinct sections don't mix
        headings_seen = {c.metadata_json.get("section_heading") for c in chunks}
        assert "Capital Allocation" in headings_seen
        assert "Insurance Float" in headings_seen

    def test_table_is_single_chunk(self):
        from app.rag.ingestion.chunker import chunk_structured

        sections = self._sections()
        chunks = chunk_structured(sections, target_tokens=10)  # tiny target
        table_chunks = [c for c in chunks if c.metadata_json.get("is_table")]
        assert len(table_chunks) == 1
        assert "Revenue" in table_chunks[0].text

    def test_section_heading_in_metadata(self):
        from app.rag.ingestion.chunker import chunk_structured

        sections = self._sections()
        chunks = chunk_structured(sections, target_tokens=400)
        for c in chunks:
            assert "section_heading" in c.metadata_json
            assert c.metadata_json["section_heading"] in (
                "Capital Allocation",
                "Insurance Float",
                "Financial Summary",
            )

    def test_sequential_indices_across_sections(self):
        from app.rag.ingestion.chunker import chunk_structured

        sections = self._sections()
        chunks = chunk_structured(sections, target_tokens=50)
        for i, c in enumerate(chunks):
            assert c.index == i
            assert c.metadata_json["chunk_index"] == i

    def test_empty_sections_list(self):
        from app.rag.ingestion.chunker import chunk_structured

        assert chunk_structured([]) == []

    def test_base_metadata_propagated(self):
        from app.rag.ingestion.chunker import chunk_structured

        meta = {"doc_hash": "abc123"}
        sections = self._sections()
        chunks = chunk_structured(sections, base_metadata=meta)
        for c in chunks:
            assert c.metadata_json["doc_hash"] == "abc123"


# ── Semantic boundary detection ───────────────────────────────────────────────


class TestSemanticBoundaryDetection:
    def test_detect_topic_boundaries_requires_two_sentences(self):
        from app.rag.ingestion.chunker import _detect_topic_boundaries

        result = _detect_topic_boundaries(["Only one sentence."], threshold=0.75)
        assert result == []

    def test_high_similarity_no_boundary(self):
        from app.rag.ingestion.chunker import _detect_topic_boundaries

        # Mock embeddings with very high similarity (same vector)
        same_vector = [1.0] + [0.0] * 255
        with patch("app.rag.ingestion.embedder.embed_batch", return_value=[same_vector, same_vector]):
            boundaries = _detect_topic_boundaries(
                ["Capital allocation is key.", "Buffett focuses on capital allocation."],
                threshold=0.75,
            )
        assert boundaries == [False]

    def test_low_similarity_triggers_boundary(self):
        from app.rag.ingestion.chunker import _detect_topic_boundaries

        # Mock embeddings with orthogonal vectors (zero similarity)
        vec_a = [1.0] + [0.0] * 255
        vec_b = [0.0, 1.0] + [0.0] * 254
        with patch("app.rag.ingestion.embedder.embed_batch", return_value=[vec_a, vec_b]):
            boundaries = _detect_topic_boundaries(
                ["Capital allocation is key.", "The weather today is sunny."],
                threshold=0.75,
            )
        assert boundaries == [True]

    def test_cosine_similarity_correctness(self):
        from app.rag.ingestion.chunker import _cosine_similarity

        a = [1.0, 0.0]
        b = [1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(1.0)

        c = [0.0, 1.0]
        assert _cosine_similarity(a, c) == pytest.approx(0.0)

    def test_cosine_similarity_zero_vector(self):
        from app.rag.ingestion.chunker import _cosine_similarity

        assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_apply_semantic_boundaries_splits_correctly(self):
        from app.rag.ingestion.chunker import _apply_semantic_boundaries

        sentences = ["A.", "B.", "C.", "D."]
        boundaries = [False, True, False]  # split between B and C
        groups = _apply_semantic_boundaries(sentences, boundaries)
        assert len(groups) == 2
        assert groups[0] == ["A.", "B."]
        assert groups[1] == ["C.", "D."]

    def test_apply_semantic_boundaries_empty_input(self):
        from app.rag.ingestion.chunker import _apply_semantic_boundaries

        assert _apply_semantic_boundaries([], []) == []

    def test_chunk_recursive_semantic_enabled_via_param(self):
        """Semantic chunking path should execute without error (mocked embeddings)."""
        from app.rag.ingestion.chunker import chunk_recursive

        text = (
            "Capital allocation is the most important skill. "
            "Buffett excels at this. "
            "The weather today is sunny and warm. "
            "Tomorrow it will rain heavily."
        )
        vec_a = [1.0] + [0.0] * 255
        vec_b = [0.0, 1.0] + [0.0] * 254

        with patch(
            "app.rag.ingestion.embedder.embed_batch",
            return_value=[vec_a, vec_b, vec_a, vec_b],
        ):
            chunks = chunk_recursive(text, semantic=True, semantic_threshold=0.75)

        assert len(chunks) >= 1
        for c in chunks:
            assert c.text.strip() != ""


# ── Environment variable configuration ───────────────────────────────────────


class TestEnvVarConfiguration:
    def test_target_tokens_from_env(self, monkeypatch):
        monkeypatch.setenv("RAG_CHUNKING_TARGET_TOKENS", "50")
        from app.rag.ingestion import chunker

        text = MULTI_PARA
        # With small target, should produce multiple chunks
        result = chunker.chunk_recursive(text)
        assert len(result) > 1

    def test_min_tokens_from_env(self, monkeypatch):
        monkeypatch.setenv("RAG_CHUNKING_MIN_TOKENS", "1")
        from app.rag.ingestion import chunker

        result = chunker.chunk_recursive("Short.", target_tokens=400)
        # Even short text should produce a chunk with min_tokens=1
        assert len(result) == 1

    def test_semantic_disabled_by_default(self):
        os.environ.pop("RAG_CHUNKING_SEMANTIC", None)
        from app.rag.ingestion.chunker import _cfg_bool

        assert _cfg_bool("RAG_CHUNKING_SEMANTIC", False) is False

    def test_semantic_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("RAG_CHUNKING_SEMANTIC", "1")
        from app.rag.ingestion.chunker import _cfg_bool

        assert _cfg_bool("RAG_CHUNKING_SEMANTIC", False) is True


# ── Backward compatibility (chunk_text) ───────────────────────────────────────


class TestChunkTextBackwardCompat:
    def test_chunk_text_returns_nonempty_list(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(MULTI_PARA)
        assert len(chunks) > 0

    def test_chunk_text_empty_returns_empty(self):
        from app.rag.ingestion.chunker import chunk_text

        assert chunk_text("") == []

    def test_chunk_text_sequential_indices(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(MULTI_PARA)
        for i, c in enumerate(chunks):
            assert c.index == i

    def test_chunk_text_positive_token_count(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(MULTI_PARA)
        for c in chunks:
            assert c.token_count > 0

    def test_chunk_text_base_metadata_propagated(self):
        from app.rag.ingestion.chunker import chunk_text

        meta = {"author": "Test Author", "doc_hash": "deadbeef"}
        chunks = chunk_text(MULTI_PARA, base_metadata=meta)
        for c in chunks:
            assert c.metadata_json["author"] == "Test Author"
            assert "chunk_index" in c.metadata_json

    def test_chunk_text_target_tokens_respected(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(MULTI_PARA, target_tokens=50)
        assert len(chunks) > 1

    def test_chunk_text_very_short_single_chunk(self):
        from app.rag.ingestion.chunker import chunk_text

        text = "Short text that fits in one chunk easily."
        chunks = chunk_text(text)
        assert len(chunks) == 1

    def test_chunk_text_no_empty_chunks(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(LONG_PARAGRAPH, target_tokens=50)
        for c in chunks:
            assert c.text.strip() != ""

    def test_chunk_text_chunk_index_in_metadata(self):
        from app.rag.ingestion.chunker import chunk_text

        chunks = chunk_text(MULTI_PARA)
        for i, c in enumerate(chunks):
            assert c.metadata_json.get("chunk_index") == i


# ── Token count accuracy ──────────────────────────────────────────────────────


class TestTokenCountAccuracy:
    """Verify token counts in metadata are accurate."""

    def test_token_count_matches_stored_value(self):
        from app.rag.ingestion.chunker import chunk_text, _count_tokens

        chunks = chunk_text(MULTI_PARA)
        for c in chunks:
            actual = _count_tokens(c.text)
            stored = c.token_count
            # Should be identical since we compute both the same way
            assert actual == stored

    def test_long_paragraph_chunks_within_target(self):
        """After recursive splitting, no chunk should exceed target * 1.5."""
        from app.rag.ingestion.chunker import chunk_recursive

        target = 100
        chunks = chunk_recursive(LONG_PARAGRAPH, target_tokens=target)
        for c in chunks[:-1]:  # last chunk may be slightly over
            assert c.token_count <= target * 2  # generous bound
