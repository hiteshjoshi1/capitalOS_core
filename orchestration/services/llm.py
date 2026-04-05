from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from queue import Empty, Queue
from typing import Type, TypeVar

from pydantic import BaseModel

from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.services.config import get_config
from orchestration.services.console import emit_event

T = TypeVar("T", bound=BaseModel)


def _copilot_session_root() -> Path:
    return Path.home() / ".copilot" / "session-state"


def _iter_session_event_files() -> list[Path]:
    root = _copilot_session_root()
    if not root.exists():
        return []
    return sorted(root.glob("*/events.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def _session_metadata(events_path: Path) -> dict[str, str] | None:
    try:
        with events_path.open() as handle:
            first_line = handle.readline()
    except OSError:
        return None
    if not first_line.strip():
        return None
    try:
        payload = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    if payload.get("type") != "session.start":
        return None
    data = payload.get("data") or {}
    context = data.get("context") or {}
    return {
        "model": str(data.get("selectedModel") or ""),
        "cwd": str(context.get("cwd") or ""),
        "branch": str(context.get("branch") or ""),
    }


def find_latest_copilot_session(
    *,
    model: str,
    repo_root: str | None,
    started_after_epoch: float | None = None,
    branch: str | None = None,
) -> Path | None:
    normalized_root = str(Path(repo_root).resolve()) if repo_root else ""
    for events_path in _iter_session_event_files():
        try:
            stat = events_path.stat()
        except OSError:
            continue
        if started_after_epoch is not None and stat.st_mtime + 1 < started_after_epoch:
            continue
        metadata = _session_metadata(events_path)
        if metadata is None:
            continue
        if metadata["model"] != model:
            continue
        if normalized_root and metadata["cwd"] and str(Path(metadata["cwd"]).resolve()) != normalized_root:
            continue
        if branch and metadata["branch"] and metadata["branch"] != branch:
            continue
        return events_path
    return None


def extract_latest_assistant_message(events_path: Path) -> str | None:
    latest_content: str | None = None
    try:
        with events_path.open() as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if payload.get("type") != "assistant.message":
                    continue
                content = ((payload.get("data") or {}).get("content") or "").strip()
                if content:
                    latest_content = content
    except OSError:
        return None
    return latest_content


def wait_for_latest_assistant_message(
    events_path: Path,
    *,
    timeout_seconds: float = 5.0,
    poll_interval_seconds: float = 0.25,
    require_json: bool = False,
) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    latest_message: str | None = None
    while time.monotonic() <= deadline:
        latest_message = extract_latest_assistant_message(events_path)
        if latest_message:
            if not require_json:
                return latest_message
            try:
                _extract_first_json_value(latest_message)
                return latest_message
            except json.JSONDecodeError:
                pass
        time.sleep(poll_interval_seconds)
    return latest_message


def extract_session_repair_context(events_path: Path) -> str | None:
    assistant_messages: list[str] = []
    tool_results: list[str] = []
    task_complete_summary: str | None = None
    modified_files: list[str] = []
    lines_added: int | None = None
    lines_removed: int | None = None

    try:
        with events_path.open() as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = payload.get("type")
                data = payload.get("data") or {}

                if event_type == "assistant.message":
                    content = str(data.get("content") or "").strip()
                    if content:
                        assistant_messages.append(content)
                    continue

                if event_type == "tool.execution_complete":
                    result = data.get("result") or {}
                    content = str(result.get("content") or "").strip()
                    if content:
                        tool_results.append(content)
                    continue

                if event_type == "session.task_complete":
                    task_complete_summary = str(data.get("summary") or "").strip() or None
                    continue

                if event_type == "session.shutdown":
                    code_changes = data.get("codeChanges") or {}
                    modified_files = [str(path) for path in code_changes.get("filesModified") or []]
                    lines_added = code_changes.get("linesAdded")
                    lines_removed = code_changes.get("linesRemoved")
                    continue
    except OSError:
        return None

    context_lines: list[str] = []
    if task_complete_summary:
        context_lines.append(f"Task-complete summary: {task_complete_summary}")
    if modified_files:
        context_lines.append("Modified files:")
        context_lines.extend(f"- {path}" for path in modified_files[:20])
    if lines_added is not None or lines_removed is not None:
        context_lines.append(
            f"Line changes: +{lines_added or 0} / -{lines_removed or 0}"
        )
    if assistant_messages:
        context_lines.append("Recent assistant messages:")
        context_lines.extend(f"- {message}" for message in assistant_messages[-5:])
    if tool_results:
        context_lines.append("Recent successful tool outputs:")
        context_lines.extend(f"- {result[:500]}" for result in tool_results[-8:])

    if not context_lines:
        return None
    return "\n".join(context_lines)


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


def _extract_json_with_fallback(raw: str, fallback_raw: str | None = None) -> object:
    try:
        return _extract_first_json_value(raw)
    except json.JSONDecodeError as exc:
        if fallback_raw:
            try:
                return _extract_first_json_value(fallback_raw)
            except json.JSONDecodeError:
                raise RuntimeError(f"Model did not return valid JSON:\n{raw}") from exc
        else:
            raise RuntimeError(f"Model did not return valid JSON:\n{raw}") from exc


def extract_structured_plan_output(raw: str, fallback_raw: str | None = None) -> PlanOutput:
    data = _extract_json_with_fallback(raw, fallback_raw)
    return PlanOutput.model_validate(data)


class LLMService:
    def __init__(self, stage: PipelineStage, repo_root: str | None = None) -> None:
        self.stage = stage
        self.repo_root = repo_root
        self.cfg = get_config()
        self.model = self.cfg.model_for_stage(stage)
        self.last_started_at_epoch: float | None = None
        self.last_session_events_path: Path | None = None

    def _should_use_tools_enabled_mode(self) -> bool:
        return (
            self.cfg.copilot_tool_mode == "tools-enabled"
            and self.stage in {PipelineStage.BUILD, PipelineStage.REWORK_IMPLEMENTATION}
        )

    def _complete_text_with_mode(self, prompt: str, *, tools_enabled: bool) -> str:
        args = ["copilot", "--model", self.model, "--stream", "on"]
        tool_mode = "tools-enabled" if tools_enabled else "text-only"
        if tools_enabled:
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

        self.last_started_at_epoch = time.time()
        self.last_session_events_path = None
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            cwd=self.repo_root,
        )
        started_at = time.monotonic()
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
                continue

            if stream_name == "stdout":
                stdout_chunks.append(chunk)
                if not tools_enabled:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
            else:
                stderr_chunks.append(chunk)
                if not tools_enabled:
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
            raise RuntimeError(
                f"Copilot subprocess failed during `{self.stage.value}`. "
                "Check Copilot session logs or the llm_request_failed event for details."
            )
        self.last_session_events_path = find_latest_copilot_session(
            model=self.model,
            repo_root=self.repo_root or os.getcwd(),
            started_after_epoch=self.last_started_at_epoch,
        )
        emit_event(
            "llm_request_finished",
            stage=self.stage,
            status="completed",
            evidence=[f"model={self.model}", f"elapsed_seconds={duration}"],
            conclusion="Model returned output for this stage.",
        )
        return output

    def complete_text(self, prompt: str) -> str:
        return self._complete_text_with_mode(
            prompt,
            tools_enabled=self._should_use_tools_enabled_mode(),
        )

    def _repair_structured_output(
        self,
        *,
        original_prompt: str,
        raw: str,
        fallback_raw: str | None,
        session_context: str,
    ) -> str:
        repair_prompt = f"""
The previous tools-enabled Copilot run completed work in the repository but did not emit the required final JSON payload.

Return strict JSON only. Do not call tools. Do not propose additional edits. Summarize the work already completed.

Original prompt:
{original_prompt}

Observed stdout from the previous run:
{raw or "<empty>"}

Observed assistant-message fallback:
{fallback_raw or "<empty>"}

Observed Copilot session trace:
{session_context}
""".strip()
        return self._complete_text_with_mode(repair_prompt, tools_enabled=False)

    def complete_structured(self, prompt: str, model_cls: Type[T]) -> T:
        raw = self.complete_text(prompt)
        fallback_raw = None
        if self.last_session_events_path is not None:
            fallback_raw = wait_for_latest_assistant_message(
                self.last_session_events_path,
                require_json=True,
            )
        if model_cls is PlanOutput:
            return extract_structured_plan_output(raw, fallback_raw)  # type: ignore[return-value]
        try:
            data = _extract_json_with_fallback(raw, fallback_raw)
        except RuntimeError:
            if self._should_use_tools_enabled_mode() and self.last_session_events_path is not None:
                session_context = extract_session_repair_context(self.last_session_events_path)
                if session_context:
                    repaired_raw = self._repair_structured_output(
                        original_prompt=prompt,
                        raw=raw,
                        fallback_raw=fallback_raw,
                        session_context=session_context,
                    )
                    data = _extract_json_with_fallback(repaired_raw)
                else:
                    raise
            else:
                raise
        return model_cls.model_validate(data)
