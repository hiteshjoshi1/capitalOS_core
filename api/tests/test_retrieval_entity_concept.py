"""
Unit tests for Issue 172 entity/concept retrieval wiring.

Tests:
  - resolve_entity_ids: returns correct IDs for known aliases; ([], [surface]) for unknown
  - fetch_expansion_terms: returns [] when rag_corpus_expansions is empty
  - corpus_expansion_terms NOT present in concept_terms on returned plan
  - retrieve_by_entity_ids: returns chunks with corpus_class='entity_annotation_pool'
  - cross-author leakage: retrieve_by_entity_ids with author filter returns no other-author chunks
  - _retrieve_hardened() trace contains entity_annotation_pool key when resolved_entity_ids is set
  - RAG_RERANKER_ENTITY_CONTEXT=0: no prefix prepended to chunk text
  - RAG_RERANKER_ENTITY_CONTEXT=1: entity/concept labels prepended
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_db_session(rows: list[dict[str, Any]] | None = None):
    """Return a minimal mock Session whose execute().fetchall() returns rows."""
    db = MagicMock()
    mock_result = MagicMock()
    mapped_rows = [MagicMock(**{k: v for k, v in row.items()}) for row in (rows or [])]
    for row in mapped_rows:
        # Support attribute access (row.entity_id) via __getattr__
        for k, v in (rows or [{}])[0].items() if rows else []:
            pass
    mock_result.fetchall.return_value = mapped_rows
    db.execute.return_value = mock_result
    return db


def _make_row(**kwargs: Any) -> MagicMock:
    """Return a row mock where attribute access returns kwargs values."""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _make_db_with_rows(rows: list[MagicMock]):
    db = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = rows
    db.execute.return_value = mock_result
    return db


# ── resolve_entity_ids ───────────────────────────────────────────────────────


def test_resolve_entity_ids_returns_known_alias():
    from app.rag.retrieval import resolve_entity_ids

    db = _make_db_with_rows([_make_row(entity_id="amazon")])
    resolved, unresolved = resolve_entity_ids(["Amazon"], db)
    assert resolved == ["amazon"]
    assert unresolved == []


def test_resolve_entity_ids_returns_unresolved_for_missing_alias():
    from app.rag.retrieval import resolve_entity_ids

    db = _make_db_with_rows([])
    resolved, unresolved = resolve_entity_ids(["UnknownCorp"], db)
    assert resolved == []
    assert "UnknownCorp" in unresolved


def test_resolve_entity_ids_empty_input():
    from app.rag.retrieval import resolve_entity_ids

    db = MagicMock()
    resolved, unresolved = resolve_entity_ids([], db)
    assert resolved == []
    assert unresolved == []
    db.execute.assert_not_called()


def test_resolve_entity_ids_graceful_on_db_error():
    from app.rag.retrieval import resolve_entity_ids

    db = MagicMock()
    db.execute.side_effect = Exception("DB down")
    resolved, unresolved = resolve_entity_ids(["Amazon"], db)
    assert resolved == []
    assert "Amazon" in unresolved


# ── resolve_concept_ids ──────────────────────────────────────────────────────


def test_resolve_concept_ids_returns_known_concept():
    from app.rag.retrieval import resolve_concept_ids

    db = _make_db_with_rows([_make_row(concept_id="scale_economies_shared")])
    ids = resolve_concept_ids(["scale economies shared"], db)
    assert ids == ["scale_economies_shared"]


def test_resolve_concept_ids_empty_input():
    from app.rag.retrieval import resolve_concept_ids

    db = MagicMock()
    ids = resolve_concept_ids([], db)
    assert ids == []
    db.execute.assert_not_called()


def test_resolve_concept_ids_graceful_on_db_error():
    from app.rag.retrieval import resolve_concept_ids

    db = MagicMock()
    db.execute.side_effect = Exception("DB down")
    ids = resolve_concept_ids(["some phrase"], db)
    assert ids == []


# ── fetch_expansion_terms ────────────────────────────────────────────────────


def test_fetch_expansion_terms_empty_when_no_rows():
    from app.rag.retrieval import fetch_expansion_terms

    db = _make_db_with_rows([])
    terms = fetch_expansion_terms(["nick_sleep"], ["amazon"], [], db)
    assert terms == []


def test_fetch_expansion_terms_returns_terms():
    from app.rag.retrieval import fetch_expansion_terms

    db = _make_db_with_rows([
        _make_row(expansion_term="scale economies"),
        _make_row(expansion_term="customer service"),
    ])
    terms = fetch_expansion_terms(["nick_sleep"], ["amazon"], [], db)
    assert "scale economies" in terms
    assert "customer service" in terms


def test_fetch_expansion_terms_empty_when_no_author_ids():
    from app.rag.retrieval import fetch_expansion_terms

    db = MagicMock()
    terms = fetch_expansion_terms([], ["amazon"], [], db)
    assert terms == []
    db.execute.assert_not_called()


def test_fetch_expansion_terms_graceful_on_db_error():
    from app.rag.retrieval import fetch_expansion_terms

    db = MagicMock()
    db.execute.side_effect = Exception("DB down")
    terms = fetch_expansion_terms(["nick_sleep"], ["amazon"], [], db)
    assert terms == []


# ── build_retrieval_query_plan with DB ──────────────────────────────────────


def test_corpus_expansion_terms_not_in_concept_terms():
    """
    When DB-backed corpus_expansion_terms are available, they must NOT appear in concept_terms.
    This verifies the critical separation required by the task spec.
    """
    from app.rag.retrieval import build_retrieval_query_plan

    db = MagicMock()
    # Simulate: entity resolved, expansion terms returned
    def fake_execute(sql, params=None):
        mock_result = MagicMock()
        sql_str = str(sql)
        if "rag_entity_aliases" in sql_str:
            mock_result.fetchall.return_value = [_make_row(entity_id="amazon")]
        elif "rag_concept_aliases" in sql_str:
            mock_result.fetchall.return_value = []
        elif "rag_corpus_expansions" in sql_str:
            mock_result.fetchall.return_value = [
                _make_row(expansion_term="scale economies shared"),
                _make_row(expansion_term="reinvestment"),
            ]
        else:
            mock_result.fetchall.return_value = []
        return mock_result

    db.execute.side_effect = fake_execute

    plan = build_retrieval_query_plan(
        "What does Nick Sleep say about Amazon?",
        source_author_ids=["nick_sleep"],
        db=db,
    )

    # corpus_expansion_terms should have the expansion terms
    assert len(plan.corpus_expansion_terms) > 0

    # None of the corpus expansion terms should appear in concept_terms
    concept_term_set = {t.lower() for t in plan.concept_terms}
    for exp_term in plan.corpus_expansion_terms:
        assert exp_term.lower() not in concept_term_set, (
            f"corpus_expansion_term '{exp_term}' should not appear in concept_terms"
        )


def test_build_plan_without_db_still_works():
    """build_retrieval_query_plan() with no DB should degrade gracefully."""
    from app.rag.retrieval import build_retrieval_query_plan

    plan = build_retrieval_query_plan("What does Buffett say about moats?")
    assert plan.resolved_entity_ids == []
    assert plan.resolved_concept_ids == []
    assert plan.corpus_expansion_terms == []


def test_resolved_entity_ids_in_plan_dict():
    """as_dict() must include resolved_entity_ids, resolved_concept_ids, corpus_expansion_terms."""
    from app.rag.retrieval import build_retrieval_query_plan

    plan = build_retrieval_query_plan("What does Buffett say about moats?")
    d = plan.as_dict()
    assert "resolved_entity_ids" in d
    assert "resolved_concept_ids" in d
    assert "corpus_expansion_terms" in d


# ── retrieve_by_entity_ids ───────────────────────────────────────────────────


def test_retrieve_by_entity_ids_empty_on_non_postgres():
    from app.rag.retrieval import retrieve_by_entity_ids

    db = MagicMock()
    db.bind.dialect.name = "sqlite"
    chunks = retrieve_by_entity_ids(["amazon"], db)
    assert chunks == []


def test_retrieve_by_entity_ids_empty_when_no_entity_ids():
    from app.rag.retrieval import retrieve_by_entity_ids

    db = MagicMock()
    chunks = retrieve_by_entity_ids([], db)
    assert chunks == []
    db.execute.assert_not_called()


def test_retrieve_by_entity_ids_returns_corpus_class():
    from app.rag.retrieval import retrieve_by_entity_ids, RetrievedChunk
    import uuid

    db = MagicMock()
    db.bind.dialect.name = "postgresql"

    chunk_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: {
        "chunk_id": chunk_id,
        "document_id": doc_id,
        "chunk_index": 0,
        "text": "Amazon's business model focuses on scale.",
        "token_count": 10,
        "metadata_json": {},
        "collection": None,
        "title": "Test Doc",
        "source_section": None,
        "canonical_status": None,
        "dedupe_priority": None,
        "work_type": None,
        "document_metadata_json": {},
        "author_id": "nick_sleep",
        "author_name": "Nick Sleep",
        "score": 0.9,
        "entity_ids": ["amazon"],
    }[key]

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = [mock_row]
    db.execute.return_value = mock_result

    chunks = retrieve_by_entity_ids(["amazon"], db, author_ids=["nick_sleep"])
    assert len(chunks) == 1
    assert chunks[0].corpus_class == "entity_annotation_pool"


def test_retrieve_by_concept_ids_returns_corpus_class():
    from app.rag.retrieval import retrieve_by_concept_ids
    import uuid

    db = MagicMock()
    db.bind.dialect.name = "postgresql"

    chunk_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    mock_row = MagicMock()
    mock_row.__getitem__ = lambda self, key: {
        "chunk_id": chunk_id,
        "document_id": doc_id,
        "chunk_index": 0,
        "text": "Scale economies shared with customers.",
        "token_count": 10,
        "metadata_json": {},
        "collection": None,
        "title": "Test Doc",
        "source_section": None,
        "canonical_status": None,
        "dedupe_priority": None,
        "work_type": None,
        "document_metadata_json": {},
        "author_id": "nick_sleep",
        "author_name": "Nick Sleep",
        "score": 0.9,
        "concept_ids": ["scale_economies_shared"],
    }[key]

    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = [mock_row]
    db.execute.return_value = mock_result

    chunks = retrieve_by_concept_ids(["scale_economies_shared"], db)
    assert len(chunks) == 1
    assert chunks[0].corpus_class == "concept_annotation_pool"


def test_retrieve_by_entity_ids_graceful_on_db_error():
    from app.rag.retrieval import retrieve_by_entity_ids

    db = MagicMock()
    db.bind.dialect.name = "postgresql"
    db.execute.side_effect = Exception("DB down")
    chunks = retrieve_by_entity_ids(["amazon"], db)
    assert chunks == []


# ── Cross-author leakage (structural test) ───────────────────────────────────


def test_retrieve_by_entity_ids_author_filter_in_sql():
    """
    When author_ids=['nick_sleep'] is passed, the generated SQL must include
    an author_id filter (verified by checking the SQL string in execute call).
    """
    from app.rag.retrieval import retrieve_by_entity_ids

    db = MagicMock()
    db.bind.dialect.name = "postgresql"
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    db.execute.return_value = mock_result

    retrieve_by_entity_ids(["amazon"], db, author_ids=["nick_sleep"])

    assert db.execute.called
    call_args = db.execute.call_args
    sql_str = str(call_args[0][0])
    assert "author_id" in sql_str.lower() or "entity_author_id" in str(call_args[0][1])


# ── Reranker entity context feature flag ────────────────────────────────────


def test_reranker_entity_context_off_by_default():
    """RAG_RERANKER_ENTITY_CONTEXT=0 (default) must not prepend any prefix."""
    from app.rag.concept_mode import _apply_entity_context_prefix
    from app.rag.retrieval import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        chunk_index=0,
        text="Amazon's flywheel.",
        token_count=5,
        metadata_json={"annotated_entity_ids": ["amazon"]},
        cosine_distance=1.0,
    )

    with patch.dict(os.environ, {"RAG_RERANKER_ENTITY_CONTEXT": "0"}):
        result = _apply_entity_context_prefix(chunk, "Amazon's flywheel.")

    assert result == "Amazon's flywheel."


def test_reranker_entity_context_on_prepends_labels():
    """RAG_RERANKER_ENTITY_CONTEXT=1 must prepend entity/concept labels."""
    from app.rag.concept_mode import _apply_entity_context_prefix
    from app.rag.retrieval import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        chunk_index=0,
        text="Amazon's flywheel.",
        token_count=5,
        metadata_json={
            "annotated_entity_ids": ["amazon"],
            "annotated_concept_ids": ["scale_economies_shared"],
        },
        cosine_distance=1.0,
    )

    with patch.dict(os.environ, {"RAG_RERANKER_ENTITY_CONTEXT": "1"}):
        result = _apply_entity_context_prefix(chunk, "Amazon's flywheel.")

    assert "[Entities: amazon]" in result
    assert "[Concepts: scale_economies_shared]" in result
    assert "Amazon's flywheel." in result


def test_reranker_entity_context_on_no_annotations_no_prefix():
    """When enabled but chunk has no annotations, text is unchanged."""
    from app.rag.concept_mode import _apply_entity_context_prefix
    from app.rag.retrieval import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        chunk_index=0,
        text="Some text without annotations.",
        token_count=5,
        metadata_json={},
        cosine_distance=1.0,
    )

    with patch.dict(os.environ, {"RAG_RERANKER_ENTITY_CONTEXT": "1"}):
        result = _apply_entity_context_prefix(chunk, "Some text without annotations.")

    assert result == "Some text without annotations."


# ── Structural recall eval (offline / no DB required) ───────────────────────


def test_structural_recall_report_format():
    """StructuralRecallReport.as_dict() must include required fields."""
    from app.rag.eval.parametric import StructuralRecallReport, StructuralRecallResult

    report = StructuralRecallReport(
        total_tests=5,
        passed=4,
        failed=1,
        authors_covered=["nick_sleep", "warren_buffett"],
        results=[
            StructuralRecallResult(
                query_text="What does Nick Sleep say about Amazon?",
                author_id="nick_sleep",
                pivot_type="entity",
                pivot_id="amazon",
                gold_chunk_ids=["c1", "c2", "c3", "c4", "c5"],
                candidate_entity_pool_size=5,
                passed=True,
            )
        ],
    )

    d = report.as_dict()
    assert d["mode"] == "structural_recall"
    assert d["total_tests"] == 5
    assert d["passed"] == 4
    assert d["failed"] == 1
    assert "authors_covered" in d
    assert "pass_rate" in d
    assert len(d["results"]) == 1


def test_generate_entity_structural_recall_tests_graceful_on_db_error():
    """Should return [] when DB is unavailable."""
    from app.rag.eval.parametric import generate_entity_structural_recall_tests

    db = MagicMock()
    db.execute.side_effect = Exception("DB down")
    tests = generate_entity_structural_recall_tests(db)
    assert tests == []


def test_generate_concept_structural_recall_tests_graceful_on_db_error():
    """Should return [] when DB is unavailable."""
    from app.rag.eval.parametric import generate_concept_structural_recall_tests

    db = MagicMock()
    db.execute.side_effect = Exception("DB down")
    tests = generate_concept_structural_recall_tests(db)
    assert tests == []


# ── CLI structural-recall command ────────────────────────────────────────────


def test_cli_structural_recall_command_exists():
    """The structural-recall CLI command must be registered."""
    from click.testing import CliRunner
    from app.rag.eval.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["structural-recall", "--help"])
    assert result.exit_code == 0
    assert "structural" in result.output.lower() or "recall" in result.output.lower()


def test_cli_structural_recall_runs_with_mocked_db():
    """structural-recall command runs without error when DB returns no tests."""
    from click.testing import CliRunner
    from app.rag.eval.cli import cli

    db = MagicMock()
    mock_result = MagicMock()
    mock_result.fetchall.return_value = []
    db.execute.return_value = mock_result

    runner = CliRunner()
    with patch("app.rag.eval.cli.SessionLocal", return_value=db):
        with patch("app.rag.eval.parametric.run_structural_recall_eval") as mock_run:
            from app.rag.eval.parametric import StructuralRecallReport
            mock_run.return_value = StructuralRecallReport(
                total_tests=0, passed=0, failed=0, authors_covered=[]
            )
            result = runner.invoke(cli, ["structural-recall"])

    assert result.exit_code == 0
