from __future__ import annotations

import hashlib
import json

from orchestration.models.review import AgentReview, ReviewCycle
from orchestration.models.stage import PipelineStage
from orchestration.prompts.review import build_review_prompt
from orchestration.render import render_task_file
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.git import GitService
from orchestration.services.llm import LLMService
from orchestration.services.scope import ScopePolicyService
from orchestration.services.verification import VerificationService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def _agent_review_input_fingerprint(
    *,
    source: str,
    source_rework_cycle_id: str | None,
    changed_files: list[str],
    verification_summary: str | None,
    verification_failures: list[str],
    extra_paths: list[str],
) -> str:
    payload = {
        "source": source,
        "source_rework_cycle_id": source_rework_cycle_id,
        "changed_files": sorted(changed_files),
        "verification_summary": verification_summary or "",
        "verification_failures": sorted(verification_failures),
        "extra_paths": sorted(extra_paths),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _deterministic_review(
    *,
    review_id: str,
    model_name: str,
    summary: str,
    findings: list[str],
    risk: str = "medium",
) -> AgentReview:
    return AgentReview(
        review_id=review_id,
        model_name=model_name,
        decision="needs_fixes",
        risk=risk,  # type: ignore[arg-type]
        summary=summary,
        findings=findings,
        test_gaps=[],
        verification_considered=True,
    )


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.AGENT_REVIEW
    pipeline.workflow_status = "running"

    cfg = get_config()
    review_id = pipeline.next_review_id()
    source = "rework" if pipeline.active_rework_cycle_id else "build"
    emit_stage_start(
        PipelineStage.AGENT_REVIEW,
        current_action="Reviewing implementation output",
        evidence=[f"review_id={review_id}", f"source={source}"],
    )
    scope = ScopePolicyService(pipeline)
    git = GitService(pipeline.issue.repo_root)
    changed_files = git.changed_files()
    emit_progress(
        PipelineStage.AGENT_REVIEW,
        current_action="Collected changed files for scope and review analysis",
        evidence=[f"changed_files={len(changed_files)}"],
    )
    pending_extra_paths = scope.find_unapproved_extra_files(changed_files)
    extra_changed_files = []
    if pending_extra_paths:
        known_extra = {}
        if pipeline.build_output:
            known_extra = {
                item.path: item
                for item in pipeline.build_output.extra_changed_files
                if item.path
            }
        extra_changed_files = [
            known_extra.get(path) or scope.infer_extra_file_reason(path)
            for path in pending_extra_paths
        ]
    source_verification = pipeline.get_review_source_verification()
    verification_failures = [
        f"{result.name}: exit {result.exit_code}"
        for result in (source_verification.results if source_verification else [])
        if result.status == "fail"
    ]
    input_fingerprint = _agent_review_input_fingerprint(
        source=source,
        source_rework_cycle_id=pipeline.active_rework_cycle_id,
        changed_files=changed_files,
        verification_summary=source_verification.summary if source_verification else None,
        verification_failures=verification_failures,
        extra_paths=pending_extra_paths,
    )
    existing_cycle = pipeline.get_active_review_cycle()

    if (
        existing_cycle
        and existing_cycle.input_fingerprint == input_fingerprint
        and existing_cycle.source == source
        and existing_cycle.source_rework_cycle_id == pipeline.active_rework_cycle_id
        and existing_cycle.agent_review is not None
    ):
        emit_progress(
            PipelineStage.AGENT_REVIEW,
            current_action="Reusing existing agent review for identical inputs",
            evidence=[f"review_id={existing_cycle.review_id}"],
            reasoning="The stage re-entered without any effective input change, so the prior persisted review is reused.",
        )
        return dump_pipeline_state(pipeline)

    emit_progress(
        PipelineStage.AGENT_REVIEW,
        current_action="Rerunning deterministic verification before review",
        evidence=[f"review_id={review_id}", "max_attempts=1"],
        reasoning="Fresh verification ensures review decisions are based on current repo state rather than only on earlier build evidence.",
    )
    review_verification, _ = VerificationService(
        pipeline.issue.repo_root,
        stage=PipelineStage.AGENT_REVIEW.value,
    ).run_default_suite(max_attempts=1, on_code_retry_fix=None)
    review_verification_failures = [
        f"{result.name}: exit {result.exit_code}"
        for result in review_verification.results
        if result.status == "fail"
    ]

    if verification_failures or review_verification_failures:
        agent_review = _deterministic_review(
            review_id=review_id,
            model_name="deterministic-gate",
            summary=(
                "Deterministic verification failures are present, so review cannot approve. "
                "Skipping reviewer model call until verification is green."
            ),
            findings=[
                "Verification failed before review: "
                + ", ".join(verification_failures + review_verification_failures)
            ],
        )
        cycle = ReviewCycle(
            review_id=review_id,
            source=source,
            source_rework_cycle_id=pipeline.active_rework_cycle_id,
            input_fingerprint=input_fingerprint,
            agent_review=agent_review,
            review_verification=review_verification,
            extra_changed_files=extra_changed_files,
            status="needs_fixes",
        )
        pipeline.review_cycles.append(cycle)
        pipeline.active_review_cycle_id = review_id
        render_task_file(pipeline)
        emit_stage_end(
            PipelineStage.AGENT_REVIEW,
            status=cycle.status,
            evidence=[
                f"review_id={review_id}",
                "mode=deterministic",
                f"verification_failures={len(verification_failures) + len(review_verification_failures)}",
            ],
            conclusion=agent_review.summary,
        )
        return dump_pipeline_state(pipeline)

    unresolved_required_checks = pipeline.get_unresolved_required_checks()
    if unresolved_required_checks:
        agent_review = _deterministic_review(
            review_id=review_id,
            model_name="deterministic-gate",
            summary=(
                "Required checks from the prior human review are still unresolved, so review cannot approve. "
                "Skipping reviewer model call until those checks are explicitly cleared."
            ),
            findings=[
                "Unresolved required checks: " + ", ".join(unresolved_required_checks)
            ],
        )
        cycle = ReviewCycle(
            review_id=review_id,
            source=source,
            source_rework_cycle_id=pipeline.active_rework_cycle_id,
            input_fingerprint=input_fingerprint,
            agent_review=agent_review,
            review_verification=review_verification,
            extra_changed_files=extra_changed_files,
            status="needs_fixes",
        )
        pipeline.review_cycles.append(cycle)
        pipeline.active_review_cycle_id = review_id
        render_task_file(pipeline)
        emit_stage_end(
            PipelineStage.AGENT_REVIEW,
            status=cycle.status,
            evidence=[
                f"review_id={review_id}",
                "mode=deterministic",
                f"required_checks={len(unresolved_required_checks)}",
            ],
            conclusion=agent_review.summary,
        )
        return dump_pipeline_state(pipeline)

    reviewer = LLMService(PipelineStage.AGENT_REVIEW)
    emit_progress(
        PipelineStage.AGENT_REVIEW,
        current_action="Requesting primary review decision",
        evidence=[f"model={cfg.reviewer_model}", f"review_id={review_id}"],
        reasoning="The reviewer checks correctness, scope, and test coverage before the workflow can proceed.",
    )
    agent_review = reviewer.complete_structured(
        build_review_prompt(
            pipeline,
            verification_summary=review_verification.summary,
            pending_extra_files=extra_changed_files,
        ),
        AgentReview,
    )
    agent_review.review_id = review_id
    agent_review.model_name = cfg.reviewer_model

    if pipeline.build_output and pipeline.build_output.verification and pipeline.build_output.verification.any_failures:
        agent_review.decision = "needs_fixes"
        if agent_review.risk == "low":
            agent_review.risk = "medium"
        agent_review.summary = (
            agent_review.summary + " Verification failures present, so review cannot approve."
        ).strip()

    cycle = ReviewCycle(
        review_id=review_id,
        source=source,
        source_rework_cycle_id=pipeline.active_rework_cycle_id,
        input_fingerprint=input_fingerprint,
        agent_review=agent_review,
        review_verification=review_verification,
        extra_changed_files=extra_changed_files,
        status="in_review" if agent_review.decision == "escalate" else (
            "approved" if agent_review.decision == "approved" else "needs_fixes"
        ),
    )

    pipeline.review_cycles.append(cycle)
    pipeline.active_review_cycle_id = review_id

    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.AGENT_REVIEW,
        status=cycle.status,
        evidence=[
            f"review_id={review_id}",
            f"decision={agent_review.decision}",
            f"risk={agent_review.risk}",
            f"findings={len(agent_review.findings)}",
            f"test_gaps={len(agent_review.test_gaps)}",
        ],
        conclusion=agent_review.summary,
    )
    return dump_pipeline_state(pipeline)
