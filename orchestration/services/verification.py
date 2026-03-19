from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable, Callable, Optional

from orchestration.models.build import RetryEntry
from orchestration.models.verification import (
    VerificationCommandResult,
    VerificationEvidence,
)
from orchestration.services.artifacts import ArtifactService


class VerificationService:
    def __init__(self, repo_root: str) -> None:
        self.repo_root = repo_root
        self.artifacts = ArtifactService(repo_root)

    def _classify_failure(self, output: str) -> str:
        infra_markers = [
            "permission denied while trying to connect to the docker daemon socket",
            "cannot connect to the docker daemon",
            "temporary failure in name resolution",
            "network is unreachable",
            "tls handshake timeout",
            "context deadline exceeded",
            "connection refused",
        ]
        lowered = output.lower()
        return "infra" if any(x in lowered for x in infra_markers) else "code"

    def _run_raw(self, command: str) -> tuple[int, str]:
        proc = subprocess.run(
            command,
            cwd=self.repo_root,
            shell=True,
            text=True,
            capture_output=True,
        )
        return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()

    def _collect_known_artifacts(self) -> list[str]:
        candidates = [
            "web/playwright-report",
            "web/test-results",
        ]
        found: list[str] = []
        for c in candidates:
            p = Path(self.repo_root, c)
            if p.exists():
                found.append(c)
        return found

    def run_with_retry_policy(
        self,
        *,
        name: str,
        command: str,
        max_attempts: int,
        on_code_retry_fix: Optional[Callable[[str, str, int, str], None]] = None,
    ) -> tuple[VerificationCommandResult, list[RetryEntry]]:
        retry_entries: list[RetryEntry] = []

        for attempt in range(1, max_attempts + 1):
            code, output = self._run_raw(command)
            if code == 0:
                return (
                    VerificationCommandResult(
                        name=name,
                        command=command,
                        status="pass",
                        exit_code=0,
                        output_excerpt=output[:4000],
                        artifact_paths=self._collect_known_artifacts(),
                    ),
                    retry_entries,
                )

            classification = self._classify_failure(output)
            failure_log = self.artifacts.persist_failure_output(
                label=name,
                command=command,
                attempt=attempt,
                exit_code=code,
                output=output,
            )

            entry = RetryEntry(
                label=name,
                attempt=attempt,
                max_attempts=max_attempts,
                command=command,
                exit_code=code,
                classification=classification,
                failure_log_path=failure_log,
                notes="Verification attempt failed.",
            )
            retry_entries.append(entry)

            if classification == "infra":
                return (
                    VerificationCommandResult(
                        name=name,
                        command=command,
                        status="fail",
                        exit_code=code,
                        output_excerpt=output[:4000],
                        artifact_paths=self._collect_known_artifacts(),
                        failure_log_path=failure_log,
                    ),
                    retry_entries,
                )

            if attempt == 2 and on_code_retry_fix is not None:
                on_code_retry_fix(name, command, code, output)

        final = retry_entries[-1]
        return (
            VerificationCommandResult(
                name=name,
                command=command,
                status="fail",
                exit_code=final.exit_code,
                output_excerpt="Failed after retry policy; see failure log.",
                artifact_paths=self._collect_known_artifacts(),
                failure_log_path=final.failure_log_path,
            ),
            retry_entries,
        )

    def run_default_suite(
        self,
        *,
        max_attempts: int = 3,
        on_code_retry_fix: Optional[Callable[[str, str, int, str], None]] = None,
    ) -> tuple[VerificationEvidence, list[RetryEntry]]:
        commands: Iterable[tuple[str, str]] = [
            ("lint", "make lint"),
            ("typecheck", "make typecheck"),
            ("api-rebuild", "make api-rebuild"),
            ("test-backend", "make test-backend"),
            ("test-frontend", "make test-frontend"),
            ("api-smoke", "make api-smoke"),
        ]

        results: list[VerificationCommandResult] = []
        retries: list[RetryEntry] = []

        for name, cmd in commands:
            result, retry_entries = self.run_with_retry_policy(
                name=name,
                command=cmd,
                max_attempts=max_attempts,
                on_code_retry_fix=on_code_retry_fix,
            )
            results.append(result)
            retries.extend(retry_entries)

        playwright_ts = Path(self.repo_root, "web/playwright.config.ts")
        playwright_js = Path(self.repo_root, "web/playwright.config.js")
        if playwright_ts.exists() or playwright_js.exists():
            result, retry_entries = self.run_with_retry_policy(
                name="e2e",
                command="make e2e",
                max_attempts=max_attempts,
                on_code_retry_fix=on_code_retry_fix,
            )
            results.append(result)
            retries.extend(retry_entries)
        else:
            results.append(
                VerificationCommandResult(
                    name="e2e",
                    command="make e2e",
                    status="skip",
                    exit_code=0,
                    output_excerpt="Playwright not configured.",
                )
            )

        any_failures = any(r.status == "fail" for r in results)
        return VerificationEvidence(results=results, any_failures=any_failures), retries