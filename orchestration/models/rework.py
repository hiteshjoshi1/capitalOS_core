from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReworkAnswerEntry(BaseModel):
    reviewer_finding: str
    human_comment: str
    root_cause: str
    change_made: str = ""
    verification_performed: str = ""
    status: Literal["planned", "needs_input", "blocked", "resolved", "partial"]


class ReworkAnalysis(BaseModel):
    rework_cycle_id: str
    review_id: str
    root_cause: str
    findings_addressed: List[str] = Field(default_factory=list)
    planned_changes: List[str] = Field(default_factory=list)
    validation_plan: List[str] = Field(default_factory=list)
    unresolved_assumptions: List[str] = Field(default_factory=list)
    answer_matrix: List[ReworkAnswerEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class ReworkImplementationResult(BaseModel):
    rework_cycle_id: str
    review_id: str
    summary: str
    changed_files: List[str] = Field(default_factory=list)
    verification_summary: str = ""
    completed: bool = True
    created_at: datetime = Field(default_factory=utc_now)


class ReworkCycle(BaseModel):
    rework_cycle_id: str
    source_review_id: str
    analysis: Optional[ReworkAnalysis] = None
    implementation: Optional[ReworkImplementationResult] = None
    status: Literal["analysis_complete", "implementation_complete", "blocked"] = "analysis_complete"
    created_at: datetime = Field(default_factory=utc_now)