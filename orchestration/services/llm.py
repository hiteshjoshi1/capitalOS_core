from __future__ import annotations

import json
import re
import subprocess
from typing import Type, TypeVar

from pydantic import BaseModel

from orchestration.models.plan import PlanOutput
from orchestration.models.stage import PipelineStage
from orchestration.services.config import get_config

T = TypeVar("T", bound=BaseModel)


def _extract_first_json_value(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    fenced_match = re.search(r"```json\s*(\{.*?\}|\[.*?\])\s*```", raw, re.DOTALL | re.IGNORECASE)
    if fenced_match:
        return json.loads(fenced_match.group(1))

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
        args = ["copilot", "--model", self.model]
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

        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=self.repo_root,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout.strip()

    def complete_structured(self, prompt: str, model_cls: Type[T]) -> T:
        raw = self.complete_text(prompt)
        if model_cls is PlanOutput:
            return extract_structured_plan_output(raw)  # type: ignore[return-value]
        try:
            data = _extract_first_json_value(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model did not return valid JSON:\n{raw}") from exc
        return model_cls.model_validate(data)
