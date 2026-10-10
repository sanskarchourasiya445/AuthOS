"""Typed state representations for AuthOS bounded multi-agent workflow (Phase 8).

Adheres to agentic-architecture guidelines:
- Minimal, serializable, auditable state.
- Reducers for safe accumulation across node passes.
- Explicit budget and step telemetry tracking.
"""
from typing import Annotated, Any
from typing_extensions import TypedDict
import operator


class AgentCriterionState(TypedDict):
    """Per-criterion state tracked through retrieval, analysis, and verification."""
    criterion_id: str
    criterion_text: str
    evidence_expectation: str | None
    required_facts: list[str]
    min_duration_days: int | None
    query: str
    retrieval_round: int
    candidates: list[dict[str, Any]]
    proposal: dict[str, Any] | None
    verification_result: dict[str, Any] | None
    is_verified: bool
    missing_facts: list[str]
    detected_gaps: list[str]
    flags: list[str]
    status: str  # "PENDING", "ANALYZED", "VERIFIED", "RETRYING", "ABSTAINED", "FAILED"


class AgentWorkflowState(TypedDict):
    """Global workflow state managed across LangGraph nodes."""
    case_id: str
    patient_id: str
    policy_id: str
    run_id: str
    criteria: list[AgentCriterionState]
    current_index: int
    max_retries: int
    time_budget_sec: float
    start_time_monotonic: float
    total_retries: int
    steps_log: Annotated[list[str], operator.add]
    global_flags: Annotated[list[str], operator.add]
    workflow_status: str  # "RUNNING", "SUCCESS", "ABSTAINED", "PARTIAL", "FAILED"
    error_message: str | None
