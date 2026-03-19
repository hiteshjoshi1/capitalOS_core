from __future__ import annotations

from typing import Iterable

from orchestration.models.pipeline import PipelineState
from orchestration.services.config import get_config


class ScopePolicyService:
    def __init__(self, state: PipelineState) -> None:
        self.state = state
        self.cfg = get_config()

    def allowed_paths(self) -> list[str]:
        allowed = {self.state.issue.task_file}
        allowed.update(self.cfg.allowed_aux_files)

        if self.state.plan_output:
            allowed.update(self.state.plan_output.allowed_paths())

        if self.state.build_output:
            allowed.update(self.state.build_output.changed_files)

        rework = self.state.get_active_rework_cycle()
        if rework and rework.implementation:
            allowed.update(rework.implementation.changed_files)

        return sorted(p for p in allowed if p)

    @staticmethod
    def is_path_allowed(path: str, allowed_paths: Iterable[str]) -> bool:
        normalized = [p.strip() for p in allowed_paths if p.strip()]
        for allowed in normalized:
            if path == allowed:
                return True
            if allowed.endswith("/"):
                if path.startswith(allowed):
                    return True
            elif path.startswith(f"{allowed}/"):
                return True
        return False