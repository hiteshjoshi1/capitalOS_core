from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from orchestration.models.stage import PipelineStage


def _load_env_files() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)
    load_dotenv(repo_root / ".ai-models.env", override=False)


class ModelRoutingConfig(BaseModel):
    # --- Unified pipeline provider config ---
    provider: Literal["copilot", "codex"] = "copilot"
    model: str = Field(default="gpt-5.3-codex")
    reasoning_effort: Literal["low", "medium", "high", "xhigh"] | None = None
    longrun_timeout_minutes: int = Field(default=120, ge=1)
    enable_post_pr_human_review: bool = True
    require_pre_ship_human_on_high_risk: bool = True
    enable_caffeinate: bool = True
    inactivity_timeout_minutes: int = Field(default=30, ge=1)
    repair_enabled: bool = True

    planner_model: str = Field(default="claude-opus-4.6")
    builder_model: str = Field(default="gpt-5.3-codex")
    reviewer_model: str = Field(default="claude-sonnet-4.6")
    review_escalation_model: str = Field(default="claude-opus-4.6")
    copilot_tool_mode: Literal["text-only", "tools-enabled"] = "tools-enabled"

    max_retries: int = Field(default=3, ge=1)
    max_rework_cycles: int = Field(default=2, ge=1)
    codex_timeout_minutes: int = Field(default=60, ge=1)
    codex_sandbox_mode: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"
    build_max_autopilot_continues: int = Field(default=12, ge=1)

    create_pr_on_ship: bool = False
    base_branch: str = "main"
    allowed_aux_files: list[str] = Field(default_factory=list)

    # --- Backward-compat aliases (read-only) ---
    @property
    def pipeline_version(self) -> str:
        return "v3"

    @property
    def v3_provider(self) -> str:
        return self.provider

    @property
    def v3_model(self) -> str:
        return self.model

    @property
    def v3_reasoning_effort(self) -> str | None:
        return self.reasoning_effort

    @property
    def v3_longrun_timeout_minutes(self) -> int:
        return self.longrun_timeout_minutes

    @property
    def v3_enable_post_pr_human_review(self) -> bool:
        return self.enable_post_pr_human_review

    @property
    def v3_require_pre_ship_human_on_high_risk(self) -> bool:
        return self.require_pre_ship_human_on_high_risk

    @property
    def v3_enable_caffeinate(self) -> bool:
        return self.enable_caffeinate

    @property
    def v3_inactivity_timeout_minutes(self) -> int:
        return self.inactivity_timeout_minutes

    @property
    def v3_repair_enabled(self) -> bool:
        return self.repair_enabled

    @classmethod
    def from_env(cls) -> "ModelRoutingConfig":
        _load_env_files()

        raw_aux = os.getenv("ALLOWED_AUX_FILES", "")
        aux_files = [x.strip() for x in raw_aux.replace(";", ",").split(",") if x.strip()]

        # Accept both new names (PROVIDER, MODEL) and legacy v3-prefixed names
        return cls(
            provider=os.getenv("PROVIDER", os.getenv("V3_PROVIDER", "copilot")),
            model=os.getenv("MODEL", os.getenv("V3_MODEL", os.getenv("BUILD_MODEL", "gpt-5.3-codex"))),
            reasoning_effort=os.getenv("REASONING_EFFORT", os.getenv("V3_REASONING_EFFORT")),
            longrun_timeout_minutes=int(os.getenv("LONGRUN_TIMEOUT_MINUTES", os.getenv("V3_LONGRUN_TIMEOUT_MINUTES", "120"))),
            enable_post_pr_human_review=os.getenv("ENABLE_POST_PR_HUMAN_REVIEW", os.getenv("V3_ENABLE_POST_PR_HUMAN_REVIEW", "1")) == "1",
            require_pre_ship_human_on_high_risk=os.getenv("REQUIRE_PRE_SHIP_HUMAN_ON_HIGH_RISK", os.getenv("V3_REQUIRE_PRE_SHIP_HUMAN_ON_HIGH_RISK", "1")) == "1",
            enable_caffeinate=os.getenv(
                "ENABLE_CAFFEINATE",
                os.getenv("V3_ENABLE_CAFFEINATE", "1"),
            ) == "1",
            inactivity_timeout_minutes=int(os.getenv("INACTIVITY_TIMEOUT_MINUTES", os.getenv("V3_INACTIVITY_TIMEOUT_MINUTES", "30"))),
            repair_enabled=os.getenv("REPAIR_ENABLED", os.getenv("V3_REPAIR_ENABLED", "1")) == "1",
            planner_model=os.getenv("PLAN_MODEL", "claude-opus-4.6"),
            builder_model=os.getenv("BUILD_MODEL", "claude-sonnet-4.6"),
            reviewer_model=os.getenv("REVIEW_MODEL", "claude-sonnet-4.6"),
            review_escalation_model=os.getenv("REVIEW_ESCALATION_MODEL", "claude-opus-4.6"),
            copilot_tool_mode=os.getenv("COPILOT_TOOL_MODE", "tools-enabled"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            max_rework_cycles=int(os.getenv("MAX_REWORK_CYCLES", "2")),
            codex_timeout_minutes=int(os.getenv("CODEX_TIMEOUT_MINUTES", "60")),
            codex_sandbox_mode=os.getenv("CODEX_SANDBOX_MODE", "workspace-write"),
            build_max_autopilot_continues=int(os.getenv("BUILD_MAX_AUTOPILOT_CONTINUES", "12")),
            create_pr_on_ship=os.getenv("CREATE_PR_ON_SHIP", "0") == "1",
            base_branch=os.getenv("BASE_BRANCH", "main"),
            allowed_aux_files=aux_files,
        )

    def model_for_stage(self, stage: PipelineStage) -> str:
        if stage == PipelineStage.PLAN:
            return self.planner_model

        if stage in {
            PipelineStage.BUILD,
            PipelineStage.AGENT_RUN,
            PipelineStage.DETERMINISTIC_GATES,
            PipelineStage.REWORK_ANALYSIS,
            PipelineStage.REWORK_IMPLEMENTATION,
        }:
            return self.builder_model

        if stage == PipelineStage.AGENT_REVIEW:
            return self.reviewer_model

        if stage == PipelineStage.ESCALATION_REVIEW:
            return self.review_escalation_model

        raise ValueError(
            f"Stage {stage.value} does not have an associated LLM model. "
            "This stage should not use LLMService."
        )


@lru_cache(maxsize=1)
def get_config() -> ModelRoutingConfig:
    return ModelRoutingConfig.from_env()
