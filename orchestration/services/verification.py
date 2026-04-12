from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

from orchestration.models.build import RetryEntry
from orchestration.models.verification import (
    VerificationCommandResult,
    VerificationEvidence,
)
from orchestration.services.artifacts import ArtifactService
from orchestration.services.console import emit_event


class VerificationService:
    def __init__(self, repo_root: str, stage: str | None = None) -> None:
        self.repo_root = repo_root
        self.artifacts = ArtifactService(repo_root)
        self.stage = stage

    def _classify_failure(self, output: str) -> str:
        infra_markers = [
            "permission denied while trying to connect to the docker daemon socket",
            "cannot connect to the docker daemon",
            "secitemcopymatching failed",
            "temporary failure in name resolution",
            "network is unreachable",
            "tls handshake timeout",
            "context deadline exceeded",
            "connection refused",
        ]
        lowered = output.lower()
        return "infra" if any(x in lowered for x in infra_markers) else "code"

    def _extract_failure_reason(self, output: str) -> str:
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if not lines:
            return "Verification command failed."

        preferred_markers = [
            "permission denied while trying to connect to the docker daemon socket",
            "cannot connect to the docker daemon",
            "secitemcopymatching failed",
            "temporary failure in name resolution",
            "network is unreachable",
            "tls handshake timeout",
            "context deadline exceeded",
            "connection refused",
            "testinglibraryelementerror",
            "operationalerror",
            "unrecognized token",
            "unable to find an element",
        ]
        for marker in preferred_markers:
            for line in lines:
                if marker in line.lower():
                    return line[:300]

        for line in lines:
            lowered = line.lower()
            if "error" in lowered or "failed" in lowered or "unable" in lowered:
                return line[:300]

        return lines[-1][:300]

    def _failure_signature(self, name: str, output: str) -> str:
        return f"{name}:{self._extract_failure_reason(output).lower()}"

    def _run_raw(self, name: str, command: str) -> tuple[int, str]:
        emit_event(
            "verification_command_started",
            stage=self.stage,
            current_action=f"Running `{name}`",
            evidence=[f"command={command}"],
        )
        proc = subprocess.Popen(
            command,
            cwd=self.repo_root,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        started_at = time.monotonic()
        last_heartbeat = started_at

        while True:
            try:
                stdout, stderr = proc.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                if now - last_heartbeat >= 30:
                    emit_event(
                        "verification_command_progress",
                        stage=self.stage,
                        current_action=f"`{name}` is still running",
                        evidence=[f"command={command}", f"elapsed_seconds={int(now - started_at)}"],
                        reasoning="The verification command is still active and has not exited yet.",
                    )
                    last_heartbeat = now

        output = (stdout + "\n" + stderr).strip()
        emit_event(
            "verification_command_finished",
            stage=self.stage,
            status="completed" if proc.returncode == 0 else "failed",
            evidence=[f"name={name}", f"exit_code={proc.returncode}", f"elapsed_seconds={int(time.monotonic() - started_at)}"],
            conclusion=f"`{name}` finished with exit code {proc.returncode}.",
        )
        return proc.returncode, output

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

    @staticmethod
    def _retry_applied_code_fix(entry: RetryEntry) -> bool:
        return entry.classification == "code" and entry.notes.startswith(
            "Code failure analyzed and auto-fix applied:"
        )

    @staticmethod
    def _detect_changed_areas(changed_files: list[str]) -> set[str]:
        areas: set[str] = set()
        for path in changed_files:
            if path.startswith("api/") or path.startswith("migrations/"):
                areas.add("backend")
            if path.startswith("web/"):
                areas.add("frontend")
            if (
                path.startswith("orchestration/")
                or path.startswith("docs/workflows/")
                or path == "Makefile"
            ):
                areas.add("pipeline")
        return areas

    @classmethod
    def _verification_commands_for_areas(cls, repo_root: str, areas: set[str]) -> list[dict[str, str]]:
        commands: list[dict[str, str]] = []

        if "backend" in areas:
            commands.extend(
                [
                    {"name": "api-rebuild", "command": "make api-rebuild", "family": "backend"},
                    {"name": "contract-backend", "command": "make contract-backend", "family": "backend"},
                    {"name": "test-backend", "command": "make test-backend", "family": "backend"},
                    {"name": "api-smoke", "command": "make api-smoke", "family": "backend"},
                ]
            )

        if "frontend" in areas:
            commands.extend(
                [
                    {"name": "lint", "command": "make lint", "family": "frontend"},
                    {"name": "typecheck", "command": "make typecheck", "family": "frontend"},
                    {"name": "contract-frontend", "command": "make contract-frontend", "family": "frontend"},
                    {"name": "test-frontend", "command": "make test-frontend", "family": "frontend"},
                ]
            )
            playwright_ts = Path(repo_root, "web/playwright.config.ts")
            playwright_js = Path(repo_root, "web/playwright.config.js")
            if playwright_ts.exists() or playwright_js.exists():
                commands.append({"name": "e2e", "command": "make e2e", "family": "frontend"})
            else:
                commands.append({"name": "e2e", "command": "__skip__", "family": "frontend"})

        if "pipeline" in areas:
            commands.append({"name": "orch-test", "command": "make orch-test", "family": "pipeline"})

        return commands

    @classmethod
    def expected_commands_for_changed_files(cls, repo_root: str, changed_files: list[str]) -> list[str]:
        return [
            item["command"]
            for item in cls._verification_commands_for_changed_files(repo_root, changed_files)
            if item["command"] != "__skip__"
        ]

    @classmethod
    def expected_commands_for_default_suite(cls, repo_root: str) -> list[str]:
        return [
            item["command"]
            for item in cls._default_suite_commands(repo_root)
            if item["command"] != "__skip__"
        ]

    @classmethod
    def _verification_commands_for_changed_files(cls, repo_root: str, changed_files: list[str]) -> list[dict[str, str]]:
        areas = cls._detect_changed_areas(changed_files)
        return cls._verification_commands_for_areas(repo_root, areas)

    @classmethod
    def _default_suite_commands(cls, repo_root: str) -> list[dict[str, str]]:
        return cls._verification_commands_for_areas(
            repo_root,
            {"backend", "frontend", "pipeline"},
        )

    @staticmethod
    def _restart_family_for_command(name: str) -> str:
        if name in {"lint", "typecheck", "contract-frontend", "test-frontend", "e2e"}:
            return "frontend"
        if name in {"api-rebuild", "contract-backend", "test-backend", "api-smoke"}:
            return "backend"
        if name == "orch-test":
            return "pipeline"
        return "frontend"

    def run_with_retry_policy(
        self,
        *,
        name: str,
        command: str,
        max_attempts: int,
        on_code_retry_fix: Optional[Callable[[str, str, int, str, list[RetryEntry]], None]] = None,
    ) -> tuple[VerificationCommandResult, list[RetryEntry]]:
        retry_entries: list[RetryEntry] = []

        for attempt in range(1, max_attempts + 1):
            code, output = self._run_raw(name, command)
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
            reason = self._extract_failure_reason(output)
            failure_signature = self._failure_signature(name, output)
            entry_max_attempts = min(max_attempts, 2) if classification == "infra" else max_attempts
            failure_log = self.artifacts.persist_failure_output(
                label=name,
                command=command,
                attempt=attempt,
                exit_code=code,
                output=output,
            )
            emit_event(
                "verification_attempt_failed",
                stage=self.stage,
                current_action=f"`{name}` failed on attempt {attempt}",
                evidence=[
                    f"classification={classification}",
                    f"failure_log={failure_log}",
                    f"reason={reason}",
                ],
                reasoning="The failure was classified to decide whether to retry directly or attempt an automated code fix.",
            )

            entry = RetryEntry(
                label=name,
                attempt=attempt,
                max_attempts=entry_max_attempts,
                command=command,
                exit_code=code,
                classification=classification,
                failure_signature=failure_signature,
                failure_log_path=failure_log,
                notes=f"Failure reason: {reason}",
            )

            if classification == "infra":
                entry.notes = f"Infra failure: {reason}"
                retry_entries.append(entry)
                if attempt < min(max_attempts, 2):
                    emit_event(
                        "verification_retry_scheduled",
                        stage=self.stage,
                        current_action=f"Retrying infra command `{name}`",
                        evidence=[f"next_attempt={attempt + 1}", f"reason={reason}"],
                        conclusion="Infra failures are retried once before the stage is blocked.",
                    )
                    continue
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

            if on_code_retry_fix is None:
                entry.notes = f"Code failure with no auto-fix available: {reason}"
                retry_entries.append(entry)
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

            if attempt >= max_attempts:
                entry.notes = f"Code failure after max retry budget: {reason}"
                retry_entries.append(entry)
                break

            repeated_signature = any(
                prior.classification == "code"
                and prior.failure_signature == failure_signature
                and self._retry_applied_code_fix(prior)
                for prior in retry_entries
            )
            if repeated_signature:
                entry.notes = (
                    "Code failure repeated with the same signature after an auto-fix attempt; "
                    f"stopping to avoid thrash without new context: {reason}"
                )
                retry_entries.append(entry)
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

            try:
                emit_event(
                    "verification_auto_fix_started",
                    stage=self.stage,
                    current_action=f"Applying automated fix for `{name}`",
                    evidence=[f"attempt={attempt}", f"reason={reason}"],
                        reasoning="Code failures trigger an automated fix before the next retry.",
                )
                on_code_retry_fix(name, command, code, output, [*retry_entries, entry])
            except Exception as exc:
                entry.notes = f"Auto-fix failed after code failure: {exc}"
                retry_entries.append(entry)
                return (
                    VerificationCommandResult(
                        name=name,
                        command=command,
                        status="fail",
                        exit_code=code,
                        output_excerpt=(output + f"\n\nAuto-fix failed: {exc}")[:4000],
                        artifact_paths=self._collect_known_artifacts(),
                        failure_log_path=failure_log,
                    ),
                    retry_entries,
                )

            entry.notes = f"Code failure analyzed and auto-fix applied: {reason}"
            retry_entries.append(entry)
            emit_event(
                "verification_auto_fix_finished",
                stage=self.stage,
                status="completed",
                evidence=[f"next_attempt={attempt + 1}", f"reason={reason}"],
                conclusion=f"Automated fix completed for `{name}`; retrying the command.",
            )

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

    def run_suite_for_changed_files(
        self,
        changed_files: list[str],
        *,
        max_attempts: int = 3,
        on_code_retry_fix: Optional[Callable[[str, str, int, str, list[RetryEntry]], None]] = None,
    ) -> tuple[VerificationEvidence, list[RetryEntry]]:
        commands = self._verification_commands_for_changed_files(self.repo_root, changed_files)
        suite_name = "+".join(sorted(self._detect_changed_areas(changed_files))) or "none"
        emit_event(
            "verification_suite_started",
            stage=self.stage,
            current_action="Running verification suite",
            evidence=[
                f"suite={suite_name}",
                f"commands={','.join(item['name'] for item in commands) or 'none'}",
            ],
        )
        if not commands:
            evidence = VerificationEvidence(suite_name=suite_name, results=[], any_failures=False)
            emit_event(
                "verification_suite_finished",
                stage=self.stage,
                status="completed",
                evidence=["failed_commands=none"],
                conclusion="No relevant verification commands were required for the changed files.",
            )
            return evidence, []
        family_starts: dict[str, int] = {}
        for index, item in enumerate(commands):
            family_starts.setdefault(item["family"], index)

        results: list[VerificationCommandResult] = []
        retries: list[RetryEntry] = []
        max_suite_rounds = max(2, max_attempts + 1)
        start_index = 0

        for suite_round in range(1, max_suite_rounds + 1):
            round_results: list[VerificationCommandResult] = list(results[:start_index])
            round_retries: list[RetryEntry] = []

            for item in commands[start_index:]:
                name = item["name"]
                cmd = item["command"]
                if cmd == "__skip__":
                    round_results.append(
                        VerificationCommandResult(
                            name="e2e",
                            command="make e2e",
                            status="skip",
                            exit_code=0,
                            output_excerpt="Playwright not configured.",
                        )
                    )
                    continue

                result, retry_entries = self.run_with_retry_policy(
                    name=name,
                    command=cmd,
                    max_attempts=max_attempts,
                    on_code_retry_fix=on_code_retry_fix,
                )
                round_results.append(result)
                round_retries.extend(retry_entries)

            results = round_results
            retries.extend(round_retries)
            any_failures = any(r.status == "fail" for r in round_results)
            code_fix_applied = any(
                self._retry_applied_code_fix(entry) for entry in round_retries
            )

            if any_failures or not code_fix_applied or suite_round >= max_suite_rounds:
                break

            impacted_families = {
                self._restart_family_for_command(entry.label)
                for entry in round_retries
                if self._retry_applied_code_fix(entry)
            }
            restart_at = min(
                (family_starts.get(family, 0) for family in impacted_families),
                default=0,
            )
            start_index = restart_at

            emit_event(
                "verification_suite_restarted",
                stage=self.stage,
                current_action="Restarting verification suite after auto-fix",
                evidence=[
                    f"round={suite_round}",
                    "reason=repo mutated after auto-fix",
                    f"restart_index={start_index}",
                    f"families={','.join(sorted(impacted_families)) or 'foundation'}",
                ],
                reasoning="A code-mutating fix invalidates the impacted verification family and everything after it, so the suite reruns from the appropriate family boundary.",
            )

        any_failures = any(r.status == "fail" for r in results)
        emit_event(
            "verification_suite_finished",
            stage=self.stage,
            status="failed" if any_failures else "completed",
            evidence=[f"failed_commands={','.join(r.name for r in results if r.status == 'fail') or 'none'}"],
            conclusion="Verification suite completed.",
        )
        return VerificationEvidence(suite_name=suite_name, results=results, any_failures=any_failures), retries

    def run_default_suite(
        self,
        *,
        max_attempts: int = 3,
        on_code_retry_fix: Optional[Callable[[str, str, int, str, list[RetryEntry]], None]] = None,
    ) -> tuple[VerificationEvidence, list[RetryEntry]]:
        commands = self._default_suite_commands(self.repo_root)
        suite_name = "default"
        emit_event(
            "verification_suite_started",
            stage=self.stage,
            current_action="Running verification suite",
            evidence=[
                f"suite={suite_name}",
                f"commands={','.join(item['name'] for item in commands) or 'none'}",
            ],
        )
        if not commands:
            evidence = VerificationEvidence(suite_name=suite_name, results=[], any_failures=False)
            emit_event(
                "verification_suite_finished",
                stage=self.stage,
                status="completed",
                evidence=["failed_commands=none"],
                conclusion="No verification commands were configured for the default suite.",
            )
            return evidence, []

        family_starts: dict[str, int] = {}
        for index, item in enumerate(commands):
            family_starts.setdefault(item["family"], index)

        results: list[VerificationCommandResult] = []
        retries: list[RetryEntry] = []
        max_suite_rounds = max(2, max_attempts + 1)
        start_index = 0

        for suite_round in range(1, max_suite_rounds + 1):
            round_results: list[VerificationCommandResult] = list(results[:start_index])
            round_retries: list[RetryEntry] = []

            for item in commands[start_index:]:
                name = item["name"]
                cmd = item["command"]
                if cmd == "__skip__":
                    round_results.append(
                        VerificationCommandResult(
                            name="e2e",
                            command="make e2e",
                            status="skip",
                            exit_code=0,
                            output_excerpt="Playwright not configured.",
                        )
                    )
                    continue

                result, retry_entries = self.run_with_retry_policy(
                    name=name,
                    command=cmd,
                    max_attempts=max_attempts,
                    on_code_retry_fix=on_code_retry_fix,
                )
                round_results.append(result)
                round_retries.extend(retry_entries)

            results = round_results
            retries.extend(round_retries)
            any_failures = any(r.status == "fail" for r in round_results)
            code_fix_applied = any(
                self._retry_applied_code_fix(entry) for entry in round_retries
            )

            if any_failures or not code_fix_applied or suite_round >= max_suite_rounds:
                break

            impacted_families = {
                self._restart_family_for_command(entry.label)
                for entry in round_retries
                if self._retry_applied_code_fix(entry)
            }
            restart_at = min(
                (family_starts.get(family, 0) for family in impacted_families),
                default=0,
            )
            start_index = restart_at

            emit_event(
                "verification_suite_restarted",
                stage=self.stage,
                current_action="Restarting verification suite after auto-fix",
                evidence=[
                    f"round={suite_round}",
                    "reason=repo mutated after auto-fix",
                    f"restart_index={start_index}",
                    f"families={','.join(sorted(impacted_families)) or 'foundation'}",
                ],
                reasoning="A code-mutating fix invalidates the impacted verification family and everything after it, so the suite reruns from the appropriate family boundary.",
            )

        any_failures = any(r.status == "fail" for r in results)
        emit_event(
            "verification_suite_finished",
            stage=self.stage,
            status="failed" if any_failures else "completed",
            evidence=[f"failed_commands={','.join(r.name for r in results if r.status == 'fail') or 'none'}"],
            conclusion="Verification suite completed.",
        )
        return VerificationEvidence(suite_name=suite_name, results=results, any_failures=any_failures), retries
