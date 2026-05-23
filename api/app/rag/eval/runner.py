"""
Offline evaluation runner for the RAG retrieval pipeline.

Loads golden queries from rag_eval_golden, runs them through the configured
retrieval function, and computes aggregate IR metrics.
"""

from __future__ import annotations

import logging
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.rag.eval.metrics import ndcg_at_k, recall_at_k, precision_at_k, mrr

log = logging.getLogger(__name__)
_NO_REGRESSION_NDCG_DELTA = -0.02
_NO_REGRESSION_RECALL_DELTA = -0.02
_CLEAR_WIN_NDCG_DELTA = 0.02
_CLEAR_WIN_RECALL_DELTA = 0.02


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


@dataclass(frozen=True)
class RerankerExperiment:
    label: str
    provider: str
    input_mode: str = "raw"
    model: Optional[str] = None

    @property
    def is_baseline(self) -> bool:
        return self.provider == "heuristic"


@dataclass
class CandidateBundle:
    query_text: str
    intent: Any
    candidates: list[Any] = field(default_factory=list)
    expanded_by_chunk_id: dict[str, Any] = field(default_factory=dict)
    source_author_terms: set[str] = field(default_factory=set)
    constraints_relaxed: bool = False
    relaxation_reason: Optional[str] = None


def no_regression_bar() -> dict[str, float]:
    return {
        "mean_ndcg@10_min_delta": _NO_REGRESSION_NDCG_DELTA,
        "mean_recall@10_min_delta": _NO_REGRESSION_RECALL_DELTA,
    }


def clear_win_bar() -> dict[str, float]:
    return {
        "mean_ndcg@10_min_delta": _CLEAR_WIN_NDCG_DELTA,
        "mean_recall@10_min_delta": _CLEAR_WIN_RECALL_DELTA,
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


def _normalize_provider_filter(providers: Optional[list[str] | tuple[str, ...]]) -> Optional[set[str]]:
    if not providers:
        return None
    normalized = {provider.strip().lower() for provider in providers if provider.strip()}
    return normalized or None


def _normalize_input_modes(input_modes: Optional[list[str] | tuple[str, ...]]) -> list[str]:
    from app.rag.reranker import reranker_input_mode

    if not input_modes:
        return ["raw", "compact_context", "expanded_context"]
    modes: list[str] = []
    for mode in input_modes:
        normalized = reranker_input_mode(mode)
        if normalized not in modes:
            modes.append(normalized)
    return modes or ["raw", "compact_context", "expanded_context"]


def default_reranker_experiments(
    *,
    include_cohere: bool = False,
    providers: Optional[list[str] | tuple[str, ...]] = None,
    input_modes: Optional[list[str] | tuple[str, ...]] = None,
) -> list[RerankerExperiment]:
    from app.rag.reranker import reranker_available, reranker_model

    provider_filter = _normalize_provider_filter(providers)
    modes = _normalize_input_modes(input_modes)
    experiments = [
        RerankerExperiment(
            label="baseline/heuristic",
            provider="heuristic",
            input_mode="expanded_context",
        )
    ]

    def add_provider(provider: str) -> None:
        if provider_filter is not None and provider not in provider_filter:
            return
        if not reranker_available(provider):
            return
        model = reranker_model(provider)
        for mode in modes:
            experiments.append(RerankerExperiment(label=f"{provider}/{mode}", provider=provider, input_mode=mode, model=model))

    add_provider("jina")
    add_provider("local")
    if include_cohere:
        add_provider("cohere")
    return experiments


def _load_reranker_cache(cache_path: Optional[str]) -> dict[str, Any]:
    if not cache_path:
        return {}
    path = Path(cache_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        log.warning("Ignoring unreadable reranker diagnosis cache %s: %s", cache_path, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _save_reranker_cache(cache_path: Optional[str], cache: dict[str, Any]) -> None:
    if not cache_path:
        return
    path = Path(cache_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True))


def _reranker_cache_key(
    *,
    provider: str,
    model: Optional[str],
    input_mode: str,
    query_text: str,
    passages: list[str],
) -> str:
    payload = {
        "provider": provider,
        "model": model or "",
        "input_mode": input_mode,
        "query": query_text,
        "passages_sha256": [
            hashlib.sha256(passage.encode("utf-8", errors="ignore")).hexdigest()
            for passage in passages
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _clone_chunk(chunk: Any) -> Any:
    from app.rag.retrieval import RetrievedChunk

    metadata = getattr(chunk, "metadata_json", None)
    metadata_json = dict(metadata) if isinstance(metadata, dict) else {}
    return RetrievedChunk(
        chunk_id=str(getattr(chunk, "chunk_id")),
        document_id=str(getattr(chunk, "document_id")),
        chunk_index=int(getattr(chunk, "chunk_index")),
        text=str(getattr(chunk, "text", "") or ""),
        token_count=getattr(chunk, "token_count", None),
        metadata_json=metadata_json,
        cosine_distance=float(getattr(chunk, "cosine_distance", 1.0) or 1.0),
        ts_rank=getattr(chunk, "ts_rank", None),
        rrf_score=getattr(chunk, "rrf_score", None),
        reranker_score=getattr(chunk, "reranker_score", None),
        metadata_weight=float(getattr(chunk, "metadata_weight", 1.0) or 1.0),
        base_score=getattr(chunk, "base_score", None),
        weighted_score=getattr(chunk, "weighted_score", None),
        corpus_class=getattr(chunk, "corpus_class", None),
        weighting_applied=bool(getattr(chunk, "weighting_applied", False)),
    )


def _build_eval_report(
    *,
    config_label: str,
    metrics: list[PerQueryMetrics],
    per_query_rows: list[dict[str, Any]],
    scope: Optional[dict[str, Any]] = None,
) -> EvalReport:
    return EvalReport(
        config_label=config_label,
        num_queries=len(metrics),
        mean_ndcg_at_5=_safe_mean([row.ndcg_at_5 for row in metrics]),
        mean_ndcg_at_10=_safe_mean([row.ndcg_at_10 for row in metrics]),
        mean_recall_at_5=_safe_mean([row.recall_at_5 for row in metrics]),
        mean_recall_at_10=_safe_mean([row.recall_at_10 for row in metrics]),
        mean_precision_at_5=_safe_mean([row.precision_at_5 for row in metrics]),
        mean_precision_at_10=_safe_mean([row.precision_at_10 for row in metrics]),
        mean_mrr=_safe_mean([row.mrr_score for row in metrics]),
        scope=scope or {},
        per_query=per_query_rows,
    )


def _build_candidate_bundle(db: Session, query_text: str, *, candidate_pool_size: int) -> CandidateBundle:
    from app.rag.author_selection import select_authors
    from app.rag.concept_mode import (
        _BROAD_RETRIEVAL_MAX,
        _BROAD_RETRIEVAL_MIN,
        _CONCEPT_TOP_K_AUTHORS,
        _CONTEXT_EXPANSION_MAX_CHARS,
        _CONTEXT_EXPANSION_WINDOW,
        _collect_candidate_chunks,
        _source_author_terms,
    )
    from app.rag.intent_router import parse_intent
    from app.rag.retrieval import expand_chunks_with_context

    intent = parse_intent(query_text)
    if intent.query_type == "single_author" and intent.author_ids:
        author_ids = intent.author_ids[:1]
    else:
        author_ids = [author.author_id for author in select_authors(query_text, db, top_k=_CONCEPT_TOP_K_AUTHORS)]

    broad_top_k = min(_BROAD_RETRIEVAL_MAX, max(candidate_pool_size, _BROAD_RETRIEVAL_MIN))
    candidates, constraints_relaxed, relaxation_reason = _collect_candidate_chunks(
        query_text,
        db,
        intent=intent,
        author_ids=author_ids,
        broad_top_k=broad_top_k,
    )
    expanded_chunks = expand_chunks_with_context(
        candidates,
        db,
        window_size=_CONTEXT_EXPANSION_WINDOW,
        max_chars=_CONTEXT_EXPANSION_MAX_CHARS,
        only_when_needed=False,
    )
    return CandidateBundle(
        query_text=query_text,
        intent=intent,
        candidates=candidates,
        expanded_by_chunk_id={chunk.chunk_id: chunk for chunk in expanded_chunks},
        source_author_terms=_source_author_terms(intent),
        constraints_relaxed=constraints_relaxed,
        relaxation_reason=relaxation_reason,
    )


def _candidate_pool_row(gq: GoldenQuery, bundle: CandidateBundle) -> dict[str, Any]:
    candidate_ids = {str(getattr(chunk, "chunk_id")) for chunk in bundle.candidates}
    relevant_hits = len(candidate_ids & gq.relevant_ids)
    high_relevance_hits = len(candidate_ids & gq.high_relevance_ids)
    relevant_count = len(gq.relevant_ids)
    high_relevance_count = len(gq.high_relevance_ids)
    return {
        "query": gq.query_text,
        "candidate_pool_size": len(bundle.candidates),
        "candidate_pool_relevant_hits": relevant_hits,
        "candidate_pool_high_relevance_hits": high_relevance_hits,
        "candidate_pool_recall": round(relevant_hits / relevant_count, 4) if relevant_count else 0.0,
        "candidate_pool_high_recall": round(high_relevance_hits / high_relevance_count, 4) if high_relevance_count else 0.0,
        "constraints_relaxed": bundle.constraints_relaxed,
        "constraint_relaxation_reason": bundle.relaxation_reason,
        "candidate_pool_top_results": _chunk_briefs(bundle.candidates, limit=10),
    }


def _chunk_briefs(chunks: list[Any], *, limit: int = 5) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in chunks[:limit]:
        rows.append(
            {
                "chunk_id": str(getattr(chunk, "chunk_id", "")),
                "document_id": str(getattr(chunk, "document_id", "")),
                "chunk_index": int(getattr(chunk, "chunk_index", -1)),
                "reranker_score": round(float(getattr(chunk, "reranker_score", 0.0) or 0.0), 6)
                if getattr(chunk, "reranker_score", None) is not None
                else None,
            }
        )
    return rows


def _rank_with_experiment(
    query_text: str,
    bundle: CandidateBundle,
    experiment: RerankerExperiment,
    *,
    top_k: int,
    reranker_cache: Optional[dict[str, Any]] = None,
) -> tuple[list[Any], Optional[str]]:
    from app.rag.concept_mode import (
        _apply_cross_encoder_scores,
        _heuristic_rank_candidates,
        _reranker_passages_for_mode,
        _select_diverse_top_chunks,
    )
    from app.rag.reranker import rerank, reranker_input_mode

    if not bundle.candidates:
        return [], None

    topic_entities = getattr(bundle.intent, "topic_entities", None)
    candidates = [_clone_chunk(chunk) for chunk in bundle.candidates]
    expanded_by_chunk_id = {
        chunk_id: _clone_chunk(chunk)
        for chunk_id, chunk in bundle.expanded_by_chunk_id.items()
    }
    heuristic_ranked = _heuristic_rank_candidates(
        query_text,
        candidates,
        topic_entities=topic_entities,
        source_author_terms=bundle.source_author_terms,
        expanded_by_chunk_id=expanded_by_chunk_id,
    )
    ranked = heuristic_ranked

    if not experiment.is_baseline:
        try:
            input_mode = reranker_input_mode(experiment.input_mode)
            _reranker_inputs, passages = _reranker_passages_for_mode(
                candidates,
                input_mode=input_mode,
                expanded_by_chunk_id=expanded_by_chunk_id,
            )
            cache_key = _reranker_cache_key(
                provider=experiment.provider,
                model=experiment.model,
                input_mode=input_mode,
                query_text=query_text,
                passages=passages,
            )
            cached_results = (reranker_cache or {}).get(cache_key)
            if isinstance(cached_results, list):
                from app.rag.reranker import RerankedResult

                results = [
                    RerankedResult(
                        index=int(item["index"]),
                        relevance_score=float(item["relevance_score"]),
                        text=passages[int(item["index"])],
                    )
                    for item in cached_results
                    if isinstance(item, dict) and int(item.get("index", -1)) < len(passages)
                ]
            else:
                results = rerank(
                    query_text,
                    passages,
                    top_k=len(candidates),
                    provider=experiment.provider,
                    model=experiment.model,
                )
                if reranker_cache is not None:
                    reranker_cache[cache_key] = [
                        {"index": result.index, "relevance_score": result.relevance_score}
                        for result in results
                    ]
            if results:
                ranked = _apply_cross_encoder_scores(candidates, heuristic_ranked, results, query=query_text)
        except Exception as exc:
            return [], str(exc)

    selected = _select_diverse_top_chunks(ranked, top_k=min(top_k, len(candidates)))
    return selected, None


def recommend_reranker_rollout(
    baseline_report: EvalReport,
    candidate_reports: list[EvalReport],
    *,
    experiments_by_label: Optional[dict[str, RerankerExperiment]] = None,
) -> dict[str, Any]:
    comparisons: list[dict[str, Any]] = []
    eligible_candidates: list[dict[str, Any]] = []
    clear_win = clear_win_bar()

    for report in candidate_reports:
        comparison = compare_reports(baseline_report, report)
        delta = comparison["delta"]
        eligible_for_default = (
            comparison["passes_no_regression_bar"]
            and delta["mean_ndcg@10"] >= clear_win["mean_ndcg@10_min_delta"]
            and delta["mean_recall@10"] >= clear_win["mean_recall@10_min_delta"]
        )
        row = {
            "label": report.config_label,
            "provider": experiments_by_label.get(report.config_label).provider if experiments_by_label and report.config_label in experiments_by_label else None,
            "input_mode": experiments_by_label.get(report.config_label).input_mode if experiments_by_label and report.config_label in experiments_by_label else None,
            "model": experiments_by_label.get(report.config_label).model if experiments_by_label and report.config_label in experiments_by_label else None,
            "comparison": comparison,
            "eligible_for_default": eligible_for_default,
        }
        comparisons.append(row)
        if eligible_for_default:
            eligible_candidates.append(row)

    eligible_candidates.sort(
        key=lambda row: (
            row["comparison"]["delta"]["mean_ndcg@10"],
            row["comparison"]["delta"]["mean_recall@10"],
            row["comparison"]["delta"]["mean_mrr"],
        ),
        reverse=True,
    )
    selected = eligible_candidates[0] if eligible_candidates else None
    return {
        "baseline_label": baseline_report.config_label,
        "clear_win_bar": clear_win,
        "candidate_comparisons": comparisons,
        "recommended_default_provider": selected["provider"] if selected else "none",
        "recommended_default_label": selected["label"] if selected else "none",
        "recommended_input_mode": selected["input_mode"] if selected else None,
        "recommended_model": selected["model"] if selected else None,
        "keep_default_disabled": selected is None,
        "reason": (
            "No reranker beat the heuristic baseline strongly enough to justify enabling it by default."
            if selected is None
            else f"Enable {selected['label']} only because it cleared the aggregate + per-query win bars."
        ),
    }


def _regressed_queries(baseline_report: EvalReport, candidate_report: EvalReport) -> list[dict[str, Any]]:
    baseline_by_query = {row.get("query"): row for row in baseline_report.per_query}
    rows: list[dict[str, Any]] = []
    for row in candidate_report.per_query:
        query = row.get("query")
        baseline_row = baseline_by_query.get(query, {})
        delta_ndcg = round(float(row.get("ndcg@10") or 0.0) - float(baseline_row.get("ndcg@10") or 0.0), 4)
        delta_recall = round(float(row.get("recall@10") or 0.0) - float(baseline_row.get("recall@10") or 0.0), 4)
        if delta_ndcg >= 0 and delta_recall >= 0:
            continue
        rows.append(
            {
                "query": query,
                "delta_ndcg@10": delta_ndcg,
                "delta_recall@10": delta_recall,
                "candidate_pool_recall": row.get("candidate_pool_recall"),
                "top_results": row.get("top_results", []),
            }
        )
    rows.sort(key=lambda row: (row["delta_ndcg@10"], row["delta_recall@10"]))
    return rows


def diagnose_jina_failure_mode(
    baseline_report: EvalReport,
    experiment_reports: dict[str, EvalReport],
    candidate_pool_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    findings: list[str] = []
    evidence: dict[str, Any] = {}

    jina_raw = experiment_reports.get("jina/raw")
    jina_expanded = experiment_reports.get("jina/expanded_context")
    local_reports = [report for label, report in experiment_reports.items() if label.startswith("local/")]
    best_local = max(local_reports, key=lambda report: (report.mean_ndcg_at_10, report.mean_recall_at_10), default=None)
    best_jina = max(
        [report for report in (jina_raw, jina_expanded) if report is not None],
        key=lambda report: (report.mean_ndcg_at_10, report.mean_recall_at_10),
        default=None,
    )

    if jina_raw is None:
        findings.append("Jina was not benchmarked because the provider was unavailable in this environment.")
    else:
        raw_vs_baseline = compare_reports(baseline_report, jina_raw)
        evidence["jina_raw_vs_baseline"] = raw_vs_baseline["delta"]
        if raw_vs_baseline["delta"]["mean_ndcg@10"] < 0 or raw_vs_baseline["delta"]["mean_recall@10"] < 0:
            findings.append(
                "Raw-anchor Jina reranking regressed against the heuristic baseline on the golden set, so the historical poor results were reproducible."
            )
        elif raw_vs_baseline["delta"]["mean_ndcg@10"] > 0 or raw_vs_baseline["delta"]["mean_recall@10"] > 0:
            findings.append(
                "Raw-anchor Jina improved ranking quality over the heuristic baseline, but the gain was not strong enough to clear the default-rollout bar."
            )
        regressed_queries = _regressed_queries(baseline_report, jina_raw)
        if regressed_queries:
            evidence["jina_raw_regressed_queries"] = regressed_queries[:5]

    if jina_raw is not None and jina_expanded is not None:
        expanded_vs_raw = compare_reports(jina_raw, jina_expanded)
        evidence["jina_expanded_vs_raw"] = expanded_vs_raw["delta"]
        if (
            expanded_vs_raw["delta"]["mean_ndcg@10"] > 0
            or expanded_vs_raw["delta"]["mean_recall@10"] > 0
        ):
            findings.append(
                "Expanded local context improved Jina over raw anchor chunks, indicating that weak reranker inputs were a major failure mode."
            )
        elif (
            expanded_vs_raw["delta"]["mean_ndcg@10"] < 0
            or expanded_vs_raw["delta"]["mean_recall@10"] < 0
        ):
            findings.append(
                "Expanded local context made Jina materially worse than raw anchors on this corpus, so naive context inflation is not a trustworthy reranker input default."
            )

    if best_local is not None and best_jina is not None:
        local_vs_jina = compare_reports(best_jina, best_local)
        evidence["best_local_vs_best_jina"] = local_vs_jina["delta"]
        if (
            local_vs_jina["delta"]["mean_ndcg@10"] > 0
            or local_vs_jina["delta"]["mean_recall@10"] > 0
        ):
            findings.append(
                "A local cross-encoder outperformed the configured Jina model on the same candidate pool, so the current Jina model is not the leading fit for this English finance corpus."
            )

    candidate_pool_gaps = [
        row for row in candidate_pool_rows
        if float(row.get("candidate_pool_recall") or 0.0) < 0.5
    ]
    if candidate_pool_gaps:
        findings.append(
            "Some golden evidence never entered the broad candidate pool, so reranking could not recover it; ingestion and chunk quality still bound the ceiling."
        )
        evidence["candidate_pool_gaps"] = candidate_pool_gaps[:5]

    return {
        "summary": " ".join(findings[:2]) if findings else "Jina diagnosis was inconclusive.",
        "findings": findings,
        "evidence": evidence,
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


def run_reranker_diagnosis(
    db: Session,
    *,
    top_k: int = 10,
    candidate_pool_size: int = 40,
    source_type: Optional[str] = None,
    include_cohere: bool = False,
    providers: Optional[list[str] | tuple[str, ...]] = None,
    input_modes: Optional[list[str] | tuple[str, ...]] = None,
    query_contains: Optional[str] = None,
    cache_path: Optional[str] = None,
) -> dict[str, Any]:
    golden_queries = load_golden_queries(db, source_type=source_type)
    if query_contains:
        needle = query_contains.strip().lower()
        golden_queries = [gq for gq in golden_queries if needle in gq.query_text.lower()]
    experiments = default_reranker_experiments(
        include_cohere=include_cohere,
        providers=providers,
        input_modes=input_modes,
    )
    experiments_by_label = {experiment.label: experiment for experiment in experiments}
    metric_rows: dict[str, list[PerQueryMetrics]] = {experiment.label: [] for experiment in experiments}
    per_query_rows: dict[str, list[dict[str, Any]]] = {experiment.label: [] for experiment in experiments}
    candidate_pool_rows: list[dict[str, Any]] = []
    reranker_cache = _load_reranker_cache(cache_path)

    for gq in golden_queries:
        try:
            bundle = _build_candidate_bundle(db, gq.query_text, candidate_pool_size=candidate_pool_size)
        except Exception as exc:
            log.warning("Candidate bundle failed for query %r: %s", gq.query_text[:80], exc)
            bundle = CandidateBundle(query_text=gq.query_text, intent=None)
        pool_row = _candidate_pool_row(gq, bundle)
        candidate_pool_rows.append(pool_row)

        for experiment in experiments:
            ranked_chunks, error = _rank_with_experiment(
                gq.query_text,
                bundle,
                experiment,
                top_k=top_k,
                reranker_cache=reranker_cache,
            )
            metric = _compute_per_query(
                gq,
                [str(getattr(chunk, "chunk_id")) for chunk in ranked_chunks],
            )
            metric_rows[experiment.label].append(metric)
            per_query_rows[experiment.label].append(
                {
                    **metric.as_dict(),
                    **pool_row,
                    "provider": experiment.provider,
                    "input_mode": experiment.input_mode,
                    "model": experiment.model,
                    "top_results": _chunk_briefs(ranked_chunks),
                    "error": error,
                }
            )

    scope_root = {
        "source_type": source_type,
        "candidate_pool_size": candidate_pool_size,
        "query_contains": query_contains,
        "providers": list(providers or []),
        "input_modes": list(input_modes or []),
        "cache_path": cache_path,
    }
    _save_reranker_cache(cache_path, reranker_cache)
    reports = {
        experiment.label: _build_eval_report(
            config_label=experiment.label,
            metrics=metric_rows[experiment.label],
            per_query_rows=per_query_rows[experiment.label],
            scope={**scope_root, "provider": experiment.provider, "input_mode": experiment.input_mode, "model": experiment.model},
        )
        for experiment in experiments
    }
    baseline_report = reports["baseline/heuristic"]
    candidate_reports = [
        report
        for label, report in reports.items()
        if label != "baseline/heuristic"
    ]
    rollout_policy = recommend_reranker_rollout(
        baseline_report,
        candidate_reports,
        experiments_by_label=experiments_by_label,
    )
    return {
        "baseline": baseline_report.as_dict(),
        "experiments": [
            {
                "label": experiment.label,
                "provider": experiment.provider,
                "input_mode": experiment.input_mode,
                "model": experiment.model,
                "report": reports[experiment.label].as_dict(),
            }
            for experiment in experiments
        ],
        "candidate_pool_summary": {
            "num_queries": len(candidate_pool_rows),
            "mean_candidate_pool_recall": round(
                _safe_mean([float(row.get("candidate_pool_recall") or 0.0) for row in candidate_pool_rows]),
                4,
            ),
            "mean_candidate_pool_high_recall": round(
                _safe_mean([float(row.get("candidate_pool_high_recall") or 0.0) for row in candidate_pool_rows]),
                4,
            ),
            "queries_with_pool_gaps": [
                row["query"]
                for row in candidate_pool_rows
                if float(row.get("candidate_pool_recall") or 0.0) < 0.5
            ],
        },
        "rollout_policy": rollout_policy,
        "jina_diagnosis": diagnose_jina_failure_mode(baseline_report, reports, candidate_pool_rows),
    }


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
