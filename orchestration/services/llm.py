from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import time
from queue import Empty, Queue
from typing import Type, TypeVar

from pydantic import BaseModel

from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.services.config import get_config
from orchestration.services.console import emit_event

T = TypeVar("T", bound=BaseModel)


def _extract_first_json_value(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fenced_matches = re.findall(r"```json\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL | re.IGNORECASE)
    for snippet in reversed(fenced_matches):
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue

    start = next((idx for idx, ch in enumerate(raw) if ch in "{["), -1)
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", raw, 0)

    decoder = json.JSONDecoder()
    for idx, ch in enumerate(raw[start:], start=start):
        if ch not in "}]":
            continue
        try:
            value, end = decoder.raw_decode(raw[start: idx + 1])
        except json.JSONDecodeError:
            continue
        if start + end == idx + 1:
            return value

    raise json.JSONDecodeError("No complete JSON object found", raw, start)


def extract_structured_plan_output(raw: str) -> PlanOutput:
    try:
        data = _extract_first_json_value(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model did not return valid JSON:\n{raw}") from exc
    return PlanOutput.model_validate(data)


class LLMService:
    def __init__(self, stage: PipelineStage, repo_root: str | None = None) -> None:
        self.stage = stage
        self.repo_root = repo_root
        self.cfg = get_config()
        self.model = self.cfg.model_for_stage(stage)

    def _should_use_tools_enabled_mode(self) -> bool:
        return (
            self.cfg.copilot_tool_mode == "tools-enabled"
            and self.stage in {PipelineStage.BUILD, PipelineStage.REWORK_IMPLEMENTATION}
        )

    def complete_text(self, prompt: str) -> str:
        args = ["copilot", "--model", self.model, "--stream", "on"]
        tool_mode = "tools-enabled" if self._should_use_tools_enabled_mode() else "text-only"
        if self._should_use_tools_enabled_mode():
            args.extend(
                [
                    "--autopilot",
                    "--allow-all",
                    "--max-autopilot-continues",
                    str(self.cfg.build_max_autopilot_continues),
                    "--no-ask-user",
                    "--no-color",
                    "-p",
                    prompt,
                ]
            )
        else:
            args.extend(["-p", prompt, "--no-color", "--no-ask-user"])

        emit_event(
            "llm_request_started",
            stage=self.stage,
            current_action=f"Requesting model output from `{self.model}`",
            evidence=[f"tool_mode={tool_mode}"],
            reasoning="This stage depends on a Copilot model response before it can continue.",
        )

        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.repo_root,
        )
        started_at = time.monotonic()
        last_heartbeat = started_at
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

        while stdout_thread.is_alive() or stderr_thread.is_alive() or not queue.empty():
            try:
                stream_name, chunk = queue.get(timeout=1)
            except Empty:
                now = time.monotonic()
                if proc.poll() is None and now - last_heartbeat >= 30:
                    emit_event(
                        "llm_request_progress",
                        stage=self.stage,
                        current_action=f"Still waiting for `{self.model}` to finish",
                        evidence=[f"elapsed_seconds={int(now - started_at)}", f"tool_mode={tool_mode}"],
                        reasoning="The model subprocess is still running and may still be reading files, editing code, or executing tools.",
                    )
                    last_heartbeat = now
                continue

            if stream_name == "stdout":
                stdout_chunks.append(chunk)
                sys.stdout.write(chunk)
                sys.stdout.flush()
            else:
                stderr_chunks.append(chunk)
                sys.stderr.write(chunk)
                sys.stderr.flush()

        proc.wait()
        output = "".join(stdout_chunks).strip()
        error = "".join(stderr_chunks).strip()
        duration = int(time.monotonic() - started_at)
        if proc.returncode != 0:
            message = error or output
            emit_event(
                "llm_request_failed",
                stage=self.stage,
                status="failed",
                evidence=[f"model={self.model}", f"elapsed_seconds={duration}", message[:300]],
                conclusion="The model subprocess exited non-zero.",
            )
            raise RuntimeError(message)
        emit_event(
            "llm_request_finished",
            stage=self.stage,
            status="completed",
            evidence=[f"model={self.model}", f"elapsed_seconds={duration}"],
            conclusion="Model returned output for this stage.",
        )
        return output

    def complete_structured(self, prompt: str, model_cls: Type[T]) -> T:
        raw = self.complete_text(prompt)
        if model_cls is PlanOutput:
            return extract_structured_plan_output(raw)  # type: ignore[return-value]
        try:
            data = _extract_first_json_value(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model did not return valid JSON:\n{raw}") from exc
        return model_cls.model_validate(data)
