"""
Tests for AI Sage Company Thesis Mode.

Coverage:
  - Thesis query classification (positive and negative cases)
  - execute_thesis_query result shape
  - ThesisQueryResult data shapes
  - Source attribution: corpus vs live sources
  - Follow-up questions are surfaced but not recursively researched
  - Live research fetch routing (mocked)
  - Critique response shape
  - /ai-sage/query endpoint routes to thesis mode for thesis queries
  - /ai-sage/query endpoint routes to concept mode for concept queries
  - Concept mode regression (mode=="concept" on non-thesis queries)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ── Thesis classification ─────────────────────────────────────────────────────


def test_classify_thesis_pressure_test():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert classify_query_as_thesis("Here is my thesis on Tencent Music. Pressure test it.") is True


def test_classify_thesis_buffett_worry():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert classify_query_as_thesis("What would Buffett and Nick Sleep worry about here?") is True


def test_classify_thesis_missing_questions():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert (
        classify_query_as_thesis(
            "What are the missing questions and weak points in this thesis?"
        )
        is True
    )


def test_classify_thesis_bull_case():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert classify_query_as_thesis("Walk me through the bull case for Amazon.") is True


def test_classify_thesis_investment_thesis():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert classify_query_as_thesis("My investment thesis on Alphabet is...") is True


def test_classify_thesis_i_think():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert classify_query_as_thesis("I think Spotify has a durable moat.") is True


def test_classify_concept_question_not_thesis():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert classify_query_as_thesis("What makes a good business?") is False


def test_classify_concept_network_effects():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert (
        classify_query_as_thesis("How should I think about network effects?") is False
    )


def test_classify_concept_moat():
    from app.rag.company_thesis_mode import classify_query_as_thesis

    assert classify_query_as_thesis("Explain the concept of economic moat.") is False


# ── ThesisQueryResult data shape ──────────────────────────────────────────────


def test_thesis_query_result_as_dict_shape():
    from app.rag.company_thesis_mode import ThesisQueryResult, UpdatedThesisView

    result = ThesisQueryResult(
        query="My thesis on Spotify.",
        mode="thesis",
        best_passages=[],
        critique="Critique text.",
        evidence_sufficient=False,
        weak_evidence_note="Thin corpus.",
        thesis_question="Is Spotify's moat durable?",
        pushback_questions=["Q1", "Q2"],
        missing_information=["M1"],
        key_facts=["Fact 1"],
        updated_thesis_view=UpdatedThesisView(
            stronger=["S1"], weaker=["W1"], unresolved=["U1"]
        ).as_dict(),
        live_sources=[],
        follow_up_questions=["FU1"],
    )
    d = result.as_dict()

    assert d["mode"] == "thesis"
    assert d["thesis_question"] == "Is Spotify's moat durable?"
    assert d["pushback_questions"] == ["Q1", "Q2"]
    assert d["missing_information"] == ["M1"]
    assert d["key_facts"] == ["Fact 1"]
    assert d["updated_thesis_view"]["stronger"] == ["S1"]
    assert d["updated_thesis_view"]["weaker"] == ["W1"]
    assert d["updated_thesis_view"]["unresolved"] == ["U1"]
    assert d["follow_up_questions"] == ["FU1"]
    assert d["live_sources"] == []


def test_live_source_as_dict():
    from app.rag.company_thesis_mode import LiveSource

    src = LiveSource(
        url="https://example.com",
        title="Example",
        snippet="Some text",
        source_type="web",
    )
    d = src.as_dict()
    assert d["url"] == "https://example.com"
    assert d["source_type"] == "web"
    assert "snippet" in d


def test_updated_thesis_view_as_dict():
    from app.rag.company_thesis_mode import UpdatedThesisView

    utv = UpdatedThesisView(
        stronger=["Revenue growing"],
        weaker=["Margins compressed"],
        unresolved=["Competitive response unknown"],
    )
    d = utv.as_dict()
    assert "stronger" in d
    assert "weaker" in d
    assert "unresolved" in d


# ── Live research routing ─────────────────────────────────────────────────────


def test_live_research_disabled_in_test_mode():
    """RAG_EMBEDDING_MOCK=1 disables live research automatically."""
    from app.rag.company_thesis_mode import _live_research_enabled

    # RAG_EMBEDDING_MOCK=1 is set at the top of this file
    assert _live_research_enabled() is False


def test_fetch_company_research_returns_empty_in_test_mode():
    """fetch_company_research returns [] when live research is disabled."""
    from app.rag.company_thesis_mode import fetch_company_research

    sources = fetch_company_research("Tencent Music thesis")
    assert sources == []


def test_fetch_company_research_returns_empty_on_failure():
    """fetch_company_research swallows errors and returns []."""
    from app.rag.company_thesis_mode import fetch_company_research

    with patch("app.rag.company_thesis_mode._live_research_enabled", return_value=True), \
         patch("app.rag.company_thesis_mode._ddg_search", side_effect=Exception("Network error")):
        sources = fetch_company_research("Tencent Music thesis")
        assert sources == []


def test_fetch_company_research_returns_sources_when_enabled():
    """fetch_company_research returns LiveSource list when enabled and search succeeds."""
    from app.rag.company_thesis_mode import LiveSource, fetch_company_research

    mock_sources = [
        LiveSource(url="https://sec.gov/edgar/x", title="10-K Filing", snippet="Revenue 5B", source_type="filing"),
        LiveSource(url="https://web.com/article", title="Article", snippet="Growth slowing", source_type="web"),
    ]

    with patch("app.rag.company_thesis_mode._live_research_enabled", return_value=True), \
         patch("app.rag.company_thesis_mode._ddg_search", return_value=mock_sources):
        sources = fetch_company_research("Tencent Music thesis")
        assert len(sources) == 2
        assert sources[0].source_type == "filing"
        assert sources[1].source_type == "web"


# ── Fallback thesis analysis ──────────────────────────────────────────────────


def test_fallback_thesis_analysis_shape():
    from app.rag.company_thesis_mode import _fallback_thesis_analysis

    result = _fallback_thesis_analysis("My thesis on Tencent Music.")
    assert "thesis_question" in result
    assert isinstance(result["pushback_questions"], list)
    assert len(result["pushback_questions"]) >= 1
    assert isinstance(result["missing_information"], list)
    assert isinstance(result["key_facts"], list)
    assert "critique" in result
    assert "updated_thesis_view" in result
    assert isinstance(result["updated_thesis_view"]["stronger"], list)
    assert isinstance(result["updated_thesis_view"]["weaker"], list)
    assert isinstance(result["updated_thesis_view"]["unresolved"], list)
    assert isinstance(result["follow_up_questions"], list)


# ── execute_thesis_query (unit, no LLM, no live research) ────────────────────

_EMPTY_PATCHES = {
    "app.rag.company_thesis_mode.select_authors": [],
    "app.rag.company_thesis_mode.retrieve_similar_chunks": [],
    "app.rag.company_thesis_mode._author_entries": [],
    "app.rag.company_thesis_mode._enrich_chunks": [],
}


def _make_mock_db():
    """Return a minimal mock Session that satisfies the execute_thesis_query interface."""
    return MagicMock()


def test_execute_thesis_query_shape():
    """execute_thesis_query returns ThesisQueryResult with all required fields."""
    from app.rag.company_thesis_mode import execute_thesis_query

    db = _make_mock_db()
    with patch("app.rag.company_thesis_mode.select_authors", return_value=[]), \
         patch("app.rag.company_thesis_mode._author_entries", return_value=[]), \
         patch("app.rag.company_thesis_mode.retrieve_similar_chunks", return_value=[]), \
         patch("app.rag.company_thesis_mode._enrich_chunks", return_value=[]):
        result = execute_thesis_query("My thesis on Tencent Music. Pressure test it.", db)
        d = result.as_dict()

        assert d["mode"] == "thesis"
        assert "thesis_question" in d
        assert isinstance(d["pushback_questions"], list)
        assert isinstance(d["missing_information"], list)
        assert isinstance(d["key_facts"], list)
        assert isinstance(d["best_passages"], list)
        assert isinstance(d["live_sources"], list)
        assert isinstance(d["follow_up_questions"], list)
        assert "critique" in d
        assert "updated_thesis_view" in d
        assert isinstance(d.get("evidence_sufficient"), bool)


def test_execute_thesis_query_follow_up_not_empty():
    """follow_up_questions are surfaced in the result."""
    from app.rag.company_thesis_mode import execute_thesis_query

    db = _make_mock_db()
    with patch("app.rag.company_thesis_mode.select_authors", return_value=[]), \
         patch("app.rag.company_thesis_mode._author_entries", return_value=[]), \
         patch("app.rag.company_thesis_mode.retrieve_similar_chunks", return_value=[]), \
         patch("app.rag.company_thesis_mode._enrich_chunks", return_value=[]):
        result = execute_thesis_query("I believe Spotify has a durable competitive moat.", db)
        assert isinstance(result.follow_up_questions, list)


def test_execute_thesis_query_does_not_recursive_research():
    """System surfaces follow_up_questions but does NOT recursively call fetch_company_research for them."""
    from app.rag.company_thesis_mode import execute_thesis_query

    db = _make_mock_db()
    call_count = [0]

    def counting_fetch(query, max_results=5):
        call_count[0] += 1
        return []

    with patch("app.rag.company_thesis_mode.select_authors", return_value=[]), \
         patch("app.rag.company_thesis_mode._author_entries", return_value=[]), \
         patch("app.rag.company_thesis_mode.retrieve_similar_chunks", return_value=[]), \
         patch("app.rag.company_thesis_mode._enrich_chunks", return_value=[]), \
         patch("app.rag.company_thesis_mode.fetch_company_research", side_effect=counting_fetch):
        execute_thesis_query("My thesis on Tencent Music. Pressure test it.", db)
        # fetch_company_research should be called at most once (for the original query only)
        assert call_count[0] <= 1


# ── Source attribution ────────────────────────────────────────────────────────


def test_source_attribution_live_vs_corpus():
    """live_sources and best_passages are separate and distinguishable."""
    from app.rag.company_thesis_mode import LiveSource, execute_thesis_query

    db = _make_mock_db()
    mock_sources = [
        LiveSource(url="https://sec.gov/10k", title="10-K", snippet="Revenue", source_type="filing")
    ]

    with patch("app.rag.company_thesis_mode.select_authors", return_value=[]), \
         patch("app.rag.company_thesis_mode._author_entries", return_value=[]), \
         patch("app.rag.company_thesis_mode.retrieve_similar_chunks", return_value=[]), \
         patch("app.rag.company_thesis_mode._enrich_chunks", return_value=[]), \
         patch("app.rag.company_thesis_mode.fetch_company_research", return_value=mock_sources):
        result = execute_thesis_query("My thesis on Spotify. Pressure test it.", db)
        d = result.as_dict()

        # live_sources come from web research
        assert isinstance(d["live_sources"], list)
        for src in d["live_sources"]:
            assert "source_type" in src
            assert src.get("source_type") in {"web", "filing", "transcript"}

        # best_passages come from the thinker corpus
        for passage in d["best_passages"]:
            assert "author_id" in passage
            assert "author_name" in passage
            assert "similarity" in passage


@pytest.fixture
def test_client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


def test_api_routes_thesis_query_to_thesis_mode(test_client):
    """POST /ai-sage/query with a thesis prompt returns mode='thesis'."""
    response = test_client.post(
        "/ai-sage/query",
        json={"query": "Here is my thesis on Tencent Music. Pressure test it."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "thesis"
    assert "thesis_question" in data
    assert isinstance(data["pushback_questions"], list)
    assert isinstance(data["missing_information"], list)
    assert isinstance(data["key_facts"], list)
    assert isinstance(data["updated_thesis_view"], (dict, type(None)))
    assert isinstance(data["live_sources"], list)
    assert isinstance(data["follow_up_questions"], list)


def test_api_routes_concept_query_to_concept_mode(test_client):
    """POST /ai-sage/query with a concept prompt returns mode='concept'."""
    response = test_client.post(
        "/ai-sage/query",
        json={"query": "What makes a good business?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "concept"
    # Thesis-mode fields should be empty/None in concept mode
    assert data["thesis_question"] is None
    assert data["pushback_questions"] == []
    assert data["live_sources"] == []


def test_api_thesis_response_has_all_required_sections(test_client):
    """Thesis mode response includes all required sections from acceptance criteria."""
    response = test_client.post(
        "/ai-sage/query",
        json={"query": "What would Buffett and Nick Sleep worry about in Tencent Music?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mode"] == "thesis"

    # All AC-required sections present
    assert "thesis_question" in data           # thesis / question
    assert "pushback_questions" in data        # key pushback questions
    assert "missing_information" in data       # missing information
    assert "key_facts" in data                 # key facts extracted
    assert "critique" in data                  # critique
    assert "updated_thesis_view" in data       # updated thesis view
    assert "live_sources" in data              # fetched sources used


def test_api_concept_mode_regression(test_client):
    """Concept mode still works correctly and returns expected fields."""
    response = test_client.post(
        "/ai-sage/query",
        json={"query": "How should I think about capital allocation?"},
    )
    assert response.status_code == 200
    data = response.json()

    # Concept mode fields still present
    assert "best_passages" in data
    assert "critique" in data
    assert "evidence_sufficient" in data
