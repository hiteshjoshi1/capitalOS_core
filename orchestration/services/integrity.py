from __future__ import annotations

from orchestration.models.pipeline import PipelineState
from orchestration.services.task_markdown import TaskMarkdownService


class IntegrityService:
    def __init__(self, repo_root: str) -> None:
        self.md = TaskMarkdownService(repo_root)

    def capture_current_immutable_hash(self, task_file: str) -> str:
        self.md.ensure_required_markers(task_file)
        content = self.md.read(task_file)
        return self.md.immutable_hash(content)

    def assert_matches_planned_hash(self, state: PipelineState) -> None:
        if not state.plan_output or not state.plan_output.immutable_plan_hash:
            raise RuntimeError("Missing immutable plan hash in structured state.")

        self.md.ensure_required_markers(state.issue.task_file)
        current = self.capture_current_immutable_hash(state.issue.task_file)
        expected = state.plan_output.immutable_plan_hash
        if current != expected:
            raise RuntimeError(
                "Immutable plan region changed after planning. "
                "Mutable stages must not edit content above the immutable marker."
            )