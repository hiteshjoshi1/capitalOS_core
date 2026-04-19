from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from app.rag.author_selection import SelectedAuthor
from app.rag.intent_router import QueryIntent
from app.rag.query import EvidenceChunk
from app.rag.retrieval import RetrievedChunk

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_retrieval_pipeline_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


def _mk_chunk(
    chunk_id: str,
    *,
    text: str,
    cosine_distance: float,
    document_id: str = "doc-1",
    chunk_index: int = 0,
    author_id: str = "warren_buffett",
    author_name: str = "Warren Buffett",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        chunk_index=chunk_index,
        text=text,
        token_count=120,
        metadata_json={"author_id": author_id, "author_name": author_name},
        cosine_distance=cosine_distance,
    )


def _fake_enrich(raw_chunks: list[RetrievedChunk], _db, _author_map) -> list[EvidenceChunk]:
    evidence: list[EvidenceChunk] = []
    for chunk in raw_chunks:
        meta = chunk.metadata_json or {}
        evidence.append(
            EvidenceChunk(
                chunk_id=chunk.chunk_id,
                author_id=str(meta.get("author_id", "unknown")),
                author_name=str(meta.get("author_name", "unknown")),
                text=chunk.text,
                similarity=chunk.similarity,
                metadata=meta,
            )
        )
    return evidence


def _routing_client_with_indices(indices_json: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = indices_json
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create.return_value = response
    return client


def test_broad_retrieval_uses_larger_candidate_pool_than_final_top_k():
    import app.rag.concept_mode as cm

    intent = QueryIntent(query_type="open")

    with (
        patch("app.rag.concept_mode.parse_intent", return_value=intent),
        patch("app.rag.concept_mode.select_authors", return_value=[]),
        patch("app.rag.concept_mode._author_entries", return_value=[]),
        patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]) as mock_retrieve,
        patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
    ):
        cm.execute_concept_query("What does Buffett say about Charlie Munger?", MagicMock(), top_k_chunks=6)

    assert mock_retrieve.call_count >= 1
    assert mock_retrieve.call_args_list[0].kwargs["top_k"] > 6


def test_reranking_uses_heuristic_without_cross_encoder():
    """When no cross-encoder reranker is available and LLM reranking is disabled,
    heuristic ranking (keyword overlap + cosine) determines order."""
    import app.rag.concept_mode as cm

    candidates = [
        _mk_chunk("c1", text="Repeated mistakes motif.", cosine_distance=0.01, chunk_index=1),
        _mk_chunk("c2", text="Patience and capital allocation.", cosine_distance=0.02, chunk_index=2),
        _mk_chunk(
            "c3",
            text="Think like a business owner, not a stock picker.",
            cosine_distance=0.03,
            chunk_index=3,
        ),
    ]
    selected = [
        SelectedAuthor(
            author_id="warren_buffett",
            name="Warren Buffett",
            score=5.0,
            domains=["investing"],
            expertise_tags=[],
            overall_weight=4.0,
            role_type="investor",
        )
    ]
    author_entries = [{"author_id": "warren_buffett", "name": "Warren Buffett"}]

    with (
        patch("app.rag.concept_mode.parse_intent", return_value=QueryIntent(query_type="single_author", author_ids=["warren_buffett"])),
        patch("app.rag.concept_mode.select_authors", return_value=selected),
        patch("app.rag.concept_mode._author_entries", return_value=author_entries),
        patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=candidates),
        patch("app.rag.concept_mode.reranker_available", return_value=False),
        patch("app.rag.concept_mode.routing_available", return_value=False),
        patch("app.rag.concept_mode.expand_chunks_with_context", side_effect=lambda chunks, *_args, **_kwargs: chunks),
        patch("app.rag.concept_mode._enrich_chunks", side_effect=_fake_enrich),
        patch("app.rag.concept_mode.inference_available", return_value=False),
    ):
        result = cm.execute_concept_query(
            "How does Buffett describe thinking like a business owner rather than a stock picker?",
            MagicMock(),
            top_k_chunks=2,
        )

    assert len(result.best_passages) == 2
    # Heuristic ranking: c3 has best keyword overlap ("business owner", "stock picker")
    # followed by c1 or c2 by cosine distance
    chunk_ids = [p["chunk_id"] for p in result.best_passages]
    assert "c3" in chunk_ids  # best keyword overlap should appear


def test_context_expansion_is_used_for_author_view_synthesis_and_critique():
    import app.rag.concept_mode as cm

    candidates = [
        _mk_chunk("n1", text="Scale economies shared core passage.", cosine_distance=0.04, author_id="nick_sleep", author_name="Nick Sleep"),
        _mk_chunk("n2", text="Customer service and long-termism.", cosine_distance=0.05, document_id="doc-2", chunk_index=1, author_id="nick_sleep", author_name="Nick Sleep"),
    ]
    selected = [
        SelectedAuthor(
            author_id="nick_sleep",
            name="Nick Sleep",
            score=4.2,
            domains=["investing"],
            expertise_tags=["scale_economies_shared"],
            overall_weight=3.5,
            role_type="investor",
        )
    ]
    author_entries = [{"author_id": "nick_sleep", "name": "Nick Sleep"}]

    def _expand(chunks: list[RetrievedChunk], *_args, **_kwargs) -> list[RetrievedChunk]:
        expanded: list[RetrievedChunk] = []
        for chunk in chunks:
            expanded.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    chunk_index=chunk.chunk_index,
                    text=f"{chunk.text} [expanded context]",
                    token_count=chunk.token_count,
                    metadata_json=chunk.metadata_json,
                    cosine_distance=chunk.cosine_distance,
                )
            )
        return expanded

    with (
        patch.dict("os.environ", {"AI_SAGE_CRITIQUE_ENABLED": "1", "AI_SAGE_SYNTHESIS_ENABLED": "1"}, clear=False),
        patch("app.rag.concept_mode.parse_intent", return_value=QueryIntent(query_type="open")),
        patch("app.rag.concept_mode.select_authors", return_value=selected),
        patch("app.rag.concept_mode._author_entries", return_value=author_entries),
        patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=candidates),
        patch("app.rag.concept_mode.routing_available", return_value=False),
        patch("app.rag.concept_mode.expand_chunks_with_context", side_effect=_expand),
        patch("app.rag.concept_mode._enrich_chunks", side_effect=_fake_enrich),
        patch("app.rag.concept_mode.inference_available", return_value=True),
        patch("app.rag.concept_mode._llm_author_view", return_value="author view") as mock_author_view,
        patch("app.rag.concept_mode._llm_synthesis", return_value="synthesis text"),
        patch("app.rag.concept_mode._llm_critique", return_value="critique text"),
        patch("app.rag.concept_mode._llm_suggested_readings", return_value=[]),
    ):
        result = cm.execute_concept_query(
            "What does Nick Sleep mean by scale economies shared?",
            MagicMock(),
            top_k_chunks=2,
        )

    llm_call = mock_author_view.call_args
    assert llm_call is not None
    passages = llm_call.args[4]
    assert any("[expanded context]" in passage for passage in passages)
    assert all("[expanded context]" not in passage["text"] for passage in result.best_passages)
    assert all("[expanded context]" in str(passage["metadata"].get("context_text", "")) for passage in result.best_passages)
    assert result.synthesis == "synthesis text"
    assert result.critique == "critique text"


def test_buffett_query_surfaces_results_by_heuristic_rank():
    """Without cross-encoder, heuristic ranking uses keyword overlap + cosine distance."""
    import app.rag.concept_mode as cm

    candidates = [
        _mk_chunk("b1", text="Charlie and mistakes.", cosine_distance=0.01),
        _mk_chunk("b2", text="Think like business owners, not stock pickers.", cosine_distance=0.02, chunk_index=2),
        _mk_chunk("b3", text="Patience in capital allocation over decades.", cosine_distance=0.03, chunk_index=3),
    ]
    selected = [
        SelectedAuthor(
            author_id="warren_buffett",
            name="Warren Buffett",
            score=5.0,
            domains=["investing"],
            expertise_tags=[],
            overall_weight=4.0,
            role_type="investor",
        )
    ]

    with (
        patch("app.rag.concept_mode.parse_intent", return_value=QueryIntent(query_type="single_author", author_ids=["warren_buffett"])),
        patch("app.rag.concept_mode.select_authors", return_value=selected),
        patch("app.rag.concept_mode._author_entries", return_value=[{"author_id": "warren_buffett", "name": "Warren Buffett"}]),
        patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=candidates),
        patch("app.rag.concept_mode.reranker_available", return_value=False),
        patch("app.rag.concept_mode.routing_available", return_value=False),
        patch("app.rag.concept_mode.expand_chunks_with_context", side_effect=lambda chunks, *_args, **_kwargs: chunks),
        patch("app.rag.concept_mode._enrich_chunks", side_effect=_fake_enrich),
        patch("app.rag.concept_mode.inference_available", return_value=False),
    ):
        result = cm.execute_concept_query("What does Buffett say about Charlie Munger?", MagicMock(), top_k_chunks=2)

    # b1 has keyword overlap ("charlie") + lowest cosine → should rank first
    texts = [p["text"].lower() for p in result.best_passages]
    assert any("charlie" in t for t in texts)


def test_nick_sleep_query_surfaces_multiple_distinct_examples():
    import app.rag.concept_mode as cm

    candidates = [
        _mk_chunk(
            "s1",
            text="Amazon shares scale economies with customers through lower prices.",
            cosine_distance=0.02,
            author_id="nick_sleep",
            author_name="Nick Sleep",
        ),
        _mk_chunk(
            "s2",
            text="Costco membership model reinforces customer service and trust.",
            cosine_distance=0.03,
            chunk_index=1,
            author_id="nick_sleep",
            author_name="Nick Sleep",
        ),
        _mk_chunk(
            "s3",
            text="Long-termism is behavior: hold compounders through volatility.",
            cosine_distance=0.04,
            chunk_index=2,
            author_id="nick_sleep",
            author_name="Nick Sleep",
        ),
    ]
    selected = [
        SelectedAuthor(
            author_id="nick_sleep",
            name="Nick Sleep",
            score=4.2,
            domains=["investing"],
            expertise_tags=["scale_economies_shared"],
            overall_weight=3.5,
            role_type="investor",
        )
    ]

    with (
        patch("app.rag.concept_mode.parse_intent", return_value=QueryIntent(query_type="single_author", author_ids=["nick_sleep"])),
        patch("app.rag.concept_mode.select_authors", return_value=selected),
        patch("app.rag.concept_mode._author_entries", return_value=[{"author_id": "nick_sleep", "name": "Nick Sleep"}]),
        patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=candidates),
        patch("app.rag.concept_mode.routing_available", return_value=True),
        patch("app.rag.concept_mode.create_routing_client", return_value=_routing_client_with_indices("[1, 2, 3]")),
        patch("app.rag.concept_mode.routing_model", return_value="qwen/qwen-2.5-7b-instruct"),
        patch("app.rag.concept_mode.expand_chunks_with_context", side_effect=lambda chunks, *_args, **_kwargs: chunks),
        patch("app.rag.concept_mode._enrich_chunks", side_effect=_fake_enrich),
        patch("app.rag.concept_mode.inference_available", return_value=False),
    ):
        result = cm.execute_concept_query(
            "What does Nick Sleep say about Amazon, Costco, and service to customers?",
            MagicMock(),
            top_k_chunks=3,
        )

    texts = [p["text"].lower() for p in result.best_passages]
    assert any("amazon" in t for t in texts)
    assert any("costco" in t for t in texts)
    assert any("long-termism" in t for t in texts)
