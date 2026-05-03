from __future__ import annotations

import json
from argparse import Namespace
from types import SimpleNamespace

import pytest

from orchestration import cli
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput


class _FakeGraph:
    def __init__(self, snapshot=None, invoke_result=None):
        self.snapshot = snapshot or SimpleNamespace(values={}, interrupts=[], next=())
        self.invoke_result = invoke_result if invoke_result is not None else {"ok": True}
        self.invocations = []

    def get_state(self, config):
        return self.snapshot

    def invoke(self, state, config=None):
        self.invocations.append((state, config))
        return self.invoke_result


def _pipeline() -> PipelineState:
    return PipelineState(
        issue=IssueMetadata(
            issue_id="123",
            slug="test",
            title="Test",
            task_file="tasks/issue-123-test.md",
            repo_root="/tmp/repo",
            branch="feature/issue-123-test",
        ),
        plan_output=PlanOutput(
            summary="Planned workflow",
            architecture_decisions=["A"],
            risks=["R"],
            open_questions=[],
            acceptance_criteria=["AC"],
            planned_paths=["orchestration/"],
            checklist=[],
        ),
        current_stage="build",
        workflow_status="running",
        execution_mode="step",
    )


def test_parse_args_parses_restore_mode_and_restart(monkeypatch):
    monkeypatch.setattr(
        "sys.argv",
        [
            "orch",
            "restore-state",
            "--thread-id",
            "issue-123",
            "--task-file",
            "tasks/issue-123-test.md",
            "--state-file",
            "state.json",
            "--restart-at",
            "rework_implementation",
            "--restore-mode",
            "step",
        ],
    )

    args = cli.parse_args()

    assert args.command == "restore-state"
    assert args.restart_at == "rework_implementation"
    assert args.restore_mode == "step"


def test_infer_helpers_cover_non_issue_names():
    assert cli.infer_issue_id("tasks/random.md") == "0"
    assert cli.infer_slug("tasks/random.md") == "random"
    assert cli.infer_title("risk-and-test") == "Risk And Test"


def test_parse_resume_payload_rejects_missing_invalid_and_non_object():
    with pytest.raises(SystemExit, match="--resume-json is required"):
        cli.parse_resume_payload(Namespace(resume_json=None))

    with pytest.raises(SystemExit, match="Invalid JSON"):
        cli.parse_resume_payload(Namespace(resume_json="{bad"))

    with pytest.raises(SystemExit, match="must decode to a JSON object"):
        cli.parse_resume_payload(Namespace(resume_json='["x"]'))


def test_effective_stage_from_interrupts_handles_none_and_unknown_gate():
    assert cli._effective_stage_from_interrupts([]) == (None, None)
    interrupt = [SimpleNamespace(value={"gate": "build_retry_approval"})]
    assert cli._effective_stage_from_interrupts(interrupt) == (None, "waiting_for_human")


def test_prompt_helpers_retry_until_valid(capsys):
    answers = iter(["", "  ok  "])
    assert cli._prompt_non_empty("Label: ", lambda _: next(answers)) == "ok"
    assert "Value is required." in capsys.readouterr().out

    decisions = iter(["maybe", "yes"])
    assert cli._prompt_decision(lambda _: next(decisions)) == "approved"
    assert "Enter 'y' for approve or 'n' for needs_fixes." in capsys.readouterr().out



def test_print_result_reports_interrupts_and_blocked_states(capsys):
    pipeline = _pipeline()
    blocked_pipeline = pipeline.model_copy(update={"workflow_status": "blocked"})
    interrupt_snapshot = SimpleNamespace(
        values={"pipeline": pipeline.model_dump(mode="json")},
        interrupts=[SimpleNamespace(value={"gate": "human_review"})],
        next=("human_review",),
    )
    blocked_snapshot = SimpleNamespace(
        values={"pipeline": blocked_pipeline.model_dump(mode="json")},
        interrupts=[],
        next=(),
    )

    cli.print_result(_FakeGraph(snapshot=interrupt_snapshot), {"configurable": {"thread_id": "x"}}, {"ok": True})
    interrupt_output = capsys.readouterr().out
    assert '"interrupt_gate": "human_review"' in interrupt_output
    assert '"status": "interrupted"' in interrupt_output

    cli.print_result(_FakeGraph(snapshot=blocked_snapshot), {"configurable": {"thread_id": "x"}}, {"ok": True})
    blocked_output = capsys.readouterr().out
    assert "Workflow blocked. Check task markdown or blockers." in blocked_output


def test_main_export_and_import_state(monkeypatch, capsys):
    snapshot = SimpleNamespace(values={"pipeline": _pipeline().model_dump(mode="json")}, interrupts=[], next=("n1",))
    graph = _FakeGraph(snapshot=snapshot)
    state_io_calls = []

    class FakeStateIO:
        def __init__(self, repo_root):
            self.repo_root = repo_root

        def export_state(self, thread_id, snapshot_payload):
            state_io_calls.append(("export", thread_id, snapshot_payload))
            return ".task-flow/exports/issue-123.json"

        def import_state(self, path):
            state_io_calls.append(("import", path))
            return {"pipeline": {"current_stage": "build"}}

    monkeypatch.setattr(cli, "StateIOService", FakeStateIO)
    monkeypatch.setattr(cli, "get_checkpointer", lambda _: object())
    monkeypatch.setattr(cli, "build_graph", lambda _: graph)

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: Namespace(
            command="export-state",
            thread_id="issue-123",
            repo_root=".",
            task_file="tasks/issue-123-test.md",
            issue_id=None,
            slug=None,
            title=None,
            db_path=".task-flow/langgraph.sqlite",
            resume_json=None,
            state_file=None,
            restart_at=None,
            restore_mode="workflow",
        ),
    )
    cli.main()
    assert state_io_calls[0][0] == "export"
    assert "exported_to" in capsys.readouterr().out

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: Namespace(
            command="import-state",
            thread_id="issue-123",
            repo_root=".",
            task_file="tasks/issue-123-test.md",
            issue_id=None,
            slug=None,
            title=None,
            db_path=".task-flow/langgraph.sqlite",
            resume_json=None,
            state_file="state.json",
            restart_at=None,
            restore_mode="workflow",
        ),
    )
    cli.main()
    assert state_io_calls[-1] == ("import", "state.json")
    assert '"current_stage": "build"' in capsys.readouterr().out


def test_main_restore_state_requires_inputs(monkeypatch):
    monkeypatch.setattr(cli, "parse_args", lambda: Namespace(
        command="restore-state",
        thread_id="issue-123",
        repo_root=".",
        task_file="tasks/issue-123-test.md",
        issue_id=None,
        slug=None,
        title=None,
        db_path=".task-flow/langgraph.sqlite",
        resume_json=None,
        state_file=None,
        restart_at=None,
        restore_mode="workflow",
    ))
    monkeypatch.setattr(cli, "StateIOService", lambda repo_root: object())
    monkeypatch.setattr(cli, "get_checkpointer", lambda _: object())
    monkeypatch.setattr(cli, "build_graph", lambda _: _FakeGraph())

    with pytest.raises(SystemExit, match="--state-file is required"):
        cli.main()


def test_main_restore_state_and_all_print_results(monkeypatch, capsys):
    snapshot = SimpleNamespace(values={"pipeline": _pipeline().model_dump(mode="json")}, interrupts=[], next=())
    graph = _FakeGraph(snapshot=snapshot, invoke_result={"restored": True})

    class FakeStateIO:
        def __init__(self, repo_root):
            pass

        def import_state(self, path):
            return {"pipeline": _pipeline().model_dump(mode="json")}

    monkeypatch.setattr(cli, "StateIOService", FakeStateIO)
    monkeypatch.setattr(cli, "get_checkpointer", lambda _: object())
    monkeypatch.setattr(cli, "build_graph", lambda _: graph)
    monkeypatch.setattr(cli, "RestoreBootstrapService", SimpleNamespace(from_export=lambda payload, restart_at, execution_mode: {"pipeline": {"current_stage": "dispatch"}}))

    printed = []
    monkeypatch.setattr(cli, "print_result", lambda graph, config, result: printed.append(result))

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: Namespace(
            command="restore-state",
            thread_id="issue-123",
            repo_root=".",
            task_file="tasks/issue-123-test.md",
            issue_id=None,
            slug=None,
            title=None,
            db_path=".task-flow/langgraph.sqlite",
            resume_json=None,
            state_file="state.json",
            restart_at="build",
            restore_mode="step",
        ),
    )
    cli.main()
    assert printed[-1] == {"restored": True}

    monkeypatch.setattr(
        cli,
        "parse_args",
        lambda: Namespace(
            command="all",
            thread_id="issue-123",
            repo_root=".",
            task_file="tasks/issue-123-test.md",
            issue_id=None,
            slug=None,
            title=None,
            db_path=".task-flow/langgraph.sqlite",
            resume_json=None,
            state_file=None,
            restart_at=None,
            restore_mode="workflow",
        ),
    )
    monkeypatch.setattr(cli, "make_initial_state", lambda args, entrypoint, mode: {"pipeline": {"requested_entrypoint": entrypoint, "execution_mode": mode}})
    cli.main()
    assert printed[-1] == {"restored": True}


def test_main_salvage_plan_success_and_errors(monkeypatch):
    pipeline = _pipeline()
    snapshot = SimpleNamespace(values={"pipeline": pipeline.model_dump(mode="json")}, interrupts=[], next=())
    graph = _FakeGraph(snapshot=snapshot, invoke_result={"salvaged": True})

    class FakeStateIO:
        def __init__(self, repo_root):
            pass

    class FakeMarkdown:
        def __init__(self, repo_root):
            pass

        def ensure_required_markers(self, task_file):
            return None

        def read(self, task_file):
            return "# task\n<!-- IMMUTABLE_PLAN_END -->\n"

        def immutable_hash(self, content):
            return "hash123"

    monkeypatch.setattr(cli, "StateIOService", FakeStateIO)
    monkeypatch.setattr(cli, "get_checkpointer", lambda _: object())
    monkeypatch.setattr(cli, "build_graph", lambda _: graph)
    monkeypatch.setattr(cli, "load_existing_pipeline_state", lambda graph, config: pipeline)
    monkeypatch.setattr(cli, "TaskMarkdownService", FakeMarkdown)
    monkeypatch.setattr(cli, "print_result", lambda graph, config, result: None)
    monkeypatch.setattr(cli, "get_config", lambda: SimpleNamespace(planner_model="planner-model"))

    args = Namespace(
        command="salvage-plan",
        thread_id="issue-123",
        repo_root=".",
        task_file="tasks/issue-123-test.md",
        issue_id=None,
        slug=None,
        title=None,
        db_path=".task-flow/langgraph.sqlite",
        resume_json=None,
        state_file=None,
        restart_at=None,
        restore_mode="workflow",
    )
    monkeypatch.setattr(cli, "parse_args", lambda: args)
    monkeypatch.setattr(cli, "find_latest_copilot_session", lambda **kwargs: None)
    with pytest.raises(SystemExit, match="Could not find a matching Copilot planner session"):
        cli.main()

    monkeypatch.setattr(cli, "find_latest_copilot_session", lambda **kwargs: "events.jsonl")
    monkeypatch.setattr(cli, "extract_latest_assistant_message", lambda path: "")
    with pytest.raises(SystemExit, match="Could not find a final assistant message"):
        cli.main()

    monkeypatch.setattr(cli, "extract_latest_assistant_message", lambda path: json.dumps(_pipeline().plan_output.model_dump(mode="json")))
    monkeypatch.setattr(cli, "extract_structured_plan_output", lambda raw: _pipeline().plan_output.model_copy(deep=True))
    cli.main()
    invoked_state, _ = graph.invocations[-1]
    assert invoked_state["pipeline"]["requested_entrypoint"] == "human_approval_gate"


def test_main_resume_interactive_and_step_paths(monkeypatch):
    snapshot = SimpleNamespace(values={"pipeline": _pipeline().model_dump(mode="json")}, interrupts=[], next=())
    graph = _FakeGraph(snapshot=snapshot, invoke_result={"done": True})

    class FakeStateIO:
        def __init__(self, repo_root):
            pass

    monkeypatch.setattr(cli, "StateIOService", FakeStateIO)
    monkeypatch.setattr(cli, "get_checkpointer", lambda _: object())
    monkeypatch.setattr(cli, "build_graph", lambda _: graph)
    monkeypatch.setattr(cli, "print_result", lambda graph, config, result: None)

    common = dict(
        thread_id="issue-123",
        repo_root=".",
        task_file="tasks/issue-123-test.md",
        issue_id=None,
        slug=None,
        title=None,
        db_path=".task-flow/langgraph.sqlite",
        state_file=None,
        restart_at=None,
        restore_mode="workflow",
    )

    monkeypatch.setattr(cli, "parse_args", lambda: Namespace(command="resume", resume_json='{"decision":"approved"}', **common))
    monkeypatch.setattr(cli, "parse_resume_payload", lambda args: {"decision": "approved"})
    cli.main()
    assert graph.invocations[-1][0].resume == {"decision": "approved"}

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli, "parse_args", lambda: Namespace(command="respond", resume_json=None, **common))
    with pytest.raises(SystemExit, match="requires a TTY"):
        cli.main()

    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli, "load_pending_interrupt", lambda graph, config: {"gate": "human_review"})
    monkeypatch.setattr(cli, "build_interactive_resume_payload", lambda interrupt: {"decision": "needs_fixes"})
    cli.main()
    assert graph.invocations[-1][0].resume == {"decision": "needs_fixes"}

    monkeypatch.setattr(cli, "parse_args", lambda: Namespace(command="build", resume_json=None, **common))
    monkeypatch.setattr(cli, "make_step_state", lambda args, entrypoint, graph, config: {"pipeline": {"requested_entrypoint": entrypoint}})
    cli.main()
    assert graph.invocations[-1][0] == {"pipeline": {"requested_entrypoint": "build"}}
