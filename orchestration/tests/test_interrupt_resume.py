from __future__ import annotations

from pathlib import Path

from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver

from orchestration.graph import build_graph


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


def test_plan_interrupt_and_resume(tmp_path: Path, monkeypatch):
    def fake_complete_structured(prompt, model_cls):
        name = model_cls.__name__

        if name == "PlanOutput":
            return model_cls(
                summary="Planned",
                architecture_decisions=["A"],
                risks=["R"],
                open_questions=[],
                acceptance_criteria=["AC1"],
                planned_paths=["orchestration/"],
                checklist=[],
            )

        if name == "BuildOutput":
            return model_cls(
                summary="Implemented feature",
                changed_files=["orchestration/graph.py"],
                completed_checklist_item_ids=[],
                implementation_notes=["Graph added"],
            )

        if name == "AgentReview":
            return model_cls(
                review_id="R1",
                model_name="fake-reviewer",
                decision="approved",
                risk="low",
                summary="Looks good",
                findings=[],
                test_gaps=[],
                verification_considered=True,
            )

        raise AssertionError(f"Unexpected model requested: {name}")

    monkeypatch.setattr(
        "orchestration.services.llm.LLMService.complete_structured",
        lambda self, prompt, model_cls: fake_complete_structured(prompt, model_cls),
    )

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

    def fake_run_default_suite(self, max_attempts=3, on_code_retry_fix=None):
        from orchestration.models.verification import (
            VerificationEvidence,
            VerificationCommandResult,
        )

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

    task_file = make_task_file(tmp_path)
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

    graph.invoke(state, config=config)
    snapshot = graph.get_state(config)
    assert snapshot.interrupts, "Expected interrupt at human approval gate"

    graph.invoke(
        Command(
            resume={
                "gate_type": "plan_approval",
                "decision": "approved",
                "reviewer": "Hitesh",
                "notes": "ok",
                "questions": [],
                "response_requirements": [],
                "unresolved_comments": [],
            }
        ),
        config=config,
    )

    snapshot = graph.get_state(config)
    assert snapshot.interrupts, "Expected interrupt at human review after resume"