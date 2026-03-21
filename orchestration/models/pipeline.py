from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, Field

from orchestration.models.issue import IssueMetadata
from orchestration.models.plan import PlanOutput
from orchestration.models.build import BuildOutput, RetryEntry, ExtraChangedFile
from orchestration.models.review import ReviewCycle, HumanDecision
from orchestration.models.rework import ReworkCycle
from orchestration.models.ship import ShipResult


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


StageName = Literal[
    "dispatch",
    "prepare",
    "plan",
    "human_approval_gate",
    "build",
    "agent_review",
    "escalation_review",
    "human_review",
    "rework_analysis",
    "rework_implementation",
    "ship",
    "done",
]

WorkflowStatus = Literal[
    "not_started",
    "running",
    "waiting_for_human",
    "needs_fixes",
    "approved",
    "shipped",
    "blocked",
    "failed",
]


class PrepareResult(BaseModel):
    base_branch: str = "main"
    branch_ready: bool = False
    branch_name: str
    task_file_bootstrapped: bool = False
    summary: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class PipelineState(BaseModel):
    issue: IssueMetadata
    current_stage: StageName = "dispatch"
    workflow_status: WorkflowStatus = "not_started"

    requested_entrypoint: Optional[StageName] = None
    execution_mode: Literal["step", "workflow"] = "workflow"

    prepare_result: Optional[PrepareResult] = None
    plan_output: Optional[PlanOutput] = None
    build_output: Optional[BuildOutput] = None

    review_cycles: List[ReviewCycle] = Field(default_factory=list)
    rework_cycles: List[ReworkCycle] = Field(default_factory=list)

    active_review_cycle_id: Optional[str] = None
    active_rework_cycle_id: Optional[str] = None

    human_gate_decisions: Dict[str, HumanDecision] = Field(default_factory=dict)

    ship_result: Optional[ShipResult] = None
    approved_extra_files: List[ExtraChangedFile] = Field(default_factory=list)
    blockers: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    retry_log: List[RetryEntry] = Field(default_factory=list)

    updated_at: datetime = Field(default_factory=utc_now)

    def next_review_id(self) -> str:
        return f"R{len(self.review_cycles) + 1}"

    def next_rework_id(self) -> str:
        return f"W{len(self.rework_cycles) + 1}"

    def touch(self) -> None:
        self.updated_at = utc_now()

    def add_retry(self, entry: RetryEntry) -> None:
        self.retry_log.append(entry)
        if self.build_output is not None:
            self.build_output.retry_entries.append(entry)

    @staticmethod
    def is_build_blocker(blocker: str) -> bool:
        return blocker == "Verification suite failed during build." or blocker.startswith(
            (
                "Out-of-scope changed files detected during build:",
                "Build validation failed:",
            )
        )

    def reset_build_state(self) -> None:
        previous_retries = []
        if self.build_output is not None:
            previous_retries = list(self.build_output.retry_entries)

        if previous_retries:
            self.retry_log = [entry for entry in self.retry_log if entry not in previous_retries]

        self.build_output = None
        self.blockers = [blocker for blocker in self.blockers if not self.is_build_blocker(blocker)]

    def approved_extra_file_paths(self) -> set[str]:
        return {item.path for item in self.approved_extra_files if item.path}

    def approve_extra_files(self, files: list[ExtraChangedFile]) -> None:
        merged = {item.path: item for item in self.approved_extra_files if item.path}
        for item in files:
            if not item.path:
                continue
            merged[item.path] = item.model_copy(update={"reason_source": "approved"})
        self.approved_extra_files = [merged[path] for path in sorted(merged)]

    def get_active_review_cycle(self) -> Optional[ReviewCycle]:
        if not self.active_review_cycle_id:
            return None
        for cycle in self.review_cycles:
            if cycle.review_id == self.active_review_cycle_id:
                return cycle
        return None

    def get_review_cycle(self, review_id: str | None) -> Optional[ReviewCycle]:
        if not review_id:
            return None
        for cycle in self.review_cycles:
            if cycle.review_id == review_id:
                return cycle
        return None

    def get_rework_context_review_cycle(self) -> Optional[ReviewCycle]:
        active = self.get_active_review_cycle()
        if active is None:
            return None
        if not active.extra_changed_files:
            return active

        active_index = None
        for idx, cycle in enumerate(self.review_cycles):
            if cycle.review_id == active.review_id:
                active_index = idx
                break

        if active_index is None:
            return active

        for cycle in reversed(self.review_cycles[:active_index]):
            if not cycle.extra_changed_files:
                return cycle
        return active

    def get_semantic_requirements(self) -> list[str]:
        requirements: list[str] = []

        if self.plan_output:
            requirements.extend(
                f"Acceptance criterion: {item}"
                for item in self.plan_output.acceptance_criteria
                if item and item.strip()
            )

        source_cycle: Optional[ReviewCycle] = None
        active_rework = self.get_active_rework_cycle()
        if active_rework is not None:
            source_cycle = self.get_review_cycle(active_rework.source_review_id)

        if source_cycle is None:
            source_cycle = self.get_rework_context_review_cycle() or self.get_active_review_cycle()

        if source_cycle and source_cycle.human_review:
            requirements.extend(
                f"Human response requirement: {item}"
                for item in source_cycle.human_review.response_requirements
                if item and item.strip()
            )
            requirements.extend(
                f"Human unresolved concern: {item}"
                for item in source_cycle.human_review.unresolved_comments
                if item and item.strip()
            )

        deduped: list[str] = []
        seen: set[str] = set()
        for item in requirements:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
        return deduped

    def get_active_rework_cycle(self) -> Optional[ReworkCycle]:
        if not self.active_rework_cycle_id:
            return None
        for cycle in self.rework_cycles:
            if cycle.rework_cycle_id == self.active_rework_cycle_id:
                return cycle
        return None
