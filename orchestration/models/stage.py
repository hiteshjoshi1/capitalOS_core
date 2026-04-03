from enum import Enum


class PipelineStage(str, Enum):
    PREPARE = "prepare"
    PLAN = "plan"
    HUMAN_APPROVAL_GATE = "human_approval_gate"
    BUILD = "build"
    AGENT_RUN = "agent_run"
    DETERMINISTIC_GATES = "deterministic_gates"
    AGENT_REVIEW = "agent_review"
    ESCALATION_REVIEW = "escalation_review"
    HUMAN_REVIEW = "human_review"
    REWORK_ANALYSIS = "rework_analysis"
    REWORK_IMPLEMENTATION = "rework_implementation"
    SHIP = "ship"
