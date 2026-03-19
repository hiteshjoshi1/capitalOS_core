from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from langgraph.types import Command

from orchestration.graph import build_graph
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.services.persistence import get_checkpointer
from orchestration.services.restore import RestoreBootstrapService
from orchestration.services.state_io import StateIOService


STEP_ENTRYPOINT_MAP = {
    "prepare": "prepare",
    "plan": "plan",
    "build": "build",
    "agent-review": "agent_review",
    "rework": "rework_analysis",
    "ship": "ship",
}


RESUME_COMMANDS = {"resume", "approve-plan", "human-review"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangGraph orchestration CLI")
    parser.add_argument(
        "command",
        choices=[
            "prepare",
            "plan",
            "approve-plan",
            "build",
            "agent-review",
            "human-review",
            "rework",
            "ship",
            "all",
            "resume",
            "export-state",
            "import-state",
            "restore-state",
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
        requested_entrypoint=entrypoint,  # type: ignore[arg-type]
        execution_mode=mode,              # type: ignore[arg-type]
    )
    return {"pipeline": pipeline.model_dump(mode="json")}


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


def print_result(graph, config: dict[str, Any], result: Any) -> None:
    print(json.dumps(result, indent=2, default=str))

    snapshot = graph.get_state(config)
    if snapshot.interrupts:
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


def main() -> None:
    args = parse_args()
    repo_root = str(Path(args.repo_root).resolve())
    state_io = StateIOService(repo_root)

    checkpointer = get_checkpointer(args.db_path)
    graph = build_graph(checkpointer)
    config = {"configurable": {"thread_id": args.thread_id}}

    if args.command == "export-state":
        snapshot = graph.get_state(config)
        exported = state_io.export_state(
            args.thread_id,
            {
                "pipeline": snapshot.values.get("pipeline"),
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

    entrypoint = STEP_ENTRYPOINT_MAP[args.command]
    state = make_initial_state(args, entrypoint, "step")
    result = graph.invoke(state, config=config)
    print_result(graph, config, result)


if __name__ == "__main__":
    main()