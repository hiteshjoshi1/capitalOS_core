from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sanitize_label(label: str) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", label)
    return label.strip("-") or "artifact"


class ArtifactService:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = Path(repo_root)
        self.base_dir = self.repo_root / ".task-flow"
        self.failures_dir = self.base_dir / "failures"
        self.state_dir = self.base_dir / "state"
        self.failures_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def persist_failure_output(
        self,
        *,
        label: str,
        command: str,
        attempt: int,
        exit_code: int,
        output: str,
    ) -> str:
        safe = sanitize_label(label)
        path = self.failures_dir / f"{utc_stamp()}_{safe}_attempt{attempt}.log"
        payload = {
            "label": label,
            "command": command,
            "attempt": attempt,
            "exit_code": exit_code,
            "output": output,
        }
        path.write_text(json.dumps(payload, indent=2))
        return str(path.relative_to(self.repo_root))