from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


VerificationStatus = Literal["pass", "fail", "skip"]


class VerificationCommandResult(BaseModel):
    name: str
    command: str
    status: VerificationStatus
    exit_code: int
    output_excerpt: str = ""
    artifact_paths: List[str] = Field(default_factory=list)
    failure_log_path: Optional[str] = None


class VerificationEvidence(BaseModel):
    suite_name: str = "default"
    results: List[VerificationCommandResult] = Field(default_factory=list)
    any_failures: bool = False
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def summary(self) -> str:
        if not self.results:
            return "No verification commands executed."
        return "\n".join(
            f"- {r.name}: {r.status.upper()} (exit {r.exit_code})"
            for r in self.results
        )