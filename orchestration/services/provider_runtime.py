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
        if not self.cfg.v3_enable_caffeinate:
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

        deadline = time.monotonic() + (self.cfg.v3_longrun_timeout_minutes * 60)
        try:
            while stdout_thread.is_alive() or stderr_thread.is_alive() or not queue.empty():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    proc.kill()
                    raise RuntimeError(
                        f"Provider subprocess exceeded timeout of {self.cfg.v3_longrun_timeout_minutes} minutes."
                    )
                try:
                    stream_name, chunk = queue.get(timeout=min(1.0, remaining))
                except Empty:
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
                timeout_seconds=5.0,
                poll_interval_seconds=0.25,
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
        provider = self.cfg.v3_provider
        model_name = self.cfg.v3_model

        emit_event(
            "provider_run_started",
            stage=self.stage,
            current_action=f"Starting v3 long-run session via `{provider}`",
            evidence=[f"provider={provider}", f"model={model_name}"],
        )

        try:
            run_result = self._run_provider(provider, model=model_name, prompt=prompt)
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
            emit_event(
                "provider_run_failed",
                stage=self.stage,
                status="failed",
                evidence=[f"provider={provider}", f"error={str(exc)[:280]}"],
                conclusion=f"Provider `{provider}` failed for this v3 run attempt.",
            )
            raise RuntimeError(f"Provider `{provider}` failed for v3 run: {exc}") from exc


def structured_output_for_debug(output: BaseModel) -> str:
    return json.dumps(output.model_dump(mode="json"), indent=2, default=str)
