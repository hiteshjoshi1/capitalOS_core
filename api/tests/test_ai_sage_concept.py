"""
Tests for AI Sage Concept Mode.

Coverage:
  - ConceptQueryResult data shape
  - execute_concept_query routing (unit-level, no LLM)
  - Author selection integration (select_authors called with query)
  - Critique shape
  - /ai-sage/query endpoint (API-level, TestClient + SQLite)
  - Weak evidence behaviour
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_ai_sage_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def rag_yaml_file(tmp_path_factory):
    content = """
authors:
  - id: warren_buffett
    name: Warren Buffett
    enabled: true
    domains: [investing, business_quality]
    expertise_tags: [moat, capital_allocation, valuation]
    overall_weight: 4.0
    role_type: investor
    reasoning_lens:
      focus:
        - durable competitive advantage
        - long-term earnings power
      avoid:
        - macro speculation
      biases:
        - strong preference for simplicity

  - id: nick_sleep
    name: Nick Sleep
    enabled: true
    domains: [investing, business_quality]
    expertise_tags: [scale_economies_shared, network_effects, long_term]
    overall_weight: 3.5
    role_type: investor
    reasoning_lens:
      focus:
        - scale economies shared
        - destination businesses
      avoid:
        - short-term earnings focus
      biases:
        - strongly prefers businesses that share cost savings with customers
"""
    p = tmp_path_factory.mktemp("config") / "rag_authors.yaml"
    p.write_text(content)
    return str(p)


@pytest.fixture
def client(rag_yaml_file):
    from fastapi.testclient import TestClient

    with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
        from app.main import app

        yield TestClient(app)


# ── Unit: data shape tests ────────────────────────────────────────────────────


class TestConceptQueryResultShape:
    def test_as_dict_contains_all_fields(self):
        from app.rag.concept_mode import ConceptQueryResult

        result = ConceptQueryResult(
            query="What makes a good business?",
            best_passages=[],
            critique="These views may undervalue growth.",
            evidence_sufficient=True,
            weak_evidence_note=None,
        )
        d = result.as_dict()
        assert d["query"] == "What makes a good business?"
        assert isinstance(d["best_passages"], list)
        assert d["critique"] == "These views may undervalue growth."
        assert d["evidence_sufficient"] is True
        assert d["weak_evidence_note"] is None

    def test_weak_evidence_note_when_no_evidence(self):
        from app.rag.concept_mode import ConceptQueryResult

        result = ConceptQueryResult(
            query="Obscure question",
            best_passages=[],
            critique=None,
            evidence_sufficient=False,
            weak_evidence_note="The author corpus does not contain passages strongly relevant to this question.",
        )
        d = result.as_dict()
        assert d["evidence_sufficient"] is False
        assert d["weak_evidence_note"] is not None
        assert "corpus" in d["weak_evidence_note"].lower()


# ── Unit: execute_concept_query routing ──────────────────────────────────────


class TestConceptQueryRouting:
    """Tests that exercise execute_concept_query with mocked dependencies."""

    def _make_mock_db(self):
        return MagicMock()

    def test_returns_concept_query_result_type(self):
        from app.rag.concept_mode import ConceptQueryResult, execute_concept_query

        with (
            patch("app.rag.concept_mode.select_authors", return_value=[]),
            patch("app.rag.concept_mode._author_entries", return_value=[]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
        ):
            result = execute_concept_query("What makes a good business?", self._make_mock_db())

        assert isinstance(result, ConceptQueryResult)

    def test_query_is_preserved(self):
        from app.rag.concept_mode import execute_concept_query

        query = "What makes a good business?"
        with (
            patch("app.rag.concept_mode.select_authors", return_value=[]),
            patch("app.rag.concept_mode._author_entries", return_value=[]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
        ):
            result = execute_concept_query(query, self._make_mock_db())

        assert result.query == query

    def test_select_authors_called_with_query(self):
        from app.rag.concept_mode import execute_concept_query

        with (
            patch("app.rag.concept_mode.select_authors", return_value=[]) as mock_select,
            patch("app.rag.concept_mode._author_entries", return_value=[]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
        ):
            db = self._make_mock_db()
            execute_concept_query("network effects", db)

        mock_select.assert_called_once()
        call_args = mock_select.call_args
        assert call_args[0][0] == "network effects"
        assert call_args[0][1] is db

    def test_no_evidence_sets_evidence_sufficient_false(self):
        from app.rag.concept_mode import execute_concept_query

        with (
            patch("app.rag.concept_mode.select_authors", return_value=[]),
            patch("app.rag.concept_mode._author_entries", return_value=[]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
        ):
            result = execute_concept_query("obscure topic with no corpus match", self._make_mock_db())

        assert result.evidence_sufficient is False
        assert result.weak_evidence_note is not None

    def test_no_evidence_weak_note_contains_corpus_mention(self):
        from app.rag.concept_mode import execute_concept_query

        with (
            patch("app.rag.concept_mode.select_authors", return_value=[]),
            patch("app.rag.concept_mode._author_entries", return_value=[]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
        ):
            result = execute_concept_query("no match query", self._make_mock_db())

        assert "corpus" in (result.weak_evidence_note or "").lower()

    def test_critique_none_when_no_evidence_and_no_authors(self):
        from app.rag.concept_mode import execute_concept_query

        with (
            patch("app.rag.concept_mode.select_authors", return_value=[]),
            patch("app.rag.concept_mode._author_entries", return_value=[]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
        ):
            result = execute_concept_query("no match", self._make_mock_db())

        assert result.critique is None


# ── Unit: critique shape ──────────────────────────────────────────────────────


class TestCritiqueShape:
    def test_critique_none_when_no_llm(self):
        """Critique requires LLM; without it, critique is None."""
        from app.rag.concept_mode import EvidenceChunk, execute_concept_query
        from app.rag.author_selection import SelectedAuthor

        mock_author = SelectedAuthor(
            author_id="buffett",
            name="Warren Buffett",
            score=3.5,
            domains=["investing"],
            expertise_tags=[],
            overall_weight=3.5,
            role_type="investor",
            match_reason=[],
        )
        mock_entry = {
            "author_id": "buffett",
            "name": "Warren Buffett",
            "score": 3.5,
            "domains": ["investing"],
            "expertise_tags": [],
            "match_reason": [],
            "worldview": "Focus on moat.",
            "key_maxims": [],
        }
        mock_chunk = EvidenceChunk(
            chunk_id="c1",
            author_id="buffett",
            author_name="Warren Buffett",
            text="Moat is the key to long-term returns.",
            similarity=0.88,
            metadata={},
        )

        with (
            patch("app.rag.concept_mode.select_authors", return_value=[mock_author]),
            patch("app.rag.concept_mode._author_entries", return_value=[mock_entry]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[MagicMock()]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[mock_chunk]),
            patch("app.rag.concept_mode.inference_available", return_value=False),
        ):
            result = execute_concept_query("What is a moat?", MagicMock())

        # Critique is None when LLM is unavailable
        assert result.critique is None

    def test_critique_generated_when_llm_available(self):
        from app.rag.concept_mode import EvidenceChunk, execute_concept_query
        from app.rag.author_selection import SelectedAuthor

        mock_author = SelectedAuthor(
            author_id="buffett",
            name="Warren Buffett",
            score=3.5,
            domains=["investing"],
            expertise_tags=[],
            overall_weight=3.5,
            role_type="investor",
            match_reason=[],
        )
        mock_entry = {
            "author_id": "buffett",
            "name": "Warren Buffett",
            "score": 3.5,
            "domains": ["investing"],
            "expertise_tags": [],
            "match_reason": [],
            "worldview": "Focus on moat.",
            "key_maxims": [],
        }
        mock_chunk = EvidenceChunk(
            chunk_id="c1",
            author_id="buffett",
            author_name="Warren Buffett",
            text="Moat is the key to long-term returns.",
            similarity=0.88,
            metadata={},
        )

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = (
            "The perspectives may underweight the role of execution."
        )

        with (
            patch.dict("os.environ", {"AI_SAGE_CRITIQUE_ENABLED": "1"}, clear=False),
            patch("app.rag.concept_mode.select_authors", return_value=[mock_author]),
            patch("app.rag.concept_mode._author_entries", return_value=[mock_entry]),
            patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[MagicMock()]),
            patch("app.rag.concept_mode._enrich_chunks", return_value=[mock_chunk]),
            patch("app.rag.concept_mode.inference_available", return_value=True),
            patch("app.rag.concept_mode.create_inference_client", return_value=mock_client),
            patch("app.rag.concept_mode.inference_model", return_value="gpt-4o-mini"),
        ):
            result = execute_concept_query("What is a moat?", MagicMock())

        assert result.critique is not None
        assert isinstance(result.critique, str)
        assert len(result.critique) > 0


# ── API endpoint tests ────────────────────────────────────────────────────────


class TestAISageConceptAPI:
    """API-level tests for /ai-sage/query endpoint via TestClient."""

    def _ensure_authors(self, client, rag_yaml_file):
        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_file}):
            client.post("/rag/authors/sync-config")

    def test_endpoint_returns_200(self, client, rag_yaml_file):
        self._ensure_authors(client, rag_yaml_file)
        resp = client.post(
            "/ai-sage/query",
            json={"query": "What makes a good business?"},
        )
        assert resp.status_code == 200

    def test_response_contains_required_fields(self, client, rag_yaml_file):
        self._ensure_authors(client, rag_yaml_file)
        resp = client.post(
            "/ai-sage/query",
            json={"query": "What makes a good business?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        required_fields = [
            "query",
            "best_passages",
            "critique",
            "evidence_sufficient",
            "weak_evidence_note",
        ]
        for field in required_fields:
            assert field in body, f"Missing field: {field}"

    def test_query_echoed_in_response(self, client, rag_yaml_file):
        self._ensure_authors(client, rag_yaml_file)
        resp = client.post(
            "/ai-sage/query",
            json={"query": "How should I think about network effects?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["query"] == "How should I think about network effects?"

    def test_best_passages_is_list(self, client, rag_yaml_file):
        self._ensure_authors(client, rag_yaml_file)
        resp = client.post(
            "/ai-sage/query",
            json={"query": "What makes a good business?"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["best_passages"], list)

    def test_evidence_sufficient_is_bool(self, client, rag_yaml_file):
        self._ensure_authors(client, rag_yaml_file)
        resp = client.post(
            "/ai-sage/query",
            json={"query": "What makes a good business?"},
        )
        assert resp.status_code == 200
        assert isinstance(resp.json()["evidence_sufficient"], bool)

    def test_empty_query_rejected(self, client, rag_yaml_file):
        resp = client.post("/ai-sage/query", json={"query": ""})
        assert resp.status_code == 422

    def test_requires_auth_when_bypass_disabled(self, client):
        with patch.dict(os.environ, {"AUTH_BYPASS_USER_ID": ""}, clear=False):
            resp = client.post(
                "/ai-sage/query",
                json={"query": "What makes a good business?"},
            )
        assert resp.status_code in (401, 403)

    def test_weak_evidence_note_set_when_no_corpus(self, client, rag_yaml_file):
        """When no corpus chunks match, weak_evidence_note should be non-null."""
        self._ensure_authors(client, rag_yaml_file)
        resp = client.post(
            "/ai-sage/query",
            json={"query": "What makes a good business?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Without real pgvector data, evidence_sufficient should be False
        # and weak_evidence_note should be set
        if not body["evidence_sufficient"]:
            assert body["weak_evidence_note"] is not None

    def test_no_exposed_internal_mode_fields(self, client, rag_yaml_file):
        """Response must not expose internal routing jargon (retrieve, ask, etc.)."""
        self._ensure_authors(client, rag_yaml_file)
        resp = client.post(
            "/ai-sage/query",
            json={"query": "What makes a good business?"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # "mode" is a valid routing field (concept vs thesis) — allowed in response
        # Internal LLM jargon and raw retrieval fields must not appear
        for forbidden in ["missing_information", "answer"]:
            assert forbidden not in body or body[forbidden] in (None, [], ""), (
                f"Internal field '{forbidden}' leaked into response"
            )
        # Concept mode should use "concept" not implementation-level routing terms
        assert body.get("mode") in ("concept", None), (
            f"Unexpected mode value '{body.get('mode')}' in concept response"
        )
