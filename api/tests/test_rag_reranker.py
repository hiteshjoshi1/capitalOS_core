"""
Tests for the cross-encoder reranking service (api/app/rag/reranker.py).

Covers:
  - reranker_available() under various env configurations
  - provider routing in rerank()
  - Cohere, Jina, and local provider implementations (mocked)
  - Score ordering correctness
  - API error handling / graceful fallback
  - Integration: _rerank_candidate_chunks() uses cross-encoder when available
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_reranker_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _set_env(**kwargs: str):
    """Context-manager-free helper; returns a patch.dict context manager."""
    return patch.dict(os.environ, kwargs)


# ── reranker_available() ──────────────────────────────────────────────────────


def test_reranker_available_returns_false_when_provider_is_none():
    with _set_env(RAG_RERANKER_PROVIDER="none"):
        from app.rag import reranker

        assert reranker.reranker_available() is False


def test_reranker_available_returns_false_when_provider_is_llm():
    with _set_env(RAG_RERANKER_PROVIDER="llm"):
        from app.rag import reranker

        assert reranker.reranker_available() is False


def test_reranker_available_returns_false_for_cohere_without_key():
    with _set_env(RAG_RERANKER_PROVIDER="cohere", COHERE_API_KEY=""):
        from app.rag import reranker

        assert reranker.reranker_available() is False


def test_reranker_available_returns_true_for_cohere_with_key():
    with _set_env(RAG_RERANKER_PROVIDER="cohere", COHERE_API_KEY="test-key"):
        from app.rag import reranker

        assert reranker.reranker_available() is True


def test_reranker_available_returns_false_for_jina_without_key():
    with _set_env(RAG_RERANKER_PROVIDER="jina", JINA_API_KEY=""):
        from app.rag import reranker

        assert reranker.reranker_available() is False


def test_reranker_available_returns_true_for_jina_with_key():
    with _set_env(RAG_RERANKER_PROVIDER="jina", JINA_API_KEY="jina-key"):
        from app.rag import reranker

        assert reranker.reranker_available() is True


def test_reranker_available_local_requires_sentence_transformers():
    with _set_env(RAG_RERANKER_PROVIDER="local"):
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            from importlib import reload

            from app.rag import reranker as rm

            # Simulate sentence_transformers missing
            import builtins

            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "sentence_transformers":
                    raise ImportError("no module")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                result = rm.reranker_available()
            assert result is False


# ── rerank() dispatcher ───────────────────────────────────────────────────────


def test_rerank_raises_for_unknown_provider():
    from app.rag.reranker import rerank

    with pytest.raises(ValueError, match="Unknown or unsupported"):
        rerank("query", ["passage1"], top_k=1, provider="bogus")


def test_rerank_returns_empty_for_no_passages():
    from app.rag.reranker import rerank

    result = rerank("query", [], top_k=5)
    assert result == []


def test_rerank_limits_to_passage_count():
    """top_k is clamped to len(passages) so no IndexError."""
    from app.rag.reranker import rerank

    passages = ["a", "b"]
    with patch("app.rag.reranker._rerank_local") as mock_local:
        mock_local.return_value = []
        rerank("q", passages, top_k=100, provider="local")
        call_kwargs = mock_local.call_args[1]
        assert call_kwargs["top_k"] <= len(passages)


# ── Cohere provider ───────────────────────────────────────────────────────────


def _make_cohere_result(index: int, score: float):
    r = MagicMock()
    r.index = index
    r.relevance_score = score
    return r


def test_cohere_reranker_returns_sorted_results():
    passages = ["irrelevant text", "highly relevant passage about moats", "somewhat relevant"]
    query = "What is a moat?"

    mock_cohere_client = MagicMock()
    mock_response = MagicMock()
    mock_response.results = [
        _make_cohere_result(1, 0.92),
        _make_cohere_result(2, 0.45),
        _make_cohere_result(0, 0.10),
    ]
    mock_cohere_client.rerank.return_value = mock_response

    with (
        _set_env(RAG_RERANKER_PROVIDER="cohere", COHERE_API_KEY="test-key", RAG_RERANKER_MODEL="rerank-english-v3.0"),
        patch.dict("sys.modules", {"cohere": MagicMock(Client=MagicMock(return_value=mock_cohere_client))}),
    ):
        from importlib import reload

        import app.rag.reranker as rm

        reload(rm)
        results = rm._rerank_cohere(query, passages, top_k=3)

    assert len(results) == 3
    assert results[0].index == 1
    assert results[0].relevance_score == pytest.approx(0.92)
    assert results[1].index == 2
    assert results[2].index == 0


def test_cohere_reranker_error_propagates():
    """API errors should propagate so callers can catch and fall back."""
    passages = ["text1", "text2"]
    query = "q"

    mock_cohere_client = MagicMock()
    mock_cohere_client.rerank.side_effect = RuntimeError("API unavailable")

    with (
        _set_env(RAG_RERANKER_PROVIDER="cohere", COHERE_API_KEY="test-key"),
        patch.dict("sys.modules", {"cohere": MagicMock(Client=MagicMock(return_value=mock_cohere_client))}),
    ):
        from importlib import reload

        import app.rag.reranker as rm

        reload(rm)
        with pytest.raises(RuntimeError, match="API unavailable"):
            rm._rerank_cohere(query, passages, top_k=2)


# ── Jina provider ─────────────────────────────────────────────────────────────


def test_jina_reranker_returns_sorted_results():
    passages = ["irrelevant", "very relevant moat passage", "somewhat relevant"]
    query = "moat durability"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.88},
            {"index": 2, "relevance_score": 0.55},
            {"index": 0, "relevance_score": 0.12},
        ]
    }
    mock_response.raise_for_status = MagicMock()

    mock_httpx_client = MagicMock()
    mock_httpx_client.__enter__ = MagicMock(return_value=mock_httpx_client)
    mock_httpx_client.__exit__ = MagicMock(return_value=False)
    mock_httpx_client.post.return_value = mock_response

    with (
        _set_env(RAG_RERANKER_PROVIDER="jina", JINA_API_KEY="jina-key", RAG_RERANKER_MODEL="jina-reranker-v2-base-multilingual"),
        patch("app.rag.reranker.httpx") as mock_httpx,
    ):
        mock_httpx.Client.return_value = mock_httpx_client
        from app.rag.reranker import _rerank_jina

        results = _rerank_jina(query, passages, top_k=3)

    assert len(results) == 3
    assert results[0].index == 1
    assert results[0].relevance_score == pytest.approx(0.88)


def test_jina_reranker_http_error_propagates():
    import httpx as real_httpx

    passages = ["a", "b"]
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = real_httpx.HTTPStatusError(
        "403", request=MagicMock(), response=MagicMock()
    )

    mock_httpx_client = MagicMock()
    mock_httpx_client.__enter__ = MagicMock(return_value=mock_httpx_client)
    mock_httpx_client.__exit__ = MagicMock(return_value=False)
    mock_httpx_client.post.return_value = mock_response

    with (
        _set_env(RAG_RERANKER_PROVIDER="jina", JINA_API_KEY="jina-key"),
        patch("app.rag.reranker.httpx") as mock_httpx,
    ):
        mock_httpx.Client.return_value = mock_httpx_client
        mock_httpx.HTTPStatusError = real_httpx.HTTPStatusError
        from app.rag.reranker import _rerank_jina

        with pytest.raises(real_httpx.HTTPStatusError):
            _rerank_jina("q", passages, top_k=2)


# ── Local cross-encoder provider ──────────────────────────────────────────────


def test_local_reranker_returns_sorted_results():
    import numpy as np

    passages = ["capital allocation is key", "moat durability matters", "irrelevant text"]
    query = "moat durability"

    mock_model = MagicMock()
    # Scores: passage 1 is most relevant (higher logit)
    mock_model.predict.return_value = np.array([-2.0, 3.0, -5.0])

    mock_st = MagicMock()
    mock_st.CrossEncoder.return_value = mock_model

    with (
        _set_env(RAG_RERANKER_PROVIDER="local", RAG_RERANKER_LOCAL_MODEL="cross-encoder/ms-marco-MiniLM-L-6-v2"),
        patch.dict("sys.modules", {"sentence_transformers": mock_st}),
    ):
        from importlib import reload

        import app.rag.reranker as rm

        # Clear cache to force reload
        rm._local_model_cache.clear()
        reload(rm)
        rm._local_model_cache.clear()

        results = rm._rerank_local(query, passages, top_k=3)

    assert len(results) == 3
    # passage index 1 should be ranked first (highest logit)
    assert results[0].index == 1
    assert results[0].relevance_score > results[1].relevance_score


def test_local_reranker_caches_model():
    import numpy as np

    passages = ["a", "b"]
    query = "q"

    mock_model = MagicMock()
    mock_model.predict.return_value = np.array([0.5, 0.8])

    mock_st = MagicMock()
    mock_st.CrossEncoder.return_value = mock_model

    with (
        _set_env(RAG_RERANKER_PROVIDER="local", RAG_RERANKER_LOCAL_MODEL="cross-encoder/ms-marco-MiniLM-L-6-v2"),
        patch.dict("sys.modules", {"sentence_transformers": mock_st}),
    ):
        from importlib import reload

        import app.rag.reranker as rm

        rm._local_model_cache.clear()
        reload(rm)
        rm._local_model_cache.clear()

        rm._rerank_local(query, passages, top_k=2)
        rm._rerank_local(query, passages, top_k=2)

    # CrossEncoder constructor should only be called once (model is cached)
    assert mock_st.CrossEncoder.call_count == 1


# ── Fallback chain integration ────────────────────────────────────────────────


def test_fallback_chain_cross_encoder_to_llm_to_heuristic():
    """When cross-encoder fails, LLM fallback is tried; when that also fails, heuristic applies."""
    from app.rag.retrieval import RetrievedChunk

    def _mk_chunk(cid, text, dist):
        return RetrievedChunk(
            chunk_id=cid,
            document_id="doc-1",
            chunk_index=0,
            text=text,
            token_count=50,
            metadata_json={},
            cosine_distance=dist,
        )

    candidates = [
        _mk_chunk("c1", "capital allocation", 0.3),
        _mk_chunk("c2", "moat durability", 0.2),
        _mk_chunk("c3", "irrelevant text", 0.4),
    ]

    import app.rag.concept_mode as cm

    # Both cross-encoder and LLM fail — heuristic should apply
    with (
        patch("app.rag.concept_mode.reranker_available", return_value=True),
        patch("app.rag.concept_mode._cross_encoder_rerank", side_effect=RuntimeError("CE failed")),
        patch("app.rag.concept_mode.routing_available", return_value=False),
    ):
        result = cm._rerank_candidate_chunks("moat", candidates, top_k=3)

    assert len(result) >= 1
    # Should return chunks (heuristic path)
    chunk_ids = {c.chunk_id for c in result}
    assert chunk_ids.issubset({"c1", "c2", "c3"})


def test_cross_encoder_reranking_overrides_cosine_order():
    """Cross-encoder results should override vector-similarity ordering."""
    from app.rag.retrieval import RetrievedChunk

    from app.rag.reranker import RerankedResult

    def _mk_chunk(cid, text, dist):
        return RetrievedChunk(
            chunk_id=cid,
            document_id="doc-1",
            chunk_index=0,
            text=text,
            token_count=50,
            metadata_json={},
            cosine_distance=dist,
        )

    # c1 is closest by cosine, but c3 is most semantically relevant
    candidates = [
        _mk_chunk("c1", "unrelated noise text", 0.01),
        _mk_chunk("c2", "moat durability somewhat relevant", 0.20),
        _mk_chunk("c3", "moat durability highly relevant passage", 0.35),
    ]

    # Cross-encoder ranks c3 first, c2 second, c1 last
    ce_results = [
        RerankedResult(index=2, relevance_score=0.95, text=candidates[2].text),
        RerankedResult(index=1, relevance_score=0.60, text=candidates[1].text),
        RerankedResult(index=0, relevance_score=0.05, text=candidates[0].text),
    ]

    import app.rag.concept_mode as cm

    with (
        patch("app.rag.concept_mode.reranker_available", return_value=True),
        patch("app.rag.concept_mode._cross_encoder_rerank", return_value=ce_results),
    ):
        result = cm._rerank_candidate_chunks("moat durability", candidates, top_k=3)

    assert result[0].chunk_id == "c3"
    assert result[1].chunk_id == "c2"
    assert result[2].chunk_id == "c1"


def test_diversity_cap_still_applied_after_cross_encoder():
    """_select_diverse_top_chunks must still cap per-document results when diversity allows."""
    from app.rag.retrieval import RetrievedChunk

    from app.rag.reranker import RerankedResult

    def _mk_chunk(cid, text, dist, doc="doc-1"):
        return RetrievedChunk(
            chunk_id=cid,
            document_id=doc,
            chunk_index=int(cid[-1]),
            text=text,
            token_count=50,
            metadata_json={},
            cosine_distance=dist,
        )

    # 4 chunks from doc-1, 2 from doc-2
    candidates = [
        _mk_chunk("c1", "moat passage 1", 0.1, doc="doc-1"),
        _mk_chunk("c2", "moat passage 2", 0.2, doc="doc-1"),
        _mk_chunk("c3", "moat passage 3", 0.3, doc="doc-1"),
        _mk_chunk("c4", "moat passage 4", 0.4, doc="doc-1"),
        _mk_chunk("c5", "capital allocation A", 0.5, doc="doc-2"),
        _mk_chunk("c6", "capital allocation B", 0.6, doc="doc-2"),
    ]

    # Cross-encoder ranks doc-1 first, then doc-2
    ce_results = [
        RerankedResult(index=0, relevance_score=0.95, text=candidates[0].text),
        RerankedResult(index=1, relevance_score=0.90, text=candidates[1].text),
        RerankedResult(index=2, relevance_score=0.85, text=candidates[2].text),
        RerankedResult(index=3, relevance_score=0.80, text=candidates[3].text),
        RerankedResult(index=4, relevance_score=0.70, text=candidates[4].text),
        RerankedResult(index=5, relevance_score=0.65, text=candidates[5].text),
    ]

    import app.rag.concept_mode as cm

    with (
        patch("app.rag.concept_mode.reranker_available", return_value=True),
        patch("app.rag.concept_mode._cross_encoder_rerank", return_value=ce_results),
    ):
        # top_k=4 means we ask for 4 chunks; diversity cap = 2 per doc
        # Should get: c1, c2 from doc-1 + c5, c6 from doc-2 = 4 chunks, 2 from each doc
        result = cm._rerank_candidate_chunks("moat", candidates, top_k=4)

    doc1_count = sum(1 for c in result if c.document_id == "doc-1")
    doc2_count = sum(1 for c in result if c.document_id == "doc-2")
    assert doc1_count == 2
    assert doc2_count == 2
    assert len(result) == 4
