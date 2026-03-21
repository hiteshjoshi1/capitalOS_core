from __future__ import annotations

import pytest

from orchestration.models.issue import IssueMetadata
from orchestration.models.pipeline import PipelineState
from orchestration.models.plan import PlanOutput
from orchestration.services.integrity import IntegrityService
from orchestration.services.task_markdown import TaskMarkdownService


def test_immutable_hash_detects_changes(tmp_path):
    repo_root = str(tmp_path)
    task_file = "tasks/issue-1-test.md"

    md = TaskMarkdownService(repo_root)
    md.bootstrap_if_missing(task_file, "Test", "1")
    content = md.read(task_file)
    immutable_hash = md.immutable_hash(content)

    state = PipelineState(
        issue=IssueMetadata(
            issue_id="1",
            slug="test",
            title="Test",
            task_file=task_file,
            repo_root=repo_root,
            branch="feature/issue-1-test",
        ),
        plan_output=PlanOutput(
            summary="s",
            architecture_decisions=[],
            risks=[],
            open_questions=[],
            acceptance_criteria=[],
            checklist=[],
            immutable_plan_hash=immutable_hash,
        ),
    )

    updated = content.replace("## Objective", "## Objective Changed")
    md.write(task_file, updated)

    with pytest.raises(RuntimeError):
        IntegrityService(repo_root).assert_matches_planned_hash(state)