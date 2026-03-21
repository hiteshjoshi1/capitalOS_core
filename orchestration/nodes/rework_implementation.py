from __future__ import annotations

from orchestration.models.rework import ReworkImplementationResult
from orchestration.models.stage import PipelineStage
from orchestration.prompts.rework import build_rework_implementation_prompt
from orchestration.render import render_task_file
from orchestration.services.builder_fix import BuilderFixService
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.git import GitService
from orchestration.services.integrity import IntegrityService
from orchestration.services.llm import LLMService
from orchestration.services.verification import VerificationService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.REWORK_IMPLEMENTATION
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

    def fix_callback(name: str, command: str, exit_code: int, output: str) -> None:
        integrity.assert_matches_planned_hash(pipeline)
        fix_service.invoke_fix(
            label=name,
            command=command,
            exit_code=exit_code,
            output=output,
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
    impl.verification_summary = verification.summary

    for entry in retries:
        pipeline.add_retry(entry)

    allowed = {pipeline.issue.task_file, *cfg.allowed_aux_files}
    allowed.update(impl.changed_files)
    staged, blocked = git.stage_scoped_changes(allowed)

    if blocked:
        rework.status = "blocked"
        pipeline.blockers.append(
            f"Out-of-scope changed files detected during rework: {', '.join(blocked)}"
        )
    else:
        rework.status = "implementation_complete" if not verification.any_failures else "blocked"

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
