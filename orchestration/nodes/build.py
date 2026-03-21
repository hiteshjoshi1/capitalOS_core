from __future__ import annotations

import os

from orchestration.models.build import BuildOutput, ExtraChangedFile
from orchestration.models.stage import PipelineStage
from orchestration.prompts.build import build_build_prompt
from orchestration.render import render_task_file
from orchestration.services.builder_fix import BuilderFixService
from orchestration.services.config import get_config
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.git import GitService
from orchestration.services.llm import LLMService
from orchestration.services.scope import ScopePolicyService
from orchestration.services.verification import VerificationService
from orchestration.state import GraphState, load_pipeline_state, dump_pipeline_state


def _path_matches_scope(path: str, scope: str) -> bool:
    normalized_path = path.strip()
    normalized_scope = scope.strip().rstrip("/")
    if not normalized_path or not normalized_scope:
        return False
    return normalized_path == normalized_scope or normalized_path.startswith(f"{normalized_scope}/")


def _changed_files_in_planned_paths(changed_files: list[str], planned_paths: list[str]) -> list[str]:
    return [
        path
        for path in changed_files
        if any(_path_matches_scope(path, scope) for scope in planned_paths)
    ]


def _claims_write_permission_restrictions(build_output: BuildOutput) -> bool:
    text = " ".join([build_output.summary, *build_output.implementation_notes]).lower()
    markers = (
        "filesystem write permission",
        "write permission restriction",
        "write permission restrictions",
        "permission restrictions",
        "read-only filesystem",
        "cannot write",
        "unable to write",
    )
    return any(marker in text for marker in markers)


def _validate_build_output(pipeline, build_output: BuildOutput) -> list[str]:
    blockers: list[str] = []
    planned_paths = pipeline.plan_output.allowed_paths() if pipeline.plan_output else []
    matched_paths = _changed_files_in_planned_paths(build_output.changed_files, planned_paths)

    if planned_paths and not matched_paths:
        blockers.append(
            "Build validation failed: no files under the planned paths were changed."
        )

    if _claims_write_permission_restrictions(build_output) and os.access(
        pipeline.issue.repo_root, os.W_OK | os.X_OK
    ):
        blockers.append(
            "Build validation failed: model reported filesystem write permission restrictions, "
            "but the repo root is writable."
        )

    return blockers


def _append_verification_failure_blockers(pipeline, retries) -> None:
    latest_retry_by_label = {}
    for entry in retries:
        latest_retry_by_label[entry.label] = entry

    for entry in latest_retry_by_label.values():
        if entry.classification == "infra" and entry.notes:
            pipeline.blockers.append(
                f"Infra verification failure on {entry.label}: {entry.notes}"
            )


def _base_scope_paths(pipeline, cfg) -> list[str]:
    allowed = {pipeline.issue.task_file, *cfg.allowed_aux_files}
    if pipeline.plan_output:
        allowed.update(pipeline.plan_output.allowed_paths())
    return sorted(path for path in allowed if path)


def _normalize_extra_changed_files(
    pipeline,
    cfg,
    changed_files: list[str],
    provided: list[ExtraChangedFile],
) -> list[ExtraChangedFile]:
    base_scope = _base_scope_paths(pipeline, cfg)
    scope = ScopePolicyService(pipeline)
    provided_by_path = {item.path: item for item in provided if item.path}
    extra_paths = sorted(
        path for path in changed_files
        if path and not ScopePolicyService.is_path_allowed(path, base_scope)
    )

    normalized: list[ExtraChangedFile] = []
    for path in extra_paths:
        item = provided_by_path.get(path)
        if item and item.reason.strip():
            normalized.append(item)
            continue
        normalized.append(scope.infer_extra_file_reason(path))
    return normalized


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.BUILD
    pipeline.workflow_status = "running"
    emit_stage_start(
        PipelineStage.BUILD,
        current_action="Running builder implementation and verification",
        evidence=[f"planned_paths={len(pipeline.plan_output.allowed_paths()) if pipeline.plan_output else 0}"],
    )

    cfg = get_config()
    decision = pipeline.human_gate_decisions.get("plan_approval")
    if not decision or decision.decision != "approved":
        raise RuntimeError("Build blocked: plan approval gate has not approved the plan.")

    pipeline.reset_build_state()

    builder = LLMService(PipelineStage.BUILD, repo_root=pipeline.issue.repo_root)
    emit_progress(
        PipelineStage.BUILD,
        current_action="Requesting implementation from builder model",
        evidence=[f"model={cfg.builder_model}"],
        reasoning="Build generates repo changes before verification runs.",
    )
    build_output = builder.complete_structured(build_build_prompt(pipeline), BuildOutput)
    build_output.builder_model = cfg.builder_model
    emit_progress(
        PipelineStage.BUILD,
        current_action="Builder response received",
        evidence=[f"summary={build_output.summary[:160]}", f"implementation_notes={len(build_output.implementation_notes)}"],
    )

    fix_service = BuilderFixService(pipeline)

    def fix_callback(name: str, command: str, exit_code: int, output: str) -> None:
        fix_service.invoke_fix(
            label=name,
            command=command,
            exit_code=exit_code,
            output=output,
        )

    verification_service = VerificationService(
        pipeline.issue.repo_root,
        stage=PipelineStage.BUILD.value,
    )
    emit_progress(
        PipelineStage.BUILD,
        current_action="Starting verification suite",
        evidence=["suite=lint,typecheck,api-rebuild,test-backend,test-frontend,api-smoke,e2e"],
        reasoning="Verification determines whether the build output is usable and reviewable.",
    )
    verification, retries = verification_service.run_default_suite(
        max_attempts=cfg.max_retries,
        on_code_retry_fix=fix_callback,
    )
    build_output.verification = verification

    git = GitService(pipeline.issue.repo_root)
    build_output.changed_files = git.changed_files()
    build_output.extra_changed_files = _normalize_extra_changed_files(
        pipeline,
        cfg,
        build_output.changed_files,
        build_output.extra_changed_files,
    )
    pipeline.build_output = build_output
    emit_progress(
        PipelineStage.BUILD,
        current_action="Collected changed file inventory",
        evidence=[f"changed_files={len(build_output.changed_files)}", f"extra_changed_files={len(build_output.extra_changed_files)}"],
        reasoning="The build records which files changed so review can assess scope and feature coverage.",
    )

    for entry in retries:
        pipeline.add_retry(entry)

    allowed = {pipeline.issue.task_file, *cfg.allowed_aux_files}
    allowed.update(build_output.changed_files)
    staged, blocked = git.stage_scoped_changes(allowed)

    build_failed = False

    if blocked:
        # Review owns approval of extra files. Build records context but does not fail solely on scope.
        pass

    validation_blockers = _validate_build_output(pipeline, build_output)
    for blocker in validation_blockers:
        pipeline.blockers.append(blocker)
    if validation_blockers:
        build_failed = True

    if verification.any_failures:
        _append_verification_failure_blockers(pipeline, retries)
        pipeline.blockers.append("Verification suite failed during build.")
        build_failed = True

    if build_failed:
        pipeline.workflow_status = "blocked"

    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.BUILD,
        status=pipeline.workflow_status,
        evidence=[
            f"verification_failures={verification.any_failures}",
            f"blockers={len(pipeline.blockers)}",
            f"changed_files={len(build_output.changed_files)}",
        ],
        conclusion="Build stage finished and the task file was updated with build evidence.",
    )
    return dump_pipeline_state(pipeline)
