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
    document_id: str = "doc-1",
    chunk_index: int = 0,
) -> Any:
    from app.rag.retrieval import RetrievedChunk

    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=chunk_index,
        text=text,
        token_count=10,
        metadata_json=metadata or {},
        cosine_distance=cosine_distance,
        ts_rank=ts_rank,
        rrf_score=rrf_score,
        reranker_score=reranker_score,
    )


@pytest.fixture
def sqlite_parent_child_session(tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.rag import RagAuthor, RagChunk, RagDocument, RagSource

    db_path = tmp_path / "retrieval_parent_child.db"
    engine = create_engine(
        f"sqlite+pysqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    RagAuthor.__table__.create(bind=engine, checkfirst=True)
    RagSource.__table__.create(bind=engine, checkfirst=True)
    RagDocument.__table__.create(bind=engine, checkfirst=True)
    RagChunk.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        author = RagAuthor(id="author-1", name="Author One", enabled=True, domains=["investing"], expertise_tags=[])
        source = RagSource(id="source-1", author_id="author-1", source_type="manual", status="ingested")
        parent = RagDocument(id="parent-doc", source_id="source-1", author_id="author-1", title="Parent")
        child = RagDocument(
            id="child-doc",
            source_id="source-1",
            author_id="author-1",
            title="Child",
            parent_document_id="parent-doc",
        )
        session.add_all(
            [
                author,
                source,
                parent,
                child,
                RagChunk(id="p0", document_id="parent-doc", chunk_index=0, text="Parent intro", token_count=5, metadata_json={}),
                RagChunk(id="p1", document_id="parent-doc", chunk_index=1, text="Parent detail on See's Candies 2003 Q&A.", token_count=9, metadata_json={}),
                RagChunk(id="p2", document_id="parent-doc", chunk_index=2, text="Parent closing thought", token_count=4, metadata_json={}),
            ]
        )
        session.commit()
        yield session
    finally:
        session.close()
        engine.dispose()


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
            result = retrieve_hybrid(
                "capital allocation",
                db,
                top_k=2,
                weighting_enabled=True,
                hardening_enabled=False,
            )

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


class TestRetrievalHardeningHelpers:
    def test_trace_payload_prints_separator_when_enabled(self, capsys):
        from app.rag.retrieval import trace_retrieval_payload

        with patch.dict(os.environ, {"RAG_RETRIEVAL_TRACE": "1"}):
            trace_retrieval_payload("unit_stage", {"content_query": "main mental models"})

        output = capsys.readouterr().out
        assert "-------------- RAG RETRIEVAL TRACE: unit_stage --------------" in output
        assert '"content_query": "main mental models"' in output
        assert "-------------- END RAG RETRIEVAL TRACE --------------" in output

    def test_trace_payload_can_be_disabled(self, capsys):
        from app.rag.retrieval import trace_retrieval_payload

        with patch.dict(os.environ, {"RAG_RETRIEVAL_TRACE": "0"}):
            trace_retrieval_payload("unit_stage", {"content_query": "main mental models"})

        assert capsys.readouterr().out == ""

    def test_retrieval_query_plan_strips_source_author_and_keeps_concept(self):
        from app.rag.retrieval import build_retrieval_query_plan

        plan = build_retrieval_query_plan("What are Charlie Munger's main mental models?")

        assert plan.source_author_ids == ["charlie_munger"]
        assert plan.content_query == "main mental models"
        assert "Charlie Munger" in plan.removed_source_author_terms
        assert "mental models" in plan.required_phrases
        assert '"mental models"' in plan.sparse_query
        assert "Charlie" not in plan.content_query
        assert "Munger" not in plan.content_query

    def test_retrieval_query_plan_cleans_possessive_and_scaffolding(self):
        from app.rag.retrieval import build_retrieval_query_plan

        plan = build_retrieval_query_plan(
            "What are some of the best mental models that Charlie Munger lives by?"
        )

        assert plan.content_query == "best mental models"
        assert "mental models" in plan.required_phrases

    def test_sparse_query_plan_extracts_entity_year_and_transcript_hints(self):
        from app.rag.retrieval import build_sparse_query_plan

        plan = build_sparse_query_plan('What did Charlie Munger say about See\'s Candies in 2003 transcript Q&A?')

        assert "2003" in plan.year_terms
        assert any(term.lower() == "see's candies" for term in plan.entity_terms)
        assert plan.transcript_sensitive is True

    def test_hardened_retrieval_uses_content_query_inside_author_space(self):
        from app.rag.retrieval import retrieve_hybrid

        dense_hit = _make_chunk("dense", text="A latticework of mental models matters.")

        with patch("app.rag.retrieval.retrieve_similar_chunks", return_value=[dense_hit]) as mock_dense, \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[]):
            db = MagicMock()
            result = retrieve_hybrid(
                "What are Charlie Munger's main mental models?",
                db,
                top_k=3,
                hardening_enabled=True,
            )

        first_query, _db = mock_dense.call_args_list[0].args
        _, first_kwargs = mock_dense.call_args_list[0]
        assert first_query == "main mental models"
        assert first_kwargs["author_ids"] == ["charlie_munger"]
        assert result[0].metadata_json["retrieval_query_plan"]["content_query"] == "main mental models"

    def test_explainable_fusion_boosts_exact_phrase_and_concept_hits(self):
        from app.rag.retrieval import build_retrieval_query_plan, fuse_hardened_candidates

        plan = build_retrieval_query_plan("What are Charlie Munger's main mental models?")
        generic = _make_chunk("generic", text="Charlie Munger answered a question about children.")
        exact = _make_chunk("exact", text="The latticework of mental models is the main idea.")

        result = fuse_hardened_candidates(
            plan=plan,
            pools={"dense_content": [generic, exact], "sparse_required_phrase": [exact]},
            top_k=2,
        )

        assert [chunk.chunk_id for chunk in result] == ["exact", "generic"]
        diagnostics = result[0].metadata_json["retrieval_diagnostics"]
        assert "mental models" in diagnostics["phrase_hits"]
        assert diagnostics["score_components"]["required_phrase_score"] > 0

    def test_explainable_fusion_downranks_shallow_question_prompt(self):
        from app.rag.retrieval import build_retrieval_query_plan, fuse_hardened_candidates

        plan = build_retrieval_query_plan("What are Charlie Munger's main mental models?")
        prompt_only = _make_chunk(
            "prompt",
            text="Questioner: Mental models [which are your favorites]?",
        )
        actual_model = _make_chunk(
            "actual",
            text=(
                "Munger emphasizes inversion, incentives, social proof, "
                "authority, envy, and lollapalooza effects as practical models."
            ),
        )

        result = fuse_hardened_candidates(
            plan=plan,
            pools={"dense_content": [prompt_only, actual_model], "sparse_required_phrase": [prompt_only]},
            top_k=2,
        )

        assert [chunk.chunk_id for chunk in result] == ["actual", "prompt"]
        diagnostics = result[1].metadata_json["retrieval_diagnostics"]
        assert diagnostics["score_components"]["shallow_prompt_penalty"] < 0

    def test_hardened_fusion_promotes_aspect_coverage_and_diversity(self):
        from app.rag.retrieval import build_retrieval_query_plan, fuse_hardened_candidates

        plan = build_retrieval_query_plan("What are Charlie Munger's main mental models?")
        shallow_one = _make_chunk(
            "shallow-1",
            text="The main mental models are important.",
            document_id="doc-shallow",
            chunk_index=1,
        )
        shallow_two = _make_chunk(
            "shallow-2",
            text="Questioner: what mental models are the best mental models?",
            document_id="doc-shallow",
            chunk_index=2,
        )
        aspect_rich = _make_chunk(
            "aspect-rich",
            text=(
                "Munger uses inversion, incentives, social proof, authority bias, "
                "operant conditioning, critical mass, and margin of safety."
            ),
            document_id="doc-models",
            chunk_index=1,
        )

        result = fuse_hardened_candidates(
            plan=plan,
            pools={
                "dense_content": [shallow_one, shallow_two, aspect_rich],
                "sparse_required_phrase": [shallow_one, shallow_two],
            },
            top_k=3,
        )

        assert result[0].chunk_id == "aspect-rich"
        ranks = {chunk.chunk_id: index for index, chunk in enumerate(result)}
        assert ranks["aspect-rich"] < ranks["shallow-2"]
        diagnostics = result[0].metadata_json["retrieval_diagnostics"]
        assert set(diagnostics["aspect_hits"]) >= {"inversion", "incentives", "biases"}
        assert diagnostics["score_components"]["aspect_coverage_score"] > 0
        assert diagnostics["diversity"]["new_aspects"]

    def test_feedback_terms_are_domain_controlled_not_title_noise(self):
        from app.rag.retrieval import _extract_salient_feedback_terms, build_retrieval_query_plan

        plan = build_retrieval_query_plan("What does Charlie Munger say about decision making?")
        chunk = _make_chunk(
            "feedback",
            text=(
                "Wesco Financial lesson wisdom revisited. "
                "The useful psychology includes social proof and authority."
            ),
            metadata={
                "document_title": "A Lesson on Elementary, Worldly Wisdom, Revisited",
                "source_section": "Wesco Financial meeting notes",
            },
        )

        terms = _extract_salient_feedback_terms(plan, {"dense_content": [chunk]}, max_terms=8)

        assert "social proof" in terms
        assert "authority" in terms
        assert "wesco financial" not in terms
        assert "lesson wisdom" not in terms

    def test_hardened_retrieval_does_not_rank_neighbor_context_as_candidate_pool(self):
        from app.rag.retrieval import retrieve_hybrid

        dense_hit = _make_chunk("dense", text="Inversion and incentives are useful mental models.")

        with patch("app.rag.retrieval.retrieve_similar_chunks", return_value=[dense_hit]), \
             patch("app.rag.retrieval.retrieve_keyword_chunks", return_value=[]), \
             patch("app.rag.retrieval._neighbor_candidate_pool") as mock_neighbor:
            db = MagicMock()
            retrieve_hybrid(
                "What are Charlie Munger's main mental models?",
                db,
                top_k=3,
                hardening_enabled=True,
            )

        mock_neighbor.assert_not_called()

    def test_parent_child_delivery_prefers_parent_document_context(self, sqlite_parent_child_session):
        from app.rag.retrieval import deliver_parent_sections

        anchor = _make_chunk(
            "child-anchor",
            text="Short child anchor",
            document_id="child-doc",
            chunk_index=1,
            metadata={"author_id": "author-1"},
        )

        delivered = deliver_parent_sections([anchor], sqlite_parent_child_session, window_size=1, max_chars=500)

        assert len(delivered) == 1
        assert delivered[0].metadata_json["delivery_mode"] == "parent_document"
        assert delivered[0].metadata_json["parent_document_id"] == "parent-doc"
        assert "Parent detail on See's Candies 2003 Q&A." in delivered[0].text

    def test_near_duplicate_suppression_is_deterministic(self):
        from app.rag.retrieval import suppress_near_duplicates

        left = _make_chunk("left", text="Capital allocation means disciplined reinvestment over time.")
        right = _make_chunk("right", text="Capital allocation means disciplined reinvestment over time!")

        kept, suppressed = suppress_near_duplicates([left, right], threshold=0.9)

        assert [chunk.chunk_id for chunk in kept] == ["left"]
        assert suppressed == [{"chunk_id": "right", "matched_chunk_id": "left", "similarity": 1.0}]


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
