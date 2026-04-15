from __future__ import annotations

from orchestration.models.agent_run import AgentRunOutput
from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.prompts.agent_run import build_agent_run_prompt
from orchestration.render import render_task_file
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.git import GitService
from orchestration.services.provider_runtime import ProviderRuntimeService
from orchestration.services.task_markdown import TaskMarkdownService
from orchestration.services.verification import VerificationService
from orchestration.services.v3_policy import V3PolicyService
from orchestration.state import GraphState, dump_pipeline_state, load_pipeline_state


def _plan_from_agent_output(state, output, immutable_hash: str | None) -> PlanOutput:
    planner_model = state.plan_output.planner_model if state.plan_output else None
    return PlanOutput(
        summary=output.plan_summary or output.summary,
        architecture_decisions=output.architecture_decisions,
        risks=output.risks,
        open_questions=output.open_questions,
        acceptance_criteria=output.acceptance_criteria,
        checklist=output.checklist,
        planned_paths=output.planned_paths,
        immutable_plan_hash=immutable_hash,
        planner_model=planner_model,
    )


def run(state: GraphState) -> GraphState:
    pipeline = load_pipeline_state(state)
    pipeline.current_stage = PipelineStage.AGENT_RUN.value
    pipeline.workflow_status = "running"
    emit_stage_start(
        PipelineStage.AGENT_RUN,
        current_action="Executing single-session implementation run",
        evidence=[f"task={pipeline.issue.task_file}", f"attempt={pipeline.v3_agent_run_attempts + 1}"],
    )

    pipeline.v3_agent_run_attempts += 1
    pipeline.blockers = []
    pipeline.errors = []
    pipeline.v3_permanent_failure_reason = None

    runtime = ProviderRuntimeService(PipelineStage.AGENT_RUN, repo_root=pipeline.issue.repo_root)
    markdown = TaskMarkdownService(pipeline.issue.repo_root)
    markdown.ensure_required_markers(pipeline.issue.task_file)
    immutable_hash = markdown.immutable_hash(markdown.read(pipeline.issue.task_file))
    try:
        output, run_result = runtime.complete_structured(
            build_agent_run_prompt(pipeline),
            model_cls=AgentRunOutput,
        )
    except Exception as exc:  # noqa: BLE001
        exc_str = str(exc)
        if "subprocess failed" in exc_str or "stalled" in exc_str:
            blocker = "V3 agent run: provider subprocess failed or stalled before completing."
        elif "malformed structured output" in exc_str:
            blocker = "V3 agent run completed work but failed to produce valid JSON output (repair also failed)."
        else:
            blocker = "V3 agent run failed before producing valid structured output."
        pipeline.workflow_status = "blocked"
        pipeline.v3_permanent_failure_reason = f"agent_run failed: {exc}"
        pipeline.blockers.append(blocker)
        pipeline.errors.append(str(exc))
        render_task_file(pipeline)
        emit_stage_end(
            PipelineStage.AGENT_RUN,
            status="blocked",
            evidence=[f"attempt={pipeline.v3_agent_run_attempts}"],
            conclusion="V3 agent_run failed and the workflow is blocked.",
        )
        return dump_pipeline_state(pipeline)

    output.provider = run_result.provider
    output.model_name = run_result.model
    git = GitService(pipeline.issue.repo_root)
    actual_changed_files = git.changed_files()
    reported_changed_files = sorted({path for path in output.changed_files if path})
    task_file = pipeline.issue.task_file
    normalized_actual_changed_files = sorted(
        path for path in actual_changed_files
        if path and path != task_file
    )
    normalized_reported_changed_files = sorted(
        path for path in reported_changed_files
        if path and path != task_file
    )

    # ---- integrity checks ----
    # 1. Changed-files policy: block only if restricted files were modified (.env, fixtures, .gitignore).
    #    All other changes are allowed — the model may touch files it didn't predict.
    # 2. Semantic contradiction: intent_achieved=True with non-empty unresolved_failures.
    #
    # Verification coverage is NOT gated here. The model is instructed to run the full
    # suite and report results, but whether it actually ran every required command is
    # verified by deterministic_gates, which re-runs the real suite independently.
    integrity_failures: list[str] = []

    # Policy check: block restricted files
    policy = V3PolicyService(pipeline.issue.repo_root)
    non_task_actual = [p for p in actual_changed_files if p and p != task_file]
    for path in non_task_actual:
        restricted = policy._restricted_path(path)
        if restricted:
            integrity_failures.append(restricted)

    # Log mismatch as warning, not a blocker — the model can touch files it didn't plan
    if normalized_actual_changed_files != normalized_reported_changed_files:
        emit_progress(
            PipelineStage.AGENT_RUN,
            current_action="Warning: model-reported changed_files differ from actual git diff",
            evidence=[
                f"reported={normalized_reported_changed_files or ['<none>']}",
                f"actual={normalized_actual_changed_files or ['<none>']}",
                "using actual git changed files as source of truth",
            ],
        )

    if output.semantic_intent_achieved and output.unresolved_failures:
        integrity_failures.append(
            "agent_run marked semantic intent achieved but still reported unresolved failures."
        )

    # Emit a non-blocking warning if the model omitted expected verification commands —
    # deterministic_gates will re-run and will be the authority on pass/fail.
    expected_verification_commands = VerificationService.expected_commands_for_default_suite(
        pipeline.issue.repo_root,
    )
    reported_verification_commands = {
        item.command for item in output.verification_commands_run if item.command
    }
    missing_verification_commands = [
        command for command in expected_verification_commands if command not in reported_verification_commands
    ]
    if missing_verification_commands:
        emit_progress(
            PipelineStage.AGENT_RUN,
            current_action="Warning: model did not report running all expected verification commands",
            evidence=[
                f"missing={missing_verification_commands}",
                "deterministic_gates will rerun the full suite independently",
            ],
        )
    if integrity_failures:
        pipeline.workflow_status = "blocked"
        pipeline.v3_permanent_failure_reason = integrity_failures[0]
        pipeline.blockers.extend(integrity_failures)
        pipeline.errors.extend(integrity_failures)
        render_task_file(pipeline)
        emit_stage_end(
            PipelineStage.AGENT_RUN,
            status="blocked",
            evidence=[
                f"attempt={pipeline.v3_agent_run_attempts}",
                f"actual_changed_files={len(actual_changed_files)}",
                f"reported_changed_files={len(reported_changed_files)}",
            ],
            conclusion="V3 agent_run output failed repo-integrity checks and the workflow is blocked.",
        )
        return dump_pipeline_state(pipeline)
    output.changed_files = actual_changed_files
    pipeline.v3_provider = run_result.provider
    pipeline.v3_model = run_result.model
    pipeline.agent_run_output = output
    pipeline.plan_output = _plan_from_agent_output(pipeline, output, immutable_hash)
    pipeline.workflow_status = "running"

    render_task_file(pipeline)
    emit_progress(
        PipelineStage.AGENT_RUN,
        current_action="Structured output accepted and persisted",
        evidence=[
            f"provider={run_result.provider}",
            f"model={run_result.model}",
            f"changed_files={len(output.changed_files)}",
            f"semantic_intent_achieved={output.semantic_intent_achieved}",
        ],
    )
    emit_stage_end(
        PipelineStage.AGENT_RUN,
        status="completed",
        evidence=[f"attempt={pipeline.v3_agent_run_attempts}"],
        conclusion="V3 agent_run completed successfully.",
    )
    return dump_pipeline_state(pipeline)
