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
    planner_model: str = Field(default="claude-opus-4.6")
    builder_model: str = Field(default="gpt-5.3-codex")
    reviewer_model: str = Field(default="claude-sonnet-4.6")
    review_escalation_model: str = Field(default="claude-opus-4.6")
    copilot_tool_mode: Literal["text-only", "tools-enabled"] = "tools-enabled"

    max_retries: int = Field(default=3, ge=1)
    codex_timeout_minutes: int = Field(default=60, ge=1)
    build_max_autopilot_continues: int = Field(default=12, ge=1)

    create_pr_on_ship: bool = False
    base_branch: str = "main"
    allowed_aux_files: list[str] = Field(default_factory=list)

    @classmethod
    def from_env(cls) -> "ModelRoutingConfig":
        _load_env_files()

        raw_aux = os.getenv("ALLOWED_AUX_FILES", "")
        aux_files = [x.strip() for x in raw_aux.replace(";", ",").split(",") if x.strip()]

        return cls(
            planner_model=os.getenv("PLAN_MODEL", "claude-opus-4.6"),
            builder_model=os.getenv("BUILD_MODEL", "claude-sonnet-4.6"),
            reviewer_model=os.getenv("REVIEW_MODEL", "claude-sonnet-4.6"),
            review_escalation_model=os.getenv("REVIEW_ESCALATION_MODEL", "claude-opus-4.6"),
            copilot_tool_mode=os.getenv("COPILOT_TOOL_MODE", "tools-enabled"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            codex_timeout_minutes=int(os.getenv("CODEX_TIMEOUT_MINUTES", "60")),
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
