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
