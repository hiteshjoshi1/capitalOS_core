from __future__ import annotations

import os

from orchestration.models.build import BuildOutput, BuildRetryRequest, ExtraChangedFile, RetryEntry
from orchestration.models.stage import PipelineStage
from orchestration.prompts.build import build_build_prompt, build_retry_request_prompt
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
    required_checklist_ids = {
        item.id
        for item in (pipeline.plan_output.checklist if pipeline.plan_output else [])
        if item.required and not item.human_only and not item.post_ship
    }
    completed_checklist_ids = set(build_output.completed_checklist_item_ids)
    missing_checklist_ids = sorted(required_checklist_ids - completed_checklist_ids)

    if planned_paths and not matched_paths:
        blockers.append(
            "Build validation failed: no files under the planned paths were changed."
        )

    if missing_checklist_ids:
        blockers.append(
            "Build validation failed: required checklist items were not completed: "
            + ", ".join(missing_checklist_ids)
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


def _request_build_retry_approval(
    *,
    pipeline,
    builder,
    build_output: BuildOutput,
    retries: list[RetryEntry],
) -> BuildRetryRequest:
    blockers = list(pipeline.blockers)
    try:
        request = builder.complete_structured(
            build_retry_request_prompt(
                pipeline,
                build_output=build_output,
                blockers=blockers,
                retries=retries,
            ),
            BuildRetryRequest,
        )
    except Exception as exc:
        return BuildRetryRequest(
            summary="Builder could not justify more retries and human guidance is required.",
            why_more_retries_help="",
            proposed_new_strategy="",
            latest_failures=blockers[-3:] if blockers else [str(exc)],
            requested_retry_count=0,
            valid_reason=False,
        )

    request.latest_failures = list(dict.fromkeys(request.latest_failures or blockers[-3:]))
    if request.valid_reason:
        if request.requested_retry_count <= 0 or not request.proposed_new_strategy.strip():
            request.valid_reason = False
    if not request.valid_reason:
        request.requested_retry_count = 0
    return request


def _base_scope_paths(pipeline, cfg) -> list[str]:
    return ScopePolicyService(pipeline).review_allowed_paths()


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


def _persist_blocked_build_exception(
    pipeline,
    *,
    exc: Exception,
    build_output: BuildOutput | None,
) -> GraphState:
    if build_output is not None and pipeline.build_output is None:
        try:
            git = GitService(pipeline.issue.repo_root)
            if not build_output.changed_files:
                build_output.changed_files = git.changed_files()
        except Exception:
            pass
        pipeline.build_output = build_output

    pipeline.workflow_status = "blocked"
    pipeline.blockers.append("Build stage crashed after repository changes may have been applied.")
    pipeline.errors.append(str(exc))
    render_task_file(pipeline)
    emit_stage_end(
        PipelineStage.BUILD,
        status="blocked",
        evidence=[
            f"builder_output_present={build_output is not None}",
            f"build_output_persisted={pipeline.build_output is not None}",
            f"blockers={len(pipeline.blockers)}",
            f"errors={len(pipeline.errors)}",
        ],
        conclusion="Build stage blocked because an exception escaped after build-side effects had already occurred.",
    )
    return dump_pipeline_state(pipeline)


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

    prior_build_output = pipeline.build_output.model_copy(deep=True) if pipeline.build_output else None
    prior_retry_entries = list(pipeline.retry_log)
    prior_build_blockers = [
        blocker for blocker in pipeline.blockers if pipeline.is_build_blocker(blocker)
    ]
    build_retry_decision = pipeline.human_gate_decisions.get("build_retry_approval")
    extra_retry_budget = 0
    if (
        prior_build_output is not None
        and prior_build_output.retry_request is not None
        and build_retry_decision is not None
        and build_retry_decision.decision == "approved"
    ):
        extra_retry_budget = build_retry_decision.approved_retry_count
    pipeline.reset_build_state()
    build_output: BuildOutput | None = None

    try:
        builder = LLMService(PipelineStage.BUILD, repo_root=pipeline.issue.repo_root)
        emit_progress(
            PipelineStage.BUILD,
            current_action="Requesting implementation from builder model",
            evidence=[f"model={cfg.builder_model}"],
            reasoning="Build generates repo changes before verification runs.",
        )
        try:
            build_output = builder.complete_structured(
                build_build_prompt(
                    pipeline,
                    prior_build_output=prior_build_output,
                    prior_retry_entries=prior_retry_entries,
                    prior_blockers=prior_build_blockers,
                ),
                BuildOutput,
            )
        except Exception as exc:
            pipeline.workflow_status = "blocked"
            pipeline.blockers.append("Builder failed before structured output was recorded.")
            pipeline.errors.append(str(exc))
            render_task_file(pipeline)
            emit_stage_end(
                PipelineStage.BUILD,
                status="blocked",
                evidence=["builder_output=missing", "verification_failures=unknown", "blockers=1"],
                conclusion="Build stage blocked because the builder failed before returning structured output.",
            )
            return dump_pipeline_state(pipeline)
        build_output.builder_model = cfg.builder_model
        emit_progress(
            PipelineStage.BUILD,
            current_action="Builder response received",
            evidence=[f"summary={build_output.summary[:160]}", f"implementation_notes={len(build_output.implementation_notes)}"],
        )

        fix_service = BuilderFixService(pipeline)

        def fix_callback(
            name: str,
            command: str,
            exit_code: int,
            output: str,
            prior_attempts: list[RetryEntry],
        ) -> None:
            fix_service.invoke_fix(
                label=name,
                command=command,
                exit_code=exit_code,
                output=output,
                prior_attempts=prior_attempts,
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
            max_attempts=cfg.max_retries + extra_retry_budget,
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
            build_output.retry_request = _request_build_retry_approval(
                pipeline=pipeline,
                builder=builder,
                build_output=build_output,
                retries=retries,
            )

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
    except Exception as exc:
        return _persist_blocked_build_exception(pipeline, exc=exc, build_output=build_output)
