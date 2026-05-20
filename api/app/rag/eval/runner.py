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

    @property
    def high_relevance_ids(self) -> set[str]:
        """IDs with relevance_grade >= 3 (strongly relevant)."""
        return {cid for cid, grade in self.golden.items() if grade >= 3}


@dataclass
class PerQueryMetrics:
    query_text: str
    ndcg_at_5: float
    ndcg_at_10: float
    recall_at_5: float
    recall_at_10: float
    recall_at_50: float
    recall_at_100: float
    precision_at_5: float
    precision_at_10: float
    mrr_score: float
    retrieved_count: int
    relevant_hits_at_5: int = 0
    relevant_hits_at_10: int = 0
    relevant_hits_at_50: int = 0
    relevant_hits_at_100: int = 0
    high_relevance_hits_at_5: int = 0
    high_relevance_hits_at_10: int = 0
    high_relevance_hits_at_50: int = 0
    high_relevance_hits_at_100: int = 0
    golden_relevant_count: int = 0
    golden_high_relevance_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query_text,
            "ndcg@5": round(self.ndcg_at_5, 4),
            "ndcg@10": round(self.ndcg_at_10, 4),
            "recall@5": round(self.recall_at_5, 4),
            "recall@10": round(self.recall_at_10, 4),
            "recall@50": round(self.recall_at_50, 4),
            "recall@100": round(self.recall_at_100, 4),
            "precision@5": round(self.precision_at_5, 4),
            "precision@10": round(self.precision_at_10, 4),
            "mrr": round(self.mrr_score, 4),
            "retrieved_count": self.retrieved_count,
            "relevant_hits@5": self.relevant_hits_at_5,
            "relevant_hits@10": self.relevant_hits_at_10,
            "relevant_hits@50": self.relevant_hits_at_50,
            "relevant_hits@100": self.relevant_hits_at_100,
            "high_relevance_hits@5": self.high_relevance_hits_at_5,
            "high_relevance_hits@10": self.high_relevance_hits_at_10,
            "high_relevance_hits@50": self.high_relevance_hits_at_50,
            "high_relevance_hits@100": self.high_relevance_hits_at_100,
            "golden_relevant_count": self.golden_relevant_count,
            "golden_high_relevance_count": self.golden_high_relevance_count,
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
    scope: dict[str, Any] = field(default_factory=dict)
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
            "scope": self.scope,
            "per_query": self.per_query,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvalReport":
        return cls(
            config_label=payload["config_label"],
            num_queries=payload["num_queries"],
            mean_ndcg_at_5=payload["mean_ndcg@5"],
            mean_ndcg_at_10=payload["mean_ndcg@10"],
            mean_recall_at_5=payload["mean_recall@5"],
            mean_recall_at_10=payload["mean_recall@10"],
            mean_precision_at_5=payload["mean_precision@5"],
            mean_precision_at_10=payload["mean_precision@10"],
            mean_mrr=payload["mean_mrr"],
            scope=payload.get("scope", {}),
            per_query=payload.get("per_query", []),
        )


@dataclass(frozen=True)
class EvalConfig:
    label: str
    retrieval_mode: Optional[str]
    weighting_enabled: Optional[bool]
    hardening_enabled: Optional[bool]


def no_regression_bar() -> dict[str, float]:
    return {
        "mean_ndcg@10_min_delta": _NO_REGRESSION_NDCG_DELTA,
        "mean_recall@10_min_delta": _NO_REGRESSION_RECALL_DELTA,
    }


def parse_eval_config(label: str) -> EvalConfig:
    normalized = label.strip().lower()
    retrieval_mode: Optional[str] = None
    weighting_enabled: Optional[bool] = None
    hardening_enabled: Optional[bool] = None

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
    if any(token in normalized for token in ("retrieval_hardening_on", "hardening_on", "parent_child_on")):
        hardening_enabled = True
    elif any(token in normalized for token in ("retrieval_hardening_off", "hardening_off", "parent_child_off")):
        hardening_enabled = False

    return EvalConfig(
        label=label,
        retrieval_mode=retrieval_mode,
        weighting_enabled=weighting_enabled,
        hardening_enabled=hardening_enabled,
    )


def compare_reports(report_a: EvalReport, report_b: EvalReport) -> dict[str, Any]:
    delta_ndcg = round(report_b.mean_ndcg_at_10 - report_a.mean_ndcg_at_10, 4)
    delta_recall = round(report_b.mean_recall_at_10 - report_a.mean_recall_at_10, 4)
    per_query_gates = evaluate_per_query_gates(report_a, report_b)
    passes_per_query_gates = all(gate["passed"] for gate in per_query_gates)
    passes_aggregate_bar = (
        delta_ndcg >= _NO_REGRESSION_NDCG_DELTA
        and delta_recall >= _NO_REGRESSION_RECALL_DELTA
    )
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
        "per_query_gates": per_query_gates,
        "passes_per_query_gates": passes_per_query_gates,
        "passes_no_regression_bar": passes_aggregate_bar and passes_per_query_gates,
    }


def _per_query_requirements(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    relevant_count = int(row.get("golden_relevant_count") or 0)
    high_count = int(row.get("golden_high_relevance_count") or 0)
    if relevant_count < 5 or high_count < 1:
        return None
    requirements = {
        "min_high_relevance_hits@5": 1,
        "min_relevant_hits@10": min(3, relevant_count),
        "no_regression_metrics": ["ndcg@10", "recall@10"],
    }
    if int(row.get("retrieved_count") or 0) >= 50:
        requirements["min_high_relevance_hits@50"] = min(3, high_count)
        requirements["min_relevant_hits@50"] = min(8, relevant_count)
        requirements["no_regression_metrics"].append("recall@50")
    return requirements


def evaluate_per_query_gates(report_a: EvalReport, report_b: EvalReport) -> list[dict[str, Any]]:
    baseline_by_query = {row.get("query"): row for row in report_a.per_query}
    gates: list[dict[str, Any]] = []
    for current in report_b.per_query:
        query = current.get("query")
        baseline = baseline_by_query.get(query, {})
        requirements = _per_query_requirements(current)
        if requirements is None:
            continue

        failures: list[str] = []
        if int(current.get("high_relevance_hits@5") or 0) < requirements["min_high_relevance_hits@5"]:
            failures.append(
                "high_relevance_hits@5 "
                f"{current.get('high_relevance_hits@5')} < {requirements['min_high_relevance_hits@5']}"
            )
        if int(current.get("relevant_hits@10") or 0) < requirements["min_relevant_hits@10"]:
            failures.append(
                "relevant_hits@10 "
                f"{current.get('relevant_hits@10')} < {requirements['min_relevant_hits@10']}"
            )
        if (
            "min_high_relevance_hits@50" in requirements
            and int(current.get("high_relevance_hits@50") or 0) < requirements["min_high_relevance_hits@50"]
        ):
            failures.append(
                "high_relevance_hits@50 "
                f"{current.get('high_relevance_hits@50')} < {requirements['min_high_relevance_hits@50']}"
            )
        if (
            "min_relevant_hits@50" in requirements
            and int(current.get("relevant_hits@50") or 0) < requirements["min_relevant_hits@50"]
        ):
            failures.append(
                "relevant_hits@50 "
                f"{current.get('relevant_hits@50')} < {requirements['min_relevant_hits@50']}"
            )
        for metric in requirements["no_regression_metrics"]:
            if float(current.get(metric) or 0.0) + 1e-9 < float(baseline.get(metric) or 0.0):
                failures.append(
                    f"{metric} regressed {current.get(metric)} < {baseline.get(metric)}"
                )

        gates.append(
            {
                "query": query,
                "requirements": requirements,
                "passed": not failures,
                "failures": failures,
            }
        )
    return gates


def load_golden_queries(db: Session, *, source_type: Optional[str] = None) -> list[GoldenQuery]:
    """Load all golden queries from rag_eval_golden, grouped by query_text."""
    from app.models.rag import RagChunk, RagDocument, RagEvalGolden, RagSource

    query = db.query(RagEvalGolden)
    if source_type:
        query = (
            query.join(RagChunk, RagEvalGolden.chunk_id == RagChunk.id)
            .join(RagDocument, RagChunk.document_id == RagDocument.id)
            .join(RagSource, RagDocument.source_id == RagSource.id)
            .filter(RagSource.source_type == source_type)
        )
    rows = query.all()
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
    top5 = set(retrieved_ids[:5])
    top10 = set(retrieved_ids[:10])
    top50 = set(retrieved_ids[:50])
    top100 = set(retrieved_ids[:100])
    return PerQueryMetrics(
        query_text=gq.query_text,
        ndcg_at_5=ndcg_at_k(retrieved_ids, gq.golden, k=5),
        ndcg_at_10=ndcg_at_k(retrieved_ids, gq.golden, k=10),
        recall_at_5=recall_at_k(retrieved_ids, gq.relevant_ids, k=5),
        recall_at_10=recall_at_k(retrieved_ids, gq.relevant_ids, k=10),
        recall_at_50=recall_at_k(retrieved_ids, gq.relevant_ids, k=50),
        recall_at_100=recall_at_k(retrieved_ids, gq.relevant_ids, k=100),
        precision_at_5=precision_at_k(retrieved_ids, gq.relevant_ids, k=5),
        precision_at_10=precision_at_k(retrieved_ids, gq.relevant_ids, k=10),
        mrr_score=mrr(retrieved_ids, gq.relevant_ids),
        retrieved_count=len(retrieved_ids),
        relevant_hits_at_5=len(top5 & gq.relevant_ids),
        relevant_hits_at_10=len(top10 & gq.relevant_ids),
        relevant_hits_at_50=len(top50 & gq.relevant_ids),
        relevant_hits_at_100=len(top100 & gq.relevant_ids),
        high_relevance_hits_at_5=len(top5 & gq.high_relevance_ids),
        high_relevance_hits_at_10=len(top10 & gq.high_relevance_ids),
        high_relevance_hits_at_50=len(top50 & gq.high_relevance_ids),
        high_relevance_hits_at_100=len(top100 & gq.high_relevance_ids),
        golden_relevant_count=len(gq.relevant_ids),
        golden_high_relevance_count=len(gq.high_relevance_ids),
    )


def _safe_mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def run_evaluation(
    db: Session,
    *,
    config_label: str = "current",
    retrieval_fn: Optional[Callable] = None,
    top_k: int = 10,
    source_type: Optional[str] = None,
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
                hardening_enabled=config.hardening_enabled,
            )

    golden_queries = load_golden_queries(db, source_type=source_type)
    if not golden_queries:
        scope_note = f" for source_type={source_type}" if source_type else ""
        log.warning("No golden queries found in rag_eval_golden%s; returning empty report.", scope_note)
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
            scope={"source_type": source_type} if source_type else {},
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
        scope={"source_type": source_type} if source_type else {},
        per_query=[m.as_dict() for m in per_query_metrics],
    )
