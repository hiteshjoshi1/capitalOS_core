"""Deterministic drift checker for RAG eval reports.

This module compares two saved evaluation reports and emits aggregate,
per-query, and slice-level deltas in a stable JSON format.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable

AGGREGATE_METRICS = (
    "mean_ndcg@10",
    "mean_recall@10",
    "mean_precision@10",
    "mean_mrr",
)


def load_report(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if "per_query" in payload and "num_queries" in payload:
        return payload
    baseline = payload.get("baseline")
    if isinstance(baseline, dict) and "per_query" in baseline and "num_queries" in baseline:
        return baseline
    raise ValueError(f"Unsupported report payload shape: {path}")


def _query_rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in report.get("per_query", []):
        query = str(row.get("query", "")).strip()
        if query:
            rows[query] = row
    return rows


def aggregate_deltas(old: dict[str, Any], new: dict[str, Any]) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for metric in AGGREGATE_METRICS:
        deltas[metric] = round(float(new.get(metric, 0.0)) - float(old.get(metric, 0.0)), 4)
    return deltas


def changed_queries(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    old_rows = _query_rows(old)
    new_rows = _query_rows(new)
    out: list[dict[str, Any]] = []
    for query, old_row in old_rows.items():
        if query not in new_rows:
            continue
        new_row = new_rows[query]
        ndcg_delta = float(new_row.get("ndcg@10", 0.0)) - float(old_row.get("ndcg@10", 0.0))
        recall_delta = float(new_row.get("recall@10", 0.0)) - float(old_row.get("recall@10", 0.0))
        mrr_delta = float(new_row.get("mrr", 0.0)) - float(old_row.get("mrr", 0.0))
        if any(abs(value) > 1e-9 for value in (ndcg_delta, recall_delta, mrr_delta)):
            out.append(
                {
                    "query": query,
                    "delta": {
                        "ndcg@10": round(ndcg_delta, 4),
                        "recall@10": round(recall_delta, 4),
                        "mrr": round(mrr_delta, 4),
                    },
                    "retrieved_count": {
                        "old": int(old_row.get("retrieved_count", 0)),
                        "new": int(new_row.get("retrieved_count", 0)),
                    },
                }
            )
    out.sort(key=lambda row: (row["delta"]["ndcg@10"], row["delta"]["recall@10"], row["delta"]["mrr"]))
    return out


def _slice_rules() -> dict[str, Callable[[str], bool]]:
    return {
        "buffett": lambda q: "buffett" in q.lower(),
        "munger_mental_models": lambda q: ("munger" in q.lower()) or ("mental models" in q.lower()),
        "nick_sleep": lambda q: "nick sleep" in q.lower(),
    }


def _slice_avg(report: dict[str, Any], predicate: Callable[[str], bool]) -> tuple[float, float, float, int]:
    rows = [row for row in report.get("per_query", []) if predicate(str(row.get("query", "")))]
    n = len(rows)
    if n == 0:
        return (math.nan, math.nan, math.nan, 0)
    return (
        sum(float(row.get("ndcg@10", 0.0)) for row in rows) / n,
        sum(float(row.get("recall@10", 0.0)) for row in rows) / n,
        sum(float(row.get("mrr", 0.0)) for row in rows) / n,
        n,
    )


def slice_deltas(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name, predicate in _slice_rules().items():
        old_ndcg, old_recall, old_mrr, n = _slice_avg(old, predicate)
        new_ndcg, new_recall, new_mrr, _ = _slice_avg(new, predicate)
        if n == 0:
            out[name] = {"count": 0}
            continue
        out[name] = {
            "count": n,
            "old": {
                "ndcg@10": round(old_ndcg, 4),
                "recall@10": round(old_recall, 4),
                "mrr": round(old_mrr, 4),
            },
            "new": {
                "ndcg@10": round(new_ndcg, 4),
                "recall@10": round(new_recall, 4),
                "mrr": round(new_mrr, 4),
            },
            "delta": {
                "ndcg@10": round(new_ndcg - old_ndcg, 4),
                "recall@10": round(new_recall - old_recall, 4),
                "mrr": round(new_mrr - old_mrr, 4),
            },
        }
    return out


def drift_report(old: dict[str, Any], new: dict[str, Any], *, max_rows: int = 20) -> dict[str, Any]:
    changed = changed_queries(old, new)
    return {
        "old_config_label": old.get("config_label"),
        "new_config_label": new.get("config_label"),
        "aggregate_deltas": aggregate_deltas(old, new),
        "changed_queries": changed[: max(1, max_rows)],
        "changed_query_count": len(changed),
        "slice_deltas": slice_deltas(old, new),
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Deterministic drift checker for RAG eval reports")
    parser.add_argument("--old", required=True, help="Old/baseline report path")
    parser.add_argument("--new", required=True, help="New/candidate report path")
    parser.add_argument("--max-rows", type=int, default=20, help="Maximum changed query rows to print")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    old_report = load_report(Path(args.old))
    new_report = load_report(Path(args.new))
    print(json.dumps(drift_report(old_report, new_report, max_rows=args.max_rows), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
