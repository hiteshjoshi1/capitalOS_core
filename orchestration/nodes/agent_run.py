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
        pipeline.workflow_status = "blocked"
        pipeline.v3_permanent_failure_reason = f"agent_run failed: {exc}"
        pipeline.blockers.append(
            "V3 agent run failed before producing valid structured output."
        )
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
    expected_verification_commands = VerificationService.expected_commands_for_changed_files(
        pipeline.issue.repo_root,
        actual_changed_files,
    )
    reported_verification_commands = {
        item.command for item in output.verification_commands_run if item.command
    }
    integrity_failures: list[str] = []
    if sorted(actual_changed_files) != reported_changed_files:
        integrity_failures.append(
            "agent_run reported changed_files that do not match the actual git diff. "
            f"reported={reported_changed_files or ['<none>']} actual={actual_changed_files or ['<none>']}"
        )
    if output.semantic_intent_achieved and output.unresolved_failures:
        integrity_failures.append(
            "agent_run marked semantic intent achieved but still reported unresolved failures."
        )
    missing_verification_commands = [
        command for command in expected_verification_commands if command not in reported_verification_commands
    ]
    if output.semantic_intent_achieved and missing_verification_commands:
        integrity_failures.append(
            "agent_run did not report running all required relevant verification commands: "
            + ", ".join(missing_verification_commands)
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
