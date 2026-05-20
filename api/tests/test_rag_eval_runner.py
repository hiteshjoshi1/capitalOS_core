from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from app.rag.eval.cli import cli
from app.rag.eval.runner import EvalReport, GoldenQuery, compare_reports, parse_eval_config, run_evaluation


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
