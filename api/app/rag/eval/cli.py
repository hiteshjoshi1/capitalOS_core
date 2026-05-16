"""
CLI entry point for the RAG evaluation harness.

Usage (via make targets):
  python -m app.rag.eval.cli run
  python -m app.rag.eval.cli compare --a dense_only --b hybrid
  python -m app.rag.eval.cli seed --file data/fixtures/rag_golden_queries.yaml

Exit codes:
  0  — evaluation passed thresholds (or no thresholds configured)
  1  — one or more metrics dropped below configured thresholds
  2  — no golden queries found
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click

from app.db.session import SessionLocal
from app.rag.eval.runner import EvalReport, compare_reports, run_evaluation

log = logging.getLogger(__name__)


def _ndcg_threshold() -> float:
    return float(os.getenv("RAG_EVAL_NDCG_THRESHOLD", "0.0"))


def _recall_threshold() -> float:
    return float(os.getenv("RAG_EVAL_RECALL_THRESHOLD", "0.0"))


def _check_thresholds(report: EvalReport) -> bool:
    """Return True if the report passes all configured thresholds."""
    ndcg_min = _ndcg_threshold()
    recall_min = _recall_threshold()
    if ndcg_min > 0 and report.mean_ndcg_at_10 < ndcg_min:
        click.echo(
            f"FAIL: mean_ndcg@10={report.mean_ndcg_at_10:.4f} < threshold={ndcg_min}",
            err=True,
        )
        return False
    if recall_min > 0 and report.mean_recall_at_10 < recall_min:
        click.echo(
            f"FAIL: mean_recall@10={report.mean_recall_at_10:.4f} < threshold={recall_min}",
            err=True,
        )
        return False
    return True


def _load_report(path: str) -> EvalReport:
    payload = json.loads(Path(path).read_text())
    return EvalReport.from_dict(payload)


@click.group()
def cli() -> None:
    """RAG retrieval evaluation harness."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")


@cli.command()
@click.option("--label", default="current", show_default=True, help="Config label for this run.")
@click.option("--top-k", default=10, show_default=True, help="Number of chunks to retrieve per query.")
@click.option(
    "--source-type",
    type=click.Choice(["html", "pdf", "text", "manual"], case_sensitive=False),
    default=None,
    help="Restrict evaluation to golden evidence backed by this source type.",
)
@click.option("--output", type=click.Path(), default=None, help="Write JSON report to this file.")
def run(label: str, top_k: int, source_type: Optional[str], output: Optional[str]) -> None:
    """Run offline evaluation against the golden dataset."""
    db = SessionLocal()
    try:
        report = run_evaluation(db, config_label=label, top_k=top_k, source_type=source_type)
    finally:
        db.close()

    if report.num_queries == 0:
        scope_note = f" for source_type={source_type}" if source_type else ""
        click.echo(
            f"No golden queries found{scope_note}. Seed the dataset with: make rag-eval-seed",
            err=True,
        )
        sys.exit(2)

    payload = json.dumps(report.as_dict(), indent=2)
    click.echo(payload)

    if output:
        Path(output).write_text(payload)
        click.echo(f"Report written to {output}", err=True)

    if not _check_thresholds(report):
        sys.exit(1)


@cli.command()
@click.option("--a", "label_a", required=True, help="Label for configuration A.")
@click.option("--b", "label_b", required=True, help="Label for configuration B.")
@click.option("--top-k", default=10, show_default=True)
@click.option(
    "--source-type",
    type=click.Choice(["html", "pdf", "text", "manual"], case_sensitive=False),
    default=None,
    help="Restrict both evaluation runs to golden evidence backed by this source type.",
)
@click.option(
    "--fail-on-regression/--no-fail-on-regression",
    default=False,
    show_default=True,
    help="Exit non-zero when the no-regression bar is not met.",
)
def compare(label_a: str, label_b: str, top_k: int, source_type: Optional[str], fail_on_regression: bool) -> None:
    """Compare two retrieval configurations on the golden dataset."""
    db = SessionLocal()
    try:
        report_a = run_evaluation(db, config_label=label_a, top_k=top_k, source_type=source_type)
        report_b = run_evaluation(db, config_label=label_b, top_k=top_k, source_type=source_type)
    finally:
        db.close()

    comparison = compare_reports(report_a, report_b)
    click.echo(json.dumps(comparison, indent=2))
    if fail_on_regression and not comparison["passes_no_regression_bar"]:
        sys.exit(1)


@cli.command()
@click.option("--baseline-report", required=True, type=click.Path(exists=True), help="Path to a saved baseline JSON report.")
@click.option("--label", default="current", show_default=True, help="Config label for the current run.")
@click.option("--top-k", default=10, show_default=True, help="Number of chunks to retrieve per query.")
@click.option(
    "--source-type",
    type=click.Choice(["html", "pdf", "text", "manual"], case_sensitive=False),
    default=None,
    help="Restrict the candidate evaluation to golden evidence backed by this source type.",
)
def gate(baseline_report: str, label: str, top_k: int, source_type: Optional[str]) -> None:
    """Compare the current corpus against a saved baseline and fail on regression."""
    baseline = _load_report(baseline_report)
    db = SessionLocal()
    try:
        current = run_evaluation(db, config_label=label, top_k=top_k, source_type=source_type)
    finally:
        db.close()

    if baseline.num_queries == 0 or current.num_queries == 0:
        click.echo("Baseline or current evaluation report has no golden queries.", err=True)
        sys.exit(2)

    if baseline.scope and current.scope and baseline.scope != current.scope:
        click.echo(
            f"Baseline scope {baseline.scope} does not match current scope {current.scope}.",
            err=True,
        )
        sys.exit(1)

    comparison = compare_reports(baseline, current)
    comparison["baseline_report"] = baseline_report
    click.echo(json.dumps(comparison, indent=2))
    if not comparison["passes_no_regression_bar"]:
        sys.exit(1)


@cli.command()
@click.option(
    "--file",
    "fixture_file",
    default="data/fixtures/rag_golden_queries.yaml",
    show_default=True,
    help="Path to YAML fixture file.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Validate fixture without writing to DB.")
def seed(fixture_file: str, dry_run: bool) -> None:
    """Seed the golden dataset from a YAML fixture file."""
    import yaml

    path = Path(fixture_file)
    if not path.exists():
        click.echo(f"Fixture file not found: {path}", err=True)
        sys.exit(1)

    data = yaml.safe_load(path.read_text())
    entries = data if isinstance(data, list) else data.get("golden_queries", [])
    click.echo(f"Loaded {len(entries)} golden query entries from {path}")

    if dry_run:
        click.echo("Dry-run mode: no DB writes.")
        return

    from app.db.session import SessionLocal
    from app.models.rag import RagChunk, RagDocument, RagSource, RagEvalGolden

    db = SessionLocal()
    inserted = 0
    skipped = 0
    try:
        for entry in entries:
            query_text = entry["query"]
            for passage in entry.get("relevant_chunks", []):
                doc_external_id = passage.get("doc_external_id", "")
                chunk_indices = passage.get("chunk_index", [])
                if isinstance(chunk_indices, int):
                    chunk_indices = [chunk_indices]
                relevance = passage.get("relevance", 1)

                # Resolve chunk IDs via doc_external_id (stored in source URL or hash field)
                # and chunk_index. Gracefully skip entries when chunks don't exist yet.
                for idx in chunk_indices:
                    chunk = (
                        db.query(RagChunk)
                        .join(RagDocument, RagChunk.document_id == RagDocument.id)
                        .join(RagSource, RagDocument.source_id == RagSource.id)
                        .filter(
                            RagSource.url.contains(doc_external_id),
                            RagChunk.chunk_index == idx,
                        )
                        .first()
                    )
                    if chunk is None:
                        log.warning(
                            "Chunk not found: doc=%s index=%d — skipping", doc_external_id, idx
                        )
                        skipped += 1
                        continue

                    existing = (
                        db.query(RagEvalGolden)
                        .filter(
                            RagEvalGolden.query_text == query_text,
                            RagEvalGolden.chunk_id == str(chunk.id),
                        )
                        .first()
                    )
                    if existing:
                        existing.relevance_grade = relevance
                    else:
                        db.add(
                            RagEvalGolden(
                                query_text=query_text,
                                chunk_id=str(chunk.id),
                                relevance_grade=relevance,
                                notes=f"seeded from {path.name}",
                            )
                        )
                    inserted += 1

        db.commit()
        click.echo(f"Seeded {inserted} golden pairs ({skipped} skipped — chunks not yet ingested).")
    except Exception as exc:
        db.rollback()
        click.echo(f"Seeding failed: {exc}", err=True)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    cli()
