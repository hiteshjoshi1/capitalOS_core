from __future__ import annotations

from pathlib import Path

import pytest

from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.nodes import prepare


def test_prepare_rejects_missing_task_file_without_bootstrapping(tmp_path: Path) -> None:
    task_file = "tasks/issue-999-missing.md"
    state = PipelineState(
        issue=IssueMetadata(
            issue_id="999",
            slug="missing",
            title="Missing",
            task_file=task_file,
            repo_root=str(tmp_path),
            branch="feature/issue-999-missing",
        )
    )

    with pytest.raises(RuntimeError, match="Task file does not exist"):
        prepare.run({"pipeline": state.model_dump(mode="json")})

    assert not (tmp_path / task_file).exists()


def test_prepare_rejects_task_without_test_instructions_before_git_work(tmp_path: Path) -> None:
    task_file = "tasks/issue-999-validation.md"
    path = tmp_path / task_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """# Issue 999: Validation

## Objective
- Validate task docs.

## Acceptance Criteria
- Missing test instructions should fail before implementation.

<!-- IMMUTABLE_PLAN_END -->
"""
    )
    state = PipelineState(
        issue=IssueMetadata(
            issue_id="999",
            slug="validation",
            title="Validation",
            task_file=task_file,
            repo_root=str(tmp_path),
            branch="feature/issue-999-validation",
        )
    )

    with pytest.raises(RuntimeError, match="add a `## How To Test` or `## Verification Plan`"):
        prepare.run({"pipeline": state.model_dump(mode="json")})
