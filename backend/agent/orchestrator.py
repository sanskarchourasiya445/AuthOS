"""Bounded Multi-Agent Orchestrator for AuthOS (Phase 8).

Implements:
- LangGraph-driven deterministic, bounded state graph.
- Hard time budgets, output size limits, and maximum retry caps (default <= 2).
- Structured output validation at each step.
- Deterministic verification boundary gate: agent outputs NEVER bypass deterministic rules.
- Complete separation of advisory agent proposals (AgentProposalModel) from authoritative records.
- Immutable audit logging without logging raw patient chart text.
- Human-in-the-loop guarantee: agent workflow NEVER finalizes or submits a prior authorization.
"""
from datetime import datetime, timezone
import logging
import time
import uuid
from typing import Any
from sqlalchemy.orm import Session

from langgraph.graph import END, StateGraph

from backend.agent.analysis_agent import CriterionAnalysisAgent
from backend.agent.retrieval_agent import EvidenceRetrievalAgent
from backend.agent.state import AgentCriterionState, AgentWorkflowState
from backend.db.models import (
    AgentProposalModel,
    AuditLogModel,
    CaseModel,
    DocumentModel,
    PolicyCriterionModel,
)
from backend.verification.engine import verify_criterion_evidence
from contracts.schemas import (
    AgentCriterionProposal,
    AgentExecutionMetadata,
    AgentWorkflowResponse,
    CriterionStatus,
    EvidenceItem,
)

logger = logging.getLogger("authos.agent.orchestrator")

DEFAULT_MAX_RETRIES = 2
DEFAULT_TIME_BUDGET_SEC = 10.0


class AgentOrchestrator:
    """Orchestrates multi-agent retrieval, clinical analysis, and deterministic verification."""

    def __init__(
        self,
        retrieval_agent: EvidenceRetrievalAgent | None = None,
        analysis_agent: CriterionAnalysisAgent | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        time_budget_sec: float = DEFAULT_TIME_BUDGET_SEC,
    ):
        self.retrieval_agent = retrieval_agent or EvidenceRetrievalAgent(top_k=4)
        self.analysis_agent = analysis_agent or CriterionAnalysisAgent()
        self.max_retries = min(max_retries, 3)  # Hard bound on retries
        self.time_budget_sec = time_budget_sec

    def build_graph(self, session: Session, raw_documents: list[dict[str, Any]]):
        """Construct the bounded LangGraph state graph."""
        graph = StateGraph(AgentWorkflowState)

        # 1. Retrieve Node
        def retrieve_node(state: AgentWorkflowState) -> dict[str, Any]:
            idx = state["current_index"]
            crit = state["criteria"][idx]

            # Budget / Timeout guard
            elapsed = time.monotonic() - state["start_time_monotonic"]
            if elapsed > state["time_budget_sec"]:
                crit["flags"].append("TIME_BUDGET_EXCEEDED")
                crit["status"] = "FAILED"
                return {
                    "criteria": state["criteria"],
                    "steps_log": [f"Criterion {crit['criterion_id']}: Retrieval skipped due to time budget"],
                    "global_flags": ["TIMEOUT_BUDGET_EXCEEDED"],
                }

            result = self.retrieval_agent.retrieve(
                session,
                criterion_id=crit["criterion_id"],
                criterion_text=crit["criterion_text"],
                patient_id=state["patient_id"],
                target_patient_id=state["patient_id"],
                evidence_expectation=crit.get("evidence_expectation"),
                missing_facts=crit.get("missing_facts") if crit["retrieval_round"] > 1 else None,
                retry_round=crit["retrieval_round"],
            )

            crit["candidates"] = result.candidates
            crit["query"] = result.query_used
            for f in result.flags:
                if f not in crit["flags"]:
                    crit["flags"].append(f)

            crit["status"] = "ABSTAINED" if result.abstained else "RETRIEVED"
            return {
                "criteria": state["criteria"],
                "steps_log": [
                    f"Criterion {crit['criterion_id']}: Retrieved {len(result.candidates)} candidates (round {crit['retrieval_round']})"
                ],
            }

        # 2. Analyze Node
        def analyze_node(state: AgentWorkflowState) -> dict[str, Any]:
            idx = state["current_index"]
            crit = state["criteria"][idx]

            # If retrieval failed/timed out, skip analysis
            if crit["status"] == "FAILED":
                return {"steps_log": [f"Criterion {crit['criterion_id']}: Analysis skipped"]}

            analysis = self.analysis_agent.analyze(
                criterion_id=crit["criterion_id"],
                criterion_text=crit["criterion_text"],
                patient_id=state["patient_id"],
                required_facts=crit["required_facts"],
                min_duration_days=crit["min_duration_days"],
                candidates=crit["candidates"],
                retrieval_round=crit["retrieval_round"],
            )

            crit["proposal"] = {
                "criterion_id": analysis.criterion_id,
                "proposed_status": analysis.proposed_status,
                "confidence": analysis.confidence,
                "evidence_quotes": [e.model_dump() for e in analysis.evidence_items],
                "missing_facts": analysis.missing_facts,
                "detected_gaps": analysis.detected_gaps,
                "uncertainty_rationale": analysis.uncertainty_rationale,
                "is_ai_generated": True,
                "flags": analysis.flags,
            }
            crit["missing_facts"] = analysis.missing_facts
            crit["detected_gaps"] = analysis.detected_gaps
            for f in analysis.flags:
                if f not in crit["flags"]:
                    crit["flags"].append(f)

            crit["status"] = "ANALYZED"
            return {
                "criteria": state["criteria"],
                "steps_log": [
                    f"Criterion {crit['criterion_id']}: Analyzed with proposed status {analysis.proposed_status.value}"
                ],
            }

        # 3. Deterministic Verification Gate Node
        def verify_gate_node(state: AgentWorkflowState) -> dict[str, Any]:
            idx = state["current_index"]
            crit = state["criteria"][idx]

            prop = crit.get("proposal")
            if not prop or crit["status"] == "FAILED":
                crit["is_verified"] = False
                return {"steps_log": [f"Criterion {crit['criterion_id']}: Verification gate skipped"]}

            candidate_evidence = prop.get("evidence_quotes", [])

            # Run pure deterministic verification
            verif_res = verify_criterion_evidence(
                criterion_id=crit["criterion_id"],
                criterion_text=crit["criterion_text"],
                patient_id=state["patient_id"],
                candidate_evidence=candidate_evidence,
                raw_documents=raw_documents,
                required_facts=crit["required_facts"],
                min_duration_days=crit["min_duration_days"],
            )

            # Check if verifier approved citations and agreed with proposal
            crit["verification_result"] = {
                "status": verif_res.status.value,
                "verified": verif_res.verified,
                "reason": verif_res.reason,
                "validator_flags": verif_res.validator_flags,
            }
            crit["is_verified"] = verif_res.verified

            # Collect flags from verifier
            for flag in verif_res.validator_flags:
                if flag not in crit["flags"]:
                    crit["flags"].append(flag)

            crit["status"] = "VERIFIED"
            return {
                "criteria": state["criteria"],
                "steps_log": [
                    f"Criterion {crit['criterion_id']}: Deterministic verification result: status={verif_res.status.value}, verified={verif_res.verified}"
                ],
            }

        # 4. Conditional Router
        def route_decision(state: AgentWorkflowState) -> str:
            idx = state["current_index"]
            crit = state["criteria"][idx]

            # Check timeout
            elapsed = time.monotonic() - state["start_time_monotonic"]
            if elapsed > state["time_budget_sec"]:
                return "advance"

            # If not verified and status is MISSING/AMBIGUOUS and retries remain, attempt corrective retry
            can_retry = (
                not crit["is_verified"]
                and crit["retrieval_round"] < state["max_retries"]
                and len(crit["missing_facts"]) > 0
                and "CROSS_PATIENT_VIOLATION_BLOCKED" not in crit["flags"]
            )

            if can_retry:
                return "retry"
            return "advance"

        # 5. Retry Node
        def retry_node(state: AgentWorkflowState) -> dict[str, Any]:
            idx = state["current_index"]
            crit = state["criteria"][idx]
            crit["retrieval_round"] += 1
            crit["status"] = "RETRYING"
            crit["flags"].append(f"RETRIED_ROUND_{crit['retrieval_round']}")
            return {
                "criteria": state["criteria"],
                "total_retries": state["total_retries"] + 1,
                "steps_log": [
                    f"Criterion {crit['criterion_id']}: Initiating corrective retry round {crit['retrieval_round']}"
                ],
            }

        # 6. Advance Criterion Node
        def advance_node(state: AgentWorkflowState) -> dict[str, Any]:
            next_idx = state["current_index"] + 1
            return {
                "current_index": next_idx,
                "steps_log": [f"Advanced to criterion index {next_idx}"],
            }

        # 7. Check if all criteria complete
        def should_continue_criteria(state: AgentWorkflowState) -> str:
            if state["current_index"] < len(state["criteria"]):
                return "retrieve"
            return "finalize"

        # 8. Finalize Node
        def finalize_node(state: AgentWorkflowState) -> dict[str, Any]:
            has_fails = any(c["status"] == "FAILED" for c in state["criteria"])
            all_abstained = all(
                c["proposal"] and c["proposal"]["proposed_status"] == CriterionStatus.MISSING
                for c in state["criteria"]
            )
            if has_fails:
                wf_status = "PARTIAL"
            elif all_abstained:
                wf_status = "ABSTAINED"
            else:
                wf_status = "SUCCESS"

            return {
                "workflow_status": wf_status,
                "steps_log": [f"Multi-agent workflow completed with status {wf_status}"],
            }

        # Register nodes in LangGraph
        graph.add_node("retrieve", retrieve_node)
        graph.add_node("analyze", analyze_node)
        graph.add_node("verify", verify_gate_node)
        graph.add_node("retry", retry_node)
        graph.add_node("advance", advance_node)
        graph.add_node("finalize", finalize_node)

        # Wire edges
        graph.set_entry_point("retrieve")
        graph.add_edge("retrieve", "analyze")
        graph.add_edge("analyze", "verify")

        graph.add_conditional_edges(
            "verify",
            route_decision,
            {
                "retry": "retry",
                "advance": "advance",
            },
        )
        graph.add_edge("retry", "retrieve")

        graph.add_conditional_edges(
            "advance",
            should_continue_criteria,
            {
                "retrieve": "retrieve",
                "finalize": "finalize",
            },
        )
        graph.add_edge("finalize", END)

        return graph.compile()

    def run_case_workflow(
        self,
        session: Session,
        *,
        case_id: str,
        actor_name: str = "SYSTEM_AGENT_ORCHESTRATOR",
    ) -> AgentWorkflowResponse:
        """Execute the multi-agent workflow for a prior authorization case."""
        t0 = time.monotonic()
        run_id = f"RUN-AGENT-{uuid.uuid4().hex[:12].upper()}"

        # 1. Fetch case and policy
        case = session.query(CaseModel).filter_by(case_id=case_id).first()
        if not case:
            raise ValueError(f"Case '{case_id}' was not found.")

        criteria_models = (
            session.query(PolicyCriterionModel)
            .filter_by(policy_id=case.policy_id)
            .order_by(PolicyCriterionModel.criterion_id)
            .all()
        )
        if not criteria_models:
            raise ValueError(f"No policy criteria found for policy '{case.policy_id}'.")

        # 2. Fetch raw documents for deterministic verification boundary
        raw_docs = session.query(DocumentModel).filter_by(patient_id=case.patient_id).all()
        raw_documents = [
            {
                "source_id": d.source_id,
                "patient_id": d.patient_id,
                "date": d.doc_date,
                "text": d.text,
            }
            for d in raw_docs
        ]

        # 3. Setup initial state
        crit_states: list[AgentCriterionState] = []
        for cm in criteria_models:
            from backend.verification.engine import has_keyword
            if has_keyword(cm.text, ["conservative", "physical therapy", "therapy"]):
                min_dur = 42
                reqs = ["Supervised physical therapy", "Duration >= 6 weeks"]
            elif has_keyword(cm.text, ["request", "order", "mri"]):
                min_dur = None
                reqs = ["Lumbar MRI requested"]
            elif has_keyword(cm.text, ["persistent", "symptom", "back pain", "low back"]):
                min_dur = None
                reqs = ["Low back pain"]
            else:
                min_dur = None
                reqs = []

            crit_states.append(
                {
                    "criterion_id": cm.criterion_id,
                    "criterion_text": cm.text,
                    "evidence_expectation": cm.evidence_expectation,
                    "required_facts": reqs,
                    "min_duration_days": min_dur,
                    "query": cm.text,
                    "retrieval_round": 1,
                    "candidates": [],
                    "proposal": None,
                    "verification_result": None,
                    "is_verified": False,
                    "missing_facts": [],
                    "detected_gaps": [],
                    "flags": [],
                    "status": "PENDING",
                }
            )

        initial_state: AgentWorkflowState = {
            "case_id": case_id,
            "patient_id": case.patient_id,
            "policy_id": case.policy_id,
            "run_id": run_id,
            "criteria": crit_states,
            "current_index": 0,
            "max_retries": self.max_retries,
            "time_budget_sec": self.time_budget_sec,
            "start_time_monotonic": t0,
            "total_retries": 0,
            "steps_log": ["Workflow initialized"],
            "global_flags": [],
            "workflow_status": "RUNNING",
            "error_message": None,
        }

        # 4. Compile and invoke graph
        compiled_graph = self.build_graph(session, raw_documents)
        final_state = compiled_graph.invoke(initial_state)

        duration_ms = round((time.monotonic() - t0) * 1000, 2)
        now_iso = datetime.now(timezone.utc).isoformat()

        # 5. Extract proposals and persist to AgentProposalModel
        proposals_out: list[AgentCriterionProposal] = []
        for crit in final_state["criteria"]:
            prop_data = crit.get("proposal") or {}
            ev_list = [EvidenceItem(**e) for e in prop_data.get("evidence_quotes", [])]

            prop_model = AgentCriterionProposal(
                criterion_id=crit["criterion_id"],
                proposed_status=prop_data.get("proposed_status", CriterionStatus.MISSING),
                confidence=prop_data.get("confidence", 0.0),
                evidence_quotes=ev_list,
                missing_facts=crit["missing_facts"],
                detected_gaps=crit["detected_gaps"],
                uncertainty_rationale=prop_data.get("uncertainty_rationale", "No proposal formulated."),
                retrieval_rounds=crit["retrieval_round"],
                is_verified_by_boundary=crit["is_verified"],
                boundary_feedback=crit.get("verification_result"),
                is_ai_generated=True,
                flags=crit["flags"],
            )
            proposals_out.append(prop_model)

            # Persist to separate AgentProposalModel (NEVER mutate CriterionResultModel)
            db_proposal = AgentProposalModel(
                case_id=case_id,
                run_id=run_id,
                criterion_id=crit["criterion_id"],
                proposed_status=prop_model.proposed_status.value,
                confidence=prop_model.confidence,
                uncertainty_rationale=prop_model.uncertainty_rationale,
                evidence_quotes=[e.model_dump() for e in prop_model.evidence_quotes],
                missing_facts=prop_model.missing_facts,
                detected_gaps=prop_model.detected_gaps,
                retrieval_rounds=prop_model.retrieval_rounds,
                is_verified=prop_model.is_verified_by_boundary,
                verification_feedback=prop_model.boundary_feedback,
                flags=prop_model.flags,
                created_at=datetime.now(timezone.utc),
            )
            session.add(db_proposal)

        # 6. Record immutable audit log entry (PHI-safe)
        audit_note = (
            f"Multi-agent run {run_id} completed: status={final_state['workflow_status']}, "
            f"criteria_count={len(proposals_out)}, retries={final_state['total_retries']}, latency_ms={duration_ms}."
        )
        audit_entry = AuditLogModel(
            case_id=case_id,
            criterion_id=None,
            action="AGENT_WORKFLOW_EXECUTED",
            note=audit_note,
            actor=f"AGENT_ORCHESTRATOR ({self.analysis_agent.provider_name})",
            created_at=datetime.now(timezone.utc),
        )
        session.add(audit_entry)
        session.flush()

        metadata = AgentExecutionMetadata(
            run_id=run_id,
            provider=self.analysis_agent.provider_name,
            is_external_llm=self.analysis_agent.is_external_llm,
            latency_ms=duration_ms,
            retries_attempted=final_state["total_retries"],
            max_retries_budget=self.max_retries,
            time_budget_sec=self.time_budget_sec,
            steps_executed=final_state["steps_log"],
            safety_flags=list(set(final_state["global_flags"])),
        )

        return AgentWorkflowResponse(
            case_id=case_id,
            patient_id=case.patient_id,
            policy_id=case.policy_id,
            run_id=run_id,
            status=final_state["workflow_status"],
            proposals=proposals_out,
            execution_metadata=metadata,
            created_at=now_iso,
        )
