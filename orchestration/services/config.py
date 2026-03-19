from __future__ import annotations

import os
from functools import lru_cache
from pydantic import BaseModel, Field


class ModelRoutingConfig(BaseModel):
    planner_model: str = Field(default="planner")
    builder_model: str = Field(default="builder")
    reviewer_model: str = Field(default="reviewer")
    review_escalation_model: str = Field(default="reviewer_escalation")

    max_retries: int = Field(default=3, ge=1)
    codex_timeout_minutes: int = Field(default=60, ge=1)
    build_max_autopilot_continues: int = Field(default=12, ge=1)

    create_pr_on_ship: bool = False
    base_branch: str = "main"
    allowed_aux_files: list[str] = Field(default_factory=list)

    @classmethod
    def from_env(cls) -> "ModelRoutingConfig":
        raw_aux = os.getenv("ALLOWED_AUX_FILES", "")
        aux_files = [x.strip() for x in raw_aux.replace(";", ",").split(",") if x.strip()]
        return cls(
            planner_model=os.getenv("PLAN_MODEL", "planner"),
            builder_model=os.getenv("BUILD_MODEL", "builder"),
            reviewer_model=os.getenv("REVIEW_MODEL", "reviewer"),
            review_escalation_model=os.getenv("REVIEW_ESCALATION_MODEL", "reviewer_escalation"),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            codex_timeout_minutes=int(os.getenv("CODEX_TIMEOUT_MINUTES", "60")),
            build_max_autopilot_continues=int(os.getenv("BUILD_MAX_AUTOPILOT_CONTINUES", "12")),
            create_pr_on_ship=os.getenv("CREATE_PR_ON_SHIP", "0") == "1",
            base_branch=os.getenv("BASE_BRANCH", "main"),
            allowed_aux_files=aux_files,
        )


@lru_cache(maxsize=1)
def get_config() -> ModelRoutingConfig:
    return ModelRoutingConfig.from_env()