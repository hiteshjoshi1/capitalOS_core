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

## How To Test
- Run `make orch-test` and confirm this mocked flow passes.

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


def _mock_unified_pipeline(monkeypatch, tmp_path, *, risk_flags=None):
    """Set up mocks for the unified pipeline: prepare -> agent_run -> deterministic_gates."""
    from orchestration.models.agent_run import AgentRunOutput
    from orchestration.services.provider_runtime import ProviderRunResult

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
            risk_flags=risk_flags or [],
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

    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.ScopePolicyService.review_allowed_paths",
        lambda self: ["orchestration/"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.V3PolicyService.evaluate",
        lambda self, changed_files, allowed_paths, extra_changed_files: type(
            "R", (), {"blocked": False, "blockers": [], "extra_files_with_reasons": []}
        )(),
    )


def test_plan_interrupt_and_resume(tmp_path: Path, monkeypatch):
    """Unified pipeline: prepare -> agent_run -> deterministic_gates -> waiting_for_human."""
    _mock_unified_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.get_config",
        lambda: type("Cfg", (), {
            "max_retries": 3,
            "require_pre_ship_human_on_high_risk": False,
        })(),
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
    pipeline = snapshot.values.get("pipeline", {})
    # Unified pipeline ends at deterministic_gates with waiting_for_human
    assert pipeline["workflow_status"] == "waiting_for_human"


def test_step_mode_plan_reaches_human_approval_gate(tmp_path: Path, monkeypatch):
    """In unified pipeline, plan entry routes to agent_run -> deterministic_gates."""
    _mock_unified_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.get_config",
        lambda: type("Cfg", (), {
            "max_retries": 3,
            "require_pre_ship_human_on_high_risk": False,
        })(),
    )

    def fake_llm(self, prompt, model_cls):
        if model_cls.__name__ == "PlanOutput":
            return model_cls(
                summary="Planned",
                architecture_decisions=["A"],
                risks=["R"],
                open_questions=[],
                acceptance_criteria=["AC1"],
                planned_paths=["orchestration/"],
                checklist=[],
            )
        raise AssertionError(f"Unexpected model: {model_cls.__name__}")

    monkeypatch.setattr(
        "orchestration.services.llm.LLMService.complete_structured",
        fake_llm,
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
    pipeline = snapshot.values.get("pipeline", {})
    # Plan routes to agent_run in unified pipeline
    assert pipeline["workflow_status"] == "waiting_for_human"


def test_step_mode_plan_approval_continues_to_human_review(tmp_path: Path, monkeypatch):
    """In unified pipeline, plan entry flows through agent_run to deterministic_gates."""
    _mock_unified_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.get_config",
        lambda: type("Cfg", (), {
            "max_retries": 3,
            "require_pre_ship_human_on_high_risk": False,
        })(),
    )

    def fake_llm(self, prompt, model_cls):
        if model_cls.__name__ == "PlanOutput":
            return model_cls(
                summary="Planned",
                architecture_decisions=["A"],
                risks=["R"],
                open_questions=[],
                acceptance_criteria=["AC1"],
                planned_paths=["orchestration/"],
                checklist=[],
            )
        raise AssertionError(f"Unexpected model: {model_cls.__name__}")

    monkeypatch.setattr(
        "orchestration.services.llm.LLMService.complete_structured",
        fake_llm,
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
    snapshot = graph.get_state(config)
    pipeline = snapshot.values.get("pipeline", {})
    assert pipeline["workflow_status"] == "waiting_for_human"
    assert pipeline["current_stage"] == "deterministic_gates"


def test_workflow_extra_files_gate_then_returns_to_review(tmp_path: Path, monkeypatch):
    """Unified pipeline handles extra changed files via policy in deterministic_gates."""
    from orchestration.models.agent_run import AgentRunOutput
    from orchestration.services.provider_runtime import ProviderRunResult

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

    def fake_complete_structured(self, prompt, model_cls):
        return AgentRunOutput(
            summary="Implemented feature and supporting workflow fix.",
            plan_summary="Add feature",
            architecture_decisions=["A"],
            risks=[],
            open_questions=[],
            acceptance_criteria=["AC1"],
            planned_paths=["web/src/"],
            checklist=[],
            changed_files=["web/src/App.tsx", "orchestration/cli.py"],
            extra_changed_files=[
                {
                    "path": "orchestration/cli.py",
                    "reason": "Workflow support change needed for resume handling.",
                    "reason_source": "builder",
                }
            ],
            implementation_notes=["Updated UI and workflow support."],
            verification_commands_run=[
                {"command": "make lint", "status": "pass", "evidence": "ok"},
            ],
            unresolved_failures=[],
            acceptance_criteria_checks=[
                {"criterion": "AC1", "status": "pass", "evidence": "ok"},
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

    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.get_config",
        lambda: type("Cfg", (), {
            "max_retries": 3,
            "require_pre_ship_human_on_high_risk": False,
        })(),
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.ScopePolicyService.review_allowed_paths",
        lambda self: ["web/src/"],
    )
    monkeypatch.setattr(
        "orchestration.nodes.deterministic_gates.V3PolicyService.evaluate",
        lambda self, changed_files, allowed_paths, extra_changed_files: type(
            "R", (), {"blocked": False, "blockers": [], "extra_files_with_reasons": []}
        )(),
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
    pipeline = snapshot.values.get("pipeline", {})
    assert pipeline["workflow_status"] == "waiting_for_human"
    assert pipeline["agent_run_output"] is not None
