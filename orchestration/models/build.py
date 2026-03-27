from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

from orchestration.models.verification import VerificationEvidence


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RetryEntry(BaseModel):
    label: str
    attempt: int
    max_attempts: int
    command: str
    exit_code: int
    classification: str  # code | infra
    failure_signature: Optional[str] = None
    failure_log_path: Optional[str] = None
    notes: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ExtraChangedFile(BaseModel):
    path: str
    reason: str = ""
    reason_source: str = "unknown"  # builder | inferred | unknown | approved


class BuildRetryRequest(BaseModel):
    summary: str
    why_more_retries_help: str = ""
    proposed_new_strategy: str = ""
    latest_failures: List[str] = Field(default_factory=list)
    requested_retry_count: int = 0
    valid_reason: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class BuildOutput(BaseModel):
    summary: str
    changed_files: List[str] = Field(default_factory=list)
    extra_changed_files: List[ExtraChangedFile] = Field(default_factory=list)
    completed_checklist_item_ids: List[str] = Field(default_factory=list)
    implementation_notes: List[str] = Field(default_factory=list)
    verification: Optional[VerificationEvidence] = None
    retry_entries: List[RetryEntry] = Field(default_factory=list)
    retry_request: Optional[BuildRetryRequest] = None
    builder_model: Optional[str] = None
    generated_at: datetime = Field(default_factory=utc_now)
