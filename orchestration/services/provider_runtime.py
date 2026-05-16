from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Type, TypeVar

from pydantic import BaseModel

from orchestration.models.stage import PipelineStage
from orchestration.services.config import get_config
from orchestration.services.console import emit_event
from orchestration.services.llm import (
    _extract_json_with_fallback,
    extract_session_repair_context,
    find_latest_copilot_session,
    wait_for_latest_assistant_message,
)

T = TypeVar("T", bound=BaseModel)


@dataclass
class ProviderRunResult:
    provider: str
    model: str
    output: str
    diagnostics: list[str]
    fallback_output: str | None = None
    session_events_path: str | None = None


class ProviderRuntimeService:
    def __init__(self, stage: PipelineStage, repo_root: str) -> None:
        self.stage = stage
        self.repo_root = repo_root
        self.cfg = get_config()

    def _prefix_with_caffeinate(self, args: list[str]) -> list[str]:
        if not self.cfg.enable_caffeinate:
            return args
        caffeinate = shutil.which("caffeinate")
        if not caffeinate:
            return args
        return [caffeinate, "-dimsu", *args]

    def _run_streaming_command(
        self,
        args: list[str],
        *,
        stream_stdout: bool = True,
        stream_stderr: bool = True,
        timeout_minutes: int | None = None,
    ) -> tuple[int, str, str]:
        proc = subprocess.Popen(
            args,
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        queue: Queue[tuple[str, str]] = Queue()

        def _reader(name: str, pipe) -> None:
            if pipe is None:
                return
            try:
                while True:
                    chunk = pipe.read(1)
                    if not chunk:
                        break
                    queue.put((name, chunk))
            finally:
                pipe.close()

        stdout_thread = threading.Thread(target=_reader, args=("stdout", proc.stdout), daemon=True)
        stderr_thread = threading.Thread(target=_reader, args=("stderr", proc.stderr), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        total_timeout_seconds = (timeout_minutes or self.cfg.longrun_timeout_minutes) * 60
        inactivity_limit_seconds = self.cfg.inactivity_timeout_minutes * 60
        deadline = time.monotonic() + total_timeout_seconds
        last_output_time = time.monotonic()
        try:
            while stdout_thread.is_alive() or stderr_thread.is_alive() or not queue.empty():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    proc.kill()
                    raise RuntimeError(
                        f"Provider subprocess exceeded total timeout of "
                        f"{timeout_minutes or self.cfg.longrun_timeout_minutes} minutes."
                    )
                try:
                    stream_name, chunk = queue.get(timeout=min(1.0, remaining))
                    last_output_time = time.monotonic()
                except Empty:
                    inactivity_elapsed = time.monotonic() - last_output_time
                    if inactivity_elapsed >= inactivity_limit_seconds:
                        proc.kill()
                        raise RuntimeError(
                            f"Provider subprocess stalled: no output for "
                            f"{int(inactivity_elapsed / 60)} minutes "
                            f"(inactivity limit is {self.cfg.inactivity_timeout_minutes} minutes)."
                        )
                    continue

                if stream_name == "stdout":
                    stdout_chunks.append(chunk)
                    if stream_stdout:
                        sys.stdout.write(chunk)
                        sys.stdout.flush()
                else:
                    stderr_chunks.append(chunk)
                    if stream_stderr:
                        sys.stderr.write(chunk)
                        sys.stderr.flush()
        except KeyboardInterrupt:
            proc.terminate()
            raise

        proc.wait()
        return proc.returncode, "".join(stdout_chunks).strip(), "".join(stderr_chunks).strip()

    def _run_copilot(self, *, model: str, prompt: str) -> ProviderRunResult:
        started_at_epoch = time.time()
        args = [
            "copilot",
            "--model",
            model,
            "--stream",
            "on",
            "--autopilot",
            "--allow-all",
            "--max-autopilot-continues",
            str(self.cfg.build_max_autopilot_continues),
            "--no-ask-user",
            "--no-color",
            "-p",
            prompt,
        ]
        reasoning_effort = getattr(self.cfg, "reasoning_effort", None)
        if reasoning_effort:
            args[3:3] = ["--reasoning-effort", reasoning_effort]
        final_args = self._prefix_with_caffeinate(args)
        returncode, output, error = self._run_streaming_command(final_args)
        if returncode != 0:
            raise RuntimeError(error or output or "Copilot provider failed without output.")
        session_events_path = find_latest_copilot_session(
            model=model,
            repo_root=self.repo_root,
            started_after_epoch=started_at_epoch,
        )
        fallback_output = None
        if session_events_path is not None:
            fallback_output = wait_for_latest_assistant_message(
                session_events_path,
                timeout_seconds=30.0,
                poll_interval_seconds=0.5,
                require_json=True,
            )
        diagnostics = [
            f"provider=copilot",
            f"model={model}",
            f"stdout_chars={len(output)}",
            f"stderr_chars={len(error)}",
        ]
        if session_events_path is not None:
            diagnostics.append(f"session_events={session_events_path}")
            diagnostics.append(f"session_json_chars={len(fallback_output or '')}")
        return ProviderRunResult(
            provider="copilot",
            model=model,
            output=output,
            diagnostics=diagnostics,
            fallback_output=fallback_output,
            session_events_path=str(session_events_path) if session_events_path else None,
        )

    def _build_repair_prompt(
        self,
        *,
        original_prompt: str,
        raw: str,
        fallback_raw: str | None,
        session_context: str,
    ) -> str:
        return (
            "The previous implementation session completed work in the repository but did not emit"
            " the required final JSON payload.\n\n"
            "Your ONLY task: produce the strict JSON output that the previous session should have produced.\n"
            "- Do NOT call any tools.\n"
            "- Do NOT make any file changes.\n"
            "- Return ONLY a valid JSON object — no prose, no markdown fences.\n\n"
            "Original prompt (defines the expected JSON schema and what work was done):\n"
            f"{original_prompt}\n\n"
            "Previous session stdout (may be empty or contain partial output):\n"
            f"{raw[:8000] if raw else '<empty>'}\n\n"
            "Previous session assistant-message fallback:\n"
            f"{fallback_raw[:4000] if fallback_raw else '<empty>'}\n\n"
            "Session context summary (what the agent actually did):\n"
            f"{session_context}\n\n"
            "Return only valid JSON matching the schema in the original prompt."
        )

    def _run_copilot_repair(self, *, model: str, prompt: str) -> str:
        """Lightweight text-only Copilot call to repair malformed structured output.

        No autopilot, no tools — this is purely a JSON-formatting request and
        should complete in well under 5 minutes.
        """
        args = [
            "copilot",
            "--model",
            model,
            "-p",
            prompt,
            "--no-color",
            "--no-ask-user",
        ]
        reasoning_effort = getattr(self.cfg, "reasoning_effort", None)
        if reasoning_effort:
            args[3:3] = ["--reasoning-effort", reasoning_effort]
        final_args = self._prefix_with_caffeinate(args)
        returncode, output, error = self._run_streaming_command(
            final_args,
            stream_stdout=True,
            stream_stderr=False,
            timeout_minutes=5,
        )
        if returncode != 0:
            raise RuntimeError(error or output or "Copilot repair call failed without output.")
        return output

    def _run_codex(self, *, model: str, prompt: str) -> ProviderRunResult:
        with tempfile.NamedTemporaryFile(prefix="codex-last-message-", suffix=".txt", delete=False) as handle:
            output_path = Path(handle.name)

        args = [
            "codex",
            "exec",
            "--model",
            model,
            "--full-auto",
            "--sandbox",
            "workspace-write",
            "--cd",
            self.repo_root,
            "--output-last-message",
            str(output_path),
            "--color",
            "never",
            prompt,
        ]
        final_args = self._prefix_with_caffeinate(args)
        try:
            returncode, output, error = self._run_streaming_command(final_args)
            output = output_path.read_text().strip() if output_path.exists() else output
            if not output:
                output = ""
            if returncode != 0:
                raise RuntimeError(error or output or "Codex provider failed without output.")
            diagnostics = [
                f"provider=codex",
                f"model={model}",
                f"stdout_chars={len(output)}",
                f"stderr_chars={len(error)}",
            ]
            return ProviderRunResult(provider="codex", model=model, output=output, diagnostics=diagnostics)
        finally:
            output_path.unlink(missing_ok=True)

    def _run_provider(self, provider: str, *, model: str, prompt: str) -> ProviderRunResult:
        if provider == "copilot":
            return self._run_copilot(model=model, prompt=prompt)
        if provider == "codex":
            return self._run_codex(model=model, prompt=prompt)
        raise RuntimeError(f"Unsupported provider: {provider}")

    def complete_structured(self, prompt: str, model_cls: Type[T]) -> tuple[T, ProviderRunResult]:
        provider = self.cfg.provider
        model_name = self.cfg.model

        emit_event(
            "provider_run_started",
            stage=self.stage,
            current_action=f"Starting v3 long-run session via `{provider}`",
            evidence=[f"provider={provider}", f"model={model_name}"],
        )

        # --- Phase 1: run the provider subprocess ---
        try:
            run_result = self._run_provider(provider, model=model_name, prompt=prompt)
        except RuntimeError as exc:
            emit_event(
                "provider_run_failed",
                stage=self.stage,
                status="failed",
                evidence=[f"provider={provider}", f"error={str(exc)[:280]}"],
                conclusion=f"Provider `{provider}` subprocess failed or stalled.",
            )
            raise RuntimeError(f"Provider `{provider}` subprocess failed for v3 run: {exc}") from exc

        # --- Phase 2: parse structured output from stdout / session fallback ---
        first_parse_failure: Exception | None = None
        try:
            payload = _extract_json_with_fallback(run_result.output, run_result.fallback_output)
            parsed = model_cls.model_validate(payload)
            emit_event(
                "provider_run_finished",
                stage=self.stage,
                status="completed",
                evidence=run_result.diagnostics,
                conclusion=f"Structured payload parsed successfully from `{provider}`.",
            )
            return parsed, run_result
        except Exception as exc:  # noqa: BLE001
            first_parse_failure = exc

        # --- Phase 3: single repair attempt (copilot only, if enabled) ---
        if (
            provider == "copilot"
            and run_result.session_events_path is not None
            and self.cfg.repair_enabled
        ):
            session_context = extract_session_repair_context(Path(run_result.session_events_path))
            if session_context:
                emit_event(
                    "provider_repair_started",
                    stage=self.stage,
                    current_action="Structured output malformed; attempting single text-only repair call",
                    evidence=[
                        f"provider={provider}",
                        f"session_context_chars={len(session_context)}",
                    ],
                )
                try:
                    repair_prompt = self._build_repair_prompt(
                        original_prompt=prompt,
                        raw=run_result.output,
                        fallback_raw=run_result.fallback_output,
                        session_context=session_context,
                    )
                    repaired_raw = self._run_copilot_repair(model=model_name, prompt=repair_prompt)
                    payload = _extract_json_with_fallback(repaired_raw, None)
                    parsed = model_cls.model_validate(payload)
                    emit_event(
                        "provider_repair_finished",
                        stage=self.stage,
                        status="completed",
                        evidence=[f"provider={provider}", f"repaired_chars={len(repaired_raw)}"],
                        conclusion="Repair call produced valid structured output.",
                    )
                    return parsed, run_result
                except Exception as repair_exc:  # noqa: BLE001
                    emit_event(
                        "provider_repair_failed",
                        stage=self.stage,
                        status="failed",
                        evidence=[f"provider={provider}", f"error={str(repair_exc)[:280]}"],
                        conclusion="Repair call also failed to produce valid structured output.",
                    )
                    raise RuntimeError(
                        f"Provider `{provider}` returned malformed structured output and"
                        f" repair also failed: {repair_exc}"
                    ) from repair_exc

        emit_event(
            "provider_run_failed",
            stage=self.stage,
            status="failed",
            evidence=[
                f"provider={provider}",
                f"error={str(first_parse_failure)[:280]}",
                "repair_attempted=false",
            ],
            conclusion=f"Provider `{provider}` completed but returned malformed structured output.",
        )
        raise RuntimeError(
            f"Provider `{provider}` completed but returned malformed structured output: {first_parse_failure}"
        ) from first_parse_failure


def structured_output_for_debug(output: BaseModel) -> str:
    return json.dumps(output.model_dump(mode="json"), indent=2, default=str)
