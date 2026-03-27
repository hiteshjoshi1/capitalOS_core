from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestration.models.build import BuildOutput, RetryEntry
from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.models.rework import ReworkCycle, ReworkImplementationResult
from orchestration.services.builder_fix import BuilderFixService


def _state() -> PipelineState:
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
            summary="plan",
            architecture_decisions=[],
            risks=[],
            open_questions=[],
            acceptance_criteria=[],
            planned_paths=["web/src", "orchestration"],
            checklist=[],
        ),
    )


def test_invoke_fix_builds_prompt_with_prior_attempts_and_allowed_paths(monkeypatch):
    state = _state()
    state.build_output = BuildOutput(summary="build", changed_files=["web/src/App.tsx"])
    state.rework_cycles.append(
        ReworkCycle(
            rework_cycle_id="W1",
            source_review_id="R1",
            implementation=ReworkImplementationResult(
                rework_cycle_id="W1",
                review_id="R1",
                summary="impl",
                changed_files=["orchestration/render.py"],
            ),
            status="implementation_complete",
        )
    )
    state.active_rework_cycle_id = "W1"

    monkeypatch.setattr(
        "orchestration.services.builder_fix.get_config",
        lambda: SimpleNamespace(
            builder_model="gpt-5.3-codex",
            build_max_autopilot_continues=7,
        ),
    )
    monkeypatch.setattr(
        "orchestration.services.builder_fix.ScopePolicyService.allowed_paths",
        lambda self: ["tasks/issue-123-test.md", "api/app"],
    )

    calls = []

    def fake_run(args, cwd, capture_output, text):
        calls.append((args, cwd))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("orchestration.services.builder_fix.subprocess.run", fake_run)

    BuilderFixService(state).invoke_fix(
        label="test-frontend",
        command="make test-frontend",
        exit_code=2,
        output="TestingLibraryElementError",
        prior_attempts=[
            RetryEntry(
                label="test-frontend",
                attempt=1,
                max_attempts=3,
                command="make test-frontend",
                exit_code=2,
                classification="code",
                failure_signature="sig",
                notes="first try",
            )
        ],
        allowed_paths=["tasks/issue-123-test.md", "web/src/App.tsx"],
        primary_objective="Implement the reviewer-requested dashboard changes first.",
    )

    args, cwd = calls[0]
    prompt = args[-1]
    assert cwd == "/tmp/repo"
    assert args[:10] == [
        "copilot",
        "--model",
        "gpt-5.3-codex",
        "--autopilot",
        "--allow-all",
        "--max-autopilot-continues",
        "7",
        "--no-ask-user",
        "--no-color",
        "--silent",
    ]
    assert "Previous attempts for this command:" in prompt
    assert "Primary objective: Implement the reviewer-requested dashboard changes first." in prompt
    assert "attempt 1/3, signature=sig, notes=first try" in prompt
    assert "- tasks/issue-123-test.md" in prompt
    assert "- web/src/App.tsx" in prompt
    assert "Change your approach if the same failure signature has already repeated" in prompt
    assert "Do not spend this retry on test-only churn" in prompt


def test_invoke_fix_raises_when_copilot_fails(monkeypatch):
    state = _state()
    monkeypatch.setattr(
        "orchestration.services.builder_fix.get_config",
        lambda: SimpleNamespace(
            builder_model="gpt-5.3-codex",
            build_max_autopilot_continues=7,
        ),
    )
    monkeypatch.setattr(
        "orchestration.services.builder_fix.ScopePolicyService.allowed_paths",
        lambda self: [],
    )
    monkeypatch.setattr(
        "orchestration.services.builder_fix.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="copilot failed"),
    )

    with pytest.raises(RuntimeError, match="copilot failed"):
        BuilderFixService(state).invoke_fix(
            label="lint",
            command="make lint",
            exit_code=2,
            output="boom",
            prior_attempts=[],
        )
