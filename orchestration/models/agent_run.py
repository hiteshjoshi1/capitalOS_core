from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from orchestration.models.build import ExtraChangedFile
from orchestration.models.plan import PlanChecklistItem


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


AgentCriteriaStatus = Literal["pass", "fail", "partial"]


class AcceptanceCriteriaCheck(BaseModel):
    criterion: str
    status: AgentCriteriaStatus = "partial"
    evidence: str = ""


class CommandExecutionCheck(BaseModel):
    command: str
    status: Literal["pass", "fail", "skip"] = "pass"
    evidence: str = ""


class AgentRunOutput(BaseModel):
    summary: str

    plan_summary: str = ""
    architecture_decisions: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    planned_paths: List[str] = Field(default_factory=list)
    checklist: List[PlanChecklistItem] = Field(default_factory=list)

    changed_files: List[str] = Field(default_factory=list)
    extra_changed_files: List[ExtraChangedFile] = Field(default_factory=list)
    implementation_notes: List[str] = Field(default_factory=list)
    verification_commands_run: List[CommandExecutionCheck] = Field(default_factory=list)
    unresolved_failures: List[str] = Field(default_factory=list)

    acceptance_criteria_checks: List[AcceptanceCriteriaCheck] = Field(default_factory=list)
    semantic_intent_achieved: bool = False
    risk_flags: List[str] = Field(default_factory=list)

    provider: Optional[str] = None
    model_name: Optional[str] = None
    generated_at: datetime = Field(default_factory=utc_now)
