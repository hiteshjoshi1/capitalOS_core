from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from orchestration.models.build import ExtraChangedFile


@dataclass
class V3PolicyResult:
    blocked: bool = False
    blockers: list[str] = field(default_factory=list)
    extra_files_with_reasons: list[ExtraChangedFile] = field(default_factory=list)


class V3PolicyService:
    RESTRICTED_PREFIXES = (
        "data/fixtures/",
        ".task-flow/",
    )
    RESTRICTED_EXACT = {
        ".gitignore",
    }
    SECRET_PATTERNS = (
        re.compile(r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
    )

    def __init__(self, repo_root: str) -> None:
        self.repo_root = Path(repo_root)

    @staticmethod
    def _is_path_allowed(path: str, allowed_paths: list[str]) -> bool:
        for allowed in allowed_paths:
            if path == allowed:
                return True
            if allowed.endswith("/") and path.startswith(allowed):
                return True
            if path.startswith(f"{allowed}/"):
                return True
        return False

    def _restricted_path(self, path: str) -> str | None:
        if path in self.RESTRICTED_EXACT:
            return f"Restricted file modified: `{path}`."
        for prefix in self.RESTRICTED_PREFIXES:
            if path.startswith(prefix):
                return f"Restricted path modified: `{path}`."
        return None

    def _contains_secret(self, path: str) -> str | None:
        full_path = self.repo_root / path
        if not full_path.exists() or full_path.is_dir():
            return None
        try:
            text = full_path.read_text(errors="ignore")
        except OSError:
            return None
        for pattern in self.SECRET_PATTERNS:
            if pattern.search(text):
                return f"Potential secret detected in `{path}` via pattern `{pattern.pattern}`."
        return None

    def evaluate(
        self,
        *,
        changed_files: list[str],
        allowed_paths: list[str],
        extra_changed_files: list[ExtraChangedFile],
    ) -> V3PolicyResult:
        result = V3PolicyResult()
        provided = {item.path: item for item in extra_changed_files if item.path}

        for path in changed_files:
            restricted = self._restricted_path(path)
            if restricted:
                result.blocked = True
                result.blockers.append(restricted)

            secret = self._contains_secret(path)
            if secret:
                result.blocked = True
                result.blockers.append(secret)

            if self._is_path_allowed(path, allowed_paths):
                continue

            item = provided.get(path)
            if item is None or not item.reason.strip():
                result.blocked = True
                result.blockers.append(
                    f"Out-of-scope file `{path}` missing explicit reason in task markdown."
                )
                continue
            result.extra_files_with_reasons.append(item)

        return result
