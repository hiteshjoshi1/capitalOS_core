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


def test_step_mode_plan_reaches_human_approval_gate(tmp_path: Path, monkeypatch):
    def fake_complete_structured(prompt, model_cls):
        if model_cls.__name__ != "PlanOutput":
            raise AssertionError(f"Unexpected model requested: {model_cls.__name__}")

        return model_cls(
            summary="Planned",
            architecture_decisions=["A"],
            risks=["R"],
            open_questions=[],
            acceptance_criteria=["AC1"],
            planned_paths=["orchestration/"],
            checklist=[],
        )

    monkeypatch.setattr(
        "orchestration.services.llm.LLMService.complete_structured",
        lambda self, prompt, model_cls: fake_complete_structured(prompt, model_cls),
    )

    task_file = make_task_file(tmp_path)
    graph = build_graph(InMemorySaver())

    config = {"configurable": {"thread_id": "issue-123-step-plan"}}
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
            "requested_entrypoint": "plan",
            "execution_mode": "step",
        }
    }

    graph.invoke(state, config=config)
    snapshot = graph.get_state(config)

    assert snapshot.interrupts, "Expected interrupt at plan approval in step mode"
    assert snapshot.interrupts[0].value["gate"] == "plan_approval"
    rendered = (tmp_path / task_file).read_text()
    assert "**Current Stage**: `human_approval_gate`" in rendered
    assert "**Workflow Status**: `waiting_for_human`" in rendered


def test_step_mode_plan_approval_continues_to_human_review(tmp_path: Path, monkeypatch):
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
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["orchestration/graph.py"],
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.stage_scoped_changes",
        lambda self, allowed_paths: (["orchestration/graph.py"], []),
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
    config = {"configurable": {"thread_id": "issue-123-step-plan-continue"}}
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
            "requested_entrypoint": "plan",
            "execution_mode": "step",
        }
    }

    graph.invoke(state, config=config)
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
    assert snapshot.interrupts
    assert snapshot.interrupts[0].value["gate"] == "human_review"
    rendered = (tmp_path / task_file).read_text()
    assert "**Current Stage**: `human_review`" in rendered
    assert "**Workflow Status**: `waiting_for_human`" in rendered


def test_workflow_extra_files_gate_then_returns_to_review(tmp_path: Path, monkeypatch):
    agent_review_calls = {"count": 0}

    def fake_complete_structured(prompt, model_cls):
        name = model_cls.__name__

        if name == "PlanOutput":
            return model_cls(
                summary="Planned",
                architecture_decisions=["A"],
                risks=["R"],
                open_questions=[],
                acceptance_criteria=["AC1"],
                planned_paths=["web/src/"],
                checklist=[],
            )

        if name == "BuildOutput":
            return model_cls(
                summary="Implemented feature and supporting workflow fix.",
                changed_files=["web/src/App.tsx", "orchestration/cli.py"],
                extra_changed_files=[
                    {
                        "path": "orchestration/cli.py",
                        "reason": "Workflow support change needed for resume handling.",
                        "reason_source": "builder",
                    }
                ],
                completed_checklist_item_ids=[],
                implementation_notes=["Updated UI and workflow support."],
            )

        if name == "AgentReview":
            agent_review_calls["count"] += 1
            return model_cls(
                review_id=f"R{agent_review_calls['count']}",
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
        lambda self: ["web/src/App.tsx", "orchestration/cli.py"],
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.stage_scoped_changes",
        lambda self, allowed_paths: (["web/src/App.tsx", "orchestration/cli.py"], []),
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

    config = {"configurable": {"thread_id": "issue-123-extra-files"}}
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
    assert snapshot.interrupts
    assert snapshot.interrupts[0].value["gate"] == "plan_approval"

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
    assert snapshot.interrupts
    assert snapshot.interrupts[0].value["gate"] == "human_review"
    assert snapshot.interrupts[0].value["extra_changed_files"][0]["path"] == "orchestration/cli.py"
    assert agent_review_calls["count"] == 1


def test_step_mode_extra_files_gate_then_next_review_accepts_approved_files(tmp_path: Path, monkeypatch):
    agent_review_calls = {"count": 0}

    def fake_complete_structured(prompt, model_cls):
        if model_cls.__name__ != "AgentReview":
            raise AssertionError(f"Unexpected model requested: {model_cls.__name__}")
        agent_review_calls["count"] += 1
        return model_cls(
            review_id=f"R{agent_review_calls['count']}",
            model_name="fake-reviewer",
            decision="approved",
            risk="low",
            summary="Looks good",
            findings=[],
            test_gaps=[],
            verification_considered=True,
        )

    monkeypatch.setattr(
        "orchestration.services.llm.LLMService.complete_structured",
        lambda self, prompt, model_cls: fake_complete_structured(prompt, model_cls),
    )
    monkeypatch.setattr(
        "orchestration.services.git.GitService.changed_files",
        lambda self: ["web/src/App.tsx", "orchestration/cli.py"],
    )
    monkeypatch.setattr(
        "orchestration.services.verification.VerificationService.run_default_suite",
        lambda self, max_attempts=1, on_code_retry_fix=None: (
            __import__("orchestration.models.verification", fromlist=["VerificationEvidence"]).VerificationEvidence(
                results=[
                    __import__("orchestration.models.verification", fromlist=["VerificationCommandResult"]).VerificationCommandResult(
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
        ),
    )

    task_file = make_task_file(tmp_path)
    graph = build_graph(InMemorySaver())
    config = {"configurable": {"thread_id": "issue-123-step-extra-files"}}
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
            "requested_entrypoint": "agent_review",
            "execution_mode": "step",
            "plan_output": {
                "summary": "Planned",
                "architecture_decisions": ["A"],
                "risks": ["R"],
                "open_questions": [],
                "acceptance_criteria": ["AC1"],
                "planned_paths": ["web/src/"],
                "checklist": [],
            },
            "build_output": {
                "summary": "Implemented feature and supporting workflow fix.",
                "changed_files": ["web/src/App.tsx", "orchestration/cli.py"],
                "extra_changed_files": [
                    {
                        "path": "orchestration/cli.py",
                        "reason": "Workflow support change needed for resume handling.",
                        "reason_source": "builder",
                    }
                ],
                "completed_checklist_item_ids": [],
                "implementation_notes": [],
            },
        }
    }

    graph.invoke(state, config=config)
    snapshot = graph.get_state(config)
    assert snapshot.interrupts
    assert snapshot.interrupts[0].value["gate"] == "human_review"
    assert snapshot.interrupts[0].value["extra_changed_files"][0]["path"] == "orchestration/cli.py"
    assert agent_review_calls["count"] == 1
