from __future__ import annotations

from orchestration.models.agent_run import AgentRunOutput
from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.prompts.agent_run import build_agent_run_prompt
from orchestration.render import render_task_file
from orchestration.services.console import emit_progress, emit_stage_end, emit_stage_start
from orchestration.services.provider_runtime import ProviderRuntimeService
from orchestration.services.task_markdown import TaskMarkdownService
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
