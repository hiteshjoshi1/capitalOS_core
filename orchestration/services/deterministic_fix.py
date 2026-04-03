from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class DeterministicFixResult:
    applied: bool
    summary: str


class DeterministicFixService:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root

    def _run(self, command: str) -> None:
        proc = subprocess.run(
            command,
            cwd=self.repo_root,
            shell=True,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"Command failed: {command}")

    def apply_for_failure(self, *, output: str) -> DeterministicFixResult:
        lowered = output.lower()

        if "permission denied while trying to connect to the docker daemon socket" in lowered:
            return DeterministicFixResult(
                applied=False,
                summary="Docker daemon access issue detected; deterministic workaround unavailable in pipeline runtime.",
            )

        if "command not found: npm" in lowered or "npx: command not found" in lowered:
            self._run("make web-deps")
            return DeterministicFixResult(applied=True, summary="Ran `make web-deps` to restore frontend toolchain.")

        if "playwright" in lowered and "executable doesn't exist" in lowered:
            self._run("cd web && npx playwright install")
            return DeterministicFixResult(applied=True, summary="Installed missing Playwright browsers.")

        if "mypy not installed" in lowered:
            return DeterministicFixResult(applied=False, summary="mypy missing is tolerated by current pipeline config.")

        return DeterministicFixResult(
            applied=False,
            summary="No deterministic mitigation rule matched this failure signature.",
        )
