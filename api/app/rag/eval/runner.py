"""
Offline evaluation runner for the RAG retrieval pipeline.

Loads golden queries from rag_eval_golden, runs them through the configured
retrieval function, and computes aggregate IR metrics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.rag.eval.metrics import ndcg_at_k, recall_at_k, precision_at_k, mrr

log = logging.getLogger(__name__)
_NO_REGRESSION_NDCG_DELTA = -0.02
_NO_REGRESSION_RECALL_DELTA = -0.02


@dataclass
class GoldenQuery:
    query_text: str
    # mapping chunk_id → relevance_grade
    golden: dict[str, int] = field(default_factory=dict)

    @property
    def relevant_ids(self) -> set[str]:
        """IDs with relevance_grade >= 1 (any positive grade counts as relevant)."""
        return {cid for cid, grade in self.golden.items() if grade >= 1}


@dataclass
class PerQueryMetrics:
    query_text: str
    ndcg_at_5: float
    ndcg_at_10: float
    recall_at_5: float
    recall_at_10: float
    precision_at_5: float
    precision_at_10: float
    mrr_score: float
    retrieved_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query_text,
            "ndcg@5": round(self.ndcg_at_5, 4),
            "ndcg@10": round(self.ndcg_at_10, 4),
            "recall@5": round(self.recall_at_5, 4),
            "recall@10": round(self.recall_at_10, 4),
            "precision@5": round(self.precision_at_5, 4),
            "precision@10": round(self.precision_at_10, 4),
            "mrr": round(self.mrr_score, 4),
            "retrieved_count": self.retrieved_count,
        }


@dataclass
class EvalReport:
    config_label: str
    num_queries: int
    mean_ndcg_at_5: float
    mean_ndcg_at_10: float
    mean_recall_at_5: float
    mean_recall_at_10: float
    mean_precision_at_5: float
    mean_precision_at_10: float
    mean_mrr: float
    per_query: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "config_label": self.config_label,
            "num_queries": self.num_queries,
            "mean_ndcg@5": round(self.mean_ndcg_at_5, 4),
            "mean_ndcg@10": round(self.mean_ndcg_at_10, 4),
            "mean_recall@5": round(self.mean_recall_at_5, 4),
            "mean_recall@10": round(self.mean_recall_at_10, 4),
            "mean_precision@5": round(self.mean_precision_at_5, 4),
            "mean_precision@10": round(self.mean_precision_at_10, 4),
            "mean_mrr": round(self.mean_mrr, 4),
            "per_query": self.per_query,
        }


@dataclass(frozen=True)
class EvalConfig:
    label: str
    retrieval_mode: Optional[str]
    weighting_enabled: Optional[bool]


def no_regression_bar() -> dict[str, float]:
    return {
        "mean_ndcg@10_min_delta": _NO_REGRESSION_NDCG_DELTA,
        "mean_recall@10_min_delta": _NO_REGRESSION_RECALL_DELTA,
    }


def parse_eval_config(label: str) -> EvalConfig:
    normalized = label.strip().lower()
    retrieval_mode: Optional[str] = None
    weighting_enabled: Optional[bool] = None

    if "dense_only" in normalized:
        retrieval_mode = "dense_only"
    elif "sparse_only" in normalized:
        retrieval_mode = "sparse_only"
    elif "hybrid" in normalized:
        retrieval_mode = "hybrid"

    if any(token in normalized for token in ("metadata_weighting_on", "weighting_on", "weighted")):
        weighting_enabled = True
    elif any(token in normalized for token in ("metadata_weighting_off", "weighting_off", "unweighted")):
        weighting_enabled = False

    return EvalConfig(
        label=label,
        retrieval_mode=retrieval_mode,
        weighting_enabled=weighting_enabled,
    )


def compare_reports(report_a: EvalReport, report_b: EvalReport) -> dict[str, Any]:
    delta_ndcg = round(report_b.mean_ndcg_at_10 - report_a.mean_ndcg_at_10, 4)
    delta_recall = round(report_b.mean_recall_at_10 - report_a.mean_recall_at_10, 4)
    return {
        "config_a": report_a.as_dict(),
        "config_b": report_b.as_dict(),
        "delta": {
            "mean_ndcg@10": delta_ndcg,
            "mean_recall@10": delta_recall,
            "mean_precision@10": round(
                report_b.mean_precision_at_10 - report_a.mean_precision_at_10, 4
            ),
            "mean_mrr": round(report_b.mean_mrr - report_a.mean_mrr, 4),
        },
        "no_regression_bar": no_regression_bar(),
        "passes_no_regression_bar": (
            delta_ndcg >= _NO_REGRESSION_NDCG_DELTA
            and delta_recall >= _NO_REGRESSION_RECALL_DELTA
        ),
    }


def load_golden_queries(db: Session) -> list[GoldenQuery]:
    """Load all golden queries from rag_eval_golden, grouped by query_text."""
    from app.models.rag import RagEvalGolden

    rows = db.query(RagEvalGolden).all()
    groups: dict[str, dict[str, int]] = {}
    for row in rows:
        text = row.query_text
        if text not in groups:
            groups[text] = {}
        groups[text][str(row.chunk_id)] = row.relevance_grade

    return [GoldenQuery(query_text=t, golden=g) for t, g in groups.items()]


def _compute_per_query(
    gq: GoldenQuery,
    retrieved_ids: list[str],
) -> PerQueryMetrics:
    return PerQueryMetrics(
        query_text=gq.query_text,
        ndcg_at_5=ndcg_at_k(retrieved_ids, gq.golden, k=5),
        ndcg_at_10=ndcg_at_k(retrieved_ids, gq.golden, k=10),
        recall_at_5=recall_at_k(retrieved_ids, gq.relevant_ids, k=5),
        recall_at_10=recall_at_k(retrieved_ids, gq.relevant_ids, k=10),
        precision_at_5=precision_at_k(retrieved_ids, gq.relevant_ids, k=5),
        precision_at_10=precision_at_k(retrieved_ids, gq.relevant_ids, k=10),
        mrr_score=mrr(retrieved_ids, gq.relevant_ids),
        retrieved_count=len(retrieved_ids),
    )


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def run_evaluation(
    db: Session,
    *,
    config_label: str = "current",
    retrieval_fn: Optional[Callable] = None,
    top_k: int = 10,
) -> EvalReport:
    """
    Run all golden queries through *retrieval_fn* and return aggregate metrics.

    If *retrieval_fn* is None, the current hybrid retrieval stack is used. The
    config label can optionally encode the retrieval mode and whether metadata
    weighting is enabled (for example: "hybrid+metadata_weighting_on").
    """
    if retrieval_fn is None:
        from app.rag.retrieval import retrieve_hybrid

        config = parse_eval_config(config_label)

        def retrieval_fn(query_text: str, session: Session, *, top_k: int = top_k):
            return retrieve_hybrid(
                query_text,
                session,
                top_k=top_k,
                retrieval_mode=config.retrieval_mode,
                weighting_enabled=config.weighting_enabled,
            )

    golden_queries = load_golden_queries(db)
    if not golden_queries:
        log.warning("No golden queries found in rag_eval_golden; returning empty report.")
        return EvalReport(
            config_label=config_label,
            num_queries=0,
            mean_ndcg_at_5=0.0,
            mean_ndcg_at_10=0.0,
            mean_recall_at_5=0.0,
            mean_recall_at_10=0.0,
            mean_precision_at_5=0.0,
            mean_precision_at_10=0.0,
            mean_mrr=0.0,
            per_query=[],
        )

    per_query_metrics: list[PerQueryMetrics] = []
    for gq in golden_queries:
        try:
            raw = retrieval_fn(gq.query_text, db, top_k=top_k)
            # Support both RetrievedChunk objects and plain strings.
            retrieved_ids = [
                str(r.chunk_id) if hasattr(r, "chunk_id") else str(r)
                for r in raw
            ]
        except Exception as exc:
            log.warning("Retrieval failed for query %r: %s", gq.query_text[:60], exc)
            retrieved_ids = []

        per_query_metrics.append(_compute_per_query(gq, retrieved_ids))

    return EvalReport(
        config_label=config_label,
        num_queries=len(per_query_metrics),
        mean_ndcg_at_5=_safe_mean([m.ndcg_at_5 for m in per_query_metrics]),
        mean_ndcg_at_10=_safe_mean([m.ndcg_at_10 for m in per_query_metrics]),
        mean_recall_at_5=_safe_mean([m.recall_at_5 for m in per_query_metrics]),
        mean_recall_at_10=_safe_mean([m.recall_at_10 for m in per_query_metrics]),
        mean_precision_at_5=_safe_mean([m.precision_at_5 for m in per_query_metrics]),
        mean_precision_at_10=_safe_mean([m.precision_at_10 for m in per_query_metrics]),
        mean_mrr=_safe_mean([m.mrr_score for m in per_query_metrics]),
        per_query=[m.as_dict() for m in per_query_metrics],
    )
