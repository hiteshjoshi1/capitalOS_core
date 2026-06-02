from __future__ import annotations

import json

from app.rag.eval.drift import aggregate_deltas, changed_queries, drift_report, load_report, slice_deltas


def _report(config_label: str, ndcg10: float, recall10: float, precision10: float, mrr: float, per_query: list[dict]):
    return {
        "config_label": config_label,
        "num_queries": len(per_query),
        "mean_ndcg@10": ndcg10,
        "mean_recall@10": recall10,
        "mean_precision@10": precision10,
        "mean_mrr": mrr,
        "per_query": per_query,
    }


def test_load_report_accepts_eval_report_shape(tmp_path):
    report = _report(
        "old",
        0.5,
        0.4,
        0.3,
        0.7,
        [{"query": "What does Buffett say about circle of competence?", "ndcg@10": 0.8, "recall@10": 0.75, "mrr": 1.0, "retrieved_count": 4}],
    )
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))

    loaded = load_report(path)

    assert loaded["config_label"] == "old"
    assert loaded["num_queries"] == 1


def test_load_report_accepts_baseline_wrapped_shape(tmp_path):
    baseline = _report(
        "baseline/heuristic",
        0.49,
        0.51,
        0.28,
        0.74,
        [{"query": "What does Nick Sleep say about Amazon's business model?", "ndcg@10": 0.3209, "recall@10": 0.5, "mrr": 0.2, "retrieved_count": 10}],
    )
    path = tmp_path / "wrapped.json"
    path.write_text(json.dumps({"baseline": baseline}))

    loaded = load_report(path)

    assert loaded["config_label"] == "baseline/heuristic"
    assert loaded["num_queries"] == 1


def test_drift_report_computes_aggregate_query_and_slice_deltas():
    old = _report(
        "old",
        0.5335,
        0.5471,
        0.3015,
        0.804,
        [
            {"query": "What does Buffett say about circle of competence?", "ndcg@10": 0.9907, "recall@10": 1.0, "mrr": 1.0, "retrieved_count": 10},
            {"query": "How does Charlie Munger think about mental models and latticework?", "ndcg@10": 0.5117, "recall@10": 0.375, "mrr": 1.0, "retrieved_count": 10},
            {"query": "What does Nick Sleep say about Amazon's business model?", "ndcg@10": 0.2978, "recall@10": 0.5, "mrr": 0.1667, "retrieved_count": 10},
        ],
    )
    new = _report(
        "new",
        0.5263,
        0.5387,
        0.3372,
        0.7729,
        [
            {"query": "What does Buffett say about circle of competence?", "ndcg@10": 0.8722, "recall@10": 0.75, "mrr": 1.0, "retrieved_count": 4},
            {"query": "How does Charlie Munger think about mental models and latticework?", "ndcg@10": 0.4982, "recall@10": 0.5, "mrr": 0.5, "retrieved_count": 10},
            {"query": "What does Nick Sleep say about Amazon's business model?", "ndcg@10": 0.3209, "recall@10": 0.5, "mrr": 0.2, "retrieved_count": 10},
        ],
    )

    agg = aggregate_deltas(old, new)
    assert agg == {
        "mean_ndcg@10": -0.0072,
        "mean_recall@10": -0.0084,
        "mean_precision@10": 0.0357,
        "mean_mrr": -0.0311,
    }

    changed = changed_queries(old, new)
    assert len(changed) == 3
    assert changed[0]["query"] == "What does Buffett say about circle of competence?"
    assert changed[0]["delta"] == {"ndcg@10": -0.1185, "recall@10": -0.25, "mrr": 0.0}

    slices = slice_deltas(old, new)
    assert slices["buffett"]["count"] == 1
    assert slices["buffett"]["delta"] == {"ndcg@10": -0.1185, "recall@10": -0.25, "mrr": 0.0}

    report = drift_report(old, new, max_rows=2)
    assert report["changed_query_count"] == 3
    assert len(report["changed_queries"]) == 2
