from __future__ import annotations

from pathlib import Path

from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver

from orchestration.graph import build_graph
from orchestration.services.persistence import get_checkpointer


def make_task_file(tmp_path: Path) -> str:
    repo_root = tmp_path
    tasks_dir = repo_root / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    task_file = tasks_dir / "issue-123-test.md"
    task_file.write_text(
        """# Issue 123: Test

## Objective
- Test objective

## Architecture Decisions
- Test decision

## Acceptance Criteria
- Test acceptance criteria

## Human Approval Gate
- [ ] Approved for implementation

<!-- IMMUTABLE_PLAN_END -->

<!-- MACHINE_RENDERED_START -->
## Execution Journal
_Not rendered yet._
<!-- MACHINE_RENDERED_END -->
"""
    )
    return str(task_file.relative_to(repo_root))


def test_full_e2e_happy_path(tmp_path: Path, monkeypatch):
    """Unified pipeline e2e: prepare → agent_run → deterministic_gates → ship."""
    task_file = make_task_file(tmp_path)

    monkeypatch.setattr(
        "orchestration.services.git.GitService.ensure_clean_worktree_except",
        lambda self, allowed_paths: None,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.checkout_main_and_prepare_branch",
        lambda self, branch, base_branch="main": None,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["orchestration/graph.py"],
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.stage_scoped_changes",
        lambda self, allowed_paths: (["orchestration/graph.py"], []),
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.add",
        lambda self, *paths: None,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.commit_if_needed",
        lambda self, message: True,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.push",
        lambda self, branch: None,
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.current_branch",
        lambda self: "feature/issue-123-test",
    )

    # Mock the unified pipeline provider runtime (agent_run uses ProviderRuntimeService)
    from orchestration.models.agent_run import AgentRunOutput
    from orchestration.services.provider_runtime import ProviderRunResult

    def fake_complete_structured(self, prompt, model_cls):
        return AgentRunOutput(
            summary="Implemented feature",
            plan_summary="Add graph support",
            architecture_decisions=["Use LangGraph"],
            risks=["Low"],
            open_questions=[],
            acceptance_criteria=["Workflow runs"],
            planned_paths=["orchestration/"],
            checklist=[],
            changed_files=["orchestration/graph.py"],
            extra_changed_files=[],
            implementation_notes=["Graph added"],
            verification_commands_run=[
                {"command": "make lint", "status": "pass", "evidence": "ok"},
            ],
            unresolved_failures=[],
            acceptance_criteria_checks=[
                {"criterion": "Workflow runs", "status": "pass", "evidence": "ok"},
            ],
            semantic_intent_achieved=True,
            risk_flags=[],
        ), ProviderRunResult(
            provider="copilot",
            model="gpt-5.3-codex",
            output="{}",
            diagnostics=[],
        )

    monkeypatch.setattr(
        "orchestration.nodes.agent_run.ProviderRuntimeService.complete_structured",
        fake_complete_structured,
    )

    def fake_run_default_suite(self, max_attempts=3, on_code_retry_fix=None):
        from orchestration.models.verification import VerificationEvidence, VerificationCommandResult
        return (
            VerificationEvidence(
                results=[
                    VerificationCommandResult(
                        name="lint",
                        command="make lint",
                        status="pass",
                        exit_code=0,
                        output_excerpt="ok",
                    )
                ],
                any_failures=False,
            ),
            [],
        )

    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        fake_run_default_suite,
    )

    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.get_config",
        lambda: type("Cfg", (), {
            "max_retries": 3,
            "require_pre_ship_human_on_high_risk": False,
        })(),
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.ScopePolicyService.review_allowed_paths",
        lambda self: ["orchestration/"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.V3PolicyService.evaluate",
        lambda self, changed_files, allowed_paths, extra_changed_files: type("R", (), {"blocked": False, "blockers": [], "extra_files_with_reasons": []})(),
    )

    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "issue-123"}}

    state = {
        "pipeline": {
            "issue": {
                "issue_id": "123",
                "slug": "test",
                "title": "Test",
                "task_file": task_file,
                "repo_root": str(tmp_path),
                "branch": "feature/issue-123-test",
                "created_at": "2026-03-18T00:00:00Z",
            },
            "requested_entrypoint": "prepare",
            "execution_mode": "workflow",
        }
    }

    # Run the graph — should go prepare → agent_run → deterministic_gates → interrupt (waiting_for_human)
    graph.invoke(state, config=config)

    snapshot = graph.get_state(config)
    # Unified pipeline ends at deterministic_gates with waiting_for_human (no interrupt in happy path since
    # require_pre_ship_human_on_high_risk=False and no risk flags — pipeline ends with __end__)
    pipeline = snapshot.values.get("pipeline", {})
    if snapshot.interrupts:
        # If interrupted, resume with approval
        result = graph.invoke(
            Command(
                resume={
                    "gate_type": "v3_high_risk_review",
                    "decision": "approved",
                    "reviewer": "Hitesh",
                    "notes": "ship it",
                    "questions": [],
                    "response_requirements": [],
                    "unresolved_comments": [],
                }
            ),
            config=config,
        )
        pipeline = result["pipeline"]

    # The unified pipeline sets waiting_for_human after deterministic_gates pass.
    # Ship must be triggered manually via task-ship.
    assert pipeline["workflow_status"] == "waiting_for_human"
    assert pipeline["current_stage"] == "deterministic_gates"