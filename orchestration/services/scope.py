from __future__ import annotations

from typing import Iterable

from orchestration.models.build import ExtraChangedFile
from orchestration.models.pipeline import PipelineState
from orchestration.services.config import get_config


def derive_verification_support_paths(paths: Iterable[str]) -> list[str]:
    normalized = [path.strip().rstrip("/") for path in paths if path and path.strip()]
    derived: set[str] = set()

    if any(path == "web" or path.startswith("web/") for path in normalized):
        derived.update({"web/src/__tests__/", "web/tests/e2e/"})

    if any(path == "api" or path.startswith("api/") for path in normalized):
        derived.add("api/tests/")

    if any(path == "orchestration" or path.startswith("orchestration/") for path in normalized):
        derived.add("orchestration/tests/")

    return sorted(derived)


class ScopePolicyService:
    def __init__(self, state: PipelineState) -> None:
        self.state = state
        self.cfg = get_config()

    def allowed_paths(self, *, include_verification_support: bool = True) -> list[str]:
        allowed = {self.state.issue.task_file}
        allowed.update(self.cfg.allowed_aux_files)

        if self.state.plan_output:
            allowed.update(self.state.plan_output.allowed_paths())
            if include_verification_support:
                allowed.update(
                    derive_verification_support_paths(self.state.plan_output.allowed_paths())
                )

        allowed.update(self.state.approved_extra_file_paths())

        if self.state.build_output:
            allowed.update(self.state.build_output.changed_files)

        rework = self.state.get_active_rework_cycle()
        if rework and rework.implementation:
            allowed.update(rework.implementation.changed_files)

        return sorted(p for p in allowed if p)

    def review_allowed_paths(self, *, include_verification_support: bool = True) -> list[str]:
        allowed = {self.state.issue.task_file}
        allowed.update(self.cfg.allowed_aux_files)
        if self.state.plan_output:
            allowed.update(self.state.plan_output.allowed_paths())
            if include_verification_support:
                allowed.update(
                    derive_verification_support_paths(self.state.plan_output.allowed_paths())
                )
        allowed.update(self.state.approved_extra_file_paths())
        return sorted(p for p in allowed if p)

    def rework_autofix_allowed_paths(self, implementation_changed_files: Iterable[str]) -> list[str]:
        allowed = set(self.review_allowed_paths(include_verification_support=False))
        allowed.update(path for path in implementation_changed_files if path)
        return sorted(allowed)

    def find_unapproved_extra_files(self, changed_files: Iterable[str]) -> list[str]:
        allowed = self.review_allowed_paths()
        return sorted(
            path for path in changed_files
            if path and not self.is_path_allowed(path, allowed)
        )

    @staticmethod
    def infer_extra_file_reason(path: str) -> ExtraChangedFile:
        if path.startswith("orchestration/") or path == "scripts/task_flow.sh":
            return ExtraChangedFile(
                path=path,
                reason="Likely workflow or pipeline support change required alongside the task implementation.",
                reason_source="inferred",
            )
        if path.startswith("api/tests/") or path.startswith("web/src/__tests__/"):
            return ExtraChangedFile(
                path=path,
                reason="Likely test update required to align verification with the implementation change.",
                reason_source="inferred",
            )
        if path.startswith("api/") or path.startswith("web/src/"):
            return ExtraChangedFile(
                path=path,
                reason="Builder likely changed an additional application file outside the planned paths.",
                reason_source="inferred",
            )
        if path == ".ai-models.env":
            return ExtraChangedFile(
                path=path,
                reason="Likely builder/runtime configuration change required for the workflow to execute correctly.",
                reason_source="inferred",
            )
        return ExtraChangedFile(
            path=path,
            reason="Builder could not infer why this out-of-scope file was changed.",
            reason_source="unknown",
        )

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
