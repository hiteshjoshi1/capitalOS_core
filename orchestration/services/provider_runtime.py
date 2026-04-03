from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

from orchestration.models.stage import PipelineStage
from orchestration.services.config import get_config
from orchestration.services.console import emit_event
from orchestration.services.llm import _extract_json_with_fallback

T = TypeVar("T", bound=BaseModel)


@dataclass
class ProviderRunResult:
    provider: str
    model: str
    output: str
    diagnostics: list[str]


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

    def _run_copilot(self, *, model: str, prompt: str) -> ProviderRunResult:
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
        proc = subprocess.run(
            final_args,
            cwd=self.repo_root,
            capture_output=True,
            text=True,
            timeout=self.cfg.v3_longrun_timeout_minutes * 60,
        )
        output = (proc.stdout or "").strip()
        error = (proc.stderr or "").strip()
        if proc.returncode != 0:
            raise RuntimeError(error or output or "Copilot provider failed without output.")
        diagnostics = [f"provider=copilot", f"model={model}", f"stdout_chars={len(output)}"]
        return ProviderRunResult(provider="copilot", model=model, output=output, diagnostics=diagnostics)

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
            proc = subprocess.run(
                final_args,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.cfg.v3_longrun_timeout_minutes * 60,
            )
            output = output_path.read_text().strip() if output_path.exists() else ""
            if not output:
                output = (proc.stdout or "").strip()
            error = (proc.stderr or "").strip()
            if proc.returncode != 0:
                raise RuntimeError(error or output or "Codex provider failed without output.")
            diagnostics = [f"provider=codex", f"model={model}", f"stdout_chars={len(output)}"]
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
        primary = self.cfg.v3_provider
        model_name = self.cfg.v3_model

        emit_event(
            "provider_run_started",
            stage=self.stage,
            current_action=f"Starting v3 long-run session via `{primary}`",
            evidence=[f"provider={primary}", f"model={model_name}"],
        )

        tried: list[str] = []
        last_exc: Exception | None = None
        for provider in [primary, self.cfg.v3_fallback_provider]:
            if provider in tried:
                continue
            if provider != primary and not self.cfg.v3_enable_provider_fallback:
                continue
            tried.append(provider)
            try:
                run_result = self._run_provider(provider, model=model_name, prompt=prompt)
                payload = _extract_json_with_fallback(run_result.output)
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
                last_exc = exc
                emit_event(
                    "provider_run_failed",
                    stage=self.stage,
                    status="failed",
                    evidence=[f"provider={provider}", f"error={str(exc)[:280]}"],
                    conclusion=f"Provider `{provider}` failed for this v3 run attempt.",
                )
                continue

        raise RuntimeError(f"All providers failed for v3 run: {last_exc}")


def structured_output_for_debug(output: BaseModel) -> str:
    return json.dumps(output.model_dump(mode="json"), indent=2, default=str)
