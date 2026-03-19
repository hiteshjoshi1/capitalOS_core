from __future__ import annotations

import json
import subprocess
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMService:
    """
    Thin adapter around the existing Copilot CLI usage.
    Prompts require strict JSON output and are validated by Pydantic.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    def complete_text(self, prompt: str) -> str:
        proc = subprocess.run(
            ["copilot", "--model", self.model, "-p", prompt, "--no-color", "--no-ask-user"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
        return proc.stdout.strip()

    def complete_structured(self, prompt: str, model_cls: Type[T]) -> T:
        raw = self.complete_text(prompt)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Model did not return valid JSON:\n{raw}") from exc
        return model_cls.model_validate(data)