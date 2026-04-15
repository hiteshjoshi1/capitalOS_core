from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from langgraph.types import Command

from orchestration.graph import build_graph
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.services.config import get_config
from orchestration.services.llm import (
    extract_latest_assistant_message,
    extract_structured_plan_output,
    find_latest_copilot_session,
)
from orchestration.services.persistence import get_checkpointer
from orchestration.services.restore import RestoreBootstrapService
from orchestration.services.state_io import StateIOService
from orchestration.services.task_markdown import TaskMarkdownService


STEP_ENTRYPOINT_MAP = {
    "prepare": "prepare",
    "plan": "plan",
    "build": "build",
    "agent-run": "agent_run",
    "deterministic-gates": "deterministic_gates",
    "agent-review": "agent_review",
    "rework": "rework_analysis",
    "ship": "ship",
}


RESUME_COMMANDS = {"resume", "approve-plan", "human-review"}
INTERACTIVE_COMMANDS = {"respond"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangGraph orchestration CLI")
    parser.add_argument(
        "command",
        choices=[
            "prepare",
            "plan",
            "approve-plan",
            "build",
            "agent-run",
            "deterministic-gates",
            "agent-review",
            "human-review",
            "rework",
            "ship",
            "all",
            "resume",
            "respond",
            "export-state",
            "import-state",
            "restore-state",
            "salvage-plan",
        ],
    )
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--issue-id")
    parser.add_argument("--slug")
    parser.add_argument("--title")
    parser.add_argument("--db-path", default=".task-flow/langgraph.sqlite")
    parser.add_argument("--resume-json")
    parser.add_argument("--state-file")
    parser.add_argument(
        "--restart-at",
        choices=[
            "prepare",
            "plan",
            "human_approval_gate",
            "build",
            "agent_review",
            "human_review",
            "rework_analysis",
            "rework_implementation",
            "agent_run",
            "deterministic_gates",
            "ship",
        ],
    )
    parser.add_argument(
        "--restore-mode",
        choices=["step", "workflow"],
        default="workflow",
    )
    return parser.parse_args()


def infer_issue_id(task_file: str) -> str:
    name = Path(task_file).name
    parts = name.removesuffix(".md").split("-")
    if len(parts) >= 3 and parts[0] == "issue" and parts[1].isdigit():
        return parts[1]
    return "0"


def infer_slug(task_file: str) -> str:
    name = Path(task_file).name.removesuffix(".md")
    parts = name.split("-")
    if len(parts) >= 3 and parts[0] == "issue" and parts[1].isdigit():
        return "-".join(parts[2:])
    return name


def infer_title(slug: str) -> str:
    return slug.replace("-", " ").title()


def make_initial_state(args: argparse.Namespace, entrypoint: str, mode: str) -> dict[str, Any]:
    issue_id = args.issue_id or infer_issue_id(args.task_file)
    slug = args.slug or infer_slug(args.task_file)
    title = args.title or infer_title(slug)
    repo_root = str(Path(args.repo_root).resolve())
    branch = f"feature/issue-{issue_id}-{slug}"

    issue = IssueMetadata(
        issue_id=issue_id,
        slug=slug,
        title=title,
        task_file=args.task_file,
        repo_root=repo_root,
        branch=branch,
    )

    pipeline = PipelineState(
        issue=issue,
        pipeline_version="v3",
        requested_entrypoint=entrypoint,  # type: ignore[arg-type]
        execution_mode=mode,              # type: ignore[arg-type]
    )
    return {"pipeline": pipeline.model_dump(mode="json")}


def load_existing_pipeline_state(graph, config: dict[str, Any]) -> PipelineState | None:
    history_fn = getattr(graph, "get_state_history", None)
    if callable(history_fn):
        for snapshot in history_fn(config):
            pipeline = _pipeline_from_snapshot(snapshot)
            if pipeline is not None and _is_usable_pipeline_state(pipeline):
                return pipeline

    snapshot = graph.get_state(config)
    pipeline = _pipeline_from_snapshot(snapshot)
    if pipeline is not None and _is_usable_pipeline_state(pipeline):
        return pipeline
    return None


def _pipeline_from_snapshot(snapshot: Any) -> PipelineState | None:
    values = getattr(snapshot, "values", None) or {}
    raw_pipeline = values.get("pipeline")
    if not raw_pipeline:
        return None
    return PipelineState.model_validate(raw_pipeline)


def _is_usable_pipeline_state(pipeline: PipelineState) -> bool:
    return any(
        [
            pipeline.prepare_result is not None,
            pipeline.plan_output is not None,
            pipeline.build_output is not None,
            bool(pipeline.review_cycles),
            bool(pipeline.rework_cycles),
            bool(pipeline.human_gate_decisions),
            pipeline.ship_result is not None,
            bool(pipeline.blockers),
            bool(pipeline.errors),
            bool(pipeline.retry_log),
            pipeline.current_stage not in {"dispatch"},
            pipeline.workflow_status != "not_started",
        ]
    )


def make_step_state(
    args: argparse.Namespace,
    entrypoint: str,
    graph,
    config: dict[str, Any],
) -> dict[str, Any]:
    existing = load_existing_pipeline_state(graph, config)
    if existing is None:
        return make_initial_state(args, entrypoint, "step")

    existing.requested_entrypoint = entrypoint  # type: ignore[assignment]
    existing.execution_mode = "step"  # type: ignore[assignment]
    return {"pipeline": existing.model_dump(mode="json")}


def parse_resume_payload(args: argparse.Namespace) -> dict[str, Any]:
    if not args.resume_json:
        raise SystemExit("--resume-json is required for this command")
    try:
        payload = json.loads(args.resume_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON passed to --resume-json: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("--resume-json must decode to a JSON object")
    return payload


def load_pending_interrupt(graph, config: dict[str, Any]) -> dict[str, Any]:
    snapshot = graph.get_state(config)
    if not snapshot.interrupts:
        raise SystemExit("No pending human interrupt for this thread.")
    return snapshot.interrupts[0].value


def _effective_stage_from_interrupts(interrupts: list[Any]) -> tuple[str | None, str | None]:
    if not interrupts:
        return None, None
    gate = interrupts[0].value.get("gate")
    if gate == "plan_approval":
        return "human_approval_gate", "waiting_for_human"
    if gate in {"human_review", "extra_files_approval"}:
        return "human_review", "waiting_for_human"
    if gate == "v3_high_risk_review":
        return "deterministic_gates", "waiting_for_human"
    return None, "waiting_for_human"


def _pipeline_with_interrupt_context(snapshot: Any) -> PipelineState | None:
    values = getattr(snapshot, "values", None) or {}
    raw_pipeline = values.get("pipeline")
    if not raw_pipeline:
        return None
    pipeline = PipelineState.model_validate(raw_pipeline)
    current_stage, workflow_status = _effective_stage_from_interrupts(list(snapshot.interrupts))
    if current_stage:
        pipeline.current_stage = current_stage  # type: ignore[assignment]
    if workflow_status:
        pipeline.workflow_status = workflow_status  # type: ignore[assignment]
    return pipeline


def _parse_list_input(raw: str) -> list[str]:
    return [item.strip() for item in raw.split("|") if item.strip()]


def _prompt_non_empty(label: str, input_fn: Callable[[str], str]) -> str:
    while True:
        value = input_fn(label).strip()
        if value:
            return value
        print("Value is required.")


def _prompt_decision(input_fn: Callable[[str], str]) -> str:
    while True:
        raw = input_fn("Approve? [y/N]: ").strip().lower()
        if raw in {"y", "yes"}:
            return "approved"
        if raw in {"", "n", "no"}:
            return "needs_fixes"
        print("Enter 'y' for approve or 'n' for needs_fixes.")


def build_interactive_resume_payload(
    interrupt: dict[str, Any],
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> dict[str, Any]:
    gate = interrupt.get("gate")
    if not gate:
        raise SystemExit("Pending interrupt does not include a gate name.")

    print_fn(f"Pending gate: {gate}")
    if gate == "plan_approval":
        summary = interrupt.get("plan_summary")
        if summary:
            print_fn(f"Plan summary: {summary}")
    elif gate == "extra_files_approval":
        files = interrupt.get("extra_changed_files") or []
        if files:
            print_fn("Extra files requiring approval:")
            for item in files:
                path = item.get("path", "")
                reason = item.get("reason") or "No reason recorded."
                print_fn(f"- {path}: {reason}")
    elif gate == "human_review":
        review_id = interrupt.get("review_id")
        agent_review = interrupt.get("agent_review") or {}
        if review_id:
            print_fn(f"Review cycle: {review_id}")
        if agent_review:
            print_fn(f"Agent decision: {agent_review.get('decision')}")
            print_fn(f"Agent summary: {agent_review.get('summary')}")
    elif gate == "build_retry_approval":
        retry_request = interrupt.get("retry_request") or {}
        print_fn(f"Retry summary: {retry_request.get('summary') or 'None'}")
        print_fn(
            f"Why more retries may help: {retry_request.get('why_more_retries_help') or 'None'}"
        )
        print_fn(
            f"Proposed new strategy: {retry_request.get('proposed_new_strategy') or 'None'}"
        )
        requested = retry_request.get("requested_retry_count") or 0
        print_fn(f"Requested additional retries: {requested}")
    elif gate == "v3_high_risk_review":
        findings = interrupt.get("findings") or []
        if findings:
            print_fn("High-risk findings:")
            for item in findings:
                print_fn(f"- {item}")

    decision = _prompt_decision(input_fn)
    reviewer = _prompt_non_empty("Reviewer name: ", input_fn)
    if decision == "needs_fixes":
        notes = _prompt_non_empty("Notes: ", input_fn)
    else:
        notes = input_fn("Notes: ").strip()
    questions = _parse_list_input(
        input_fn("Questions (optional, separate with ' | '): ").strip()
    )
    required_checks: list[str] = []
    response_requirements: list[str] = []
    unresolved_comments: list[str] = []
    approved_retry_count = 0
    if gate == "build_retry_approval" and decision == "approved":
        approved_retry_count = int(
            _prompt_non_empty("Approved additional retries: ", input_fn)
        )
    if decision == "needs_fixes":
        print_fn("What must be addressed before approval?")
        required_checks = _parse_list_input(
            input_fn(
                "Required check IDs for the next rework/review (optional, separate with ' | '): "
            ).strip()
        )
        response_requirements = _parse_list_input(
            input_fn(
                "Response requirements for the next rework/review (optional, separate with ' | '): "
            ).strip()
        )
        unresolved_comments = _parse_list_input(
            input_fn(
                "Unresolved comments to carry forward (optional, separate with ' | '): "
            ).strip()
        )

    payload = {
        "gate_type": gate,
        "decision": decision,
        "reviewer": reviewer,
        "notes": notes,
        "questions": questions,
        "required_checks": required_checks,
        "response_requirements": response_requirements,
        "unresolved_comments": unresolved_comments,
        "approved_retry_count": approved_retry_count,
    }
    return payload


def print_result(graph, config: dict[str, Any], result: Any) -> None:
    print(json.dumps(result, indent=2, default=str))

    snapshot = graph.get_state(config)
    summary: dict[str, Any] = {}
    pipeline = _pipeline_with_interrupt_context(snapshot)
    if pipeline:
        summary = {
            "current_stage": pipeline.current_stage,
            "workflow_status": pipeline.workflow_status,
        }
        if snapshot.next:
            summary["next_nodes"] = list(snapshot.next)
    if snapshot.interrupts:
        if summary:
            first_interrupt = snapshot.interrupts[0].value
            summary.update(
                {
                    "status": "interrupted",
                    "interrupt_gate": first_interrupt.get("gate"),
                    "message": f"Waiting for human input at `{first_interrupt.get('gate')}`.",
                }
            )
            print(json.dumps({"summary": summary}, indent=2, default=str))
        print(
            json.dumps(
                {
                    "status": "interrupted",
                    "interrupts": [interrupt.value for interrupt in snapshot.interrupts],
                },
                indent=2,
                default=str,
            )
        )
        return

    if summary:
        if pipeline.workflow_status == "shipped":
            summary.update({"status": "completed", "message": "Workflow shipped successfully."})
        elif pipeline.workflow_status == "blocked":
            summary.update({"status": "blocked", "message": "Workflow blocked. Check task markdown or blockers."})
        elif pipeline.workflow_status == "needs_fixes":
            summary.update(
                {
                    "status": "needs_fixes",
                    "message": "Workflow needs fixes before shipping. Check task markdown for required action.",
                }
            )
        else:
            summary.update(
                {
                    "status": "completed",
                    "message": f"Execution reached `{pipeline.current_stage}` with workflow status `{pipeline.workflow_status}`.",
                }
            )
        print(json.dumps({"summary": summary}, indent=2, default=str))


def main() -> None:
    args = parse_args()
    repo_root = str(Path(args.repo_root).resolve())
    state_io = StateIOService(repo_root)

    checkpointer = get_checkpointer(args.db_path)
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": args.thread_id}}

    if args.command == "export-state":
        snapshot = graph.get_state(config)
        pipeline = _pipeline_with_interrupt_context(snapshot)
        exported = state_io.export_state(
            args.thread_id,
            {
                "pipeline": pipeline.model_dump(mode="json") if pipeline is not None else snapshot.values.get("pipeline"),
                "next": snapshot.next,
                "interrupts": [i.value for i in snapshot.interrupts],
            },
        )
        print(json.dumps({"exported_to": exported}, indent=2))
        return

    if args.command == "import-state":
        if not args.state_file:
            raise SystemExit("--state-file is required for import-state")
        imported = state_io.import_state(args.state_file)
        print(json.dumps(imported, indent=2, default=str))
        return

    if args.command == "restore-state":
        if not args.state_file:
            raise SystemExit("--state-file is required for restore-state")
        if not args.restart_at:
            raise SystemExit("--restart-at is required for restore-state")

        imported = state_io.import_state(args.state_file)
        restored_state = RestoreBootstrapService.from_export(
            imported,
            restart_at=args.restart_at,
            execution_mode=args.restore_mode,
        )
        result = graph.invoke(restored_state, config=config)
        print_result(graph, config, result)
        return

    if args.command == "salvage-plan":
        pipeline = load_existing_pipeline_state(graph, config)
        if pipeline is None:
            pipeline = PipelineState.model_validate(make_initial_state(args, "prepare", "workflow")["pipeline"])

        cfg = get_config()
        events_path = find_latest_copilot_session(
            model=cfg.planner_model,
            repo_root=repo_root,
            branch=pipeline.issue.branch,
        )
        if events_path is None:
            raise SystemExit("Could not find a matching Copilot planner session to salvage.")

        assistant_content = extract_latest_assistant_message(events_path)
        if not assistant_content:
            raise SystemExit(f"Could not find a final assistant message in {events_path}.")

        md = TaskMarkdownService(repo_root)
        md.ensure_required_markers(args.task_file)
        task_markdown = md.read(args.task_file)
        plan = extract_structured_plan_output(assistant_content)
        plan.planner_model = cfg.planner_model
        plan.immutable_plan_hash = md.immutable_hash(task_markdown)

        pipeline.plan_output = plan
        pipeline.requested_entrypoint = "human_approval_gate"  # type: ignore[assignment]
        pipeline.execution_mode = "workflow"  # type: ignore[assignment]
        pipeline.current_stage = "dispatch"
        pipeline.workflow_status = "running"

        result = graph.invoke({"pipeline": pipeline.model_dump(mode="json")}, config=config)
        print_result(graph, config, result)
        return

    if args.command == "all":
        state = make_initial_state(args, "prepare", "workflow")
        result = graph.invoke(state, config=config)
        print_result(graph, config, result)
        return

    if args.command in RESUME_COMMANDS:
        payload = parse_resume_payload(args)
        result = graph.invoke(Command(resume=payload), config=config)
        print_result(graph, config, result)
        return

    if args.command in INTERACTIVE_COMMANDS:
        if not sys.stdin.isatty():
            raise SystemExit("Interactive respond command requires a TTY.")
        interrupt = load_pending_interrupt(graph, config)
        payload = build_interactive_resume_payload(interrupt)
        result = graph.invoke(Command(resume=payload), config=config)
        print_result(graph, config, result)
        return

    entrypoint = STEP_ENTRYPOINT_MAP[args.command]
    state = make_step_state(args, entrypoint, graph, config)
    result = graph.invoke(state, config=config)
    print_result(graph, config, result)


if __name__ == "__main__":
    main()
