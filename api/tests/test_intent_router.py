"""
Tests for AI Sage intent routing (Issue 137).

Coverage:
  - Author intent extraction (text-based parser)
  - Date/source constraint extraction (text-based parser)
  - Single-author query type classification
  - Multi-author query type classification
  - Open query type classification
  - Sub-query decomposition
  - Single-author enforcement in execute_concept_query
  - Routing model config independence from INFERENCE_LLM_MODEL
  - parse_intent returns text-fallback when routing LLM unavailable
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:////tmp/capitalos_intent_test.db")
os.environ["RAG_EMBEDDING_MOCK"] = "1"
os.environ.setdefault("AUTH_BYPASS_USER_ID", "1")


# ── Text-based parser unit tests ──────────────────────────────────────────────


class TestParseIntentFromText:
    """Unit tests for the pure-Python text parser."""

    def _parse(self, query: str):
        from app.rag.intent_router import parse_intent_from_text
        return parse_intent_from_text(query)

    # ── Author extraction ──────────────────────────────────────────────────

    def test_single_author_buffett(self):
        intent = self._parse("What does Warren Buffett say about circle of competence?")
        assert "warren_buffett" in intent.author_ids
        assert intent.query_type == "single_author"

    def test_single_author_buffett_shortname(self):
        intent = self._parse("What are Buffett's views on moat?")
        assert "warren_buffett" in intent.author_ids
        assert intent.query_type == "single_author"

    def test_multi_author_buffett_and_munger(self):
        intent = self._parse("Compare Buffett and Munger on patience.")
        assert "warren_buffett" in intent.author_ids
        assert "charlie_munger" in intent.author_ids
        assert intent.query_type == "multi_author"

    def test_open_query_no_author(self):
        intent = self._parse("What is a good framework for valuing businesses?")
        assert intent.author_ids == []
        assert intent.query_type == "open"

    def test_author_ids_are_unique(self):
        # Mentioning "Buffett" and "Warren Buffett" should yield one entry
        intent = self._parse("Buffett and Warren Buffett both emphasise moat.")
        assert intent.author_ids.count("warren_buffett") == 1

    def test_nick_sleep_detected(self):
        intent = self._parse("What does Nick Sleep think about scale economies?")
        assert "nick_sleep" in intent.author_ids

    # ── Source type extraction ─────────────────────────────────────────────

    def test_source_type_letter_not_hard_mapped(self):
        intent = self._parse("What does Buffett say in his letters about patience?")
        assert intent.source_types == []

    def test_source_type_annual_report(self):
        intent = self._parse("What does Buffett discuss in annual reports?")
        assert "pdf" in intent.source_types

    def test_source_type_shareholder_letter_not_hard_mapped(self):
        intent = self._parse("Buffett shareholder letter advice on investing.")
        assert intent.source_types == []

    def test_no_source_type_for_generic_query(self):
        intent = self._parse("What is a good business?")
        assert intent.source_types == []

    # ── Date extraction ────────────────────────────────────────────────────

    def test_date_range(self):
        intent = self._parse("Buffett letters from 2010 to 2020 on capital allocation.")
        assert intent.date_from == "2010"
        assert intent.date_to == "2020"

    def test_date_from_only(self):
        intent = self._parse("Buffett writing since 2015.")
        assert intent.date_from == "2015"
        assert intent.date_to is None

    def test_date_to_only(self):
        intent = self._parse("Buffett writing before 2010.")
        assert intent.date_to == "2010"
        assert intent.date_from is None

    def test_single_year_in(self):
        intent = self._parse("What did Buffett write in 2008?")
        assert intent.date_from == "2008"
        assert intent.date_to == "2008"

    def test_no_date_for_generic_query(self):
        intent = self._parse("What is competitive advantage?")
        assert intent.date_from is None
        assert intent.date_to is None

    # ── Output shape extraction ────────────────────────────────────────────

    def test_output_shape_aphorisms(self):
        intent = self._parse("Give me Buffett's best aphorisms on money.")
        assert intent.output_shape == "aphorisms"

    def test_output_shape_life_advice(self):
        intent = self._parse("Buffett life advice for young investors.")
        assert intent.output_shape == "life advice"

    def test_no_output_shape_generic(self):
        intent = self._parse("How does Buffett evaluate management?")
        assert intent.output_shape is None

    # ── Sub-query decomposition ────────────────────────────────────────────

    def test_multi_question_mark_decomposition(self):
        intent = self._parse("What does Buffett say about moat? What does he say about debt?")
        assert len(intent.sub_queries) >= 2

    def test_and_also_decomposition(self):
        intent = self._parse(
            "What does Buffett say about patience and also what does he say about management?"
        )
        assert len(intent.sub_queries) >= 2

    def test_single_sentence_no_decomposition(self):
        intent = self._parse("What is a moat?")
        assert intent.sub_queries == []


# ── parse_intent fallback test ─────────────────────────────────────────────────


class TestParseIntentFallback:
    def test_falls_back_to_text_parser_when_llm_unavailable(self):
        """When routing LLM is not available, parse_intent must use text parser."""
        from app.rag.intent_router import parse_intent

        with patch("app.rag.intent_router._parse_intent_with_llm", return_value=None):
            intent = parse_intent("What does Buffett say about moat?")
        assert "warren_buffett" in intent.author_ids
        assert intent.query_type == "single_author"


# ── Routing model config independence ─────────────────────────────────────────


class TestRoutingModelConfig:
    def test_routing_model_defaults_to_qwen_on_openrouter(self):
        from app.rag.inference import routing_model

        with patch.dict(
            os.environ,
            {"INFERENCE_LLM_PROVIDER": "openrouter"},
            clear=False,
        ):
            # Remove ROUTING_LLM_MODEL if set, to test the default
            env = {k: v for k, v in os.environ.items() if k != "ROUTING_LLM_MODEL"}
            with patch.dict(os.environ, env, clear=True):
                model = routing_model()
        assert "qwen" in model.lower()

    def test_routing_model_overridable_independently(self):
        from app.rag.inference import routing_model, inference_model

        with patch.dict(
            os.environ,
            {
                "INFERENCE_LLM_MODEL": "openai/gpt-4o",
                "ROUTING_LLM_MODEL": "google/gemini-flash-1.5",
                "INFERENCE_LLM_PROVIDER": "openrouter",
            },
        ):
            assert routing_model() == "google/gemini-flash-1.5"
            assert inference_model() == "openai/gpt-4o"

    def test_routing_model_falls_back_to_inference_model_on_non_openrouter(self):
        from app.rag.inference import routing_model

        with patch.dict(
            os.environ,
            {"INFERENCE_LLM_PROVIDER": "openai", "INFERENCE_LLM_MODEL": "gpt-4o-mini"},
            clear=False,
        ):
            env = {k: v for k, v in os.environ.items() if k != "ROUTING_LLM_MODEL"}
            with patch.dict(os.environ, env, clear=True):
                model = routing_model()
        assert model == "gpt-4o-mini"


# ── execute_concept_query: single-author enforcement ──────────────────────────


@pytest.fixture(scope="module")
def rag_yaml_for_intent(tmp_path_factory):
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
      focus: [durable competitive advantage]
      avoid: [macro speculation]
      biases: []

  - id: nick_sleep
    name: Nick Sleep
    enabled: true
    domains: [investing, business_quality]
    expertise_tags: [scale_economies_shared, long_term]
    overall_weight: 3.5
    role_type: investor
    reasoning_lens:
      focus: [scale economies shared]
      avoid: [short-term focus]
      biases: []
"""
    p = tmp_path_factory.mktemp("cfg_intent") / "rag_authors.yaml"
    p.write_text(content)
    return str(p)


class TestConceptModeSingleAuthorEnforcement:
    """Verify that a Buffett-only question restricts to Buffett-only retrieval."""

    def test_single_author_query_restricts_select_authors(self, rag_yaml_for_intent):
        """select_authors should be called with author_id=warren_buffett, top_k=1."""
        import app.rag.concept_mode as cm

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_for_intent}):
            mock_db = MagicMock()

            # Make intent return single_author=warren_buffett
            from app.rag.intent_router import QueryIntent
            single_author_intent = QueryIntent(
                author_ids=["warren_buffett"],
                author_names=["Warren Buffett"],
                query_type="single_author",
            )

            with (
                patch("app.rag.concept_mode.parse_intent", return_value=single_author_intent),
                patch("app.rag.concept_mode.select_authors", return_value=[]) as mock_select,
                patch("app.rag.concept_mode._author_entries", return_value=[]),
                patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
                patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            ):
                cm.execute_concept_query(
                    "What does Buffett say about moat in his letters?",
                    mock_db,
                )
                # The first call must be the constrained single-author call
                first_call = mock_select.call_args_list[0]
                assert first_call.kwargs.get("author_id") == "warren_buffett"
                assert first_call.kwargs.get("top_k") == 1

    def test_open_query_does_not_constrain_authors(self, rag_yaml_for_intent):
        """An open query should call select_authors without an author_id constraint."""
        import app.rag.concept_mode as cm

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_for_intent}):
            mock_db = MagicMock()

            from app.rag.intent_router import QueryIntent
            open_intent = QueryIntent(query_type="open")

            with (
                patch("app.rag.concept_mode.parse_intent", return_value=open_intent),
                patch("app.rag.concept_mode.select_authors", return_value=[]) as mock_select,
                patch("app.rag.concept_mode._author_entries", return_value=[]),
                patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
                patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            ):
                cm.execute_concept_query("What is a good business?", mock_db)
                first_call = mock_select.call_args_list[0]
                # No author_id constraint for open queries
                assert first_call.kwargs.get("author_id") is None

    def test_source_type_constraint_passed_to_retrieval(self, rag_yaml_for_intent):
        """Source-type constraints are relaxed if they produce zero retrieval results."""
        import app.rag.concept_mode as cm

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_for_intent}):
            mock_db = MagicMock()

            from app.rag.intent_router import QueryIntent
            from app.rag.author_selection import SelectedAuthor
            letter_intent = QueryIntent(
                author_ids=["warren_buffett"],
                author_names=["Warren Buffett"],
                source_types=["text"],
                query_type="single_author",
            )
            fake_selected = [
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
            fake_evidence = [
                MagicMock(author_id="warren_buffett", author_name="Warren Buffett", text="A", as_dict=lambda: {}),
                MagicMock(author_id="warren_buffett", author_name="Warren Buffett", text="B", as_dict=lambda: {}),
            ]

            with (
                patch("app.rag.concept_mode.parse_intent", return_value=letter_intent),
                patch("app.rag.concept_mode.select_authors", return_value=fake_selected),
                patch("app.rag.concept_mode._author_entries", return_value=[{"author_id": "warren_buffett", "name": "Warren Buffett"}]),
                patch("app.rag.concept_mode._enrich_chunks", return_value=fake_evidence),
                patch(
                    "app.rag.concept_mode.retrieve_similar_chunks",
                    side_effect=[[], [MagicMock(chunk_id="c1", cosine_distance=0.1)]],
                ) as mock_retr,
            ):
                result = cm.execute_concept_query(
                    "What does Buffett say in his letters?",
                    mock_db,
                )
                first_call = mock_retr.call_args_list[0].kwargs
                second_call = mock_retr.call_args_list[1].kwargs
                assert first_call.get("source_type") == "text"
                assert second_call.get("source_type") is None
                assert result.evidence_sufficient is True
                assert result.weak_evidence_note is None

    def test_date_constraints_passed_to_retrieval(self, rag_yaml_for_intent):
        """Date constraints are relaxed if the corpus has no matching year metadata."""
        import app.rag.concept_mode as cm

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_for_intent}):
            mock_db = MagicMock()

            from app.rag.intent_router import QueryIntent
            from app.rag.author_selection import SelectedAuthor
            dated_intent = QueryIntent(
                author_ids=["warren_buffett"],
                author_names=["Warren Buffett"],
                date_from="2010",
                date_to="2020",
                query_type="single_author",
            )
            fake_selected = [
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
            fake_evidence = [
                MagicMock(author_id="warren_buffett", author_name="Warren Buffett", text="A", as_dict=lambda: {}),
                MagicMock(author_id="warren_buffett", author_name="Warren Buffett", text="B", as_dict=lambda: {}),
            ]

            with (
                patch("app.rag.concept_mode.parse_intent", return_value=dated_intent),
                patch("app.rag.concept_mode.select_authors", return_value=fake_selected),
                patch("app.rag.concept_mode._author_entries", return_value=[{"author_id": "warren_buffett", "name": "Warren Buffett"}]),
                patch("app.rag.concept_mode._enrich_chunks", return_value=fake_evidence),
                patch(
                    "app.rag.concept_mode.retrieve_similar_chunks",
                    side_effect=[[], [MagicMock(chunk_id="c1", cosine_distance=0.1)]],
                ) as mock_retr,
            ):
                result = cm.execute_concept_query(
                    "Buffett letters from 2010 to 2020.",
                    mock_db,
                )
                first_call = mock_retr.call_args_list[0].kwargs
                second_call = mock_retr.call_args_list[1].kwargs
                assert first_call.get("year_from") == 2010
                assert first_call.get("year_to") == 2020
                assert second_call.get("year_from") is None
                assert second_call.get("year_to") is None
                assert result.evidence_sufficient is True
                assert result.weak_evidence_note is None

    def test_combined_source_and_date_constraints_fall_back_to_unfiltered(self, rag_yaml_for_intent):
        """If both source and date constraints fail, retrieval must eventually fall back to unfiltered corpus search."""
        import app.rag.concept_mode as cm

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_for_intent}):
            mock_db = MagicMock()

            from app.rag.intent_router import QueryIntent
            from app.rag.author_selection import SelectedAuthor

            constrained_intent = QueryIntent(
                author_ids=["warren_buffett"],
                author_names=["Warren Buffett"],
                source_types=["text"],
                date_from="2020",
                date_to="2025",
                query_type="single_author",
            )
            fake_selected = [
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
            fake_evidence = [
                MagicMock(author_id="warren_buffett", author_name="Warren Buffett", text="A", as_dict=lambda: {}),
                MagicMock(author_id="warren_buffett", author_name="Warren Buffett", text="B", as_dict=lambda: {}),
            ]

            with (
                patch("app.rag.concept_mode.parse_intent", return_value=constrained_intent),
                patch("app.rag.concept_mode.select_authors", return_value=fake_selected),
                patch("app.rag.concept_mode._author_entries", return_value=[{"author_id": "warren_buffett", "name": "Warren Buffett"}]),
                patch("app.rag.concept_mode._enrich_chunks", return_value=fake_evidence),
                patch(
                    "app.rag.concept_mode.retrieve_similar_chunks",
                    side_effect=[
                        [],
                        [],
                        [],
                        [MagicMock(chunk_id="c1", cosine_distance=0.1)],
                    ],
                ) as mock_retr,
            ):
                result = cm.execute_concept_query(
                    "What does Buffett say in his letters from 2020 to 2025?",
                    mock_db,
                )

                assert mock_retr.call_count == 4
                assert mock_retr.call_args_list[0].kwargs["source_type"] == "text"
                assert mock_retr.call_args_list[0].kwargs["year_from"] == 2020
                assert mock_retr.call_args_list[0].kwargs["year_to"] == 2025
                assert mock_retr.call_args_list[-1].kwargs["source_type"] is None
                assert mock_retr.call_args_list[-1].kwargs["year_from"] is None
                assert mock_retr.call_args_list[-1].kwargs["year_to"] is None
                assert result.evidence_sufficient is True
                assert result.weak_evidence_note is None

    def test_multi_part_query_uses_sub_queries(self, rag_yaml_for_intent):
        """Multi-part queries trigger per-sub-query retrieval calls."""
        import app.rag.concept_mode as cm

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_for_intent}):
            mock_db = MagicMock()

            from app.rag.intent_router import QueryIntent
            multi_intent = QueryIntent(
                query_type="open",
                sub_queries=[
                    "What does Buffett say about moat?",
                    "What does Buffett say about debt?",
                ],
            )

            with (
                patch("app.rag.concept_mode.parse_intent", return_value=multi_intent),
                patch("app.rag.concept_mode.select_authors", return_value=[]),
                patch("app.rag.concept_mode._author_entries", return_value=[]),
                patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
                patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]) as mock_retr,
            ):
                cm.execute_concept_query(
                    "What does Buffett say about moat? What does he say about debt?",
                    mock_db,
                )
                # Should have been called once per sub-query
                assert mock_retr.call_count == 2

    def test_intent_present_in_result(self, rag_yaml_for_intent):
        """ConceptQueryResult.intent should be a populated dict."""
        import app.rag.concept_mode as cm

        with patch.dict(os.environ, {"RAG_AUTHORS_CONFIG": rag_yaml_for_intent}):
            mock_db = MagicMock()

            with (
                patch("app.rag.concept_mode.select_authors", return_value=[]),
                patch("app.rag.concept_mode._author_entries", return_value=[]),
                patch("app.rag.concept_mode._enrich_chunks", return_value=[]),
                patch("app.rag.concept_mode.retrieve_similar_chunks", return_value=[]),
            ):
                result = cm.execute_concept_query(
                    "What does Buffett think about moat?",
                    mock_db,
                )

        assert result.intent is not None
        assert "query_type" in result.intent
        assert "author_ids" in result.intent
