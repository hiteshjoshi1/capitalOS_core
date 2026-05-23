from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from app.rag.eval.cli import cli
from app.rag.eval.runner import (
    EvalReport,
    GoldenQuery,
    compare_reports,
    default_reranker_experiments,
    diagnose_jina_failure_mode,
    parse_eval_config,
    recommend_reranker_rollout,
    run_evaluation,
)


def test_parse_eval_config_supports_weighting_and_mode_tokens():
    config = parse_eval_config("hybrid+metadata_weighting_on+retrieval_hardening_on")
    assert config.retrieval_mode == "hybrid"
    assert config.weighting_enabled is True
    assert config.hardening_enabled is True

    config = parse_eval_config("dense_only+weighting_off")
    assert config.retrieval_mode == "dense_only"
    assert config.weighting_enabled is False
    assert config.hardening_enabled is None


def test_compare_reports_includes_no_regression_bar():
    report_a = MagicMock(
        mean_ndcg_at_10=0.8,
        mean_recall_at_10=0.7,
        mean_precision_at_10=0.6,
        mean_mrr=0.5,
        per_query=[],
    )
    report_a.as_dict.return_value = {"config_label": "a"}
    report_b = MagicMock(
        mean_ndcg_at_10=0.79,
        mean_recall_at_10=0.69,
        mean_precision_at_10=0.61,
        mean_mrr=0.52,
        per_query=[],
    )
    report_b.as_dict.return_value = {"config_label": "b"}

    comparison = compare_reports(report_a, report_b)
    assert comparison["no_regression_bar"]["mean_ndcg@10_min_delta"] == -0.02
    assert comparison["no_regression_bar"]["mean_recall@10_min_delta"] == -0.02
    assert comparison["passes_no_regression_bar"] is True


def test_default_reranker_experiments_include_available_variants():
    with (
        patch("app.rag.reranker.reranker_available") as mock_available,
        patch("app.rag.reranker.reranker_model") as mock_model,
    ):
        mock_available.side_effect = lambda provider=None: provider in {"jina", "local"}
        mock_model.side_effect = lambda provider=None, model=None: f"{provider}-model"
        experiments = default_reranker_experiments()

    assert [experiment.label for experiment in experiments] == [
        "baseline/heuristic",
        "jina/raw",
        "jina/compact_context",
        "jina/expanded_context",
        "local/raw",
        "local/compact_context",
        "local/expanded_context",
    ]


def test_default_reranker_experiments_can_limit_provider_and_input_mode():
    with (
        patch("app.rag.reranker.reranker_available") as mock_available,
        patch("app.rag.reranker.reranker_model") as mock_model,
    ):
        mock_available.side_effect = lambda provider=None: provider in {"jina", "local"}
        mock_model.side_effect = lambda provider=None, model=None: f"{provider}-model"
        experiments = default_reranker_experiments(providers=["jina"], input_modes=["raw"])

    assert [experiment.label for experiment in experiments] == [
        "baseline/heuristic",
        "jina/raw",
    ]


def test_compare_reports_fails_per_query_gate_when_labeled_query_misses_targets():
    report_a = EvalReport(
        config_label="baseline",
        num_queries=1,
        mean_ndcg_at_5=0.1,
        mean_ndcg_at_10=0.1,
        mean_recall_at_5=0.1,
        mean_recall_at_10=0.2,
        mean_precision_at_5=0.1,
        mean_precision_at_10=0.1,
        mean_mrr=0.1,
        per_query=[
            {
                "query": "What are Charlie Munger's main mental models?",
                "ndcg@10": 0.1,
                "recall@10": 0.2,
                "high_relevance_hits@5": 1,
                "relevant_hits@10": 3,
                "golden_relevant_count": 14,
                "golden_high_relevance_count": 3,
            }
        ],
    )
    report_b = EvalReport(
        config_label="candidate",
        num_queries=1,
        mean_ndcg_at_5=0.1,
        mean_ndcg_at_10=0.1,
        mean_recall_at_5=0.1,
        mean_recall_at_10=0.2,
        mean_precision_at_5=0.1,
        mean_precision_at_10=0.1,
        mean_mrr=0.1,
        per_query=[
            {
                "query": "What are Charlie Munger's main mental models?",
                "ndcg@10": 0.1,
                "recall@10": 0.2,
                "high_relevance_hits@5": 0,
                "relevant_hits@10": 1,
                "golden_relevant_count": 14,
                "golden_high_relevance_count": 3,
            }
        ],
    )

    comparison = compare_reports(report_a, report_b)

    assert comparison["passes_per_query_gates"] is False
    assert comparison["passes_no_regression_bar"] is False
    assert comparison["per_query_gates"][0]["passed"] is False


def test_compare_reports_passes_per_query_gate_when_targets_are_hit():
    report_a = EvalReport(
        config_label="baseline",
        num_queries=1,
        mean_ndcg_at_5=0.1,
        mean_ndcg_at_10=0.1,
        mean_recall_at_5=0.1,
        mean_recall_at_10=0.2,
        mean_precision_at_5=0.1,
        mean_precision_at_10=0.1,
        mean_mrr=0.1,
        per_query=[
            {
                "query": "What are Charlie Munger's main mental models?",
                "ndcg@10": 0.1,
                "recall@10": 0.2,
                "high_relevance_hits@5": 1,
                "relevant_hits@10": 3,
                "golden_relevant_count": 14,
                "golden_high_relevance_count": 3,
            }
        ],
    )
    report_b = EvalReport(
        config_label="candidate",
        num_queries=1,
        mean_ndcg_at_5=0.2,
        mean_ndcg_at_10=0.2,
        mean_recall_at_5=0.2,
        mean_recall_at_10=0.3,
        mean_precision_at_5=0.2,
        mean_precision_at_10=0.2,
        mean_mrr=0.2,
        per_query=[
            {
                "query": "What are Charlie Munger's main mental models?",
                "ndcg@10": 0.2,
                "recall@10": 0.3,
                "high_relevance_hits@5": 1,
                "relevant_hits@10": 3,
                "golden_relevant_count": 14,
                "golden_high_relevance_count": 3,
            }
        ],
    )

    comparison = compare_reports(report_a, report_b)

    assert comparison["passes_per_query_gates"] is True
    assert comparison["passes_no_regression_bar"] is True


def test_recommend_reranker_rollout_keeps_default_disabled_without_clear_win():
    baseline = EvalReport(
        config_label="baseline/heuristic",
        num_queries=1,
        mean_ndcg_at_5=0.5,
        mean_ndcg_at_10=0.5,
        mean_recall_at_5=0.5,
        mean_recall_at_10=0.5,
        mean_precision_at_5=0.5,
        mean_precision_at_10=0.5,
        mean_mrr=0.5,
        per_query=[],
    )
    candidate = EvalReport(
        config_label="jina/expanded_context",
        num_queries=1,
        mean_ndcg_at_5=0.51,
        mean_ndcg_at_10=0.51,
        mean_recall_at_5=0.51,
        mean_recall_at_10=0.51,
        mean_precision_at_5=0.51,
        mean_precision_at_10=0.51,
        mean_mrr=0.52,
        per_query=[],
    )

    recommendation = recommend_reranker_rollout(baseline, [candidate])

    assert recommendation["recommended_default_provider"] == "none"
    assert recommendation["keep_default_disabled"] is True


def test_recommend_reranker_rollout_selects_clear_winner():
    baseline = EvalReport(
        config_label="baseline/heuristic",
        num_queries=1,
        mean_ndcg_at_5=0.4,
        mean_ndcg_at_10=0.4,
        mean_recall_at_5=0.4,
        mean_recall_at_10=0.4,
        mean_precision_at_5=0.4,
        mean_precision_at_10=0.4,
        mean_mrr=0.4,
        per_query=[],
    )
    candidate = EvalReport(
        config_label="local/expanded_context",
        num_queries=1,
        mean_ndcg_at_5=0.45,
        mean_ndcg_at_10=0.44,
        mean_recall_at_5=0.45,
        mean_recall_at_10=0.43,
        mean_precision_at_5=0.45,
        mean_precision_at_10=0.44,
        mean_mrr=0.46,
        per_query=[],
    )

    recommendation = recommend_reranker_rollout(baseline, [candidate])

    assert recommendation["recommended_default_label"] == "local/expanded_context"
    assert recommendation["keep_default_disabled"] is False


def test_compare_reports_fails_candidate_recall_gate_when_top50_misses_targets():
    report_a = EvalReport(
        config_label="baseline",
        num_queries=1,
        mean_ndcg_at_5=0.1,
        mean_ndcg_at_10=0.1,
        mean_recall_at_5=0.1,
        mean_recall_at_10=0.2,
        mean_precision_at_5=0.1,
        mean_precision_at_10=0.1,
        mean_mrr=0.1,
        per_query=[
            {
                "query": "What are Charlie Munger's main mental models?",
                "ndcg@10": 0.1,
                "recall@10": 0.2,
                "recall@50": 0.5,
                "retrieved_count": 50,
                "high_relevance_hits@5": 1,
                "relevant_hits@10": 3,
                "high_relevance_hits@50": 3,
                "relevant_hits@50": 8,
                "golden_relevant_count": 14,
                "golden_high_relevance_count": 4,
            }
        ],
    )
    report_b = EvalReport(
        config_label="candidate",
        num_queries=1,
        mean_ndcg_at_5=0.2,
        mean_ndcg_at_10=0.2,
        mean_recall_at_5=0.2,
        mean_recall_at_10=0.3,
        mean_precision_at_5=0.2,
        mean_precision_at_10=0.2,
        mean_mrr=0.2,
        per_query=[
            {
                "query": "What are Charlie Munger's main mental models?",
                "ndcg@10": 0.2,
                "recall@10": 0.3,
                "recall@50": 0.35,
                "retrieved_count": 50,
                "high_relevance_hits@5": 1,
                "relevant_hits@10": 3,
                "high_relevance_hits@50": 1,
                "relevant_hits@50": 5,
                "golden_relevant_count": 14,
                "golden_high_relevance_count": 4,
            }
        ],
    )

    comparison = compare_reports(report_a, report_b)

    assert comparison["passes_per_query_gates"] is False
    assert comparison["passes_no_regression_bar"] is False
    assert any("high_relevance_hits@50" in failure for failure in comparison["per_query_gates"][0]["failures"])


def test_diagnose_jina_failure_mode_flags_raw_regression_and_pool_gaps():
    baseline = EvalReport(
        config_label="baseline/heuristic",
        num_queries=1,
        mean_ndcg_at_5=0.5,
        mean_ndcg_at_10=0.5,
        mean_recall_at_5=0.5,
        mean_recall_at_10=0.5,
        mean_precision_at_5=0.5,
        mean_precision_at_10=0.5,
        mean_mrr=0.5,
        per_query=[{"query": "moat", "ndcg@10": 0.5, "recall@10": 0.5}],
    )
    jina_raw = EvalReport(
        config_label="jina/raw",
        num_queries=1,
        mean_ndcg_at_5=0.3,
        mean_ndcg_at_10=0.3,
        mean_recall_at_5=0.3,
        mean_recall_at_10=0.3,
        mean_precision_at_5=0.3,
        mean_precision_at_10=0.3,
        mean_mrr=0.3,
        per_query=[
            {
                "query": "moat",
                "ndcg@10": 0.3,
                "recall@10": 0.3,
                "candidate_pool_recall": 0.25,
                "top_results": [],
            }
        ],
    )
    jina_expanded = EvalReport(
        config_label="jina/expanded_context",
        num_queries=1,
        mean_ndcg_at_5=0.35,
        mean_ndcg_at_10=0.35,
        mean_recall_at_5=0.35,
        mean_recall_at_10=0.35,
        mean_precision_at_5=0.35,
        mean_precision_at_10=0.35,
        mean_mrr=0.35,
        per_query=[{"query": "moat", "ndcg@10": 0.35, "recall@10": 0.35}],
    )
    local_report = EvalReport(
        config_label="local/expanded_context",
        num_queries=1,
        mean_ndcg_at_5=0.55,
        mean_ndcg_at_10=0.55,
        mean_recall_at_5=0.55,
        mean_recall_at_10=0.55,
        mean_precision_at_5=0.55,
        mean_precision_at_10=0.55,
        mean_mrr=0.55,
        per_query=[{"query": "moat", "ndcg@10": 0.55, "recall@10": 0.55}],
    )

    diagnosis = diagnose_jina_failure_mode(
        baseline,
        {
            "baseline/heuristic": baseline,
            "jina/raw": jina_raw,
            "jina/expanded_context": jina_expanded,
            "local/expanded_context": local_report,
        },
        [{"query": "moat", "candidate_pool_recall": 0.25}],
    )

    assert "Raw-anchor Jina reranking regressed" in diagnosis["summary"]
    assert any("Expanded local context improved Jina" in finding for finding in diagnosis["findings"])


def test_run_evaluation_uses_hybrid_with_config_overrides():
    db = MagicMock()
    with (
        patch("app.rag.eval.runner.load_golden_queries") as mock_load,
        patch("app.rag.retrieval.retrieve_hybrid") as mock_retrieve_hybrid,
    ):
        mock_load.return_value = [GoldenQuery(query_text="moat", golden={"c1": 3})]
        mock_retrieve_hybrid.return_value = [MagicMock(chunk_id="c1")]

        report = run_evaluation(db, config_label="sparse_only+metadata_weighting_on", top_k=7)

    assert report.num_queries == 1
    _, kwargs = mock_retrieve_hybrid.call_args
    assert kwargs["top_k"] == 7
    assert kwargs["retrieval_mode"] == "sparse_only"
    assert kwargs["weighting_enabled"] is True
    assert kwargs["hardening_enabled"] is None


def test_run_evaluation_passes_hardening_override():
    db = MagicMock()
    with (
        patch("app.rag.eval.runner.load_golden_queries") as mock_load,
        patch("app.rag.retrieval.retrieve_hybrid") as mock_retrieve_hybrid,
    ):
        mock_load.return_value = [GoldenQuery(query_text="moat", golden={"c1": 3})]
        mock_retrieve_hybrid.return_value = [MagicMock(chunk_id="c1")]

        run_evaluation(db, config_label="hybrid+retrieval_hardening_on", top_k=5)

    _, kwargs = mock_retrieve_hybrid.call_args
    assert kwargs["hardening_enabled"] is True


def test_run_evaluation_passes_source_type_scope():
    db = MagicMock()
    with (
        patch("app.rag.eval.runner.load_golden_queries") as mock_load,
        patch("app.rag.retrieval.retrieve_hybrid") as mock_retrieve_hybrid,
    ):
        mock_load.return_value = [GoldenQuery(query_text="moat", golden={"c1": 3})]
        mock_retrieve_hybrid.return_value = [MagicMock(chunk_id="c1")]

        report = run_evaluation(db, config_label="current", top_k=5, source_type="pdf")

    mock_load.assert_called_once_with(db, source_type="pdf")
    assert report.scope == {"source_type": "pdf"}


def test_eval_cli_gate_fails_on_pdf_regression(tmp_path):
    baseline = {
        "config_label": "pdf-baseline",
        "num_queries": 2,
        "mean_ndcg@5": 0.8,
        "mean_ndcg@10": 0.8,
        "mean_recall@5": 0.7,
        "mean_recall@10": 0.7,
        "mean_precision@5": 0.6,
        "mean_precision@10": 0.6,
        "mean_mrr": 0.5,
        "scope": {"source_type": "pdf"},
        "per_query": [],
    }
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))

    current_report = MagicMock(
        num_queries=2,
        scope={"source_type": "pdf"},
    )
    current_report.as_dict.return_value = {"config_label": "pdf-candidate"}
    current_report.mean_ndcg_at_10 = 0.74
    current_report.mean_recall_at_10 = 0.65
    current_report.mean_precision_at_10 = 0.6
    current_report.mean_mrr = 0.5

    runner = CliRunner()
    with patch("app.rag.eval.cli.SessionLocal") as mock_session_local, patch(
        "app.rag.eval.cli.run_evaluation",
        return_value=current_report,
    ):
        mock_session_local.return_value = MagicMock(close=MagicMock())
        result = runner.invoke(
            cli,
            [
                "gate",
                "--baseline-report",
                str(baseline_path),
                "--label",
                "pdf-candidate",
                "--source-type",
                "pdf",
            ],
        )

    assert result.exit_code == 1
    assert '"passes_no_regression_bar": false' in result.output


def test_eval_cli_diagnose_reranker_writes_report(tmp_path):
    runner = CliRunner()
    output_path = tmp_path / "reranker-report.json"

    with patch("app.rag.eval.cli.SessionLocal") as mock_session_local, patch(
        "app.rag.eval.cli.run_reranker_diagnosis",
        return_value={"rollout_policy": {"recommended_default_provider": "none"}},
    ) as mock_diagnosis:
        mock_session_local.return_value = MagicMock(close=MagicMock())
        result = runner.invoke(
            cli,
            [
                "diagnose-reranker",
                "--provider",
                "jina",
                "--input-mode",
                "raw",
                "--query-contains",
                "Munger",
                "--cache-path",
                str(tmp_path / "cache.json"),
                "--output",
                str(output_path),
            ],
        )

    assert result.exit_code == 0
    _, kwargs = mock_diagnosis.call_args
    assert kwargs["providers"] == ["jina"]
    assert kwargs["input_modes"] == ["raw"]
    assert kwargs["query_contains"] == "Munger"
    assert output_path.exists()
    assert '"recommended_default_provider": "none"' in output_path.read_text()


def test_eval_cli_seed_replace_deletes_existing_rows(tmp_path):
    fixture_path = tmp_path / "golden.yaml"
    fixture_path.write_text("golden_queries: []\n")
    query = MagicMock()
    query.delete.return_value = 7
    db = MagicMock()
    db.query.return_value = query

    runner = CliRunner()
    with patch("app.db.session.SessionLocal", return_value=db):
        result = runner.invoke(
            cli,
            [
                "seed",
                "--replace",
                "--file",
                str(fixture_path),
            ],
        )

    assert result.exit_code == 0
    query.delete.assert_called_once()
    db.commit.assert_called_once()
    assert "Deleted 7 existing golden pairs before seeding." in result.output
