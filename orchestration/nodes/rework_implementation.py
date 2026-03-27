from __future__ import annotations

from orchestration.models.rework import ReworkImplementationResult
from orchestration.models.review import ReviewCycle
from orchestration.models.stage import PipelineStage
from orchestration.prompts.rework import build_rework_implementation_prompt
from orchestration.render import render_task_file
from orchestration.models.build import RetryEntry
from orchestration.services.builder_fix import BuilderFixService
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.git import GitService
from orchestration.services.integrity import IntegrityService
from orchestration.services.llm import LLMService
from orchestration.services.scope import ScopePolicyService
from orchestration.services.verification import VerificationService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def _append_verification_failure_blockers(pipeline, verification) -> None:
    failed_checks = [result.name for result in verification.results if result.status == "fail"]
    if not failed_checks:
        return
    pipeline.blockers.append(
        "Verification suite failed during rework: " + ", ".join(failed_checks)
    )


def _rework_primary_objective(pipeline, rework) -> str:
    source_cycle = pipeline.get_review_cycle(rework.source_review_id if rework else None)
    human_review = source_cycle.human_review if source_cycle else None
    review = source_cycle.escalation_review or source_cycle.agent_review if source_cycle else None

    objective_parts: list[str] = []
    if human_review and human_review.notes:
        objective_parts.append(f"Human review notes: {human_review.notes.strip()}")
    if human_review and human_review.response_requirements:
        objective_parts.append(
            "Human response requirements: "
            + "; ".join(item for item in human_review.response_requirements if item.strip())
        )
    if human_review and human_review.unresolved_comments:
        objective_parts.append(
            "Human unresolved comments: "
            + "; ".join(item for item in human_review.unresolved_comments if item.strip())
        )
    if review and review.findings:
        objective_parts.append(
            "Reviewer findings: " + "; ".join(item for item in review.findings if item.strip())
        )
    if not objective_parts:
        objective_parts.append(
            "Implement the active rework findings in planned application files before chasing verification fallout."
        )
    return " ".join(objective_parts)


def _record_scope_gate_review(pipeline, rework, blocked_paths: list[str]) -> None:
    existing = pipeline.get_active_review_cycle()
    extra_changed_files = [
        ScopePolicyService(pipeline).infer_extra_file_reason(path)
        for path in blocked_paths
    ]

    if (
        existing
        and existing.source == "rework"
        and existing.source_rework_cycle_id == rework.rework_cycle_id
        and existing.status == "scope_gate_pending"
    ):
        existing.extra_changed_files = extra_changed_files
        return

    review_id = pipeline.next_review_id()
    cycle = ReviewCycle(
        review_id=review_id,
        source="rework",
        source_rework_cycle_id=rework.rework_cycle_id,
        extra_changed_files=extra_changed_files,
        status="scope_gate_pending",
    )
    pipeline.review_cycles.append(cycle)
    pipeline.active_review_cycle_id = review_id


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.REWORK_IMPLEMENTATION.value
    pipeline.workflow_status = "running"

    cfg = get_config()
    integrity = IntegrityService(pipeline.issue.repo_root)
    integrity.assert_matches_planned_hash(pipeline)

    rework = pipeline.get_active_rework_cycle()
    if not rework or not rework.analysis:
        raise RuntimeError("Cannot implement rework without an active rework analysis.")
    emit_stage_start(
        PipelineStage.REWORK_IMPLEMENTATION,
        current_action="Applying rework changes and rerunning verification",
        evidence=[
            f"rework_id={rework.rework_cycle_id}",
            f"source_review_id={rework.source_review_id}",
            f"planned_changes={len(rework.analysis.planned_changes)}",
        ],
    )

    emit_progress(
        PipelineStage.REWORK_IMPLEMENTATION,
        current_action="Requesting rework implementation from model",
        evidence=[f"model={cfg.builder_model}", f"rework_id={rework.rework_cycle_id}"],
        reasoning="The implementation step should modify the repo to address the specific review findings in the active rework cycle.",
    )
    impl = LLMService(
        PipelineStage.REWORK_IMPLEMENTATION,
        repo_root=pipeline.issue.repo_root,
    ).complete_structured(
        build_rework_implementation_prompt(pipeline),
        ReworkImplementationResult,
    )
    impl.rework_cycle_id = rework.rework_cycle_id
    impl.review_id = rework.source_review_id

    fix_service = BuilderFixService(pipeline)
    scope_policy = ScopePolicyService(pipeline)
    primary_objective = _rework_primary_objective(pipeline, rework)

    def fix_callback(
        name: str,
        command: str,
        exit_code: int,
        output: str,
        prior_attempts: list[RetryEntry],
    ) -> None:
        integrity.assert_matches_planned_hash(pipeline)
        fix_service.invoke_fix(
            label=name,
            command=command,
            exit_code=exit_code,
            output=output,
            prior_attempts=prior_attempts,
            allowed_paths=scope_policy.rework_autofix_allowed_paths(impl.changed_files),
            primary_objective=primary_objective,
        )
        integrity.assert_matches_planned_hash(pipeline)

    git = GitService(pipeline.issue.repo_root)
    impl.changed_files = git.changed_files()
    emit_progress(
        PipelineStage.REWORK_IMPLEMENTATION,
        current_action="Collected changed files after rework implementation",
        evidence=[f"changed_files={len(impl.changed_files)}"],
    )

    emit_progress(
        PipelineStage.REWORK_IMPLEMENTATION,
        current_action="Starting verification suite for rework",
        evidence=["suite=lint,typecheck,api-rebuild,test-backend,test-frontend,api-smoke,e2e"],
    )
    verification, retries = VerificationService(
        pipeline.issue.repo_root,
        stage=PipelineStage.REWORK_IMPLEMENTATION.value,
    ).run_default_suite(
        max_attempts=cfg.max_retries,
        on_code_retry_fix=fix_callback,
    )
    impl.verification = verification
    impl.verification_summary = verification.summary
    impl.changed_files = git.changed_files()

    for entry in retries:
        pipeline.add_retry(entry)

    allowed = set(scope_policy.rework_autofix_allowed_paths([]))
    staged, blocked = git.stage_scoped_changes(allowed)

    if blocked:
        rework.status = "blocked"
        pipeline.workflow_status = "blocked"
        pipeline.blockers.append(
            f"Out-of-scope changed files detected during rework: {', '.join(blocked)}"
        )
        _record_scope_gate_review(pipeline, rework, blocked)
    else:
        rework.status = "implementation_complete" if not verification.any_failures else "blocked"
        if verification.any_failures:
            pipeline.workflow_status = "blocked"
            _append_verification_failure_blockers(pipeline, verification)

    rework.implementation = impl
    integrity.assert_matches_planned_hash(pipeline)
    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.REWORK_IMPLEMENTATION,
        status=rework.status,
        evidence=[
            f"rework_id={rework.rework_cycle_id}",
            f"verification_failures={verification.any_failures}",
            f"retries={len(retries)}",
        ],
        conclusion=impl.summary,
    )
    return dump_pipeline_state(pipeline)
